"""
core/mcp_server.py
-------------------
MCP Server — exposes the Agent_head orchestrator as a full-featured MCP server.

This allows other agents, Claude Desktop, Cursor, or any MCP client to connect
and use the orchestrator's capabilities as tools.  Supports building **agent
networks** where multiple agents connect, share sessions, and collaborate.

Tools exposed
-------------
  orchestrate_task   — One-shot task execution (fire-and-forget)
  create_session     — Create or join a persistent session with identity
  chat               — Multi-turn conversation in a session
  list_sessions      — List all active sessions
  get_session_history— Retrieve conversation history for a session
  list_agents        — List configured worker agents & tool servers
  get_status         — Agent health + current workload (for supervisors)
  close_session      — Tear down a session and persist history

Transports
----------
  stdio              — Subprocess (Claude Desktop, Cursor, parent agents)
  sse                — Legacy SSE over HTTP (LAN/internet agent networks)
  streamable-http    — Modern MCP standard (production deployments)

Usage
-----
  agent-mcp                                          # stdio (default)
  agent-mcp --transport sse --port 9000              # SSE network mode
  agent-mcp --transport http --port 9000             # Streamable HTTP
  agent-mcp --config /path/to/config.yaml            # custom config
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP, Context

from core.config_loader import AppConfig, load_config

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Session Management — Persistent agent sessions with multi-agent identity
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class SessionParticipant:
    """Tracks an agent that has joined a session."""
    agent_name: str
    joined_at: float = field(default_factory=time.time)


@dataclass
class SessionInfo:
    """Metadata for a session (returned by list_sessions, etc.)."""
    session_id: str
    participants: list[str]
    message_count: int
    created_at: float
    last_active: float
    purpose: str = ""


class AgentSession:
    """
    One live agent session — manages MCP tool connections, conversation
    history, memory, and summarisation across multiple chat turns.

    Multiple external agents can join the same session via ``chat()`` or
    ``create_session()`` using the same ``session_id``.  Messages are
    tagged with the caller's ``agent_name`` so the orchestrator LLM can
    distinguish who said what.
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

        self.participants: dict[str, SessionParticipant] = {}
        self.purpose: str = ""
        self.created_at: float = time.time()
        self.last_active: float = time.time()

        self._stack: AsyncExitStack | None = None
        self._ready = False
        self._lock = asyncio.Lock()           # serialise concurrent chat calls
        self._shutdown_event = asyncio.Event()
        self._boot_complete = asyncio.Event()
        self._bg_task: asyncio.Task | None = None
        self._all_tools: list = []
        self._busy = False                    # whether a chat/task is running

    # ── Public API ────────────────────────────────────────────────────────

    async def boot(self) -> None:
        """Start the background task that holds MCP connections alive."""
        if self._bg_task is not None:
            return
        self._bg_task = asyncio.create_task(self._run_stack())
        await self._boot_complete.wait()

    async def shutdown(self) -> None:
        """Tear down MCP connections.  History is already persisted per-turn."""
        self._shutdown_event.set()
        if self._bg_task:
            await self._bg_task
            self._bg_task = None
        self._ready = False

    def add_participant(self, agent_name: str) -> None:
        if agent_name and agent_name not in self.participants:
            self.participants[agent_name] = SessionParticipant(agent_name=agent_name)

    def info(self) -> SessionInfo:
        return SessionInfo(
            session_id=self.session_id,
            participants=list(self.participants.keys()),
            message_count=len(self.conversation_history),
            created_at=self.created_at,
            last_active=self.last_active,
            purpose=self.purpose,
        )

    # ── Chat ──────────────────────────────────────────────────────────────

    async def chat(
        self,
        message: str,
        agent_name: str = "",
        progress: str = "summary",
        ctx: Context | None = None,
    ) -> str:
        """
        Process one turn.  Returns the final answer string.
        Streams progress via ``ctx.info()`` if a context is provided.
        """
        async with self._lock:
            self._busy = True
            self.last_active = time.time()

            try:
                from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

                # ── Tag message with sender identity ──────────────────────
                if agent_name:
                    self.add_participant(agent_name)
                    tagged_message = f"[{agent_name}]: {message}"
                else:
                    tagged_message = message

                # ── Auto-inject RAG context ───────────────────────────────
                task_text = tagged_message
                if (self.config.memory.enabled
                        and self.backend
                        and self.config.memory.auto_feed_top_k > 0):
                    try:
                        context = self.backend.search(
                            message,
                            category=self.config.memory.auto_feed_category,
                            session_id=self.session_id,
                        )
                        if context.strip() and "No relevant" not in context:
                            context = context[:4000]
                            task_text = (
                                f"[System: Relevant Past Memory]\n{context}\n\n"
                                f"{tagged_message}"
                            )
                    except Exception:
                        pass

                self.conversation_history.append(HumanMessage(content=task_text))

                if ctx and progress != "none":
                    await ctx.info(f"Processing message from '{agent_name or 'anonymous'}'...")

                # ── Run the ReAct graph ───────────────────────────────────
                final_answer = ""
                last_event = None

                async for event in self.graph.astream(
                    {"messages": self.conversation_history}, stream_mode="values"
                ):
                    last_event = event
                    last_msg = event["messages"][-1]

                    if isinstance(last_msg, AIMessage):
                        if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                            for tc in last_msg.tool_calls:
                                tc_name = tc.get("name", "unknown")
                                if ctx and progress in ("summary", "full"):
                                    detail = ""
                                    if progress == "full":
                                        args_str = json.dumps(tc.get("args", {}), ensure_ascii=False)
                                        detail = f" | args: {args_str[:500]}"
                                    await ctx.info(f"[Tool Call] {tc_name}{detail}")

                        if last_msg.content:
                            content = _extract_text(last_msg.content)
                            final_answer = content
                            if ctx and progress == "full":
                                await ctx.info(f"[LLM] {content[:1000]}")

                    elif isinstance(last_msg, ToolMessage):
                        content = _extract_text(last_msg.content)
                        tool_name = getattr(last_msg, "name", "tool") or "tool"
                        is_error = any(
                            kw in content.lower()
                            for kw in ("error", "exception", "traceback")
                        )
                        if ctx and progress in ("summary", "full"):
                            status = "❌" if is_error else "✅"
                            detail = ""
                            if progress == "full":
                                detail = f" | {content[:500]}"
                            await ctx.info(f"[Tool Result] {tool_name} {status}{detail}")

                # ── Update history from graph output ──────────────────────
                if last_event is not None:
                    self.conversation_history = list(last_event["messages"])

                # ── Persist session ───────────────────────────────────────
                if self.session_manager:
                    self.session_manager.save_session(
                        self.session_id, self.conversation_history
                    )

                # ── Rolling summarisation ─────────────────────────────────
                if (self.summarizer
                        and self.summarizer.should_summarize(self.conversation_history)):
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
                            self.session_manager.save_session(
                                self.session_id, self.conversation_history
                            )

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
                                self.backend.save_fact(
                                    fact, is_global=False, session_id=self.session_id
                                )

                        if ctx and progress != "none":
                            await ctx.info(
                                f"[Memory] History compressed. "
                                f"{len(result.new_global_facts) + len(result.new_private_facts)} "
                                f"new facts saved."
                            )
                    except Exception as exc:
                        logger.warning(
                            "[Session %s] Summariser failed: %s", self.session_id, exc
                        )

                return final_answer or "Orchestrator completed but produced no text output."

            except Exception as exc:
                logger.exception("[Session %s] Chat error", self.session_id)
                # Pop the failed user message so history stays consistent
                from langchain_core.messages import HumanMessage
                if (self.conversation_history
                        and isinstance(self.conversation_history[-1], HumanMessage)):
                    self.conversation_history.pop()
                return f"Error: {exc}"

            finally:
                self._busy = False

    # ── Internal: background stack ────────────────────────────────────────

    async def _run_stack(self) -> None:
        """Connect all tools, build the LangGraph agent.  Runs in a background task."""
        from langchain_core.messages import SystemMessage
        from langchain_core.tools import tool as lc_tool
        from langgraph.prebuilt import create_react_agent, ToolNode
        from core.llm import get_llm
        from core.mcp_loader import load_mcp_server_tools
        from typing import Literal as LitType

        try:
            async with AsyncExitStack() as stack:
                self._stack = stack
                all_tools: list = []

                # ── Worker agents ─────────────────────────────────────────
                for wa in self.config.worker_agents:
                    try:
                        tools = await load_mcp_server_tools(
                            stack,
                            command=wa.command,
                            args=wa.args,
                            env=wa.env or None,
                            description_override=wa.description,
                        )
                        all_tools.extend(tools)
                        logger.info(
                            "[Session %s] Worker '%s' → %s",
                            self.session_id, wa.name, [t.name for t in tools],
                        )
                    except Exception as exc:
                        logger.warning(
                            "[Session %s] Worker '%s' failed: %s",
                            self.session_id, wa.name, exc,
                        )

                # ── Direct MCP tool servers ───────────────────────────────
                for mc in self.config.mcp_clients:
                    try:
                        tools = await load_mcp_server_tools(
                            stack,
                            transport=mc.transport,
                            url=mc.url,
                            command=mc.command,
                            args=mc.args,
                            env=mc.env or None,
                        )
                        all_tools.extend(tools)
                        logger.info(
                            "[Session %s] MCP '%s' → %s",
                            self.session_id, mc.name, [t.name for t in tools],
                        )
                    except Exception as exc:
                        logger.warning(
                            "[Session %s] MCP '%s' failed: %s",
                            self.session_id, mc.name, exc,
                        )

                # ── Memory tools ──────────────────────────────────────────
                if self.config.memory.enabled:
                    from core.memory import get_backend as _get_backend

                    _mem_dir = Path(self.config.memory.memory_dir)
                    if not _mem_dir.is_absolute():
                        _mem_dir = Path(__file__).parent.parent / self.config.memory.memory_dir
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
                        def memory_search(
                            query: str,
                            category: LitType["all", "history", "facts"] = "all",
                        ) -> str:
                            """Search long-term memory for past tasks, results, and saved facts."""
                            return _backend.search(query, category=category, session_id=_sid)

                        @lc_tool
                        def memory_save(fact: str) -> str:
                            """Save an important fact to long-term memory for future sessions."""
                            return _backend.save_fact(fact)

                        all_tools.extend([memory_search, memory_save])
                        logger.info("[Session %s] Memory tools loaded", self.session_id)
                    except Exception as exc:
                        logger.warning(
                            "[Session %s] Memory failed: %s", self.session_id, exc
                        )

                # ── Image tools ───────────────────────────────────────────
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
                except Exception as exc:
                    logger.warning("[Session %s] Image tools failed: %s", self.session_id, exc)

                # ── Audio tools ───────────────────────────────────────────
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
                except Exception as exc:
                    logger.warning("[Session %s] Audio tools failed: %s", self.session_id, exc)

                # ── Build LLM + ReAct graph ───────────────────────────────
                llm = get_llm(self.config.model)
                tool_node = ToolNode(all_tools, handle_tool_errors=True)
                self.graph = create_react_agent(model=llm, tools=tool_node)
                self._all_tools = all_tools

                # ── Summarizer ────────────────────────────────────────────
                from core.conversation_summarizer import ConversationSummarizer
                if self.config.summarizer.enabled:
                    self.summarizer = ConversationSummarizer(
                        self.config.summarizer, self.config.model
                    )

                # ── Load persisted conversation history ───────────────────
                if self.session_id:
                    cfg = self.config.chat_history
                    if cfg.backend == "sqlite":
                        from core.history_sqlite import SqliteConversationHistory
                        _db = Path(cfg.connection_string)
                        if not _db.is_absolute():
                            _mem_dir2 = Path(self.config.memory.memory_dir)
                            if not _mem_dir2.is_absolute():
                                _mem_dir2 = (
                                    Path(__file__).parent.parent
                                    / self.config.memory.memory_dir
                                )
                            _db = _mem_dir2 / cfg.connection_string
                        self.session_manager = SqliteConversationHistory(db_path=_db)
                        history = self.session_manager.load_session(self.session_id)
                        if history:
                            self.conversation_history = history
                            logger.info(
                                "[Session %s] Resumed: %d messages",
                                self.session_id, len(history),
                            )

                # ── System prompt ─────────────────────────────────────────
                if not self.conversation_history:
                    # Build an enhanced system prompt that explains multi-agent
                    # identity when participants are present.
                    self.conversation_history = [
                        SystemMessage(content=self._build_system_prompt())
                    ]

                self._ready = True
                self._boot_complete.set()

                logger.info(
                    "[Session %s] Ready — %d tools loaded",
                    self.session_id, len(all_tools),
                )

                # Keep the stack alive until shutdown is requested
                await self._shutdown_event.wait()

        except Exception:
            logger.exception("[Session %s] Background task crashed", self.session_id)
        finally:
            self._ready = False
            self._boot_complete.set()

    def _build_system_prompt(self) -> str:
        """Build the system prompt, including multi-agent identity instructions."""
        base = self.config.agent.system_prompt

        # If there are participants, add multi-agent awareness
        if self.participants:
            names = ", ".join(self.participants.keys())
            multi_agent_addendum = (
                "\n\n--- Multi-Agent Session ---\n"
                "This is a collaborative multi-agent session.  Messages from "
                "different agents are prefixed with their identity in the format "
                "'[AgentName]: message'.  You MUST treat each prefix as a "
                "distinct agent with its own context and expertise.\n"
                f"Current participants: {names}\n"
                "When responding, consider all agents' inputs and synthesise "
                "a coherent response.  If a task was delegated by a specific "
                "agent, address your response to them.\n"
                "--- End Multi-Agent Session ---"
            )
            return base + multi_agent_addendum

        return base


