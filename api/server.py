"""
api/server.py
--------------
FastAPI REST + SSE interface for Agent_head.

Endpoints
---------
  GET  /health                         → liveness check
  GET  /sessions                       → list all known session IDs
  POST /sessions                       → create (or resume) a session
  GET  /sessions/{session_id}          → session metadata & message count
  DELETE /sessions/{session_id}        → clear session history
  POST /sessions/{session_id}/chat     → send a message, get SSE stream back
  POST /sessions/{session_id}/shutdown → tear down the live agent for a session

SSE event types (streamed during /chat)
--------------------------------------
  {"type": "tool_call",   "name": "...", "args": {...}}
  {"type": "tool_result", "name": "...", "content": "..."}
  {"type": "token",       "content": "..."}   ← intermediate AI text
  {"type": "done",        "content": "..."}   ← final answer
  {"type": "error",       "content": "..."}   ← something went wrong

Usage
-----
  python -m api.server                 (default: http://0.0.0.0:8000)
  python -m api.server --port 9000 --config /path/to/config.yaml
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
import warnings
from contextlib import AsyncExitStack
from typing import AsyncGenerator, Literal

warnings.filterwarnings("ignore", category=DeprecationWarning)

# ── Force UTF-8 on Windows ───────────────────────────────────────────────────
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# Ensure `core/` imports resolve when running from project root or as module
import os, sys as _sys
_sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config_loader import load_config, AppConfig
from core.mcp_loader import load_mcp_server_tools
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.WARNING, stream=sys.stderr,
                    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")


# ─────────────────────────────────────────────────────────────────────────────
# Per-session agent runtime
# ─────────────────────────────────────────────────────────────────────────────

class AgentSession:
    """
    One live agent per session_id.
    Keeps MCP tool connections open across multiple chat turns.
    """

    def __init__(self, session_id: str, config: AppConfig):
        self.session_id = session_id
        self.config = config
        self.graph = None
        self.backend = None          # memory backend
        self.summarizer = None
        self.session_manager = None
        self.conversation_history: list = []
        self.current_summary: str = ""
        self.known_global_facts: list[str] = []
        self.known_private_facts: list[str] = []
        self._stack = None
        self._ready = False
        self._lock = asyncio.Lock()   # serialise concurrent chat calls
        self._shutdown_event = asyncio.Event()
        self._boot_complete = asyncio.Event()
        self._bg_task = None

    async def boot(self) -> None:
        """Starts the background task that manages MCP connections."""
        if self._bg_task is not None:
            return
        self._bg_task = asyncio.create_task(self._run_stack())
        await self._boot_complete.wait()

    async def _run_stack(self) -> None:
        """Connect all tools, build the graph, load history. Runs in a dedicated task."""
        from langgraph.prebuilt import create_react_agent, ToolNode
        from core.llm import get_llm

        try:
            async with AsyncExitStack() as stack:
                self._stack = stack
                all_tools = []

                # ── Worker agents ──────────────────────────────────────────────────
                for wa in self.config.worker_agents:
                    try:
                        tools = await load_mcp_server_tools(
                            self._stack,
                            command=wa.command, args=wa.args, env=wa.env or None,
                            description_override=wa.description,
                        )
                        all_tools.extend(tools)
                        logger.info("[Session %s] Worker '%s' → %s", self.session_id, wa.name, [t.name for t in tools])
                    except Exception as exc:
                        logger.warning("[Session %s] Worker '%s' failed: %s", self.session_id, wa.name, exc)

                # ── Direct MCP tool servers ────────────────────────────────────────
                for mc in self.config.mcp_clients:
                    try:
                        tools = await load_mcp_server_tools(
                            self._stack,
                            transport=mc.transport, url=mc.url,
                            headers=mc.headers or None,
                            command=mc.command, args=mc.args, env=mc.env or None,
                        )
                        all_tools.extend(tools)
                        logger.info("[Session %s] MCP '%s' → %s", self.session_id, mc.name, [t.name for t in tools])
                    except Exception as exc:
                        logger.warning("[Session %s] MCP '%s' failed: %s", self.session_id, mc.name, exc)

                # ── Memory tools ───────────────────────────────────────────────────
                if self.config.memory.enabled:
                    from core.memory import get_backend as _get_backend
                    from pathlib import Path as _Path
                    from langchain_core.tools import tool as lc_tool

                    _mem_dir = _Path(self.config.memory.memory_dir)
                    if not _mem_dir.is_absolute():
                        _mem_dir = _Path(__file__).parent.parent / self.config.memory.memory_dir
                    try:
                        self.backend = _get_backend(
                            backend_type=self.config.memory.backend,
                            memory_dir=_mem_dir,
                            max_save_length=self.config.memory.max_save_length,
                            rag_server_cfg=self.config.memory.rag_server,
                        )

                        _backend = self.backend
                        _sid = self.session_id

                        @lc_tool
                        def memory_search(query: str, category: Literal["all", "history", "facts"] = "all") -> str:
                            """Search long-term memory for past tasks and results."""
                            return _backend.search(query, category=category, session_id=_sid)

                        @lc_tool
                        def memory_save(fact: str) -> str:
                            """Save an important fact to long-term memory for future sessions."""
                            return _backend.save_fact(fact)

                        all_tools.extend([memory_search, memory_save])
                    except Exception as exc:
                        logger.warning("[Session %s] Memory failed: %s", self.session_id, exc)

                # ── Image tools (read, save, screenshot, OCR) ─────────────────────
                try:
                    from core.image_tools import get_image_tools
                    _img_cfg = self.config.image_tools
                    _img_tools = get_image_tools(
                        enabled=_img_cfg.enabled,
                        enable_save=_img_cfg.enable_save,
                        enable_screenshot=_img_cfg.enable_screenshot,
                        enable_ocr=_img_cfg.enable_ocr,
                        screenshot_dir=_img_cfg.screenshot_dir,
                    )
                    if _img_tools:
                        all_tools.extend(_img_tools)
                        logger.info("[Session %s] Image → %s", self.session_id, [t.name for t in _img_tools])
                except Exception as exc:
                    logger.warning("[Session %s] Image tools failed: %s", self.session_id, exc)

                # ── Audio tools (transcribe, TTS, save, record) ───────────────────
                try:
                    from core.audio_tools import get_audio_tools
                    _aud_cfg = self.config.audio_tools
                    _aud_tools = get_audio_tools(
                        enabled=_aud_cfg.enabled,
                        enable_transcribe=_aud_cfg.enable_transcribe,
                        enable_tts=_aud_cfg.enable_tts,
                        enable_save=_aud_cfg.enable_save,
                        enable_record=_aud_cfg.enable_record,
                        enable_play=_aud_cfg.enable_play,
                        enable_speak=_aud_cfg.enable_speak,
                        audio_dir=_aud_cfg.audio_dir,
                    )
                    if _aud_tools:
                        all_tools.extend(_aud_tools)
                        logger.info("[Session %s] Audio → %s", self.session_id, [t.name for t in _aud_tools])
                except Exception as exc:
                    logger.warning("[Session %s] Audio tools failed: %s", self.session_id, exc)

                # ── Skills (catalog + always-inject + load_skill tool) ─────────────────
                self._skills_prompt = ""
                self._session_skills = []
                try:
                    from core.skill_loader import (
                        discover_skills, build_catalog_block,
                        load_skill_content, make_load_skill_tool,
                    )
                    _sk_cfg = self.config.skills
                    if _sk_cfg.enabled:
                        self._session_skills = discover_skills(_sk_cfg.skills_dirs)
                        if self._session_skills:
                            all_tools.append(make_load_skill_tool(self._session_skills))
                            logger.info(
                                "[Session %s] Skills: %s",
                                self.session_id, [s.name for s in self._session_skills],
                            )
                            self._skills_prompt = build_catalog_block(self._session_skills)
                            for sname in _sk_cfg.always_inject:
                                body = load_skill_content(sname, self._session_skills)
                                self._skills_prompt += f"\n\n{body}"
                except Exception as exc:
                    logger.warning("[Session %s] Skills failed: %s", self.session_id, exc)

                # ── Build graph ────────────────────────────────────────────────────
                llm = get_llm(self.config.model)
                tool_node = ToolNode(all_tools, handle_tool_errors=True)
                self.graph = create_react_agent(model=llm, tools=tool_node)

                # ── Summarizer ─────────────────────────────────────────────────────
                from core.conversation_summarizer import ConversationSummarizer
                if self.config.summarizer.enabled:
                    self.summarizer = ConversationSummarizer(self.config.summarizer, self.config.model)

                # ── Load persisted conversation history ────────────────────────────
                if self.session_id:
                    cfg = self.config.chat_history
                    if cfg.backend == "sqlite":
                        from core.history_sqlite import SqliteConversationHistory
                        from pathlib import Path
                        _db = Path(cfg.connection_string)
                        if not _db.is_absolute():
                            _mem_dir2 = Path(self.config.memory.memory_dir)
                            if not _mem_dir2.is_absolute():
                                _mem_dir2 = Path(__file__).parent.parent / self.config.memory.memory_dir
                            _db = _mem_dir2 / cfg.connection_string
                        self.session_manager = SqliteConversationHistory(db_path=_db)
                        history = self.session_manager.load_session(self.session_id)
                        if history:
                            self.conversation_history = history
                            logger.info("[Session %s] Resumed: %d messages", self.session_id, len(history))

                if not self.conversation_history:
                    # Prepend skills catalog + always-inject if available
                    _sp = self.config.agent.system_prompt
                    _skills_p = getattr(self, "_skills_prompt", "")
                    if _skills_p:
                        _sp = _skills_p + "\n\n" + _sp
                    self.conversation_history = [SystemMessage(content=_sp)]

                self._ready = True
                self._boot_complete.set()
                await self._shutdown_event.wait()
                
        except Exception as exc:
            logger.exception("[Session %s] Background task crashed", self.session_id)
        finally:
            self._ready = False
            self._boot_complete.set()

    async def shutdown(self) -> None:
        """Tear down MCP connections."""
        self._shutdown_event.set()
        if self._bg_task:
            await self._bg_task
            self._bg_task = None
        self._ready = False

    async def chat(self, user_message: str) -> AsyncGenerator[str, None]:
        """
        Process one user turn, yielding SSE-formatted JSON strings.
        Serialises concurrent calls with a lock.
        """
        async with self._lock:
            # ── /skillname slash-command injection ──────────────────────────────
            task_text = user_message
            _session_skills = getattr(self, "_session_skills", [])
            if (
                _session_skills
                and self.config.skills.enabled
                and self.config.skills.prompt_skill_trigger
            ):
                try:
                    from core.skill_loader import extract_slash_commands, load_skill_content
                    task_text, _triggered = extract_slash_commands(task_text, _session_skills)
                    for _sk in _triggered:
                        _full = load_skill_content(_sk.name, _session_skills)
                        task_text = f"[Skill Loaded: {_sk.name}]\n{_full}\n\n" + task_text
                        logger.info("[Session %s] Skill triggered: %s", self.session_id, _sk.name)
                except Exception as _ske:
                    logger.warning("[Session %s] Skill slash-cmd error: %s", self.session_id, _ske)

            # Auto-inject RAG context
            if self.config.memory.enabled and self.backend and self.config.memory.auto_feed_top_k > 0:
                try:
                    ctx = self.backend.search(
                        user_message,
                        category=self.config.memory.auto_feed_category,
                        session_id=self.session_id,
                    )
                    if ctx.strip() and "No relevant" not in ctx:
                        ctx = ctx[:4000]
                        task_text = f"[Relevant Past Memory]\n{ctx}\n\n[User Task]\n{user_message}"
                except Exception:
                    pass

            self.conversation_history.append(HumanMessage(content=task_text))
            final_answer = ""
            last_event = None

            try:
                async for event in self.graph.astream(
                    {"messages": self.conversation_history}, stream_mode="values"
                ):
                    last_event = event
                    last_msg = event["messages"][-1]

                    if isinstance(last_msg, AIMessage):
                        # Tool dispatch
                        if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                            for tc in last_msg.tool_calls:
                                yield _sse({"type": "tool_call",
                                            "name": tc.get("name", ""),
                                            "args": tc.get("args", {})})
                        # Intermediate or final text
                        if last_msg.content:
                            content = _extract_text(last_msg.content)
                            yield _sse({"type": "token", "content": content})
                            final_answer = content

                    elif isinstance(last_msg, ToolMessage):
                        content = _extract_text(last_msg.content)
                        tool_name = getattr(last_msg, "name", None) or "tool"
                        yield _sse({"type": "tool_result",
                                    "name": tool_name,
                                    "content": content[:2000]})   # truncate for wire

            except Exception as exc:
                logger.exception("[Session %s] Graph stream error", self.session_id)
                yield _sse({"type": "error", "content": str(exc)})
                # Pop failed user message so history stays consistent
                if self.conversation_history and isinstance(self.conversation_history[-1], HumanMessage):
                    self.conversation_history.pop()
                yield _sse({"type": "done", "content": ""})
                return

            # Capture full history from last event
            if last_event:
                self.conversation_history = list(last_event["messages"])

            # Persist session
            if self.session_manager:
                self.session_manager.save_session(self.session_id, self.conversation_history)

            # Rolling summarisation
            if self.summarizer and self.summarizer.should_summarize(self.conversation_history):
                try:
                    result = await self.summarizer.summarize(
                        history=self.conversation_history,
                        prev_summary=self.current_summary,
                        known_global_facts=self.known_global_facts,
                        known_private_facts=self.known_private_facts,
                    )
                    self.conversation_history = result.trimmed_history
                    self.current_summary = result.summary
                    self.known_global_facts = result.global_facts
                    self.known_private_facts = result.private_facts

                    if self.session_manager:
                        self.session_manager.save_session(self.session_id, self.conversation_history)

                    if self.config.summarizer.save_to_memory and self.backend:
                        self.backend.save(
                            job_id=f"summary_{int(time.time())}",
                            task="Rolling Session Summary",
                            summary=result.summary,
                            session_id=self.session_id,
                        )
                        for fact in result.new_global_facts:
                            self.backend.save_fact(fact, is_global=True)
                        for fact in result.new_private_facts:
                            self.backend.save_fact(fact, is_global=False, session_id=self.session_id)
                except Exception as exc:
                    logger.warning("[Session %s] Summariser failed: %s", self.session_id, exc)

            yield _sse({"type": "done", "content": final_answer})


# ─────────────────────────────────────────────────────────────────────────────
# Global registry of live sessions
# ─────────────────────────────────────────────────────────────────────────────

_sessions: dict[str, AgentSession] = {}
_config: AppConfig | None = None


def _get_config() -> AppConfig:
    global _config
    if _config is None:
        _config = load_config()
    return _config


async def _get_or_create_session(session_id: str) -> AgentSession:
    if session_id not in _sessions:
        sess = AgentSession(session_id, _get_config())
        await sess.boot()
        _sessions[session_id] = sess
    return _sessions[session_id]


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI app
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Agent_head API",
    description="REST + SSE interface for the autonomous orchestrator agent.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],    # tighten in production
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request / response models ─────────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    session_id: str

class ChatRequest(BaseModel):
    message: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "active_sessions": list(_sessions.keys())}


@app.get("/sessions")
async def list_sessions():
    return {"sessions": list(_sessions.keys())}


@app.post("/sessions", status_code=201)
async def create_session(body: CreateSessionRequest):
    """Create (or resume) a session. Boots the agent runtime if not already live."""
    session_id = body.session_id.strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id must not be empty.")
    sess = await _get_or_create_session(session_id)
    return {
        "session_id": session_id,
        "message_count": len(sess.conversation_history),
        "ready": sess._ready,
    }


@app.get("/sessions/{session_id}")
async def get_session(session_id: str):
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found. POST /sessions to create it.")
    sess = _sessions[session_id]
    return {
        "session_id": session_id,
        "message_count": len(sess.conversation_history),
        "ready": sess._ready,
    }


@app.delete("/sessions/{session_id}", status_code=200)
async def delete_session(session_id: str):
    """Clears the in-memory session AND history. The agent runtime is shut down."""
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found.")
    await _sessions[session_id].shutdown()
    del _sessions[session_id]
    return {"detail": f"Session '{session_id}' deleted."}


@app.post("/sessions/{session_id}/shutdown")
async def shutdown_session(session_id: str):
    """Tears down the live agent (closes MCP connections) without deleting history."""
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found.")
    await _sessions[session_id].shutdown()
    del _sessions[session_id]
    return {"detail": f"Session '{session_id}' shut down. POST /sessions to restart."}


@app.post("/sessions/{session_id}/chat")
async def chat(session_id: str, body: ChatRequest, request: Request):
    """
    Send a message to the agent. Returns a Server-Sent Events stream.

    Each SSE event is a JSON object:
      {"type": "tool_call",   "name": "...", "args": {...}}
      {"type": "tool_result", "name": "...", "content": "..."}
      {"type": "token",       "content": "..."}
      {"type": "done",        "content": "<final answer>"}
      {"type": "error",       "content": "<error message>"}
    """
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="message must not be empty.")

    # Boot the session if it's not already live (e.g. server restarted)
    sess = await _get_or_create_session(session_id)

    async def event_stream() -> AsyncGenerator[str, None]:
        # Check client disconnect
        async for chunk in sess.chat(body.message):
            if await request.is_disconnected():
                break
            yield chunk

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _sse(data: dict) -> str:
    """Format a dict as an SSE 'data:' line."""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _extract_text(content) -> str:
    if isinstance(content, list):
        return " ".join(
            b.get("text", str(b)) if isinstance(b, dict) else str(b)
            for b in content
        )
    return str(content)


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    """Main entry point for the API server."""
    import argparse
    import uvicorn

    p = argparse.ArgumentParser(description="Agent_head API Server")
    p.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    p.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    p.add_argument("--config", default=None, help="Path to config.yaml")
    p.add_argument("--reload", action="store_true", help="Enable auto-reload (dev only)")
    args = p.parse_args()

    if args.config:
        os.environ["ORCHESTRATOR_CONFIG"] = args.config

    print(f"\n🚀  Agent_head API  →  http://{args.host}:{args.port}")
    print(f"   Docs            →  http://{args.host}:{args.port}/docs\n")

    uvicorn.run(
        "api.server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
