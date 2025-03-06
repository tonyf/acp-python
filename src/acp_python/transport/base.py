from typing import Any, AsyncGenerator, Dict, List, Protocol, Generator

from acp_python.types import (
    ActorInfo,
    Session,
    MessageEnvelope,
    HandshakeRequest,
    HandshakeResponse,
)


class Transport(Protocol):
    actor: ActorInfo

    def connect(self, info: ActorInfo): ...

    def send(self, to: ActorInfo, message: MessageEnvelope): ...

    def request(self, to: ActorInfo, message: MessageEnvelope) -> MessageEnvelope: ...

    def register_session(self, peer: ActorInfo, session_id: str) -> Dict[str, Any]: ...

    def close_session(self, session_id: str): ...

    def handshake_request(
        self, to: ActorInfo, request: HandshakeRequest
    ) -> HandshakeResponse: ...

    def handshake_reply(self, to: ActorInfo, response: HandshakeResponse): ...

    def handshakes(
        self, peer: ActorInfo
    ) -> Generator[HandshakeRequest, None, None]: ...

    def messages(
        self, me: ActorInfo, sessions: List[Session]
    ) -> Generator[MessageEnvelope, None, None]: ...


class AsyncTransport(Protocol):
    actor: ActorInfo

    async def connect(self, info: ActorInfo): ...

    async def send(self, to: ActorInfo, message: MessageEnvelope): ...

    async def request(
        self, to: ActorInfo, message: MessageEnvelope, timeout: int = 10
    ) -> MessageEnvelope: ...

    async def register_session(
        self, peer: ActorInfo, session_id: str
    ) -> Dict[str, Any]: ...

    async def close_session(self, session_id: str): ...

    async def handshake_request(
        self, to: ActorInfo, request: HandshakeRequest
    ) -> HandshakeResponse: ...

    async def handshake_reply(self, to: ActorInfo, response: HandshakeResponse): ...

    async def handshakes(
        self, peer: ActorInfo
    ) -> AsyncGenerator[HandshakeRequest, None]: ...

    async def messages(
        self, me: ActorInfo, sessions: List[Session]
    ) -> AsyncGenerator[MessageEnvelope, None]: ...
