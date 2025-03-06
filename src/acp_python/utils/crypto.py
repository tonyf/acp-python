import os
import json

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from acp_python.types.message import registry, Message, MessageEnvelope


def encrypt(msg: Message, shared_secret: bytes) -> MessageEnvelope:
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
        content_type=registry.get_content_type(msg),
    )


def decrypt(msg: MessageEnvelope, shared_secret: bytes) -> Message:
    """Decrypt an encrypted message using AES-GCM with the shared secret.

    Args:
        msg: The encrypted message to decrypt
        shared_secret: The shared secret key used for decryption

    Returns:
        The decrypted Message, properly typed based on content_type

    Raises:
        ValueError: If the message type is not registered
    """
    cipher = AESGCM(shared_secret[:32])
    content = cipher.decrypt(
        bytes.fromhex(msg.nonce), bytes.fromhex(msg.content), None
    ).decode()

    try:
        message_class = registry.get(msg.content_type)
        return message_class.model_validate_json(content)
    except KeyError as e:
        raise ValueError(f"Unknown message type: {msg.content_type}") from e
