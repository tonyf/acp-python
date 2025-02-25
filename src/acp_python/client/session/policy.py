from typing import Protocol, Tuple, List, Optional, Dict, Any
from acp_python.core.types import Actor
from ..middleware import Middleware
from ..client import AcpClient
import aiohttp


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

    async def __call__(self, peer: Actor) -> Tuple[bool, str]: ...


class AllowAllPolicy(SessionPolicy):
    """Policy that allows sessions with all actors."""

    async def __call__(self, peer: Actor) -> Tuple[bool, str]:
        return True, ""


class DenyAllPolicy(SessionPolicy):
    """Policy that denies sessions with all actors."""

    async def __call__(self, peer: Actor) -> Tuple[bool, str]:
        return False, "Sessions are not allowed"


class WhitelistPolicy(SessionPolicy):
    """
    Policy that only allows sessions with a predefined list of actors.

    Args:
        allowed_actors: List of Actor objects that are allowed to establish sessions.
    """

    def __init__(self, allowed_actors: List[Actor]):
        self.allowed_actors = allowed_actors

    async def __call__(self, peer: Actor) -> Tuple[bool, str]:
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

    async def fetch_is_allowed(self, peer: Actor) -> Dict[str, Any]:
        async with aiohttp.ClientSession() as client:
            async with client.get(
                self.api_url, headers={"Authorization": f"Bearer {self.token}"}
            ) as response:
                return await response.json()

    async def __call__(self, peer: Actor) -> Tuple[bool, str]:
        resp = await self.fetch_is_allowed(peer)
        return resp["allowed"], resp["reason"]


class SessionPolicyMiddleware(Middleware):
    """
    Middleware that enforces session policies for actor connections.

    This middleware checks whether a peer is allowed to establish a session
    based on the configured SessionPolicy.

    Args:
        session_policy: The policy to use for determining session permissions.
    """

    def __init__(self, session_policy: SessionPolicy):
        self.session_policy = session_policy

    async def on_session_request(
        self, client: AcpClient, me: Actor, peer: Actor
    ) -> Tuple[bool, Optional[str]]:
        """
        Handles incoming session requests by checking against the session policy.

        Args:
            client: The ACP client handling the request
            me: The actor receiving the session request
            peer: The actor requesting the session

        Returns:
            Tuple containing:
                - bool: Whether the session is allowed
                - Optional[str]: Reason for rejection if session is denied
        """
        allowed, reason = await self.session_policy(peer)
        return allowed, reason
