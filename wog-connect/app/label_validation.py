from __future__ import annotations

from app.address_validation import AddressValidator
from app.config import get_settings
from app.soloplan_parser import ShipmentDraft
from app.weight_util import weight_warning


def validate_for_label(draft: ShipmentDraft, *, skip_address_validation: bool = False) -> list[str]:
    errors: list[str] = []
    recipient = draft.recipient
    if not (recipient.name1 or "").strip():
        errors.append("Empfängername fehlt")
    if not (recipient.street or "").strip():
        errors.append("Straße fehlt")
    if not (recipient.zip_code or "").strip():
        errors.append("PLZ fehlt")
    if not (recipient.city or "").strip():
        errors.append("Ort fehlt")
    if not (recipient.country or "").strip():
        errors.append("Land fehlt")
    if draft.weight_grams < 1:
        errors.append("Gewicht ungültig")

    settings = get_settings()
    if settings.post_address_validate_enabled and not errors and not skip_address_validation:
        result = AddressValidator(settings).validate_draft(draft)
        if not result.valid:
            errors.append(result.message)
    return errors


def warnings_for_shipment(draft: ShipmentDraft) -> list[str]:
    out: list[str] = []
    warn = weight_warning(draft.weight_grams, draft.packstuecke)
    if warn:
        out.append(warn)
    return out
