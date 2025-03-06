from cryptography.hazmat.primitives.asymmetric import x25519
from pydantic import BaseModel, ConfigDict, field_serializer, field_validator


from typing import Dict
from .actor import ActorInfo


class HandshakeRequest(BaseModel):
    """A handshake request from an agent."""

    from_actor: ActorInfo
    """The actor that is sending the handshake request."""

    session_id: str
    """The session ID of the conversation."""

    public_key: x25519.X25519PublicKey
    """The public key of the actor."""

    metadata: Dict[str, str] = {}
    """Additional metadata about the conversation such as auth tokens."""

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
