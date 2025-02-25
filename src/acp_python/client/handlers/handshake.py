import uuid
from typing import TYPE_CHECKING
from nats.aio.msg import Msg
from acp_python.core.types import (
    _Message,
    HandshakeRequest,
    HandshakeAccept,
    HandshakeReject,
    Session,
)
from acp_python.core.crypto import generate_keys, compute_shared_secret

if TYPE_CHECKING:
    from ..client import AcpClient


async def on_handshake_msg(msg: Msg, *, client: "AcpClient") -> None:
    """
    Handles incoming handshake messages for establishing secure sessions between actors.

    This function processes handshake requests by:
    1. Validating the request through middleware policies
    2. Creating a new session with cryptographic keys if allowed
    3. Responding with either an accept or reject message
    4. Storing the new session if accepted

    Args:
        msg: The raw NATS message containing the handshake request
        client: The ACP client instance handling the handshake

    Returns:
        None

    Side Effects:
        - Creates and stores a new session if request is accepted
        - Sends response message (accept/reject) to requester
        - Notifies middleware of session creation
    """
    request = _Message.from_bytes(msg.data)
    if not isinstance(request, HandshakeRequest):
        return

    # check policy
    for middleware in client._middleware:
        allowed, reason = await middleware.on_session_request(
            client, client.me_as_peer, request.from_
        )
        if not allowed:
            reject = HandshakeReject(
                from_=client.me_as_peer,
                to_=request.from_,
                reason=reason or "Unknown reason",
            )
        await msg.respond(reject.to_bytes())
        return

    # create session
    private_key, public_key = generate_keys()
    session = Session(
        id=str(uuid.uuid4()),
        peer=request.from_,
        shared_secret=compute_shared_secret(private_key, request.public_key),
    )

    # send accept
    accept = HandshakeAccept(
        from_=client.me_as_peer,
        to_=request.from_,
        session_id=session.id,
        public_key=public_key,
    )
    await msg.respond(accept.to_bytes())

    # store session
    await client._session_store.set_session(request.from_.id, session)
    for middleware in client._middleware:
        await middleware.on_session_create(client, request.from_, session)
