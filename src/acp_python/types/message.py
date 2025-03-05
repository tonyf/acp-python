from typing import Any, Dict, Literal

from pydantic import BaseModel

from .actor import ActorInfo


class Message(BaseModel):
    source: ActorInfo
    """The actor that sent this message."""

    content: str
    """The content of the message."""

    session_id: str
    """The session ID of the message."""

    metadata: Dict[str, Any] = {}
    """Additional metadata"""


class Task(BaseModel):
    """A task to be executed by an actor."""

    source: ActorInfo
    """The actor executing this task."""

    session_id: str
    """The session ID to which this task belongs."""

    payload: Dict[str, Any]
    """The payload of the task."""


class MessageEnvelope(BaseModel):
    """An encrypted message envelope."""

    session_id: str
    """The session ID of the message."""

    content: str
    """The encrypted content of the message."""

    nonce: str
    """The nonce of the message."""

    type: Literal["message", "task"]
    """The type of message."""
