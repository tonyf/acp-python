import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..types import EncryptedMessage, TextMessage


def encrypt(msg: TextMessage, shared_secret: bytes) -> "EncryptedMessage":
    nonce = os.urandom(24)
    cipher = AESGCM(shared_secret[:32])
    content = cipher.encrypt(nonce, msg.model_dump_json().encode(), None)
    return EncryptedMessage(
        session_id=msg.session_id,
        content=content.hex(),
        nonce=nonce.hex(),
    )


def decrypt(msg: EncryptedMessage, shared_secret: bytes) -> TextMessage:
    cipher = AESGCM(shared_secret[:32])
    content = cipher.decrypt(bytes.fromhex(msg.nonce), bytes.fromhex(msg.content), None)
    return TextMessage.model_validate_json(content.decode())
