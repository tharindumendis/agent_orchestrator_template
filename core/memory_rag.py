"""
core/memory_rag.py
------------------
RAG-backed long-term memory for Agent_head.
Uses an MCP client in a background thread to communicate with the Agent_rag server.
"""

from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from concurrent.futures import Future
import os

from core.memory import MemoryBackend

logger = logging.getLogger(__name__)

# We use the config-provided command and args to spawn the RAG server.

class SyncRagMCPClient:
    """
    A synchronous wrapper around the asynchronous MCP stdio client.
    Spawns the RAG server subprocess and exposes its tools synchronously.

    Thread-safety note:
        All tool calls are serialized via _call_lock. This prevents a
        stale-read race where a search() for Turn N+1 executes before the
        save() from Turn N has fully completed on the MCP server.
        Without this lock, both calls are submitted to the asyncio loop nearly
        simultaneously and the loop may run them in either order.
    """
    def __init__(self, command: str, args: list[str], env: dict | None = None):
        self._command = command
        self._args = args
        
        # Merge the basic OS environ with our custom overrides
        cwd_env = dict(os.environ)
        if env:
            cwd_env.update(env)
        self._env = cwd_env
        
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._ready_event = threading.Event()
        self._session = None
        self._exit_stack = None
        # ── Serialise all tool calls so writes are always visible to the
        #    next read, regardless of which thread triggers each call. ──────
        self._call_lock = threading.Lock()
        self._thread.start()
        self._ready_event.wait(timeout=10.0)
        if self._session is None:
            raise RuntimeError("RagMemoryBackend failed to initialize MCP client.")

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._startup())
        self._loop.run_forever()

    async def _startup(self):
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
            from contextlib import AsyncExitStack

            params = StdioServerParameters(
                command=self._command,
                args=self._args,
                env=self._env,
            )

            self._exit_stack = AsyncExitStack()
            read, write = await self._exit_stack.enter_async_context(stdio_client(params))
            self._session = await self._exit_stack.enter_async_context(ClientSession(read, write))
            await self._session.initialize()
            
            # Ensure tools are available
            await self._session.list_tools()
        except Exception as e:
            logger.error("[Memory:rag] MCP client startup failed: %s", e)
        finally:
            self._ready_event.set()

    def call_tool_sync(self, name: str, arguments: dict) -> str:
        """
        Call a tool synchronously by dispatching to the background loop.

        Acquires _call_lock so concurrent callers (e.g. a save() from a
        LangGraph node and a search() from the next conversation turn) are
        strictly ordered — one finishes completely before the next starts.
        """
        if not self._session:
            logger.error("[Memory:rag] MCP session not initialized — cannot call '%s'", name)
            return "ERROR: MCP session not initialized."

        with self._call_lock:
            future = asyncio.run_coroutine_threadsafe(
                self._session.call_tool(name, arguments),
                self._loop
            )
            try:
                result = future.result(timeout=60.0)
                return result.content[0].text if result.content else ""
            except asyncio.TimeoutError:
                logger.error("[Memory:rag] Tool call '%s' timed out after 60s", name)
                return "ERROR: timeout"
            except Exception as e:
                exc_type = type(e).__name__
                exc_msg = str(e) or "(no message)"
                logger.error(
                    "[Memory:rag] Tool call '%s' failed: [%s] %s\n%s",
                    name, exc_type, exc_msg, traceback.format_exc(),
                )
                return f"ERROR: [{exc_type}] {exc_msg}"



