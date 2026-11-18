from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

import requests

# "delivered" nur als eigenstaendiges Wort – sonst trifft TO_BE_DELIVERED faelschlich zu
_DELIVERED_RE = re.compile(
    r"(zugestellt|ausgeliefert|erfolgreich zugestellt|item delivered|distribution successful|(?<![a-z_])delivered(?![a-z_]))",
    re.I,
)
_HANDED_OVER_RE = re.compile(
    r"(annahme|accepted|in transport|transport|sortierung|distribution|unterwegs|departed|arrived at hub|elektronisch|to[_\s-]?be[_\s-]?delivered)",
    re.I,
)

# EKP globalStatus → Anzeige / interner Status
_GLOBAL_STATUS_LABELS = {
    "REPORTED": "Elektronisch gemeldet",
    "ANNOUNCED": "Elektronisch gemeldet",
    "PREADVICED": "Elektronisch gemeldet",
    "IN_TRANSIT": "Unterwegs",
    "INTRANSIT": "Unterwegs",
    "TRANSPORT": "Unterwegs",
    "TO_BE_DELIVERED": "Zur Zustellung bereit",
    "READY_FOR_DELIVERY": "Zur Zustellung bereit",
    "DISTRIBUTION": "In Zustellung",
    "OUT_FOR_DELIVERY": "In Zustellung",
    "DELIVERED": "Zugestellt",
    "RETURNED": "Retourniert",
    "NOT_DELIVERED": "Nicht zugestellt",
    "UNKNOWN": "Status unbekannt",
}

_GLOBAL_STATUS_MAP = {
    "REPORTED": "label_created",
    "ANNOUNCED": "label_created",
    "PREADVICED": "label_created",
    "IN_TRANSIT": "handed_over",
    "INTRANSIT": "handed_over",
    "TRANSPORT": "handed_over",
    "TO_BE_DELIVERED": "handed_over",
    "READY_FOR_DELIVERY": "handed_over",
    "DISTRIBUTION": "handed_over",
    "OUT_FOR_DELIVERY": "handed_over",
    "DELIVERED": "delivered",
}


def primary_identcode(identcode: str | None) -> str:
    raw = (identcode or "").strip()
    if not raw:
        return ""
    return raw.split(",")[0].strip()


def tracking_url(identcode: str | None, *, lang: str = "de") -> str | None:
    """Offizielle Post Track&Trace-URL – Nummer steht im Pfad nach Redirect."""
    raw = (identcode or "").strip()
    codes = [x.strip() for x in raw.split(",") if x.strip()][:10]
    if not codes:
        return None
    # www.post.ch/swisspost-tracking → service.post.ch/ekp-web/ui/entry/search/{code}
    # (Query-Param auf /ui/tracking wird von der Post-UI oft ignoriert)
    joined = ",".join(codes)
    return f"https://www.post.ch/swisspost-tracking?formattedParcelCodes={quote(joined, safe=',')}"


def global_status_label(global_status: str | None, *, product_status: str | None = None) -> str:
    key = (global_status or "").strip().upper()
    if key in _GLOBAL_STATUS_LABELS:
        return _GLOBAL_STATUS_LABELS[key]
    # Fallback aus Produkt-Statuscode, z. B. PARCEL.*.2.1
    code = (product_status or "").strip()
    if code.endswith(".1") or code.endswith(".2.1"):
        return "Elektronisch gemeldet"
    if code.endswith(".2.3") or code.endswith(".3"):
        return "Zur Zustellung bereit"
    if key:
        return f"Status: {key}"
    return ""


