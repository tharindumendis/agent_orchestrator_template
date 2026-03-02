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
        """Call a tool synchronously by dispatching to the background loop."""
        q = queue.Queue()
        
        async def _call():
            try:
                result = await self._session.call_tool(name, arguments)
                text = result.content[0].text if result.content else ""
                q.put(("ok", text))
            except Exception as e:
                q.put(("err", e))
                
        # Schedule the coroutine in the background loop safely
        self._loop.call_soon_threadsafe(lambda: self._loop.create_task(_call()))
        
        # Wait for the result synchronously (with timeout)
        try:
            status, value = q.get(timeout=30.0)
            if status == "err":
                logger.error("[Memory:rag] Tool call '%s' failed: %s", name, value)
                return f"ERROR: {value}"
            return value
        except queue.Empty:
            logger.error("[Memory:rag] Tool call '%s' timed out after 30s", name)
            return "ERROR: timeout"


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

    def load_relevant(self, task: str, n: int = 10) -> list[dict]:
        """
        Uses rag_search to find relevant history.
        """
        raw_result = self._mcp.call_tool_sync(
            "rag_search",
            {"query": task, "collection": self._col_history, "top_k": n}
        )
        
        if "No results found" in raw_result or "ERROR" in raw_result:
            return []
            
        return [{
            "job_id": "rag-search",
            "ts": datetime.now(timezone.utc).isoformat(),
            "task": f"RAG Search Results for: {task[:50]}...",
            "summary": raw_result,
            "tools_used": ["rag_search"],
            "outcome": "rag_result"
        }]

    def save(
        self,
        job_id: str,
        task: str,
        summary: str,
        tools_used: list[str] | None = None,
        outcome: str = "success",
    ) -> None:
        """
        Ingests the job record into the RAG collection as a text string.
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
        
        self._mcp.call_tool_sync(
            "rag_ingest",
            {"source": text_content, "collection": self._col_history}
        )
        logger.info("[Memory:rag] Saved job %s to collection %s", job_id, self._col_history)

    def search(self, query: str, top_k: int = 5, category: str = "all") -> str:
        """Call rag_search on the targeted collection(s)."""
        if category == "facts":
            return self._mcp.call_tool_sync("rag_search", {"query": query, "collection": self._col_facts, "top_k": top_k})
        elif category == "history":
            return self._mcp.call_tool_sync("rag_search", {"query": query, "collection": self._col_history, "top_k": top_k})
        else:
            # Combine both if category is "all"
            h_res = self._mcp.call_tool_sync("rag_search", {"query": query, "collection": self._col_history, "top_k": max(1, top_k//2)})
            f_res = self._mcp.call_tool_sync("rag_search", {"query": query, "collection": self._col_facts, "top_k": max(1, top_k//2)})
            
            combined = []
            if "No results" not in h_res and "ERROR" not in h_res:
                combined.append(f"=== HISTORY RESULTS ===\n{h_res}")
            if "No results" not in f_res and "ERROR" not in f_res:
                combined.append(f"=== FACTS RESULTS ===\n{f_res}")
            
            if not combined:
                return f"No results found matching '{query}' across any memory collections."
            return "\n\n".join(combined)

    def save_fact(self, fact: str) -> str:
        text_content = f"[EXPLICIT FACT] {fact}"
        result = self._mcp.call_tool_sync(
            "rag_ingest",
            {"source": text_content, "collection": self._col_facts}
        )
        logger.info("[Memory:rag] Saved fact to RAG.")
        return f"Fact saved to RAG memory: {fact[:100]}"
