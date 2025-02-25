from typing import Protocol, Optional
from acp_python.core.types import Session
from typing import Dict


class SessionStore(Protocol):
    """
    A protocol (interface) for storing and retrieving Sessions by their ID.
    """

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    async def get_session(self, actor_id: str, session_id: str) -> Optional[Session]:
        """
        Retrieve a session by ID.
        """
        ...

    async def set_session(self, actor_id: str, session: Session) -> None:
        """
        Store a session by its ID.
        """
        ...

    async def delete_session(self, actor_id: str, session_id: str) -> None:
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

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    async def get_session(self, actor_id: str, session_id: str) -> Optional[Session]:
        return self._sessions.get(f"{actor_id}.{session_id}")

    async def set_session(self, actor_id: str, session: Session) -> None:
        self._sessions[f"{actor_id}.{session.id}"] = session

    async def delete_session(self, actor_id: str, session_id: str) -> None:
        self._sessions.pop(f"{actor_id}.{session_id}", None)


class RedisSessionStore:
    """
    A Redis-based session store for distributed access.
    Stores each Session as a JSON-encoded blob in Redis.
    """

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        import aioredis

        self._redis = aioredis.from_url(redis_url)
        self._session = None

    async def __aenter__(self):
        self._session = await self._redis.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._redis.__aexit__(exc_type, exc_val, exc_tb)

    def _redis_session(self):
        if self._session is None:
            return self._redis
        return self._session

    async def get_session(self, actor_id: str, session_id: str) -> Optional[Session]:
        data = await self._redis_session().get(f"{actor_id}.{session_id}")
        if data is None:
            return None
        return Session.model_validate_json(data)

    async def set_session(self, actor_id: str, session: Session) -> None:
        await self._redis_session().set(
            f"{actor_id}.{session.id}", session.model_dump_json()
        )

    async def delete_session(self, actor_id: str, session_id: str) -> None:
        await self._redis_session().delete(f"{actor_id}.{session_id}")


class Boto3SessionStore:
    """
    A Redis-based session store for distributed access.
    Stores each Session as a JSON-encoded blob in Redis.
    """

    def __init__(self, bucket: str, prefix: str = "acp"):
        import aioboto3

        self._bucket = bucket
        self._prefix = prefix

        self._session = aioboto3.Session()
        self._client = None

    async def __aenter__(self):
        self._session = await self._redis.__aenter__()
        self._client = self._session.client("s3").__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._client.__aexit__(exc_type, exc_val, exc_tb)
        await self._session.__aexit__(exc_type, exc_val, exc_tb)

    def get_client(self):
        if self._client is None:
            return self._session.client("s3")
        return self._client

    async def get_session(self, actor_id: str, session_id: str) -> Optional[Session]:
        data = await self.get_client().get_object(
            Bucket=self._bucket,
            Key=f"{self._prefix}/{actor_id}/{session_id}",
        )
        if data is None:
            return None
        return Session.model_validate_json(data)

    async def set_session(self, actor_id: str, session: Session) -> None:
        await self.get_client().put_object(
            Bucket=self._bucket,
            Key=f"{self._prefix}/{actor_id}/{session.id}",
            Body=session.model_dump_json().encode("utf-8"),
        )

    async def delete_session(self, actor_id: str, session_id: str) -> None:
        await self.get_client().delete_object(
            Bucket=self._bucket,
            Key=f"{self._prefix}/{actor_id}/{session_id}",
        )
