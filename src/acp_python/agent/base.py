from typing import Dict, List, Literal
import nats
from nats.aio.client import Msg
from abc import abstractmethod, ABC
from pydantic import BaseModel, ConfigDict

from openai.types.chat import ChatCompletionToolParam


class BaseMessage(BaseModel, ABC):
    """Base class for all message types."""

    source: str
    """The name of the agent that sent this message."""

    metadata: Dict[str, str] = {}
    """Additional metadata about the message."""

    model_config = ConfigDict(arbitrary_types_allowed=True)


class TextMessage(BaseMessage):
    """A text message."""

    content: str
    """The content of the message."""

    type: Literal["TextMessage"] = "TextMessage"


class MessageHistory(BaseModel):
    """A history of messages."""

    peer: str
    """The source of the messages."""

    messages: List[TextMessage]
    """The messages in the history."""


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

    async def _connect(self):
        # Setup clients
        self._nc = await nats.connect(self._server_url)
        self._js = self._nc.jetstream()
        self._kv = await self._js.create_key_value(bucket="acp_agent_history")

        # Setup streams
        await self._js.add_stream(
            name=f"acp_agent_{self._name}",
            subjects=[f"acp.agent.{self._name}.message.*"],
        )

    ##
    ## History API
    ##
    async def get_history(self, source: str) -> MessageHistory:
        try:
            history = await self._kv.get(f"{source}.{self._name}")
            if history is None:
                return MessageHistory(peer=source, messages=[])
            return MessageHistory.model_validate_json(history.value)
        except Exception:
            return MessageHistory(peer=source, messages=[])

    async def put_history(self, source: str, history: MessageHistory):
        await self._kv.put(
            f"{source}.{self._name}",
            history.model_dump_json().encode(),
        )

    async def _handler(self, msg: Msg):
        message = TextMessage.model_validate_json(msg.data)
        await self.on_message(message)

    ##
    ## Message API
    ##

    @abstractmethod
    async def on_message(self, message: TextMessage):
        pass

    async def register_peer(self, *peers: AgentInfo):
        self._peers.extend(peers)

    async def send(self, to: str, message: TextMessage):
        await self._js.publish(
            f"acp.agent.{to}.message.{self._name}", message.model_dump_json().encode()
        )

    async def run(self):
        sub = await self._js.subscribe(
            f"acp.agent.{self._name}.message.*",
            durable=self._name,
        )

        # Run infinitely by waiting forever
        async for msg in sub.messages:
            await self._handler(msg)
