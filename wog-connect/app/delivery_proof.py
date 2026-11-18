from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

_GREEN = HexColor("#1B5E3B")
_GREEN_SOFT = HexColor("#E8F2EC")
_BLUE = HexColor("#4BA3C7")
_TEXT = HexColor("#1A1F1C")
_MUTED = HexColor("#5C6B63")
_LINE = HexColor("#D5E0DA")
_BG_CARD = HexColor("#F7FAF8")

_LOGO_CANDIDATES = [
    Path(__file__).resolve().parent / "assets" / "wog-logo.png",
    Path("/opt/wog-connect/app/assets/wog-logo.png"),
]


def _logo_path() -> Path | None:
    for p in _LOGO_CANDIDATES:
        if p.is_file():
            return p
    return None


def _fmt_dt(raw: str | None) -> str:
    if not raw:
        return "—"
    text = str(raw).strip().replace("T", " ")
    if not text:
        return "—"
    try:
        if len(text) >= 16:
            dt = datetime.strptime(text[:16], "%Y-%m-%d %H:%M")
            return dt.strftime("%d.%m.%Y %H:%M")
        if len(text) >= 10:
            dt = datetime.strptime(text[:10], "%Y-%m-%d")
            return dt.strftime("%d.%m.%Y")
    except ValueError:
        pass
    return text[:19]



def _status_label(tracking_info: dict[str, Any]) -> str:
    if tracking_info.get("delivered"):
        return "Zugestellt"
    raw = (tracking_info.get("summary") or tracking_info.get("globalStatus") or "").strip()
    return raw or "—"


