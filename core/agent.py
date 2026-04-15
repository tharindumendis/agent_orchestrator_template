"""
core/agent.py
-------------
The heart of the Orchestrator Agent.

Responsibilities:
1. Read config — know which worker agents + direct MCP tool servers to connect.
2. Spawn each worker agent as an MCP stdio subprocess → discover its tools.
3. Connect to each direct MCP tool server → discover its tools.
4. Combine ALL tools into one LangGraph ReAct loop.
5. Log every single step via JobLogger.
6. Expose run_orchestrator(task, config) -> str  used by main.py.
"""

from __future__ import annotations

import asyncio
import logging
import traceback
import warnings
from contextlib import AsyncExitStack
from pathlib import Path

warnings.filterwarnings("ignore", category=DeprecationWarning)

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import BaseTool
from langchain_ollama import ChatOllama

try:
    from langchain_openai import ChatOpenAI
except ImportError:
    pass
try:
    from langchain_google_genai import ChatGoogleGenerativeAI
except ImportError:
    pass

from core.mcp_loader import load_mcp_server_tools
from langgraph.prebuilt import create_react_agent, ToolNode

from core.config_loader import AppConfig
from core.job_logger import JobLogger
from core.memory import get_backend

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _tool_input(tool_call: dict) -> dict:
    return tool_call.get("args", {}) or {}


def _truncate(text: str, max_chars: int = 1000) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n... [{len(text) - max_chars} chars truncated]"


def _unwrap_exception(exc: BaseException) -> BaseException:
    if hasattr(exc, "exceptions") and exc.exceptions:
        return _unwrap_exception(exc.exceptions[0])
    return exc


def _content_to_str(content) -> str:
    """Normalise AIMessage.content to a plain string (handles Gemini list format)."""
    if isinstance(content, list):
        return "\n".join(
            b.get("text", str(b)) if isinstance(b, dict) else str(b)
            for b in content
        )
    if not isinstance(content, str):
        return str(content)
    return content


# ---------------------------------------------------------------------------
# Main entry-point
# ---------------------------------------------------------------------------


