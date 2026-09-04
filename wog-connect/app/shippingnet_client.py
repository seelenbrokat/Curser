from __future__ import annotations

import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Any
from urllib.parse import quote

import requests

from app.config import Settings


def normalize_shippingnet_status_date(raw: datetime | str | None) -> str | None:
    """Post-Zustellzeit → ISO-8601 UTC für shipping.NET (nie „jetzt“ erfinden)."""
    if raw is None:
        return None
    if isinstance(raw, datetime):
        dt = raw
    else:
        text = str(raw).strip()
        if not text:
            return None
        text = text.replace("Z", "+00:00")
        # "2026-07-17 09:37:36" → iso
        if " " in text and "T" not in text:
            text = text.replace(" ", "T", 1)
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
                try:
                    dt = datetime.strptime(text[:19], fmt)
                    break
                except ValueError:
                    dt = None
            if dt is None:
                return None
    if dt.tzinfo is None:
        # Formatierte Post-Zeiten ohne Offset = Schweizer Lokalzeit
        dt = dt.replace(tzinfo=ZoneInfo("Europe/Zurich"))
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


class ShippingNetError(Exception):
    def __init__(self, message: str, status: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status = status
        self.payload = payload


class ShippingNetClient:
    """WOG-Portal → shipping.NET / OnDot Status-Updates."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._token: str | None = None
        self._token_expires = 0.0

    @property
    def enabled(self) -> bool:
        return bool(
            self.settings.shippingnet_enabled
            and self.settings.shippingnet_base_url
            and self.settings.shippingnet_email
            and self.settings.shippingnet_password
        )

    def _login(self) -> str:
        if self._token and time.time() < self._token_expires - 30:
            return self._token
        url = f"{self.settings.shippingnet_base_url.rstrip('/')}/api/auth/login"
        last_err: Exception | None = None
        for attempt in range(4):
            try:
                resp = requests.post(
                    url,
                    json={
                        "email": self.settings.shippingnet_email,
                        "password": self.settings.shippingnet_password,
                    },
                    timeout=45,
                )
            except requests.RequestException as e:
                last_err = e
                time.sleep(1.5 * (attempt + 1))
                continue
            if resp.status_code in {502, 503, 504}:
                last_err = ShippingNetError(
                    f"Login fehlgeschlagen ({resp.status_code})",
                    resp.status_code,
                    resp.text[:300],
                )
                time.sleep(1.5 * (attempt + 1))
                continue
            if resp.status_code >= 400:
                raise ShippingNetError(
                    f"Login fehlgeschlagen ({resp.status_code})",
                    resp.status_code,
                    resp.text[:500],
                )
            data = resp.json() if resp.content else {}
            token = data.get("accessToken") or data.get("access_token") or data.get("token")
            if not token:
                raise ShippingNetError("Login ohne accessToken", resp.status_code, data)
            expires_in = int(data.get("expiresIn") or data.get("expires_in") or 600)
            self._token = str(token)
            self._token_expires = time.time() + max(60, expires_in)
            return self._token
        raise ShippingNetError(str(last_err) if last_err else "Login fehlgeschlagen")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._login()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def mark_delivered(
        self,
        shipment_number: str,
        *,
        description: str = "Zugestellt",
        status_date: datetime | str | None = None,
    ) -> dict[str, Any]:
        if not self.enabled:
            raise ShippingNetError("shipping.NET Integration nicht konfiguriert")
        number = (shipment_number or "").strip()
        if not number:
            raise ShippingNetError("Keine Sendungsnummer für shipping.NET")
        iso = normalize_shippingnet_status_date(status_date)
        if not iso:
            raise ShippingNetError("Keine echte Zustellzeit (deliveryDate) – DVD nicht gesetzt")
        body: dict[str, Any] = {
            "description": description or "Zugestellt",
            "statusDate": iso,
        }
        url = (
            f"{self.settings.shippingnet_base_url.rstrip('/')}"
            f"/api/integrations/shippingnet/shipments/{quote(number, safe='')}/delivered"
        )
        resp = requests.post(url, headers=self._headers(), json=body, timeout=45)
        if resp.status_code in {401, 403}:
            # Token evtl. abgelaufen → einmal neu
            self._token = None
            resp = requests.post(url, headers=self._headers(), json=body, timeout=45)
        if resp.status_code >= 400:
            raise ShippingNetError(
                f"DVD-Status fehlgeschlagen ({resp.status_code})",
                resp.status_code,
                resp.text[:800],
            )
        try:
            return resp.json() if resp.content else {"ok": True}
        except ValueError:
            return {"ok": True, "raw": resp.text[:200]}

    def get_status(self, shipment_number: str) -> dict[str, Any]:
        if not self.enabled:
            raise ShippingNetError("shipping.NET Integration nicht konfiguriert")
        number = (shipment_number or "").strip()
        url = (
            f"{self.settings.shippingnet_base_url.rstrip('/')}"
            f"/api/integrations/shippingnet/shipments/{quote(number, safe='')}/status"
        )
        resp = requests.get(url, headers=self._headers(), timeout=30)
        if resp.status_code >= 400:
            raise ShippingNetError(
                f"Status-Abfrage fehlgeschlagen ({resp.status_code})",
                resp.status_code,
                resp.text[:500],
            )
        return resp.json() if resp.content else {}
