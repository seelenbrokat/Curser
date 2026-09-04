from __future__ import annotations

import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from app.address_book import AddressBook
from app.draft_util import draft_to_dict

STATUSES = ("uploaded", "label_created", "handed_over", "delivered", "error", "skipped")
OPEN_STATUSES = ("uploaded", "label_created", "handed_over", "error")

_EXTRA_COLUMNS = [
    ("draft_json", "TEXT"),
    ("delivery_product_id", "TEXT"),
    ("recipient_street", "TEXT"),
    ("recipient_zip", "TEXT"),
    ("recipient_country", "TEXT"),
    ("recipient_email", "TEXT"),
    ("weight_grams", "INTEGER"),
    ("packstuecke", "INTEGER"),
    ("sendungsnummer", "TEXT"),
    ("external_order_number", "TEXT"),
    ("consignment_number", "TEXT"),
]

_TOUR_EXTRA_COLUMNS = [
    ("ext_tour_number", "TEXT"),
    ("tour_planned_date", "TEXT"),
]


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Storage:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.db_path = data_dir / "wog-connect.db"
        self.tours_dir = data_dir / "tours"
        self.labels_dir = data_dir / "labels"
        self.delivery_proofs_dir = data_dir / "delivery_proofs"
        for p in (self.data_dir, self.tours_dir, self.labels_dir, self.delivery_proofs_dir):
            p.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _ensure_columns(self, conn: sqlite3.Connection) -> None:
        existing = {r[1] for r in conn.execute("PRAGMA table_info(shipments)")}
        for name, typedef in _EXTRA_COLUMNS:
            if name not in existing:
                conn.execute(f"ALTER TABLE shipments ADD COLUMN {name} {typedef}")
        tour_cols = {r[1] for r in conn.execute("PRAGMA table_info(tours)")}
        for name, typedef in _TOUR_EXTRA_COLUMNS:
            if name not in tour_cols:
                conn.execute(f"ALTER TABLE tours ADD COLUMN {name} {typedef}")

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS tours (
                  id TEXT PRIMARY KEY,
                  tour_number TEXT,
                  carrier_matchcode TEXT,
                  export_reference TEXT,
                  source_file TEXT,
                  uploaded_at TEXT,
                  meta_json TEXT
                );
                CREATE TABLE IF NOT EXISTS shipments (
                  id TEXT PRIMARY KEY,
                  tour_id TEXT,
                  transport_order_number INTEGER,
                  item_number INTEGER,
                  item_id TEXT,
                  recipient_name TEXT,
                  recipient_city TEXT,
                  consignment_reference TEXT,
                  external_number TEXT,
                  identcode TEXT,
                  status TEXT,
                  error_message TEXT,
                  label_path TEXT,
                  label_format TEXT,
                  created_at TEXT,
                  updated_at TEXT,
                  delivered_at TEXT,
                  post_response_json TEXT,
                  request_json TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_shipments_status ON shipments(status);
                CREATE INDEX IF NOT EXISTS idx_shipments_tour ON shipments(tour_id);
                CREATE TABLE IF NOT EXISTS shipment_labels (
                  id TEXT PRIMARY KEY,
                  shipment_id TEXT NOT NULL,
                  piece_number INTEGER NOT NULL,
                  identcode TEXT,
                  label_path TEXT,
                  label_format TEXT,
                  created_at TEXT,
                  UNIQUE(shipment_id, piece_number)
                );
                CREATE INDEX IF NOT EXISTS idx_shipment_labels_shipment ON shipment_labels(shipment_id);
                CREATE INDEX IF NOT EXISTS idx_tours_export_reference ON tours(export_reference);
                CREATE INDEX IF NOT EXISTS idx_shipments_tour_item ON shipments(tour_id, transport_order_number, item_number);
                """
            )
            self._ensure_columns(conn)
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS billing_imports (
                  id TEXT PRIMARY KEY,
                  filename TEXT,
                  invoice_number TEXT,
                  billing_period TEXT,
                  imported_at TEXT,
                  row_count INTEGER,
                  matched_count INTEGER,
                  meta_json TEXT
                );
                CREATE TABLE IF NOT EXISTS billing_lines (
                  id TEXT PRIMARY KEY,
                  import_id TEXT NOT NULL,
                  identcode TEXT NOT NULL,
                  amount_cents INTEGER NOT NULL,
                  currency TEXT DEFAULT 'CHF',
                  product_label TEXT,
                  invoice_number TEXT,
                  billing_period TEXT,
                  shipment_id TEXT,
                  raw_json TEXT,
                  created_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_billing_lines_ident ON billing_lines(identcode);
                CREATE INDEX IF NOT EXISTS idx_billing_lines_shipment ON billing_lines(shipment_id);
                CREATE INDEX IF NOT EXISTS idx_billing_lines_import ON billing_lines(import_id);
                """
            )
            billing_cols = {r[1] for r in conn.execute("PRAGMA table_info(billing_lines)")}
            for name, typedef in (("customer_ref", "TEXT"), ("match_method", "TEXT")):
                if name not in billing_cols:
                    conn.execute(f"ALTER TABLE billing_lines ADD COLUMN {name} {typedef}")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS recipient_address_book (
                  id TEXT PRIMARY KEY,
                  soloplan_matchcode TEXT,
                  soloplan_bp_id TEXT,
                  name_zip_key TEXT,
                  name1 TEXT NOT NULL,
                  name2 TEXT,
                  street TEXT NOT NULL,
                  zip_code TEXT NOT NULL,
                  city TEXT NOT NULL,
                  country TEXT NOT NULL DEFAULT 'CH',
                  email TEXT,
                  notes TEXT,
                  source_shipment_id TEXT,
                  created_at TEXT,
                  updated_at TEXT
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_addrbook_matchcode
                  ON recipient_address_book(soloplan_matchcode)
                  WHERE soloplan_matchcode IS NOT NULL AND soloplan_matchcode != '';
                CREATE INDEX IF NOT EXISTS idx_addrbook_namezip
                  ON recipient_address_book(name_zip_key);
                """
            )

    def save_tour_file(self, filename: str, content: bytes) -> Path:
        safe = filename.replace("/", "_").replace("\\", "_")
        path = self.tours_dir / f"{uuid.uuid4().hex}_{safe}"
        path.write_bytes(content)
        return path

    def create_tour(self, meta: dict[str, Any], source_file: str) -> str:
        tour_id = uuid.uuid4().hex
        planned = meta.get("plannedStartTime") or meta.get("sendDate")
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO tours (
                  id, tour_number, ext_tour_number, tour_planned_date,
                  carrier_matchcode, export_reference, source_file, uploaded_at, meta_json
                ) VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    tour_id,
                    str(meta.get("tourNumber", "")),
                    str(meta.get("extTourNumber") or ""),
                    planned,
                    meta.get("carrierMatchcode"),
                    meta.get("exportReference"),
                    source_file,
                    _now(),
                    json.dumps(meta, ensure_ascii=False),
                ),
            )
        return tour_id

    def update_tour_meta(self, tour_id: str, meta: dict[str, Any]) -> None:
        planned = meta.get("plannedStartTime") or meta.get("sendDate")
        with self._conn() as conn:
            conn.execute(
                """UPDATE tours SET
                  tour_number = ?, ext_tour_number = ?, tour_planned_date = ?,
                  carrier_matchcode = ?, export_reference = ?, meta_json = ?
                WHERE id = ?""",
                (
                    str(meta.get("tourNumber", "")),
                    str(meta.get("extTourNumber") or ""),
                    planned,
                    meta.get("carrierMatchcode"),
                    meta.get("exportReference"),
                    json.dumps(meta, ensure_ascii=False),
                    tour_id,
                ),
            )

    def add_shipment(self, tour_id: str, draft, status: str = "uploaded", delivery_product_id: str = "eco") -> str:
        sid = uuid.uuid4().hex
        now = _now()
        draft_data = draft_to_dict(draft, delivery_product_id=delivery_product_id)
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO shipments (
                  id, tour_id, transport_order_number, item_number, item_id,
                  recipient_name, recipient_city, consignment_reference, external_number,
                  identcode, status, error_message, label_path, label_format,
                  created_at, updated_at, delivered_at, post_response_json, request_json,
                  draft_json, delivery_product_id, recipient_street, recipient_zip,
                  recipient_country, recipient_email, weight_grams, packstuecke, sendungsnummer,
                  external_order_number, consignment_number
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    sid, tour_id, draft.transport_order_number, draft.item_number, draft.item_id,
                    draft.recipient.name1, draft.recipient.city, draft.consignment_reference, draft.external_number,
                    None, status, None, None, None, now, now, None, None, None,
                    json.dumps(draft_data, ensure_ascii=False), delivery_product_id,
                    draft.recipient.street, draft.recipient.zip_code, draft.recipient.country,
                    draft.recipient.email, draft.weight_grams, draft.packstuecke, draft.sendungsnummer,
                    getattr(draft, "external_order_number", "") or "",
                    getattr(draft, "consignment_number", "") or "",
                ),
            )
        return sid

    def update_shipment_details(self, shipment_id: str, draft_data: dict[str, Any]) -> None:
        recipient = draft_data.get("recipient") or {}
        with self._conn() as conn:
            conn.execute(
                """UPDATE shipments SET
                  draft_json = ?, delivery_product_id = ?,
                  recipient_name = ?, recipient_street = ?, recipient_zip = ?,
                  recipient_city = ?, recipient_country = ?, recipient_email = ?,
                  weight_grams = ?, packstuecke = ?, sendungsnummer = ?,
                  external_number = ?, external_order_number = ?, consignment_number = ?,
                  updated_at = ?
                WHERE id = ?""",
                (
                    json.dumps(draft_data, ensure_ascii=False),
                    draft_data.get("delivery_product_id", "eco"),
                    recipient.get("name1"), recipient.get("street"), recipient.get("zip_code"),
                    recipient.get("city"), recipient.get("country"), recipient.get("email"),
                    int(draft_data.get("weight_grams") or 1000),
                    max(1, int(draft_data.get("packstuecke") or 1)),
                    str(draft_data.get("sendungsnummer") or ""),
                    str(draft_data.get("external_number") or ""),
                    str(draft_data.get("external_order_number") or ""),
                    str(draft_data.get("consignment_number") or ""),
                    _now(), shipment_id,
                ),
            )

    def save_address_validation(self, shipment_id: str, validation: dict[str, Any]) -> None:
        row = self.get_shipment(shipment_id)
        if not row:
            return
        base: dict[str, Any] = {}
        if row.get("draft_json"):
            try:
                base = json.loads(row["draft_json"])
            except json.JSONDecodeError:
                base = {}
        base["address_validation"] = validation
        with self._conn() as conn:
            conn.execute(
                "UPDATE shipments SET draft_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(base, ensure_ascii=False), _now(), shipment_id),
            )

    def save_tracking_snapshot(self, shipment_id: str, snapshot: dict[str, Any]) -> None:
        row = self.get_shipment(shipment_id)
        if not row:
            return
        base: dict[str, Any] = {}
        if row.get("draft_json"):
            try:
                base = json.loads(row["draft_json"])
            except json.JSONDecodeError:
                base = {}
        base["tracking"] = snapshot
        with self._conn() as conn:
            conn.execute(
                "UPDATE shipments SET draft_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(base, ensure_ascii=False), _now(), shipment_id),
            )

    def list_tours(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM tours ORDER BY uploaded_at").fetchall()
        return [dict(r) for r in rows]

    def list_shipments_for_tour(self, tour_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM shipments WHERE tour_id = ? ORDER BY transport_order_number, item_number",
                (tour_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def find_tour_file(self, source_file: str) -> Path | None:
        matches = list(self.tours_dir.glob(f"*_{source_file}"))
        if not matches:
            matches = list(self.tours_dir.glob(source_file))
        if not matches:
            return None
        return max(matches, key=lambda p: p.stat().st_mtime)

    def list_shipments(
        self,
        status: str | None = None,
        open_only: bool = False,
        tour_number: str | None = None,
        date: str | None = None,
        q: str | None = None,
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT s.*, t.tour_number, t.ext_tour_number, t.tour_planned_date, t.uploaded_at AS tour_uploaded_at,
                   (SELECT COUNT(*) FROM shipment_labels sl WHERE sl.shipment_id = s.id) AS label_count
            FROM shipments s
            JOIN tours t ON t.id = s.tour_id
            WHERE 1=1
        """
        params: list[Any] = []
        if open_only:
            sql += f" AND s.status IN ({','.join('?' for _ in OPEN_STATUSES)})"
            params.extend(OPEN_STATUSES)
        elif status:
            sql += " AND s.status = ?"
            params.append(status)
        if tour_number:
            sql += " AND (t.tour_number = ? OR t.ext_tour_number = ?)"
            params.extend([tour_number.strip(), tour_number.strip()])
        # Nummernsuche: ohne Datumsfilter, sonst findet man alte Labels nicht
        search = (q or "").strip()
        if search:
            like = f"%{search}%"
            digits = re.sub(r"\D", "", search)
            sql += """ AND (
                IFNULL(s.sendungsnummer, '') LIKE ?
                OR IFNULL(s.identcode, '') LIKE ?
                OR IFNULL(s.item_id, '') LIKE ?
                OR IFNULL(s.external_number, '') LIKE ?
                OR IFNULL(s.external_order_number, '') LIKE ?
                OR EXISTS (
                    SELECT 1 FROM shipment_labels sl
                    WHERE sl.shipment_id = s.id AND IFNULL(sl.identcode, '') LIKE ?
                )
            """
            params.extend([like, like, like, like, like, like])
            if digits and digits != search:
                dlike = f"%{digits}%"
                sql += """ OR REPLACE(REPLACE(IFNULL(s.identcode, ''), ' ', ''), '-', '') LIKE ?
                    OR EXISTS (
                        SELECT 1 FROM shipment_labels sl
                        WHERE sl.shipment_id = s.id
                          AND REPLACE(REPLACE(IFNULL(sl.identcode, ''), ' ', ''), '-', '') LIKE ?
                    )"""
                params.extend([dlike, dlike])
            sql += ")"
        elif date:
            day = date.strip()[:10]
            sql += """ AND (
                date(substr(t.tour_planned_date, 1, 10)) = ?
                OR date(substr(t.uploaded_at, 1, 10)) = ?
                OR date(substr(s.created_at, 1, 10)) = ?
            )"""
            params.extend([day, day, day])
        sql += " ORDER BY s.created_at DESC"
        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def find_tour_by_export_reference(self, export_reference: str) -> dict[str, Any] | None:
        if not export_reference:
            return None
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM tours WHERE export_reference = ? ORDER BY uploaded_at DESC LIMIT 1",
                (export_reference.strip(),),
            ).fetchone()
        return dict(row) if row else None

    def find_tour_by_number(
        self,
        tour_number: str,
        *,
        ext_tour_number: str = "",
        planned_date: str = "",
    ) -> dict[str, Any] | None:
        tn = str(tour_number or "").strip()
        ext = str(ext_tour_number or "").strip()
        if not tn and not ext:
            return None
        day = str(planned_date or "").strip()[:10]
        with self._conn() as conn:
            if day:
                row = conn.execute(
                    """SELECT * FROM tours
                       WHERE (tour_number = ? OR ext_tour_number = ? OR tour_number = ? OR ext_tour_number = ?)
                       AND (
                         substr(COALESCE(tour_planned_date, ''), 1, 10) = ?
                         OR substr(COALESCE(uploaded_at, ''), 1, 10) = ?
                       )
                       ORDER BY uploaded_at DESC LIMIT 1""",
                    (tn, tn, ext, ext, day, day),
                ).fetchone()
            else:
                row = conn.execute(
                    """SELECT * FROM tours
                       WHERE tour_number = ? OR ext_tour_number = ? OR tour_number = ? OR ext_tour_number = ?
                       ORDER BY uploaded_at DESC LIMIT 1""",
                    (tn, tn, ext, ext),
                ).fetchone()
        return dict(row) if row else None

    def get_tour(self, tour_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM tours WHERE id = ?", (tour_id,)).fetchone()
        return dict(row) if row else None

    def resolve_tour_id(self, tour_ref: str) -> str | None:
        ref = (tour_ref or "").strip()
        if not ref:
            return None
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id FROM tours WHERE id = ? OR tour_number = ? OR ext_tour_number = ? ORDER BY uploaded_at DESC LIMIT 1",
                (ref, ref, ref),
            ).fetchone()
        return row[0] if row else None

    def find_shipment_key(self, tour_id: str, transport_order_number: int, item_number: int) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                """SELECT * FROM shipments
                   WHERE tour_id = ? AND transport_order_number = ? AND item_number = ?""",
                (tour_id, transport_order_number, item_number),
            ).fetchone()
        return dict(row) if row else None

    def replace_shipment_labels(self, shipment_id: str, labels: list[dict[str, Any]]) -> None:
        now = _now()
        with self._conn() as conn:
            conn.execute("DELETE FROM shipment_labels WHERE shipment_id = ?", (shipment_id,))
            for label in labels:
                conn.execute(
                    """INSERT INTO shipment_labels (id, shipment_id, piece_number, identcode, label_path, label_format, created_at)
                       VALUES (?,?,?,?,?,?,?)""",
                    (
                        uuid.uuid4().hex,
                        shipment_id,
                        int(label["piece_number"]),
                        label.get("identcode"),
                        label.get("label_path"),
                        label.get("label_format"),
                        now,
                    ),
                )

    def list_shipment_labels(self, shipment_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM shipment_labels WHERE shipment_id = ? ORDER BY piece_number",
                (shipment_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_labels_for_tour(self, tour_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT sl.*, s.transport_order_number, s.item_number, s.recipient_name
                   FROM shipment_labels sl
                   JOIN shipments s ON s.id = sl.shipment_id
                   WHERE s.tour_id = ?
                   ORDER BY s.transport_order_number, s.item_number, sl.piece_number""",
                (tour_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_trackable_shipments(self) -> list[dict[str, Any]]:
        """Sendungen mit Identcode, die noch getrackt werden sollen.

        Inkl. kürzlich zugestellte (Woche), damit der Status stabil bleibt
        und Ablieferbelege nachgezogen werden können.
        """
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT s.*, t.tour_number FROM shipments s
                   JOIN tours t ON t.id = s.tour_id
                   WHERE s.identcode IS NOT NULL AND s.identcode != ''
                     AND (
                       s.status IN ('label_created', 'handed_over')
                       OR (
                         s.status = 'delivered'
                         AND substr(COALESCE(s.updated_at, s.created_at), 1, 10)
                             >= date('now', '-7 day')
                       )
                     )
                   ORDER BY s.updated_at DESC"""
            ).fetchall()
        return [dict(r) for r in rows]

    def list_tour_filters(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT tour_number, ext_tour_number, tour_planned_date, uploaded_at, COUNT(s.id) AS shipment_count
                   FROM tours t
                   LEFT JOIN shipments s ON s.tour_id = t.id
                   GROUP BY t.id
                   ORDER BY t.uploaded_at DESC"""
            ).fetchall()
        return [dict(r) for r in rows]

    def get_shipment(self, shipment_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM shipments WHERE id = ?", (shipment_id,)).fetchone()
        return dict(row) if row else None

    def update_shipment(
        self,
        shipment_id: str,
        *,
        status: str | None = None,
        identcode: str | None = None,
        error_message: str | None = None,
        label_path: str | None = None,
        label_format: str | None = None,
        post_response: dict | None = None,
        request_body: dict | None = None,
        delivered: bool = False,
    ) -> None:
        fields: list[str] = ["updated_at = ?"]
        values: list[Any] = [_now()]
        if status is not None:
            fields.append("status = ?")
            values.append(status)
        if identcode is not None:
            fields.append("identcode = ?")
            values.append(identcode)
        if error_message is not None:
            fields.append("error_message = ?")
            values.append(error_message)
        if label_path is not None:
            fields.append("label_path = ?")
            values.append(label_path)
        if label_format is not None:
            fields.append("label_format = ?")
            values.append(label_format)
        if post_response is not None:
            fields.append("post_response_json = ?")
            values.append(json.dumps(post_response, ensure_ascii=False))
        if request_body is not None:
            fields.append("request_json = ?")
            values.append(json.dumps(request_body, ensure_ascii=False))
        if delivered:
            fields.append("delivered_at = ?")
            values.append(_now())
        values.append(shipment_id)
        with self._conn() as conn:
            conn.execute(f"UPDATE shipments SET {', '.join(fields)} WHERE id = ?", values)

    def export_status_for_wog(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT s.transport_order_number, s.item_number, s.item_id, s.identcode,
                          s.status, s.updated_at, s.delivered_at, s.external_number,
                          s.delivery_product_id, t.tour_number
                   FROM shipments s JOIN tours t ON t.id = s.tour_id
                   ORDER BY s.updated_at DESC"""
            ).fetchall()
        return [dict(r) for r in rows]

    def find_shipment_id_by_identcode(self, identcode: str) -> str | None:
        norm = re.sub(r"\D", "", identcode or "")
        if not norm:
            return None
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT id, identcode FROM shipments
                   WHERE identcode IS NOT NULL AND identcode != ''"""
            ).fetchall()
            for row in rows:
                stored = row["identcode"] or ""
                for part in stored.split(","):
                    part_norm = re.sub(r"\D", "", part.strip())
                    if part_norm and (part_norm == norm or part_norm.endswith(norm) or norm.endswith(part_norm)):
                        return row["id"]
            label_row = conn.execute(
                """SELECT shipment_id, identcode FROM shipment_labels
                   WHERE identcode IS NOT NULL AND identcode != ''"""
            ).fetchall()
            for row in label_row:
                part_norm = re.sub(r"\D", "", (row["identcode"] or "").strip())
                if part_norm and (part_norm == norm or part_norm.endswith(norm) or norm.endswith(part_norm)):
                    return row["shipment_id"]
        return None

    def find_shipment_id_by_reference(self, ref: str) -> str | None:
        from app.reference_util import normalize_reference_token

        raw = (ref or "").strip()
        if not raw:
            return None
        base = normalize_reference_token(raw)
        with self._conn() as conn:
            for candidate in (raw, base):
                if not candidate:
                    continue
                row = conn.execute(
                    "SELECT id FROM shipments WHERE sendungsnummer = ? LIMIT 1",
                    (candidate,),
                ).fetchone()
                if row:
                    return row["id"]
            for candidate in (raw, base):
                if not candidate:
                    continue
                row = conn.execute(
                    "SELECT id FROM shipments WHERE item_id = ? LIMIT 1",
                    (candidate,),
                ).fetchone()
                if row:
                    return row["id"]
            m = re.match(r"^(\d+)-(\d+)$", base)
            if m:
                row = conn.execute(
                    """SELECT id FROM shipments
                       WHERE transport_order_number = ? AND item_number = ?
                       ORDER BY created_at DESC LIMIT 1""",
                    (int(m.group(1)), int(m.group(2))),
                ).fetchone()
                if row:
                    return row["id"]
            row = conn.execute(
                "SELECT id FROM shipments WHERE external_number = ? ORDER BY created_at DESC LIMIT 1",
                (raw,),
            ).fetchone()
            if row:
                return row["id"]
        return None

    def get_soloplan_refs(self, shipment_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                """SELECT s.transport_order_number, s.item_number, s.item_id, s.external_number,
                          s.external_order_number, s.consignment_number, s.sendungsnummer,
                          t.tour_number, t.ext_tour_number
                   FROM shipments s
                   JOIN tours t ON t.id = s.tour_id
                   WHERE s.id = ?""",
                (shipment_id,),
            ).fetchone()
        if not row:
            return None
        data = dict(row)
        data["soloplan_label"] = self.format_soloplan_label(data)
        return data

    @staticmethod
    def format_soloplan_label(row: dict[str, Any]) -> str:
        parts: list[str] = []
        if row.get("sendungsnummer"):
            parts.append(f"Sendung {row['sendungsnummer']}")
        tour = row.get("tour_number") or row.get("ext_tour_number")
        if tour:
            parts.append(f"Tour {tour}")
        to_no = row.get("transport_order_number")
        if to_no is not None:
            parts.append(f"TA {to_no}")
        item_no = row.get("item_number")
        if item_no is not None:
            parts.append(f"Pos {item_no}")
        return " · ".join(parts)

    def save_billing_import(
        self,
        filename: str,
        lines: list[dict[str, Any]],
        *,
        invoice_number: str = "",
        billing_period: str = "",
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        import_id = uuid.uuid4().hex
        now = _now()
        matched = 0
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO billing_imports
                   (id, filename, invoice_number, billing_period, imported_at, row_count, matched_count, meta_json)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    import_id,
                    filename,
                    invoice_number,
                    billing_period,
                    now,
                    len(lines),
                    0,
                    json.dumps(meta or {}, ensure_ascii=False),
                ),
            )
            for line in lines:
                shipment_id = line.get("shipment_id")
                if shipment_id:
                    matched += 1
                conn.execute(
                    """INSERT INTO billing_lines
                       (id, import_id, identcode, amount_cents, currency, product_label,
                        invoice_number, billing_period, shipment_id, raw_json, created_at,
                        customer_ref, match_method)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        uuid.uuid4().hex,
                        import_id,
                        line["identcode"],
                        line["amount_cents"],
                        line.get("currency", "CHF"),
                        line.get("product_label"),
                        line.get("invoice_number") or invoice_number,
                        line.get("billing_period") or billing_period,
                        shipment_id,
                        json.dumps(line.get("raw") or {}, ensure_ascii=False),
                        now,
                        line.get("customer_ref"),
                        line.get("match_method"),
                    ),
                )
            conn.execute(
                "UPDATE billing_imports SET matched_count = ? WHERE id = ?",
                (matched, import_id),
            )
        return {
            "import_id": import_id,
            "row_count": len(lines),
            "matched_count": matched,
            "unmatched_count": len(lines) - matched,
        }

    def list_billing_imports(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM billing_imports ORDER BY imported_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def billing_summary_for_shipments(self, shipment_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not shipment_ids:
            return {}
        placeholders = ",".join("?" for _ in shipment_ids)
        q = f"""
            SELECT shipment_id,
                   SUM(amount_cents) AS total_cents,
                   COUNT(*) AS line_count,
                   GROUP_CONCAT(DISTINCT product_label) AS products,
                   MAX(invoice_number) AS invoice_number,
                   MAX(billing_period) AS billing_period
            FROM billing_lines
            WHERE shipment_id IN ({placeholders})
            GROUP BY shipment_id
        """
        with self._conn() as conn:
            rows = conn.execute(q, shipment_ids).fetchall()
        out: dict[str, dict[str, Any]] = {}
        for row in rows:
            sid = row["shipment_id"]
            if not sid:
                continue
            products = (row["products"] or "").split(",") if row["products"] else []
            out[sid] = {
                "billing_total_cents": int(row["total_cents"] or 0),
                "billing_line_count": int(row["line_count"] or 0),
                "billing_products": [p.strip() for p in products if p.strip()],
                "billing_invoice_number": row["invoice_number"],
                "billing_period": row["billing_period"],
            }
        return out

    def list_billing_lines_for_shipment(self, shipment_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM billing_lines WHERE shipment_id = ?
                   ORDER BY created_at DESC""",
                (shipment_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_unmatched_billing_lines(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM billing_lines
                   WHERE shipment_id IS NULL OR shipment_id = ''
                   ORDER BY created_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_address_book(self) -> AddressBook:
        return AddressBook(self._conn)

    def list_address_book(self, limit: int = 200) -> list[dict[str, Any]]:
        return self.get_address_book().list_entries(limit=limit)

    def upsert_address_book_entry(self, **kwargs) -> dict[str, Any]:
        return self.get_address_book().upsert(**kwargs)

    def delete_address_book_entry(self, entry_id: str) -> bool:
        return self.get_address_book().delete(entry_id)

    def lookup_address_book(self, **kwargs) -> dict[str, Any] | None:
        return self.get_address_book().lookup(**kwargs)

