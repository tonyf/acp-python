from .base import Agent, TextMessage
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionToolParam
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

    async def on_message(self, message: TextMessage):
        # What happens when i get a message from another agent about a user? how do i continue the conversation with the user?
        # Format the chat history for OpenAI
        messages = [{"role": "system", "content": self.system_prompt}]

        history = await self.get_history(message.source)

        # Add relevant conversation history
        for msg in history.messages:
            role = "assistant" if msg.source == self._name else "user"
            messages.append({"role": role, "content": msg.content})

        # Add the current message
        messages.append({"role": "user", "content": message.content})

        try:
            # Call the OpenAI API
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,  # type: ignore
                temperature=self.temperature,
                tools=[peer.to_tool() for peer in self.peers],
            )

            # Extract the assistant's response
            assistant_message = response.choices[0].message
            sent_message: TextMessage | None = None

            # Check if the response is a tool call or a regular reply
            if assistant_message.tool_calls:
                # Handle tool call (message to another agent)
                tool_call = assistant_message.tool_calls[0]
                target_agent = tool_call.function.name
                tool_content = tool_call.function.arguments

                # Send the message to the target agent
                sent_message = TextMessage(content=tool_content, source=self._name)
                await self.send(target_agent, sent_message)
            else:
                # Regular text reply
                reply_content = assistant_message.content
                if reply_content is None:
                    raise Exception("No response from OpenAI")

                # Send the response back & update history
                sent_message = TextMessage(content=reply_content, source=self._name)
                await self.send(message.source, sent_message)

            history.messages.extend([message, sent_message])
            await self.put_history(message.source, history)

        except Exception as e:
            error_message = f"Error generating response: {str(e)}"
            await self.send(
                message.source, TextMessage(content=error_message, source=self._name)
            )
