import sqlite3
import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from langchain_core.messages import messages_from_dict, messages_to_dict, BaseMessage

from core.history import ConversationHistoryBackend

logger = logging.getLogger(__name__)

class SqliteConversationHistory(ConversationHistoryBackend):
    """
    Implements ConversationHistoryBackend using SQLite.

    Two-table design
    ----------------
    sessions         — WORKING COPY: the windowed/summarised slice fed to the
                       LLM.  Overwritten each turn.  May shrink after
                       summarisation.  Fast to load at session resume.

    session_archive  — PERMANENT ARCHIVE: every message ever produced,
                       append-only.  Never trimmed or overwritten.  Used for
                       debug export and full conversation replay.
    """

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            # Working-copy table (original, unchanged schema)
            conn.execute('''
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    messages_json TEXT,
                    updated_at TEXT
                )
            ''')
            # Permanent archive table — one row per message, append-only
            conn.execute('''
                CREATE TABLE IF NOT EXISTS session_archive (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id  TEXT    NOT NULL,
                    role        TEXT    NOT NULL,
                    content_json TEXT   NOT NULL,
                    created_at  TEXT    NOT NULL
                )
            ''')
            conn.execute(
                'CREATE INDEX IF NOT EXISTS idx_archive_session '
                'ON session_archive (session_id, id)'
            )
            conn.commit()

    # ── Working-copy (sessions table) ────────────────────────────────────────

    def load_session(self, session_id: str) -> list[BaseMessage] | None:
        """Load the windowed working copy for the LLM."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT messages_json FROM sessions WHERE session_id = ?",
                (session_id,),
            )
            row = cursor.fetchone()
            if row:
                try:
                    data = json.loads(row[0])
                    return messages_from_dict(data)
                except Exception as e:
                    logger.error("Failed to decode session %s: %s", session_id, e)
        return None

    def save_session(self, session_id: str, messages: list[BaseMessage]) -> None:
        """Persist the working copy (may be windowed/trimmed).  Does NOT touch the archive."""
        try:
            data = messages_to_dict(messages)
            msgs_json = json.dumps(data)
            now = datetime.now(timezone.utc).isoformat()

            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    '''
                    INSERT OR REPLACE INTO sessions (session_id, messages_json, updated_at)
                    VALUES (?, ?, ?)
                    ''',
                    (session_id, msgs_json, now),
                )
                conn.commit()

            logger.debug(
                "Saved working copy: %d messages to session '%s'.",
                len(messages), session_id,
            )
        except Exception as e:
            logger.error("Failed to save session %s: %s", session_id, e)

    # ── Permanent archive (session_archive table) ─────────────────────────────

    def append_to_archive(
        self,
        session_id: str,
        messages: list[BaseMessage],
        already_archived_count: int = 0,
    ) -> None:
        """
        Append only the *new* messages (those after already_archived_count) to
        the permanent archive.  Safe to call after every turn — will only
        write the delta.
        """
        new_msgs = messages[already_archived_count:]
        if not new_msgs:
            return

        try:
            now = datetime.now(timezone.utc).isoformat()
            rows = []
            for msg in new_msgs:
                role = type(msg).__name__  # e.g. "HumanMessage", "AIMessage"
                content_json = json.dumps(messages_to_dict([msg]))
                rows.append((session_id, role, content_json, now))

            with sqlite3.connect(self.db_path) as conn:
                conn.executemany(
                    '''
                    INSERT INTO session_archive (session_id, role, content_json, created_at)
                    VALUES (?, ?, ?, ?)
                    ''',
                    rows,
                )
                conn.commit()

            logger.debug(
                "Archived %d new messages for session '%s' (total offset was %d).",
                len(new_msgs), session_id, already_archived_count,
            )
        except Exception as e:
            logger.error("Failed to archive messages for session %s: %s", session_id, e)

    def load_full_archive(self, session_id: str) -> list[BaseMessage] | None:
        """Return every message ever archived for this session, in order."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT content_json FROM session_archive WHERE session_id = ? ORDER BY id ASC",
                (session_id,),
            )
            rows = cursor.fetchall()

        if not rows:
            return None

        all_msgs: list[BaseMessage] = []
        for (content_json,) in rows:
            try:
                data = json.loads(content_json)
                all_msgs.extend(messages_from_dict(data))
            except Exception as e:
                logger.warning("Skipping corrupt archive row for session %s: %s", session_id, e)
        return all_msgs or None

    def get_archive_count(self, session_id: str) -> int:
        """Return how many messages are in the archive (cheap COUNT query)."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM session_archive WHERE session_id = ?",
                (session_id,),
            )
            row = cursor.fetchone()
            return row[0] if row else 0

    def export_full_archive(self, session_id: str) -> str | None:
        """Return the complete archive as a JSON string (for the API endpoint)."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT content_json FROM session_archive WHERE session_id = ? ORDER BY id ASC",
                (session_id,),
            )
            rows = cursor.fetchall()

        if not rows:
            return None

        all_data = []
        for (content_json,) in rows:
            try:
                all_data.extend(json.loads(content_json))
            except Exception:
                pass
        return json.dumps(all_data)

    # ── Listing / Export ──────────────────────────────────────────────────────

    def list_sessions(self) -> list[str]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT session_id FROM sessions ORDER BY updated_at DESC"
            )
            return [row[0] for row in cursor.fetchall()]

    def export_session(self, session_id: str) -> str | None:
        """Export the WORKING COPY (windowed) as JSON."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT messages_json FROM sessions WHERE session_id = ?",
                (session_id,),
            )
            row = cursor.fetchone()
            if row:
                return row[0]
        return None
