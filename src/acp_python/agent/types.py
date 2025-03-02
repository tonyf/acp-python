from typing import Dict, List, Literal
from abc import ABC
from pydantic import BaseModel, ConfigDict, field_serializer, field_validator
from openai.types.chat import ChatCompletionToolParam
from datetime import datetime
from cryptography.hazmat.primitives.asymmetric import x25519
from nats.js.api import ConsumerInfo


class KeyPair(BaseModel):
    """A cryptographic key pair."""

    private_key: x25519.X25519PrivateKey
    """The private key."""

    public_key: x25519.X25519PublicKey
    """The public key."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @field_serializer("private_key")
    def serialize_private_key(self, private_key: x25519.X25519PrivateKey) -> str:
        """Serialize private key to hex string."""
        return private_key.private_bytes_raw().hex()

    @field_serializer("public_key")
    def serialize_public_key(self, public_key: x25519.X25519PublicKey) -> str:
        """Serialize public key to hex string."""
        return public_key.public_bytes_raw().hex()

    @field_validator("private_key", mode="before")
    @classmethod
    def validate_private_key(cls, value):
        """Deserialize private key from hex string."""
        if isinstance(value, str):
            return x25519.X25519PrivateKey.from_private_bytes(bytes.fromhex(value))
        return value

    @field_validator("public_key", mode="before")
    @classmethod
    def validate_public_key(cls, value):
        """Deserialize public key from hex string."""
        if isinstance(value, str):
            return x25519.X25519PublicKey.from_public_bytes(bytes.fromhex(value))
        return value

    @classmethod
    def generate(cls) -> "KeyPair":
        """Generate a new key pair."""
        private_key = x25519.X25519PrivateKey.generate()
        public_key = private_key.public_key()
        return cls(private_key=private_key, public_key=public_key)

    def get_shared_secret(self, peer_public_key: x25519.X25519PublicKey) -> bytes:
        """Compute the shared secret with a peer's public key."""
        return self.private_key.exchange(peer_public_key)


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


class EncryptedMessage(BaseModel):
    """An encrypted message."""

    session_id: str
    """The session ID of the message."""

    content: str
    """The encrypted content of the message."""

    nonce: str
    """The nonce of the message."""

    type: Literal["EncryptedMessage"] = "EncryptedMessage"


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

    me: AgentInfo
    """The agent that is participating in this conversation."""

    consumer_info: ConsumerInfo
    """The consumer info for this conversation."""

    my_keypair: KeyPair
    """The keypair for this conversation."""

    peer_public_key: x25519.X25519PublicKey
    """The public key of the peer."""

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

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @field_serializer("peer_public_key")
    def serialize_peer_public_key(self, public_key: x25519.X25519PublicKey) -> str:
        """Serialize public key to hex string."""
        return public_key.public_bytes_raw().hex()

    @field_validator("peer_public_key", mode="before")
    @classmethod
    def validate_peer_public_key(cls, value):
        """Deserialize public key from hex string."""
        if isinstance(value, str):
            return x25519.X25519PublicKey.from_public_bytes(bytes.fromhex(value))
        return value

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

    public_key: x25519.X25519PublicKey
    """The public key of the agent."""

    metadata: Dict[str, str] = {}
    """Additional metadata about the conversation."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @field_serializer("public_key")
    def serialize_public_key(self, public_key: x25519.X25519PublicKey) -> str:
        """Serialize public key to hex string."""
        return public_key.public_bytes_raw().hex()

    @field_validator("public_key", mode="before")
    @classmethod
    def validate_public_key(cls, value):
        """Deserialize public key from hex string."""
        if isinstance(value, str):
            return x25519.X25519PublicKey.from_public_bytes(bytes.fromhex(value))
        return value


class HandshakeResponse(BaseModel):
    """A handshake response from an agent."""

    session_id: str
    """The session ID of the conversation."""

    public_key: x25519.X25519PublicKey | None = None
    """The public key of the agent."""

    metadata: Dict[str, str] = {}
    """Additional metadata about the conversation."""

    accept: bool
    """Whether the handshake was accepted."""

    reason: str | None = None
    """The reason the handshake was rejected."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @field_serializer("public_key")
    def serialize_public_key(
        self, public_key: x25519.X25519PublicKey | None
    ) -> str | None:
        """Serialize public key to hex string."""
        if public_key is None:
            return None
        return public_key.public_bytes_raw().hex()

    @field_validator("public_key", mode="before")
    @classmethod
    def validate_public_key(cls, value):
        """Deserialize public key from hex string."""
        if value is None:
            return None
        if isinstance(value, str):
            return x25519.X25519PublicKey.from_public_bytes(bytes.fromhex(value))
        return value
