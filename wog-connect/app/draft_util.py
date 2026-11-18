from __future__ import annotations

import json
from typing import Any

from app.delivery_products import get_delivery_product, przl_for_product
from app.soloplan_parser import Address, ShipmentDraft


def draft_to_dict(draft: ShipmentDraft, *, delivery_product_id: str = "eco") -> dict[str, Any]:
    return {
        "tour_number": draft.tour_number,
        "transport_order_number": draft.transport_order_number,
        "item_number": draft.item_number,
        "carrier_matchcode": draft.carrier_matchcode,
        "consignment_reference": draft.consignment_reference,
        "item_id": draft.item_id,
        "external_number": draft.external_number,
        "external_order_number": draft.external_order_number,
        "consignment_number": draft.consignment_number,
        "sendungsnummer": draft.sendungsnummer,
        "content": draft.content,
        "weight_grams": draft.weight_grams,
        "packstuecke": draft.packstuecke,
        "delivery_product_id": delivery_product_id,
        "przl": draft.przl or przl_for_product(delivery_product_id),
        "notify_recipient": draft.notify_recipient,
        "recipient": {
            "name1": draft.recipient.name1,
            "name2": draft.recipient.name2,
            "street": draft.recipient.street,
            "zip_code": draft.recipient.zip_code,
            "city": draft.recipient.city,
            "country": draft.recipient.country,
            "email": draft.recipient.email,
        },
        "sender": {
            "name1": draft.sender.name1,
            "street": draft.sender.street,
            "zip_code": draft.sender.zip_code,
            "city": draft.sender.city,
            "country": draft.sender.country,
            "email": draft.sender.email,
        },
        "recipient_matchcode": draft.recipient_matchcode,
        "recipient_bp_id": draft.recipient_bp_id,
    }


def _addr_from(data: dict[str, Any]) -> Address:
    return Address(
        name1=str(data.get("name1") or ""),
        street=str(data.get("street") or ""),
        zip_code=str(data.get("zip_code") or data.get("zip") or ""),
        city=str(data.get("city") or ""),
        country=str(data.get("country") or "CH"),
        email=(str(data.get("email")).strip() or None) if data.get("email") else None,
        name2=(str(data.get("name2")).strip() or None) if data.get("name2") else None,
    )


def draft_from_dict(data: dict[str, Any]) -> ShipmentDraft:
    product_id = str(data.get("delivery_product_id") or "eco")
    przl = data.get("przl") or przl_for_product(product_id)
    recipient = _addr_from(data.get("recipient") or {})
    notify = data.get("notify_recipient")
    if notify is None:
        notify = bool(recipient.email)
    return ShipmentDraft(
        tour_number=data.get("tour_number", "?"),
        transport_order_number=int(data.get("transport_order_number") or 0),
        item_number=int(data.get("item_number") or 1),
        carrier_matchcode=str(data.get("carrier_matchcode") or ""),
        consignment_reference=str(data.get("consignment_reference") or ""),
        item_id=str(data.get("item_id") or ""),
        recipient=recipient,
        sender=_addr_from(data.get("sender") or {}),
        weight_grams=max(1, int(data.get("weight_grams") or 1000)),
        packstuecke=max(1, int(data.get("packstuecke") or 1)),
        content=str(data.get("content") or ""),
        external_number=str(data.get("external_number") or ""),
        external_order_number=str(data.get("external_order_number") or ""),
        consignment_number=str(data.get("consignment_number") or ""),
        sendungsnummer=str(data.get("sendungsnummer") or ""),
        przl=list(przl),
        notify_recipient=bool(notify),
        recipient_matchcode=str(data.get("recipient_matchcode") or ""),
        recipient_bp_id=str(data.get("recipient_bp_id") or ""),
    )


def draft_from_row(row: dict[str, Any]) -> ShipmentDraft | None:
    raw = row.get("draft_json")
    if raw:
        try:
            return draft_from_dict(json.loads(raw))
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    return draft_from_row_fallback(row)


def draft_from_row_fallback(row: dict[str, Any]) -> ShipmentDraft | None:
    if not row.get("recipient_name"):
        return None
    product_id = row.get("delivery_product_id") or "eco"
    return ShipmentDraft(
        tour_number="?",
        transport_order_number=int(row.get("transport_order_number") or 0),
        item_number=int(row.get("item_number") or 1),
        carrier_matchcode="",
        consignment_reference=str(row.get("consignment_reference") or ""),
        item_id=str(row.get("item_id") or ""),
        recipient=Address(
            name1=str(row.get("recipient_name") or ""),
            street=str(row.get("recipient_street") or ""),
            zip_code=str(row.get("recipient_zip") or ""),
            city=str(row.get("recipient_city") or ""),
            country=str(row.get("recipient_country") or "CH"),
            email=row.get("recipient_email"),
        ),
        sender=Address(
            name1="WOG Logistics AG",
            street="Wildenaustraße 22",
            zip_code="9444",
            city="Diepoldsau",
            country="CH",
        ),
        weight_grams=int(row.get("weight_grams") or 1000),
        packstuecke=max(1, int(row.get("packstuecke") or 1)),
        external_number=str(row.get("external_number") or ""),
        external_order_number=str(row.get("external_order_number") or ""),
        consignment_number=str(row.get("consignment_number") or row.get("item_number") or ""),
        sendungsnummer=str(row.get("sendungsnummer") or ""),
        przl=przl_for_product(product_id),
        notify_recipient=bool(row.get("recipient_email")),
    )