class TrackingClient:
    """Post Sendungsverfolgung ueber die oeffentliche EKP-API (Track-Scope bei WOG noch nicht freigeschaltet)."""

    BASE = "https://service.post.ch/ekp-web/api"

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": "WOG-Connect/1.0",
                "Accept": "application/json",
            }
        )
        self._user_id: str | None = None
        self._api_headers: dict[str, str] | None = None

    def _reset_session(self) -> None:
        self._user_id = None
        self._api_headers = None
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": "WOG-Connect/1.0",
                "Accept": "application/json",
            }
        )

    def _bootstrap(self, *, force: bool = False) -> tuple[str, dict[str, str]]:
        if not force and self._user_id and self._api_headers:
            return self._user_id, self._api_headers
        if force:
            self._reset_session()
        r = self._session.get(f"{self.BASE}/user", timeout=30)
        r.raise_for_status()
        self._user_id = str(r.json().get("userIdentifier") or "")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        csrf = r.headers.get("X-CSRF-TOKEN") or r.headers.get("x-csrf-token")
        if csrf:
            headers["X-CSRF-TOKEN"] = csrf
        self._api_headers = headers
        return self._user_id, headers

    def fetch_events(self, identcode: str) -> list[dict[str, Any]]:
        info = self.fetch_shipment_info(identcode)
        return info.get("raw_events") or []

    def fetch_shipment_info(self, identcode: str) -> dict[str, Any]:
        identcode = primary_identcode(identcode)
        if not identcode:
            return {}
        return self._fetch_shipment_info_once(identcode, retry_auth=True)

    def _fetch_shipment_info_once(self, identcode: str, *, retry_auth: bool) -> dict[str, Any]:
        uid, headers = self._bootstrap()
        r = self._session.post(
            f"{self.BASE}/history?userId={uid}",
            json={"searchQuery": identcode},
            headers=headers,
            timeout=30,
        )
        if r.status_code in {401, 403} and retry_auth:
            self._bootstrap(force=True)
            return self._fetch_shipment_info_once(identcode, retry_auth=False)
        if r.status_code == 404:
            return {}
        r.raise_for_status()
        search_hash = r.json().get("hash")
        if not search_hash:
            return {}
        r2 = self._session.get(
            f"{self.BASE}/history/not-included/{search_hash}?userId={uid}",
            headers=headers,
            timeout=30,
        )
        if r2.status_code in {401, 403} and retry_auth:
            self._bootstrap(force=True)
            return self._fetch_shipment_info_once(identcode, retry_auth=False)
        if r2.status_code == 404:
            return {}
        r2.raise_for_status()
        items = r2.json()
        if not isinstance(items, list) or not items:
            return {}
        item = items[0] if isinstance(items[0], dict) else {}
        raw_events = self._fetch_events_by_identity(item.get("identity"), headers)
        # EKP liefert Events oft leer / 404 – dann Status aus dem Stammdatensatz ableiten
        if not raw_events and isinstance(item.get("events"), list):
            raw_events = [ev for ev in item["events"] if isinstance(ev, dict)]
        global_status = (item.get("globalStatus") or "").strip()
        product_status = (item.get("status") or "").strip()
        summary = global_status_label(global_status, product_status=product_status)
        # EKP liefert oft keine Event-Liste – Timeline aus bekannten Zeitstempeln aufbauen
        if not raw_events:
            raw_events = TrackingClient._milestone_events(item, global_status, product_status, summary)
        gs = global_status.upper()
        delivered = bool(item.get("delivered")) or gs == "DELIVERED"
        # Zwischenstatus nie als zugestellt werten
        if gs in {
            "TO_BE_DELIVERED",
            "READY_FOR_DELIVERY",
            "OUT_FOR_DELIVERY",
            "DISTRIBUTION",
            "IN_TRANSIT",
            "INTRANSIT",
            "TRANSPORT",
            "REPORTED",
            "ANNOUNCED",
            "PREADVICED",
        }:
            delivered = False
        return {
            "shipmentNumber": item.get("shipmentNumber") or identcode,
            "formattedShipmentNumber": item.get("formattedShipmentNumber"),
            "delivered": delivered,
            "deliveryDate": item.get("deliveryDate"),
            "globalStatus": global_status,
            "productStatus": product_status,
            "summary": summary,
            "creationDateTime": item.get("creationDateTime"),
            "sendingDateTime": item.get("sendingDateTime"),
            "lastEventDateTime": item.get("lastEventDateTime"),
            "signatureRequired": bool(item.get("signatureRequired")),
            "signature": item.get("signature"),
            "imageReference": item.get("imageReference"),
            "addressee": item.get("addressee") or {},
            "raw_events": raw_events,
        }

    def _fetch_events_by_identity(self, identity: str | None, headers: dict[str, str]) -> list[dict[str, Any]]:
        if not identity:
            return []
        try:
            r3 = self._session.get(
                f"{self.BASE}/shipment/id/{identity}/events/",
                headers=headers,
                timeout=30,
            )
        except requests.RequestException:
            return []
        if r3.status_code in {404, 403, 401}:
            return []
        if not r3.ok:
            return []
        try:
            events = r3.json()
        except ValueError:
            return []
        if isinstance(events, list):
            return events
        if isinstance(events, dict):
            return events.get("events") or []
        return []

    @staticmethod
    def _fmt_when(raw: Any) -> str:
        if not isinstance(raw, str) or not raw.strip():
            return ""
        return raw.strip()[:19].replace("T", " ")

    @staticmethod
    def _milestone_events(
        item: dict[str, Any],
        global_status: str,
        product_status: str,
        summary: str,
    ) -> list[dict[str, Any]]:
        """Vollständige Meilenstein-Timeline, wenn die Post keine Detail-Events liefert."""
        events: list[dict[str, Any]] = []
        created = TrackingClient._fmt_when(item.get("creationDateTime") or item.get("shipmentInfoCreationDateTime"))
        sent = TrackingClient._fmt_when(item.get("sendingDateTime"))
        last = TrackingClient._fmt_when(item.get("lastEventDateTime"))
        delivered_at = TrackingClient._fmt_when(item.get("deliveryDate"))
        calc = TrackingClient._fmt_when(item.get("calculatedDeliveryDate"))

        if created:
            events.append({
                "localDateTime": created,
                "title": "Elektronisch gemeldet",
                "description": "Sendung bei der Post erfasst",
                "status": "REPORTED",
            })
        if sent and sent != created:
            events.append({
                "localDateTime": sent,
                "title": "In Zustellung übernommen",
                "description": "Physischer Versand / Annahme bei der Post",
                "status": "IN_TRANSIT",
            })
        if calc and (item.get("globalStatus") or "").upper() not in {"DELIVERED"}:
            events.append({
                "localDateTime": calc,
                "title": "Voraussichtliche Zustellung",
                "description": "Berechnetes Zustelldatum",
                "status": "TO_BE_DELIVERED",
            })
        gs = (global_status or "").upper()
        if gs == "DELIVERED" or item.get("delivered"):
            when = delivered_at or last or sent or created
            events.append({
                "localDateTime": when,
                "title": "Zugestellt",
                "description": f"Post-Status: {global_status or product_status or 'DELIVERED'}",
                "status": "DELIVERED",
            })
        elif summary:
            when = last or sent or created
            # nicht doppelt, wenn schon gleicher Titel/Zeit
            if not any(e.get("title") == summary and e.get("localDateTime") == when for e in events):
                events.append({
                    "localDateTime": when,
                    "title": summary,
                    "description": f"Post-Status: {global_status or product_status or '-'}",
                    "status": global_status or product_status,
                })
        # chronologisch
        events.sort(key=lambda e: e.get("localDateTime") or "")
        return events

    @staticmethod
    def merge_formatted_events(*event_lists: list[dict[str, str]]) -> list[dict[str, str]]:
        """Events mehrerer Identcodes zusammenführen, Duplikate entfernen."""
        seen: set[tuple[str, str, str]] = set()
        out: list[dict[str, str]] = []
        for lst in event_lists:
            for ev in lst or []:
                key = (ev.get("at") or "", ev.get("title") or "", ev.get("detail") or "")
                if key in seen:
                    continue
                seen.add(key)
                out.append(ev)
        out.sort(key=lambda e: e.get("at") or "")
        return out

    @staticmethod
    def format_events(events: list[dict[str, Any]]) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        for ev in events:
            title = ""
            detail = ""
            when = ""
            for key in ("timestamp", "date", "eventDate", "localDateTime", "gmtDateTime"):
                val = ev.get(key)
                if isinstance(val, str) and val.strip():
                    when = val.strip()[:19].replace("T", " ")
                    break
            for key in ("title", "label", "status", "eventText"):
                val = ev.get(key)
                if isinstance(val, str) and val.strip():
                    title = val.strip()
                    break
            for key in ("description", "detail", "text"):
                val = ev.get(key)
                if isinstance(val, str) and val.strip():
                    detail = val.strip()
                    break
            nested = ev.get("event") or ev.get("mailpieceEvent") or {}
            if isinstance(nested, dict):
                if not title:
                    for key in ("title", "label", "status"):
                        val = nested.get(key)
                        if isinstance(val, str) and val.strip():
                            title = val.strip()
                            break
                if not detail:
                    for key in ("description", "detail"):
                        val = nested.get(key)
                        if isinstance(val, str) and val.strip():
                            detail = val.strip()
                            break
            if not title and not detail:
                continue
            title_key = title.upper().removeprefix("STATUS:").strip()
            if title_key in _GLOBAL_STATUS_LABELS:
                title = _GLOBAL_STATUS_LABELS[title_key]
            out.append({"at": when, "title": title or detail, "detail": detail if detail != title else ""})
        return out

    @staticmethod
    def latest_summary(events: list[dict[str, Any]], *, info: dict[str, Any] | None = None) -> str:
        if info:
            label = global_status_label(info.get("globalStatus"), product_status=info.get("productStatus"))
            if label:
                return label
            label = (info.get("summary") or "").strip()
            if label and not label.startswith("Status:"):
                return label
            if info.get("delivered"):
                return "Zugestellt"
        formatted = TrackingClient.format_events(events)
        if not formatted:
            return ""
        latest = formatted[0]
        return latest.get("title") or latest.get("detail") or ""

    @staticmethod
    def map_status(events: list[dict[str, Any]], *, info: dict[str, Any] | None = None) -> str | None:
        if info:
            key = (info.get("globalStatus") or "").strip().upper()
            if key in _GLOBAL_STATUS_MAP:
                return _GLOBAL_STATUS_MAP[key]
            if info.get("delivered") and key not in {
                "TO_BE_DELIVERED",
                "READY_FOR_DELIVERY",
                "OUT_FOR_DELIVERY",
                "DISTRIBUTION",
                "IN_TRANSIT",
                "INTRANSIT",
                "TRANSPORT",
            }:
                return "delivered"
        if not events:
            return None
        texts: list[str] = []
        for ev in events:
            for key in ("title", "description", "status", "eventText", "label"):
                val = ev.get(key)
                if isinstance(val, str) and val.strip():
                    texts.append(val.strip())
            nested = ev.get("event") or ev.get("mailpieceEvent") or {}
            if isinstance(nested, dict):
                for key in ("title", "description", "status"):
                    val = nested.get(key)
                    if isinstance(val, str) and val.strip():
                        texts.append(val.strip())
        blob = " | ".join(texts)
        if _DELIVERED_RE.search(blob):
            return "delivered"
        if _HANDED_OVER_RE.search(blob):
            return "handed_over"
        return None
