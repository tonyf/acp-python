from pydantic import BaseModel
from typing import Dict, Any, TypeVar, Type, Optional, ClassVar
from enum import Enum
import json
from .actor import Actor
from abc import ABC


class MessageType(Enum):
    HANDSHAKE_REQUEST = "handshake_request"
    HANDSHAKE_ACCEPT = "handshake_accept"
    HANDSHAKE_REJECT = "handshake_reject"
    SESSION_MESSAGE = "session_message"


class Message(BaseModel, ABC):
    """Base message class that all message types inherit from."""

    message_type: MessageType

    # Class registry for polymorphic deserialization
    _message_types: ClassVar[Dict[MessageType, Type["Message"]]] = {}

    def __init_subclass__(cls, **kwargs):
        """Register subclasses in the message type registry."""
        super().__init_subclass__(**kwargs)
        if hasattr(cls, "message_type") and not isinstance(cls.message_type, property):
            Message._message_types[cls.message_type] = cls

    @classmethod
    def from_bytes(cls, data: bytes) -> "Message":
        """Deserialize message from bytes into the appropriate message type."""
        msg_dict = json.loads(data)
        msg_type = MessageType(msg_dict["message_type"])

        # Get the right message class from the registry
        message_class = cls._message_types.get(msg_type)
        if not message_class:
            raise ValueError(f"Unknown message type: {msg_type}")

        # Handle binary fields that need hex decoding
        if msg_type == MessageType.HANDSHAKE_REQUEST:
            msg_dict["public_key"] = bytes.fromhex(msg_dict["public_key"])
            msg_dict["certificate"] = bytes.fromhex(msg_dict["certificate"])
        elif msg_type == MessageType.HANDSHAKE_ACCEPT:
            msg_dict["public_key"] = bytes.fromhex(msg_dict["public_key"])

        return message_class(**msg_dict)

    def to_bytes(self) -> bytes:
        """Serialize message to bytes."""
        data = self.model_dump()

        # Convert enum to string
        if "message_type" in data:
            data["message_type"] = data["message_type"].value

        # Handle binary fields that need hex encoding
        for field in ["public_key", "certificate", "content"]:
            if field in data and isinstance(data[field], bytes):
                data[field] = data[field].hex()

        return json.dumps(data).encode("utf-8")


class HandshakeRequest(Message):
    sender: Actor
    recipient: Actor
    message_type: MessageType = MessageType.HANDSHAKE_REQUEST
    public_key: bytes
    certificate: bytes


class HandshakeAccept(Message):
    sender: Actor
    recipient: Actor
    message_type: MessageType = MessageType.HANDSHAKE_ACCEPT
    session_id: str
    public_key: bytes


class HandshakeReject(Message):
    sender: Actor
    recipient: Actor
    message_type: MessageType = MessageType.HANDSHAKE_REJECT
    reason: str


class SessionMessage(Message):
    message_type: MessageType = MessageType.SESSION_MESSAGE
    session_id: str
    sender: Actor
    recipient: Actor
    content: bytes


T = TypeVar("T", bound=BaseModel)
