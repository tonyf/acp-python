from typing import Protocol, Tuple, Optional
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from acp_python.client.client import AcpClient
    from acp_python.core.types import Session, Actor


class Middleware(Protocol):
    """
    Protocol defining middleware components that can intercept and modify ACP client behavior.

    Middleware components can hook into various events in the client lifecycle like connections,
    session management, and message handling. They can also perform actions like accepting/rejecting
    sessions.
    """

    async def __aenter__(self):
        """Called when entering an async context"""
        ...

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Called when exiting an async context"""
        ...

    # On Callbacks
    async def on_connect(self, client: "AcpClient") -> None:
        """
        Called when the client connects to the NATS server.

        Args:
            client: The ACP client that connected
        """
        ...

    async def on_disconnect(self, client: "AcpClient") -> None:
        """
        Called when the client disconnects from the NATS server.

        Args:
            client: The ACP client that disconnected
        """
        ...

    async def on_session_request(
        self, client: "AcpClient", me: Actor, peer: Actor
    ) -> Tuple[bool, Optional[str]]:
        """
        Called when receiving a session request from a peer.

        Args:
            client: The ACP client handling the request
            me: The actor receiving the request
            peer: The actor requesting the session

        Returns:
            Tuple containing:
                - bool: True if session should be allowed, False to reject
                - Optional[str]: Reason for rejection if session is not allowed
        """
        ...

    async def on_session_response(self, client: "AcpClient", peer: Actor) -> bool:
        """
        Called when receiving a response to our session request.

        Args:
            client: The ACP client handling the response
            peer: The actor that responded

        Returns:
            bool: True if session response is accepted, False otherwise
        """
        ...

    async def on_session_create(
        self, client: "AcpClient", peer: Actor, session: Session
    ) -> None:
        """
        Called when a new session is successfully created with a peer.

        Args:
            client: The ACP client managing the session
            peer: The actor we established a session with
            session: The newly created session
        """
        ...

    async def on_session_reject(
        self, client: "AcpClient", peer: Actor, reason: str
    ) -> None:
        """
        Called when a session request is rejected by a peer.

        Args:
            client: The ACP client handling the rejection
            peer: The actor that rejected the session
            reason: The reason given for rejection
        """
        ...

    async def on_session_close(
        self, client: "AcpClient", peer: Actor, session: Session
    ) -> None:
        """
        Called when a session is closed.

        Args:
            client: The ACP client managing the session
            peer: The actor whose session was closed
            session: The session that was closed
        """
        ...
