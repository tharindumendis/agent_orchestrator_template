"""
core/memory.py
--------------
Plug-and-play long-term memory for Agent_head.

Architecture
------------
  MemoryBackend (Protocol / interface)
      |
      +-- JsonlMemoryBackend    <- default, zero deps, one .jsonl file
      +-- (future) SqliteMemoryBackend
      +-- (future) RagMemoryBackend   <- uses Agent_rag for semantic search

agent.py only ever calls the MemoryBackend interface — it never knows
which backend is active. Swapping backends is a one-line config change:

    memory:
      backend: "jsonl"   # <- change to "sqlite" or "rag" later

Public API used by agent.py
---------------------------
  backend = get_backend(mem_cfg)          # factory
  past    = backend.load_relevant(task)   # list[dict]
  ctx_str = backend.build_context(past)   # str for system prompt
  backend.save(job_id, task, summary, tools_used, outcome)
  result  = backend.search(query)         # str — for memory_search tool
  result  = backend.save_fact(fact)       # str — for memory_save tool
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


# ===========================================================================
# MemoryBackend — abstract interface
# All backends must implement exactly these methods.
# ===========================================================================

class MemoryBackend(ABC):

    @abstractmethod
    def save(
        self,
        job_id: str,
        task: str,
        summary: str,
        tools_used: list[str] | None = None,
        outcome: str = "success",
        session_id: str | None = None,
    ) -> None:
        """Persist a job memory entry."""

    @abstractmethod
    def search(self, query: str, top_k: int = 5, category: str = "all") -> str:
        """Search memory and return a formatted result string.
        category can be 'all', 'history', or 'facts'.
        """

    @abstractmethod
    def save_fact(self, fact: str, is_global: bool = True, session_id: str | None = None) -> str:
        """Save an explicit user/LLM note to memory."""


# ===========================================================================
# JsonlMemoryBackend — default implementation (zero extra dependencies)
# One JSON-lines file: <memory_dir>/memory.jsonl
# ===========================================================================

class JsonlMemoryBackend(MemoryBackend):
    """
    Simple file-based memory backend.
    Each entry is a JSON object on its own line in memory.jsonl.
    Retrieval uses keyword scoring (no embeddings needed).
    """

    def __init__(self, memory_dir: str | Path, max_save_length: int = 500):
        self._dir = Path(memory_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._file = self._dir / "memory.jsonl"
        self._max_len = max_save_length

    # ── internal helpers ───────────────────────────────────────────────

    def _all(self) -> list[dict]:
        if not self._file.exists():
            return []
        entries = []
        with open(self._file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return entries

    @staticmethod
    def _score(entry: dict, query: str) -> int:
        words = set(re.findall(r"\w+", query.lower()))
        blob  = f"{entry.get('task','')} {entry.get('summary','')}".lower()
        return sum(1 for w in words if w in blob)

    def _append(self, entry: dict) -> None:
        with open(self._file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # ── MemoryBackend interface ────────────────────────────────────────

    def load_relevant(self, task: str, n: int = 10) -> list[dict]:
        entries = self._all()
        if not entries:
            return []
        scored = sorted(
            entries,
            key=lambda e: self._score(e, task),
            reverse=True,
        )
        seen, result = set(), []
        for e in scored[:n]:
            jid = e.get("job_id", "")
            if jid not in seen:
                seen.add(jid)
                result.append(e)
        # Always include last 3 for recency
        for e in reversed(entries[-3:]):
            jid = e.get("job_id", "")
            if jid not in seen and len(result) < n:
                seen.add(jid)
                result.append(e)
        return result[:n]

    def save(
        self,
        job_id: str,
        task: str,
        summary: str,
        tools_used: list[str] | None = None,
        outcome: str = "success",
    ) -> None:
        entry = {
            "job_id":     job_id,
            "ts":         datetime.now(timezone.utc).isoformat(),
            "task":       task[:300],
            "summary":    summary[:self._max_len],
            "tools_used": tools_used or [],
            "outcome":    outcome,
        }
        self._append(entry)
        logger.info("[Memory:jsonl] Saved job %s → %s", job_id, self._file)

    def search(self, query: str, top_k: int = 5, category: str = "all") -> str:
        entries = self._all()
        if not entries:
            return "No memories stored yet."

        if category == "facts":
            entries = [e for e in entries if e.get("outcome") == "note"]
        elif category == "history":
            entries = [e for e in entries if e.get("outcome") != "note"]

        hits = sorted(
            [(self._score(e, query), e) for e in entries],
            key=lambda x: x[0],
            reverse=True,
        )
        hits = [e for sc, e in hits[:top_k] if sc > 0]
        if not hits:
            return f"No memories found matching '{query}' in category '{category}'."
        return self.build_context(hits)

    def save_fact(self, fact: str, is_global: bool = True, session_id: str | None = None) -> str:
        scope = "global" if is_global else f"private({session_id})"
        self.save(
            job_id=f"fact-{uuid.uuid4().hex[:8]}",
            task=f"[explicit-fact] scope:{scope}",
            summary=fact,
            outcome="note",
            session_id=session_id,
        )
        return f"Fact saved to memory ({scope}): {fact[:100]}"


# ===========================================================================
# Factory — returns the configured backend
# Add new backends here as elif branches.
# ===========================================================================

def get_backend(
    backend_type: str = "jsonl",
    memory_dir: str | Path = "./memory",
    max_save_length: int = 500,
    rag_server_cfg=None,
) -> MemoryBackend:
    """
    Return the requested MemoryBackend instance.

    backend_type: "jsonl" (default) | future: "sqlite" | "rag"
    """
    t = backend_type.lower().strip()
    if t == "jsonl":
        return JsonlMemoryBackend(
            memory_dir=memory_dir,
            max_save_length=max_save_length,
        )
    elif t == "sqlite":
        from core.memory_sqlite import SqliteMemoryBackend
        return SqliteMemoryBackend(memory_dir=memory_dir, max_save_length=max_save_length)
    elif t == "rag":
        from core.memory_rag import RagMemoryBackend
        return RagMemoryBackend(
            memory_dir=memory_dir,
            max_save_length=max_save_length,
            rag_server_cfg=rag_server_cfg
        )
    else:
        logger.warning("[Memory] Unknown backend '%s', falling back to jsonl.", t)
        return JsonlMemoryBackend(memory_dir=memory_dir, max_save_length=max_save_length)
