from cryptography.hazmat.primitives.asymmetric import x25519
from pydantic import BaseModel, ConfigDict, field_serializer, field_validator


from datetime import datetime
from typing import Any, Dict, List

from .actor import ActorInfo
from .message import Message
from .keypair import KeyPair


class Session(BaseModel):
    """A session representing a conversation between agents and users."""

    session_id: str
    """Unique identifier for this conversation session."""

    me: ActorInfo
    """The actor that is participating in this conversation."""

    transport_metadata: Dict[str, Any]
    """The consumer info for this conversation."""

    my_keypair: KeyPair
    """The keypair for this conversation."""

    peer_public_key: x25519.X25519PublicKey
    """The public key of the peer."""

    original_user: ActorInfo
    """The user who initiated this conversation."""

    participants: List[ActorInfo] = []
    """All actors participating in this conversation."""

    history: List[Message] = []
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

    def append(self, *messages: Message) -> "Session":
        copy = self.model_copy()
        copy.history.extend(messages)
        copy.updated_at = datetime.now().isoformat()

        for message in messages:
            if message.source not in self.participants:
                self.participants.append(message.source)

        return copy
