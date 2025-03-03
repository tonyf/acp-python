from typing import Any, AsyncGenerator, Dict, List, Protocol

from ..types import (
    AgentInfo,
    ConversationSession,
    EncryptedMessage,
    HandshakeRequest,
    HandshakeResponse,
)


class Transport(Protocol):
    agent: AgentInfo

    async def connect(self, info: AgentInfo): ...

    async def send(self, to: AgentInfo, message: EncryptedMessage): ...

    async def register_session(
        self, agent: AgentInfo, session_id: str
    ) -> Dict[str, Any]: ...

    async def handshake_request(
        self, to: AgentInfo, request: HandshakeRequest
    ) -> HandshakeResponse: ...

    async def handshake_reply(self, to: AgentInfo, response: HandshakeResponse): ...

    async def handshakes(
        self, agent: AgentInfo
    ) -> AsyncGenerator[HandshakeRequest, None]: ...

    async def messages(
        self, agent: AgentInfo, sessions: List[ConversationSession]
    ) -> AsyncGenerator[EncryptedMessage, None]: ...
