import json
from abc import ABC, abstractmethod
from langchain_core.messages import BaseMessage

class ConversationHistoryBackend(ABC):
    """
    Abstract interface for storing and retrieving the literal back-and-forth
    messages of an ongoing chat session.
    Allows easy swapping between SQLite, MySQL, Postgres, MongoDB, etc.

    Two-layer storage model
    -----------------------
    save_session()       — stores the WORKING COPY (windowed/summarised slice)
                           fed to the LLM at the next turn.  May be trimmed.
    append_to_archive()  — appends every new message to the PERMANENT ARCHIVE
                           so the full conversation is never lost for debugging.
    """

    @abstractmethod
    def load_session(self, session_id: str) -> list[BaseMessage] | None:
        """
        Loads the windowed working copy for the specified session_id.
        Returns None if not found.
        """
        pass

    @abstractmethod
    def save_session(self, session_id: str, messages: list[BaseMessage]) -> None:
        """
        Serializes and commits the working copy (windowed/trimmed) to the database.
        This is what gets fed to the LLM — may shrink after summarisation.
        Does NOT replace the archive.
        """
        pass

    @abstractmethod
    def append_to_archive(
        self,
        session_id: str,
        messages: list[BaseMessage],
        already_archived_count: int = 0,
    ) -> None:
        """
        Appends *only the new* messages (after already_archived_count) to the
        permanent session archive.  The archive is never trimmed or overwritten —
        it accumulates every message ever produced in the session.

        Args:
            session_id:              The session to archive to.
            messages:                The full current conversation_history list.
            already_archived_count:  How many messages from the start of
                                     *messages* were already archived in a
                                     previous call.  Only messages from this
                                     index onward will be written.
        """
        pass

    @abstractmethod
    def load_full_archive(self, session_id: str) -> list[BaseMessage] | None:
        """
        Returns the complete, unabridged message list for the session — every
        message ever appended via append_to_archive(), in insertion order.
        Returns None if no archive exists for this session.
        """
        pass

    @abstractmethod
    def get_archive_count(self, session_id: str) -> int:
        """
        Returns the number of messages currently stored in the archive for
        session_id.  Used to cheaply compute the delta for the next
        append_to_archive() call without loading the full list.
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
        Exports the WORKING COPY history as a raw JSON string.
        Returns None if the session is not found.
        """
        pass

    def export_full_archive(self, session_id: str) -> str | None:
        """
        Exports the complete archive (all messages ever) as a raw JSON string.
        Default implementation builds on load_full_archive(); backends may
        override for a direct DB query.
        Returns None if no archive exists.
        """
        from langchain_core.messages import messages_to_dict
        msgs = self.load_full_archive(session_id)
        if msgs is None:
            return None
        return json.dumps(messages_to_dict(msgs))
