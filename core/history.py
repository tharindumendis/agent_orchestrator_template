import json
from abc import ABC, abstractmethod
from langchain_core.messages import BaseMessage

class ConversationHistoryBackend(ABC):
    """
    Abstract interface for storing and retrieving the literal back-and-forth
    messages of an ongoing chat session.
    Allows easy swapping between SQLite, MySQL, Postgres, MongoDB, etc.
    """

    @abstractmethod
    def load_session(self, session_id: str) -> list[BaseMessage] | None:
        """
        Loads the sequence of BaseMessage objects for the specified session_id.
        Returns None if not found.
        """
        pass

    @abstractmethod
    def save_session(self, session_id: str, messages: list[BaseMessage]) -> None:
        """
        Serializes and commits the list of BaseMessage objects to the database.
        """
        pass

    @abstractmethod
    def list_sessions(self) -> list[str]:
        """
        Returns a list of all active session IDs stored in this backend.
        """
        pass

    @abstractmethod
    def export_session(self, session_id: str) -> str | None:
        """
        Exports the session history as a raw JSON string for debugging or external use.
        Returns None if the session is not found.
        """
        pass
