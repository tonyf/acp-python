from .base import Agent, TextMessage, MessageHistory
from typer import prompt
from rich.console import Console

console = Console()


class UserInterface(Agent):
    def __init__(
        self,
        name: str = "user",
        **kwargs,
    ):
        super().__init__(name, **kwargs)

    async def on_message(self, message: TextMessage):
        console.print(f"[{message.source}] {message.content}")
        response = prompt("> ")
        await self.send(
            message.source, TextMessage(content=response, source=self._name)
        )