# ═══════════════════════════════════════════════════════════════════════════════
# Session Registry — Global in-memory store
# ═══════════════════════════════════════════════════════════════════════════════

_sessions: dict[str, AgentSession] = {}
_config: AppConfig | None = None


def _get_config() -> AppConfig:
    global _config
    if _config is None:
        _config = load_config()
    return _config


async def _get_or_create_session(
    session_id: str, agent_name: str = "", purpose: str = ""
) -> AgentSession:
    """Get an existing session or create + boot a new one."""
    if session_id not in _sessions:
        cfg = _get_config()
        sess = AgentSession(session_id, cfg)
        sess.purpose = purpose
        if agent_name:
            sess.add_participant(agent_name)
        await sess.boot()
        _sessions[session_id] = sess
    else:
        sess = _sessions[session_id]
        if agent_name:
            sess.add_participant(agent_name)
        if purpose and not sess.purpose:
            sess.purpose = purpose
    return sess


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _extract_text(content) -> str:
    """Normalise content (str or list-of-blocks) to a plain string."""
    if isinstance(content, list):
        return " ".join(
            b.get("text", str(b)) if isinstance(b, dict) else str(b) for b in content
        )
    return str(content)


def _resolve_progress(explicit: str | None) -> str:
    """Resolve progress level: explicit arg > config default > 'summary'."""
    if explicit and explicit in ("none", "summary", "full"):
        return explicit
    cfg = _get_config()
    return cfg.mcp_server.default_progress


