import asyncio
import nats
from typing import AsyncGenerator, List, Callable
import inspect
import anyio
import anyio.to_thread
import os
from nats.aio.client import Client as NatsClient
from .types import (
    Actor,
    MyActor,
    Session,
    Message,
    SessionMessage,
    HandshakeRequest,
)
from .handlers import on_handshake_request, on_session_message, on_handshake_response
from .middleware import Middleware
from .session.store import SessionStore
from cryptography.hazmat.primitives.asymmetric import x25519

SigningKey = x25519.X25519PrivateKey


MessageHandler = Callable[[Message, "AcpClient"], None]


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
        server_url: URL of the NATS server (default: "nats://acp.net:4222")
        message_decoder: Function to decode message content (default: json.loads)
        message_encoder: Function to encode message content (default: json.dumps)
    """

    def __init__(
        self,
        actor_id: str,
        token: str,
        session_store: SessionStore,
        middleware: List[Middleware] = [],
        server_url: str = "nats://acp.net:4222",
    ):
        self.actor_id = actor_id
        self.token = token
        self.server_url = server_url

        self._nc: NatsClient | None = None
        self._session_store = session_store
        self._middleware = middleware or []
        self._running = False

    async def __aenter__(self):
        """Initialize NATS connection and middleware when entering async context."""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Clean up resources when exiting async context."""
        await self.stop()

    ###
    ### Properties
    ###

    @property
    def me(self) -> MyActor:
        """Returns this actor's full identity including private details."""
        return MyActor(
            id=self.actor_id,
            namespace_keys={"test": SigningKey.generate()},
            description={},
            ca_signature=bytes(),
        )

    def me_as_peer(self, namespace: str) -> Actor:
        """Returns this actor's public identity as seen by peers."""
        return Actor(
            id=self.actor_id,
            namespace=namespace,
            description={},
        )

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
            await on_handshake_request(msg, client=self)

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
        try:
            async for msg in session_sub.messages:
                message = await on_session_message(msg, client=self)
                if message is not None:
                    yield message
                await msg.ack()
        except Exception as e:
            # Log the error but don't re-raise to allow graceful shutdown
            print(f"Error in _listen_session_messages: {e}")

    ###
    ### Methods
    ###

    async def connect(self, peer: Actor):
        """
        Establish a secure session with a peer actor.

        Args:
            peer: The actor to connect with
        """
        if self._nc is None:
            raise RuntimeError("Client not connected to NATS server")

        req = HandshakeRequest(
            sender=self.me_as_peer(peer.namespace),
            recipient=peer,
            public_key=self.me.namespace_keys[peer.namespace].private_bytes_raw(),
            certificate=self.me.ca_signature,
        )
        rsp = await self._nc.request(peer.to_dns(), req.to_bytes())
        await on_handshake_response(rsp, client=self)

    async def send_message(self, session_id: str, content: bytes) -> None:
        """
        Send a message to a peer actor.

        Args:
            peer_id: ID of the recipient actor
            content: Message content to send (will be encoded using the configured encoder)
            metadata: Optional metadata to include with the message

        Raises:
            ValueError: If no active session exists with the peer
            RuntimeError: If client is not connected
        """
        if self._nc is None:
            raise RuntimeError("Client not connected to NATS server")

        # Get the session for this peer
        session = await self._session_store.get_session(
            self.actor_id, session_id=session_id
        )
        if not session:
            raise ValueError(f"No active session with id {session_id}")

        # Encrypt the message & create the message object
        session_message = SessionMessage(
            session_id=session.id,
            sender=self.me_as_peer(session.peer.namespace),
            recipient=session.peer,
            content=session.encrypt(content),
        )
        encoded_message = session_message.to_bytes()

        # Send the message
        await self._nc.publish(session.peer.to_dns(), encoded_message)

    async def messages(self) -> AsyncGenerator[Message, None]:
        """
        Yields session messages while allowing handshake messages to be handled in the background.

        Returns:
            An async generator yielding decrypted and decoded messages from peers
        """
        if self._nc is None:
            self._nc = await nats.connect(self.server_url)

        handshake_task = asyncio.create_task(self._listen_handshake_msgs(self._nc))
        try:
            async for message in self._listen_session_messages(self._nc):
                yield message
        finally:
            handshake_task.cancel()
            try:
                await handshake_task
            except asyncio.CancelledError:
                pass  # Expected when cancelling the task

    async def listen(self, message_handler: MessageHandler) -> None:
        """
        Listen for messages and process them with the provided handler.

        The handler can be either a synchronous or asynchronous function.
        Synchronous handlers are run in a separate thread to avoid blocking.

        Args:
            message_handler: Callback function to process received messages
        """
        try:
            async for message in self.messages():
                try:
                    # If message_handler is an async function, just await it
                    if inspect.iscoroutinefunction(message_handler):
                        await message_handler(message, self)
                    # Otherwise, run it in a worker thread so we don't block the event loop
                    else:
                        await anyio.to_thread.run_sync(message_handler, message, self)
                except Exception as e:
                    # Log handler errors but continue processing messages
                    print(f"Error in message handler: {e}")
        except asyncio.CancelledError:
            # Allow clean cancellation
            raise
        except Exception as e:
            # Log other errors but allow clean shutdown
            print(f"Error in message listener: {e}")

    def listen_sync(self, message_handler: MessageHandler) -> None:
        """
        Synchronous version of listen() that runs in the current thread.

        Args:
            message_handler: Callback function to process received messages
        """
        try:
            asyncio.run(self.listen(message_handler))
        except KeyboardInterrupt:
            # Allow clean Ctrl+C shutdown
            pass

    async def start(self):
        """
        Start the client and connect to the NATS server.
        Use this if not using the client as a context manager.
        """
        if self._running:
            return self

        self._nc = await nats.connect(self.server_url, {})
        self._js = self._nc.jetstream()
        self._js.publish
        await self._session_store.__aenter__()
        for middleware in self._middleware:
            await middleware.__aenter__()

        for middleware in self._middleware:
            await middleware.on_connect(self)

        self._running = True
        return self

    async def stop(self):
        """
        Stop the client and disconnect from the NATS server.
        Use this if not using the client as a context manager.
        """
        if not self._running:
            return

        for middleware in reversed(self._middleware):
            await middleware.on_disconnect(self)

        for middleware in reversed(self._middleware):
            await middleware.__aexit__(None, None, None)
        await self._session_store.__aexit__(None, None, None)
        if self._nc:
            await self._nc.close()
            self._nc = None

        self._running = False


