from __future__ import annotations

import secrets
from typing import Any

from fastapi import HTTPException, Request

from app.config import CustomerAccount, get_settings

ROLE_ADMIN = "admin"
ROLE_CUSTOMER = "customer"


def require_api_key(request: Request) -> None:
    settings = get_settings()
    if not settings.api_key:
        raise HTTPException(status_code=503, detail="API key not configured")
    key = request.headers.get("X-API-Key") or request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not key or not secrets.compare_digest(key, settings.api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")


def is_logged_in(request: Request) -> bool:
    return bool(request.session.get("user"))


def current_user(request: Request) -> str:
    return str(request.session.get("user") or "")


def current_role(request: Request) -> str:
    return str(request.session.get("role") or ROLE_ADMIN)


def is_customer(request: Request) -> bool:
    return current_role(request) == ROLE_CUSTOMER


def require_login(request: Request) -> None:
    if not is_logged_in(request):
        raise HTTPException(status_code=401, detail="Login required")


def require_admin(request: Request) -> None:
    require_login(request)
    if current_role(request) != ROLE_ADMIN:
        raise HTTPException(status_code=403, detail="Nur für Administratoren")


def require_customer(request: Request) -> None:
    require_login(request)
    if current_role(request) != ROLE_CUSTOMER:
        raise HTTPException(status_code=403, detail="Nur für Kundenportal")


def session_customer_account(request: Request) -> CustomerAccount | None:
    settings = get_settings()
    user = current_user(request)
    if not user:
        return None
    return settings.portal_customer_accounts.get(user)


def attempt_login(username: str, password: str, request: Request) -> dict[str, Any] | None:
    """Login für Admin- oder Kundenkonto. Gibt Session-Infos zurück oder None."""
    settings = get_settings()
    if not username or not password:
        return None

    customer = settings.portal_customer_accounts.get(username)
    if customer is not None:
        if not secrets.compare_digest(password, customer.password):
            return None
        request.session.clear()
        request.session["user"] = username
        request.session["role"] = ROLE_CUSTOMER
        request.session["display_name"] = customer.display_name
        return {"ok": True, "role": ROLE_CUSTOMER, "redirect": "/kunde", "display_name": customer.display_name}

    expected = settings.portal_accounts.get(username)
    if expected is None:
        return None
    if not secrets.compare_digest(password, expected):
        return None
    request.session.clear()
    request.session["user"] = username
    request.session["role"] = ROLE_ADMIN
    request.session["display_name"] = username
    return {"ok": True, "role": ROLE_ADMIN, "redirect": "/", "display_name": username}
