from __future__ import annotations

import re
from typing import Any

_STREET_NR = re.compile(r"^(.+?)\s+(\d+\w*)\s*$")
# "Grabenstrasse 1 1" / "Gillstrasse 12a 12a"
_DUP_HOUSE = re.compile(r"^(.+?)\s+(\d+[a-zA-Z]?)(?:\s+\2)+\s*$", re.IGNORECASE)
_TRAILING_HOUSE = re.compile(r"(\d+[a-zA-Z]?)\s*$")


def collapse_duplicate_house(street: str) -> str:
    """Entfernt doppelte Hausnummer am Ende: 'Strasse 1 1' → 'Strasse 1'."""
    street = (street or "").strip()
    m = _DUP_HOUSE.match(street)
    if m:
        return f"{m.group(1)} {m.group(2)}".strip()
    return street


def combine_street_house(street: str, house: str | None) -> str:
    """Soloplan street + houseNumber ohne Doppelung.

    Soloplan liefert ab und zu street='Grabenstrasse 1' und houseNumber='1'.
    """
    street = (street or "").strip()
    house = (house or "").strip()
    if not house:
        return collapse_duplicate_house(street)
    if not street:
        return house
    # Hausnummer steht bereits am Ende der Strasse
    if re.search(rf"(?:^|[\s,/.-]){re.escape(house)}\s*$", street, flags=re.IGNORECASE):
        return street
    m = _TRAILING_HOUSE.search(street)
    if m:
        existing = m.group(1)
        el, hl = existing.lower(), house.lower()
        # street spezieller ('1a') als house ('1') → street behalten
        if el.startswith(hl) and len(el) > len(hl):
            return street
        # house spezieller ('1a') als street-Ende ('1') → ersetzen
        if hl.startswith(el) and len(hl) > len(el):
            return street[: m.start(1)] + house
    return collapse_duplicate_house(f"{street} {house}".strip())


def split_street_house(street: str) -> tuple[str, str]:
    street = collapse_duplicate_house(street or "")
    if not street:
        return "", ""
    m = _STREET_NR.match(street)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return street, ""


def build_post_validation_request(
    *,
    name1: str,
    name2: str | None,
    street: str,
    zip_code: str,
    city: str,
    country: str = "CH",
    full_validation: bool = True,
) -> dict[str, Any]:
    street_name, house_number = split_street_house(street)
    payload: dict[str, Any] = {
        "geographicLocation": {
            "house": {
                "street": street_name,
                "houseNumber": house_number,
                "additionalAddress": (name2 or "").strip(),
            },
            "zip": {
                "zip": (zip_code or "").strip(),
                "city": (city or "").strip(),
            },
        },
        "logisticLocation": {"postBoxNumber": ""},
        "fullValidation": full_validation,
    }
    if country:
        payload["geographicLocation"]["country"] = country.strip()[:2]
    name1 = (name1 or "").strip()
    name2_clean = (name2 or "").strip()
    if name1 or name2_clean:
        addressee: dict[str, str] = {}
        if name1:
            addressee["companyName"] = name1[:35]
        if name2_clean:
            addressee["firstName"] = name2_clean[:35]
        payload["addressee"] = addressee
    return payload


def extract_validated_recipient(response: dict[str, Any]) -> dict[str, str] | None:
    addr = response.get("address") or {}
    geo = addr.get("geographicLocation") or {}
    house = geo.get("house") or {}
    zip_part = geo.get("zip") or {}
    addressee = addr.get("addressee") or {}

    street = (house.get("street") or "").strip()
    nr = (house.get("houseNumber") or "").strip()
    street_line = combine_street_house(street, nr)
    zip_code = (zip_part.get("zip") or "").strip()
    city = (zip_part.get("city") or "").strip()
    if not street_line and not zip_code:
        return None

    name1 = (addressee.get("companyName") or addressee.get("lastName") or "").strip()
    name2 = (addressee.get("firstName") or house.get("additionalAddress") or "").strip()
    if addressee.get("firstName") and addressee.get("lastName"):
        name1 = (addressee.get("lastName") or "").strip()
        name2 = (addressee.get("firstName") or "").strip()

    out: dict[str, str] = {
        "street": street_line,
        "zip_code": zip_code,
        "city": city,
    }
    if name1:
        out["name1"] = name1
    if name2:
        out["name2"] = name2
    return out


def merge_suggested_recipient(recipient: "Address", suggested: dict[str, str]) -> "Address":
    from app.soloplan_parser import Address

    def pick(key: str, current: str | None) -> str | None:
        if key not in suggested:
            return current
        val = (suggested.get(key) or "").strip()
        return val or current

    return Address(
        name1=pick("name1", recipient.name1) or recipient.name1,
        name2=pick("name2", recipient.name2),
        street=pick("street", recipient.street) or recipient.street,
        zip_code=pick("zip_code", recipient.zip_code) or recipient.zip_code,
        city=pick("city", recipient.city) or recipient.city,
        country=recipient.country,
        email=recipient.email,
    )


def recipient_differs(original: dict[str, str], suggested: dict[str, str]) -> bool:
    keys = ("name1", "name2", "street", "zip_code", "city")
    for key in keys:
        a = (original.get(key) or "").strip().casefold()
        b = (suggested.get(key) or "").strip().casefold()
        if a != b:
            return True
    return False
