from typing import Protocol, Tuple, List
from acp_python.client.types import Actor


class DiscoveryPolicy(Protocol):
    """
    A callable that determines whether to allow sessions with other actors.

    The callable should take a peer Actor as input and return a tuple of:
        - allowed (bool): True if session is allowed, False otherwise
        - reason (str): Description of why session was rejected if not allowed

    Example implementation:
        def my_policy(peer: Actor) -> Tuple[bool, str]:
            if peer.id.startswith("trusted-"):
                return True, ""
            return False, "Only trusted actors allowed"
    """

    def __call__(self, peer: Actor) -> Tuple[bool, str]: ...


class AllowAllPolicy(DiscoveryPolicy):
    def __call__(self, peer: Actor) -> Tuple[bool, str]:
        return True, ""


class DenyAllPolicy(DiscoveryPolicy):
    def __call__(self, peer: Actor) -> Tuple[bool, str]:
        return False, "Sessions are not allowed"


class WhitelistPolicy(DiscoveryPolicy):
    def __init__(self, allowed_actors: List[Actor]):
        self.allowed_actors = allowed_actors

    def __call__(self, peer: Actor) -> Tuple[bool, str]:
        return peer in self.allowed_actors, ""


default_policy = AllowAllPolicy()
