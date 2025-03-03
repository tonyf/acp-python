import asyncio
import logging
import uuid
from typing import List, Dict, Any

from rich.console import Console
from typer import prompt

from ..base import Agent
from ..types import AgentInfo, Session, TextMessage

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

    async def on_message(self, session: Session):
        last_message = session.messages[-1]
        console.print(f"[{last_message.source}] {last_message.content}")
        response = prompt("> ")

        if response.lower() == "exit":
            raise KeyboardInterrupt()

        if response.lower() == "pdb":
            import pdb

            pdb.set_trace()
            response = prompt("> ")

        await self.send(
            last_message.source,
            TextMessage(
                content=response,
                source=self.info,
                session_id=session.session_id,
            ),
        )

    async def run(self):
        assert len(self._peers) == 1, (
            f"User interface must have exactly one peer: Got {self._peers}"
        )
        peer = self._peers[0]

        # Start the base agent's message processing
        agent_task = asyncio.create_task(super().run())

        try:
            # Establish session and send initial message
            await asyncio.sleep(1)  # wait for other agents to connect
            session_id = await self.establish_session(peer, self.session_id)
            console.print(f"Starting new conversation (Session ID: {session_id})")

            # Send initial message to start the conversation
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

            # Wait for the agent to complete
            await agent_task

        finally:
            agent_task.cancel()
            try:
                await agent_task
            except asyncio.CancelledError:
                pass


if __name__ == "__main__":
    from typer import Typer

    from .chat import ChatAgent
    from ..transport.nats import NatsTransport

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
            transport = NatsTransport(server_url=nats_url)
            await transport.connect()
            chat = ChatAgent(
                name="assistant-2",
                model=model,
                description="A helpful assistant that can answer questions and help with tasks.",
                openai_kwargs={"api_key": api_key, "base_url": base_url},
                transport=transport,
            )
            # pirate = ChatAgent(
            #     name="pirate-riddler-2",
            #     model=model,
            #     description="A pirate that creates riddles",
            #     openai_kwargs={"api_key": api_key, "base_url": base_url},
            #     transport=transport,
            # )
            user = UserInterface(
                name="tony-2",
                session_id=session_id,
                description="A user interface for the chat agent.",
                transport=transport,
            )

            # await chat.register_peer(pirate.info)
            # await pirate.register_peer(chat.info)
            await user.register_peer(chat.info)

            # Run all agents concurrently in the background
            await asyncio.gather(
                chat.run(),
                # pirate.run(),
                user.run(),
            )

        asyncio.run(main())

    app()
