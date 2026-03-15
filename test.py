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
    return f"\033[{code}m{text}\033[0m"


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
                    Use category="history" for looking up past tool executions and workflows.
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

        graph = create_react_agent(
            model=llm,
            tools=tool_node,
        )

        # tool_desc = "\n".join(
        #     f"  - {t.name}: {getattr(t, 'description', '')}" for t in all_tools
        # )
        # sys_prompt = config.agent.system_prompt + (
        #     f"\n\nAvailable tools:\n{tool_desc}" if tool_desc else ""
        # )

        # ── Persistent conversation history (survives across turns) ───────────
        sys_prompt = config.agent.system_prompt 
        conversation_history: list = []
        
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
                
        if not conversation_history:
            conversation_history = [SystemMessage(content=sys_prompt)]

        current_summary: str = ""             # rolling narrative; updated each compression cycle
        known_global_facts: list[str] = []    # full reconciled global fact list
        known_private_facts: list[str] = []   # full reconciled private fact list

        # ── Debug Logger ───────────────────────────────────────────────────────
        debug_log_path = None
        if config.agent.debug:
            from pathlib import Path
            from datetime import datetime
            log_dir = Path("logs/runs")
            log_dir.mkdir(parents=True, exist_ok=True)
            # Use session_id if resumed, else generate a fresh timestamp
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
        with patch_stdout():

        # ── REPL loop ─────────────────────────────────────────────────────────
            while True:
                # 2. Wait until EITHER the user types a command OR a notification arrives
                done, pending_tasks = await asyncio.wait(
                    pending_tasks,
                    return_when=asyncio.FIRST_COMPLETED
                )

                # ─────────────────────────────────────────────────────────
                # SCENARIO A: A Notification Arrived!
                # ─────────────────────────────────────────────────────────
                if notif_task in done:
                    notif = notif_task.result()
                    
                    # Extract your notification data
                    change = notif.get("change", {})
                    server = notif.get("server", "?")
                    tool   = notif.get("tool", "?")
                    added  = change.get("added", [])
                    label  = f"{server}/{tool}"

                    print(f"\n{_c(YELLOW, f'[🔔 Notification] {label} — {len(added)} new item(s)')}")

                    if added:
                        import json as _j
                        auto_task = (
                            f"[Auto-Task from {label}]\n"
                            f"New items detected via notification:\n"
                            f"{_j.dumps(added, indent=2)}\n\n"
                            f"Analyse and act on these new items appropriately."
                        )
                        conversation_history.append(HumanMessage(content=auto_task))
                        print(f"{_c(BOLD, '[Auto-Task]')} {auto_task[:120]}...\n" + "─" * 60)
                        
                        # Run the Agent Graph!
                        # (Because patch_stdout is active, this will cleanly print above the user's current prompt)
                        final_answer = ""
                        last_event = None
                        async for event in graph.astream(
                            {"messages": conversation_history}, stream_mode="values"
                        ):
                            _print_event(event)
                            last_event = event
                            last = event["messages"][-1]
                            if hasattr(last, "content") and last.content:
                                final_answer = last.content
                                
                        if last_event is not None:
                            conversation_history = list(last_event["messages"])
                            
                        print(f"\n{_c(BOLD, '[Auto-Answer]')}\n{final_answer}\n" + "─" * 60)

                    # 3. RE-ARM the notification task so we can catch the next one!
                    notif_task = asyncio.create_task(notification_queue.get())
                    pending_tasks.add(notif_task)

                # try:
                #     # Use asyncio.to_thread so the event loop stays free while
                #     # waiting for input — this lets the notification background
                #     # task run concurrently instead of being starved.
                #     task = (await asyncio.to_thread(
                #         input, f"\n{_c(BOLD, '>> Task:')} "
                #     )).strip()

                if prompt_task in done:
                    try:
                        # .result() will catch EOFError/KeyboardInterrupt if Ctrl+C is pressed
                        task_text = prompt_task.result().strip()
                    except (EOFError, KeyboardInterrupt):
                        print("\n\nExiting.")
                        break

                    if task_text.lower() in {"quit", "exit", "q"}:
                        print("Exiting.")
                        break
                        
                    if task_text:

                        try:
                            # --- Auto-Inject RAG Context ---
                            if config.memory.enabled and config.memory.auto_feed_top_k > 0:
                                try:
                                    # Grab the backend initialized earlier in PHASE 2.5
                                    context_str = backend.search(
                                        task_text, 
                                        category=config.memory.auto_feed_category,
                                        session_id=session_id
                                    )
                                    
                                    # We do a basic split/truncate to avoid huge windows.
                                    # For RAG, each backend might format differently, but a raw character limit is safe.
                                    MAX_CONTEXT_CHARS = 4000
                                    if len(context_str) > MAX_CONTEXT_CHARS:
                                        context_str = context_str[:MAX_CONTEXT_CHARS] + "\n...[truncated]"
                                        
                                    if context_str.strip() and "No relevant" not in context_str:
                                        print(f"  {_c(GREY, '[~]')} Auto-injected {len(context_str)} chars of memory context.")
                                        task_text = f"[System: Relevant Past Memory]\n{context_str}\n\n[User Task]\n{task_text}"
                                except Exception as e:
                                    logger.warning(f"Failed to auto-fetch RAG context: {e}")

                            # Append the (potentially enriched) new user message to running history
                            conversation_history.append(HumanMessage(content=task_text))

                            print(f"\n{_c(BOLD, '[Task]')} {task_text}\n" + "─" * 60)
                            final_answer = ""

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

                            # ── Debug Logger For Prompts  ──────────────────────────────────────────
                            # debug_log_path = None
                            # if config.agent.debug:
                            #     from pathlib import Path
                            #     from datetime import datetime
                            #     log_prompt_dir = Path("logs/prompts")
                            #     log_prompt_dir.mkdir(parents=True, exist_ok=True)
                            #     # Use session_id if resumed, else generate a fresh timestamp
                            #     sess_name = session_id if session_id else datetime.now().strftime("%Y%m%d_%H%M%S")
                            #     debug_log_prompt_path = log_prompt_dir / f"{sess_name}.log"
                            #     with open(debug_log_prompt_path, "a", encoding="utf-8") as f:
                            #         f.write(f"=== full prompt: {conversation_history} ===\n\n")
                            # ── Debug Logger For Prompts ───────────────────────────────────────────


                            last_event: dict | None = None
                            async for event in graph.astream({"messages": conversation_history}, stream_mode="values"):
                                _print_event(event)
                                last_event = event
                                last = event["messages"][-1]
                                if hasattr(last, "content") and last.content:
                                    final_answer = last.content

                            # ── Replace history with the FULL graph output ─────────────────
                            # LangGraph streams the complete cumulative message list on every
                            # step. The final event contains: SystemMsg + HumanMsg + all
                            # intermediate AIMsg(tool_calls=[...]) + ToolMsg + final AIMsg.
                            # Capturing this preserves tool results across REPL turns so the
                            # agent won't re-call the same tools for the same information.
                            if last_event is not None:
                                conversation_history = list(last_event["messages"])

                            # Save the persistent session to SQLite if active
                            if session_manager and session_id:
                                session_manager.save_session(session_id, conversation_history)

                            # ── Rolling summarization ─────────────────────────────────────
                            if summarizer and summarizer.should_summarize(conversation_history):
                                orig_len = len(conversation_history)
                                result = await summarizer.summarize(
                                    history=conversation_history,
                                    prev_summary=current_summary,
                                    known_global_facts=known_global_facts,
                                    known_private_facts=known_private_facts,
                                )
                                conversation_history = result.trimmed_history
                                current_summary = result.summary         # replace with updated narrative
                                known_global_facts = result.global_facts # replace entirely (handles corrections)
                                known_private_facts = result.private_facts

                                # Update the persistent session to SQLite with the newly trimmed history
                                if session_manager and session_id:
                                    session_manager.save_session(session_id, conversation_history)

                                if config.summarizer.save_to_memory and backend is not None:
                                    # Reuse the SAME backend instance (and therefore the same RAG
                                    # server subprocess) that handles auto-inject search above.
                                    # Creating a second backend here would spawn a second RAG server
                                    # process writing to the same ChromaDB files simultaneously —
                                    # that causes ChromaDB HNSW 'Error finding id' race conditions.
                                    try:
                                        # Save the session narrative into the isolated history namespace
                                        backend.save(
                                            job_id=f"summary_{int(time.time())}",
                                            task="Rolling Session Summary",
                                            summary=result.summary,
                                            session_id=session_id
                                        )
                                        # Save factual learnings into the global facts namespace
                                        for fact in result.new_global_facts:
                                            backend.save_fact(fact, is_global=True)

                                        # Save private factual learnings
                                        for fact in result.new_private_facts:
                                            backend.save_fact(fact, is_global=False, session_id=session_id)
                                    except Exception as _mem_exc:
                                        logger.warning("[Summarizer] Could not persist to memory: %s", _mem_exc)

                                compressed = orig_len - len(conversation_history)
                                new_facts_count = len(result.new_global_facts) + len(result.new_private_facts)
                                total_facts_known = len(known_global_facts) + len(known_private_facts)
                                print(_c(GREY, f"\n[~] History compressed ({compressed} msgs -> summary). "
                                            f"{new_facts_count} new/changed facts saved. "
                                            f"Total facts known: {total_facts_known}."))

                            print("\n" + "─" * 60)
                            if isinstance(final_answer, list):
                                final_answer = "\n".join(
                                    b.get("text", str(b)) if isinstance(b, dict) else str(b)
                                    for b in final_answer
                                )
                            print(ANSI(f"\n{_c(BOLD, '[Final Answer]')}\n{final_answer}"))
                            print("─" * 60)
                        

                        except Exception as exc:
                            print(ANSI(f"\n{_c(RED, '[ERROR]')} {exc}"))
                            logger.exception("interactive_loop task failed")
                            # Remove the failed user message so history stays consistent
                            if conversation_history and isinstance(conversation_history[-1], HumanMessage):
                                conversation_history.pop()

                    prompt_task = asyncio.create_task(session.prompt_async(ANSI(f"\n{_c(BOLD, '>> Task:')} ")))
                    pending_tasks.add(prompt_task)
    finally:
        await _stack.__aexit__(None, None, None)


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
    return p.parse_args()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _cli_entry() -> None:
    args = parse_args()

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
