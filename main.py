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
) -> str:
    """
    Load config, optionally override model settings, then run the orchestrator.
    Returns the final answer string.
    """
    import os
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

    answer = await run_orchestrator(task=task, config=config)
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
) -> None:
    import os
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
    from langgraph.prebuilt import create_react_agent
    from contextlib import AsyncExitStack
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from langchain_mcp_adapters.tools import load_mcp_tools
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
                params = StdioServerParameters(
                    command=wa.command, args=wa.args, env=wa.env or None
                )
                r, w = await _stack.enter_async_context(stdio_client(params))
                sess = await _stack.enter_async_context(ClientSession(r, w))
                await sess.initialize()
                tools = await load_mcp_tools(sess)
                all_tools.extend(tools)
                print(f"  {_c(GREEN, '[+]')} Worker '{wa.name}' → {[t.name for t in tools]}")
            except Exception as exc:
                print(f"  {_c(RED, '[!]')} Worker '{wa.name}' failed: {exc}")

        for mc in config.mcp_clients:
            try:
                params = StdioServerParameters(
                    command=mc.command, args=mc.args, env=mc.env or None
                )
                r, w = await _stack.enter_async_context(stdio_client(params))
                sess = await _stack.enter_async_context(ClientSession(r, w))
                await sess.initialize()
                tools = await load_mcp_tools(sess)
                all_tools.extend(tools)
                print(f"  {_c(GREEN, '[+]')} MCP '{mc.name}' → {[t.name for t in tools]}")
            except Exception as exc:
                print(f"  {_c(RED, '[!]')} MCP '{mc.name}' failed: {exc}")

        if not all_tools:
            print(f"  {_c(YELLOW, '[~]')} No tools connected (besides memory) — running LLM-only.")

        # ----------------------------------------------------------------
        # PHASE 2.5 — Add memory tools so LLM can query/save explicitly
        # ----------------------------------------------------------------
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
                    """Save an important fact or note to your long-term memory for future sessions.

                    args:
                        fact (str): The fact to save.
                    """
                    return backend.save_fact(fact)

                all_tools.extend([memory_search, memory_save])
                print(f"  {_c(GREEN, '[+]')} Memory → ['memory_search', 'memory_save'] (backend={config.memory.backend})")
            except Exception as _mem_exc:
                print(f"  {_c(RED, '[!]')} Memory tools failed to load: {_mem_exc}")

        # Build LLM
        provider = config.model.provider.lower()
        if provider == "openai":
            llm = ChatOpenAI(
                model=config.model.model_name,
                temperature=config.model.temperature,
                api_key=config.model.api_key,
                base_url=(
                    config.model.base_url
                    if config.model.base_url != "http://localhost:11434"
                    else None
                ),
            )
        elif provider == "gemini":
            llm = ChatGoogleGenerativeAI(
                model=config.model.model_name,
                temperature=config.model.temperature,
                api_key=config.model.api_key,
            )
        else:
            llm = ChatOllama(
                model=config.model.model_name,
                temperature=config.model.temperature,
                base_url=config.model.base_url,
            )

        graph = create_react_agent(model=llm, tools=all_tools)

        tool_desc = "\n".join(
            f"  - {t.name}: {getattr(t, 'description', '')}" for t in all_tools
        )
        sys_prompt = config.agent.system_prompt + (
            f"\n\nAvailable tools:\n{tool_desc}" if tool_desc else ""
        )

        # ── Persistent conversation history (survives across turns) ───────────
        conversation_history: list = [SystemMessage(content=sys_prompt)]
        current_summary: str = ""       # rolling narrative; updated each compression cycle
        known_facts: list[str] = []     # full reconciled fact list; replaced each cycle

        # ── Summarizer (optional; gracefully disabled if not configured) ───────
        from core.conversation_summarizer import ConversationSummarizer
        summarizer = (
            ConversationSummarizer(config.summarizer, config.model)
            if config.summarizer.enabled
            else None
        )

        # ── REPL loop ─────────────────────────────────────────────────────────
        while True:
            try:
                task = input(f"\n{_c(BOLD, '>> Task:')} ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n\nExiting.")
                break

            if not task:
                continue
            if task.lower() in {"quit", "exit", "q"}:
                print("Exiting.")
                break

            try:
                # Append the new user message to running history
                conversation_history.append(HumanMessage(content=task))

                # Inject known_facts into the system prompt for the current turn
                if conversation_history and isinstance(conversation_history[0], SystemMessage):
                    dynamic_sys = sys_prompt
                    if known_facts:
                        facts_str = "\n".join(f"- {f}" for f in known_facts)
                        dynamic_sys += f"\n\n[Session Known Facts]\n{facts_str}"
                    conversation_history[0] = SystemMessage(content=dynamic_sys)

                print(f"\n{_c(BOLD, '[Task]')} {task}\n" + "─" * 60)
                final_answer = ""

                async for event in graph.astream({"messages": conversation_history}, stream_mode="values"):
                    _print_event(event)
                    last = event["messages"][-1]
                    if hasattr(last, "content") and last.content:
                        final_answer = last.content

                # Append the assistant's reply to history so next turn sees it
                if final_answer:
                    ai_reply = final_answer
                    if isinstance(ai_reply, list):
                        ai_reply = "\n".join(
                            b.get("text", str(b)) if isinstance(b, dict) else str(b)
                            for b in ai_reply
                        )
                    conversation_history.append(_AIMessage(content=ai_reply))

                # ── Rolling summarization ─────────────────────────────────────
                if summarizer and summarizer.should_summarize(conversation_history):
                    orig_len = len(conversation_history)
                    result = await summarizer.summarize(
                        history=conversation_history,
                        prev_summary=current_summary,
                        known_facts=known_facts,
                    )
                    conversation_history = result.trimmed_history
                    current_summary = result.summary         # replace with updated narrative
                    known_facts = result.facts               # replace entirely (handles corrections)

                    if config.summarizer.save_to_memory:
                        # Import here to avoid circular dep at module level
                        from core.memory import get_backend as _get_backend
                        from pathlib import Path as _Path
                        _mem_cfg = config.memory
                        _mem_dir = _Path(_mem_cfg.memory_dir)
                        if not _mem_dir.is_absolute():
                            _mem_dir = _Path(__file__).parent / _mem_cfg.memory_dir
                        try:
                            _backend = _get_backend(
                                backend_type=_mem_cfg.backend,
                                memory_dir=_mem_dir,
                                max_save_length=_mem_cfg.max_save_length,
                            )
                            _backend.save_fact(f"[Session summary] {result.summary}")
                            for fact in result.new_or_changed:  # only new/changed
                                _backend.save_fact(fact)
                        except Exception as _mem_exc:
                            logger.warning("[Summarizer] Could not persist to memory: %s", _mem_exc)

                    compressed = orig_len - len(conversation_history)
                    print(_c(GREY, f"\n[~] History compressed ({compressed} msgs -> summary). "
                                   f"{len(result.new_or_changed)} new/changed facts saved. "
                                   f"Total facts known: {len(known_facts)}."))

                print("\n" + "─" * 60)
                if isinstance(final_answer, list):
                    final_answer = "\n".join(
                        b.get("text", str(b)) if isinstance(b, dict) else str(b)
                        for b in final_answer
                    )
                print(f"\n{_c(BOLD, '[Final Answer]')}\n{final_answer}")
                print("─" * 60)

            except Exception as exc:
                print(f"\n{_c(RED, '[ERROR]')} {exc}")
                logger.exception("interactive_loop task failed")
                # Remove the failed user message so history stays consistent
                if conversation_history and isinstance(conversation_history[-1], HumanMessage):
                    conversation_history.pop()

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
