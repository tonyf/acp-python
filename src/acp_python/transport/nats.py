import asyncio
import logging
from typing import Any, Dict, List, Coroutine, Tuple, Optional
from functools import partial
import nats
import nats.errors
import nats.js
from nats.js.api import ConsumerConfig
from nats.aio.client import Client as NatsClient
from nats.aio.client import Msg
from nats.js.client import JetStreamContext

from acp_python.types.exceptions import SessionNotFound, SessionsUpdated
from acp_python.types import (
    ActorInfo,
    Session,
    MessageEnvelope,
    HandshakeRequest,
    HandshakeResponse,
)
from ..utils.iter import join_iters
from .base import AsyncTransport

logger = logging.getLogger(__name__)


class AsyncNatsTransport(AsyncTransport):
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

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.close()

    def stream_name(self, actor: ActorInfo) -> str:
        """Generate stream name for an actor.

        Args:
            actor: Actor information

        Returns:
            Stream name string

        Note:
            Each actor has its own JetStream for message persistence.
        """
        return f"acp_actor_messages_{actor.identifier}"

    def consumer_name(self, actor: ActorInfo, session_id: str) -> str:
        """Generate consumer name for actor session.

        Args:
            actor: Actor information
            session_id: Session identifier

        Returns:
            Consumer name string

        Note:
            Each session has a dedicated consumer to track message delivery.
        """
        return f"{actor.identifier}_{session_id}"

    def message_key(self, actor: ActorInfo, session_id: str = "*") -> str:
        """Generate message subject key.

        Args:
            actor: Actor information
            session_id: Session identifier, defaults to wildcard

        Returns:
            Message subject key

        Note:
            Messages flow through NATS subjects using this naming pattern.
            Wildcard (*) allows subscribing to all sessions for an agent.
        """
        return f"acp.actor.{actor.identifier}.inbox.{session_id}"

    def request_key(self, actor: ActorInfo, session_id: str = "*") -> str:
        """Generate request-reply subject key.

        Args:
            actor: Actor information
            session_id: Session identifier, defaults to wildcard

        Returns:
            Message subject key

        Note:
            Messages flow through NATS subjects using this naming pattern.
            Wildcard (*) allows subscribing to all sessions for an agent.
        """
        return f"acp.actor.{actor.identifier}.request.{session_id}"

    def handshake_key(self, actor: ActorInfo) -> str:
        """Generate handshake subject key.

        Args:
            actor: Actor information

        Returns:
            Handshake subject key

        Note:
            Handshakes use a separate subject from regular messages.
        """
        return f"acp.actor.{actor.identifier}.handshake"

    async def register_session(self, me: ActorInfo, session_id: str) -> Dict[str, Any]:
        """Register a new session for an actor.

        Args:
            me: Actor information
            session_id: Session identifier

        Returns:
            Consumer configuration dictionary

        Flow:
            1. Creates a JetStream consumer for the session
            2. Configures message filtering by session_id
            3. Returns configuration for later subscription
        """
        consumer_info = await self._js.add_consumer(
            stream=self.stream_name(me),
            name=me.identifier,
            durable_name=me.identifier,
            filter_subject=self.message_key(me, session_id),
            deliver_subject=self._nc.new_inbox(),
            max_ack_pending=1,
            max_waiting=None,
        )
        return consumer_info.as_dict()

    async def close_session(self, me: ActorInfo, session_id: str):
        """Close a session for an actor.

        Args:
            actor: Actor information
            session_id: Session identifier
        """
        await self._js.delete_consumer(
            stream=self.stream_name(me),
            consumer=self.consumer_name(me, session_id),
        )

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

    async def close(self):
        """Close NATS connection.

        Flow:
            Closes JetStream context
            Closes NATS connection
        """
        await self._nc.close()
        self._nc = None
        self._js = None

    async def send(self, to: ActorInfo, message: MessageEnvelope):
        """Send encrypted message to an actor.

        Args:
            to: Recipient actor information
            message: Encrypted message to send

        Flow:
            1. Serializes encrypted message to JSON
            2. Publishes to recipient's message subject with session_id
            3. Message is stored in JetStream for persistence
        """
        logger.debug(f"[{to.identifier}] Sending message: {message.model_dump_json()}")
        await self._js.publish(
            self.message_key(to, message.session_id),
            message.model_dump_json().encode(),
        )
        logger.debug(f"[{to.identifier}] Message sent to {to.identifier}")

    async def request(
        self, to: ActorInfo, message: MessageEnvelope, timeout: int = 10
    ) -> MessageEnvelope:
        logger.debug(f"[{to.identifier}] Sending request: {message.model_dump_json()}")
        resp = await self._nc.request(
            self.request_key(to, message.session_id),
            message.model_dump_json().encode(),
            timeout=timeout,
        )
        if resp.data == b"+WPI":
            sub = await self._nc.subscribe(resp.subject)
            resp = await sub.next_msg(timeout=timeout)

        logger.debug(f"[{to.identifier}] Received response: {resp.data.decode()}")
        return MessageEnvelope.model_validate_json(resp.data.decode())

    async def handshake_request(
        self, to: ActorInfo, request: HandshakeRequest
    ) -> HandshakeResponse:
        """Send handshake request and await response.

        Args:
            to: Target actor information
            request: Handshake request

        Returns:
            Handshake response

        Flow:
            1. Serializes request to JSON
            2. Sends request using NATS request-reply pattern
            3. Waits for response with 10 second timeout
            4. Deserializes and returns response
        """
        logger.debug(
            f"[{request.from_actor.identifier}] Sending handshake request to {to.identifier}"
        )
        resp = await self._nc.request(
            self.handshake_key(to),
            request.model_dump_json().encode(),
            timeout=10,
        )
        logger.debug(
            f"[{request.from_actor.identifier}] Received handshake response from {to.identifier}: {resp.data.decode()}"
        )
        return HandshakeResponse.model_validate_json(resp.data.decode())

    async def handshake_reply(self, to: ActorInfo, response: HandshakeResponse):
        """Reply to a pending handshake request.

        Args:
            to: Actor that initiated the handshake
            response: Handshake response

        Raises:
            Exception: If no pending handshake exists

        Flow:
            1. Retrieves pending message from dictionary
            2. Serializes response to JSON
            3. Sends response directly to the request's reply subject
        """
        msg = self._pending_handshakes.pop(to.identifier)
        if msg is None:
            raise Exception(f"[{to.identifier}] No pending handshake")

        logger.debug(
            f"Responding to handshake request with {response.model_dump_json()}"
        )
        await msg.respond(response.model_dump_json().encode())

    async def handshakes(
        self,
        actor: ActorInfo,
        handshake_handler: Coroutine[HandshakeRequest, None, None],
    ):
        """Listen for incoming handshake requests.

        Args:
            actor: Actor information

        Yields:
            Handshake requests

        Flow:
            1. Subscribes to actor's handshake subject
            2. For each incoming message:
               a. Deserializes to HandshakeRequest
               b. Stores message for later reply
               c. Yields request to caller
               d. Acknowledges message after processing
            3. Caller is expected to call handshake_reply() with the response
        """
        handshake_sub = await self._nc.subscribe(
            self.handshake_key(actor),
        )

        async for msg in handshake_sub.messages:
            try:
                handshake_request = HandshakeRequest.model_validate_json(
                    msg.data.decode()
                )
                logger.debug(
                    f"[{actor.identifier}] Received handshake request from {handshake_request.from_actor.identifier}"
                )
                self._pending_handshakes[handshake_request.from_actor.identifier] = msg
                await handshake_handler(handshake_request)
                logger.debug(f"[{actor.identifier}] Acknowledging handshake request")
                await msg.ack()
            except Exception as e:
                logger.error(f"[{actor.identifier}] Error processing handshake: {e}")
                await msg.nak()

    async def _reply_helper(self, response: Optional[MessageEnvelope], *, msg: Msg):
        logger.debug(
            f"[{msg.subject}] Responding to message: {response.model_dump_json() if response else 'None'}"
        )
        if response is None:
            await msg.nak()
        else:
            await msg.respond(response.model_dump_json().encode())

    async def _message_callback(
        self,
        msg: Msg,
        actor: ActorInfo,
        handler: Coroutine[
            Tuple[MessageEnvelope, Optional[Coroutine[MessageEnvelope, None, None]]],
            None,
            None,
        ],
        jetstream: bool = True,
    ):
        try:
            logger.debug(f"[{actor.identifier}] Received message: {msg.subject}")
            encrypted_message = MessageEnvelope.model_validate_json(msg.data.decode())

            if jetstream:  # stream
                await msg.in_progress()
                await handler(encrypted_message, None)
                await msg.ack()
            else:  # req-reply
                await handler(
                    encrypted_message,
                    partial(self._reply_helper, msg=msg),
                )

        except SessionNotFound as e:
            logger.debug(f"[{actor.identifier}] Session {e.session_id} not found")
            await msg.term()
        except SessionsUpdated:
            await self._message_callback(msg, actor, handler)
            logger.debug(f"[{actor.identifier}] Sessions updated, reconnecting")
            raise
        except Exception as e:
            logger.error(f"[{actor.identifier}] Error processing message: {e}")
            await msg.nak()

    async def messages(
        self,
        actor: ActorInfo,
        sessions: List[Session],
        message_handler: Coroutine[MessageEnvelope, None, None],
    ):
        """Listen for incoming messages across multiple sessions.

        Args:
            actor: Actor information
            sessions: List of active sessions

        Yields:
            Message envelopes

        Flow:
            1. Ensures JetStream exists for actor (creates or updates)
            2. Creates subscriptions for each session
            3. Merges message streams from all sessions
            4. For each incoming message:
               a. Marks message as in progress
               b. Deserializes to MessageEnvelope
               c. Yields message to caller
               d. Acknowledges message after processing
               e. Handles errors with appropriate NATS actions
        """
        try:
            await self._js.add_stream(
                name=self.stream_name(actor),
                subjects=[self.message_key(actor, "*")],
            )
        except Exception:
            logger.debug(
                f"Stream {self.stream_name(actor)} already exists, updating..."
            )
            await self._js.update_stream(
                name=self.stream_name(actor),
                subjects=[self.message_key(actor, "*")],
            )

        msg_subs: List[JetStreamContext.PushSubscription] = []
        msg_subs = await asyncio.gather(
            *[
                self._js.subscribe_bind(
                    stream=self.stream_name(actor),
                    config=ConsumerConfig(**session.transport_metadata["config"]),
                    consumer=self.consumer_name(actor, session.session_id),
                )
                for session in sessions
            ]
        )

        await self._nc.subscribe(
            self.request_key(actor, "*"),
            cb=partial(
                self._message_callback,
                actor=actor,
                handler=message_handler,
                jetstream=False,
            ),
        )

        async for msg in join_iters(*[sub.messages for sub in msg_subs]):
            await self._message_callback(msg, actor, message_handler)
