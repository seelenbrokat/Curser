from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from app.address_util import combine_street_house


WOG_NAME_RE = re.compile(r"wog\s+logistics", re.I)
# In Soloplan/WOG: consignmentReference6 "DPD" = Versand via Schweizer Post
POST_REFERENCE_ALIASES = frozenset({"POST", "DPD"})
# Neue TourOutExtended-Exports: kein consignmentReference6, dafür Truck/Carrier POSTCH
POST_CARRIER_ALIASES = frozenset({"POST", "POSTCH", "CHPOST", "SWISSPOST", "DPD"})


def _normalize_carrier_token(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def _carrier_indicates_post(*values: str | None) -> bool:
    for val in values:
        norm = _normalize_carrier_token(val)
        if not norm:
            continue
        if norm in POST_CARRIER_ALIASES:
            return True
        if norm.startswith("POST"):
            return True
    return False


def _tour_carrier_matchcodes(tour: dict[str, Any]) -> tuple[str, str]:
    carrier = tour.get("carrier") or {}
    tour_mc = (carrier.get("matchcode") or "").strip()
    truck_mc = ((tour.get("truck") or {}).get("matchcode") or "").strip()
    return tour_mc, truck_mc


def _post_consignment_reference(ref6: str, tour: dict[str, Any], to: dict[str, Any]) -> str:
    if ref6:
        return ref6
    tour_mc, truck_mc = _tour_carrier_matchcodes(tour)
    to_mc = ((to.get("carrier") or {}).get("matchcode") or "").strip()
    for candidate in (truck_mc, tour_mc, to_mc, "DPD"):
        if _carrier_indicates_post(candidate):
            return candidate.upper() or "DPD"
    return ""


def _reference_filter_values(reference_filter: str) -> frozenset[str]:
    if not reference_filter:
        return frozenset()
    values = {part.strip().upper() for part in reference_filter.split(",") if part.strip()}
    if values & POST_REFERENCE_ALIASES:
        values |= POST_REFERENCE_ALIASES
    return frozenset(values)


def _matches_post_shipment(
    ref6: str,
    reference_filter: str,
    tour: dict[str, Any],
    to: dict[str, Any],
) -> bool:
    allowed = _reference_filter_values(reference_filter)
    if not allowed:
        return True
    if ref6.strip().upper() in allowed:
        return True
    if not (allowed & POST_REFERENCE_ALIASES):
        return False
    tour_mc, truck_mc = _tour_carrier_matchcodes(tour)
    to_mc = ((to.get("carrier") or {}).get("matchcode") or "").strip()
    return _carrier_indicates_post(tour_mc, truck_mc, to_mc)


@dataclass
class Address:
    name1: str
    street: str
    zip_code: str
    city: str
    country: str
    email: str | None = None
    name2: str | None = None


@dataclass
class ShipmentDraft:
    tour_number: int | str
    transport_order_number: int
    item_number: int
    carrier_matchcode: str
    consignment_reference: str
    item_id: str
    recipient: Address
    sender: Address
    weight_grams: int
    packstuecke: int = 1
    content: str = ""
    external_number: str = ""
    external_order_number: str = ""
    consignment_number: str = ""
    sendungsnummer: str = ""
    przl: list[str] | None = None
    notify_recipient: bool = False
    recipient_matchcode: str = ""
    recipient_bp_id: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


def _pascal_to_camel(key: str) -> str:
    if not key:
        return key
    return key[0].lower() + key[1:]


def _normalize_node(obj: Any) -> Any:
    if isinstance(obj, list):
        return [_normalize_node(x) for x in obj]
    if isinstance(obj, dict):
        return {_pascal_to_camel(k): _normalize_node(v) for k, v in obj.items()}
    return obj


def coerce_tour_document(data: dict[str, Any]) -> dict[str, Any]:
    """Accept wrapped {header,tour} exports and flat PascalCase Soloplan tour JSON."""
    if data.get("tour"):
        return data
    if "TourNumber" in data or "TransportOrders" in data:
        tour = _normalize_node(data)
        export_ref = str(tour.get("id") or tour.get("tourNumber") or "").strip()
        return {
            "header": {
                "exportItemReference": export_ref,
                "sendDate": tour.get("plannedStartTime"),
            },
            "tour": [tour],
        }
    return data


def _street(addr: dict[str, Any]) -> str:
    street = (addr.get("street") or "").strip()
    house = (addr.get("houseNumber") or "").strip()
    return combine_street_house(street, house)


def _country(addr: dict[str, Any]) -> str:
    c = addr.get("country") or {}
    return (c.get("isoTwoCharacterCountryCode") or c.get("countryId") or "CH").strip()


def _name2_from(obj: dict[str, Any]) -> str | None:
    name2 = (obj.get("name2") or "").strip()
    if name2:
        return name2[:35]
    obp = obj.get("originalBusinessPartner") or {}
    bp_name2 = (obp.get("name2") or "").strip()
    if bp_name2:
        return bp_name2[:35]
    contact = obp.get("mainContactPerson") or {}
    first = (contact.get("firstName") or "").strip()
    last = (contact.get("lastName") or "").strip()
    contact_name = f"{first} {last}".strip()
    if contact_name:
        return contact_name[:35]
    return None


def _bp_address(bp: dict[str, Any] | None) -> Address | None:
    if not bp:
        return None
    main = bp.get("mainAddress") or bp.get("address") or {}
    name1 = (bp.get("name1") or "").strip()
    if not name1:
        return None
    return Address(
        name1=name1,
        street=_street(main),
        zip_code=(main.get("zipCode") or "").strip(),
        city=(main.get("location1") or main.get("city") or "").strip(),
        country=_country(main),
        email=_extract_email(bp),
        name2=_name2_from(bp),
    )


def _point_address(point: dict[str, Any] | None) -> Address | None:
    if not point:
        return None
    addr = point.get("address") or point.get("mainAddress") or {}
    name1 = (point.get("name1") or "").strip()
    if not name1 and not addr:
        return None
    if not name1:
        name1 = "Unbekannt"
    return Address(
        name1=name1,
        street=_street(addr),
        zip_code=(addr.get("zipCode") or "").strip(),
        city=(addr.get("location1") or addr.get("city") or "").strip(),
        country=_country(addr),
        email=_extract_email(point),
        name2=_name2_from(point),
    )


def _is_wog(name: str) -> bool:
    return bool(WOG_NAME_RE.search(name or ""))


def _extract_email(obj: dict[str, Any]) -> str | None:
    if not obj:
        return None
    for key in ("email", "emailAddress", "businessEmailAddress", "receiverEmail", "infoEmail"):
        val = (obj.get(key) or "").strip()
        if val and "@" in val:
            return val
    obp = obj.get("originalBusinessPartner") or {}
    val = (obp.get("businessEmailAddress") or obp.get("emailAddress") or "").strip()
    if val and "@" in val:
        return val
    contact = obp.get("mainContactPerson") or {}
    val = (contact.get("emailAddress") or contact.get("email") or "").strip()
    if val and "@" in val:
        return val
    info = obj.get("information") or {}
    for key in ("receiverEmail", "email", "infoEmail", "emailAddress"):
        val = (info.get(key) or "").strip()
        if val and "@" in val:
            return val
    return None


def _recipient_email(to: dict[str, Any], recipient: Address | None) -> str | None:
    if recipient and recipient.email:
        return recipient.email
    cons = to.get("consignment") or {}
    order = cons.get("order") or {}
    for source in (
        to.get("receiver"),
        to.get("differentDeliveryPoint"),
        cons,
        order,
        to,
    ):
        email = _extract_email(source or {})
        if email:
            return email
    return None


def _with_recipient_email(to: dict[str, Any], recipient: Address | None) -> Address | None:
    if not recipient:
        return None
    email = _recipient_email(to, recipient)
    if email == recipient.email:
        return recipient
    return Address(
        name1=recipient.name1,
        street=recipient.street,
        zip_code=recipient.zip_code,
        city=recipient.city,
        country=recipient.country,
        email=email,
        name2=recipient.name2,
    )


def _resolve_sender(to: dict[str, Any]) -> Address:
    cfg_fallback = Address(
        name1="WOG Logistics AG",
        street="Wildenaustraße 22",
        zip_code="9444",
        city="Diepoldsau",
        country="CH",
    )
    candidates: list[Address | None] = [
        _point_address(to.get("differentLoadingPoint")),
        _point_address(to.get("sender")),
        _bp_address((to.get("sender") or {}).get("originalBusinessPartner")),
        _bp_address(((to.get("consignment") or {}).get("order") or {}).get("customer")),
        _point_address(to.get("sender")),
    ]
    for cand in candidates:
        if cand and cand.name1 and not _is_wog(cand.name1):
            return cand
    sender = _point_address(to.get("sender"))
    if sender and sender.name1:
        return sender
    return cfg_fallback



def _recipient_bp_ref(to: dict[str, Any]) -> tuple[str, str]:
    """Soloplan-Kundenreferenz: Matchcode + businessPartnerId vom Empfänger."""
    for key in ("differentDeliveryPoint", "receiver"):
        point = to.get(key) or {}
        obp = point.get("originalBusinessPartner") or {}
        if not isinstance(obp, dict):
            continue
        mc = (obp.get("matchcode") or "").strip().upper()
        bp = obp.get("businessPartnerId")
        bp_s = str(bp).strip() if bp is not None and str(bp).strip() else ""
        if mc or bp_s:
            return mc, bp_s
    return "", ""


def _resolve_recipient(to: dict[str, Any]) -> Address | None:
    candidates: list[Address | None] = []
    for key in ("differentDeliveryPoint", "receiver"):
        point = to.get(key) or {}
        candidates.append(_point_address(point))
        candidates.append(_bp_address(point.get("originalBusinessPartner")))
    for addr in candidates:
        if addr and addr.zip_code and addr.city:
            return addr
    for addr in candidates:
        if addr and addr.city:
            return addr
    return None


def _kg_to_grams(val: Any) -> int | None:
    if val is None:
        return None
    if isinstance(val, dict):
        val = val.get("value") or val.get("amount")
    if val is None:
        return None
    try:
        grams = float(val) * 1000
        if grams <= 0:
            return None
        return max(1, int(round(grams)))
    except (TypeError, ValueError):
        return None


def _weight_from_dict(weights: dict[str, Any] | None) -> int | None:
    if not weights:
        return None
    for key in (
        "effectiveWeightInKilogram",
        "carrierWeightInKilogram",
        "freightWeightInKilogram",
        "grossWeightInKilogram",
    ):
        grams = _kg_to_grams(weights.get(key))
        if grams:
            return grams
    return None


def _weight_grams(item: dict[str, Any], to: dict[str, Any], default: int) -> int:
    for source in (
        item.get("weights"),
        to.get("weights"),
        (to.get("consignment") or {}).get("weights"),
    ):
        grams = _weight_from_dict(source or {})
        if grams:
            return grams
    return default


def _packstuecke(item: dict[str, Any], to: dict[str, Any]) -> int:
    for source in (item.get("quantity"), to.get("quantity")):
        if source is None:
            continue
        try:
            qty = int(round(float(source)))
            if qty >= 1:
                return qty
        except (TypeError, ValueError):
            pass
    return 1


def _item_id(item: dict[str, Any], to_number: int, item_number: int) -> str:
    sscc = item.get("consignmentItem") or {}
    for entry in sscc.get("ssccCurrents") or []:
        code = (entry.get("code") or "").strip()
        if code:
            return code
    return f"{to_number}-{item_number}"


def extract_sendungsnummer(order: dict | None, cons: dict | None = None) -> str:
    """Soloplan: order.sendungsnummer bevorzugt, sonst order.number."""
    order = order or {}
    cons = cons or {}
    for src in (order, cons):
        for key in (
            "sendungsnummer",
            "sendungsNummer",
            "Sendungsnummer",
            "shipmentNumber",
            "shipmentNo",
        ):
            val = str(src.get(key) or "").strip()
            if val:
                return val[:50]
    for key in ("number", "Number"):
        val = str(order.get(key) or "").strip()
        if val:
            return val[:50]
    return ""


def parse_tour_json(data: dict[str, Any], *, reference_filter: str = "POST", carrier_filter: str = "", default_weight: int = 1000) -> tuple[dict[str, Any], list[ShipmentDraft]]:
    data = coerce_tour_document(data)
    tours = data.get("tour") or []
    if not tours:
        raise ValueError("Keine Tour in JSON gefunden")
    tour = tours[0]
    tour_number = tour.get("tourNumber") or tour.get("extTourNumber") or "?"
    carrier = tour.get("carrier") or {}
    carrier_matchcode = (carrier.get("matchcode") or "").strip()
    if not carrier_matchcode:
        carrier_matchcode = ((tour.get("truck") or {}).get("matchcode") or "").strip()
    if carrier_filter and carrier_matchcode.upper() != carrier_filter:
        return {"tourNumber": tour_number, "skipped": "carrier_filter"}, []

    out: list[ShipmentDraft] = []
    for to in tour.get("transportOrders") or []:
        cons = to.get("consignment") or {}
        custom = cons.get("customTypeValues") or {}
        ref6 = (custom.get("consignmentReference6") or "").strip().upper()
        if not _matches_post_shipment(ref6, reference_filter, tour, to):
            continue
        effective_ref = _post_consignment_reference(ref6, tour, to)
        recipient = _with_recipient_email(to, _resolve_recipient(to))
        if not recipient or not recipient.zip_code:
            continue
        sender = _resolve_sender(to)
        to_number = int(to.get("transportOrderNumber") or 0)
        order = cons.get("order") or {}
        sendungsnummer = extract_sendungsnummer(order, cons)
        for item in to.get("transportOrderItems") or []:
            item_number = int(item.get("itemNumber") or 1)
            recip_mc, recip_bp = _recipient_bp_ref(to)
            out.append(
                ShipmentDraft(
                    tour_number=tour_number,
                    transport_order_number=to_number,
                    item_number=item_number,
                    carrier_matchcode=carrier_matchcode,
                    consignment_reference=effective_ref,
                    item_id=_item_id(item, to_number, item_number),
                    recipient=recipient,
                    sender=sender,
                    weight_grams=_weight_grams(item, to, default_weight),
                    packstuecke=_packstuecke(item, to),
                    content=(item.get("content1") or "").strip(),
                    external_number=(cons.get("externalNumber") or "").strip(),
                    external_order_number=(order.get("externalNumber") or "").strip(),
                    consignment_number=str(cons.get("number") or "").strip(),
                    sendungsnummer=sendungsnummer,
                    recipient_matchcode=recip_mc,
                    recipient_bp_id=recip_bp,
                    raw={"transportOrder": to, "item": item},
                )
            )
    meta = {
        "tourNumber": tour_number,
        "extTourNumber": tour.get("extTourNumber"),
        "carrierMatchcode": carrier_matchcode,
        "exportReference": (data.get("header") or {}).get("exportItemReference"),
        "sendDate": (data.get("header") or {}).get("sendDate"),
        "plannedStartTime": tour.get("plannedStartTime"),
        "shipmentCount": len(out),
    }
    return meta, out
