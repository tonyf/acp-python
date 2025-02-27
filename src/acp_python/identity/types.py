from typing import List, Optional
from pydantic import BaseModel, Field
import datetime


class UserClaims(BaseModel):
    """
    Represents the core user identity claims that may be present in a token (e.g., ID token).
    """

    sub: str = Field(..., description="Subject (unique user identifier).")
    iss: str = Field(..., description="Issuer of the token.")
    aud: str = Field(..., description="Audience (who the token is intended for).")
    iat: int = Field(..., description="Issued-at time (epoch seconds).")
    exp: int = Field(..., description="Expiration time (epoch seconds).")
    email: Optional[str] = Field(None, description="User's email address.")
    name: Optional[str] = Field(None, description="User's display name.")

    def is_expired(self) -> bool:
        """
        Checks if the token is already expired by comparing exp to current time.
        """
        return datetime.datetime.now(datetime.UTC).timestamp() > self.exp


class ActorClaims(BaseModel):
    """
    Represents an actor/service identity that is acting on behalf of a user.
    """

    actor_id: str = Field(..., description="Unique ID of the actor or service.")
    # Optionally: Additional details about the actor (client_id, environment, etc.)
    # client_id: Optional[str] = None
    # environment: Optional[str] = None


class AccessToken(BaseModel):
    """
    Represents a typical access token with enough data for on-behalf-of logic.
    Could be a JWT or another format, validated externally by an identity provider.
    """

    token_value: str = Field(..., description="The raw token string.")
    token_type: str = Field("Bearer", description="Indicates the token type.")
    expires_at: int = Field(..., description="Epoch timestamp at which token expires.")

    def is_valid(self) -> bool:
        """
        Simple validity check based on current time and expiration.
        """
        return datetime.datetime.utcnow().timestamp() < self.expires_at


class OnBehalfOfRequest(BaseModel):
    """
    Represents a request by one service (actor) to obtain or use a token
    on behalf of a user or another actor in the chain.
    """

    user_claims: UserClaims = Field(..., description="The end-user claims.")
    actor_claims: ActorClaims = Field(..., description="The requesting actor's claims.")
    requested_scope: List[str] = Field(
        default_factory=list,
        description="Scopes or permissions the actor is requesting on behalf of the user.",
    )


class OnBehalfOfResponse(BaseModel):
    """
    Represents the response from the identity provider or authority
    when a service requests to act on behalf of someone else.
    """

    access_token: AccessToken = Field(
        ..., description="Newly minted token for the actor."
    )
    granted_scope: List[str] = Field(
        default_factory=list,
        description="List of granted scopes that the actor received.",
    )

    # Optionally: Additional response metadata
    # refresh_token: Optional[str] = Field(None, description="Refresh token issued if applicable.")
    # token_type: str = Field("Bearer", description="Type of the returned token.")