# ═══════════════════════════════════════════════════════════════════════════════
# FastMCP Server + Tool Definitions
# ═══════════════════════════════════════════════════════════════════════════════

# The module-level `mcp` uses a default name so that importing this module does
# NOT trigger config resolution.  The `main()` function replaces it with a
# fresh instance configured from the loaded config after CLI args are parsed.
mcp = FastMCP("agent-orchestrator")


# ─── Tool 1: orchestrate_task ─────────────────────────────────────────────────

@mcp.tool()
async def orchestrate_task(
    ctx: Context,
    task: str,
    session_id: str = "",
    progress: str = "",
) -> str:
    """
    Execute a high-level task using the agent orchestrator (one-shot mode).

    The orchestrator breaks down the task, delegates to worker agents and
    MCP tool servers, and returns the final result.

    Args:
        task:       A clear, natural-language description of the task.
        session_id: Optional session ID for memory continuity across calls.
                    If empty, a temporary session is used and cleaned up after.
        progress:   Progress streaming level: "none", "summary", or "full".
                    Defaults to the server's configured default.
                    - none:    Only return the final answer.
                    - summary: Stream tool call names and success/failure.
                    - full:    Stream everything including args, results, LLM text.

    Returns:
        The final result produced by the orchestrator.
    """
    prog = _resolve_progress(progress)
    is_temp = not session_id
    if is_temp:
        session_id = f"_oneshot_{int(time.time() * 1000)}"

    try:
        await ctx.info(f"Starting orchestration (progress={prog})...")
        sess = await _get_or_create_session(session_id)
        result = await sess.chat(message=task, progress=prog, ctx=ctx)
        return result

    except Exception as exc:
        logger.exception("orchestrate_task failed")
        return f"Error: {exc}"

    finally:
        # Clean up temporary sessions
        if is_temp and session_id in _sessions:
            await _sessions[session_id].shutdown()
            del _sessions[session_id]


