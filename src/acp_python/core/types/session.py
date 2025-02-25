from pydantic import BaseModel
from .actor import Actor


class Session(BaseModel):
    id: str
    peer: Actor
    shared_secret: bytes

    def decrypt(self, content: bytes) -> bytes:
        return content

    def encrypt(self, content: bytes) -> bytes:
        return content
