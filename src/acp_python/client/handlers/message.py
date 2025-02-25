from typing import Optional, TYPE_CHECKING
from acp_python.core.types import (
    _Message,
    SessionMessage,
    Message,
)
from acp_python.client.exception import SessionNotFound
from nats.aio.msg import Msg

if TYPE_CHECKING:
    from ..client import AcpClient


async def on_session_message(
    msg: Msg,
    *,
    client: "AcpClient",
) -> Optional[Message]:
    """
    Handles an incoming session message from NATS.

    Args:
        msg: The raw NATS message
        client: The ACP client instance

    Returns:
        The decrypted and decoded Message if it's a valid session message,
        None otherwise

    Raises:
        SessionNotFound: If the session ID in the message doesn't exist
    """
    message = _Message.from_bytes(msg.data)
    if not isinstance(message, SessionMessage):
        raise ValueError("Message is not a session message")

    session = await client._session_store.get_session(
        client.me_as_peer.id, message.session_id
    )
    if session is None:
        raise SessionNotFound(f"Session {message.session_id} not found")

    return Message(
        session_id=message.session_id,
        sender=session.peer,
        content=session.decrypt(message.content),
    )