# ─── Tool 2: create_session ──────────────────────────────────────────────────

@mcp.tool()
async def create_session(
    ctx: Context,
    session_id: str,
    agent_name: str = "",
    purpose: str = "",
) -> str:
    """
    Create a new persistent session or join an existing one.

    Sessions enable multi-turn conversations and multi-agent collaboration.
    Multiple agents can join the same session to collaborate — each agent's
    messages are tagged with their identity so the orchestrator can
    distinguish who said what.

    Args:
        session_id: Unique identifier for the session.
        agent_name: Identity of the joining agent (e.g. "SupervisorAgent").
                    This is used to tag messages in shared sessions.
        purpose:    Optional description of what this session is for.

    Returns:
        Session metadata as JSON (participants, message count, tools, etc.)
    """
    sess = await _get_or_create_session(session_id, agent_name, purpose)

    info = sess.info()
    return json.dumps({
        "status": "ok",
        "session_id": info.session_id,
        "participants": info.participants,
        "message_count": info.message_count,
        "purpose": info.purpose,
        "tools_available": [t.name for t in sess._all_tools],
        "ready": sess._ready,
    }, ensure_ascii=False, indent=2)


# ─── Tool 3: chat ────────────────────────────────────────────────────────────

@mcp.tool()
async def chat(
    ctx: Context,
    session_id: str,
    message: str,
    agent_name: str = "",
    progress: str = "",
) -> str:
    """
    Send a message in a persistent session (multi-turn conversation).

    If the session does not exist, it is automatically created. Messages
    from different agents are tagged with their identity so the orchestrator
    can distinguish participants in a shared session.

    Args:
        session_id: The session to chat in.
        message:    The message to send.
        agent_name: Identity of the sending agent (e.g. "ResearchAgent").
                    Used to tag messages: "[ResearchAgent]: your message".
                    REQUIRED in shared sessions to avoid confusion.
        progress:   Progress streaming level: "none", "summary", or "full".

    Returns:
        The orchestrator's response to the message.
    """
    prog = _resolve_progress(progress)
    sess = await _get_or_create_session(session_id, agent_name)
    result = await sess.chat(message=message, agent_name=agent_name, progress=prog, ctx=ctx)
    return result


