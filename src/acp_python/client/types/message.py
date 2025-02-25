from pydantic import BaseModel
from typing import Dict, Any, TypeVar, Type
from enum import Enum
import json
from .actor import Actor
from abc import ABC


class MessageType(Enum):
    HANDSHAKE_REQUEST = "handshake_request"
    HANDSHAKE_ACCEPT = "handshake_accept"
    HANDSHAKE_REJECT = "handshake_reject"
    SESSION_MESSAGE = "session_message"


class _Message(BaseModel, ABC):
    message_type: MessageType

    @classmethod
    def from_bytes(cls, data: bytes) -> "_Message":
        msg_dict = json.loads(data)
        msg_type = MessageType(msg_dict["message_type"])

        message_classes: Dict[MessageType, Type[Any]] = {
            MessageType.HANDSHAKE_REQUEST: HandshakeRequest,
            MessageType.HANDSHAKE_ACCEPT: HandshakeAccept,
            MessageType.HANDSHAKE_REJECT: HandshakeReject,
            MessageType.SESSION_MESSAGE: SessionMessage,
        }

        return message_classes[msg_type](**msg_dict)

    def to_bytes(self) -> bytes:
        return self.model_dump_json().encode("utf-8")


class HandshakeRequest(_Message):
    sender: Actor
    recipient: Actor
    message_type: MessageType = MessageType.HANDSHAKE_REQUEST
    public_key: bytes
    certificate: bytes


class HandshakeAccept(_Message):
    sender: Actor
    recipient: Actor
    message_type: MessageType = MessageType.HANDSHAKE_ACCEPT
    session_id: str
    public_key: bytes


class HandshakeReject(_Message):
    sender: Actor
    recipient: Actor
    message_type: MessageType = MessageType.HANDSHAKE_REJECT
    reason: str


class SessionMessage(_Message):
    message_type: MessageType = MessageType.SESSION_MESSAGE
    session_id: str
    content: bytes


T = TypeVar("T", bound=BaseModel)


class Message(BaseModel):
    session_id: str
    sender: Actor
    content: bytes
