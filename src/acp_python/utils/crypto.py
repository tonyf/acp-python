import os
from typing import Union

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from acp_python.types.message import Message, MessageEnvelope, Task


def encrypt(msg: Union[Message, Task], shared_secret: bytes) -> MessageEnvelope:
    """Encrypt a text message using AES-GCM with the shared secret.

    Args:
        msg: The text message to encrypt
        shared_secret: The shared secret key used for encryption

    Returns:
        An EncryptedMessage containing the encrypted content and nonce
    """
    nonce = os.urandom(24)
    cipher = AESGCM(shared_secret[:32])
    content = cipher.encrypt(nonce, msg.model_dump_json().encode(), None)
    return MessageEnvelope(
        session_id=msg.session_id,
        content=content.hex(),
        nonce=nonce.hex(),
    )


def decrypt(msg: MessageEnvelope, shared_secret: bytes) -> Union[Message, Task]:
    """Decrypt an encrypted message using AES-GCM with the shared secret.

    Args:
        msg: The encrypted message to decrypt
        shared_secret: The shared secret key used for decryption

    Returns:
        The decrypted Message
    """
    cipher = AESGCM(shared_secret[:32])
    content = cipher.decrypt(bytes.fromhex(msg.nonce), bytes.fromhex(msg.content), None)

    if msg.type == "message":
        return Message.model_validate_json(content.decode())
    elif msg.type == "task":
        return Task.model_validate_json(content.decode())
    else:
        raise ValueError(f"Unknown message type: {msg.type}")
