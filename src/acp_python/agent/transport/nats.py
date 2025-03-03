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
    ConversationSession,
    EncryptedMessage,
    HandshakeRequest,
    HandshakeResponse,
)
from ..utils.iter import join_iters
from .base import Transport

logger = logging.getLogger(__name__)


class NatsTransport(Transport):
    def __init__(self, server_url: str = "nats://localhost:4222"):
        self._server_url = server_url
        self._nc: NatsClient = None  # type: ignore
        self._js: JetStreamContext = None  # type: ignore

        self._pending_handshakes: Dict[str, Msg] = {}

    def stream_name(self, agent: AgentInfo) -> str:
        return f"acp_agent_messages_{agent.name}"

    def consumer_name(self, agent: AgentInfo, session_id: str) -> str:
        return f"{agent.name}_{session_id}"

    def message_key(self, agent: AgentInfo, session_id: str = "*") -> str:
        return f"acp.agent.{agent.name}.message.{session_id}"

    def handshake_key(self, agent_info: AgentInfo) -> str:
        return f"acp.agent.{agent_info.name}.handshake"

    async def register_session(
        self, agent: AgentInfo, session_id: str
    ) -> Dict[str, Any]:
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
        if self._nc is not None:
            logger.info(f"Already connected to NATS: {self._server_url}")
            return

        self._nc = await nats.connect(self._server_url)
        self._js = self._nc.jetstream(timeout=None)

    async def send(self, to: AgentInfo, message: EncryptedMessage):
        await self._js.publish(
            self.message_key(to, message.session_id),
            message.model_dump_json().encode(),
        )

    async def handshake_request(
        self, to: AgentInfo, request: HandshakeRequest
    ) -> HandshakeResponse:
        resp = await self._nc.request(
            self.handshake_key(to),
            request.model_dump_json().encode(),
            timeout=10,
        )
        return HandshakeResponse.model_validate_json(resp.data.decode())

    async def handshake_reply(self, to: AgentInfo, response: HandshakeResponse):
        msg = self._pending_handshakes.pop(to.name)
        if msg is None:
            raise Exception(f"No pending handshake for {to.name}")

        await msg.respond(response.model_dump_json().encode())

    async def handshakes(
        self, agent: AgentInfo
    ) -> AsyncGenerator[HandshakeRequest, None]:
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
        self, agent: AgentInfo, sessions: List[ConversationSession]
    ) -> AsyncGenerator[EncryptedMessage, None]:
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
