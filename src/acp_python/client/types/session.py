from pydantic import BaseModel
from .actor import Actor
from acp_python.client.crypto import encrypt_message, decrypt_message


class Session(BaseModel):
    id: str
    peer: Actor
    shared_secret: bytes

    def decrypt(self, content: bytes) -> bytes:
        return decrypt_message(self.shared_secret, content)

    def encrypt(self, content: bytes) -> bytes:
        return encrypt_message(self.shared_secret, content)