async def create_client(
    actor_id: str | None,
    token: str | None,
    session_store: SessionStore | None,
    middleware: List[Middleware] = [],
    base_url: str = "https://api.acp.net",
    use_cloud_policy: bool = True,
    use_cloud_session_store: bool = True,
) -> AcpClient:
    """
    Helper function to create an AcpClient with the central authority.

    This function simplifies client creation by optionally adding cloud policy middleware
    that communicates with the central authority to verify allowed connections.

    Args:
        actor_id: Unique identifier for this actor
        token: Authentication token for this actor
        session_store: Storage backend for managing sessions
        middleware: List of middleware components for custom behavior
        base_url: Base URL for the central authority API
        use_cloud_policy: Whether to use the cloud whitelist policy

    Returns:
        Configured AcpClient instance ready for use
    """
    from .session.store import RedisSessionStore

    actor_id = actor_id or os.environ.get("ACP_ACTOR_ID")
    token = token or os.environ.get("ACP_TOKEN")

    if actor_id is None or token is None:
        raise ValueError("Actor ID and token must be provided")

    # TODO: authenticate with the central authority and get the
    # 1. NATS token
    # 2. Redis token

    if use_cloud_session_store and session_store is None:
        session_store = RedisSessionStore(redis_url="redis://acp.net:6379/0")

    if session_store is None:
        raise ValueError(
            "Session store must be provided or set `use_cloud_session_store` to True"
        )

    if use_cloud_policy:
        from .session.policy import (
            CloudWhitelistPolicy,
            SessionPolicyMiddleware,
        )

        middleware.append(
            SessionPolicyMiddleware(
                CloudWhitelistPolicy(
                    api_url="https://acp.net/api/v1/allowed-actors",
                    token=token,
                )
            )
        )
    client = AcpClient(actor_id, token, session_store, middleware)
    return client
