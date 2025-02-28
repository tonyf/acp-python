from .base import Agent, TextMessage, ConversationSession, AgentInfo
from openai import AsyncOpenAI
import os
import uuid
import json


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
        # Create a new session ID for agent-to-agent communication
        agent_session_id = str(uuid.uuid4())

        # Parse content if it's in {"msg": "..."} format from tool calls
        try:
            content_data = json.loads(content)
            if isinstance(content_data, dict) and "msg" in content_data:
                content = content_data["msg"]
        except (json.JSONDecodeError, TypeError):
            # If parsing fails, keep the original content
            pass

        # Send the message to the target agent with NEW session_id
        sent_message = TextMessage(
            content=content,
            source=self.info,
            session_id=agent_session_id,
            metadata={
                "original_user": session.original_user.name,
                "original_session_id": session.session_id,
            },
        )
        await self.send(target_agent, sent_message)

        # Also record this delegation in the original session
        delegation_note = TextMessage(
            content=f"[Delegated to {target_agent.name}: {content}]",
            source=self.info,
            session_id=session.session_id,
        )
        session.append(delegation_note)
        await self.update_session(session)

        return agent_session_id

    async def on_message(self, message: TextMessage):
        session = await self.get_or_create_session(message.source, message.session_id)
        session.append(message)
        await self.update_session(session)

        # Format the chat history for OpenAI
        messages = [{"role": "system", "content": self.system_prompt}]
        for msg in session.messages:
            if msg.source == self._name:
                role = "assistant"
            else:
                role = "user"
            messages.append({"role": role, "content": msg.content})

        # Call the OpenAI API
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,  # type: ignore
            temperature=self.temperature,
            # tools=[peer.to_tool() for peer in self.peers],
        )
        assistant_message = response.choices[0].message

        # Regular text reply - send back to the original user
        reply_content = assistant_message.content
        if reply_content is None:
            raise Exception("No response from OpenAI")

        # Send response to original user
        sent_message = TextMessage(
            content=reply_content,
            source=self.info,
            session_id=session.session_id,
        )
        await self.send(session.original_user, sent_message)

        # Update session with the sent message
        session.append(sent_message)
        await self.update_session(session)
