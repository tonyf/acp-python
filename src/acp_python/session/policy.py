from abc import ABC, abstractmethod
from typing import Any, Dict, List, Protocol, Tuple

import aiohttp

from acp_python.types import HandshakeRequest, ActorInfo


# TODO: We need a callback that communicates with the server
# to update the read/write permissions on the session subjects.


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

    async def __call__(self, request: HandshakeRequest) -> Tuple[bool, str]: ...


class AllowAllPolicy(SessionPolicy):
    """Policy that allows sessions with all actors."""

    async def __call__(self, request: HandshakeRequest) -> Tuple[bool, str]:
        return True, ""


class DenyAllPolicy(SessionPolicy):
    """Policy that denies sessions with all actors."""

    async def __call__(self, request: HandshakeRequest) -> Tuple[bool, str]:
        return False, "Sessions are not allowed"


class WhitelistPolicy(SessionPolicy):
    """
    Policy that only allows sessions with a predefined list of actors.

    Args:
        allowed_actors: List of Actor objects that are allowed to establish sessions.
    """

    def __init__(self, allowed_actors: List[ActorInfo]):
        self.allowed_actors = allowed_actors

    async def __call__(self, request: HandshakeRequest) -> Tuple[bool, str]:
        return request.from_actor in self.allowed_actors, ""


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

    async def fetch_is_allowed(self, peer: ActorInfo) -> Dict[str, Any]:
        async with aiohttp.ClientSession() as client:
            async with client.get(
                f"{self.api_url}?peer={peer.identifier}",
                headers={"Authorization": f"Bearer {self.token}"},
            ) as response:
                return await response.json()

    async def __call__(self, request: HandshakeRequest) -> Tuple[bool, str]:
        resp = await self.fetch_is_allowed(request.from_actor)
        return resp["allowed"], resp["reason"]


class JwtSessionPolicy(SessionPolicy, ABC):
    """
    Abstract base class for JWT-based session policies.

    Args:
        jwt_header: Header name for the JWT token.
    """

    @abstractmethod
    async def validate_jwt(self, metadata: Dict[str, Any]) -> Tuple[bool, str]: ...

    async def __call__(self, request: HandshakeRequest) -> Tuple[bool, str]:
        return await self.validate_jwt(request.metadata)


class MultiStepSessionPolicy(SessionPolicy):
    """
    Policy that applies a list of session policies in order.

    Args:
        policies: List of SessionPolicy objects to apply.
    """

    def __init__(self, policies: List[SessionPolicy]):
        self.policies = policies

    async def __call__(self, request: HandshakeRequest) -> Tuple[bool, str]:
        for policy in self.policies:
            allowed, reason = await policy(request)
            if not allowed:
                return False, reason
        return True, ""
