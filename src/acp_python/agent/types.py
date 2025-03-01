from typing import Dict, List, Literal
from abc import ABC
from pydantic import BaseModel, ConfigDict
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

    def append(self, *messages: TextMessage) -> "ConversationSession":
        copy = self.model_copy()
        copy.messages.extend(messages)
        copy.updated_at = datetime.now().isoformat()

        for message in messages:
            if message.source not in self.participants:
                self.participants.append(message.source)

        return copy


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
