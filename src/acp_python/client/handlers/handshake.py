import uuid
from typing import TYPE_CHECKING
from nats.aio.msg import Msg
from acp_python.client.types import (
    _Message,
    HandshakeRequest,
    HandshakeAccept,
    HandshakeReject,
    Session,
)
from acp_python.client.crypto import generate_keys, compute_shared_secret

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

    # Collect all middleware responses for policy checks
    allowed_responses = []
    rejection_reasons = []

    for middleware in client._middleware:
        allowed, reason = await middleware.on_session_request(
            client, client.me_as_peer, request.sender
        )
        allowed_responses.append(allowed)
        if not allowed and reason:
            rejection_reasons.append(reason)

    # If any middleware rejected the request, send a rejection response
    if not all(allowed_responses):
        # Combine all rejection reasons or use default
        combined_reason = (
            "; ".join(rejection_reasons) if rejection_reasons else "Unknown reason"
        )
        reject = HandshakeReject(
            sender=client.me_as_peer,
            recipient=request.sender,
            reason=combined_reason,
        )
        await msg.respond(reject.to_bytes())
        return

    # Create a new session
    private_key, public_key = generate_keys()
    session = Session(
        id=str(uuid.uuid4()),
        peer=request.sender,
        shared_secret=compute_shared_secret(private_key, request.public_key),
    )

    # Send an accept message to the requester
    accept = HandshakeAccept(
        sender=client.me_as_peer,
        recipient=request.sender,
        session_id=session.id,
        public_key=public_key,
    )
    await msg.respond(accept.to_bytes())

    # Store the new session
    await client._session_store.set_session(request.sender.id, session)

    # Notify middleware of session creation
    for middleware in client._middleware:
        await middleware.on_session_create(client, request.sender, session)
