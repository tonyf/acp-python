from acp_python.agent.base import AgentInfo
from .base import Agent, TextMessage, MessageHistory
from typer import prompt
from rich.console import Console

console = Console()


class UserInterface(Agent):
    def __init__(
        self,
        name: str = "user",
        session_id: str = "",
        **kwargs,
    ):
        super().__init__(name, **kwargs)
        self.session_id = session_id

    def message_key(self, _: str, agent_info: AgentInfo) -> str:
        return super().message_key(self.session_id, agent_info)

    async def on_message(self, message: TextMessage):
        console.print(f"[{message.source}] {message.content}")
        response = prompt("> ")

        if response.lower() == "exit":
            # Signal to exit
            raise KeyboardInterrupt()

        # Keep the same session_id in the response
        await self.send(
            message.source,
            TextMessage(
                content=response,
                source=self.info,
                session_id=message.session_id,  # Preserve session ID
            ),
        )
