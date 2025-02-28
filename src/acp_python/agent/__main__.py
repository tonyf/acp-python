from typer import Typer, prompt
from .chat import ChatAgent
from .user import UserInterface
from .base import TextMessage
import asyncio
import uuid
import signal

app = Typer()


@app.command()
def chat(
    model: str = "mistral-small",
    api_key: str = "ollama",
    base_url: str = "http://localhost:11434/v1",
    nats_url: str = "nats://local:rz3KgXUIm0SDr0oMUl1uNkHWqd0CUBm8@0.0.0.0:4222",
):
    async def main():
        session_id = str(uuid.uuid4())
        print(f"Starting new conversation (Session ID: {session_id})")

        # Create agents
        chat = ChatAgent(
            name="assistant-1",
            model=model,
            description="A helpful assistant that can answer questions and help with tasks.",
            openai_kwargs={"api_key": api_key, "base_url": base_url},
            server_url=nats_url,
        )
        pirate = ChatAgent(
            name="pirate-riddler-1",
            model=model,
            description="A pirate that creates riddles",
            openai_kwargs={"api_key": api_key, "base_url": base_url},
            server_url=nats_url,
        )
        user = UserInterface(
            name="tony-1",
            session_id=session_id,
            description="A user interface for the chat agent.",
            peers=[chat.info],
            server_url=nats_url,
        )

        # Connect all agents
        await chat._connect()
        await pirate._connect()
        await user._connect()

        # Register peers
        await chat.register_peer(pirate.info)
        await pirate.register_peer(chat.info)

        # Run all agents concurrently in the background
        user_task = asyncio.create_task(user.run())
        chat_task = asyncio.create_task(chat.run())
        pirate_task = asyncio.create_task(pirate.run())

        # Create a new session between user and chat agent
        session_id = await chat.establish_session(user.info, session_id)

        # Get initial message from user
        
        print("Type 'exit' to quit")
        user_input = prompt("> ")

        if user_input.lower() != "exit":
            # Send initial message to chat agent with session metadata
            await user.send(
                chat.info,
                TextMessage(
                    content=user_input,
                    source=user.info,
                    session_id=session_id,
                ),
            )

        # Wait for all tasks to complete
        await asyncio.gather(user_task, chat_task, pirate_task)

    asyncio.run(main())


if __name__ == "__main__":
    app()
