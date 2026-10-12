"""Authentication and authorization dependencies for the FastAPI app.

Two kinds of callers exist:

* ``service``: any caller presenting ``AUTH_SECRET`` (``x-auth-token`` or
  ``Authorization: Bearer``). Service callers may use every route, except
  admin-only routes, which always need a Discord user with the admin role.
* ``discord``: an in-process call made by the Discord adapter after the
  ed25519 signature of the interaction was verified. The adapter proves this
  by sending ``INTERNAL_TOKEN``, a random value generated per process that an
  external caller can never know. Without it, the Discord user ID header is
  ignored, so a user ID can't be spoofed from outside.
"""

import hmac
import secrets
from dataclasses import dataclass
from typing import Literal

from fastapi import Depends, HTTPException, Request

from personal_server_hub.application.users import get_user_role
from personal_server_hub.services.auth import is_authorized

INTERNAL_TOKEN = secrets.token_urlsafe(32)
INTERNAL_TOKEN_HEADER = "x-internal-token"
DISCORD_USER_HEADER = "x-discord-user-id"

ADMIN_ROLE = "superadmin"


@dataclass(frozen=True)
class Principal:
    kind: Literal["service", "discord"]
    discord_user_id: str | None = None


def internal_headers(discord_user_id: str) -> dict[str, str]:
    """Headers the Discord adapter adds to in-process calls."""
    return {
        INTERNAL_TOKEN_HEADER: INTERNAL_TOKEN,
        DISCORD_USER_HEADER: str(discord_user_id),
    }


def get_principal(request: Request) -> Principal:
    headers = dict(request.headers)

    if is_authorized(headers):
        return Principal(kind="service")

    internal_token = headers.get(INTERNAL_TOKEN_HEADER, "")
    discord_user_id = headers.get(DISCORD_USER_HEADER, "").strip()
    if (
        discord_user_id
        and internal_token
        and hmac.compare_digest(internal_token, INTERNAL_TOKEN)
    ):
        return Principal(kind="discord", discord_user_id=discord_user_id)

    raise HTTPException(status_code=401, detail="Unauthorized")


def _lookup_role(principal: Principal) -> str | None:
    status, role = get_user_role(principal.discord_user_id or "")
    if status != 200:
        raise HTTPException(status_code=502, detail="Nutzerrolle konnte nicht geprüft werden")
    return role


def require_registered(principal: Principal = Depends(get_principal)) -> Principal:
    """Service callers pass; Discord users must exist in dim_users."""
    if principal.kind == "service":
        return principal
    if _lookup_role(principal) is None:
        raise HTTPException(status_code=403, detail="Discord-Nutzer ist nicht registriert")
    return principal


def require_admin(principal: Principal = Depends(get_principal)) -> Principal:
    """Only a registered Discord user with the admin role passes.

    ``AUTH_SECRET`` alone is deliberately not enough.
    """
    if principal.kind != "discord":
        raise HTTPException(status_code=403, detail="Admin-Rechte über Discord erforderlich")
    if _lookup_role(principal) != ADMIN_ROLE:
        raise HTTPException(status_code=403, detail="Admin-Rechte erforderlich")
    return principal
