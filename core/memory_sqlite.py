"""
core/memory_sqlite.py
---------------------
SQLite-backed long-term memory for Agent_head.
Replaces the default memory.jsonl file with a memory.db database.
Offers exactly the same protocol and scoring as JsonlMemoryBackend.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from core.memory import MemoryBackend

logger = logging.getLogger(__name__)


class SqliteMemoryBackend(MemoryBackend):
    """
    SQLite-backed memory.
    Stores job memories and facts in a single `memories` table.
    """

    def __init__(self, memory_dir: str | Path, max_save_length: int = 500):
        self._dir = Path(memory_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._db_path = self._dir / "memory.db"
        self._max_len = max_save_length
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self._db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS memories (
                    job_id TEXT PRIMARY KEY,
                    ts TEXT NOT NULL,
                    task TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    tools_used TEXT NOT NULL,
                    outcome TEXT NOT NULL
                )
            ''')
            conn.commit()

    # ── internal helpers ───────────────────────────────────────────────

    def _all(self) -> list[dict]:
        entries = []
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM memories ORDER BY ts ASC")
            for row in cursor.fetchall():
                entries.append({
                    "job_id": row["job_id"],
                    "ts": row["ts"],
                    "task": row["task"],
                    "summary": row["summary"],
                    "tools_used": json.loads(row["tools_used"]),
                    "outcome": row["outcome"]
                })
        return entries

    @staticmethod
    def _score(entry: dict, query: str) -> int:
        words = set(re.findall(r"\w+", query.lower()))
        blob = f"{entry.get('task','')} {entry.get('summary','')}".lower()
        return sum(1 for w in words if w in blob)

    # ── MemoryBackend interface ────────────────────────────────────────

    def save(
        self,
        job_id: str,
        task: str,
        summary: str,
        tools_used: list[str] | None = None,
        outcome: str = "success",
    ) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                '''
                INSERT OR REPLACE INTO memories (job_id, ts, task, summary, tools_used, outcome)
                VALUES (?, ?, ?, ?, ?, ?)
                ''',
                (
                    job_id,
                    datetime.now(timezone.utc).isoformat(),
                    task[:300],
                    summary[:self._max_len],
                    json.dumps(tools_used or []),
                    outcome
                )
            )
            conn.commit()
        logger.info("[Memory:sqlite] Saved job %s -> %s", job_id, self._db_path)

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

    def save_fact(self, fact: str) -> str:
        self.save(
            job_id=f"fact-{uuid.uuid4().hex[:8]}",
            task="[explicit-fact]",
            summary=fact,
            outcome="note",
        )
        return f"Fact saved to memory: {fact[:100]}"
