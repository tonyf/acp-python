import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..types import EncryptedMessage, TextMessage


def encrypt(msg: TextMessage, shared_secret: bytes) -> "EncryptedMessage":
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
    return EncryptedMessage(
        session_id=msg.session_id,
        content=content.hex(),
        nonce=nonce.hex(),
    )


def decrypt(msg: EncryptedMessage, shared_secret: bytes) -> TextMessage:
    """Decrypt an encrypted message using AES-GCM with the shared secret.

    Args:
        msg: The encrypted message to decrypt
        shared_secret: The shared secret key used for decryption

    Returns:
        The decrypted TextMessage
    """
    cipher = AESGCM(shared_secret[:32])
    content = cipher.decrypt(bytes.fromhex(msg.nonce), bytes.fromhex(msg.content), None)
    return TextMessage.model_validate_json(content.decode())
