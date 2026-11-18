from __future__ import annotations

from typing import Any

# Schweizer Post przl-Kombinationen (Barcode API / Handbuch)
# Standard ist "eco" – Signature nie Default.
DELIVERY_PRODUCTS: list[dict[str, Any]] = [
    {
        "id": "eco",
        "label": "PostPac Economy (Standard)",
        "przl": ["ECO"],
        "group": "Standard",
        "description": "Günstigere Economy-Zustellung, etwas längere Laufzeit als Priority. Keine Unterschrift erforderlich.",
    },
    {
        "id": "pri",
        "label": "PostPac Priority",
        "przl": ["PRI"],
        "group": "Standard",
        "description": "Schnellere Priority-Zustellung, in der Regel am nächsten Werktag. Keine Unterschrift erforderlich.",
    },
    {
        "id": "sem",
        "label": "Swiss-Express Moon",
        "przl": ["SEM"],
        "group": "Express",
        "description": "Expresszustellung am nächsten Werktag am Morgen (Moon). Für zeitkritische Sendungen.",
    },
    {
        "id": "skb",
        "label": "SameDay (Nachmittag/Abend)",
        "przl": ["SKB"],
        "group": "Express",
        "description": "SameDay-Zustellung am Nachmittag oder Abend (je nach Abgabezeit und Gebiet).",
    },
    {
        "id": "pri_0912",
        "label": "Priority · Zustellung 09:00–12:00",
        "przl": ["PRI", "ZFZ0912"],
        "group": "Zeitfenster",
        "description": "PostPac Priority mit gewünschtem Zustellfenster 09:00–12:00 Uhr.",
    },
    {
        "id": "pri_1114",
        "label": "Priority · Zustellung 11:00–14:00",
        "przl": ["PRI", "ZFZ1114"],
        "group": "Zeitfenster",
        "description": "PostPac Priority mit gewünschtem Zustellfenster 11:00–14:00 Uhr.",
    },
    {
        "id": "pri_sa",
        "label": "Priority + Samstagszustellung",
        "przl": ["PRI", "SA"],
        "group": "Zusatz",
        "description": "Priority inkl. Samstagszustellung (SA). Zustellung auch am Samstag möglich.",
    },
    {
        "id": "pri_si",
        "label": "Priority + Signature (Unterschrift)",
        "przl": ["PRI", "SI"],
        "group": "Unterschrift",
        "description": (
            "PostPac Priority mit Zusatzleistung Signature (SI). "
            "Übergabe nur gegen Unterschrift (ausser Zustellgenehmigung des Empfängers). "
            "Haftung der Post bis CHF 1'500 bei Verlust/Beschädigung/Diebstahl. "
            "Nicht Standard – nur bei Bedarf wählen."
        ),
    },
    {
        "id": "eco_si",
        "label": "Economy + Signature (Unterschrift)",
        "przl": ["ECO", "SI"],
        "group": "Unterschrift",
        "description": (
            "PostPac Economy mit Signature (SI). Unterschrift bei Übergabe, "
            "günstigere Grundzustellung als Priority. Haftung bis CHF 1'500."
        ),
    },
    {
        "id": "pri_as",
        "label": "Priority + Assurance",
        "przl": ["PRI", "AS"],
        "group": "Unterschrift",
        "description": (
            "Priority mit Assurance (AS): Zustellung gegen Unterschrift und höhere Haftung "
            "bis CHF 5'000. Für besonders wertvolle Sendungen."
        ),
    },
    {
        "id": "pri_rmp",
        "label": "Priority + Persönliche Übergabe",
        "przl": ["PRI", "RMP"],
        "group": "Unterschrift",
        "description": (
            "Priority mit persönlicher Übergabe (RMP): Zustellung nur an die namentlich "
            "angegebene Person (nicht an Nachbarn/Haushalt ohne diese Person)."
        ),
    },
]

