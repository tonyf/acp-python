from typing import TYPE_CHECKING, Any, Dict, List, Protocol, Tuple

import aiohttp

if TYPE_CHECKING:
    from acp_python.agent.types import AgentInfo


class SessionPolicy(Protocol):
    """
    A coroutine that determines whether to allow sessions with other actors.

    The coroutine should take a peer Actor as input and return a tuple of:
        - allowed (bool): True if session is allowed, False otherwise
        - reason (str): Description of why session was rejected if not allowed

    Example implementation:
        async def my_policy(peer: Actor) -> Tuple[bool, str]:
            if peer.id.startswith("trusted-"):
                return True, ""
            return False, "Only trusted actors allowed"
    """

    async def __call__(self, peer: "AgentInfo") -> Tuple[bool, str]: ...


class AllowAllPolicy(SessionPolicy):
    """Policy that allows sessions with all actors."""

    async def __call__(self, peer: "AgentInfo") -> Tuple[bool, str]:
        return True, ""


class DenyAllPolicy(SessionPolicy):
    """Policy that denies sessions with all actors."""

    async def __call__(self, peer: "AgentInfo") -> Tuple[bool, str]:
        return False, "Sessions are not allowed"


class WhitelistPolicy(SessionPolicy):
    """
    Policy that only allows sessions with a predefined list of actors.

    Args:
        allowed_actors: List of Actor objects that are allowed to establish sessions.
    """

    def __init__(self, allowed_actors: List["AgentInfo"]):
        self.allowed_actors = allowed_actors

    async def __call__(self, peer: "AgentInfo") -> Tuple[bool, str]:
        return peer in self.allowed_actors, ""


class CloudWhitelistPolicy(SessionPolicy):
    """
    Policy that only allows sessions with a predefined list of actors from an API.

    Args:
        api_url: URL of the API to fetch allowed actors from.
        token: Token to use for API authentication.
    """

    def __init__(self, api_url: str, token: str):
        self.api_url = api_url
        self.token = token

    async def fetch_is_allowed(self, peer: "AgentInfo") -> Dict[str, Any]:
        async with aiohttp.ClientSession() as client:
            async with client.get(
                self.api_url, headers={"Authorization": f"Bearer {self.token}"}
            ) as response:
                return await response.json()

    async def __call__(self, peer: "AgentInfo") -> Tuple[bool, str]:
        resp = await self.fetch_is_allowed(peer)
        return resp["allowed"], resp["reason"]
