from __future__ import annotations

import json
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.auth import attempt_login, is_logged_in, require_api_key, require_login
from app.label_util import stamp_logo_on_pdf
from app.config import get_settings
from app.delivery_products import list_delivery_products, list_faq
from app.draft_util import draft_from_row
from app.processor import TourProcessor
from app.storage import Storage
from app.tracking_client import primary_identcode, tracking_url
from app.invoice_import import format_chf, is_surcharge_hint

settings = get_settings()
storage = Storage(settings.data_dir)
processor = TourProcessor(settings)

app = FastAPI(title="WOG Connect", version="0.3.0")
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret, https_only=True, same_site="lax")

static_dir = Path(__file__).resolve().parent.parent / "web" / "static"
web_dir = static_dir.parent
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


def _read_web_text(name: str) -> str:
    path = web_dir / name
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "utf-16", "utf-16le"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise RuntimeError(f"Cannot decode {path}")


def _enrich_shipment_row(row: dict) -> dict:
    out = dict(row)
    raw = out.get("draft_json")
    if not raw:
        return _attach_weight_warning(out)
    try:
        draft = json.loads(raw)
        recipient = draft.get("recipient") or {}
        if recipient.get("name2"):
            out["recipient_name2"] = recipient["name2"]
        av = draft.get("address_validation")
        if av:
            out["address_valid"] = av.get("valid")
            out["address_message"] = av.get("message")
            out["address_quality"] = av.get("quality")
        out["notify_recipient"] = draft.get("notify_recipient", bool(recipient.get("email")))
        if draft.get("sendungsnummer"):
            out["sendungsnummer"] = draft.get("sendungsnummer")
        tr = draft.get("tracking") or {}
        if tr.get("summary"):
            out["tracking_summary"] = tr.get("summary")
        if tr.get("synced_at"):
            out["tracking_synced_at"] = tr.get("synced_at")
        if tr.get("delivered"):
            out["tracking_delivered"] = True
        if tr.get("delivery_proof_at"):
            out["delivery_proof_at"] = tr.get("delivery_proof_at")
    except (json.JSONDecodeError, TypeError, AttributeError):
        pass
    if not out.get("sendungsnummer") and row.get("sendungsnummer"):
        out["sendungsnummer"] = row.get("sendungsnummer")
    ident = primary_identcode(out.get("identcode"))
    url = tracking_url(ident)
    if url:
        out["tracking_url"] = url
    if ident and (out.get("status") == "delivered" or out.get("tracking_delivered")):
        out["delivery_proof_available"] = True
    return _attach_weight_warning(out)


def _attach_weight_warning(row: dict) -> dict:
    from app.weight_util import weight_warning

    warn = weight_warning(int(row.get("weight_grams") or 0), int(row.get("packstuecke") or 1))
    if warn:
        row["weight_warning"] = warn
    return row


def _attach_billing(rows: list[dict]) -> list[dict]:
    ids = [r["id"] for r in rows if r.get("id")]
    summary = storage.billing_summary_for_shipments(ids)
    enriched: list[dict] = []
    for row in rows:
        out = dict(row)
        bill = summary.get(row["id"])
        if bill:
            out.update(bill)
            out["billing_total_chf"] = format_chf(bill.get("billing_total_cents"))
            products = bill.get("billing_products") or []
            out["billing_surcharge_hint"] = any(is_surcharge_hint(p) for p in products)
        soloplan = storage.format_soloplan_label(out)
        if soloplan:
            out["soloplan_label"] = soloplan
        enriched.append(out)
    return enriched


@app.get("/health")
def health():
    return {"ok": True, "service": "wog-connect"}


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    if not is_logged_in(request):
        return RedirectResponse("/login", status_code=302)
    return HTMLResponse(_read_web_text("index.html"))


@app.get("/login", response_class=HTMLResponse)
def login_page():
    return HTMLResponse(_read_web_text("login.html"))


