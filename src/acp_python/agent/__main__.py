from typer import Typer
from .examples.chat import ChatAgent
from .examples.user import UserInterface
import asyncio

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


if __name__ == "__main__":
    app()