# ─── Tool 4: list_sessions ───────────────────────────────────────────────────

@mcp.tool()
async def list_sessions(ctx: Context) -> str:
    """
    List all active sessions on this orchestrator.

    Returns a JSON array of session metadata including session_id,
    participants, message count, and timestamps. Useful for supervisor
    agents that need to monitor which sessions are active.

    Returns:
        JSON array of active session information.
    """
    sessions = []
    for sess in _sessions.values():
        info = sess.info()
        sessions.append({
            "session_id": info.session_id,
            "participants": info.participants,
            "message_count": info.message_count,
            "purpose": info.purpose,
            "created_at": info.created_at,
            "last_active": info.last_active,
            "busy": sess._busy,
        })
    return json.dumps(sessions, ensure_ascii=False, indent=2)


# ─── Tool 5: get_session_history ─────────────────────────────────────────────

@mcp.tool()
async def get_session_history(
    ctx: Context,
    session_id: str,
    last_n: int = 0,
) -> str:
    """
    Get conversation history for a session.

    Returns messages as a JSON array with role and content for each
    message. Useful for supervisor agents monitoring other agents' work.

    Args:
        session_id: The session to retrieve history for.
        last_n:     Only return the last N messages (0 = all messages).

    Returns:
        JSON array of messages with role and content.
    """
    if session_id not in _sessions:
        return json.dumps({"error": f"Session '{session_id}' not found."})

    sess = _sessions[session_id]
    history = sess.conversation_history

    if last_n > 0:
        history = history[-last_n:]

    messages = []
    for msg in history:
        role = type(msg).__name__.replace("Message", "").lower()
        content = _extract_text(getattr(msg, "content", ""))
        entry: dict[str, Any] = {"role": role, "content": content}

        # Include tool metadata for tool messages
        if role == "tool":
            entry["tool_name"] = getattr(msg, "name", None)
            entry["tool_call_id"] = getattr(msg, "tool_call_id", None)

        messages.append(entry)

    return json.dumps(messages, ensure_ascii=False, indent=2)


