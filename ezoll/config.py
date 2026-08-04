from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = ROOT / "artifacts"


@dataclass(frozen=True)
class Settings:
    url: str
    user: str
    password: str
    headed: bool
    channel: str | None
    firma: str
    msgty: str
    datum_von: str | None
    msgty_tabs: int
    timeout_ms: int = 30_000


def load_settings() -> Settings:
    load_dotenv(ROOT / ".env")
    user = os.getenv("EZOLL_USER", "").strip()
    password = os.getenv("EZOLL_PASSWORD", "").strip()
    if not user or not password:
        raise SystemExit(
            "Fehlende Zugangsdaten. Bitte .env aus .env.example anlegen "
            "und EZOLL_USER / EZOLL_PASSWORD setzen."
        )
    headed = os.getenv("EZOLL_HEADED", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    channel = os.getenv("EZOLL_CHANNEL", "").strip() or None
    datum_von = os.getenv("EZOLL_DATUM_VON", "").strip() or None
    try:
        msgty_tabs = int(os.getenv("EZOLL_MSGTY_TABS", "1").strip() or "1")
    except ValueError as exc:
        raise SystemExit("EZOLL_MSGTY_TABS muss eine Ganzzahl sein.") from exc
    return Settings(
        url=os.getenv(
            "EZOLL_URL", "https://zoll.ldv.at/ts/ts2/start_new.html"
        ).strip(),
        user=user,
        password=password,
        headed=headed,
        channel=channel,
        firma=os.getenv("EZOLL_FIRMA", "100").strip() or "100",
        msgty=os.getenv("EZOLL_MSGTY", "CC015C").strip() or "CC015C",
        datum_von=datum_von,
        msgty_tabs=msgty_tabs,
    )
