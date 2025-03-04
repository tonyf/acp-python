import asyncio
import logging
from typing import Any, AsyncGenerator, Dict, List

import nats
import nats.errors
import nats.js
from nats.js.api import ConsumerConfig
from nats.aio.client import Client as NatsClient
from nats.aio.client import Msg
from nats.js.client import JetStreamContext

from ..exceptions import SessionNotFound
from ..types import (
    AgentInfo,
    Session,
    EncryptedMessage,
    HandshakeRequest,
    HandshakeResponse,
)
from ..utils.iter import join_iters
from .base import Transport

logger = logging.getLogger(__name__)


class NatsTransport(Transport):
    """Transport implementation using NATS messaging system.

    Handles communication between agents using NATS JetStream for persistent messaging
    and core NATS for request-reply patterns during handshakes.
    """

    def __init__(self, server_url: str = "nats://localhost:4222"):
        """Initialize NATS transport with server URL.

        Args:
            server_url: NATS server URL to connect to

        Note:
            Connection is not established until connect() is called.
            Maintains a dictionary of pending handshakes for async request-reply pattern.
        """
        self._server_url = server_url
        self._nc: NatsClient = None  # type: ignore
        self._js: JetStreamContext = None  # type: ignore

        self._pending_handshakes: Dict[str, Msg] = {}

    def stream_name(self, agent: AgentInfo) -> str:
        """Generate stream name for an agent.

        Args:
            agent: Agent information

        Returns:
            Stream name string

        Note:
            Each agent has its own JetStream for message persistence.
        """
        return f"acp_agent_messages_{agent.name}"

    def consumer_name(self, agent: AgentInfo, session_id: str) -> str:
        """Generate consumer name for agent session.

        Args:
            agent: Agent information
            session_id: Session identifier

        Returns:
            Consumer name string

        Note:
            Each session has a dedicated consumer to track message delivery.
        """
        return f"{agent.name}_{session_id}"

    def message_key(self, agent: AgentInfo, session_id: str = "*") -> str:
        """Generate message subject key.

        Args:
            agent: Agent information
            session_id: Session identifier, defaults to wildcard

        Returns:
            Message subject key

        Note:
            Messages flow through NATS subjects using this naming pattern.
            Wildcard (*) allows subscribing to all sessions for an agent.
        """
        return f"acp.agent.{agent.name}.message.{session_id}"

    def handshake_key(self, agent_info: AgentInfo) -> str:
        """Generate handshake subject key.

        Args:
            agent_info: Agent information

        Returns:
            Handshake subject key

        Note:
            Handshakes use a separate subject from regular messages.
        """
        return f"acp.agent.{agent_info.name}.handshake"

    async def register_session(
        self, agent: AgentInfo, session_id: str
    ) -> Dict[str, Any]:
        """Register a new session for an agent.

        Args:
            agent: Agent information
            session_id: Session identifier

        Returns:
            Consumer configuration dictionary

        Flow:
            1. Creates a JetStream consumer for the session
            2. Configures message filtering by session_id
            3. Returns configuration for later subscription
        """
        consumer_info = await self._js.add_consumer(
            stream=self.stream_name(agent),
            name=agent.name,
            durable_name=agent.name,
            filter_subject=self.message_key(agent, session_id),
            deliver_subject=self._nc.new_inbox(),
            max_ack_pending=1,
            max_waiting=None,
        )
        return consumer_info.as_dict()

    async def connect(self):
        """Connect to NATS server.

        Flow:
            1. Checks if already connected
            2. Establishes connection to NATS server
            3. Initializes JetStream context
        """
        if self._nc is not None:
            logger.info(f"Already connected to NATS: {self._server_url}")
            return

        self._nc = await nats.connect(
            self._server_url,
            # Implement server-side auth
            signature_cb=None,
            user_jwt_cb=None,
        )
        self._js = self._nc.jetstream(timeout=None)

    async def send(self, to: AgentInfo, message: EncryptedMessage):
        """Send encrypted message to an agent.

        Args:
            to: Recipient agent information
            message: Encrypted message to send

        Flow:
            1. Serializes encrypted message to JSON
            2. Publishes to recipient's message subject with session_id
            3. Message is stored in JetStream for persistence
        """
        await self._js.publish(
            self.message_key(to, message.session_id),
            message.model_dump_json().encode(),
        )

    async def handshake_request(
        self, to: AgentInfo, request: HandshakeRequest
    ) -> HandshakeResponse:
        """Send handshake request and await response.

        Args:
            to: Target agent information
            request: Handshake request

        Returns:
            Handshake response

        Flow:
            1. Serializes request to JSON
            2. Sends request using NATS request-reply pattern
            3. Waits for response with 10 second timeout
            4. Deserializes and returns response
        """
        resp = await self._nc.request(
            self.handshake_key(to),
            request.model_dump_json().encode(),
            timeout=10,
        )
        return HandshakeResponse.model_validate_json(resp.data.decode())

    async def handshake_reply(self, to: AgentInfo, response: HandshakeResponse):
        """Reply to a pending handshake request.

        Args:
            to: Agent that initiated the handshake
            response: Handshake response

        Raises:
            Exception: If no pending handshake exists

        Flow:
            1. Retrieves pending message from dictionary
            2. Serializes response to JSON
            3. Sends response directly to the request's reply subject
        """
        msg = self._pending_handshakes.pop(to.name)
        if msg is None:
            raise Exception(f"No pending handshake for {to.name}")

        await msg.respond(response.model_dump_json().encode())

    async def handshakes(
        self, agent: AgentInfo
    ) -> AsyncGenerator[HandshakeRequest, None]:
        """Listen for incoming handshake requests.

        Args:
            agent: Agent information

        Yields:
            Handshake requests

        Flow:
            1. Subscribes to agent's handshake subject
            2. For each incoming message:
               a. Deserializes to HandshakeRequest
               b. Stores message for later reply
               c. Yields request to caller
               d. Acknowledges message after processing
            3. Caller is expected to call handshake_reply() with the response
        """
        handshake_sub = await self._nc.subscribe(
            self.handshake_key(agent),
        )

        async for msg in handshake_sub.messages:
            try:
                handshake_request = HandshakeRequest.model_validate_json(
                    msg.data.decode()
                )
                self._pending_handshakes[handshake_request.from_agent.name] = msg
                yield handshake_request
                await msg.ack()
            except Exception as e:
                logger.error(f"Error processing handshake: {e}")
                await msg.nak()

    async def messages(
        self, agent: AgentInfo, sessions: List[Session]
    ) -> AsyncGenerator[EncryptedMessage, None]:
        """Listen for incoming messages across multiple sessions.

        Args:
            agent: Agent information
            sessions: List of active sessions

        Yields:
            Encrypted messages

        Flow:
            1. Ensures JetStream exists for agent (creates or updates)
            2. Creates subscriptions for each session
            3. Merges message streams from all sessions
            4. For each incoming message:
               a. Marks message as in progress
               b. Deserializes to EncryptedMessage
               c. Yields message to caller
               d. Acknowledges message after processing
               e. Handles errors with appropriate NATS actions
        """
        try:
            await self._js.add_stream(
                name=self.stream_name(agent),
                subjects=[self.message_key(agent, "*")],
            )
        except Exception:
            logger.debug(
                f"Stream {self.stream_name(agent)} already exists, updating..."
            )
            await self._js.update_stream(
                name=self.stream_name(agent),
                subjects=[self.message_key(agent, "*")],
            )

        msg_subs: List[JetStreamContext.PushSubscription] = []

        msg_subs = await asyncio.gather(
            *[
                self._js.subscribe_bind(
                    stream=self.stream_name(agent),
                    config=ConsumerConfig(**session.transport_metadata["config"]),
                    consumer=self.consumer_name(agent, session.session_id),
                )
                for session in sessions
            ]
        )

        async for msg in join_iters(*[sub.messages for sub in msg_subs]):
            try:
                await msg.in_progress()
                encrypted_message = EncryptedMessage.model_validate_json(
                    msg.data.decode()
                )
                yield encrypted_message
                await msg.ack()
            except SessionNotFound as e:
                logger.warning(f"Session {e.session_id} not found")
                await msg.term()
            except Exception as e:
                logger.error(f"Error processing message: {e}")
                await msg.nak()
