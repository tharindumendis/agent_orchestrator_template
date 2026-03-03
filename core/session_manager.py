import sqlite3
import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from langchain_core.messages import messages_from_dict, messages_to_dict

logger = logging.getLogger(__name__)

class SessionManager:
    """
    Handles saving and resuming the exact conversational state (list of messages)
    using SQLite, to support fully continuous agents.
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

    def load_session(self, session_id: str) -> list | None:
        """
        Loads the sequence of BaseMessage objects for the specified session_id.
        Returns None if not found.
        """
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

    def save_session(self, session_id: str, messages: list):
        """
        Serializes and commits the list of BaseMessage objects to SQLite.
        """
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
