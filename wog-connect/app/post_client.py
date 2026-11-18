from __future__ import annotations

import base64
import time
from typing import Any

import requests

from app.config import Settings


class PostApiError(Exception):
    def __init__(self, message: str, status: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status = status
        self.payload = payload


class PostClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._token: str | None = None
        self._token_expires = 0.0
        self._token_scope: str | None = None

    def _ensure_token(self, scope: str | None = None) -> str:
        scope = scope or self.settings.post_oauth_scope
        if self._token and self._token_scope == scope and time.time() < self._token_expires - 30:
            return self._token
        if not self.settings.post_client_id or not self.settings.post_client_secret:
            raise PostApiError("Post OAuth nicht konfiguriert")
        resp = requests.post(
            self.settings.post_oauth_token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self.settings.post_client_id,
                "client_secret": self.settings.post_client_secret,
                "scope": scope,
            },
            timeout=30,
        )
        if resp.status_code >= 400:
            raise PostApiError("OAuth fehlgeschlagen", resp.status_code, resp.text)
        data = resp.json()
        self._token = data["access_token"]
        self._token_expires = time.time() + int(data.get("expires_in", 300))
        self._token_scope = scope
        return self._token

    def validate_address(self, request_body: dict[str, Any]) -> dict[str, Any]:
        scope = self.settings.post_address_oauth_scope
        token = self._ensure_token(scope)
        url = self.settings.post_address_validate_url
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=request_body,
            timeout=30,
        )
        if resp.status_code == 401:
            self._token = None
            token = self._ensure_token(scope)
            resp = requests.post(
                url,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=request_body,
                timeout=30,
            )
        if resp.status_code >= 400:
            raise PostApiError("Address validation fehlgeschlagen", resp.status_code, resp.text)
        return resp.json()

    def generate_label(self, request_body: dict[str, Any]) -> dict[str, Any]:
        token = self._ensure_token(self.settings.post_oauth_scope)
        return self._post_label(token, request_body)

    def _post_label(self, token: str, request_body: dict[str, Any]) -> dict[str, Any]:
        resp = requests.post(
            self.settings.post_barcode_url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=request_body,
            timeout=90,
        )
        if resp.status_code == 401:
            self._token = None
            token = self._ensure_token()
            resp = requests.post(
                self.settings.post_barcode_url,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=request_body,
                timeout=90,
            )
        if resp.status_code >= 400:
            detail = (resp.text or "").strip()
            if not detail:
                detail = f"HTTP {resp.status_code} (keine Detailmeldung der Post)"
            raise PostApiError(f"Barcode API fehlgeschlagen: {detail[:400]}", resp.status_code, resp.text)
        return resp.json()

    @staticmethod
    def extract_identcode(response: dict[str, Any]) -> str | None:
        item = response.get("item") or {}
        for key in ("identCode", "identcode", "identificationCode"):
            val = item.get(key)
            if val:
                return str(val)
        return None

    @staticmethod
    def extract_label_bytes(response: dict[str, Any], image_type: str) -> tuple[bytes | None, str | None]:
        item = response.get("item") or {}
        labels = item.get("label") or item.get("labels") or []
        fmt = "zpl" if image_type.upper().startswith("ZPL") else "pdf"

        for label in labels:
            if isinstance(label, str):
                try:
                    return base64.b64decode(label), fmt
                except Exception:
                    return label.encode("utf-8", errors="ignore"), fmt
            if isinstance(label, dict):
                for key in ("data", "image", "labelData", "file"):
                    raw = label.get(key)
                    if not raw:
                        continue
                    if isinstance(raw, str):
                        try:
                            return base64.b64decode(raw), fmt
                        except Exception:
                            return raw.encode("utf-8", errors="ignore"), fmt
        return None, None
