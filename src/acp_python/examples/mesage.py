from pydantic import BaseModel
from acp_python.client.types import Actor
from acp_python.client import AcpClient


class AgentMessage(BaseModel):
    id: str
    created: int
    sender: Actor

class AcpAgent(AcpClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    async def send_message(self, message: AgentMessage):
        await self.send_message(message.sender, message.content)
