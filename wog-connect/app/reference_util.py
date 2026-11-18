from __future__ import annotations

import re
import time
import uuid

from app.soloplan_parser import ShipmentDraft

_PIECE_SUFFIX_RE = re.compile(r"-P\d+$", re.I)
# Post Barcode itemID: nicht leer, Pattern alphanumerisch/Bindestrich
_ITEM_ID_SAFE = re.compile(r"[^A-Za-z0-9_-]+")


def _fallback_item_id() -> str:
    return f"WOG{int(time.time())}{uuid.uuid4().hex[:4]}".upper()


def sanitize_item_id(value: str | None) -> str:
    raw = _ITEM_ID_SAFE.sub("-", (value or "").strip()).strip("-_")
    raw = re.sub(r"-{2,}", "-", raw)
    return (raw[:50] or _fallback_item_id())[:50]


def post_item_reference(
    shipment: ShipmentDraft,
    *,
    piece_number: int = 1,
    piece_count: int = 1,
) -> str:
    base = (
        (shipment.sendungsnummer or "").strip()
        or (shipment.external_number or "").strip()
        or (shipment.item_id or "").strip()
    )
    base = sanitize_item_id(base)
    if piece_count > 1:
        suffix = f"-P{piece_number}"
        return f"{base[: max(1, 50 - len(suffix))]}{suffix}"[:50]
    return base


def normalize_reference_token(ref: str) -> str:
    return _PIECE_SUFFIX_RE.sub("", (ref or "").strip())
