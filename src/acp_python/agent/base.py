import asyncio
import logging
import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from typing import AsyncGenerator, List

from .exceptions import SessionNotFound
from .session.policy import AllowAllPolicy, SessionPolicy
from .session.store import SessionStore, default_session_store
from .transport.base import Transport
from .types import (
    AgentInfo,
    Session,
    HandshakeRequest,
    HandshakeResponse,
    KeyPair,
    TextMessage,
)
from .utils.crypto import decrypt, encrypt

logger = logging.getLogger(__name__)


class Agent(ABC):
    def __init__(
        self,
        name: str,
        description: str,
        transport: Transport,
        peers: List[AgentInfo] | None = None,
        session_store: SessionStore = default_session_store,
        session_policy: SessionPolicy = AllowAllPolicy(),
    ):
        self._name = name
        self._description = description
        self._transport = transport
        self._peers = peers or []

        self._session_store = session_store
        self._session_policy = session_policy
        self._sessions_updated = asyncio.Event()

    @property
    def name(self) -> str:
        return self._name

    @property
    def info(self) -> AgentInfo:
        return AgentInfo(
            name=self._name,
            description=self._description,
        )

    @property
    def peers(self) -> List[AgentInfo]:
        return self._peers

    @property
    def stream_name(self) -> str:
        return f"acp_agent_messages_{self._name}"

    def consumer_name(self, session_id: str) -> str:
        return f"{self._name}_{session_id}"

    def message_key(self, agent_info: AgentInfo, session_id: str = "*") -> str:
        return f"acp.agent.{agent_info.name}.message.{session_id}"

    def handshake_key(self, agent_info: AgentInfo) -> str:
        return f"acp.agent.{agent_info.name}.handshake"

    ##
    ## Message API
    ##

    async def messages(self) -> AsyncGenerator[Session, None]:
        while True:
            self._sessions_updated.clear()
            sessions = await self._session_store.active_sessions(self.info.name)
            logger.debug(f"Listening for messages from {len(sessions)} sessions")

            async for encrypted_message in self._transport.messages(
                self.info, sessions
            ):
                # Check if sessions were updated
                if self._sessions_updated.is_set():
                    logger.debug("Sessions updated, breaking")
                    break

                session = await self._session_store.get_session(
                    self.info.name, encrypted_message.session_id
                )
                if session is None:
                    logger.debug(f"Session {encrypted_message.session_id} not found")
                    # raise SessionNotFound(encrypted_message.session_id)
                    continue

                # Decrypt the message
                decrypted_message = decrypt(
                    encrypted_message,
                    session.my_keypair.private_key.exchange(session.peer_public_key),
                )

                # Append the message to the session
                updated_session = session.append(decrypted_message)
                await self._session_store.set_session(
                    self.info.name, decrypted_message.session_id, updated_session
                )

                try:
                    yield updated_session
                except Exception as e:
                    # Restore the session to the previous state if the message handler raises an error
                    await self._session_store.set_session(
                        self.info.name, decrypted_message.session_id, session
                    )
                    raise e

    async def register_peer(self, *peers: AgentInfo):
        self._peers.extend(peers)

    async def send(self, to: AgentInfo, message: TextMessage):
        session = await self._session_store.get_session(
            self.info.name, message.session_id
        )
        if session is None:
            raise Exception(
                f"Session {message.session_id} with {to.name} not found. "
                "Make sure to establish a session with the peer first."
            )

        # Encrypt the message and send it to the peer
        encrypted_message = encrypt(
            message,
            session.my_keypair.private_key.exchange(session.peer_public_key),
        )

        updated_session = session.append(message)
        await self._session_store.set_session(
            self.info.name, message.session_id, updated_session
        )

        try:
            await self._transport.send(to, encrypted_message)
        except Exception as e:
            # Restore the session to the previous state if the message send fails
            await self._session_store.set_session(
                self.info.name, message.session_id, session
            )
            raise e

    ##
    ## Session API
    ##

    async def on_handshake(self, request: HandshakeRequest):
        should_accept, reason = await self._session_policy(request.from_agent)
        if should_accept:
            # Create a new session
            keypair = KeyPair.generate()
            metadata = await self._transport.register_session(
                self.info, request.session_id
            )
            await self._session_store.set_session(
                self.info.name,
                request.session_id,
                Session(
                    me=self.info,
                    session_id=request.session_id,
                    transport_metadata=metadata,
                    original_user=request.from_agent,
                    participants=[request.from_agent, self.info],
                    my_keypair=keypair,
                    peer_public_key=request.public_key,
                ),
            )
            self._sessions_updated.set()
            logger.debug(
                f"[Receiver] Handshake accepted, created session: {request.session_id}"
            )
            await self._transport.handshake_reply(
                request.from_agent,
                HandshakeResponse(
                    session_id=request.session_id,
                    metadata=request.metadata,
                    accept=True,
                    public_key=keypair.public_key,
                ),
            )

        else:
            await self._transport.handshake_reply(
                request.from_agent,
                HandshakeResponse(
                    session_id=request.session_id,
                    metadata=request.metadata,
                    accept=False,
                    reason=reason,
                ),
            )

    async def establish_session(
        self, peer: AgentInfo, session_id: str | None = None, metadata: dict = {}
    ) -> str:
        """
        Establish a new session with another agent or user.
        Returns the session_id that can be used for future communications.
        """
        # Check if the session already exists
        logger.info(f"Establishing session with {peer.name}")
        session_id = session_id or str(uuid.uuid4())
        existing_session = await self._session_store.get_session(
            self.info.name, session_id
        )
        if existing_session is not None:
            raise Exception(f"Session {session_id} already exists")

        # Generate a keypair
        keypair = KeyPair.generate()
        handshake_response = await self._transport.handshake_request(
            peer,
            HandshakeRequest(
                from_agent=self.info,
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
            self.info.name,
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
        logger.debug(f"[Sender] Handshake accepted, created session: {session_id}")
        self._sessions_updated.set()
        return session_id

    ##
    ## Lifecycle API
    ##

    async def run_handshakes(self):
        async for handshake in self._transport.handshakes(self.info):
            await self.on_handshake(handshake)

    @abstractmethod
    async def on_message(self, session: Session):
        pass

    async def run(self):
        handshake_task = asyncio.create_task(self.run_handshakes())

        try:
            async for session in self.messages():
                await self.on_message(session)
        finally:
            # Ensure handshake task is cleaned up
            handshake_task.cancel()
            try:
                await handshake_task
            except asyncio.CancelledError:
                pass
