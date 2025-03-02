from typing import List, Dict

import nats
import nats.errors
import nats.js
from nats.aio.client import Msg, Client as NatsClient
from nats.js.client import JetStreamContext
from nats.js.api import ConsumerInfo
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
from .crypto import decrypt, encrypt
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

        self._nc: NatsClient = None  # type: ignore
        self._js: JetStreamContext = None  # type: ignore
        self._consumers: Dict[str, ConsumerInfo] = {}

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

    async def _message_handler(self, msg: Msg):
        await msg.in_progress()

        encrypted_message = EncryptedMessage.model_validate_json(msg.data.decode())
        session = await self._session_store.get_session(
            self.info.name, encrypted_message.session_id
        )
        if session is None:
            logger.warning(f"Session {encrypted_message.session_id} not found")
            await msg.term()
            return

        try:
            # Decrypt the message and append it to the session
            decrypted_message = decrypt(
                encrypted_message,
                session.my_keypair.private_key.exchange(session.peer_public_key),
            )
            updated_session = session.append(decrypted_message)

            await self._session_store.set_session(
                self.info.name, decrypted_message.session_id, updated_session
            )
            await self.on_message(updated_session)
            await msg.ack()
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            await msg.nak()
            await self._session_store.set_session(
                self.info.name, decrypted_message.session_id, session
            )

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

        encrypted_message = encrypt(
            message,
            session.my_keypair.private_key.exchange(session.peer_public_key),
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
        print(f"Sent message to {to.name}")

    ##
    ## Session API
    ##

    async def _handshake_handler(self, msg: Msg):
        handshake_request = HandshakeRequest.model_validate_json(msg.data)
        logger.info(f"Handshake request: {handshake_request}")

        should_accept, reason = await self._session_policy(handshake_request.from_agent)
        print(f"Handshake response: {should_accept} {reason}")
        if should_accept:
            # Create a new session
            keypair = KeyPair.generate()
            session = ConversationSession(
                session_id=handshake_request.session_id,
                original_user=handshake_request.from_agent,
                participants=[handshake_request.from_agent, self.info],
                my_keypair=keypair,
                peer_public_key=handshake_request.public_key,
            )
            await self._session_store.set_session(
                self.info.name,
                session.session_id,
                session,
            )
            await msg.respond(
                HandshakeResponse(
                    session_id=handshake_request.session_id,
                    metadata=handshake_request.metadata,
                    accept=True,
                    public_key=keypair.public_key,
                )
                .model_dump_json()
                .encode(),
            )
            consumer_info = await self._js.add_consumer(
                stream=self.stream_name,
                name=self._name,
                durable_name=self._name,
                filter_subject=self.message_key(self.info, session.session_id),
                deliver_subject=self._nc.new_inbox(),
                max_ack_pending=1,
                max_waiting=None,
            )
            self._consumers[session.session_id] = consumer_info

        # Respond to the handshake request
        await msg.respond(
            HandshakeResponse(
                session_id=handshake_request.session_id,
                metadata=handshake_request.metadata,
                accept=should_accept,
                reason=reason,
            )
            .model_dump_json()
            .encode(),
        )
        await msg.ack()

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
            timeout=5,
        )

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
        await self._session_store.set_session(self.info.name, session_id, session)
        consumer_info = await self._js.add_consumer(
            stream=self.stream_name,
            name=self._name,
            durable_name=self._name,
            filter_subject=self.message_key(self.info, session.session_id),
            deliver_subject=self._nc.new_inbox(),
            max_ack_pending=1,
            max_waiting=None,
        )
        self._consumers[session_id] = consumer_info
        return session_id

    ##
    ## Lifecycle API
    ##

    async def connect(self):
        if self._nc is not None:
            return

        self._nc = await nats.connect(self._server_url)
        self._js = self._nc.jetstream(timeout=None)

        try:
            await self._js.add_stream(
                name=self.stream_name,
                subjects=[self.message_key(self.info, "*")],
            )
        except Exception:
            await self._js.update_stream(
                name=self.stream_name,
                subjects=[self.message_key(self.info, "*")],
            )

    async def run(self, peers: List[AgentInfo] = []):
        await self.connect()
        for peer in peers:
            await self.register_peer(peer)

        async def _process_messages():
            msg_subs: List[JetStreamContext.PushSubscription] = []
            while True:
                if len(self._consumers) != len(msg_subs):
                    logger.debug(
                        "A new consumer has been created. Re-subscribing to messages."
                    )
                    await asyncio.gather(*[sub.unsubscribe for sub in msg_subs])
                    msg_subs = await asyncio.gather(
                        *[
                            self._js.subscribe_bind(
                                stream=self.stream_name,
                                config=info.config,
                                consumer=self.consumer_name(session_id),
                            )
                            for session_id, info in self._consumers.items()
                        ]
                    )

                for sub in msg_subs:
                    try:
                        msg = await sub.next_msg()
                        await self._message_handler(msg)
                    except asyncio.TimeoutError:
                        continue

                await asyncio.sleep(1)

        async def _process_handshakes():
            handshake_sub = await self._nc.subscribe(
                self.handshake_key(self.info),
            )

            while True:
                try:
                    msg = await handshake_sub.next_msg()
                    await self._handshake_handler(msg)
                except asyncio.TimeoutError:
                    await asyncio.sleep(1)
                    continue

        # Wait for both tasks to complete (they won't unless there's an error)
        await asyncio.gather(_process_messages(), _process_handshakes())
