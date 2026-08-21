from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from app.address_util import merge_suggested_recipient, recipient_differs
from app.config import Settings, get_settings
from app.delivery_products import przl_for_product
from app.draft_util import draft_from_dict, draft_from_row, draft_to_dict
from app.address_validation import AddressValidationResult, AddressValidator
from app.label_util import build_labels_zip, merge_pdf_files, merge_zpl_files
from app.label_validation import validate_for_label
from app.mapper import build_post_request
from app.post_client import PostApiError, PostClient
from app.soloplan_parser import ShipmentDraft, coerce_tour_document, parse_tour_json
from app.storage import Storage
from app.shippingnet_client import ShippingNetClient, ShippingNetError, normalize_shippingnet_status_date
from app.tracking_client import TrackingClient, primary_identcode, tracking_url
from app.weight_util import weight_warning



def _parse_post_error_payload(payload):
    if payload is None:
        return []
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            return []
    if isinstance(payload, dict):
        # sometimes wrapped
        for key in ("errors", "validationErrors", "detail", "message"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
        else:
            return [payload] if payload.get("field") else []
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    return []


def is_customer_field_error(exc) -> bool:
    """True wenn die Post-API den Absender (customer.*) ablehnt."""
    items = _parse_post_error_payload(getattr(exc, "payload", None))
    if any(str(it.get("field") or "").startswith("customer.") for it in items):
        return True
    blob = str(getattr(exc, "payload", "") or "")
    return "customer." in blob



class TourProcessor:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.storage = Storage(self.settings.data_dir)
        self.post = PostClient(self.settings)
        self.tracking = TrackingClient()
        self.shippingnet = ShippingNetClient(self.settings)
        self.address_validator = AddressValidator(self.settings, self.post)

    @staticmethod
    def _decode_tour_json(content: bytes) -> dict:
        return coerce_tour_document(json.loads(content.decode("utf-8-sig")))

    @staticmethod
    def _transport_order_count(data: dict) -> int:
        tours = data.get("tour") or []
        if not tours:
            return 0
        tour = tours[0] if isinstance(tours, list) else tours
        if not isinstance(tour, dict):
            return 0
        return len(tour.get("transportOrders") or [])

    def _parse_tour_content(self, content: bytes) -> tuple[dict, dict, list[ShipmentDraft]]:
        data = self._decode_tour_json(content)
        meta, drafts = parse_tour_json(
            data,
            reference_filter=self.settings.consignment_reference_filter,
            carrier_filter=self.settings.carrier_matchcode_filter,
            default_weight=self.settings.default_weight_grams,
        )
        return data, meta, drafts

    def _find_existing_tour(self, data: dict, meta: dict) -> dict | None:
        export_reference = ((data.get("header") or {}).get("exportItemReference") or "").strip()
        if export_reference:
            existing = self.storage.find_tour_by_export_reference(export_reference)
            if existing:
                return existing
        planned = meta.get("plannedStartTime") or meta.get("sendDate") or ""
        return self.storage.find_tour_by_number(
            str(meta.get("tourNumber") or ""),
            ext_tour_number=str(meta.get("extTourNumber") or ""),
            planned_date=str(planned)[:10] if planned else "",
        )

    def _add_missing_shipments(
        self,
        tour_id: str,
        drafts: list[ShipmentDraft],
        *,
        auto_label: bool = False,
    ) -> tuple[list[str], int]:
        shipment_ids: list[str] = []
        skipped = 0
        for draft in drafts:
            if self.storage.find_shipment_key(tour_id, draft.transport_order_number, draft.item_number):
                skipped += 1
                continue
            sid = self.storage.add_shipment(tour_id, draft)
            shipment_ids.append(sid)
            if auto_label:
                self.generate_label(sid)
        return shipment_ids, skipped

    def ingest_bytes(self, filename: str, content: bytes, *, auto_label: bool = False) -> dict:
        data, meta, drafts = self._parse_tour_content(content)
        export_reference = ((data.get("header") or {}).get("exportItemReference") or "").strip()
        transport_orders = self._transport_order_count(data)
        warning = None
        if transport_orders > 0 and not drafts:
            warning = (
                f"Datei enthält {transport_orders} Transportauftrag/Aufträge, "
                "aber keine Post-Sendungen erkannt (Filter POST/DPD bzw. Carrier POSTCH prüfen)."
            )

        existing = self._find_existing_tour(data, meta)
        if existing:
            tour_id = existing["id"]
            self.storage.update_tour_meta(tour_id, meta)
            path = self.storage.save_tour_file(filename, content)
            shipment_ids, skipped = self._add_missing_shipments(tour_id, drafts, auto_label=auto_label)
            message = (
                f"Tour aktualisiert – {len(shipment_ids)} neue Sendung(en)"
                if shipment_ids
                else "Tour bereits vollständig importiert"
            )
            return {
                "ok": True,
                "duplicate": True,
                "tourId": tour_id,
                "tourNumber": meta.get("tourNumber") or existing.get("tour_number"),
                "exportReference": export_reference or existing.get("export_reference"),
                "message": message,
                "shipmentsFound": len(shipment_ids),
                "shipmentIds": shipment_ids,
                "skippedDuplicates": skipped,
                "transportOrdersInFile": transport_orders,
                "warning": warning,
                "tourFile": path.name,
            }

        path = self.storage.save_tour_file(filename, content)
        tour_id = self.storage.create_tour(meta, str(path.name))
        shipment_ids, skipped = self._add_missing_shipments(tour_id, drafts, auto_label=auto_label)
        return {
            "ok": True,
            "duplicate": False,
            "tourId": tour_id,
            "tourNumber": meta.get("tourNumber"),
            "exportReference": export_reference or None,
            "shipmentsFound": len(shipment_ids),
            "shipmentIds": shipment_ids,
            "skippedDuplicates": skipped,
            "skipped": meta.get("skipped"),
            "transportOrdersInFile": transport_orders,
            "warning": warning,
        }

    def get_draft(self, shipment_id: str):
        row = self.storage.get_shipment(shipment_id)
        if not row:
            return None
        return draft_from_row(row)

    def update_shipment(self, shipment_id: str, payload: dict) -> dict:
        row = self.storage.get_shipment(shipment_id)
        if not row:
            raise ValueError("Sendung nicht gefunden")
        base = {}
        if row.get("draft_json"):
            try:
                base = json.loads(row["draft_json"])
            except json.JSONDecodeError:
                base = {}
        old_recipient = dict(base.get("recipient") or {})
        recipient = payload.get("recipient") or {}
        recipient_changed = False
        for key in ("name1", "name2", "street", "zip_code", "city", "country", "email"):
            if key in recipient:
                new_val = recipient[key]
                if (old_recipient.get(key) or None) != (new_val or None):
                    recipient_changed = True
                base.setdefault("recipient", {})[key] = new_val
        if "weight_grams" in payload:
            base["weight_grams"] = max(1, int(payload["weight_grams"]))
        if "packstuecke" in payload:
            base["packstuecke"] = max(1, int(payload["packstuecke"]))
        if "delivery_product_id" in payload:
            pid = str(payload["delivery_product_id"])
            base["delivery_product_id"] = pid
            base["przl"] = przl_for_product(pid)
        if "notify_recipient" in payload:
            base["notify_recipient"] = bool(payload["notify_recipient"])
        draft = draft_from_dict(base)
        draft_data = draft_to_dict(draft, delivery_product_id=base.get("delivery_product_id", "eco"))
        # Tracking & Adressprüfung behalten; bei Adressänderung Prüfung zurücksetzen
        if base.get("tracking"):
            draft_data["tracking"] = base["tracking"]
        if not recipient_changed and base.get("address_validation"):
            draft_data["address_validation"] = base["address_validation"]
        self.storage.update_shipment_details(shipment_id, draft_data)
        warn = weight_warning(draft.weight_grams, draft.packstuecke)
        out: dict = {"ok": True, "shipmentId": shipment_id, "saved": True}
        if warn:
            out["weight_warning"] = warn
            out["warnings"] = [warn]
        return out

    def _address_override_from_row(self, row: dict) -> bool:
        raw = row.get("draft_json")
        if not raw:
            return False
        try:
            av = json.loads(raw).get("address_validation") or {}
        except (json.JSONDecodeError, TypeError, AttributeError):
            return False
        return bool(av.get("override"))

    def _apply_validated_address(
        self,
        shipment_id: str,
        draft: ShipmentDraft,
        result: AddressValidationResult,
    ) -> tuple[ShipmentDraft, bool]:
        if not result.valid or not result.suggested:
            return draft, False
        original = {
            "name1": draft.recipient.name1,
            "name2": draft.recipient.name2 or "",
            "street": draft.recipient.street,
            "zip_code": draft.recipient.zip_code,
            "city": draft.recipient.city,
        }
        if not recipient_differs(original, result.suggested):
            return draft, False
        updated = replace(draft, recipient=merge_suggested_recipient(draft.recipient, result.suggested))
        product_id = str(
            json.loads(self.storage.get_shipment(shipment_id).get("draft_json") or "{}").get("delivery_product_id")
            or "eco"
        )
        self.storage.update_shipment_details(
            shipment_id,
            draft_to_dict(updated, delivery_product_id=product_id),
        )
        return updated, True

    def _validate_and_apply_address(
        self,
        shipment_id: str,
        draft: ShipmentDraft,
    ) -> tuple[ShipmentDraft, AddressValidationResult, bool]:
        result = self.address_validator.validate_draft(draft)
        applied = False
        if result.valid and result.suggested:
            draft, applied = self._apply_validated_address(shipment_id, draft, result)
            if applied:
                result = replace(
                    result,
                    message=f"{result.message} (in Sendung gespeichert)",
                )
        validation = result.to_dict()
        validation["applied"] = applied
        validation.pop("override", None)
        self.storage.save_address_validation(shipment_id, validation)
        return draft, result, applied

    def validate_shipment_address(self, shipment_id: str) -> dict:
        draft = self.get_draft(shipment_id)
        if not draft:
            raise ValueError("Sendung nicht gefunden")
        draft, result, applied = self._validate_and_apply_address(shipment_id, draft)
        return {"ok": True, "shipmentId": shipment_id, "applied": applied, **result.to_dict()}

    def accept_shipment_address(self, shipment_id: str) -> dict:
        row = self.storage.get_shipment(shipment_id)
        if not row:
            raise ValueError("Sendung nicht gefunden")
        validation = {
            "valid": True,
            "quality": "MANUAL",
            "message": "Adresse manuell bestätigt",
            "override": True,
            "applied": False,
            "suggested": None,
        }
        self.storage.save_address_validation(shipment_id, validation)
        return {"ok": True, "shipmentId": shipment_id, **validation}

    def validate_tour_addresses(self, tour_ref: str) -> dict:
        tour_id = self.storage.resolve_tour_id(tour_ref)
        if not tour_id:
            raise ValueError("Tour nicht gefunden")
        rows = self.storage.list_shipments_for_tour(tour_id)
        results = []
        invalid = 0
        applied_count = 0
        for row in rows:
            draft = draft_from_row(row)
            if not draft:
                continue
            draft, res, applied = self._validate_and_apply_address(row["id"], draft)
            if applied:
                applied_count += 1
            entry = {
                "shipmentId": row["id"],
                "recipientName": row.get("recipient_name"),
                "applied": applied,
                **res.to_dict(),
            }
            results.append(entry)
            if not res.valid:
                invalid += 1
        return {
            "ok": invalid == 0,
            "tourId": tour_id,
            "checked": len(results),
            "invalid": invalid,
            "applied": applied_count,
            "results": results,
        }

    def _piece_count(self, draft: ShipmentDraft, row: dict) -> int:
        return max(1, int(getattr(draft, "packstuecke", None) or row.get("packstuecke") or 1))

    def generate_label(self, shipment_id: str, draft: ShipmentDraft | None = None) -> dict:
        row = self.storage.get_shipment(shipment_id)
        if not row:
            raise ValueError("Sendung nicht gefunden")
        if draft is None:
            draft = draft_from_row(row)
        if draft is None:
            raise ValueError("Keine Sendungsdaten – bitte Adresse speichern")

        address_override = self._address_override_from_row(row)
        if self.settings.post_address_validate_enabled and not address_override:
            draft, addr_result, _applied = self._validate_and_apply_address(shipment_id, draft)
            if not addr_result.valid:
                msg = addr_result.message
                # Adresse bleibt gespeichert – nur Label unterbinden, Status nicht auf error setzen
                self.storage.update_shipment(shipment_id, error_message=msg)
                return {
                    "ok": False,
                    "shipmentId": shipment_id,
                    "error": msg,
                    "addressInvalid": True,
                    "saved": True,
                }
            row = self.storage.get_shipment(shipment_id) or row

        validation_errors = validate_for_label(draft, skip_address_validation=True)
        if validation_errors:
            msg = "; ".join(validation_errors)
            self.storage.update_shipment(shipment_id, status="error", error_message=msg)
            return {"ok": False, "shipmentId": shipment_id, "error": msg}

        weight_warn = weight_warning(draft.weight_grams, self._piece_count(draft, row))

        product_id = row.get("delivery_product_id") or "eco"
        piece_count = self._piece_count(draft, row)
        generated: list[dict] = []
        errors: list[str] = []

        wog_fallback_used = False
        for piece in range(1, piece_count + 1):
            req = build_post_request(
                draft,
                self.settings,
                delivery_product_id=product_id,
                piece_number=piece,
                piece_count=piece_count,
            )
            try:
                resp = self.post.generate_label(req)
            except PostApiError as e:
                # Absender (Soloplan) oft mit Post-Restriktionen → Retry mit WOG Diepoldsau
                if self.settings.post_label_sender_from_soloplan and is_customer_field_error(e):
                    req = build_post_request(
                        draft,
                        self.settings,
                        delivery_product_id=product_id,
                        piece_number=piece,
                        piece_count=piece_count,
                        use_wog_sender=True,
                    )
                    try:
                        resp = self.post.generate_label(req)
                        wog_fallback_used = True
                    except PostApiError as e2:
                        msg = str(e2)
                        if e2.payload:
                            msg = f"{msg}: {str(e2.payload)[:300]}"
                        errors.append(f"Packstück {piece}: {msg}")
                        continue
                else:
                    msg = str(e)
                    if e.payload:
                        msg = f"{msg}: {str(e.payload)[:300]}"
                    errors.append(f"Packstück {piece}: {msg}")
                    continue
            ident = self.post.extract_identcode(resp)
            label_bytes, fmt = self.post.extract_label_bytes(resp, self.settings.post_label_image_type)
            ext = "zpl" if (fmt or "").startswith("zpl") else "pdf"
            label_path = None
            if label_bytes:
                label_path = self.storage.labels_dir / f"{shipment_id}_p{piece}.{ext}"
                label_path.write_bytes(label_bytes)
            generated.append(
                {
                    "piece_number": piece,
                    "identcode": ident,
                    "label_path": str(label_path) if label_path else None,
                    "label_format": ext,
                    "response": resp,
                    "request": req,
                }
            )

        if not generated:
            msg = errors[0] if errors else "Label fehlgeschlagen"
            self.storage.update_shipment(
                shipment_id,
                status="error",
                error_message=msg,
            )
            return {"ok": False, "shipmentId": shipment_id, "error": msg}

        self.storage.replace_shipment_labels(
            shipment_id,
            [
                {
                    "piece_number": g["piece_number"],
                    "identcode": g.get("identcode"),
                    "label_path": g.get("label_path"),
                    "label_format": g.get("label_format"),
                }
                for g in generated
            ],
        )

        primary = generated[0]
        combined_path = self._write_combined_label(shipment_id, generated)
        idents = [g.get("identcode") for g in generated if g.get("identcode")]
        error_message = "; ".join(errors) if errors else ""
        complete = len(generated) == piece_count
        status = "label_created" if complete else "error"
        if not complete and generated:
            error_message = (error_message + "; " if error_message else "") + f"Nur {len(generated)}/{piece_count} Packstück-Labels erzeugt"

        self.storage.update_shipment(
            shipment_id,
            status=status,
            identcode=", ".join(idents) if idents else primary.get("identcode"),
            label_path=str(combined_path) if combined_path else primary.get("label_path"),
            label_format=primary.get("label_format"),
            post_response={"pieces": [g["response"] for g in generated], "errors": errors},
            request_body={"pieces": [g["request"] for g in generated]},
            error_message=error_message,
        )
        warnings = list(errors)
        if wog_fallback_used:
            warnings.insert(0, "Absender durch WOG Diepoldsau ersetzt (Post-Restriktion)")
        if weight_warn:
            warnings.insert(0, weight_warn)
        return {
            "ok": True,
            "shipmentId": shipment_id,
            "identcode": ", ".join(idents),
            "labelFormat": primary.get("label_format"),
            "piecesGenerated": len(generated),
            "pieceCount": piece_count,
            "warnings": warnings,
            "weight_warning": weight_warn,
        }

    def _write_combined_label(self, shipment_id: str, generated: list[dict]) -> Path | None:
        paths = [Path(g["label_path"]) for g in generated if g.get("label_path")]
        if not paths:
            return None
        fmt = generated[0].get("label_format") or "zpl"
        if fmt == "zpl" and len(paths) > 1:
            combined = self.storage.labels_dir / f"{shipment_id}_all.zpl"
            combined.write_bytes(merge_zpl_files(paths))
            return combined
        if fmt == "pdf" and len(paths) > 1:
            combined = self.storage.labels_dir / f"{shipment_id}_all.pdf"
            combined.write_bytes(merge_pdf_files(paths))
            return combined
        return paths[0]

    def generate_labels_for_tour(self, tour_ref: str, *, only_missing: bool = True) -> dict:
        tour_id = self.storage.resolve_tour_id(tour_ref)
        if not tour_id:
            raise ValueError("Tour nicht gefunden")
        rows = self.storage.list_shipments_for_tour(tour_id)
        results = []
        ok = 0
        failed = 0
        for row in rows:
            if only_missing and row.get("label_path") and row.get("status") == "label_created":
                results.append({"shipmentId": row["id"], "skipped": True})
                continue
            if row.get("status") not in {"uploaded", "error", "label_created"}:
                results.append({"shipmentId": row["id"], "skipped": True, "reason": row.get("status")})
                continue
            res = self.generate_label(row["id"])
            results.append(res)
            if res.get("ok"):
                ok += 1
            else:
                failed += 1
        return {
            "ok": failed == 0,
            "tourId": tour_id,
            "processed": len(results),
            "labelsCreated": ok,
            "failed": failed,
            "results": results,
        }

    def build_tour_labels_zip(self, tour_ref: str) -> tuple[bytes, str]:
        tour_id = self.storage.resolve_tour_id(tour_ref)
        if not tour_id:
            raise ValueError("Tour nicht gefunden")
        tour = self.storage.get_tour(tour_id) or {}
        labels = self.storage.list_labels_for_tour(tour_id)
        entries: list[tuple[str, Path]] = []
        if labels:
            for label in labels:
                path = Path(label["label_path"]) if label.get("label_path") else None
                if path and path.is_file():
                    arc = f"TO{label['transport_order_number']}_Pos{label['item_number']}_P{label['piece_number']}{path.suffix}"
                    entries.append((arc, path))
        else:
            for row in self.storage.list_shipments_for_tour(tour_id):
                path = Path(row["label_path"]) if row.get("label_path") else None
                if path and path.is_file():
                    arc = f"TO{row['transport_order_number']}_Pos{row['item_number']}{path.suffix}"
                    entries.append((arc, path))
        if not entries:
            raise ValueError("Keine Labels für diese Tour vorhanden")
        tour_no = tour.get("tour_number") or tour_id[:8]
        return build_labels_zip(entries), f"WOG-Tour-{tour_no}-labels.zip"

    def build_tour_labels_pdf(self, tour_ref: str) -> tuple[bytes, str]:
        tour_id = self.storage.resolve_tour_id(tour_ref)
        if not tour_id:
            raise ValueError("Tour nicht gefunden")
        tour = self.storage.get_tour(tour_id) or {}
        paths: list[Path] = []
        labels = self.storage.list_labels_for_tour(tour_id)
        if labels:
            for label in labels:
                path = Path(label["label_path"]) if label.get("label_path") else None
                if path and path.is_file():
                    paths.append(path)
        else:
            for row in self.storage.list_shipments_for_tour(tour_id):
                path = Path(row["label_path"]) if row.get("label_path") else None
                if path and path.is_file():
                    paths.append(path)
        pdf_paths = [p for p in paths if p.suffix.lower() == ".pdf"]
        if not pdf_paths:
            if paths:
                raise ValueError("Labels sind noch ZPL – bitte neu erzeugen (Einstellung: PDF/A6)")
            raise ValueError("Keine Labels für diese Tour vorhanden")
        tour_no = tour.get("tour_number") or tour_id[:8]
        logo = self.settings.label_logo_path if self.settings.label_logo_enabled else None
        return (
            merge_pdf_files(
                pdf_paths,
                logo_path=logo,
                logo_width_pt=self.settings.label_logo_width_pt,
            ),
            f"WOG-Tour-{tour_no}-labels.pdf",
        )

    def fetch_shipment_tracking(self, shipment_id: str, *, refresh: bool = False) -> dict:
        row = self.storage.get_shipment(shipment_id)
        if not row:
            raise ValueError("Sendung nicht gefunden")
        ident = primary_identcode(row.get("identcode"))
        url = tracking_url(ident)
        cached = {}
        if row.get("draft_json"):
            try:
                cached = json.loads(row["draft_json"]).get("tracking") or {}
            except (json.JSONDecodeError, TypeError, AttributeError):
                cached = {}

        events: list[dict] = cached.get("events") or []
        summary = cached.get("summary") or ""
        error = cached.get("error") or ""

        synced_at = cached.get("synced_at") or ""
        global_status = cached.get("globalStatus") or ""

        if refresh and ident:
            try:
                info = self.tracking.fetch_shipment_info(ident)
                if not info:
                    raise ValueError("Sendung bei der Post noch nicht gefunden")
                raw = info.get("raw_events") or []
                events = self.tracking.format_events(raw)
                summary = self.tracking.latest_summary(raw, info=info) or (
                    "Zugestellt" if info.get("delivered") else "Elektronisch gemeldet"
                )
                status = self.tracking.map_status(raw, info=info)
                delivered = bool(info.get("delivered")) or status == "delivered"
                global_status = info.get("globalStatus") or ""
                # Status nur vorwärts setzen (nicht REPORTED → label_created zurückspringen)
                if status == "delivered" and row.get("status") != "delivered":
                    self.storage.update_shipment(shipment_id, status="delivered", delivered=True)
                elif status == "handed_over" and row.get("status") in {"uploaded", "label_created", "error"}:
                    self.storage.update_shipment(shipment_id, status="handed_over", delivered=False)
                synced_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
                self.storage.save_tracking_snapshot(
                    shipment_id,
                    {
                        "events": events,
                        "summary": summary,
                        "synced_at": synced_at,
                        "error": "",
                        "delivered": delivered,
                        "globalStatus": global_status,
                        "productStatus": info.get("productStatus") or "",
                    },
                )
                error = ""
                row = self.storage.get_shipment(shipment_id) or row
            except Exception as e:
                error = str(e)
                self.storage.save_tracking_snapshot(
                    shipment_id,
                    {
                        "events": events,
                        "summary": summary,
                        "error": error,
                        **({"synced_at": cached.get("synced_at")} if cached.get("synced_at") else {}),
                    },
                )

        # Leere Events + REPORTED ist kein Fehler
        if not error and not summary and global_status.upper() in {"REPORTED", "ANNOUNCED", "PREADVICED"}:
            summary = "Elektronisch gemeldet"

        return {
            "ok": not bool(error),
            "shipmentId": shipment_id,
            "identcode": ident,
            "trackingUrl": url,
            "summary": summary,
            "events": events,
            "error": error,
            "syncedAt": synced_at,
            "globalStatus": global_status,
            "delivered": row.get("status") == "delivered" or cached.get("delivered") is True,
            "deliveryProofAvailable": bool(ident) and (
                row.get("status") == "delivered" or cached.get("delivered") is True
            ),
        }


    @staticmethod
    def delivery_proof_export_name(shipment: dict) -> str:
        """Dateiname für FTP: {Auftragsnummer}.{ConsignmentNumber}.pdf z.B. 435958.1.pdf"""
        order_no = str(
            shipment.get("sendungsnummer")
            or shipment.get("external_order_number")
            or shipment.get("transport_order_number")
            or "ohne-auftrag"
        ).strip()
        cons_no = str(
            shipment.get("consignment_number")
            or shipment.get("item_number")
            or "1"
        ).strip() or "1"
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", f"{order_no}.{cons_no}")
        return f"{safe}.pdf"

    @classmethod
    def shippingnet_shipment_number(cls, shipment: dict) -> str:
        """shipping.NET Sendungsnummer: {Auftrag}.{Consignment} z.B. 435958.1"""
        return cls.delivery_proof_export_name(shipment).removesuffix(".pdf")

    def _shipment_meta(self, shipment_id: str, row: dict | None = None) -> dict:
        row = row or self.storage.get_shipment(shipment_id) or {}
        solo = self.storage.get_soloplan_refs(shipment_id) or {}
        meta = {**row, **solo}
        try:
            draft = json.loads(row.get("draft_json") or "{}")
        except (json.JSONDecodeError, TypeError, AttributeError):
            draft = {}
        for key in ("sendungsnummer", "consignment_number", "external_order_number", "external_number"):
            if not meta.get(key) and draft.get(key):
                meta[key] = draft[key]
        return meta

    def _resolve_delivery_datetime(self, shipment_id: str, status_date: datetime | str | None = None) -> str | None:
        """Echte Post-Zustellzeit ermitteln (nie aktuelles Datum als Fallback)."""
        if status_date is not None:
            iso = normalize_shippingnet_status_date(status_date)
            if iso:
                return iso
        meta = self._shipment_meta(shipment_id)
        try:
            cached = json.loads(meta.get("draft_json") or "{}").get("tracking") or {}
        except (json.JSONDecodeError, TypeError, AttributeError):
            cached = {}
        for key in ("deliveryDate", "lastEventDateTime", "delivered_at"):
            raw = cached.get(key) or meta.get(key)
            iso = normalize_shippingnet_status_date(raw)
            if iso:
                return iso
        # Live von der Post holen
        ident = primary_identcode(meta.get("identcode"))
        if ident:
            try:
                info = self.tracking.fetch_shipment_info(ident)
            except Exception:
                info = {}
            for key in ("deliveryDate", "lastEventDateTime"):
                iso = normalize_shippingnet_status_date(info.get(key) if info else None)
                if iso:
                    return iso
            # Zugestellt-Event aus Timeline
            for ev in self.tracking.format_events(info.get("raw_events") or []):
                title = (ev.get("title") or "").lower()
                if "zugestellt" in title or "delivered" in title:
                    iso = normalize_shippingnet_status_date(ev.get("at"))
                    if iso:
                        return iso
        return None

    def push_shippingnet_delivered(
        self,
        shipment_id: str,
        *,
        status_date: datetime | str | None = None,
        force: bool = False,
    ) -> dict:
        """Setzt in shipping.NET den Status DVD (Zugestellt) mit echter Zustellzeit."""
        if not self.shippingnet.enabled:
            return {"ok": False, "skipped": True, "reason": "not_configured"}
        meta = self._shipment_meta(shipment_id)
        number = self.shippingnet_shipment_number(meta)
        cached = {}
        try:
            cached = json.loads(meta.get("draft_json") or "{}").get("tracking") or {}
        except (json.JSONDecodeError, TypeError, AttributeError):
            cached = {}
        if cached.get("shippingnet_dvd_at") and not force:
            return {
                "ok": True,
                "skipped": True,
                "reason": "already_pushed",
                "shipmentNumber": number,
                "shippingnet_dvd_at": cached.get("shippingnet_dvd_at"),
            }
        resolved = self._resolve_delivery_datetime(shipment_id, status_date)
        if not resolved:
            err = "Keine echte Zustellzeit von der Post verfügbar"
            self.storage.save_tracking_snapshot(
                shipment_id,
                {**cached, "shippingnet_error": err, "shippingnet_shipment_number": number},
            )
            return {"ok": False, "shipmentNumber": number, "error": err}
        try:
            result = self.shippingnet.mark_delivered(
                number,
                description="Zugestellt",
                status_date=resolved,
            )
            now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            self.storage.save_tracking_snapshot(
                shipment_id,
                {
                    **cached,
                    "shippingnet_dvd_at": now,
                    "shippingnet_status_date": resolved,
                    "shippingnet_shipment_number": number,
                    "shippingnet_error": "",
                    "shippingnet_response": result if isinstance(result, dict) else {"raw": str(result)},
                },
            )
            return {"ok": True, "shipmentNumber": number, "result": result}
        except ShippingNetError as e:
            self.storage.save_tracking_snapshot(
                shipment_id,
                {
                    **cached,
                    "shippingnet_error": str(e),
                    "shippingnet_shipment_number": number,
                },
            )
            return {"ok": False, "shipmentNumber": number, "error": str(e)}

    def export_delivery_proof_file(self, shipment_id: str, pdf: bytes, shipment: dict | None = None) -> Path:
        """Speichert Ablieferbeleg zusätzlich im SFTP-Ordner für Abholung."""
        row = shipment or self.storage.get_shipment(shipment_id) or {}
        solo = self.storage.get_soloplan_refs(shipment_id) or {}
        meta = {**row, **solo}
        try:
            draft = json.loads((row.get("draft_json") or "{}"))
            for key in ("sendungsnummer", "consignment_number", "external_order_number", "external_number"):
                if not meta.get(key) and draft.get(key):
                    meta[key] = draft[key]
        except (json.JSONDecodeError, TypeError, AttributeError):
            pass
        name = self.delivery_proof_export_name(meta)
        export_dir = Path(self.settings.delivery_proofs_export_dir)
        export_dir.mkdir(parents=True, exist_ok=True)
        path = export_dir / name
        path.write_bytes(pdf)
        try:
            path.chmod(0o664)
        except OSError:
            pass
        return path

    def build_delivery_proof(self, shipment_id: str) -> tuple[bytes, str]:
        from app.delivery_proof import build_delivery_proof_pdf

        row = self.storage.get_shipment(shipment_id)
        if not row:
            raise ValueError("Sendung nicht gefunden")
        ident = primary_identcode(row.get("identcode"))
        if not ident:
            raise ValueError("Kein Identcode – Zustellnachweis erst nach Label möglich")

        idents = [x.strip() for x in str(row.get("identcode") or "").split(",") if x.strip()]
        info = self.tracking.fetch_shipment_info(ident)
        event_lists: list[list[dict]] = []
        for code in idents:
            piece_info = self.tracking.fetch_shipment_info(code) if code != ident else info
            if not piece_info:
                continue
            raw = piece_info.get("raw_events") or []
            formatted = self.tracking.format_events(raw)
            # Mehrere Colli: Identcode im Detail vermerken
            if len(idents) > 1:
                for ev in formatted:
                    detail = (ev.get("detail") or "").strip()
                    tag = f"Paket {code}"
                    if tag not in detail:
                        ev["detail"] = f"{detail} · {tag}".strip(" ·") if detail else tag
            event_lists.append(formatted)
            if piece_info.get("delivered"):
                info = {**info, **{k: piece_info.get(k) for k in (
                    "delivered", "deliveryDate", "globalStatus", "summary", "addressee",
                    "creationDateTime", "sendingDateTime", "lastEventDateTime",
                ) if piece_info.get(k) is not None}}
        events = self.tracking.merge_formatted_events(*event_lists)
        raw_events = info.get("raw_events") or []
        summary = self.tracking.latest_summary(raw_events, info=info)
        delivered = row.get("status") == "delivered" or info.get("delivered") or self.tracking.map_status(raw_events, info=info) == "delivered"
        if not delivered:
            raise ValueError("Sendung noch nicht zugestellt – Ablieferbeleg nicht verfügbar")

        soloplan = self.storage.get_soloplan_refs(shipment_id) or {}
        shipment = {**row, **soloplan}
        # externe Nummern ggf. aus Draft nachziehen
        try:
            draft = json.loads(row.get("draft_json") or "{}")
        except (json.JSONDecodeError, TypeError):
            draft = {}
        if not shipment.get("external_order_number") and draft.get("external_order_number"):
            shipment["external_order_number"] = draft.get("external_order_number")
        if not shipment.get("external_number") and draft.get("external_number"):
            shipment["external_number"] = draft.get("external_number")

        pdf = build_delivery_proof_pdf(shipment=shipment, tracking_info=info, events=events)

        sendung = shipment.get("sendungsnummer") or ident
        filename = f"Zustellnachweis-{sendung}.pdf".replace("/", "-")
        path = self.storage.delivery_proofs_dir / f"{shipment_id}.pdf"
        path.write_bytes(pdf)
        export_path = self.export_delivery_proof_file(shipment_id, pdf, shipment)
        cached = {}
        if row.get("draft_json"):
            try:
                cached = json.loads(row["draft_json"]).get("tracking") or {}
            except (json.JSONDecodeError, TypeError, AttributeError):
                cached = {}
        self.storage.save_tracking_snapshot(
            shipment_id,
            {
                **cached,
                "events": events,
                "summary": summary or cached.get("summary") or "Zugestellt",
                "delivered": True,
                "delivery_proof_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                "delivery_proof_export": str(export_path.name),
                "delivery_proof_export_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            },
        )
        return pdf, filename

    def sync_tracking(self) -> dict:
        updated = 0
        checked = 0
        proofs_generated = 0
        shippingnet_pushed = 0
        errors: list[str] = []
        for row in self.storage.list_trackable_shipments():
            checked += 1
            idents = [x.strip() for x in str(row.get("identcode") or "").split(",") if x.strip()]
            if not idents:
                continue
            try:
                info = self.tracking.fetch_shipment_info(idents[0])
                if not info:
                    continue
                raw = info.get("raw_events") or []
                events = self.tracking.format_events(raw)
                summary = self.tracking.latest_summary(raw, info=info)
                status = self.tracking.map_status(raw, info=info)
                self.storage.save_tracking_snapshot(
                    row["id"],
                    {
                        "events": events,
                        "summary": summary,
                        "synced_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                        "error": "",
                        "delivered": bool(info.get("delivered")),
                        "globalStatus": info.get("globalStatus") or "",
                        "productStatus": info.get("productStatus") or "",
                    },
                )
                newly_delivered = status == "delivered" and row.get("status") != "delivered"
                if newly_delivered:
                    self.storage.update_shipment(row["id"], status="delivered", delivered=True)
                    updated += 1
                elif status == "handed_over" and row.get("status") in {"uploaded", "label_created", "error"}:
                    self.storage.update_shipment(row["id"], status="handed_over", delivered=False)
                    updated += 1

                is_delivered = newly_delivered or row.get("status") == "delivered" or status == "delivered"
                if is_delivered:
                    cached = {}
                    if row.get("draft_json"):
                        try:
                            cached = json.loads(row["draft_json"]).get("tracking") or {}
                        except (json.JSONDecodeError, TypeError, AttributeError):
                            cached = {}
                    export_name = cached.get("delivery_proof_export") or ""
                    export_path = Path(self.settings.delivery_proofs_export_dir) / export_name if export_name else None
                    needs_export = not export_name or not export_path or not export_path.is_file()
                    if needs_export:
                        try:
                            self.build_delivery_proof(row["id"])
                            proofs_generated += 1
                        except Exception as pe:
                            errors.append(f"{row['id']} proof: {pe}")
                    # shipping.NET Status DVD setzen (einmalig)
                    try:
                        sn = self.push_shippingnet_delivered(
                            row["id"],
                            status_date=info.get("deliveryDate") or info.get("lastEventDateTime"),
                        )
                        if sn.get("ok") and not sn.get("skipped"):
                            shippingnet_pushed += 1
                        elif not sn.get("ok") and not sn.get("skipped"):
                            errors.append(f"{row['id']} shippingnet: {sn.get('error')}")
                    except Exception as se:
                        errors.append(f"{row['id']} shippingnet: {se}")
            except Exception as e:
                errors.append(f"{row['id']}: {e}")
        return {
            "ok": True,
            "checked": checked,
            "updated": updated,
            "proofs_generated": proofs_generated,
            "shippingnet_pushed": shippingnet_pushed,
            "errors": errors[:20],
        }

    def process_incoming_dir(self) -> list[dict]:
        incoming = self.settings.incoming_dir
        incoming.mkdir(parents=True, exist_ok=True)
        (incoming / "processed").mkdir(exist_ok=True)
        (incoming / "error").mkdir(exist_ok=True)
        results = []
        paths = sorted(incoming.glob("*.json")) + sorted(incoming.glob("*.JSON"))
        for path in paths:
            if not path.is_file():
                continue
            try:
                content = path.read_bytes()
                res = self.ingest_bytes(path.name, content, auto_label=False)
                done = incoming / "processed" / path.name
                path.rename(done)
                results.append({"file": path.name, **res})
            except Exception as e:
                err = incoming / "error" / path.name
                if path.exists():
                    path.rename(err)
                results.append({"file": path.name, "ok": False, "error": str(e)})
        return results

    def backfill_shipments_from_tours(self) -> dict:
        updated = 0
        created = 0
        skipped = 0
        for tour in self.storage.list_tours():
            tour_id = tour["id"]
            source_file = tour.get("source_file") or ""
            path = self.storage.find_tour_file(source_file)
            if not path or not path.is_file():
                skipped += len(self.storage.list_shipments_for_tour(tour_id))
                continue
            data = coerce_tour_document(json.loads(path.read_bytes().decode("utf-8-sig")))
            meta, drafts = parse_tour_json(
                data,
                reference_filter=self.settings.consignment_reference_filter,
                carrier_filter=self.settings.carrier_matchcode_filter,
                default_weight=self.settings.default_weight_grams,
            )
            self.storage.update_tour_meta(tour_id, meta)
            by_key = {(d.transport_order_number, d.item_number): d for d in drafts}
            existing_keys = {
                (int(row["transport_order_number"]), int(row["item_number"]))
                for row in self.storage.list_shipments_for_tour(tour_id)
            }
            for row in self.storage.list_shipments_for_tour(tour_id):
                draft = by_key.get((int(row["transport_order_number"]), int(row["item_number"])))
                if not draft:
                    skipped += 1
                    continue
                product_id = row.get("delivery_product_id") or "eco"
                self.storage.update_shipment_details(
                    row["id"],
                    draft_to_dict(draft, delivery_product_id=product_id),
                )
                updated += 1
            for key, draft in by_key.items():
                if key in existing_keys:
                    continue
                self.storage.add_shipment(tour_id, draft)
                created += 1
        return {"ok": True, "updated": updated, "created": created, "skipped": skipped}

    def import_billing_file(self, filename: str, content: bytes) -> dict:
        from app.invoice_import import is_surcharge_hint, parse_billing_file

        parsed = parse_billing_file(content, filename)
        lines_out: list[dict] = []
        surcharge_hints = 0
        matched_examples: list[dict] = []
        for line in parsed.lines:
            shipment_id = None
            match_method = None
            if line.identcode:
                shipment_id = self.storage.find_shipment_id_by_identcode(line.identcode)
                if shipment_id:
                    match_method = "identcode"
            if not shipment_id and line.customer_ref:
                shipment_id = self.storage.find_shipment_id_by_reference(line.customer_ref)
                if shipment_id:
                    match_method = "soloplan_ref"
            if line.product_label and is_surcharge_hint(line.product_label):
                surcharge_hints += 1
            entry = {
                "identcode": line.identcode,
                "amount_cents": line.amount_cents,
                "product_label": line.product_label,
                "invoice_number": line.invoice_number or parsed.invoice_number,
                "billing_period": line.billing_period or parsed.billing_period,
                "customer_ref": line.customer_ref,
                "shipment_id": shipment_id,
                "match_method": match_method,
                "raw": line.raw,
            }
            lines_out.append(entry)
            if shipment_id and len(matched_examples) < 5:
                refs = self.storage.get_soloplan_refs(shipment_id) or {}
                matched_examples.append(
                    {
                        "identcode": line.identcode or None,
                        "customer_ref": line.customer_ref or None,
                        "match_method": match_method,
                        "soloplan_label": refs.get("soloplan_label"),
                        "item_id": refs.get("item_id"),
                    }
                )
        result = self.storage.save_billing_import(
            filename,
            lines_out,
            invoice_number=parsed.invoice_number,
            billing_period=parsed.billing_period,
            meta={
                "header_row": parsed.header_row,
                "columns": parsed.columns,
                "warnings": parsed.warnings,
                "surcharge_hints": surcharge_hints,
            },
        )
        total_cents = sum(l["amount_cents"] for l in lines_out)
        return {
            "ok": True,
            "filename": filename,
            "invoice_number": parsed.invoice_number or None,
            "billing_period": parsed.billing_period or None,
            "header_row": parsed.header_row,
            "warnings": parsed.warnings,
            "total_chf": round(total_cents / 100, 2),
            "surcharge_hints": surcharge_hints,
            "matched_examples": matched_examples,
            **result,
        }
