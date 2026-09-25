"""
Authentication endpoints.

Deliberately thin. All the rules live in `services/auth.py`; this module only
translates HTTP into calls on that service and service results back into HTTP.

The one invariant enforced here, in the router, not the service: **the session
token is never echoed in a body that also carries configuration.** `auth_status`
reports `supabase_configured` as a boolean and nothing else — the URL and keys
stay on the server. `services/auth.py` already guarantees the service-role key
never leaves it; the endpoint surface is written so a future change cannot
route around that.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from services import auth as auth_service
from services.auth import AuthState, AuthUnavailable, resolve_identity

router = APIRouter(prefix="/auth", tags=["auth"])


class CredentialsBody(BaseModel):
    """Email and password. Neither is logged, echoed, or persisted here."""

    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=8, max_length=256)

    @field_validator("email")
    @classmethod
    def _looks_like_email(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if "@" not in cleaned or cleaned.startswith("@") or cleaned.endswith("@"):
            raise ValueError("email must contain a local part and a domain")
        return cleaned


def _unavailable(exc: Exception, code: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"error": code, "detail": str(exc), "kind": "unavailable"},
    )


@router.get(
    "/status",
    summary="What sign-in this deployment supports (never any credential)",
)
def status_() -> dict:
    """
    Capability disclosure for the login page: can the user sign up, is this a
    demo, is sign-in required. Reports booleans and a human note — no URL, no
    anon key, no service-role key.
    """
    return auth_service.auth_status()


@router.post(
    "/signup",
    status_code=status.HTTP_201_CREATED,
    summary="Create an account (disabled in demo mode)",
)
def signup(body: CredentialsBody) -> dict:
    """
    Register a user. Returns whether a session was issued or email confirmation
    is required first. In demo mode this is refused — a demo should not collect
    real passwords for storage in a local JSON file.
    """
    try:
        return auth_service.sign_up(body.email, body.password)
    except AuthUnavailable as exc:
        raise _unavailable(exc, "signup_unavailable")


@router.post(
    "/login",
    summary="Exchange credentials for a session token",
)
def login(body: CredentialsBody) -> dict:
    """
    Returns the access token for the caller to use as
    `Authorization: Bearer <token>`. The browser holds this and the anon key;
    the service-role key is never in scope here and never returned.
    """
    try:
        return auth_service.sign_in(body.email, body.password)
    except AuthUnavailable as exc:
        # 401 for "not accepted", 503 for "Supabase isn't configured". The
        # distinction matters: one is the user's problem, the other is the
        # deployment's, and a login form should say which it is.
        if "not accepted" in str(exc).lower():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": "invalid_credentials", "detail": str(exc), "kind": "unavailable"},
            )
        raise _unavailable(exc, "signin_unavailable")


@router.post(
    "/logout",
    summary="Invalidate the current session",
)
def logout(authorization: Optional[str] = Header(None)) -> dict:
    """
    Best-effort revocation. In demo mode this is a no-op that still reports
    success, because there is no session to revoke and telling the UI otherwise
    would be a false statement about server state.
    """
    identity = resolve_identity(authorization)
    if identity.get("state") == AuthState.AUTHENTICATED and identity.get("token"):
        auth_service.sign_out(identity["token"])
    return {"signed_out": True}
