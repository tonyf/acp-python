import asyncio
import nats
from typing import AsyncGenerator, List, Callable, Any
import inspect
import anyio
import anyio.to_thread

from nats.aio.client import Client as NatsClient
from acp_python.core.types import (
    Actor,
    MyActor,
    Session,
    Message,
)
import json
from .handlers import on_handshake_msg, on_session_message
from .middleware import Middleware
from .session.store import SessionStore


class AcpClient:
    """
    An asynchronous client for the Actor Communication Protocol (ACP).

    This client handles secure communication between actors using NATS as the transport layer.
    It manages sessions, handles message encryption/decryption, and provides an async API
    for sending and receiving messages.

    Args:
        actor_id: Unique identifier for this actor
        token: Authentication token for this actor
        session_store: Storage backend for managing sessions
        middleware: List of middleware components for custom behavior
        server_url: URL of the NATS server (default: "nats://localhost:4222")
        message_decoder: Function to decode message content (default: json.loads)
    """

    def __init__(
        self,
        actor_id: str,
        token: str,
        session_store: SessionStore,
        middleware: List[Middleware],
        server_url: str = "nats://localhost:4222",
        message_decoder: Callable[[bytes], Any] = json.loads,
    ):
        self.actor_id = actor_id
        self.token = token
        self.server_url = server_url

        self._nc: NatsClient | None = None
        self._session_store = session_store
        self._middleware = middleware
        self._message_decoder = message_decoder

    async def __aenter__(self):
        """Initialize NATS connection and middleware when entering async context."""
        self._nc = await nats.connect(self.server_url)
        self._session_store.__aenter__()
        for middleware in self._middleware:
            await middleware.__aenter__()

        for middleware in self._middleware:
            await middleware.on_connect(self)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Clean up resources when exiting async context."""
        for middleware in self._middleware:
            await middleware.on_disconnect(self)

        for middleware in self._middleware:
            await middleware.__aexit__(exc_type, exc_val, exc_tb)
        await self._session_store.__aexit__(exc_type, exc_val, exc_tb)
        await self._nc.close()

    ###
    ### Properties
    ###

    @property
    def me(self) -> MyActor:
        """Returns this actor's full identity including private details."""
        raise NotImplementedError

    @property
    def me_as_peer(self) -> Actor:
        """Returns this actor's public identity as seen by peers."""
        raise NotImplementedError

    @property
    def peers(self) -> List[Actor]:
        """Returns list of known peer actors."""
        raise NotImplementedError

    @property
    def sessions(self) -> List[Session]:
        """Returns list of active sessions with peers."""
        raise NotImplementedError

    ###
    ### Handlers
    ###

    async def _listen_handshake_msgs(self, nc: NatsClient):
        """
        Listen for and handle incoming handshake messages.

        Args:
            nc: NATS client connection
        """
        handshake_sub = await nc.subscribe(f"acp.{self.actor_id}.handshake.*")
        async for msg in handshake_sub.messages:
            await on_handshake_msg(msg, client=self)

    async def _listen_session_messages(
        self, nc: NatsClient
    ) -> AsyncGenerator[Message, None]:
        """
        Listen for and handle incoming session messages.

        Args:
            nc: NATS client connection

        Yields:
            Decrypted and decoded messages from peers
        """
        session_sub = await nc.subscribe(f"acp.{self.actor_id}.inbox.*")
        async for msg in session_sub.messages:
            message = await on_session_message(msg, client=self)
            if message is not None:
                yield message
            await msg.ack()

    ###
    ### Methods
    ###

    async def connect(self, peer: Actor):
        """
        Establish a secure session with a peer actor.

        Args:
            peer: The actor to connect with
        """
        # create a session with the peer
        raise

    async def messages(self) -> AsyncGenerator[Message, None]:
        """
        Yields session messages while allowing handshake messages to be handled in the background.

        Returns:
            An async generator yielding decrypted and decoded messages from peers
        """
        if self._nc is None:
            nc = await nats.connect(self.server_url)
        else:
            nc = self._nc

        handshake_task = asyncio.create_task(self._listen_handshake_msgs(nc))
        try:
            async for message in self._listen_session_messages(nc):
                yield message
        finally:
            handshake_task.cancel()
            await handshake_task

    async def listen(
        self, message_handler: Callable[[Message, "AcpClient"], None]
    ) -> None:
        """
        Listen for messages and process them with the provided handler.

        The handler can be either a synchronous or asynchronous function.
        Synchronous handlers are run in a separate thread to avoid blocking.

        Args:
            message_handler: Callback function to process received messages
        """
        async for message in self.messages():
            # If message_handler is an async function, just await it
            if inspect.iscoroutinefunction(message_handler):
                await message_handler(message, self)
            # Otherwise, run it in a worker thread so we don't block the event loop
            else:
                await anyio.to_thread.run_sync(message_handler, message, self)

    def listen_sync(
        self, message_handler: Callable[[Message, "AcpClient"], None]
    ) -> None:
        """
        Synchronous version of listen() that runs in the current thread.

        Args:
            message_handler: Callback function to process received messages
        """
        asyncio.run(self.listen(message_handler))
