from __future__ import annotations

import re
from typing import Any

import requests

from app.config import Settings


class PortalAblieferbelegError(Exception):
    def __init__(self, message: str, status: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status = status
        self.payload = payload


def format_post_barcode(identcode: str | None) -> str:
    """Roh-Identcode → Post-Barcode mit Punkten, z. B. 9960… → 99.60.076424.00000913."""
    digits = re.sub(r"\D", "", str(identcode or "").strip())
    if len(digits) >= 18:
        return f"{digits[0:2]}.{digits[2:4]}.{digits[4:10]}.{digits[10:18]}"
    return digits


class PortalAblieferbelegClient:
    """WOG-Portal: Post-Ablieferbeleg (POD) und Post-Tracking per X-API-KEY."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def enabled(self) -> bool:
        return bool(
            self.settings.portal_ablieferbeleg_enabled
            and self.settings.portal_ablieferbeleg_api_key
            and self.settings.portal_ablieferbeleg_base_url
        )

    def _headers(self) -> dict[str, str]:
        return {
            "X-API-KEY": self.settings.portal_ablieferbeleg_api_key,
            "Accept": "application/json",
        }

    def upload_pdf(
        self,
        pdf: bytes,
        *,
        filename: str,
        shipment_number: str | None = None,
        post_barcode: str | None = None,
        delivered_at: str | None = None,
        mark_delivered: bool = True,
    ) -> dict[str, Any]:
        if not self.enabled:
            raise PortalAblieferbelegError("Portal-Ablieferbeleg-API nicht konfiguriert")
        if not pdf:
            raise PortalAblieferbelegError("PDF fehlt")
        number = (shipment_number or "").strip()
        barcode = (post_barcode or "").strip()
        if not number and not barcode:
            raise PortalAblieferbelegError("shipmentNumber oder postBarcode erforderlich")

        url = (
            f"{self.settings.portal_ablieferbeleg_base_url.rstrip('/')}"
            "/api/integrations/post/ablieferbelege"
        )
        data: dict[str, str] = {
            "markDelivered": "true" if mark_delivered else "false",
        }
        if number:
            data["shipmentNumber"] = number
        if barcode:
            data["postBarcode"] = barcode
        if delivered_at:
            data["deliveredAt"] = str(delivered_at).strip()

        safe_name = (filename or "ablieferbeleg.pdf").replace("/", "-")
        if not safe_name.lower().endswith(".pdf"):
            safe_name = f"{safe_name}.pdf"

        resp = requests.post(
            url,
            headers=self._headers(),
            data=data,
            files={"file": (safe_name, pdf, "application/pdf")},
            timeout=90,
        )
        if resp.status_code >= 400:
            raise PortalAblieferbelegError(
                f"Portal-Ablieferbeleg fehlgeschlagen ({resp.status_code})",
                resp.status_code,
                resp.text[:800],
            )
        try:
            return resp.json() if resp.content else {"ok": True}
        except ValueError:
            return {"ok": True, "raw": resp.text[:200]}

    def set_post_tracking(
        self,
        *,
        shipment_number: str,
        post_barcode: str,
    ) -> dict[str, Any]:
        """Setzt den Post-Barcode sofort im Portal (sichtbar/suchbar ohne POD)."""
        if not self.enabled:
            raise PortalAblieferbelegError("Portal-Ablieferbeleg-API nicht konfiguriert")
        number = (shipment_number or "").strip()
        barcode = format_post_barcode(post_barcode)
        if not number:
            raise PortalAblieferbelegError("shipmentNumber fehlt")
        if not barcode:
            raise PortalAblieferbelegError("postBarcode fehlt")

        url = (
            f"{self.settings.portal_ablieferbeleg_base_url.rstrip('/')}"
            "/api/integrations/post/tracking"
        )
        resp = requests.post(
            url,
            headers={**self._headers(), "Content-Type": "application/json"},
            json={"shipmentNumber": number, "postBarcode": barcode},
            timeout=45,
        )
        if resp.status_code >= 400:
            raise PortalAblieferbelegError(
                f"Portal Post-Tracking fehlgeschlagen ({resp.status_code})",
                resp.status_code,
                resp.text[:800],
            )
        try:
            return resp.json() if resp.content else {"ok": True}
        except ValueError:
            return {"ok": True, "raw": resp.text[:200]}
