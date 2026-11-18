from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from app.soloplan_parser import Address


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_matchcode(value: str | None) -> str:
    return re.sub(r"\s+", "", (value or "").strip()).upper()


def name_zip_key(name1: str | None, zip_code: str | None) -> str:
    name = re.sub(r"\s+", " ", (name1 or "").strip()).casefold()
    z = re.sub(r"\s+", "", (zip_code or "").strip())
    return f"{name}|{z}"


class AddressBook:
    """Kleine Empfänger-Korrekturdatenbank, Schlüssel = Soloplan-Matchcode."""

    def __init__(self, conn_factory):
        self._conn_factory = conn_factory

    def ensure_schema(self) -> None:
        with self._conn_factory() as conn:
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
                CREATE INDEX IF NOT EXISTS idx_addrbook_bp
                  ON recipient_address_book(soloplan_bp_id);
                """
            )

    def upsert(
        self,
        *,
        name1: str,
        street: str,
        zip_code: str,
        city: str,
        country: str = "CH",
        name2: str | None = None,
        email: str | None = None,
        soloplan_matchcode: str | None = None,
        soloplan_bp_id: str | None = None,
        notes: str | None = None,
        source_shipment_id: str | None = None,
    ) -> dict[str, Any]:
        mc = normalize_matchcode(soloplan_matchcode) or None
        bp = str(soloplan_bp_id or "").strip() or None
        key = name_zip_key(name1, zip_code)
        now = _now()
        with self._conn_factory() as conn:
            existing = None
            if mc:
                existing = conn.execute(
                    "SELECT * FROM recipient_address_book WHERE soloplan_matchcode = ?",
                    (mc,),
                ).fetchone()
            if existing is None:
                existing = conn.execute(
                    "SELECT * FROM recipient_address_book WHERE name_zip_key = ? ORDER BY updated_at DESC LIMIT 1",
                    (key,),
                ).fetchone()

            payload = {
                "soloplan_matchcode": mc,
                "soloplan_bp_id": bp,
                "name_zip_key": key,
                "name1": (name1 or "").strip(),
                "name2": (name2 or "").strip() or None,
                "street": (street or "").strip(),
                "zip_code": (zip_code or "").strip(),
                "city": (city or "").strip(),
                "country": ((country or "CH").strip()[:2].upper()),
                "email": (email or "").strip() or None,
                "notes": (notes or "").strip() or None,
                "source_shipment_id": source_shipment_id,
                "updated_at": now,
            }
            if existing:
                eid = existing["id"] if isinstance(existing, dict) else existing[0]
                conn.execute(
                    """UPDATE recipient_address_book SET
                        soloplan_matchcode = COALESCE(?, soloplan_matchcode),
                        soloplan_bp_id = COALESCE(?, soloplan_bp_id),
                        name_zip_key = ?, name1 = ?, name2 = ?, street = ?,
                        zip_code = ?, city = ?, country = ?, email = ?,
                        notes = COALESCE(?, notes),
                        source_shipment_id = COALESCE(?, source_shipment_id),
                        updated_at = ?
                      WHERE id = ?""",
                    (
                        payload["soloplan_matchcode"],
                        payload["soloplan_bp_id"],
                        payload["name_zip_key"],
                        payload["name1"],
                        payload["name2"],
                        payload["street"],
                        payload["zip_code"],
                        payload["city"],
                        payload["country"],
                        payload["email"],
                        payload["notes"],
                        payload["source_shipment_id"],
                        now,
                        eid,
                    ),
                )
                row = conn.execute("SELECT * FROM recipient_address_book WHERE id = ?", (eid,)).fetchone()
            else:
                eid = uuid.uuid4().hex
                conn.execute(
                    """INSERT INTO recipient_address_book (
                        id, soloplan_matchcode, soloplan_bp_id, name_zip_key,
                        name1, name2, street, zip_code, city, country, email,
                        notes, source_shipment_id, created_at, updated_at
                      ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        eid,
                        payload["soloplan_matchcode"],
                        payload["soloplan_bp_id"],
                        payload["name_zip_key"],
                        payload["name1"],
                        payload["name2"],
                        payload["street"],
                        payload["zip_code"],
                        payload["city"],
                        payload["country"],
                        payload["email"],
                        payload["notes"],
                        payload["source_shipment_id"],
                        now,
                        now,
                    ),
                )
                row = conn.execute("SELECT * FROM recipient_address_book WHERE id = ?", (eid,)).fetchone()
            return dict(row)

    def lookup(
        self,
        *,
        soloplan_matchcode: str | None = None,
        soloplan_bp_id: str | None = None,
        name1: str | None = None,
        zip_code: str | None = None,
    ) -> dict[str, Any] | None:
        mc = normalize_matchcode(soloplan_matchcode)
        bp = str(soloplan_bp_id or "").strip()
        with self._conn_factory() as conn:
            if mc:
                row = conn.execute(
                    "SELECT * FROM recipient_address_book WHERE soloplan_matchcode = ?",
                    (mc,),
                ).fetchone()
                if row:
                    return dict(row)
            if bp:
                row = conn.execute(
                    """SELECT * FROM recipient_address_book
                       WHERE soloplan_bp_id = ?
                       ORDER BY updated_at DESC LIMIT 1""",
                    (bp,),
                ).fetchone()
                if row:
                    return dict(row)
            if name1 and zip_code:
                row = conn.execute(
                    "SELECT * FROM recipient_address_book WHERE name_zip_key = ? ORDER BY updated_at DESC LIMIT 1",
                    (name_zip_key(name1, zip_code),),
                ).fetchone()
                if row:
                    return dict(row)
        return None

    def list_entries(self, limit: int = 200) -> list[dict[str, Any]]:
        with self._conn_factory() as conn:
            rows = conn.execute(
                """SELECT * FROM recipient_address_book
                   ORDER BY updated_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def delete(self, entry_id: str) -> bool:
        with self._conn_factory() as conn:
            cur = conn.execute("DELETE FROM recipient_address_book WHERE id = ?", (entry_id,))
            return cur.rowcount > 0

    def to_address(self, entry: dict[str, Any]) -> Address:
        return Address(
            name1=entry.get("name1") or "",
            street=entry.get("street") or "",
            zip_code=entry.get("zip_code") or "",
            city=entry.get("city") or "",
            country=entry.get("country") or "CH",
            email=entry.get("email"),
            name2=entry.get("name2"),
        )

    def apply_to_draft_recipient(
        self,
        recipient: Address,
        *,
        soloplan_matchcode: str | None = None,
        soloplan_bp_id: str | None = None,
    ) -> tuple[Address, dict[str, Any] | None]:
        """Ersetzt Soloplan-Adresse durch bekannte Korrektur, falls vorhanden."""
        entry = self.lookup(
            soloplan_matchcode=soloplan_matchcode,
            soloplan_bp_id=soloplan_bp_id,
            name1=recipient.name1,
            zip_code=recipient.zip_code,
        )
        if not entry:
            return recipient, None
        return self.to_address(entry), entry

    @staticmethod
    def recipient_changed(before: Address, after: Address) -> bool:
        return (
            (before.name1 or "").strip() != (after.name1 or "").strip()
            or (before.name2 or "").strip() != (after.name2 or "").strip()
            or (before.street or "").strip() != (after.street or "").strip()
            or (before.zip_code or "").strip() != (after.zip_code or "").strip()
            or (before.city or "").strip() != (after.city or "").strip()
            or (before.country or "CH").strip().upper() != (after.country or "CH").strip().upper()
        )
