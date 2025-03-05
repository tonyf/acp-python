from cryptography.hazmat.primitives.asymmetric import x25519
from pydantic import BaseModel, ConfigDict, field_serializer, field_validator


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