# ─── Tool 6: list_agents ─────────────────────────────────────────────────────

@mcp.tool()
async def list_agents(ctx: Context) -> str:
    """
    List all configured worker agents and MCP tool servers.

    Returns a JSON object with two arrays:
      - worker_agents: Agent_a-style subprocess workers
      - mcp_tools:     Direct MCP tool servers (filesystem, search, etc.)

    Returns:
        JSON with configured agents and tools.
    """
    cfg = _get_config()

    workers = []
    for wa in cfg.worker_agents:
        workers.append({
            "name": wa.name,
            "description": wa.description,
            "command": wa.command,
            "args": wa.args,
        })

    tools = []
    for mc in cfg.mcp_clients:
        tools.append({
            "name": mc.name,
            "transport": mc.transport,
            "command": mc.command,
            "args": mc.args,
            "url": mc.url,
        })

    return json.dumps({
        "worker_agents": workers,
        "mcp_tools": tools,
    }, ensure_ascii=False, indent=2)


# ─── Tool 7: get_status ──────────────────────────────────────────────────────

@mcp.tool()
async def get_status(ctx: Context) -> str:
    """
    Get the current status and health of this orchestrator agent.

    Returns information about the agent's identity, model, active sessions,
    available tools, and current workload. Essential for supervisor agents
    that need to assess an agent's capacity before assigning tasks.

    Returns:
        JSON with agent status, model info, session count, and workload.
    """
    cfg = _get_config()

    active_sessions = []
    busy_count = 0
    for sess in _sessions.values():
        active_sessions.append({
            "session_id": sess.session_id,
            "busy": sess._busy,
            "message_count": len(sess.conversation_history),
        })
        if sess._busy:
            busy_count += 1

    return json.dumps({
        "agent": {
            "name": cfg.agent.name,
            "version": cfg.agent.version,
            "description": cfg.agent.description,
        },
        "model": {
            "provider": cfg.model.provider,
            "model_name": cfg.model.model_name,
        },
        "active_sessions": len(_sessions),
        "busy_sessions": busy_count,
        "sessions": active_sessions,
        "configured_workers": [wa.name for wa in cfg.worker_agents],
        "configured_mcp_tools": [mc.name for mc in cfg.mcp_clients],
    }, ensure_ascii=False, indent=2)


