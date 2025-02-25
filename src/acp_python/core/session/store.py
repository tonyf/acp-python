from typing import Protocol, Optional
from acp_python.core.types import Session
from typing import Dict


class SessionStore(Protocol):
    """
    A protocol (interface) for storing and retrieving Sessions by their ID.
    """

    def get_session(self, session_id: str) -> Optional[Session]:
        """
        Retrieve a session by ID.
        """
        ...

    def set_session(self, session: Session) -> None:
        """
        Store a session by its ID.
        """
        ...

    def delete_session(self, session_id: str) -> None:
        """
        Remove the session by ID.
        """
        ...


class InMemorySessionStore:
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

    def get_session(self, session_id: str) -> Optional[Session]:
        return self._sessions.get(session_id)

    def set_session(self, session: Session) -> None:
        self._sessions[session.id] = session

    def delete_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)


class RedisSessionStore:
    """
    A Redis-based session store for distributed access.
    Stores each Session as a JSON-encoded blob in Redis.
    """

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        import redis

        self._redis = redis.Redis.from_url(redis_url)

    def get_session(self, session_id: str) -> Optional[Session]:
        import redis

        data = self._redis.get(session_id)
        if data is None:
            return None
        return Session.model_validate_json(data)

    def set_session(self, session: Session) -> None:
        self._redis.set(session.id, session.model_dump_json())

    def delete_session(self, session_id: str) -> None:
        self._redis.delete(session_id)
