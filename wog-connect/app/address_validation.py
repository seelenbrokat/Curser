from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.address_util import (
    build_post_validation_request,
    extract_validated_recipient,
    merge_suggested_recipient,
    recipient_differs,
)
from app.config import Settings
from app.post_client import PostApiError, PostClient
from app.soloplan_parser import Address, ShipmentDraft

_OK_QUALITIES = frozenset({"CERTIFIED", "DOMICILE_VALIDATED"})
_WARN_QUALITIES = frozenset({"HOUSE_NO_NOT_FOUND", "HOUSE_NO_INVALID"})


@dataclass
class AddressValidationResult:
    valid: bool
    quality: str | None
    message: str
    suggested: dict[str, str] | None = None
    raw: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "quality": self.quality,
            "message": self.message,
            "suggested": self.suggested,
        }


class AddressValidator:
    def __init__(self, settings: Settings, post: PostClient | None = None):
        self.settings = settings
        self.post = post or PostClient(settings)

    def validate_recipient(
        self,
        recipient: Address,
        *,
        full_validation: bool = True,
    ) -> AddressValidationResult:
        country = (recipient.country or "CH").strip().upper()
        if country not in {"CH", "LI"}:
            return AddressValidationResult(
                valid=True,
                quality=None,
                message=f"Adressprüfung nur für CH/LI (Land: {country}) – übersprungen",
            )

        if not self.settings.post_address_validate_enabled:
            return AddressValidationResult(valid=True, quality=None, message="Adressprüfung deaktiviert")

        try:
            payload = build_post_validation_request(
                name1=recipient.name1,
                name2=recipient.name2,
                street=recipient.street,
                zip_code=recipient.zip_code,
                city=recipient.city,
                country=country,
                full_validation=full_validation,
            )
            resp = self.post.validate_address(payload)
        except PostApiError as e:
            detail = str(e.payload)[:300] if e.payload else str(e)
            if e.status == 403:
                return AddressValidationResult(
                    valid=not self.settings.post_address_validate_strict,
                    quality="FORBIDDEN",
                    message="Post Adressprüfung nicht freigeschaltet (Scope DCAPI_ADDRESS_VALIDATE)",
                    raw={"error": detail},
                )
            return AddressValidationResult(
                valid=not self.settings.post_address_validate_strict,
                quality="ERROR",
                message=f"Adressprüfung fehlgeschlagen: {detail}",
                raw={"error": detail},
            )

        quality = str(resp.get("quality") or "").upper()
        suggested = extract_validated_recipient(resp)
        original = {
            "name1": recipient.name1,
            "name2": recipient.name2 or "",
            "street": recipient.street,
            "zip_code": recipient.zip_code,
            "city": recipient.city,
        }

        if quality in _OK_QUALITIES:
            if suggested and recipient_differs(original, suggested):
                return AddressValidationResult(
                    valid=True,
                    quality=quality,
                    message="Adresse gültig – Post-Version wird übernommen",
                    suggested=suggested,
                    raw=resp,
                )
            return AddressValidationResult(
                valid=True,
                quality=quality,
                message="Adresse von der Post bestätigt",
                suggested=suggested,
                raw=resp,
            )

        if quality in _WARN_QUALITIES:
            msg = f"Adresse mit Einschränkung ({quality})"
            return AddressValidationResult(
                valid=not self.settings.post_address_validate_strict,
                quality=quality,
                message=msg,
                suggested=suggested,
                raw=resp,
            )

        return AddressValidationResult(
            valid=False,
            quality=quality or "INVALID",
            message=f"Adresse nicht zustellbar laut Post ({quality or 'unbekannt'})",
            suggested=suggested,
            raw=resp,
        )

    def validate_draft(self, draft: ShipmentDraft) -> AddressValidationResult:
        return self.validate_recipient(draft.recipient)
