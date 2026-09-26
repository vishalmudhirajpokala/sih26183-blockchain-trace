"""
Authentication.

The rule this module exists to enforce: **the browser may never hold a
privileged key.** The Supabase anon key is publishable and is the only Supabase
credential that belongs in client code. The service-role key stays in the
server process, is read from config, and is never returned from any function
here.

Three states, all explicit:

  AUTHENTICATED  a real Supabase user token was verified
  ANONYMOUS      demo mode with no Supabase configured — everything is
                 reachable and nothing is private
  UNAVAILABLE    Supabase is configured but no token was presented

`ANONYMOUS` and `UNAVAILABLE` are different answers. The first means the product
is deliberately open; the second means a request arrived without credentials
and should be rejected. Collapsing them would turn a misconfigured deployment
into a silently public one.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

import config

__all__ = [
    "AuthState", "resolve_identity", "auth_status", "AuthUnavailable",
    "sign_up", "sign_in", "sign_out",
]

#: Demo-mode identities are namespaced so a saved local case can never collide
#: with a real user's id, and so the UI can label them honestly.
ANONYMOUS_USER_ID = "00000000-0000-0000-0000-000000000000"
ANONYMOUS_EMAIL = "demo@blocktrace.local"


class AuthState:
    AUTHENTICATED = "authenticated"
    ANONYMOUS = "anonymous"
    UNAVAILABLE = "unavailable"


class AuthUnavailable(RuntimeError):
    """Raised when an operation needs Supabase and it is not configured."""


_client = None
_client_failed = False


def _supabase_anon():
    """
    A server-side client using the publishable anon key.

    Even server-side, the anon key is the correct credential: it is subject to
    row-level security, so a bug in a query returns nothing rather than
    everything. The service-role key is for the repository, which needs to
    write on a user's behalf after the token has already been verified.
    """
    global _client, _client_failed
    if _client is not None:
        return _client
    if _client_failed:
        return None
    if not (config.SUPABASE_URL and config.SUPABASE_ANON_KEY):
        return None
    try:
        from supabase import create_client
        _client = create_client(config.SUPABASE_URL, config.SUPABASE_ANON_KEY)
        return _client
    except Exception:
        # Import-time failure must not stop the API from serving traces.
        _client_failed = True
        return None


def _bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


def resolve_identity(authorization: Optional[str] = None) -> Dict[str, Any]:
    """
    Who is making this request.

    Returns `{state, user_id, email, token}`. `token` is passed through for the
    one call that needs it (sign-out) and must not be logged or returned in a
    response body.
    """
    token = _bearer_token(authorization)

    if not token:
        # Demo mode is checked FIRST, and that ordering is load-bearing.
        #
        # These two checks used to be the other way round, with
        # `has_supabase()` first. That meant merely adding SUPABASE_URL and
        # SUPABASE_ANON_KEY to the environment -- the step every deployment
        # takes before it is ready to require sign-in -- silently turned a demo
        # deployment into a locked one, and every route began answering 401.
        # The operator had configured accounts and had not yet asked for them.
        #
        # Demo mode is a statement that no credential is required, so it holds
        # whether or not a Supabase project happens to be configured. Only when
        # demo mode is off does it matter whether Supabase is present: present
        # means "sign in", absent means "locked, and cannot be unlocked".
        if config.DEMO_MODE:
            return {
                "state": AuthState.ANONYMOUS,
                "user_id": ANONYMOUS_USER_ID,
                "email": ANONYMOUS_EMAIL,
                "token": None,
            }
        if config.has_supabase():
            return {"state": AuthState.UNAVAILABLE, "user_id": None, "email": None, "token": None}
        return {"state": AuthState.UNAVAILABLE, "user_id": None, "email": None, "token": None}

    client = _supabase_anon()
    if client is None:
        return {"state": AuthState.UNAVAILABLE, "user_id": None, "email": None, "token": None}

    try:
        response = client.auth.get_user(token)
        user = getattr(response, "user", None) or (
            response.get("user") if isinstance(response, dict) else None
        )
    except Exception:
        # An invalid or expired token is an authentication failure, not a
        # server error. Reporting it as "unavailable" would be honest; letting
        # it become a 500 would not be.
        return {"state": AuthState.UNAVAILABLE, "user_id": None, "email": None, "token": None}

    if not user:
        return {"state": AuthState.UNAVAILABLE, "user_id": None, "email": None, "token": None}

    return {
        "state": AuthState.AUTHENTICATED,
        "user_id": getattr(user, "id", None),
        "email": getattr(user, "email", None),
        "token": token,
    }


def auth_status() -> Dict[str, Any]:
    """
    What this deployment supports, for the login page and the health check.

    Reports capability, never credentials.
    """
    return {
        "supabase_configured": config.has_supabase(),
        "signup_enabled": config.has_supabase() and not config.DEMO_MODE,
        # Google sign-in is an OAuth handshake the browser runs against Supabase.
        # Supabase returns a Supabase access token, which is the same credential
        # `resolve_identity` already verifies, so this needs no new backend
        # verification path and no Google client secret anywhere in this repo.
        # The capability is therefore purely "is Supabase configured", and
        # reporting it lets the login page explain the button rather than offer
        # one that cannot work.
        #
        # Whether the Google *provider* is switched on inside a given Supabase
        # project is not knowable here without a live call this endpoint must
        # not make, so the frontend offers it when Supabase is configured and
        # surfaces any provider-side rejection verbatim if Google is off.
        "google_sign_in": config.has_supabase(),
        "demo_mode": config.DEMO_MODE,
        "mode": (
            "live" if config.has_supabase() and not config.DEMO_MODE
            else "demo" if config.DEMO_MODE
            else "locked"
        ),
        "note": (
            "Demo mode: no account required and no case isolation. "
            "Configure SUPABASE_URL and SUPABASE_ANON_KEY and set "
            "BLOCKTRACE_DEMO_MODE=false to require sign-in."
        ) if config.DEMO_MODE else (
            "Supabase is configured. Sign-in is required for all case data."
        ),
    }


# ============================================================
# AUTH OPERATIONS
# ============================================================


def sign_up(email: str, password: str) -> Dict[str, Any]:
    """
    Register a user.

    Disabled in demo mode on purpose: a demo that accepts real registrations
    invites people to type a real password into something that stores cases in
    a JSON file on the developer's laptop.
    """
    if config.DEMO_MODE:
        raise AuthUnavailable(
            "Account creation is disabled in demo mode. Set "
            "BLOCKTRACE_DEMO_MODE=false and configure Supabase to enable it."
        )
    client = _supabase_anon()
    if client is None:
        raise AuthUnavailable("Supabase is not configured on this deployment.")

    response = client.auth.sign_up({"email": email, "password": password})
    user = getattr(response, "user", None)
    session = getattr(response, "session", None)
    return {
        "user_id": getattr(user, "id", None),
        "email": getattr(user, "email", email),
        # A session is absent when email confirmation is required. Saying so is
        # better than returning a null token the UI would treat as success.
        "session": bool(session),
        "confirmation_required": user is not None and session is None,
    }


def sign_in(email: str, password: str) -> Dict[str, Any]:
    """Exchange credentials for a session token."""
    client = _supabase_anon()
    if client is None:
        raise AuthUnavailable("Supabase is not configured on this deployment.")

    response = client.auth.sign_in_with_password({"email": email, "password": password})
    session = getattr(response, "session", None)
    if session is None:
        raise AuthUnavailable("Those credentials were not accepted.")

    return {
        "access_token": getattr(session, "access_token", None),
        "refresh_token": getattr(session, "refresh_token", None),
        "expires_at": getattr(session, "expires_at", None),
        "user": {
            "id": getattr(getattr(session, "user", None), "id", None),
            "email": getattr(getattr(session, "user", None), "email", email),
        },
    }


def sign_out(token: str) -> None:
    """Invalidate a session. Best-effort: a local JWT expiry still holds."""
    client = _supabase_anon()
    if client is None:
        return
    try:
        client.auth.sign_out(token)
    except Exception:
        # Failing to revoke server-side does not make the client token valid
        # again, and the client discards it regardless.
        pass
