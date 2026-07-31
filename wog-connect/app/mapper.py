from __future__ import annotations

import re
from typing import Any

from app.config import Settings
from app.delivery_products import przl_for_product
from app.reference_util import post_item_reference
from app.address_util import collapse_duplicate_house
from app.soloplan_parser import ShipmentDraft

_NAME_WORDS = re.compile(r"\b(OR|AND)\b", re.I)
_GMBH = re.compile(r"\bgmbh\b", re.I)
# Apostrophe / Anführungszeichen, die die Barcode-API (Pattern) ablehnt
_BAD_CHARS = re.compile(r"[''`´‘’‚‛″‟\"«»]")
_MULTI_SPACE = re.compile(r"\s+")

# Swiss Post: customer.name1 max 25, recipient.name1 max 35
CUSTOMER_NAME1_MAX = 25
RECIPIENT_NAME1_MAX = 35
NAME2_MAX = 35


def _sanitize_name(value: str, max_len: int = RECIPIENT_NAME1_MAX) -> str:
    """Namen für Barcode-API säubern: Apostrophe entfernen, kürzen."""
    value = _MULTI_SPACE.sub(" ", (value or "").strip())
    value = _BAD_CHARS.sub("", value)
    value = _GMBH.sub("AG", value)
    value = _NAME_WORDS.sub("", value)
    value = _MULTI_SPACE.sub(" ", value).strip(" ,.-")
    return value[:max_len] or "Unbekannt"


def _sanitize_name2(value: str) -> str:
    value = _MULTI_SPACE.sub(" ", (value or "").strip())
    value = _BAD_CHARS.sub("", value)
    return value[:NAME2_MAX]


def _split_name_lines(value: str, name1_max: int) -> tuple[str, str | None]:
    """Lange Firmennamen auf name1/name2 aufteilen (nach Säuberung)."""
    cleaned = _MULTI_SPACE.sub(" ", (value or "").strip())
    cleaned = _BAD_CHARS.sub("", cleaned)
    cleaned = _GMBH.sub("AG", cleaned)
    cleaned = _NAME_WORDS.sub("", cleaned)
    cleaned = _MULTI_SPACE.sub(" ", cleaned).strip(" ,.-")
    if not cleaned:
        return "Unbekannt", None
    if len(cleaned) <= name1_max:
        return cleaned, None
    # Am Wortende schneiden, Rest nach name2
    cut = cleaned[:name1_max]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    rest = cleaned[len(cut) :].strip(" ,.-")
    name1 = cut or cleaned[:name1_max]
    name2 = rest[:NAME2_MAX] if rest else None
    return name1 or "Unbekannt", name2 or None


def _addr(a, *, name1_max: int = RECIPIENT_NAME1_MAX) -> dict[str, Any]:
    name1, overflow_name2 = _split_name_lines(a.name1, name1_max)
    out: dict[str, Any] = {
        "name1": name1,
        "street": collapse_duplicate_house(a.street)[:35],
        "zip": a.zip_code.strip()[:10],
        "city": a.city.strip()[:35],
        "country": (a.country or "CH").strip()[:2],
    }
    name2 = _sanitize_name2(a.name2) if a.name2 else ""
    if not name2 and overflow_name2:
        name2 = overflow_name2
    if name2:
        out["name2"] = name2
    # customer/recipient.email ist in der Barcode-API nicht erlaubt (HTTP 400, leerer Body).
    # Empfänger-Mail nur über attributes.notifications senden.
    return out


def build_post_request(
    shipment: ShipmentDraft,
    settings: Settings,
    *,
    delivery_product_id: str | None = None,
    piece_number: int = 1,
    piece_count: int = 1,
) -> dict[str, Any]:
    if settings.post_label_sender_from_soloplan:
        customer = _addr(shipment.sender, name1_max=CUSTOMER_NAME1_MAX)
    else:
        name1, name2 = _split_name_lines(settings.post_sender_name1, CUSTOMER_NAME1_MAX)
        customer = {
            "name1": name1,
            "street": settings.post_sender_street,
            "zip": settings.post_sender_zip,
            "city": settings.post_sender_city,
            "country": settings.post_sender_country,
        }
        if name2:
            customer["name2"] = name2

    recipient = _addr(shipment.recipient, name1_max=RECIPIENT_NAME1_MAX)
    przl = shipment.przl or przl_for_product(delivery_product_id) or settings.post_przl
    attributes: dict[str, Any] = {
        "przl": przl,
        "weight": max(1, int(shipment.weight_grams // piece_count) if piece_count > 1 else shipment.weight_grams),
    }

    if settings.post_notifications_enabled and shipment.notify_recipient and shipment.recipient.email:
        attributes["notifications"] = [
            {
                "type": "EMAIL",
                "service": svc,
                "language": settings.post_notification_language,
                "communication": {"email": shipment.recipient.email.strip()},
            }
            for svc in settings.post_notification_services
        ]

    return {
        "language": settings.post_language,
        "frankingLicense": settings.post_franking_license,
        "ppFranking": False,
        "customer": customer,
        "customerSystem": "WOG Connect",
        "labelDefinition": {
            "labelLayout": settings.post_label_layout,
            "printAddresses": "RECIPIENT_AND_CUSTOMER",
            "imageFileType": settings.post_label_image_type,
            "imageResolution": settings.post_label_resolution,
            "printPreview": settings.post_print_preview,
        },
        "item": {
            "itemID": post_item_reference(
                shipment,
                piece_number=piece_number,
                piece_count=piece_count,
            ),
            "recipient": recipient,
            "attributes": attributes,
        },
    }
