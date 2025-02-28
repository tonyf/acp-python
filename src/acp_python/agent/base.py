from typing import Dict, List, Literal
import nats
from nats.aio.client import Msg
from abc import abstractmethod, ABC
from pydantic import BaseModel, ConfigDict
import uuid
import asyncio
from openai.types.chat import ChatCompletionToolParam
from datetime import datetime


class AgentInfo(BaseModel):
    """Information about an agent."""

    name: str
    """The name of the agent."""

    description: str
    """The description of the agent."""

    def to_tool(self) -> ChatCompletionToolParam:
        return {
            "type": "function",
            "function": {
                "name": self.name.lower(),
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "msg": {
                            "type": "string",
                            "description": "The message to send to the agent",
                        }
                    },
                    "required": ["msg"],
                },
            },
        }


class BaseMessage(BaseModel, ABC):
    """Base class for all message types."""

    source: AgentInfo
    """The agent that sent this message."""

    metadata: Dict[str, str] = {}
    """Additional metadata about the message."""

    model_config = ConfigDict(arbitrary_types_allowed=True)


class TextMessage(BaseMessage):
    """A text message."""

    content: str
    """The content of the message."""

    session_id: str
    """The session ID of the message."""

    type: Literal["TextMessage"] = "TextMessage"


class MessageHistory(BaseModel):
    """A history of messages."""

    peer: AgentInfo
    """The source of the messages."""

    messages: List[TextMessage]
    """The messages in the history."""


class ConversationSession(BaseModel):
    """A session representing a conversation between agents and users."""

    session_id: str
    """Unique identifier for this conversation session."""

    original_user: AgentInfo
    """The user who initiated this conversation."""

    participants: List[AgentInfo] = []
    """All agents/users participating in this conversation."""

    messages: List[TextMessage] = []
    """All messages in the conversation."""

    metadata: Dict[str, str] = {}
    """Additional session metadata and context."""

    created_at: str = ""
    """When this session was created."""

    updated_at: str = ""
    """When this session was last updated."""

    def append(self, *messages: TextMessage):
        self.messages.extend(messages)
        self.updated_at = datetime.now().isoformat()

        for message in messages:
            if message.source not in self.participants:
                self.participants.append(message.source)


class HandshakeRequest(BaseModel):
    """A handshake request from an agent."""

    from_agent: AgentInfo
    """The agent that is sending the handshake request."""

    session_id: str
    """The session ID of the conversation."""

    metadata: Dict[str, str] = {}
    """Additional metadata about the conversation."""


class HandshakeResponse(BaseModel):
    """A handshake response from an agent."""

    session_id: str
    """The session ID of the conversation."""

    metadata: Dict[str, str] = {}
    """Additional metadata about the conversation."""

    accept: bool
    """Whether the handshake was accepted."""


class Agent(ABC):
    def __init__(
        self,
        name: str,
        description: str,
        peers: List[AgentInfo] = [],
        server_url: str = "nats://localhost:4222",
    ):
        self._name = name
        self._description = description
        self._server_url = server_url
        self._peers = peers

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

    def message_key(self, session_id: str, agent_info: AgentInfo) -> str:
        return f"acp.agent.{agent_info.name}.message.{session_id}"

    def handshake_key(self, agent_info: AgentInfo) -> str:
        return f"acp.agent.{agent_info.name}.handshake"

    async def _connect(self):
        # Setup clients
        self._nc = await nats.connect(self._server_url)
        self._js = self._nc.jetstream()

        # Setup resources
        self._kv = await self._js.create_key_value(bucket="acp")
        try:
            await self._js.add_stream(
                name=f"acp_agent_messages_{self._name}",
                subjects=[self.message_key("*", self.info)],
            )
        except Exception:
            pass

        self._msg_sub = await self._js.subscribe(
            self.message_key("*", self.info),
            # durable=self._name,
        )
        self._handshake_sub = await self._nc.subscribe(
            self.handshake_key(self.info),
            # durable=self._name,
        )

    async def _message_handler(self, msg: Msg):
        message = TextMessage.model_validate_json(msg.data)
        await self.on_message(message)

    async def _handshake_handler(self, msg: Msg):
        handshake_request = HandshakeRequest.model_validate_json(msg.data)
        await msg.respond(
            HandshakeResponse(
                session_id=handshake_request.session_id,
                metadata=handshake_request.metadata,
                accept=True,
            )
            .model_dump_json()
            .encode(),
        )

    ##
    ## Message API
    ##

    @abstractmethod
    async def on_message(self, message: TextMessage):
        pass

    async def register_peer(self, *peers: AgentInfo):
        self._peers.extend(peers)

    async def send(self, to: AgentInfo, message: TextMessage):
        await self._js.publish(
            self.message_key(message.session_id, to),
            message.model_dump_json().encode(),
        )

    async def run(self):
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

    ##
    ## Session API
    ##
    def _session_store_key(self, session_id: str) -> str:
        return f"session_{self._name}_{session_id}"

    async def _get_session(self, session_id: str) -> ConversationSession | None:
        try:
            session_data = await self._kv.get(self._session_store_key(session_id))
            if session_data is None:
                return None
            return ConversationSession.model_validate_json(session_data.value)
        except Exception:
            return None

    async def _create_session(
        self, peer: AgentInfo, session_id: str
    ) -> ConversationSession:
        from datetime import datetime

        timestamp = datetime.now().isoformat()

        session = ConversationSession(
            session_id=session_id,
            original_user=peer,
            participants=[peer, self.info],
            created_at=timestamp,
            updated_at=timestamp,
        )

        await self._kv.put(
            self._session_store_key(session_id),
            session.model_dump_json().encode(),
        )
        # await self._js.add_stream(
        #     name=f"acp_session_{session_id}",
        #     subjects=[f"acp.agent.{self._name}.session.{session_id}"],
        # )

        return session

    async def get_or_create_session(
        self, peer: AgentInfo, session_id: str
    ) -> ConversationSession:
        session = await self._get_session(session_id)
        if session is None:
            return await self._create_session(peer, session_id)
        return session

    async def update_session(self, session: ConversationSession):
        await self._kv.put(
            self._session_store_key(session.session_id),
            session.model_dump_json().encode(),
        )

    async def establish_session(
        self, peer: AgentInfo, session_id: str | None = None, metadata: dict = {}
    ) -> str:
        """
        Establish a new session with another agent or user.
        Returns the session_id that can be used for future communications.
        """
        session_id = session_id or str(uuid.uuid4())
        if (session := await self._get_session(session_id)) is not None:
            raise Exception(f"Session {session_id} already exists")

        handshake_request = HandshakeRequest(
            from_agent=self.info,
            session_id=session_id,
            metadata=metadata or {},
        )
        resp = await self._nc.request(
            self.handshake_key(peer),
            handshake_request.model_dump_json().encode(),
        )
        handshake_response = HandshakeResponse.model_validate_json(resp.data)
        if not handshake_response.accept:
            raise Exception("Handshake rejected")

        # Create a new session or get existing one
        session = await self.get_or_create_session(peer, session_id)
        for key, value in metadata.items():
            session.metadata[key] = value

        # Save the updated session
        await self._kv.put(
            self._session_store_key(session_id),
            session.model_dump_json().encode(),
        )

        return session_id
