from typing import List
import nats
from nats.aio.client import Msg
from abc import abstractmethod, ABC
import uuid
import asyncio
from .types import (
    AgentInfo,
    ConversationSession,
    TextMessage,
    EncryptedMessage,
    HandshakeRequest,
    HandshakeResponse,
    KeyPair,
)
from .session.store import SessionStore, default_session_store
from .session.policy import SessionPolicy, AllowAllPolicy
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class Agent(ABC):
    def __init__(
        self,
        name: str,
        description: str,
        peers: List[AgentInfo] = [],
        server_url: str = "nats://localhost:4222",
        session_store: SessionStore = default_session_store,
        session_policy: SessionPolicy = AllowAllPolicy(),
    ):
        self._name = name
        self._description = description
        self._server_url = server_url
        self._peers = peers

        self._session_store = session_store
        self._session_policy = session_policy

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

    def message_key(self, agent_info: AgentInfo, session_id: str = "*") -> str:
        return f"acp.agent.{agent_info.name}.message.{session_id}"

    def handshake_key(self, agent_info: AgentInfo) -> str:
        return f"acp.agent.{agent_info.name}.handshake"

    ##
    ## Message API
    ##

    async def _message_handler(self, msg: Msg):
        await msg.ack()

        encrypted_message = EncryptedMessage.model_validate_json(msg.data)
        session = await self._session_store.get_session(
            self.info.name, encrypted_message.session_id
        )
        if session is None:
            return

        # Decrypt the message and append it to the session
        decrypted_message = encrypted_message.decrypt(
            session.my_keypair.private_key.exchange(session.peer_public_key)
        )
        updated_session = session.append(decrypted_message)

        await self._session_store.set_session(
            self.info.name, decrypted_message.session_id, updated_session
        )
        await self.on_message(updated_session)

    @abstractmethod
    async def on_message(self, session: ConversationSession):
        pass

    async def register_peer(self, *peers: AgentInfo):
        self._peers.extend(peers)

    async def send(self, to: AgentInfo, message: TextMessage):
        # Get the session
        session = await self._session_store.get_session(
            self.info.name, message.session_id
        )
        if session is None:
            raise Exception(
                f"Session {message.session_id} with {to.name} not found. "
                "Make sure to establish a session with the peer first."
            )

        encrypted_message = message.encrypt(
            session.my_keypair.private_key.exchange(session.peer_public_key)
        )

        # Send the message to the peer
        await self._js.publish(
            self.message_key(to, message.session_id),
            encrypted_message.model_dump_json().encode(),
        )

        # Update the session with the new message
        await self._session_store.set_session(
            self.info.name, message.session_id, session.append(message)
        )

    ##
    ## Session API
    ##

    async def _handshake_handler(self, msg: Msg):
        handshake_request = HandshakeRequest.model_validate_json(msg.data)
        logger.info(f"Handshake request: {handshake_request}")

        should_accept, reason = await self._session_policy(handshake_request.from_agent)
        if should_accept:
            session = ConversationSession(
                session_id=handshake_request.session_id,
                original_user=handshake_request.from_agent,
                participants=[handshake_request.from_agent, self.info],
            )
            await self._session_store.set_session(
                self.info.name,
                handshake_request.session_id,
                session,
            )
            await msg.respond(
                HandshakeResponse(
                    session_id=handshake_request.session_id,
                    metadata=handshake_request.metadata,
                    accept=True,
                )
                .model_dump_json()
                .encode(),
            )
        else:
            await msg.respond(
                HandshakeResponse(
                    session_id=handshake_request.session_id,
                    metadata=handshake_request.metadata,
                    accept=False,
                    reason=reason,
                )
                .model_dump_json()
                .encode(),
            )

    async def establish_session(
        self, peer: AgentInfo, session_id: str | None = None, metadata: dict = {}
    ) -> str:
        """
        Establish a new session with another agent or user.
        Returns the session_id that can be used for future communications.
        """
        logger.info(f"Establishing session with {peer.name}")
        session_id = session_id or str(uuid.uuid4())
        if (
            session := await self._session_store.get_session(self.info.name, session_id)
        ) is not None:
            raise Exception(f"Session {session_id} already exists")

        # Generate a keypair
        keypair = KeyPair.generate()
        handshake_request = (
            HandshakeRequest(
                from_agent=self.info,
                session_id=session_id,
                metadata=metadata or {},
                public_key=keypair.public_key,
            )
            .model_dump_json()
            .encode()
        )
        resp = await self._nc.request(
            self.handshake_key(peer),
            handshake_request,
        )
        logger.info(f"Handshake response: {resp.data}")

        handshake_response = HandshakeResponse.model_validate_json(resp.data)
        if not handshake_response.accept or handshake_response.public_key is None:
            raise Exception("Handshake rejected")

        # Create a new session
        session = ConversationSession(
            session_id=session_id,
            my_keypair=keypair,
            peer_public_key=handshake_response.public_key,
            original_user=peer,
            participants=[peer, self.info],
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
            metadata=metadata or {},
        )

        # Save the updated session
        await self._session_store.set_session(self.info.name, session_id, session)
        logger.info(f"Created session: {session}")
        return session_id

    ##
    ## Lifecycle API
    ##

    async def connect(self):
        # Setup clients
        self._nc = await nats.connect(self._server_url)
        self._js = self._nc.jetstream(timeout=None)

        # Setup resources
        try:
            await self._js.add_stream(
                name=f"acp_agent_messages_{self._name}",
                subjects=[self.message_key(self.info, "*")],
            )
        except Exception:
            pass

        self._msg_sub = await self._js.subscribe(
            self.message_key(self.info, "*"),
            # durable=self._name,
        )
        self._handshake_sub = await self._nc.subscribe(
            self.handshake_key(self.info),
            # durable=self._name,
        )

    async def run(self, peers: List[AgentInfo] = []):
        if self._nc is None or self._js is None:
            await self.connect()

        # Register peers
        for peer in peers:
            await self.register_peer(peer)

        # Run infinitely by waiting forever
        async def _process_messages():
            async for msg in self._msg_sub.messages:
                await self._message_handler(msg)

        async def _process_handshakes():
            async for msg in self._handshake_sub.messages:
                await self._handshake_handler(msg)

        # Create tasks for both subscriptions
        msg_task = asyncio.create_task(_process_messages())
        handshake_task = asyncio.create_task(_process_handshakes())

        # Wait for both tasks to complete (they won't unless there's an error)
        await asyncio.gather(msg_task, handshake_task)
