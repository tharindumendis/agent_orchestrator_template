"""
main.py — Agent_head entry point
---------------------------------
The main autonomous orchestrator agent.

Features:
  - Connects to multiple Worker Agents (Agent_a-style MCP subprocesses)
  - Connects to any additional direct MCP tool servers
  - Runs a LangGraph ReAct loop with all tools combined
  - Structured per-job logging to logs/jobs/
  - Rich coloured console output

Usage:
    # Interactive REPL:
    python main.py

    # Single-shot task:
    python main.py --task "Research quantum computing and write a summary"

    # Custom config:
    python main.py --config /path/to/my_config.yaml

    # Change model at runtime:
    python main.py --model gemini-2.0-flash --provider gemini --api-key sk-...

    # Export default config files to a directory for editing:
    python main.py --setup
    python main.py --setup /path/to/my/project
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Literal
import logging
import sys
import warnings
import os
import time
from prompt_toolkit.formatted_text import ANSI

import colorama
colorama.init()

warnings.filterwarnings("ignore", category=DeprecationWarning)

# Force UTF-8 on Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

from langchain_core.messages import AIMessage, ToolMessage

from core.agent import run_orchestrator
from core.config_loader import load_config

# ---------------------------------------------------------------------------
# Logging — stderr only, not stdout (keeps tool output clean)
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ANSI colour helpers
# ---------------------------------------------------------------------------
def _c(code: str, text: str) -> str:
    """Wrap text in an ANSI colour code."""
    return text  # Colors disabled to avoid display issues


CYAN   = "96"
YELLOW = "93"
GREEN  = "92"
GREY   = "90"
BOLD   = "1"
RED    = "31"


# ---------------------------------------------------------------------------
# Pretty event printer (mirrors sample_main_agent.py style)
# ---------------------------------------------------------------------------

def _print_event(event: dict) -> None:
    messages = event.get("messages", [])
    if not messages:
        return
    last = messages[-1]

    if isinstance(last, AIMessage):
        if last.content:
            content = last.content
            if isinstance(content, list):
                content = "\n".join(
                    b.get("text", str(b)) if isinstance(b, dict) else str(b)
                    for b in content
                )
            print(f"\n{_c(BOLD, '[Orchestrator]')} {_c(CYAN, str(content))}")

        if hasattr(last, "tool_calls") and last.tool_calls:
            for tc in last.tool_calls:
                args  = tc.get("args", {})
                tname = tc.get("name", "unknown")
                # Worker agents use `instruction`, others may use anything
                preview = args.get("instruction", str(args))[:400]
                if len(str(args.get("instruction", ""))) > 400:
                    preview += "..."
                print(f"\n{_c(BOLD, '[Tool Call]')} {_c(YELLOW, tname)}")
                print(f"   {_c(GREY, preview)}")

    elif isinstance(last, ToolMessage):
        content = last.content or ""
        if isinstance(content, list):
            content = "\n".join(
                b.get("text", str(b)) if isinstance(b, dict) else str(b)
                for b in content
            )
        tool_name = getattr(last, "name", "tool") or "tool"
        print(f"\n{_c(BOLD, '[Tool Result]')} {_c(GREEN, tool_name)}")
        for line in str(content)[:1200].splitlines():
            print(f"   {line}")
        if len(str(content)) > 1200:
            print("   ...")


# ---------------------------------------------------------------------------
# Core async runner
# ---------------------------------------------------------------------------

async def run(
    task: str,
    config_path: str | None = None,
    model_override: str | None = None,
    provider_override: str | None = None,
    api_key_override: str | None = None,
    base_url_override: str | None = None,
    session_id: str | None = None,
) -> str:
    """
    Load config, optionally override model settings, then run the orchestrator.
    Returns the final answer string.
    """
    if config_path:
        os.environ["ORCHESTRATOR_CONFIG"] = config_path

    config = load_config(config_path)

    # Allow CLI overrides for quick model switching without editing config.yaml
    if model_override:
        config.model.model_name = model_override
    if provider_override:
        config.model.provider = provider_override
    if api_key_override:
        config.model.api_key = api_key_override
    if base_url_override:
        config.model.base_url = base_url_override

    _print_banner(config)
    print(f"\n{_c(BOLD, '[Task]')} {task}\n")
    print("─" * 60)

    answer = await run_orchestrator(task=task, config=config, session_id=session_id)
    return answer


def _print_banner(config) -> None:
    try:
        banner_path = os.path.join(os.path.dirname(__file__), 'banner.txt')
        with open(banner_path, 'r', encoding='utf-8') as f:
            print(_c(CYAN, f.read()))
    except Exception:
        pass

    print("\n" + "═" * 60)
    print(f"  {_c(BOLD, config.agent.name)}  v{config.agent.version}")
    print("═" * 60)
    workers = [w.name for w in config.worker_agents]
    direct  = [m.name for m in config.mcp_clients]
    print(f"  Model   : {config.model.provider}/{config.model.model_name}")
    print(f"  Workers : {workers or '(none)'}")
    print(f"  Tools   : {direct or '(none)'}")
    print("═" * 60)


# ---------------------------------------------------------------------------
# Interactive REPL
# ---------------------------------------------------------------------------

async def interactive_loop(
    config_path: str | None = None,
    model_override: str | None = None,
    provider_override: str | None = None,
    api_key_override: str | None = None,
    base_url_override: str | None = None,
    session_id: str | None = None,
) -> None:
    # Session logic:
    #   no --session flag  → default to "default" (always persist)
    #   --session no       → ephemeral mode, no persistence
    #   --session myname   → named persistent session
    if not session_id:
        session_id = "default"
    elif session_id.strip().lower() == "no":
        session_id = None   # disable persistence explicitly

    if config_path:
        os.environ["ORCHESTRATOR_CONFIG"] = config_path
    config = load_config(config_path)

    if model_override:
        config.model.model_name = model_override
    if provider_override:
        config.model.provider = provider_override
    if api_key_override:
        config.model.api_key = api_key_override
    if base_url_override:
        config.model.base_url = base_url_override

    _print_banner(config)
    workers = [w.name for w in config.worker_agents]
    print(f"\n  Type your goal below. Workers available: {workers}")
    print("  'quit' or Ctrl-C to exit.\n")

    # ── One-time setup: connect tools, build LLM + graph ──────────────────────
    from langchain_core.messages import SystemMessage, HumanMessage, AIMessage as _AIMessage
    from langgraph.prebuilt import create_react_agent, ToolNode
    from contextlib import AsyncExitStack
    from core.mcp_loader import load_mcp_server_tools
    from langchain_ollama import ChatOllama
    try:
        from langchain_openai import ChatOpenAI
    except ImportError:
        pass
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except ImportError:
        pass

    print(f"\n{_c(GREY, '[*] Connecting to worker agents and tools...')}")

    all_tools = []
    _stack = AsyncExitStack()
    await _stack.__aenter__()

    try:
        for wa in config.worker_agents:
            try:
                tools = await load_mcp_server_tools(
                    _stack,
                    command=wa.command,
                    args=wa.args,
                    env=wa.env or None,
                    description_override=wa.description
                )
                all_tools.extend(tools)
                print(f"  {_c(GREEN, '[+]')} Worker '{wa.name}' → {[t.name for t in tools]}")
            except Exception as exc:
                print(f"  {_c(RED, '[!]')} Worker '{wa.name}' failed: {exc}")

        for mc in config.mcp_clients:
            try:
                tools = await load_mcp_server_tools(
                    _stack,
                    transport=mc.transport,
                    url=mc.url,
                    headers=mc.headers or None,
                    command=mc.command,
                    args=mc.args,
                    env=mc.env or None
                )
                all_tools.extend(tools)
                print(f"  {_c(GREEN, '[+]')} MCP '{mc.name}' ({mc.transport}) → {[t.name for t in tools]}")
            except Exception as exc:
                print(f"  {_c(RED, '[!]')} MCP '{mc.name}' failed: {exc}")

        if not all_tools:
            print(f"  {_c(YELLOW, '[~]')} No tools connected (besides memory) — running LLM-only.")

        # ----------------------------------------------------------------
        # PHASE 2.5 — Add memory tools so LLM can query/save explicitly
        # ----------------------------------------------------------------
        backend = None   # shared instance; also used by summarizer saves below
        if config.memory.enabled:
            from core.memory import get_backend as _get_backend
            from pathlib import Path as _Path
            _mem_dir = _Path(config.memory.memory_dir)
            if not _mem_dir.is_absolute():
                _mem_dir = _Path(__file__).parent / config.memory.memory_dir
            try:
                backend = _get_backend(
                    backend_type=config.memory.backend,
                    memory_dir=_mem_dir,
                    max_save_length=config.memory.max_save_length,
                    rag_server_cfg=config.memory.rag_server,
                )
                from langchain_core.tools import tool as lc_tool
                
                @lc_tool
                def memory_search(query: str, category: Literal["all", "history", "facts"] = "all") -> str:
                    """
                    Search your long-term memory for past tasks and results related to *query*.
                    Use category="history"  for looking up past tool executions and workflows.
                    Use category="facts" for looking up saved notes, preferences, or project details.

                    args:
                        query (str): The search query.
                        category (Literal["all", "history", "facts"]): The category to search in. Defaults to "all".
                    """
                    return backend.search(query, category=category)

                @lc_tool
                def memory_save(fact: str) -> str:
                    """
                    Save an important global fact or note to your long-term memory for future sessions.
                    DO STORE INFORMATION THAT WILL NEED FOR FUTURE TASKS.
                    YOU MUST:
                    DO NOT STORE ANY PRIVATE OR SENSITIVE INFORMATIONS.

                    args:
                        fact (str): The fact to save.
                    """
                    return backend.save_fact(fact)

                all_tools.extend([memory_search, memory_save])
                print(f"  {_c(GREEN, '[+]')} Memory → ['memory_search', 'memory_save'] (backend={config.memory.backend})")
            except Exception as _mem_exc:
                print(f"  {_c(RED, '[!]')} Memory tools failed to load: {_mem_exc}")

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
                print(f"  {_c(GREEN, '[+]')} Image → {[t.name for t in _img_tools]}")
        except Exception as _img_exc:
            print(f"  {_c(RED, '[!]')} Image tools failed to load: {_img_exc}")

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
                print(f"  {_c(GREEN, '[+]')} Audio → {[t.name for t in _aud_tools]}")
        except Exception as _aud_exc:
            print(f"  {_c(RED, '[!]')} Audio tools failed to load: {_aud_exc}")

        # ----------------------------------------------------------------
        # PHASE 2.8 — Skills (catalog + always-inject + load_skill tool)
        # ----------------------------------------------------------------
        _repl_skills = []     # all discovered skills (kept for slash-command lookup)
        _skills_prompt = ""   # catalog block + always-inject content
        try:
            from core.skill_loader import (
                discover_skills, build_catalog_block,
                load_skill_content, make_load_skill_tool,
            )
            _sk_cfg = config.skills
            if _sk_cfg.enabled:
                _repl_skills = discover_skills(_sk_cfg.skills_dirs)
                if _repl_skills:
                    all_tools.append(make_load_skill_tool(_repl_skills))
                    sk_names = [s.name for s in _repl_skills]
                    print(f"  {_c(GREEN, '[+]')} Skills → {sk_names} (load_skill tool registered)")
                    _skills_prompt = build_catalog_block(_repl_skills)
                    for sname in _sk_cfg.always_inject:
                        body = load_skill_content(sname, _repl_skills)
                        print(f"  {_c(GREEN, '[+]')} Skill always-inject: {sname}")
                        _skills_prompt += f"\n\n{body}"
        except Exception as _sk_exc:
            print(f"  {_c(RED, '[!]')} Skills failed to load: {_sk_exc}")

        # Build Orchestrator LLM
        from core.llm import get_llm
        try:
            llm = get_llm(config.model)
        except ImportError as e:
            print(f"  {_c(RED, '[!]')} {e}")
            return

        # Wrap tools in a ToolNode with error handling so that any ToolException
        # (e.g. permission errors, API failures) is caught and returned to the
        # agent as a ToolMessage instead of crashing the graph stream.
        tool_node = ToolNode(all_tools, handle_tool_errors=True)

        # No checkpointer — we manage conversation_history ourselves.
        # MemorySaver was previously used for aupdate_state()-based injection,
        # but that approach has been replaced by the break-and-restart pattern
        # in _run_agent_turn. Keeping MemorySaver caused a critical memory leak:
        # LangGraph's add_messages reducer APPENDS each turn's messages to the
        # checkpoint's accumulated state, so summarization had zero effect on
        # the context actually seen by the graph.
        graph = create_react_agent(
            model=llm,
            tools=tool_node,
        )
        _graph_config: dict = {}   # no thread_id needed without checkpointer

        # tool_desc = "\n".join(
        #     f"  - {t.name}: {getattr(t, 'description', '')}" for t in all_tools
        # )
        # sys_prompt = config.agent.system_prompt + (
        #     f"\n\nAvailable tools:\n{tool_desc}" if tool_desc else ""
        # )

        # ── Persistent conversation history (survives across turns) ───────────
        sys_prompt = config.agent.system_prompt
        # __ Add Current Date and Time to the system prompt
        import datetime
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sys_prompt += f"\n\nCurrent Date and Time: {current_time}\n"
        # __ Prepend skills catalog + always-inject content
        if _skills_prompt:
            sys_prompt = _skills_prompt + "\n\n" + sys_prompt
        conversation_history: list = []
        _archived_count: int = 0   # messages already written to session_archive

        session_manager = None
        if session_id:
            if config.chat_history.backend == "sqlite":
                from core.history_sqlite import SqliteConversationHistory
                from pathlib import Path
                _db_str = config.chat_history.connection_string
                _db_path = Path(_db_str)
                if not _db_path.is_absolute():
                    _mem_dir = Path(config.memory.memory_dir)
                    if not _mem_dir.is_absolute():
                        _mem_dir = Path(__file__).parent / config.memory.memory_dir
                    _db_path = _mem_dir / _db_str
                session_manager = SqliteConversationHistory(db_path=_db_path)
            else:
                logger.warning("Unsupported chat_history backend: %s", config.chat_history.backend)

            history = session_manager.load_session(session_id)
            if history:
                conversation_history = history
                print(f"  {_c(GREEN, '[+]')} Resumed Session: '{session_id}' ({len(history)} messages)")
                # Count already-archived messages so we don't re-archive them
                _archived_count = session_manager.get_archive_count(session_id)

        if not conversation_history:
            conversation_history = [SystemMessage(content=sys_prompt)]
        else:
            # Resumed session: guarantee SystemMessage is always position-0.
            # Summarisation may have trimmed the history that was stored.
            if not isinstance(conversation_history[0], SystemMessage):
                conversation_history.insert(0, SystemMessage(content=sys_prompt))

        current_summary: str = ""             # rolling narrative; updated each compression cycle
        known_global_facts: list[str] = []    # full reconciled global fact list
        known_private_facts: list[str] = []   # full reconciled private fact list
        to_summarize_buffer: list = []        # new msgs since last compression (human + AI + tool)

        # ── Debug Logger ───────────────────────────────────────────────────────
        debug_log_path = None
        if config.agent.debug:
            from pathlib import Path
            from datetime import datetime
            log_dir = Path(".agents/logs/runs")
            log_dir.mkdir(parents=True, exist_ok=True)
            # session_id is always set (defaults to "default") — use it directly
            # In ephemeral mode (--session no) fall back to a timestamp
            sess_name = session_id if session_id else datetime.now().strftime("%Y%m%d_%H%M%S")
            debug_log_path = log_dir / f"{sess_name}.log"
            with open(debug_log_path, "a", encoding="utf-8") as f:
                f.write(f"=== Session Booted: {sess_name} ===\n\n")

        # ── Summarizer (optional; gracefully disabled if not configured) ───────
        from core.conversation_summarizer import ConversationSummarizer
        summarizer = (
            ConversationSummarizer(config.summarizer, config.model)
            if config.summarizer.enabled
            else None
        )

        # ── State for parallel agent execution ──────────────────────────────
        _interrupt_queue: asyncio.Queue = asyncio.Queue()   # mid-run injection queue
        _agent_running: bool = False
        _current_runner: asyncio.Task | None = None

        async def _run_agent_turn(label: str = "[Agent]") -> None:
            """Run one agent turn as a background asyncio.Task.

            When the user types a message mid-run, it lands in _interrupt_queue.
            After each graph step we check the queue. If a message is waiting we:
              1. Break out of the current astream() (saving partial state)
              2. Append the new message to conversation_history
              3. Immediately re-run astream() with the full updated history
            All of this happens inside the SAME Task — _agent_running stays True,
            the prompt stays live, and the agent sees complete context.
            """
            nonlocal conversation_history, current_summary, known_global_facts, \
                     known_private_facts, _archived_count, _agent_running, to_summarize_buffer
            _agent_running = True
            try:
                while True:   # outer loop: re-runs when an interrupt message arrives
                    final_answer = ""
                    last_event: dict | None = None
                    _restart = False

                    async for event in graph.astream(
                        {"messages": conversation_history},
                        _graph_config,
                        stream_mode="values",
                    ):
                        _print_event(event)
                        last_event = event
                        _last_msg = event["messages"][-1]
                        if hasattr(_last_msg, "content") and _last_msg.content:
                            final_answer = _last_msg.content

                        # ── Check for mid-run user / notification messages ─────────
                        # IMPORTANT: Only break at "safe" points in the ReAct cycle.
                        #
                        # LangGraph's ReAct loop alternates:
                        #   agent node  → AIMessage(tool_calls=[...])   ← UNSAFE to break here
                        #   tools node  → ToolMessage(...)               ← SAFE to break here
                        #   agent node  → AIMessage(content="answer")   ← SAFE (final response)
                        #
                        # Breaking after an AIMessage with pending tool_calls leaves an
                        # unresolved tool call in history. LLM providers then raise
                        # "missing tool result" on the very next astream() call.
                        if not _interrupt_queue.empty():
                            _last_step_msg = event["messages"][-1]

                            # Determine whether we're at a clean boundary
                            _has_pending_tool_calls = (
                                isinstance(_last_step_msg, AIMessage)
                                and bool(getattr(_last_step_msg, "tool_calls", None))
                            )

                            if _has_pending_tool_calls:
                                # Not safe yet — the tools node hasn't run to produce
                                # the matching ToolMessages. Let this step finish; we'll
                                # check again on the next event (after the tool result).
                                logger.debug(
                                    "[Inject] Skipping unsafe breakpoint "
                                    "(AIMessage with pending tool_calls). "
                                    "Will retry after tool result."
                                )
                            else:
                                # Safe: either a ToolMessage or a final AIMessage.
                                # Delta-append what was produced so far, then inject
                                # the interrupt message and restart astream().
                                _inj_msg = _interrupt_queue.get_nowait()
                                if last_event is not None:
                                    _n_before = len(conversation_history)
                                    _partial = last_event["messages"][_n_before:]
                                    conversation_history.extend(_partial)
                                    to_summarize_buffer.extend(_partial)
                                conversation_history.append(HumanMessage(content=_inj_msg))
                                to_summarize_buffer.append(HumanMessage(content=_inj_msg))
                                print(
                                    f"\n  {_c(YELLOW, '[~] Mid-run message received — applying to agent:')} "
                                    f"{str(_inj_msg)[:100]}"
                                )
                                _restart = True
                                break   # break out of astream(); outer while will re-run

                    if _restart:
                        # Drain any additional messages that arrived during the break
                        while not _interrupt_queue.empty():
                            _extra = _interrupt_queue.get_nowait()
                            conversation_history.append(HumanMessage(content=_extra))
                            to_summarize_buffer.append(HumanMessage(content=_extra))
                            print(f"  {_c(YELLOW, '[~]')} Additional message queued: {str(_extra)[:80]}")
                        continue  # restart the outer while loop → new astream() call

                    # ── Stream finished normally (no interrupt) ────────────────────
                    # Delta-append: only take messages LangGraph ADDED this turn
                    # (do NOT replace conversation_history wholesale — that undoes any
                    #  previous summarizer crop and causes unbounded growth).
                    if last_event is not None:
                        _n_before = len(conversation_history)
                        _new_msgs = last_event["messages"][_n_before:]
                        conversation_history.extend(_new_msgs)
                        to_summarize_buffer.extend(_new_msgs)
                    break  # exit outer while loop


                # ── Archive new messages before any trimming ───────────────────
                if session_manager and session_id:
                    session_manager.append_to_archive(
                        session_id,
                        conversation_history,
                        already_archived_count=_archived_count,
                    )
                    _archived_count = len(conversation_history)

                # ── Save working-copy session ──────────────────────────────────
                if session_manager and session_id:
                    session_manager.save_session(session_id, conversation_history)

                # ── Rolling summarization ──────────────────────────────────────
                # Triggered by BUFFER size (msgs since last compression), not full
                # history length. Summarizer receives only the buffer + prev_summary.
                if summarizer and summarizer.should_summarize(to_summarize_buffer):
                    orig_len = len(conversation_history)
                    result = await summarizer.summarize(
                        buffer=to_summarize_buffer,
                        prev_summary=current_summary,
                        known_global_facts=known_global_facts,
                        known_private_facts=known_private_facts,
                    )

                    # Rebuild bounded working window:
                    #   [SystemMsg] + [SummaryAIMsg] + [last keep_n raw msgs]
                    _keep_n  = summarizer._keep
                    _sys_msgs = [m for m in conversation_history if isinstance(m, SystemMessage)]
                    _non_sys  = [m for m in conversation_history if not isinstance(m, SystemMessage)]
                    _to_keep  = _non_sys[-_keep_n:] if len(_non_sys) >= _keep_n else _non_sys
                    conversation_history = _sys_msgs + [result.summary_ai_msg] + _to_keep

                    current_summary     = result.summary
                    known_global_facts  = result.global_facts
                    known_private_facts = result.private_facts

                    # Archive the summary message itself (separate single-item call)
                    if session_manager and session_id:
                        session_manager.append_to_archive(
                            session_id, [result.summary_ai_msg], already_archived_count=0,
                        )
                        # IMPORTANT: reset _archived_count to the TRIMMED history length.
                        # _archived_count tracks offset into conversation_history, not DB rows.
                        # After trim, conversation_history is short again — next turn appends
                        # delta from len(conversation_history) onward, which is correct.
                        _archived_count = len(conversation_history)
                        session_manager.save_session(session_id, conversation_history)

                    # Reset buffer — compression cycle done
                    to_summarize_buffer = []

                    if config.summarizer.save_to_memory and backend is not None:
                        try:
                            backend.save(
                                job_id=f"summary_{int(time.time())}",
                                task="Rolling Session Summary",
                                summary=result.summary,
                                session_id=session_id,
                            )
                            for _fact in result.new_global_facts:
                                backend.save_fact(_fact, is_global=True)
                            for _fact in result.new_private_facts:
                                backend.save_fact(_fact, is_global=False, session_id=session_id)
                        except Exception as _mem_exc:
                            logger.warning("[Summarizer] Could not persist to memory: %s", _mem_exc)

                    compressed = orig_len - len(conversation_history)
                    new_facts_count = len(result.new_global_facts) + len(result.new_private_facts)
                    total_facts_known = len(known_global_facts) + len(known_private_facts)
                    print(_c(GREY, f"\n[~] History compressed ({compressed} msgs → summary). "
                                   f"Buffer reset. {new_facts_count} new facts saved. "
                                   f"Total facts: {total_facts_known}. "
                                   f"Working window: {len(conversation_history)} msgs."))

                # ── Print final answer ─────────────────────────────────────────
                print("\n" + "\u2500" * 60)
                if isinstance(final_answer, list):
                    final_answer = "\n".join(
                        b.get("text", str(b)) if isinstance(b, dict) else str(b)
                        for b in final_answer
                    )
                print(f"\n{_c(BOLD, '[Final Answer]')}\n{final_answer}")
                print("\u2500" * 60)

            except asyncio.CancelledError:
                pass
            except Exception as _turn_exc:
                print(ANSI(f"\n{_c(RED, '[ERROR]')} {_turn_exc}"))
                logger.exception("%s turn failed", label)
                if conversation_history and isinstance(conversation_history[-1], HumanMessage):
                    conversation_history.pop()
            finally:
                _agent_running = False

        # ── Notification Listener (optional background task) ────────────────
        notification_queue: asyncio.Queue = asyncio.Queue()
        _notify_task: asyncio.Task | None = None

        if config.notify_server.enabled and config.notify_server.command:
            async def _run_notify_listener() -> None:
                """Background: connects to Agent_notify; captures ctx.info() events via subclass."""
                import os as _os
                import json as _json
                from mcp.client.session import ClientSession as _BaseMCPSession
                from mcp import StdioServerParameters
                from mcp.client.stdio import stdio_client

                # ── Subclass: reliable notification capture via Python MRO ────
                # Monkey-patching _received_notification fails because the SDK's
                # message loop may resolve the method at startup (captured ref).
                # A subclass guarantees our override is called — always.
                _q = notification_queue

                class _CapturingSession(_BaseMCPSession):
                    async def _received_notification(self, notification):
                        try:
                            await super()._received_notification(notification)
                        except Exception:
                            pass

                        # ── Unwrap root union type ─────────────────────────
                        # The mcp SDK wraps notifications in a discriminated union.
                        # The actual LoggingMessageNotification is in .root
                        inner = getattr(notification, "root", notification)
                        method = str(getattr(inner, "method", ""))
                        if "message" not in method:
                            return

                        params_obj = getattr(inner, "params", None)
                        if not params_obj:
                            return

                        data = getattr(params_obj, "data", None) or str(params_obj)
                        try:
                            parsed = _json.loads(data) if isinstance(data, str) else data
                            if not isinstance(parsed, dict):
                                return

                            # "started" confirmation
                            if parsed.get("type") == "started":
                                print(
                                    f"  {_c(GREEN, '[~]')} Agent_notify: "
                                    f"{parsed.get('message', 'monitoring started')}",
                                    flush=True,
                                )
                                return

                            # Real change event
                            if "change" in parsed:
                                change  = parsed["change"]
                                added   = change.get("added",   [])
                                removed = change.get("removed", [])
                                changed = change.get("changed", {})
                                label   = f"{parsed.get('server')}/{parsed.get('tool')}"

                                parts = []
                                if added:   parts.append(f"+{len(added)} new")
                                if removed: parts.append(f"-{len(removed)} removed")
                                if changed and not added and not removed:
                                    parts.append("updated")
                                summary = ", ".join(parts) or "changed"

                                # Print IMMEDIATELY — visible without pressing Enter
                                print(f"\n  {_c(YELLOW, f'[🔔 LIVE] {label} — {summary}')}", flush=True)
                                if added:
                                    preview = _json.dumps(added[0], ensure_ascii=False)
                                    print(f"  → {preview[:160]}", flush=True)

                                # Queue for auto-task runner at top of REPL loop
                                _q.put_nowait(parsed)

                        except Exception as _pe:
                            import sys as _sys
                            print(f"  [Notify] parse error: {_pe}", file=_sys.stderr, flush=True)

                # ── Connect ───────────────────────────────────────────────────
                ns  = config.notify_server
                env = {**_os.environ, **(ns.env or {})}
                srv_params = StdioServerParameters(command=ns.command, args=ns.args, env=env)

                try:
                    async with stdio_client(srv_params) as (read, write):
                        async with _CapturingSession(read, write) as _notify_session:
                            await _notify_session.initialize()
                            print(
                                f"  {_c(GREEN, '[+]')} Notification listener connected → Agent_notify",
                                flush=True,
                            )
                            await _notify_session.call_tool("get_notifications", {})
                except asyncio.CancelledError:
                    pass
                except Exception as _ne:
                    logger.warning("[Notify] Listener error: %s", _ne)

            _notify_task = asyncio.create_task(_run_notify_listener())
            # Yield so the task starts and prints '[+] connected' BEFORE first prompt
            await asyncio.sleep(1.5)

        # ── Setup Prompt Toolkit ──────────────────────────────────────────────
        from prompt_toolkit import PromptSession
        from prompt_toolkit.patch_stdout import patch_stdout

        session = PromptSession()
        
        # 1. Create our two concurrent tasks before the loop starts
        prompt_task = asyncio.create_task(session.prompt_async(ANSI(f"\n{_c(BOLD, '>> Task:')} ")))
        notif_task = asyncio.create_task(notification_queue.get())
        
        # Keep track of tasks that are currently running
        pending_tasks = {prompt_task, notif_task}

        # Wrap the ENTIRE loop in patch_stdout so background prints never garble the prompt
        try:
            with patch_stdout():

                # ── REPL loop ─────────────────────────────────────────────────────────
                while True:
                    # 2. Wait until EITHER the user types a command OR a notification arrives
                    done, pending_tasks = await asyncio.wait(
                        pending_tasks,
                        return_when=asyncio.FIRST_COMPLETED
                    )

                    pending_tasks -= done

                    # ─────────────────────────────────────────────────────────
                    # SCENARIO A: A Notification Arrived!
                    # ─────────────────────────────────────────────────────────
                    if notif_task in done:
                        try:
                            notif = notif_task.result()
                        except asyncio.CancelledError:
                            break

                        # Extract notification data
                        change = notif.get("change", {})
                        server = notif.get("server", "?")
                        tool   = notif.get("tool", "?")
                        added  = change.get("added", [])
                        _notif_label = f"{server}/{tool}"

                        print(f"\n{_c(YELLOW, f'[🔔 Notification] {_notif_label} — {len(added)} new item(s)')}")

                        if added:
                            import json as _j
                            auto_task = (
                                f"[Auto-Task from {_notif_label}]\n"
                                f"New items detected via notification:\n"
                                f"{_j.dumps(added, indent=2)}\n\n"
                                f"Analyse and act on these new items appropriately."
                            )
                            print(f"{_c(BOLD, '[Auto-Task]')} {auto_task[:120]}...\n" + "─" * 60)

                            if _agent_running:
                                # ── Agent mid-run: inject into the live graph ─────────────────
                                _interrupt_queue.put_nowait(auto_task)
                                print(f"  {_c(YELLOW, '[~]')} Notification injected into running agent turn.")
                            else:
                                # ── No agent running: start a fresh turn ──────────────────────
                                conversation_history.append(HumanMessage(content=auto_task))
                                to_summarize_buffer.append(HumanMessage(content=auto_task))
                                _current_runner = asyncio.create_task(_run_agent_turn("[Auto-Task]"))

                        # Re-arm the notification task
                        notif_task = asyncio.create_task(notification_queue.get())
                        pending_tasks.add(notif_task)

                    if prompt_task in done:
                        try:
                            task_text = prompt_task.result().strip()
                        except (EOFError, KeyboardInterrupt):
                            print("\n\nExiting.")
                            break

                        if task_text.lower() in {"quit", "exit", "q"}:
                            print("Exiting.")
                            break

                        if task_text:
                            if _agent_running:
                                # ── Agent mid-run: inject the message into the live graph ──────
                                # aupdate_state writes the HumanMessage into checkpoint state;
                                # the running astream loop picks it up on its very next step.
                                _interrupt_queue.put_nowait(task_text)
                                print(f"  {_c(YELLOW, '[~]')} Message injected into running agent turn.")
                            else:
                                # ── No agent running: start a fresh turn ──────────────────────
                                try:
                                    task_text_copy: str = task_text

                                    # --- Auto-Inject RAG Context ---
                                    if config.memory.enabled and config.memory.auto_feed_top_k > 0:
                                        try:
                                            context_str = backend.search(
                                                task_text,
                                                category=config.memory.auto_feed_category,
                                                session_id=session_id,
                                            )
                                            MAX_CONTEXT_CHARS = 4000
                                            if len(context_str) > MAX_CONTEXT_CHARS:
                                                context_str = context_str[:MAX_CONTEXT_CHARS] + "\n...[truncated]"
                                            if context_str.strip() and "No relevant" not in context_str:
                                                print(f"  {_c(GREY, '[~]')} Auto-injected {len(context_str)} chars of memory context.")
                                                task_text = f"[System: Relevant Past Memory]\n{context_str}\n\n[User Task]\n{task_text}"
                                        except Exception as e:
                                            logger.warning(f"Failed to auto-fetch RAG context: {e}")

                                    # --- /skillname slash-command injection ---
                                    if (
                                        _repl_skills
                                        and config.skills.enabled
                                        and config.skills.prompt_skill_trigger
                                    ):
                                        try:
                                            from core.skill_loader import extract_slash_commands, load_skill_content
                                            task_text, _triggered = extract_slash_commands(task_text, _repl_skills)
                                            for _sk in _triggered:
                                                _full = load_skill_content(_sk.name, _repl_skills)
                                                task_text = f"[Skill Loaded: {_sk.name}]\n{_full}\n\n" + task_text
                                                print(f"  {_c(GREEN, '[+]')} Skill loaded: {_sk.name}")
                                        except Exception as _ske:
                                            logger.warning("[Skills] Slash-command error: %s", _ske)

                                    conversation_history.append(HumanMessage(content=task_text))
                                    to_summarize_buffer.append(HumanMessage(content=task_text))
                                    logger.debug(f"User Task with RAG context: {task_text}")
                                    print(f"\n{_c(BOLD, '[Task]')} {task_text_copy}\n" + "─" * 60)

                                    # --- Write exact LLM prompt to debug log ---
                                    if debug_log_path:
                                        try:
                                            import json
                                            from langchain_core.messages import messages_to_dict
                                            with open(debug_log_path, "a", encoding="utf-8") as f:
                                                f.write(f"\n--- [TURN] PROMPT FED TO LLM ---\n")
                                                f.write(json.dumps(messages_to_dict(conversation_history), indent=2))
                                                f.write("\n\n")
                                        except Exception as e:
                                            logger.error(f"Failed to write to debug log: {e}")

                                    # Launch agent as a background task — prompt re-arms immediately
                                    _current_runner = asyncio.create_task(_run_agent_turn("[User]"))

                                except Exception as exc:
                                    print(ANSI(f"\n{_c(RED, '[ERROR]')} {exc}"))
                                    logger.exception("interactive_loop task failed")
                                    if conversation_history and isinstance(conversation_history[-1], HumanMessage):
                                        conversation_history.pop()

                        # Re-arm prompt IMMEDIATELY — user can always type, even mid-run
                        prompt_task = asyncio.create_task(session.prompt_async(ANSI(f"\n{_c(BOLD, '>> Task:')} ")))
                        pending_tasks.add(prompt_task)

        except (KeyboardInterrupt, asyncio.CancelledError):
            print("\n\nExiting.")
        finally:
            # Clean up all tasks cleanly on Ctrl+C / exit
            for t in list(pending_tasks):
                t.cancel()
            if _current_runner and not _current_runner.done():
                _current_runner.cancel()
            if _notify_task:
                _notify_task.cancel()

            _all_cleanup = list(pending_tasks)
            if _current_runner:
                _all_cleanup.append(_current_runner)
            if _notify_task:
                _all_cleanup.append(_notify_task)
            await asyncio.gather(*_all_cleanup, return_exceptions=True)

    except Exception as main_exc:
        print(ANSI(f"\n{_c(RED, '[FATAL ERROR]')} {main_exc}"))
        logger.exception("interactive_loop failed during setup")
# ---------------------------------------------------------------------------
# CLI argument parser
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Agent_head — Main Autonomous Orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py
  python main.py --task "Summarise all .py files in Agent_a"
  python main.py --config my_config.yaml
  python main.py --model gpt-4o --provider openai --api-key sk-...
  python main.py --model gemini-2.0-flash --provider gemini --api-key AIza...
  python main.py --setup
  python main.py --setup /path/to/my/project
        """,
    )
    p.add_argument("--task", "-t", type=str, default=None,
                   help="Run a single task non-interactively and exit.")
    p.add_argument("--session", "-s", type=str, default=None,
                   help="Resume or start a persistent session by ID.")
    p.add_argument("--config", "-c", type=str, default=None,
                   help="Path to a custom config.yaml.")
    p.add_argument("--model", "-m", type=str, default=None,
                   help="Override the model name from config.")
    p.add_argument("--provider", "-p", type=str, default=None,
                   help="Override the LLM provider (ollama/openai/gemini).")
    p.add_argument("--api-key", type=str, default=None,
                   help="API key override.")
    p.add_argument("--base-url", type=str, default=None,
                   help="Base URL override.")
    p.add_argument("--setup", nargs="?", const="", default=None, metavar="DIR",
                   help="Copy the bundled config files to DIR for editing. "
                        "Omit DIR to use the current working directory.")
    p.add_argument("-y", "--yes", action="store_true",
                   help="Skip prompts and accept defaults (e.g. for --setup).")
    return p.parse_args()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _export_config(dest_dir: str, yes_mode: bool = False) -> None:
    """Copy the bundled config.yaml and service_config/ into <dest_dir>/.agents/."""
    import shutil
    from pathlib import Path

    # Always write into the hidden .agents subfolder
    dest = (Path(dest_dir).resolve() / ".agents")
    pkg_root = Path(__file__).parent
    pkg_config = pkg_root / "config.yaml"
    pkg_service = pkg_root / "service_config"

    dest.mkdir(parents=True, exist_ok=True)

    # Copy config.yaml
    dest_config = dest / "config.yaml"
    if dest_config.exists():
        overwrite = "y" if yes_mode else input(f"  .agents/config.yaml already exists at {dest_config}. Overwrite? [y/N] ").strip().lower()
        if overwrite != "y":
            print("  Skipped config.yaml")
        else:
            shutil.copy2(pkg_config, dest_config)
            print(f"  \u2713 Copied config.yaml \u2192 {dest_config}")
    else:
        shutil.copy2(pkg_config, dest_config)
        print(f"  \u2713 Copied config.yaml \u2192 {dest_config}")

    # Copy service_config/
    dest_service = dest / "service_config"
    if dest_service.exists():
        overwrite = "y" if yes_mode else input(f"  .agents/service_config/ already exists at {dest_service}. Overwrite? [y/N] ").strip().lower()
        if overwrite != "y":
            print("  Skipped service_config/")
        else:
            shutil.copytree(pkg_service, dest_service, dirs_exist_ok=True)
            print(f"  \u2713 Copied service_config/ \u2192 {dest_service}")
    else:
        shutil.copytree(pkg_service, dest_service)
        print(f"  \u2713 Copied service_config/ \u2192 {dest_service}")

    print(f"\n  Done! Config written to: {dest}")
    print(f"  Run 'agent-head' from '{dest_dir}' and it will auto-load .agents/config.yaml")


