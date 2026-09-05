from __future__ import annotations

from typing import Any

import requests

from app.config import Settings


class PortalAblieferbelegError(Exception):
    def __init__(self, message: str, status: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status = status
        self.payload = payload


class PortalAblieferbelegClient:
    """WOG-Portal: Post-Ablieferbeleg (POD) per X-API-KEY hochladen."""

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
