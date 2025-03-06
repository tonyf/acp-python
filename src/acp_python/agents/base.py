import asyncio
import logging
import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from typing import List

from acp_python.session.policy import AllowAllPolicy, SessionPolicy
from acp_python.session.store import SessionStore, default_session_store
from acp_python.transport.base import AsyncTransport
from acp_python.types import (
    ActorInfo,
    HandshakeRequest,
    HandshakeResponse,
    KeyPair,
    Message,
    MessageEnvelope,
    Session,
    exceptions,
)
from acp_python.utils.crypto import decrypt, encrypt

logger = logging.getLogger(__name__)


class AsyncActor(ABC):
    """Base async actor class for secure communication between actors.

    Provides core functionality for session management, message encryption/decryption,
    and peer-to-peer communication. Subclasses must implement on_message().

    Flow:
    1. Initialize with name, description, and transport
    2. Establish sessions with peers via handshakes
    3. Send/receive encrypted messages within sessions
    4. Process messages via on_message() handler
    """

    def __init__(
        self,
        identifier: str,
        description: str,
        transport: AsyncTransport,
        peers: List[ActorInfo] | None = None,
        session_store: SessionStore = default_session_store,
        session_policy: SessionPolicy = AllowAllPolicy(),
    ):
        """Initialize agent with identity and communication components.

        Args:
            name: Unique identifier for this agent
            description: Human-readable description
            transport: Communication layer implementation
            peers: Optional list of known peers
            session_store: Storage for session state
            session_policy: Policy for accepting handshakes
        """
        self._identifier = identifier
        self._description = description
        self._transport = transport
        self._peers = peers or []

        self._session_store = session_store
        self._session_policy = session_policy
        self._sessions_updated = asyncio.Event()

    ##
    ## Properties
    ##

    @property
    def identifier(self) -> str:
        """Get agent's unique name."""
        return self._identifier

    @property
    def info(self) -> ActorInfo:
        """Get actor's public information."""
        return ActorInfo(
            identifier=self._identifier,
            description=self._description,
        )

    @property
    def peers(self) -> List[ActorInfo]:
        """Get list of known peers."""
        return self._peers

    ##
    ## Internal Handlers
    ##

    async def _handshake_handler(self, request: HandshakeRequest):
        """Process incoming handshake request.

        Args:
            request: Handshake request from peer

        Flow:
            1. Evaluates request against session policy
            2. If accepted, creates new session with key exchange
            3. Registers session with transport
            4. Stores session in session store
            5. Sends handshake response to peer
        """
        should_accept, reason = await self._session_policy(request)
        if should_accept:
            # Create a new session
            keypair = KeyPair.generate()
            metadata = await self._transport.register_session(
                self.info, request.session_id
            )
            await self._session_store.set_session(
                self.info.identifier,
                request.session_id,
                Session(
                    me=self.info,
                    session_id=request.session_id,
                    transport_metadata=metadata,
                    original_user=request.from_actor,
                    participants=[request.from_actor, self.info],
                    my_keypair=keypair,
                    peer_public_key=request.public_key,
                ),
            )
            self._sessions_updated.set()
            logger.debug(
                f"[{self.info.identifier}] Handshake accepted, created session: {request.session_id}"
            )
            await self._transport.handshake_reply(
                request.from_actor,
                HandshakeResponse(
                    session_id=request.session_id,
                    metadata=request.metadata,
                    accept=True,
                    public_key=keypair.public_key,
                ),
            )

        else:
            await self._transport.handshake_reply(
                request.from_actor,
                HandshakeResponse(
                    session_id=request.session_id,
                    metadata=request.metadata,
                    accept=False,
                    reason=reason,
                ),
            )

    async def _get_session_for_message(
        self, to: ActorInfo, message: Message
    ) -> Session:
        """Helper to retrieve and validate session for a message.

        Raises:
            Exception: If session doesn't exist
        """
        session = await self._session_store.get_session(
            self.info.identifier, message.session_id
        )
        if session is None:
            raise Exception(
                f"Session {message.session_id} with {to.identifier} not found. "
                "Make sure to establish a session with the peer first."
            )
        return session

    async def _prepare_encrypted_message(
        self, session: Session, message: Message
    ) -> tuple[Session, Message]:
        """Helper to encrypt message and update session state.

        Returns:
            Tuple of (updated_session, encrypted_message)
        """
        encrypted_message = encrypt(
            message,
            session.my_keypair.private_key.exchange(session.peer_public_key),
        )
        updated_session = session.append(message)
        await self._session_store.set_session(
            self.info.identifier, message.session_id, updated_session
        )
        return updated_session, encrypted_message

    async def _message_handler(self, envelope: MessageEnvelope):
        """Listen for and process incoming messages across all sessions.

        Yields:
            Updated sessions containing new messages

        Flow:
            1. Retrieves active sessions from store
            2. Listens for encrypted messages via transport
            3. Decrypts messages using session keys
            4. Updates session state with new messages
            5. Yields updated sessions to caller
            6. Handles errors by restoring previous session state
        """
        sessions = await self._session_store.active_sessions(self.info.identifier)
        logger.debug(
            f"[{self.info.identifier}] Listening for messages from {len(sessions)} sessions"
        )

        if self._sessions_updated.is_set():
            self._sessions_updated.clear()
            raise exceptions.SessionsUpdated()

        session = await self._session_store.get_session(
            self.info.identifier, envelope.session_id
        )
        if session is None:
            raise exceptions.SessionNotFound(
                envelope.session_id,
            )

        # Decrypt the message
        message = decrypt(
            envelope,
            session.my_keypair.private_key.exchange(session.peer_public_key),
        )

        # Append the message to the session
        updated_session = session.append(message)
        await self._session_store.set_session(
            self.info.identifier, message.session_id, updated_session
        )

        try:
            await self.on_message(updated_session)
        except Exception as e:
            # Restore the session to the previous state if the message handler raises an error
            await self._session_store.set_session(
                self.info.identifier, message.session_id, session
            )
            raise e

    ##
    ## Public API
    ##

    async def register_peer(self, *peers: ActorInfo):
        """Register one or more peers with this actor.

        Args:
            peers: Agent information for peers to register
        """
        self._peers.extend(peers)

    async def send(self, to: ActorInfo, message: Message):
        """Send an encrypted message to a peer."""
        session = await self._get_session_for_message(to, message)
        try:
            _, encrypted_message = await self._prepare_encrypted_message(
                session, message
            )
            await self._transport.send(to, encrypted_message)
        except Exception as e:
            await self._session_store.set_session(
                self.info.identifier, message.session_id, session
            )
            raise e

    async def request(self, to: ActorInfo, message: Message) -> Session:
        """Send an encrypted message to a peer and wait for a response."""
        session = await self._get_session_for_message(to, message)
        try:
            updated_session, encrypted_message = await self._prepare_encrypted_message(
                session, message
            )

            response = await self._transport.request(to, encrypted_message)
            decrypted_message = decrypt(
                response,
                session.my_keypair.private_key.exchange(session.peer_public_key),
            )

            # Append the response to the session
            final_session = updated_session.append(decrypted_message)
            await self._session_store.set_session(
                self.info.identifier, decrypted_message.session_id, final_session
            )
            return final_session
        except Exception as e:
            await self._session_store.set_session(
                self.info.identifier, message.session_id, session
            )
            raise e

    async def establish_session(
        self, peer: ActorInfo, session_id: str | None = None, metadata: dict = {}
    ) -> str:
        """Establish a new session with another actor.

        Args:
            peer: Actor to establish session with
            session_id: Optional custom session ID
            metadata: Optional session metadata

        Returns:
            Session ID for the established session

        Raises:
            Exception: If session already exists or handshake is rejected

        Flow:
            1. Generates session ID if not provided
            2. Creates keypair for secure communication
            3. Sends handshake request to peer
            4. Registers session with transport
            5. Creates and stores local session state
        """
        # Check if the session already exists
        logger.info(
            f"[{self.info.identifier}] Establishing session with {peer.identifier}"
        )
        session_id = session_id or str(uuid.uuid4())
        existing_session = await self._session_store.get_session(
            self.info.identifier, session_id
        )
        if existing_session is not None:
            raise Exception(f"Session {session_id} already exists")

        # Generate a keypair
        keypair = KeyPair.generate()
        handshake_response = await self._transport.handshake_request(
            peer,
            HandshakeRequest(
                from_actor=self.info,
                session_id=session_id,
                metadata=metadata or {},
                public_key=keypair.public_key,
            ),
        )
        if not handshake_response.accept or handshake_response.public_key is None:
            raise Exception("Handshake rejected")

        # Create a new session
        metadata = await self._transport.register_session(self.info, session_id)
        await self._session_store.set_session(
            self.info.identifier,
            session_id,
            Session(
                me=self.info,
                session_id=session_id,
                transport_metadata=metadata,
                my_keypair=keypair,
                peer_public_key=handshake_response.public_key,
                original_user=peer,
                participants=[peer, self.info],
                created_at=datetime.now().isoformat(),
                updated_at=datetime.now().isoformat(),
            ),
        )
        logger.debug(
            f"[{self.info.identifier}] Handshake accepted, created session: {session_id}"
        )
        self._sessions_updated.set()
        return session_id

    ##
    ## Lifecycle API
    ##

    async def handshakes(self):
        """Listen for and process incoming handshake requests.

        Continuously monitors transport for handshake requests
        and processes them via on_handshake().
        """
        await self._transport.handshakes(
            self.info,
            self._handshake_handler,
        )

    async def messages(self):
        """Listen for and process incoming messages across all sessions.
        Forces a reconnect if the sessions are updated.
        """
        while True:
            try:
                await self._transport.messages(
                    self.info,
                    await self._session_store.active_sessions(self.info.identifier),
                    self._message_handler,
                )
            except exceptions.SessionsUpdated:
                pass
            await asyncio.sleep(1)

    async def run(self):
        """Run the agent's main processing loop.

        Starts handshake listener and message processing loops.
        Subclasses should call this method to activate the agent.

        Flow:
            1. Creates task for handshake processing
            2. Processes incoming messages via on_message()
            3. Ensures proper cleanup of tasks on exit
        """
        await asyncio.gather(
            self.handshakes(),
            self.messages(),
        )

    ##
    ## User-defined methods
    ##

    @abstractmethod
    async def on_message(self, session: Session):
        """Process incoming messages & tasks.

        Args:
            session: Updated session containing new message

        Note:
            Subclasses must implement this method to handle message and tasks.
            The most recent message is available as session.history[-1].
        """
        pass