class RagMemoryBackend(MemoryBackend):
    """
    RAG-backed memory.
    Ingests and searches memories via the Agent_rag server.
    """

    def __init__(self, memory_dir: str | Path, max_save_length: int = 500, rag_server_cfg=None):
        if not rag_server_cfg or not rag_server_cfg.command:
            raise ValueError("[Memory:rag] Missing 'rag_server' config block with 'command' in config.yaml.")
            
        # Initialise the background MCP client once
        self._mcp = SyncRagMCPClient(
            command=rag_server_cfg.command,
            args=rag_server_cfg.args,
            env=rag_server_cfg.env,
        )
        self._col_history = f"{rag_server_cfg.collection}_history"
        self._col_facts = f"{rag_server_cfg.collection}_facts"
        self._max_len = max_save_length
        logger.info("[Memory:rag] Connected to RAG server at %s", rag_server_cfg.command)

    # ── MemoryBackend interface ────────────────────────────────────────

    def save(
        self,
        job_id: str,
        task: str,
        summary: str,
        tools_used: list[str] | None = None,
        outcome: str = "success",
        session_id: str | None = None,
    ) -> None:
        """
        Ingests the job record into the RAG collection as a text string.
        If session_id is provided, the history is isolated to that session's namespace.
        """
        entry = {
            "job_id": job_id,
            "ts": datetime.now(timezone.utc).isoformat(),
            "task": task[:300],
            "summary": summary[:self._max_len],
            "tools_used": tools_used or [],
            "outcome": outcome,
        }
        
        text_content = (
            f"[{entry['ts']}] [{entry['outcome'].upper()}] Task: {entry['task']}\n"
            f"Summary: {entry['summary']}\n"
            f"Tools used: {', '.join(entry['tools_used']) or 'none'}"
        )
        
        target_col = self._col_history
        metadata = {"session_id": session_id} if session_id else {}
        self._mcp.call_tool_sync(
            "rag_ingest",
            {"source": text_content, "collection": target_col, "metadata": metadata}
        )
        logger.info("[Memory:rag] Saved job %s to collection %s (session_id: %s)", job_id, target_col, session_id)

    def search(self, query: str, top_k: int = 5, category: str = "all", session_id: str | None = None) -> str:
        """Call rag_search on the targeted collection(s)."""
        history_col = self._col_history
        facts_col = self._col_facts
        
        metadata_filter = {"session_id": session_id} if session_id else None

        combined = []
        logger.debug(f"[DEBUG RAG] Starting search with query='{query}', top_k={top_k}, category='{category}', session_id='{session_id}'")
        
        # Helper to search and append
        def _search_append(col: str, title: str, k: int, m_filter: dict | None = None):
            logger.debug("[Memory:rag] Searching '%s' (k=%d, filter=%s)", col, k, m_filter)
            if not col: return
            args = {"query": query, "collection": col, "top_k": k}
            if m_filter:
                args["metadata_filter"] = m_filter
                
            res = self._mcp.call_tool_sync("rag_search", args)
            if res.startswith("ERROR"):
                logger.warning("[Memory:rag] Search '%s' in '%s' returned: %s", query[:50], col, res)
            elif "No results" not in res:
                combined.append(f"=== {title} ===\n{res}")
            else:
                logger.debug("[Memory:rag] %s: no results for '%s'", title, query[:50])

        if category == "facts":
            _search_append(self._col_facts, "GLOBAL FACTS", top_k, m_filter={"is_global": "true"})
            if metadata_filter:
                m_filter_priv = {"$and": [{"is_global": "false"}, metadata_filter]}
                _search_append(self._col_facts, "PRIVATE FACTS", top_k, m_filter=m_filter_priv)
        elif category == "history":
            _search_append(history_col, "HISTORY RESULTS", top_k, m_filter=metadata_filter)

        elif category == "all":
            logger.debug(f"[DEBUG RAG] Searching HISTORY and GLOBAL FACTS with category 'all' and query '{query}' and metadata_filter={metadata_filter}")
            k_half = max(1, top_k//2)
            _search_append(history_col, "HISTORY RESULTS", k_half, m_filter=metadata_filter)
            _search_append(self._col_facts, "GLOBAL FACTS", k_half, m_filter={"is_global": "true"})
            if metadata_filter:
                logger.debug(f"[DEBUG RAG] Searching PRIVATE FACTS with category 'all' and query '{query}' and metadata_filter={metadata_filter}")
                m_filter_priv = {"$and": [{"is_global": "false"}, metadata_filter]}
                _search_append(self._col_facts, "PRIVATE FACTS", top_k, m_filter=m_filter_priv)
        else:
            # Combine all if category is "all"
            logger.debug(f"[DEBUG RAG] Searching all collections with query '{query}' and metadata_filter={metadata_filter}")
            k_half = max(1, top_k//2)
            _search_append(history_col, "HISTORY RESULTS", k_half, m_filter=metadata_filter)
            _search_append(self._col_facts, "GLOBAL FACTS", k_half, m_filter={"is_global": "true"})
            if metadata_filter:
                logger.debug(f"[DEBUG RAG] Searching PRIVATE FACTS with query '{query}' and metadata_filter={metadata_filter}")
                m_filter_priv = {"$and": [{"is_global": "false"}, metadata_filter]}
                _search_append(self._col_facts, "PRIVATE FACTS", k_half, m_filter=m_filter_priv)
            
        if not combined:
            return f"No results found matching '{query}' across any memory collections."
        return "\n\n".join(combined)

    def save_fact(self, fact: str, is_global: bool = True, session_id: str | None = None) -> str:
        text_content = f"[{'GLOBAL' if is_global else 'PRIVATE'} FACT] {fact}"
        target_col = self._col_facts
        
        metadata = {"is_global": "true" if is_global else "false"}
        if not is_global and session_id:
            metadata["session_id"] = session_id

        result = self._mcp.call_tool_sync(
            "rag_ingest",
            {"source": text_content, "collection": target_col, "metadata": metadata}
        )
        scope = "global" if is_global else f"private({session_id})"
        logger.info(f"[Memory:rag] Saved {scope} fact to RAG.")
        return f"Fact saved to RAG memory ({scope}): {fact[:100]}"