def _cli_entry() -> None:
    args = parse_args()

    # --setup [DIR]: export config files for editing and exit
    if args.setup is not None:
        print("\n" + "═" * 60)
        print("  Agent_head — Setup Config")
        print("═" * 60)
        dest = args.setup.strip()
        if not dest:
            if args.yes:
                dest = os.getcwd()
                print(f"  Using current working directory: {dest}")
            else:
                # No DIR given on CLI; prompt user, defaulting to CWD
                dest = input(
                    f"\n  Enter destination directory [default: current dir '{os.getcwd()}']: "
                ).strip()
        if not dest:
            dest = os.getcwd()
            print(f"  Using current working directory: {dest}")
        _export_config(dest, yes_mode=args.yes)
        return

    common = dict(
        config_path=args.config,
        model_override=args.model,
        provider_override=args.provider,
        api_key_override=args.api_key,
        base_url_override=args.base_url,
        session_id=args.session,
    )

    if args.task:
        # Single-shot mode
        result = asyncio.run(run(task=args.task, **common))
        print("\n" + "─" * 60)
        print(f"\n{_c(BOLD, '[Final Answer]')}\n{result}")
        print("─" * 60)
    else:
        # Interactive REPL
        asyncio.run(interactive_loop(**common))


if __name__ == "__main__":
    _cli_entry()
