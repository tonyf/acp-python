from typing import Any, Dict, Generic, Literal, TypeVar, Callable

from pydantic import BaseModel

from .actor import ActorInfo

T = TypeVar("T", bound=BaseModel)


class Message(BaseModel, Generic[T]):
    source: ActorInfo
    """The actor that sent this message."""

    content: T
    """The content of the message."""

    session_id: str
    """The session ID of the message."""

    metadata: Dict[str, Any] = {}
    """Additional metadata"""


class MessageTypeRegistry:
    """Registry for message types that can be serialized and deserialized."""

    def __init__(self):
        self._types: Dict[str, type[Message]] = {}

    def register(self, type_id: str, message_class: type[Message]) -> None:
        """Register a message type with the given type ID.

        Args:
            type_id: The unique identifier for this message type
            message_class: The Message class to register
        """
        self._types[type_id] = message_class

    def get(self, type_id: str) -> type[Message]:
        """Get a message type class by its type ID.

        Args:
            type_id: The type identifier to look up

        Returns:
            The corresponding Message class

        Raises:
            KeyError: If the type_id is not registered
        """
        return self._types[type_id]

    def __contains__(self, type_id: str) -> bool:
        return type_id in self._types

    def message_type(self, type_id: str) -> Callable[[type[Message]], type[Message]]:
        """Decorator to register a message type.

        Args:
            type_id: The type identifier for this message type

        Returns:
            A decorator function that registers the message class
        """

        def decorator(cls: type[Message]) -> type[Message]:
            cls.content_type = type_id  # type: ignore
            self.register(type_id, cls)
            return cls

        return decorator

    def get_content_type(self, message: Message) -> str:
        """Lookup the content type of a message from the registry."""
        for type_id, message_class in self._types.items():
            if isinstance(message, message_class):
                return type_id
        raise ValueError(f"Message type {type(message)} not registered")


# Global registry instance
registry = MessageTypeRegistry()


@registry.message_type("text")
class TextMessage(Message[str]):
    """A text message."""


Status = Literal["pending", "success", "failure"]


@registry.message_type("task_status")
class TaskStatus(Message[Status]):
    """The status of a task."""


class MessageEnvelope(BaseModel):
    """An encrypted message envelope."""

    session_id: str
    """The session ID of the message."""

    content: str
    """The encrypted content of the message."""

    nonce: str
    """The nonce of the message."""

    content_type: str
    """The type identifier for this message."""
