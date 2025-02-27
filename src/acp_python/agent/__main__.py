from typer import Typer, prompt
from .chat import ChatAgent
from .user import UserInterface
from .base import TextMessage
import asyncio

app = Typer()


@app.command()
def chat(
    model: str = "mistral-small",
    api_key: str = "ollama",
    base_url: str = "http://localhost:11434/v1",
    nats_url: str = "nats://local:mth9p5VLc3ARX4OUyQEO4IrKJIrw0Y8C@0.0.0.0:4222",
):
    async def main():
        chat = ChatAgent(
            name="chat-2",
            model=model,
            description="A helpful assistant that can answer questions and help with tasks.",
            openai_kwargs={"api_key": api_key, "base_url": base_url},
            server_url=nats_url,
        )
        pirate = ChatAgent(
            name="pirate",
            model=model,
            description="A pirate that creates riddles",
            openai_kwargs={"api_key": api_key, "base_url": base_url},
            server_url=nats_url,
        )
        user = UserInterface(
            name="tony-2",
            description="A user interface for the chat agent.",
            peers=[chat.info],
            server_url=nats_url,
        )

        # Connect both agents
        await chat._connect()
        await pirate._connect()
        await user._connect()

        # Register peers
        await chat.register_peer(pirate.info)
        await pirate.register_peer(chat.info)

        # Get the first message from the user
        first_message = prompt("> ")

        # Send the first message to the agent
        await user.send(
            chat._name, TextMessage(content=first_message, source=user._name)
        )
        await asyncio.gather(user.run(), chat.run(), pirate.run())

    asyncio.run(main())


if __name__ == "__main__":
    asyncio.run(app())
