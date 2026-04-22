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
    Stores complete conversational thread arrays for continuous sessions.
    """

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    messages_json TEXT,
                    updated_at TEXT
                )
            ''')
            conn.commit()

    def load_session(self, session_id: str) -> list[BaseMessage] | None:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT messages_json FROM sessions WHERE session_id = ?", (session_id,))
            row = cursor.fetchone()
            if row:
                try:
                    data = json.loads(row[0])
                    return messages_from_dict(data)
                except Exception as e:
                    logger.error("Failed to decode session %s: %s", session_id, e)
        return None

    def save_session(self, session_id: str, messages: list[BaseMessage]) -> None:
        try:
            data = messages_to_dict(messages)
            msgs_json = json.dumps(data)
            now = datetime.now(timezone.utc).isoformat()
            
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    INSERT OR REPLACE INTO sessions (session_id, messages_json, updated_at)
                    VALUES (?, ?, ?)
                ''', (session_id, msgs_json, now))
                conn.commit()
                
            logger.debug("Saved %d messages to session '%s'.", len(messages), session_id)
        except Exception as e:
            logger.error("Failed to save session %s: %s", session_id, e)

    def list_sessions(self) -> list[str]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT session_id FROM sessions ORDER BY updated_at DESC")
            return [row[0] for row in cursor.fetchall()]

    def export_session(self, session_id: str) -> str | None:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT messages_json FROM sessions WHERE session_id = ?", (session_id,))
            row = cursor.fetchone()
            if row:
                return row[0]
        return None
