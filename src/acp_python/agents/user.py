import asyncio
import logging
import uuid

from rich.console import Console
from typer import prompt

from acp_python.agents.base import AsyncActor
from acp_python.types import ActorInfo, Session, TextMessage

logger = logging.getLogger(__name__)

console = Console()


class ConsoleUserAgent(AsyncActor):
    """
    A user interface agent that allows human interaction with other agents.

    This agent provides a command-line interface for humans to communicate with
    other agents in the system. It handles sending messages, displaying responses,
    and managing the conversation session.
    """

    def __init__(
        self,
        identifier: str = "user",
        session_id: str | None = None,
        **kwargs,
    ):
        """
        Initialize the UserInterface agent.

        Args:
            identifier: The identifier of the user agent.
            session_id: Optional session ID. If not provided, a random UUID will be generated.
            **kwargs: Additional arguments to pass to the parent Agent class.
        """
        super().__init__(identifier, **kwargs)
        self.session_id = session_id or str(uuid.uuid4())

    def message_key(self, actor_info: ActorInfo, _: str = "*") -> str:
        """
        Generate a unique key for messages with this agent.

        Args:
            agent_info: Information about the agent to communicate with.
            _: Placeholder parameter, not used.

        Returns:
            A string key for identifying messages with this agent.
        """
        return super().message_key(actor_info, self.session_id)

    async def on_message(self, session: Session):
        """
        Handle incoming messages from other agents.

        Displays the message to the user and prompts for a response.

        Args:
            session: The current conversation session.
        """
        last_message = session.history[-1]
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
        """
        Run the user interface agent.

        Establishes a session with a peer agent and handles the conversation flow.
        The agent must have exactly one peer to communicate with.
        """
        assert len(self._peers) == 1, (
            f"User interface must have exactly one peer: Got {self._peers}"
        )
        peer = self._peers[0]

        # Start the base agent's message processing
        loop = asyncio.create_task(super().run())

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
            await loop

        finally:
            loop.cancel()
            try:
                await loop
            except asyncio.CancelledError:
                pass


if __name__ == "__main__":
    from typer import Typer
    import logging
    import os
    from acp_python.transport.nats import AsyncNatsTransport

    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=getattr(logging, log_level))

    app = Typer()

    @app.command()
    def run(
        nats_url: str = "nats://local:3GNtWSMhUvdxjp1OLJfmpa67qZyICWSf@0.0.0.0:4222",
        session_id: str | None = None,
    ):
        async def main():
            # Create agents
            async with AsyncNatsTransport(server_url=nats_url) as transport:
                user = ConsoleUserAgent(
                    identifier="tony-2",
                    session_id=session_id,
                    description="A user interface for the chat agent.",
                    transport=transport,
                )

                await user.register_peer(
                    ActorInfo(identifier="assistant-2", description="A chat agent.")
                )
                await user.run()

        asyncio.run(main())

    @app.command()
    def chat(
        model: str = "mistral-small",
        api_key: str = "ollama",
        base_url: str = "http://localhost:11434/v1",
        nats_url: str = "nats://local:3GNtWSMhUvdxjp1OLJfmpa67qZyICWSf@0.0.0.0:4222",
        session_id: str | None = None,
    ):
        from acp_python.agents.chat import ChatAgent

        async def main():
            # Create agents
            async with AsyncNatsTransport(server_url=nats_url) as transport:
                chat = ChatAgent(
                    identifier="assistant-2",
                    model=model,
                    description="A helpful assistant that can answer questions and help with tasks.",
                    openai_kwargs={"api_key": api_key, "base_url": base_url},
                    transport=transport,
                )
                user = ConsoleUserAgent(
                    identifier="tony-2",
                    session_id=session_id,
                    description="A user interface for the chat agent.",
                    transport=transport,
                )

                await user.register_peer(chat.info)
                await asyncio.gather(chat.run(), user.run())

        asyncio.run(main())

    app()