_DEFAULT = next(p for p in DELIVERY_PRODUCTS if p["id"] == "eco")  # PostPac Economy ohne Signature


FAQ_ITEMS: list[dict[str, str]] = [
    {
        "q": "Was passiert in shipping.NET bei Zustellung?",
        "a": (
            "Wenn die Post eine Sendung als zugestellt meldet (stündlicher Sync), setzt WOG Connect "
            "automatisch in OnDot/shipping.NET den Status DVD (Zugestellt). "
            "Die Sendungsnummer ist {Auftragsnummer}.{ConsignmentNumber}, z. B. 435958.1 – "
            "gleicher Schlüssel wie beim Ablieferbeleg-Dateinamen."
        ),
    },

    {
        "q": "Was ist der Standard bei der Zustellart?",
        "a": (
            "Standard ist «PostPac Economy» ohne Unterschrift. Signature und andere "
            "Zusatzleistungen werden nur verwendet, wenn du sie bei der Sendung explizit auswählst."
        ),
    },
    {
        "q": "Was bedeutet Signature (Unterschrift)?",
        "a": (
            "Die Zusatzleistung Signature (Code SI) verlangt bei der Zustellung eine Unterschrift "
            "des Empfängers (ausser es liegt eine Zustellgenehmigung vor). Zusätzlich haftet die "
            "Post im Schadenfall bis CHF 1'500. Wählbar als «Priority + Signature» oder "
            "«Economy + Signature»."
        ),
    },
    {
        "q": "Was ist der Unterschied zwischen Signature und Assurance?",
        "a": (
            "Beide verlangen eine Unterschrift. Signature haftet bis CHF 1'500, Assurance "
            "(Code AS) bis CHF 5'000 – geeignet für höherwertige Güter."
        ),
    },
    {
        "q": "Was bedeutet persönliche Übergabe (RMP)?",
        "a": (
            "Die Sendung darf nur an die namentlich bestimmte Person übergeben werden – "
            "nicht an andere Haushaltsmitglieder oder Nachbarn."
        ),
    },
    {
        "q": "Priority vs. Economy?",
        "a": (
            "Priority ist die schnellere Standardzustellung (meist nächster Werktag). "
            "Economy ist günstiger und braucht in der Regel etwas länger."
        ),
    },
    {
        "q": "Was sind Zeitfenster (09–12 / 11–14)?",
        "a": (
            "Zusatzleistungen der Post für eine gewünschte Zustellung in einem bestimmten "
            "Zeitfenster am Liefertag. Verfügbarkeit hängt vom Zustellgebiet ab."
        ),
    },
    {
        "q": "Wann erhalte ich einen Ablieferbeleg?",
        "a": (
            "Sobald die Post die Sendung als zugestellt meldet, kann der digitale "
            "Zustellnachweis erzeugt werden. Bei Signature/Assurance ist die Unterschrift "
            "bei der Post hinterlegt; der offizielle Scan kann trotzdem verzögert eintreffen."
        ),
    },
    {
        "q": "Wie hole ich Ablieferbelege per SFTP ab?",
        "a": (
            "Zugestellte Sendungen werden automatisch als PDF abgelegt unter "
            "/delivery_proofs/ mit dem Namen {Auftragsnummer}.{ConsignmentNumber}.pdf "
            "(Beispiel: 435958.1.pdf)."
        ),
    },
]


def list_delivery_products() -> list[dict[str, Any]]:
    return DELIVERY_PRODUCTS


def list_faq() -> list[dict[str, str]]:
    return FAQ_ITEMS


def get_delivery_product(product_id: str | None) -> dict[str, Any]:
    if not product_id:
        return _DEFAULT
    for p in DELIVERY_PRODUCTS:
        if p["id"] == product_id:
            return p
    return _DEFAULT


def przl_for_product(product_id: str | None) -> list[str]:
    return list(get_delivery_product(product_id)["przl"])