@app.post("/api/auth/login")
async def login(request: Request):
    body = await request.json()
    user = str(body.get("username", "")).strip()
    pw = str(body.get("password", ""))
    if attempt_login(user, pw, request):
        return {"ok": True}
    raise HTTPException(status_code=401, detail="Invalid credentials")


@app.post("/api/auth/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@app.get("/api/v1/delivery-products")
def delivery_products(request: Request):
    require_login(request)
    return {"ok": True, "products": list_delivery_products(), "default": "eco"}


@app.get("/api/v1/faq")
def faq(request: Request):
    require_login(request)
    return {"ok": True, "items": list_faq()}


@app.post("/api/v1/tours/upload")
async def upload_tour(file: UploadFile = File(...), auto_label: bool = False, _=Depends(require_api_key)):
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    try:
        return processor.ingest_bytes(file.filename or "tour.json", content, auto_label=auto_label)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/incoming/scan")
def scan_incoming(_=Depends(require_api_key)):
    return {"ok": True, "results": processor.process_incoming_dir()}


@app.get("/api/v1/shipments")
def list_shipments(
    request: Request,
    open_only: bool = False,
    status: str | None = None,
    tour_number: str | None = None,
    date: str | None = None,
    q: str | None = None,
):
    require_login(request)
    rows = [_enrich_shipment_row(r) for r in storage.list_shipments(
        status=status,
        open_only=open_only,
        tour_number=tour_number,
        date=date,
        q=q,
    )]
    rows = _attach_billing(rows)
    return {"ok": True, "shipments": rows, "count": len(rows)}


@app.get("/api/v1/tours")
def list_tours(request: Request):
    require_login(request)
    return {"ok": True, "tours": storage.list_tour_filters()}


@app.get("/api/v1/shipments/{shipment_id}")
def get_shipment(shipment_id: str, request: Request):
    require_login(request)
    row = storage.get_shipment(shipment_id)
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    draft = None
    labels = storage.list_shipment_labels(shipment_id)
    if row.get("draft_json"):
        try:
            draft = json.loads(row["draft_json"])
        except json.JSONDecodeError:
            draft = None
    return {"ok": True, "shipment": _enrich_shipment_row(row), "draft": draft, "labels": labels}


@app.patch("/api/v1/shipments/{shipment_id}")
async def patch_shipment(shipment_id: str, request: Request):
    require_login(request)
    body = await request.json()
    try:
        return processor.update_shipment(shipment_id, body)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/v1/addresses/validate")
async def validate_address_body(request: Request):
    require_login(request)
    body = await request.json()
    recipient = body.get("recipient") or body
    from app.draft_util import _addr_from
    from app.address_validation import AddressValidator

    result = AddressValidator(settings, processor.post).validate_recipient(_addr_from(recipient))
    return {"ok": True, **result.to_dict()}


@app.post("/api/v1/shipments/{shipment_id}/validate-address")
def validate_shipment_address(shipment_id: str, request: Request):
    require_login(request)
    try:
        return processor.validate_shipment_address(shipment_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/v1/shipments/{shipment_id}/accept-address")
def accept_shipment_address(shipment_id: str, request: Request):
    require_login(request)
    try:
        return processor.accept_shipment_address(shipment_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/v1/tours/{tour_ref}/validate-addresses")
def validate_tour_addresses(tour_ref: str, request: Request):
    require_login(request)
    try:
        return processor.validate_tour_addresses(tour_ref)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))




@app.get("/api/v1/address-book")
def list_address_book(request: Request, limit: int = Query(200, ge=1, le=500)):
    require_login(request)
    return {"ok": True, "entries": processor.storage.list_address_book(limit=limit)}


@app.post("/api/v1/address-book")
async def upsert_address_book(request: Request):
    require_login(request)
    body = await request.json()
    entry = processor.storage.upsert_address_book_entry(
        name1=str(body.get("name1") or ""),
        name2=body.get("name2"),
        street=str(body.get("street") or ""),
        zip_code=str(body.get("zip_code") or body.get("zip") or ""),
        city=str(body.get("city") or ""),
        country=str(body.get("country") or "CH"),
        email=body.get("email"),
        soloplan_matchcode=body.get("soloplan_matchcode") or body.get("matchcode"),
        soloplan_bp_id=body.get("soloplan_bp_id") or body.get("bp_id"),
        notes=body.get("notes"),
        source_shipment_id=body.get("source_shipment_id"),
    )
    return {"ok": True, "entry": entry}


@app.delete("/api/v1/address-book/{entry_id}")
def delete_address_book_entry(entry_id: str, request: Request):
    require_login(request)
    ok = processor.storage.delete_address_book_entry(entry_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
    return {"ok": True}


@app.post("/api/v1/shipments/{shipment_id}/address-book")
def save_shipment_to_address_book(shipment_id: str, request: Request):
    require_login(request)
    try:
        entry = processor.save_recipient_to_address_book(shipment_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"ok": True, "entry": entry}

@app.post("/api/v1/shipments/{shipment_id}/generate-label")
def generate_label(shipment_id: str, request: Request):
    require_login(request)
    result = processor.generate_label(shipment_id)
    if not result.get("ok"):
        return {"ok": False, "shipmentId": shipment_id, "error": result.get("error", "Label fehlgeschlagen")}
    return result


@app.get("/api/v1/shipments/{shipment_id}/label")
def download_label(shipment_id: str, request: Request):
    require_login(request)
    row = storage.get_shipment(shipment_id)
    if not row or not row.get("label_path"):
        raise HTTPException(status_code=404, detail="Label not found")
    path = Path(row["label_path"])
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Label file missing")
    if path.suffix.lower() == ".pdf":
        content = path.read_bytes()
        if settings.label_logo_enabled:
            content = stamp_logo_on_pdf(
                content,
                settings.label_logo_path,
                width_pt=settings.label_logo_width_pt,
            )
        return Response(
            content=content,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{path.name}"'},
        )
    return FileResponse(
        path,
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{path.name}"'},
    )


@app.patch("/api/v1/shipments/{shipment_id}/status")
async def update_status(shipment_id: str, request: Request):
    require_login(request)
    body = await request.json()
    status = str(body.get("status", "")).strip()
    if status not in {"uploaded", "label_created", "handed_over", "delivered", "error"}:
        raise HTTPException(status_code=400, detail="Invalid status")
    row = storage.get_shipment(shipment_id)
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    storage.update_shipment(shipment_id, status=status, delivered=(status == "delivered"))
    shippingnet = None
    if status == "delivered":
        shippingnet = processor.push_shippingnet_delivered(shipment_id)
    return {"ok": True, "shippingnet": shippingnet}


@app.post("/api/v1/tours/{tour_ref}/generate-labels")
def generate_tour_labels(tour_ref: str, request: Request, only_missing: bool = Query(True)):
    require_login(request)
    try:
        return processor.generate_labels_for_tour(tour_ref, only_missing=only_missing)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/v1/tours/{tour_ref}/labels.zip")
def download_tour_labels(tour_ref: str, request: Request):
    require_login(request)
    try:
        content, filename = processor.build_tour_labels_zip(tour_ref)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return Response(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/v1/tours/{tour_ref}/labels.pdf")
def download_tour_labels_pdf(tour_ref: str, request: Request):
    require_login(request)
    try:
        content, filename = processor.build_tour_labels_pdf(tour_ref)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@app.get("/api/v1/shipments/{shipment_id}/tracking")
def get_shipment_tracking(shipment_id: str, request: Request, refresh: bool = Query(False)):
    require_login(request)
    try:
        return processor.fetch_shipment_tracking(shipment_id, refresh=refresh)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/v1/shipments/{shipment_id}/tracking/refresh")
def refresh_shipment_tracking(shipment_id: str, request: Request):
    require_login(request)
    try:
        return processor.fetch_shipment_tracking(shipment_id, refresh=True)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/v1/shipments/{shipment_id}/shippingnet/delivered")
def push_shippingnet_delivered(shipment_id: str, request: Request):
    """Manuell: shipping.NET Status DVD setzen (ORG_ADMIN-Zugang über Portal-Login)."""
    require_login(request)
    row = storage.get_shipment(shipment_id)
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    result = processor.push_shippingnet_delivered(shipment_id, force=True)
    if not result.get("ok") and not result.get("skipped"):
        raise HTTPException(status_code=502, detail=result.get("error") or "shipping.NET Fehler")
    return result


@app.post("/api/v1/shipments/{shipment_id}/portal-ablieferbeleg")
def push_portal_ablieferbeleg(shipment_id: str, request: Request):
    """Manuell: Ablieferbeleg-PDF als POD an das WOG-Kundenportal senden."""
    require_login(request)
    row = storage.get_shipment(shipment_id)
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    result = processor.push_portal_ablieferbeleg(shipment_id, force=True)
    if result.get("skipped") and result.get("reason") == "not_configured":
        raise HTTPException(status_code=503, detail="Portal-Ablieferbeleg-API nicht konfiguriert")
    if not result.get("ok") and not result.get("skipped"):
        raise HTTPException(status_code=502, detail=result.get("error") or "Portal-Upload fehlgeschlagen")
    return result


@app.post("/api/v1/tracking/sync")
def sync_tracking(request: Request, _=Depends(require_api_key)):
    return processor.sync_tracking()


@app.post("/api/v1/billing/import")
async def import_billing(request: Request, file: UploadFile = File(...)):
    require_login(request)
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Leere Datei")
    try:
        return processor.import_billing_file(file.filename or "rechnung.xlsx", content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Import fehlgeschlagen: {e}")


@app.get("/api/v1/billing/imports")
def list_billing_imports(request: Request):
    require_login(request)
    imports = storage.list_billing_imports()
    for item in imports:
        item["imported_at"] = item.get("imported_at")
    return {"ok": True, "imports": imports}


@app.get("/api/v1/billing/unmatched")
def list_unmatched_billing(request: Request, limit: int = Query(50, ge=1, le=500)):
    require_login(request)
    rows = storage.list_unmatched_billing_lines(limit=limit)
    for row in rows:
        row["amount_chf"] = format_chf(row.get("amount_cents"))
    return {"ok": True, "lines": rows, "count": len(rows)}


@app.get("/api/v1/shipments/{shipment_id}/delivery-proof")
def download_delivery_proof(shipment_id: str, request: Request):
    require_login(request)
    try:
        content, filename = processor.build_delivery_proof(shipment_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ablieferbeleg fehlgeschlagen: {e}")
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@app.get("/api/v1/shipments/{shipment_id}/billing")
def get_shipment_billing(shipment_id: str, request: Request):
    require_login(request)
    row = storage.get_shipment(shipment_id)
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    lines = storage.list_billing_lines_for_shipment(shipment_id)
    total = sum(int(l.get("amount_cents") or 0) for l in lines)
    soloplan = storage.get_soloplan_refs(shipment_id)
    for line in lines:
        line["amount_chf"] = format_chf(line.get("amount_cents"))
    return {
        "ok": True,
        "shipment_id": shipment_id,
        "total_cents": total,
        "total_chf": format_chf(total),
        "soloplan": soloplan,
        "lines": lines,
    }


@app.post("/api/v1/admin/backfill")
def backfill_shipments(_=Depends(require_api_key)):
    return processor.backfill_shipments_from_tours()


@app.get("/api/v1/status/export")
def export_status_for_wog(_=Depends(require_api_key)):
    from datetime import datetime, timezone
    return {
        "ok": True,
        "exportedAt": datetime.now(timezone.utc).isoformat(),
        "items": storage.export_status_for_wog(),
    }
