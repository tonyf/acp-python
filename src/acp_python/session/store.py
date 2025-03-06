from typing import Dict, List, Optional, Protocol

from acp_python.types import Session


class SessionStore(Protocol):
    """
    A protocol (interface) for storing and retrieving Sessions by their ID.
    """

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    async def active_sessions(self, actor_id: str) -> List[Session]:
        """
        Retrieve all active sessions for an actor.
        """
        ...

    async def get_session(self, actor_id: str, session_id: str) -> Optional[Session]:
        """
        Retrieve a session by ID.
        """
        ...

    async def set_session(
        self, actor_id: str, session_id: str, session: Session
    ) -> None:
        """
        Store a session by its ID.
        """
        ...

    async def delete_session(self, actor_id: str, session_id: str) -> None:
        """
        Remove the session by ID.
        """
        ...


class InMemorySessionStore(SessionStore):
    """
    An in-memory session store using a singleton pattern to share state
    across threads within the same Python process.
    """

    _instance = None
    _sessions: Dict[str, Session] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    def session_key(self, actor_id: str, session_id: str) -> str:
        return f"acp.agent.{actor_id}.session.{session_id}"

    async def active_sessions(self, actor_id: str) -> List[Session]:
        all_sessions = list(self._sessions.values())
        return [session for session in all_sessions if session.me.name == actor_id]

    async def get_session(self, actor_id: str, session_id: str) -> Optional[Session]:
        return self._sessions.get(self.session_key(actor_id, session_id))

    async def set_session(
        self, actor_id: str, session_id: str, session: Session
    ) -> None:
        self._sessions[self.session_key(actor_id, session_id)] = session

    async def delete_session(self, actor_id: str, session_id: str) -> None:
        self._sessions.pop(self.session_key(actor_id, session_id), None)


default_session_store = InMemorySessionStore()
