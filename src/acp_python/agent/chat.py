from .base import Agent, TextMessage, ConversationSession, AgentInfo
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion
import os


class ChatAgent(Agent):
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
        self, target_agent: AgentInfo, content: str, session: ConversationSession
    ) -> str:
        """
        Delegate a task to another agent.
        Creates a new agent-to-agent session while maintaining reference to original session.
        Returns the new session_id for the delegation.
        """
        raise NotImplementedError("Delegation not implemented")

    async def assemble_conversation(self, session: ConversationSession) -> list[dict]:
        """
        Get the conversation history in openai format
        """
        messages = [{"role": "system", "content": self.system_prompt}]
        for msg in session.messages:
            if msg.source == self._name:
                role = "assistant"
            else:
                role = "user"
            messages.append({"role": role, "content": msg.content})
        return messages

    async def get_completion(self, messages: list[dict]) -> ChatCompletion:
        """
        Call the OpenAI API with the given messages
        """
        response = await self.client.chat.completions.create(
            model=self.model, messages=messages, temperature=self.temperature
        )
        return response

    async def on_message(self, session: ConversationSession):
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
