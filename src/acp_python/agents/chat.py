import os
from typing import cast

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion, ChatCompletionMessageParam

from acp_python.agents.base import AsyncActor
from acp_python.types import ActorInfo, Session, TextMessage


class ChatAgent(AsyncActor):
    """An agent that uses OpenAI's chat API to generate responses."""

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        system_prompt: str = "You are a helpful assistant.",
        temperature: float = 0.7,
        openai_kwargs: dict = {
            "api_key": os.environ.get("OPENAI_API_KEY"),
            "base_url": "https://api.openai.com/v1",
        },
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.client = AsyncOpenAI(**openai_kwargs)
        self.model = model
        self.system_prompt = system_prompt
        self.temperature = temperature

    async def delegate_to_agent(
        self, target_actor: ActorInfo, content: str, session: Session
    ) -> str:
        """
        Delegate a task to another agent.
        Creates a new agent-to-agent session while maintaining reference to original session.
        Returns the new session_id for the delegation.
        """
        raise NotImplementedError("Delegation not implemented")

    async def assemble_conversation(
        self, session: Session
    ) -> list[ChatCompletionMessageParam]:
        """
        Get the conversation history in openai format
        """
        messages = [{"role": "system", "content": self.system_prompt}]
        for msg in session.history:
            if msg.source == self._name:
                role = "assistant"
            else:
                role = "user"
            messages.append({"role": role, "content": msg.content})
        return cast(list[ChatCompletionMessageParam], messages)

    async def get_completion(
        self, messages: list[ChatCompletionMessageParam]
    ) -> ChatCompletion:
        """
        Call the OpenAI API with the given messages
        """
        return await self.client.chat.completions.create(
            model=self.model, messages=messages, temperature=self.temperature
        )

    async def on_message(self, session: Session):
        # TODO:
        # if you call a tool and create a new conversation,
        # that conversation should have the context of the original conversation
        # in the system prompt (delegation prompt)
        # the agent can respond to the original user as a tool call

        # Format the chat history for OpenAI
        messages = await self.assemble_conversation(session)
        response = await self.get_completion(messages)

        reply_content = response.choices[0].message.content
        if reply_content is None:
            raise Exception("No response from OpenAI")

        # Send response to original user
        sent_message = TextMessage(
            content=reply_content,
            source=self.info,
            session_id=session.session_id,
        )
        await self.send(session.original_user, sent_message)


if __name__ == "__main__":
    import asyncio

    from typer import Typer

    from acp_python.agents.chat import ChatAgent
    from acp_python.agents.user import UserInterface

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