def build_delivery_proof_pdf(
    *,
    shipment: dict[str, Any],
    tracking_info: dict[str, Any],
    events: list[dict[str, str]] | None = None,
) -> bytes:
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    left = 20 * mm
    right = width - 20 * mm
    content_w = right - left

    # --- Header band ---
    header_h = 32 * mm
    c.setFillColor(_GREEN_SOFT)
    c.rect(0, height - header_h, width, header_h, fill=1, stroke=0)
    c.setStrokeColor(_GREEN)
    c.setLineWidth(1.2)
    c.line(0, height - header_h, width, height - header_h)

    logo = _logo_path()
    if logo:
        try:
            img = ImageReader(str(logo))
            # keep aspect ~718x426 → width 42mm
            logo_w = 42 * mm
            logo_h = logo_w * (426 / 718)
            c.drawImage(
                img,
                left,
                height - 8 * mm - logo_h,
                width=logo_w,
                height=logo_h,
                mask="auto",
                preserveAspectRatio=True,
            )
        except Exception:
            logo = None

    title_x = left + (48 * mm if logo else 0)
    c.setFillColor(_GREEN)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(title_x, height - 16 * mm, "Digitaler Zustellnachweis")
    c.setFillColor(_MUTED)
    c.setFont("Helvetica", 9)
    c.drawString(title_x, height - 22 * mm, "WOG Logistics AG · World of Green Logistics")

    y = height - header_h - 12 * mm

    def ensure_space(need: float = 20 * mm) -> None:
        nonlocal y
        if y < 22 * mm + need:
            _footer(c, width)
            c.showPage()
            y = height - 18 * mm

    def section(title: str) -> None:
        nonlocal y
        ensure_space(18 * mm)
        y -= 2 * mm
        c.setFillColor(_GREEN)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(left, y, title.upper())
        y -= 2.2 * mm
        c.setStrokeColor(_LINE)
        c.setLineWidth(0.6)
        c.line(left, y, right, y)
        y -= 5.5 * mm

    def kv(label: str, value: str, *, value_size: int = 10) -> None:
        nonlocal y
        ensure_space(8 * mm)
        c.setFillColor(_MUTED)
        c.setFont("Helvetica", 8)
        c.drawString(left, y, label)
        c.setFillColor(_TEXT)
        c.setFont("Helvetica", value_size)
        text = (value or "—").strip() or "—"
        # wrap long values
        max_chars = 78
        if len(text) <= max_chars:
            c.drawString(left + 42 * mm, y, text)
            y -= 5.2 * mm
            return
        # multi-line
        words = text.split()
        lines: list[str] = []
        cur = ""
        for w in words:
            trial = f"{cur} {w}".strip()
            if len(trial) > max_chars and cur:
                lines.append(cur)
                cur = w
            else:
                cur = trial
        if cur:
            lines.append(cur)
        for i, ln in enumerate(lines[:4]):
            c.drawString(left + 42 * mm, y, ln)
            y -= 4.6 * mm
            if i < len(lines) - 1:
                ensure_space(6 * mm)
                c.setFillColor(_TEXT)
                c.setFont("Helvetica", value_size)

    def status_card(status: str, delivery_date: str) -> None:
        nonlocal y
        ensure_space(22 * mm)
        card_h = 16 * mm
        c.setFillColor(_BG_CARD)
        c.roundRect(left, y - card_h + 4 * mm, content_w, card_h, 3 * mm, fill=1, stroke=0)
        c.setStrokeColor(_LINE)
        c.setLineWidth(0.7)
        c.roundRect(left, y - card_h + 4 * mm, content_w, card_h, 3 * mm, fill=0, stroke=1)

        c.setFillColor(_MUTED)
        c.setFont("Helvetica", 8)
        c.drawString(left + 4 * mm, y - 1 * mm, "Zustellstatus")
        c.drawString(left + content_w / 2, y - 1 * mm, "Zustelldatum")

        c.setFillColor(_GREEN)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(left + 4 * mm, y - 7.5 * mm, status[:40])
        c.setFillColor(_TEXT)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(left + content_w / 2, y - 7.5 * mm, delivery_date)
        y -= card_h + 4 * mm

    # Meta
    c.setFillColor(_MUTED)
    c.setFont("Helvetica", 8)
    created = datetime.now().strftime("%d.%m.%Y %H:%M")
    c.drawRightString(right, y, f"Erstellt am {created}")
    y -= 8 * mm

    section("Referenzen")
    tour = shipment.get("tour_number") or "—"
    ta = shipment.get("transport_order_number") or "—"
    pos = shipment.get("item_number") or "—"
    sendung = shipment.get("sendungsnummer") or "—"
    ext_order = (shipment.get("external_order_number") or "").strip()
    ext_ship = (shipment.get("external_number") or "").strip()
    kv("Tour", str(tour))
    kv("Transportauftrag", str(ta))
    kv("Position", str(pos))
    kv("Sendungsnummer", str(sendung))
    if ext_order:
        kv("Externe Auftragsnummer", ext_order)
    if ext_ship and ext_ship.casefold() != ext_order.casefold():
        kv("Externe Sendungsnummer", ext_ship)
    elif ext_ship and not ext_order:
        kv("Externe Sendungsnummer", ext_ship)

    section("Sendung")
    addr = ", ".join(
        filter(
            None,
            [
                shipment.get("recipient_street"),
                " ".join(filter(None, [shipment.get("recipient_zip"), shipment.get("recipient_city")])),
            ],
        )
    ) or "—"
    ident = shipment.get("identcode") or tracking_info.get("shipmentNumber") or "—"
    kv("Empfänger", str(shipment.get("recipient_name") or "—"), value_size=11)
    kv("Adresse", addr)
    kv("Identcode", str(ident))

    section("Zustellung")
    status_card(_status_label(tracking_info), _fmt_dt(tracking_info.get("deliveryDate")))
    if tracking_info.get("signatureRequired"):
        kv("Unterschrift", "erforderlich")
    if tracking_info.get("signature"):
        kv("Post-Unterschrift", "verfügbar")

    if events:
        section("Tracking-Verlauf")
        ensure_space(10 * mm)
        c.setFillColor(_GREEN_SOFT)
        c.rect(left, y - 1.5 * mm, content_w, 6 * mm, fill=1, stroke=0)
        c.setFillColor(_GREEN)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(left + 2 * mm, y, "Zeitpunkt")
        c.drawString(left + 42 * mm, y, "Ereignis")
        y -= 7 * mm

        def _wrap(text: str, width_chars: int = 72) -> list[str]:
            text = (text or "").strip()
            if not text:
                return ["—"]
            words = text.split()
            lines: list[str] = []
            cur = ""
            for w in words:
                trial = f"{cur} {w}".strip()
                if len(trial) > width_chars and cur:
                    lines.append(cur)
                    cur = w
                else:
                    cur = trial
            if cur:
                lines.append(cur)
            return lines or ["—"]

        for ev in events:
            when = (ev.get("at") or "—")[:19]
            title = (ev.get("title") or "").strip()
            detail = (ev.get("detail") or "").strip()
            event_text = title
            if detail and detail != title:
                event_text = f"{title} – {detail}" if title else detail
            lines = _wrap(event_text, 72)
            ensure_space(5 * mm * max(1, len(lines)) + 3 * mm)
            for i, ln in enumerate(lines):
                if i == 0:
                    c.setFillColor(_MUTED)
                    c.setFont("Helvetica", 8)
                    c.drawString(left + 2 * mm, y, when)
                c.setFillColor(_TEXT)
                c.setFont("Helvetica", 8)
                c.drawString(left + 42 * mm, y, ln)
                y -= 4.4 * mm
            c.setStrokeColor(_LINE)
            c.setLineWidth(0.3)
            c.line(left, y + 2.2 * mm, right, y + 2.2 * mm)
            y -= 1.2 * mm

    _footer(c, width)
    c.save()
    return buf.getvalue()


def _footer(c: canvas.Canvas, width: float) -> None:
    c.setStrokeColor(_LINE)
    c.setLineWidth(0.6)
    c.line(20 * mm, 14 * mm, width - 20 * mm, 14 * mm)
    c.setFillColor(_MUTED)
    c.setFont("Helvetica", 7)
    c.drawString(20 * mm, 9 * mm, "WOG Logistics AG · Wildenaustraße 22 · 9444 Diepoldsau")
    c.drawRightString(width - 20 * mm, 9 * mm, "Digitaler Zustellnachweis")
