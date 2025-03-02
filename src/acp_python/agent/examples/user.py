from ..types import TextMessage, AgentInfo, ConversationSession
from ..base import Agent
from typer import prompt
from rich.console import Console
import uuid
import logging
import asyncio
from typing import List

logger = logging.getLogger(__name__)

console = Console()


class UserInterface(Agent):
    def __init__(
        self,
        name: str = "user",
        session_id: str | None = None,
        **kwargs,
    ):
        super().__init__(name, **kwargs)
        self.session_id = session_id or str(uuid.uuid4())

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

    async def run(self, peers: List[AgentInfo] = []):
        assert len(peers) == 1, "User interface must have exactly one peer"
        peer = peers[0]

        loop = asyncio.create_task(super().run(peers))

        while self._nc is None:
            await asyncio.sleep(1)

        session_id = await self.establish_session(peer, self.session_id)
        assert session_id == self.session_id, "Session ID mismatch"
        console.print(f"Starting new conversation (Session ID: {session_id})")
        console.print("Type 'exit' to quit")
        user_input = console.input("> ")

        if user_input.lower() == "exit":
            raise KeyboardInterrupt()

        await self.send(
            peer,
            TextMessage(
                content=user_input,
                source=self.info,
                session_id=self.session_id,
            ),
        )

        await loop


if __name__ == "__main__":
    from typer import Typer
    from .chat import ChatAgent

    app = Typer()

    @app.command()
    def chat(
        model: str = "mistral-small",
        api_key: str = "ollama",
        base_url: str = "http://localhost:11434/v1",
        nats_url: str = "nats://local:3GNtWSMhUvdxjp1OLJfmpa67qZyICWSf@0.0.0.0:4222",
        session_id: str | None = None,
    ):
        async def main():
            # Create agents
            chat = ChatAgent(
                name="assistant-2",
                model=model,
                description="A helpful assistant that can answer questions and help with tasks.",
                openai_kwargs={"api_key": api_key, "base_url": base_url},
                server_url=nats_url,
            )
            pirate = ChatAgent(
                name="pirate-riddler-2",
                model=model,
                description="A pirate that creates riddles",
                openai_kwargs={"api_key": api_key, "base_url": base_url},
                server_url=nats_url,
            )
            user = UserInterface(
                name="tony-2",
                session_id=session_id,
                description="A user interface for the chat agent.",
                peers=[chat.info],
                server_url=nats_url,
            )

            # Run all agents concurrently in the background
            await asyncio.gather(
                user.run([chat.info]),
                chat.run([pirate.info]),
                pirate.run([chat.info]),
            )

        asyncio.run(main())

        app()
