from typing import Optional, TYPE_CHECKING
from acp_python.core.types import (
    _Message,
    SessionMessage,
    Message,
)
from acp_python.core.exception import SessionNotFound
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
    request = _Message.from_bytes(msg.data)
    if not isinstance(request, SessionMessage):
        return None

    session = await client._session_store.get_session(
        client.me_as_peer.id, request.session_id
    )
    if session is None:
        raise SessionNotFound(f"Session {request.session_id} not found")

    content = session.decrypt(request.content)
    return Message(
        from_=request.from_,
        to_=request.to_,
        content=client._message_decoder(content),
    )
