from abc import ABC, abstractmethod
from typing import Optional

from acp_python.agents.actor import AsyncActor
from acp_python.types import Message, Session


class BaseAgent(AsyncActor, ABC):
    @abstractmethod
    async def on_message(self, session: Session) -> Optional[Message]:
        """Process incoming asynchronous messages.

        Args:
            session: Updated session containing new message

        Returns:
            Message response to send back to the peer, if any.
            Note, this callback can choose to send messages manually via send().

        Note:
            Subclasses must implement this method to handle message and tasks.
            The most recent message is available as session.history[-1].
        """
        pass
