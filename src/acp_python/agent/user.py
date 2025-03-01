from .types import TextMessage, AgentInfo, ConversationSession
from .base import Agent
from typer import prompt
from rich.console import Console
import uuid
import logging

logger = logging.getLogger(__name__)

console = Console()


class UserInterface(Agent):
    def __init__(
        self,
        name: str = "user",
        **kwargs,
    ):
        super().__init__(name, **kwargs)
        self.session_id = str(uuid.uuid4())

    def message_key(self, agent_info: AgentInfo, _: str = "*") -> str:
        return super().message_key(agent_info, self.session_id)

    async def on_message(self, session: ConversationSession):
        last_message = session.messages[-1]
        console.print(f"[{last_message.source}] {last_message.content}")
        response = prompt("> ")

        if response.lower() == "exit":
            # Signal to exit
            raise KeyboardInterrupt()

        if response.lower() == "pdb":
            import pdb

            pdb.set_trace()
            response = prompt("> ")

        # Keep the same session_id in the response
        await self.send(
            last_message.source,
            TextMessage(
                content=response,
                source=self.info,
                session_id=session.session_id,  # Preserve session ID
            ),
        )
