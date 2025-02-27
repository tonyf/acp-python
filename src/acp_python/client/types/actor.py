from typing import Dict, List, Optional
from pydantic import BaseModel
from cryptography.hazmat.primitives.asymmetric import x25519

SigningKey = x25519.X25519PrivateKey


class Actor(BaseModel):
    id: str
    namespace: str
    description: dict

    @classmethod
    def new(cls, id: str, namespace: str, description: dict) -> "Actor":
        return cls(id=id, namespace=namespace, description=description)

    def to_dns(self) -> str:
        return f"acp.{self.namespace}.{self.id}"

    @classmethod
    def from_dns(cls, dns: str, description: dict) -> "Actor":
        parts = dns.split(".")
        if len(parts) != 3 or parts[0] != "acp":
            raise ValueError("Invalid dns format")

        return cls(id=parts[2], namespace=parts[1], description=description)

    def make_reply(self, reply: Optional[str]) -> Optional["Actor"]:
        if reply is None:
            return None

        parts = reply.split(".")
        if len(parts) == 3 and parts[0] == "acp":
            return Actor(id=parts[2], namespace=parts[1], description=self.description)
        return None


class MyActor:
    def __init__(
        self,
        id: str,
        namespace_keys: Dict[str, SigningKey],
        description: Dict[str, dict],
        ca_signature: bytes,
    ):
        self.id = id
        self.namespace_keys = namespace_keys
        self.description = description
        self.ca_signature = ca_signature

    @classmethod
    def new(
        cls,
        id: str,
        namespace_keys: Dict[str, SigningKey],
        description: Dict[str, dict],
        ca_signature: bytes,
    ) -> "MyActor":
        return cls(
            id=id,
            namespace_keys=namespace_keys,
            description=description,
            ca_signature=ca_signature,
        )

    def to_subjects(self) -> List[str]:
        return [
            f"acp.{namespace}.{self.id}.*" for namespace in self.namespace_keys.keys()
        ]

    def sign(self, namespace: str, payload: bytes) -> bytes:
        if namespace not in self.namespace_keys:
            raise ValueError(f"Namespace '{namespace}' not found")

        key = self.namespace_keys[namespace]
        return key.sign(payload)

    def to_peer(self, namespace: str) -> Actor:
        if namespace not in self.description:
            raise ValueError("Namespace description not found")

        return Actor(
            id=self.id, namespace=namespace, description=self.description[namespace]
        )