# ─── Tool 8: close_session ───────────────────────────────────────────────────

@mcp.tool()
async def close_session(ctx: Context, session_id: str) -> str:
    """
    Close and clean up a session.

    Tears down MCP connections, persists conversation history, and frees
    resources. The session can be resumed later by creating a new session
    with the same session_id (history will be loaded from persistent storage).

    Args:
        session_id: The session to close.

    Returns:
        Confirmation message.
    """
    if session_id not in _sessions:
        return json.dumps({"error": f"Session '{session_id}' not found."})

    sess = _sessions[session_id]

    # Persist before closing
    if sess.session_manager:
        sess.session_manager.save_session(session_id, sess.conversation_history)

    await sess.shutdown()
    del _sessions[session_id]

    return json.dumps({
        "status": "ok",
        "message": f"Session '{session_id}' closed and history persisted.",
    })


# ═══════════════════════════════════════════════════════════════════════════════
# CLI Entry Point
# ═══════════════════════════════════════════════════════════════════════════════


def main():
    """CLI entry point for the MCP server (``agent-mcp`` console script)."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Agent_head — MCP Server Mode",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  agent-mcp                                       # stdio transport (default)
  agent-mcp --transport sse --port 9000           # SSE network mode
  agent-mcp --transport http --port 9000          # Streamable HTTP
  agent-mcp --config /path/to/config.yaml         # custom config
  agent-mcp --config ./my_config.yaml --transport sse --host 0.0.0.0 --port 8080
        """,
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "http"],
        default="stdio",
        help="Transport mode (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default=None,
        help="Host for SSE/HTTP transports (default: from config or 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port for SSE/HTTP transports (default: from config or 8000)",
    )
    parser.add_argument(
        "--config", "-c",
        default=None,
        help="Path to a custom config.yaml",
    )

    args = parser.parse_args()

    # ── Apply config path ─────────────────────────────────────────────────
    if args.config:
        os.environ["ORCHESTRATOR_CONFIG"] = args.config

    # ── Configure logging ─────────────────────────────────────────────────
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        stream=sys.stderr,
    )

    # ── Load config (resolves the global) ─────────────────────────────────
    global _config
    _config = load_config(args.config)

    # ── Resolve host/port from CLI > config ───────────────────────────────
    host = args.host or _config.mcp_server.host
    port = args.port or _config.mcp_server.port

    # ── Recreate the FastMCP with the loaded config name ──────────────────
    global mcp
    mcp = FastMCP(_config.mcp_server.name, host=host, port=port)

    # Re-register all tools on the new instance
    _register_tools(mcp)

    # ── Run ───────────────────────────────────────────────────────────────
    if args.transport == "stdio":
        print(
            f"Starting MCP server '{_config.mcp_server.name}' "
            f"with stdio transport...",
            file=sys.stderr,
        )
        mcp.run(transport="stdio")

    elif args.transport == "sse":
        print(
            f"Starting MCP server '{_config.mcp_server.name}' "
            f"with SSE transport on {host}:{port}...",
            file=sys.stderr,
        )
        mcp.run(transport="sse")

    elif args.transport == "http":
        print(
            f"Starting MCP server '{_config.mcp_server.name}' "
            f"with Streamable HTTP transport on {host}:{port}...",
            file=sys.stderr,
        )
        mcp.run(transport="streamable-http")


def _register_tools(server: FastMCP) -> None:
    """Register all tools on a FastMCP server instance."""
    server.tool()(orchestrate_task)
    server.tool()(create_session)
    server.tool()(chat)
    server.tool()(list_sessions)
    server.tool()(get_session_history)
    server.tool()(list_agents)
    server.tool()(get_status)
    server.tool()(close_session)


if __name__ == "__main__":
    main()
