from __future__ import annotations

import re

from app.soloplan_parser import ShipmentDraft

_PIECE_SUFFIX_RE = re.compile(r"-P\d+$", re.I)


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
    base = base[:50]
    if piece_count > 1:
        suffix = f"-P{piece_number}"
        return f"{base[: max(1, 50 - len(suffix))]}{suffix}"[:50]
    return base


def normalize_reference_token(ref: str) -> str:
    return _PIECE_SUFFIX_RE.sub("", (ref or "").strip())
