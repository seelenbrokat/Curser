from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import date
from typing import Callable

from .client import EzollClient, ScreenSnapshot

BUERGSCHAFT_RE = re.compile(
    r"([\d.]+,\d{2})\s*EUR\s*B(?:ue|u|ü)rgschaft",
    re.IGNORECASE,
)


@dataclass
class BuergschaftResult:
    amount: str
    screen: ScreenSnapshot
    pages: int


def default_datum_von(months_back: int = 6) -> str:
    """AS400-Datum YYYYMMDD, Standard: heute minus N Monate."""
    today = date.today()
    month = today.month - months_back
    year = today.year
    while month <= 0:
        month += 12
        year -= 1
    day = min(today.day, _days_in_month(year, month))
    return date(year, month, day).strftime("%Y%m%d")


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        nxt = date(year + 1, 1, 1)
    else:
        nxt = date(year, month + 1, 1)
    return (nxt - date(year, month, 1)).days


def extract_buergschaft(text: str) -> str | None:
    match = BUERGSCHAFT_RE.search(text)
    return match.group(1) if match else None


def query_buergschaft(
    client: EzollClient,
    *,
    firma: str,
    msgty: str = "CC015C",
    datum_von: str | None = None,
    msgty_tabs: int = 1,
    max_pages: int = 80,
    settle_ms: int = 800,
    on_step: Callable[[str, ScreenSnapshot], None] | None = None,
) -> BuergschaftResult:
    """
    Arbeitsschritte laut PDF „Abfrage Bürgschaft“:

    1. Login (inkl. ggf. IBM-Anmelden)
    2. Firmennummer + Enter
    3. 2 (Andere Zollverfahren) + Enter
    4. 12 (Archiv/Evidenz) + Enter
    5. Datum von + MsgTy CC015C, Enter, F10
    6. Bild-ab bis letzte Seite → Gesamtbelastung … EUR Bürgschaft
    """
    datum = datum_von or default_datum_von(6)

    def step(label: str) -> ScreenSnapshot:
        time.sleep(settle_ms / 1000)
        snap = client.read_screen(save=True)
        if on_step:
            on_step(label, snap)
        return snap

    # 1) Web-Login + optional IBM-Signon-Screen
    client.login()
    step("01-after-web-login")
    _maybe_ibm_signon(client)
    step("01b-after-ibm-signon")

    # 2) Firmennummer
    _wait_for(client, r"Firmennummer|MN0001", timeout_s=20)
    client.send_keys(f"text:{firma}")
    client.send_keys("Enter")
    step("02-firmennummer")

    # 3) Andere Zollverfahren
    client.send_keys("text:2")
    client.send_keys("Enter")
    step("03-andere-zollverfahren")

    # 4) Archiv/Evidenz
    _wait_for(client, r"Andere Zollverfahren|Auswahl", timeout_s=15)
    client.send_keys("text:12")
    client.send_keys("Enter")
    step("04-archiv-evidenz")

    # 5) Filter setzen
    _wait_for(client, r"Archiv/Evidenz|Z01015|MsgTy|Datum", timeout_s=20)
    # Cursor typischerweise im Filterbereich; Datum tippen, zu MsgTy tabben.
    client.send_keys(f"text:{datum}")
    for _ in range(max(0, msgty_tabs)):
        client.send_keys("Tab")
    client.send_keys(f"text:{msgty}")
    client.send_keys("Enter")
    time.sleep(0.5)
    client.send_keys("F10")
    step("05-filter-applied")

    # 6) Bis zur letzten Seite blättern („Weitere…“ weg / Betrag stabil)
    pages = 0
    last_text = ""
    stable_hits = 0
    while pages < max_pages:
        snap = client.read_screen(save=False)
        text = snap.text
        has_more = _has_more_pages(text)
        amount = extract_buergschaft(text)
        if not has_more and amount:
            break
        if text == last_text:
            stable_hits += 1
            if stable_hits >= 2 and not has_more:
                break
        else:
            stable_hits = 0
        last_text = text
        client.send_keys("PageDown")
        pages += 1
        time.sleep(settle_ms / 1000)

    final = step("06-last-page")
    amount = extract_buergschaft(final.text)
    if not amount:
        raise RuntimeError(
            "Bürgschaft-Betrag nicht gefunden. "
            "Bitte artifacts/06-last-page* und screen-*.txt prüfen "
            "(Tab-Reihenfolge ggf. via EZOLL_MSGTY_TABS anpassen)."
        )
    return BuergschaftResult(amount=amount, screen=final, pages=pages)


def _maybe_ibm_signon(client: EzollClient) -> None:
    """Falls nach dem Web-Login noch der IBM-Anmelden-Screen kommt."""
    snap = client.read_screen(save=False)
    text = snap.text.lower()
    if not any(token in text for token in ("anmelden", "kennwort", "benutzer")):
        return
    # Schon im Anwendungsmenü? Dann nicht erneut anmelden.
    if "firmennummer" in text or "mn0001" in text.lower():
        return
    if "ezollon" in text and "firmennummer" in text:
        return

    client.send_keys(f"text:{client.settings.user}")
    client.send_keys("Tab")
    client.send_keys(f"text:{client.settings.password}")
    client.send_keys("Enter")
    time.sleep(1.5)


def _wait_for(client: EzollClient, pattern: str, timeout_s: float = 15.0) -> None:
    deadline = time.time() + timeout_s
    regex = re.compile(pattern, re.IGNORECASE)
    while time.time() < deadline:
        snap = client.read_screen(save=False)
        if regex.search(snap.text):
            return
        time.sleep(0.4)
    # Nicht hart abbrechen – Navigation trotzdem versuchen.
    print(f"Hinweis: Screen-Muster nicht sicher erkannt: {pattern}")


def _has_more_pages(text: str) -> bool:
    # „Weitere…“ = es gibt Folgeseiten. „F3=Ende“ ist nur ein Funktionstasten-Hint.
    return bool(re.search(r"Weitere\s*(\.\.\.|…)", text, re.IGNORECASE))