async def run_orchestrator(task: str, config: AppConfig, session_id: str | None = None) -> str:
    """
    Execute a high-level task using the orchestrator's ReAct loop.

    Phases:
      1. Connect to all worker agents (MCP stdio subprocesses) → tools
      2. Connect to all direct MCP tool servers → tools
      3. Build LangGraph ReAct graph with all tools
      4. Stream ReAct loop, log every step
      5. Return final answer string

    Args:
        task:   The natural-language goal for this orchestration run.
        config: Loaded AppConfig from config.yaml.

    Returns:
        str: The final answer produced by the orchestrator.
    """
    jl = JobLogger(task=task, agent_name=config.agent.name)
    logger.info(
        "[%s] Orchestration job %s started | task: %s",
        config.agent.name,
        jl.job_id,
        task[:120],
    )

    all_tools: list[BaseTool] = []
    final_answer = ""
    success = False
    _tools_used: list[str] = []    # track tool names for memory save

    # ----------------------------------------------------------------
    # PHASE 0 — Load long-term memory and build enriched system prompt
    # ----------------------------------------------------------------
    mem_cfg = config.memory
    mem_dir = Path(mem_cfg.memory_dir)
    if not mem_dir.is_absolute():
        mem_dir = Path(__file__).parent.parent / mem_cfg.memory_dir

    memory_context = ""
    backend = None
    if mem_cfg.enabled:
        try:
            backend = get_backend(
                backend_type=mem_cfg.backend,
                memory_dir=mem_dir,
                max_save_length=mem_cfg.max_save_length,
                rag_server_cfg=mem_cfg.rag_server,
            )
            
            # -- Auto-Inject RAG Context directly into User Prompt --
            if mem_cfg.auto_feed_top_k > 0:
                context_str = backend.search(
                    task, 
                    category=mem_cfg.auto_feed_category,
                    session_id=session_id
                )
                
                MAX_CONTEXT_CHARS = 4000
                if len(context_str) > MAX_CONTEXT_CHARS:
                    context_str = context_str[:MAX_CONTEXT_CHARS] + "\n...[truncated]"
                    
                if context_str.strip() and "No relevant" not in context_str:
                    logger.info("Auto-injected %d chars of memory context for task.", len(context_str))
                    # we modify the local `task` var so the graph gets the enriched prompt below
                    jl.log_step("AGENT_INIT", "Memory auto-injected", details={"chars": len(context_str)})
                    task = f"[System: Relevant Past Memory]\n{context_str}\n\n[User Task]\n{task}"
                    
        except Exception as exc:
            logger.warning("[Memory] Failed to load memories: %s", exc)
            backend = None
    else:
        backend = None

    try:
        async with AsyncExitStack() as stack:

            # ----------------------------------------------------------------
            # PHASE 1 — Connect to worker agents (MCP servers)
            # ----------------------------------------------------------------
            for wa_cfg in config.worker_agents:
                try:
                    tools = await load_mcp_server_tools(
                        stack,
                        command=wa_cfg.command,
                        args=wa_cfg.args,
                        env=wa_cfg.env or None,
                        description_override=wa_cfg.description,
                    )
                    tool_names = [t.name for t in tools]
                    all_tools.extend(tools)

                    jl.log_step(
                        step_type="WORKER_CONNECT",
                        title=wa_cfg.name,
                        details={
                            "command": wa_cfg.command,
                            "args": wa_cfg.args,
                            "description": wa_cfg.description,
                            "tools_discovered": tool_names,
                        },
                        success=True,
                    )
                    logger.info(
                        "[WORKER] Connected to '%s' | tools: %s", wa_cfg.name, tool_names
                    )

                except Exception as exc:
                    tb = traceback.format_exc()
                    jl.log_step(
                        step_type="WORKER_CONNECT",
                        title=wa_cfg.name,
                        details={"command": wa_cfg.command, "args": wa_cfg.args},
                        error=f"{exc}\n{tb}",
                        success=False,
                    )
                    logger.error(
                        "[WORKER] Failed to connect to '%s': %s", wa_cfg.name, exc
                    )

            # ----------------------------------------------------------------
            # PHASE 2 — Connect to direct MCP tool servers
            # ----------------------------------------------------------------
            for client_cfg in config.mcp_clients:
                try:
                    tools = await load_mcp_server_tools(
                        stack,
                        transport=client_cfg.transport,
                        url=client_cfg.url,
                        headers=client_cfg.headers or None,
                        command=client_cfg.command,
                        args=client_cfg.args,
                        env=client_cfg.env or None,
                    )
                    tool_names = [t.name for t in tools]
                    all_tools.extend(tools)

                    jl.log_step(
                        step_type="MCP_CONNECT",
                        title=client_cfg.name,
                        details={
                            "command": client_cfg.command,
                            "args": client_cfg.args,
                            "tools_discovered": tool_names,
                        },
                        success=True,
                    )
                    logger.info(
                        "[MCP] Connected to '%s' | tools: %s", client_cfg.name, tool_names
                    )

                except Exception as exc:
                    tb = traceback.format_exc()
                    jl.log_step(
                        step_type="MCP_CONNECT",
                        title=client_cfg.name,
                        details={"command": client_cfg.command, "args": client_cfg.args},
                        error=f"{exc}\n{tb}",
                        success=False,
                    )
                    logger.error(
                        "[MCP] Failed to connect to '%s': %s", client_cfg.name, exc
                    )

            # ----------------------------------------------------------------
            # Check availability of tools
            # ----------------------------------------------------------------
            if not all_tools:
                jl.log_step(
                    step_type="INFO",
                    title="No tools available",
                    details={
                        "note": (
                            "Running in LLM-only mode. "
                            "Configure worker_agents or mcp_clients in config.yaml."
                        )
                    },
                )
                logger.warning(
                    "No tools available — orchestrator running in LLM-only mode."
                )

            # ----------------------------------------------------------------
            # PHASE 2.6 — Image tools (read, save, screenshot, OCR)
            # ----------------------------------------------------------------
            try:
                from core.image_tools import get_image_tools
                _img_cfg = config.image_tools
                _img_tools = get_image_tools(
                    enabled=_img_cfg.enabled,
                    enable_save=_img_cfg.enable_save,
                    enable_screenshot=_img_cfg.enable_screenshot,
                    enable_ocr=_img_cfg.enable_ocr,
                    screenshot_dir=_img_cfg.screenshot_dir,
                )
                if _img_tools:
                    all_tools.extend(_img_tools)
                    logger.info("[IMAGE] Registered: %s", [t.name for t in _img_tools])
            except Exception as _img_exc:
                logger.warning("[IMAGE] Image tools failed to load: %s", _img_exc)

            # ----------------------------------------------------------------
            # PHASE 2.7 — Audio tools (transcribe, TTS, save, record)
            # ----------------------------------------------------------------
            try:
                from core.audio_tools import get_audio_tools
                _aud_cfg = config.audio_tools
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
                    logger.info("[AUDIO] Registered: %s", [t.name for t in _aud_tools])
            except Exception as _aud_exc:
                logger.warning("[AUDIO] Audio tools failed to load: %s", _aud_exc)

            # ----------------------------------------------------------------
            # PHASE 2.8 — Skills (catalog + always-inject + load_skill tool)
            # ----------------------------------------------------------------
            _skills_catalog_block = ""
            _skills_always_block  = ""
            try:
                from core.skill_loader import (
                    discover_skills, build_catalog_block,
                    load_skill_content, make_load_skill_tool,
                )
                _sk_cfg = config.skills
                if _sk_cfg.enabled:
                    _all_skills = discover_skills(_sk_cfg.skills_dirs)
                    if _all_skills:
                        # Register load_skill tool
                        all_tools.append(make_load_skill_tool(_all_skills))
                        logger.info(
                            "[Skills] Registered load_skill | available: %s",
                            [s.name for s in _all_skills],
                        )
                        # Build compact catalog for system prompt
                        _skills_catalog_block = build_catalog_block(_all_skills)
                        # Build always-inject full content
                        for sname in _sk_cfg.always_inject:
                            body = load_skill_content(sname, _all_skills)
                            logger.info("[Skills] Always-injecting full skill: %s", sname)
                            _skills_always_block += f"\n\n{body}"
            except Exception as _sk_exc:
                logger.warning("[Skills] Failed to load skills: %s", _sk_exc)

            # ----------------------------------------------------------------
            # PHASE 3 — Build orchestrator LLM + ReAct agent
            # ----------------------------------------------------------------
            tool_descriptions = "\n".join(
                f"  - {t.name}: {getattr(t, 'description', 'no description')}"
                for t in all_tools
            )
            base_prompt = config.agent.system_prompt
            # Prepend long-term memory if available
            if memory_context:
                base_prompt = memory_context + "\n\n" + base_prompt
            enriched_prompt = base_prompt + (
                f"\n\nAvailable tools:\n{tool_descriptions}" if tool_descriptions else ""
            )
            # Prepend skills catalog (compact: name + description)
            if _skills_catalog_block:
                enriched_prompt = _skills_catalog_block + "\n\n" + enriched_prompt
            # Append always-inject skills (full content)
            if _skills_always_block:
                enriched_prompt += _skills_always_block

            try:
                from core.llm import get_llm
                llm = get_llm(config.model)
            except ImportError as e:
                logger.error("LLM init failed: %s", e)
                jl.log_step(
                    step_type="AGENT_INIT",
                    title="Agent init failed",
                    details={"error": str(e)},
                    success=False
                )
                return

            # Wrap tools in a ToolNode with error handling so that any ToolException
            # (e.g. permission errors, API failures) is caught and returned to the
            # agent as a ToolMessage instead of crashing the graph stream.
            tool_node = ToolNode(all_tools, handle_tool_errors=True)

            graph = create_react_agent(
                model=llm,
                tools=tool_node,
            )

            jl.log_step(
                step_type="AGENT_INIT",
                title="Orchestrator ReAct agent ready",
                details={
                    "model": f"{config.model.provider}/{config.model.model_name}",
                    "temperature": config.model.temperature,
                    "total_tools": len(all_tools),
                    "tools": [t.name for t in all_tools],
                },
            )
            logger.info(
                "Orchestrator ready | model=%s/%s | tools(%d)=%s",
                config.model.provider,
                config.model.model_name,
                len(all_tools),
                [t.name for t in all_tools],
            )
            logger.info("enriched_prompt: %s", enriched_prompt)
            # ----------------------------------------------------------------
            # PHASE 4 — Run the ReAct loop + log every event
            # ----------------------------------------------------------------
            messages = [
                SystemMessage(content=enriched_prompt),
                HumanMessage(content=task),
            ]

            # --- Debug Logger ---
            if config.agent.debug:
                try:
                    import json
                    from langchain_core.messages import messages_to_dict
                    
                    log_dir = Path("logs/runs")
                    log_dir.mkdir(parents=True, exist_ok=True)
                    debug_log_path = log_dir / f"{jl.job_id}.log"
                    
                    with open(debug_log_path, "w", encoding="utf-8") as f:
                        f.write(f"=== Single-Shot Job: {jl.job_id} ===\n\n")
                        f.write(f"\n--- [START] PROMPT FED TO LLM ---\n")
                        f.write(json.dumps(messages_to_dict(messages), indent=2))
                        f.write("\n\n")
                except Exception as e:
                    logger.error("Failed to write to debug log: %s", e)

            _logged_tool_calls: set = set()
            _llm_step = 0

            try:
                async for event in graph.astream(
                    {"messages": messages},
                    stream_mode="values",
                ):
                    last_msg = event["messages"][-1]

                    # ── AIMessage: LLM text or tool-call plan ─────────────────
                    if isinstance(last_msg, AIMessage):
                        tool_calls = getattr(last_msg, "tool_calls", []) or []

                        if last_msg.content:
                            _llm_step += 1
                            content_str = _content_to_str(last_msg.content)
                            jl.log_step(
                                step_type="LLM_RESPONSE",
                                title=f"Orchestrator turn {_llm_step}",
                                output=_truncate(content_str),
                            )
                            final_answer = content_str

                        for tc in tool_calls:
                            tc_id = tc.get("id", "")
                            if tc_id in _logged_tool_calls:
                                continue
                            _logged_tool_calls.add(tc_id)
                            jl.log_step(
                                step_type="TOOL_CALL",
                                title=tc.get("name", "unknown"),
                                details={
                                    "tool": tc.get("name"),
                                    "call_id": tc_id,
                                    "input": _tool_input(tc),
                                },
                            )

                    # ── ToolMessage: result came back ─────────────────────────
                    elif isinstance(last_msg, ToolMessage):
                        raw_content = last_msg.content or ""
                        content_str = _content_to_str(raw_content)
                        is_error = any(
                            kw in content_str.lower()
                            for kw in ("error", "exception", "traceback")
                        )
                        tool_name = getattr(last_msg, "name", "tool") or "tool"
                        if tool_name not in _tools_used:
                            _tools_used.append(tool_name)
                        jl.log_step(
                            step_type="TOOL_RESULT",
                            title=getattr(last_msg, "name", "tool") or "tool",
                            details={"call_id": getattr(last_msg, "tool_call_id", "")},
                            output=_truncate(content_str),
                            success=not is_error,
                            error=content_str if is_error else None,
                        )

            except Exception as stream_exc:  # noqa: BLE001
                # A tool raised an un-handled exception inside the stream.
                # Log it, set it as the final answer so the caller sees it,
                # and let the REPL continue instead of dying.
                exc_name = type(stream_exc).__name__
                exc_msg  = str(stream_exc)
                jl.log_step(
                    step_type="TOOL_ERROR",
                    title=exc_name,
                    error=exc_msg,
                    success=False,
                )
                logger.error(
                    "[%s] Tool raised unhandled error: %s — %s",
                    config.agent.name, exc_name, exc_msg,
                )
                final_answer = f"Tool error ({exc_name}): {exc_msg}"
                # success stays False — the finally block will handle memory save
            else:
                # Stream completed normally — no exception was raised
                success = True

    except BaseException as root_exc:
        exc = _unwrap_exception(root_exc)
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))

        if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt)):
            logger.warning(
                "[%s] Job %s cancelled/interrupted.", config.agent.name, jl.job_id
            )
            final_answer = "ERROR: Orchestration was cancelled or interrupted."
            success = False

        elif type(exc).__name__ in (
            "RateLimitError",
            "AuthenticationError",
            "APIConnectionError",
            "APIError",
            "InvalidRequestError",
        ):
            jl.log_step(
                step_type="LLM_API_ERROR",
                title=type(exc).__name__,
                error=str(exc),
                success=False,
            )
            logger.error(
                "[%s] Job %s LLM API error: %s", config.agent.name, jl.job_id, exc
            )
            final_answer = f"ERROR: LLM Provider Issue ({type(exc).__name__}): {exc}"
            success = False

        else:
            jl.log_step(
                step_type="FATAL_ERROR",
                title=type(exc).__name__,
                error=f"{exc}\n\n{tb}",
                success=False,
            )
            logger.exception(
                "[%s] Job %s unhandled exception: %s", config.agent.name, jl.job_id, exc
            )
            final_answer = f"ERROR: {type(exc).__name__}: {exc}"
            success = False

    finally:
        jl.finish(final_answer=final_answer, success=success)
        logger.info(
            "[%s] Job %s %s | log: %s",
            config.agent.name,
            jl.job_id,
            "COMPLETE" if success else "FAILED",
            jl.path,
        )
        # ----------------------------------------------------------------
        # PHASE 5 — Auto-save job summary to long-term memory
        # ----------------------------------------------------------------
        if mem_cfg.enabled and backend is not None and (final_answer or not success):
            try:
                backend.save(
                    job_id=jl.job_id,
                    task=task,
                    summary=final_answer or "Job failed with no output.",
                    tools_used=_tools_used,
                    outcome="success" if success else "failed",
                    session_id=session_id,
                )
            except Exception as exc:
                logger.warning("[Memory] Failed to save memory: %s", exc)

    return final_answer or "Orchestrator completed but produced no text output."
