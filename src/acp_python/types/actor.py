from pydantic import BaseModel


class ActorInfo(BaseModel):
    """Information about an actor."""

    identifier: str
    """The identifier of the actor."""

    description: str
    """The description of the actor."""
