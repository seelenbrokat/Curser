from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from typing import Any

from app.invoice_import import ParsedBillingLine, ParseResult, amount_to_cents, normalize_identcode

_IDENT_RE = re.compile(r"^(99\d{16})\s+(.*)$", re.M)
_AMOUNT_RE = re.compile(r"\d+\.\d{2}")
_PERIOD_RE = re.compile(
    r"Datum von\s+(\d{2}\.\d{2}\.\d{4})\s+bis\s+(\d{2}\.\d{2}\.\d{4})",
    re.I,
)
_LICENSE_RE = re.compile(r"Frankierlizenz\s+(\d{5,})", re.I)

_ZL_CODES = {
    "MAN",
    "SI",
    "FRA",
    "AS",
    "ETI",
    "AMB",
    "AZS",
    "ZFZ",
    "LE1",
    "LE2",
    "XXL",
    "LQ",
    "RMP",
    "CALL",
    "DX",
    "GU",
    "ZA11",
    "ZA13",
    "ZA14",
    "ZA15",
    "ZA16",
    "ZA19",
    "ZA20",
    "ZA23",
    "ZA26",
    "ZA34",
}

_ZL_DESC = {
    "MAN": "Manuelle Verarbeitung (Zuschlag)",
    "SI": "Signature (Zuschlag)",
    "FRA": "Fragile (Zuschlag)",
    "AS": "Assurance (Zuschlag)",
    "ETI": "Etikette mitnehmen",
    "AMB": "ThermoCare Ambient",
    "AZS": "Zustellzeitfenster (Abend)",
    "ZFZ": "Zustellzeitfenster",
    "LE1": "Überlänge/Übergewicht: Länge >2.5m oder (>2m & >10kg)",
    "LE2": "Gurtmass über 400 cm",
    "XXL": "Übergewicht XXL",
    "LQ": "Gefahrgut (LQ)",
    "RMP": "Eigenhändig",
    "CALL": "Änderung Versandauftrag",
}


@dataclass
class PvePackageLine:
    identcode: str
    product: str
    weight_stage: str
    package_chf: float
    zl_code: str | None = None
    zl_chf: float | None = None
    raw: str = ""

    @property
    def total_chf(self) -> float:
        return round(self.package_chf + (self.zl_chf or 0.0), 2)

    @property
    def is_bulky(self) -> bool:
        return "sperrgut" in (self.product or "").lower()

    @property
    def has_extra(self) -> bool:
        return self.is_bulky or bool(self.zl_code)


def extract_pdf_text(content: bytes) -> str:
    """Text aus Post-PvE-PDF (pypdf, Fallback pdftotext)."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(__import__("io").BytesIO(content))
        parts = [(page.extract_text() or "") for page in reader.pages]
        text = "\n".join(parts)
        if text.strip():
            return text
    except Exception:
        pass
    try:
        proc = subprocess.run(
            ["pdftotext", "-layout", "-", "-"],
            input=content,
            capture_output=True,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout.decode("utf-8", errors="replace")
    except FileNotFoundError:
        pass
    raise ValueError(
        "PDF-Text konnte nicht gelesen werden. Bitte Verarbeitungsnachweis-PDF der Post verwenden "
        "oder Excel/CSV aus dem Rechnungsmanager."
    )


def _parse_product_and_weight(rest: str) -> tuple[str, str, str | None]:
    tokens = rest.split()
    zl = next((t for t in tokens if t in _ZL_CODES), None)
    prod_tokens: list[str] = []
    for i, t in enumerate(tokens):
        if t in _ZL_CODES or _AMOUNT_RE.fullmatch(t):
            break
        if t.lower() == "bis" and i > 0:
            break
        if t.isdigit() and i > 0 and i + 1 < len(tokens) and tokens[i + 1].lower() in {"bis", "kg"}:
            break
        prod_tokens.append(t)
        if prod_tokens and prod_tokens[0] in {"PostPac", "Sperrgut"} and len(prod_tokens) >= 2:
            break
    product = " ".join(prod_tokens).strip() or "Post-Paket"
    cleaned = rest
    for a in _AMOUNT_RE.findall(rest):
        cleaned = cleaned.replace(a, " ", 1)
    if zl:
        cleaned = cleaned.replace(zl, " ", 1)
    for t in product.split():
        cleaned = cleaned.replace(t, " ", 1)
    weight = re.sub(r"\s+", " ", cleaned).strip(" -")
    return product, weight, zl


def parse_pve_text(text: str) -> tuple[list[PvePackageLine], dict[str, Any]]:
    meta: dict[str, Any] = {"source": "pve_pdf"}
    m_period = _PERIOD_RE.search(text)
    if m_period:
        meta["billing_period"] = f"{m_period.group(1)}–{m_period.group(2)}"
    m_lic = _LICENSE_RE.search(text)
    if m_lic:
        meta["franking_license"] = m_lic.group(1)

    lines: list[PvePackageLine] = []
    for m in _IDENT_RE.finditer(text):
        ident = normalize_identcode(m.group(1))
        rest = m.group(2).strip()
        amounts = [float(x) for x in _AMOUNT_RE.findall(rest)]
        if not amounts:
            continue
        product, weight, zl = _parse_product_and_weight(rest)
        package = amounts[0]
        zl_amt = amounts[1] if zl and len(amounts) >= 2 else None
        # ZFZ sometimes written as "ZFZ 0900-1200"
        if not zl:
            for code in _ZL_CODES:
                if re.search(rf"\b{code}\b", rest):
                    zl = code
                    if len(amounts) >= 2:
                        zl_amt = amounts[1]
                    break
        lines.append(
            PvePackageLine(
                identcode=ident,
                product=product,
                weight_stage=weight,
                package_chf=package,
                zl_code=zl,
                zl_chf=zl_amt,
                raw=rest[:200],
            )
        )
    return lines, meta


def typical_postpac_price(lines: list[PvePackageLine]) -> float:
    prices = [ln.package_chf for ln in lines if ln.product.lower().startswith("postpac")]
    if not prices:
        return 9.05
    # Modus / häufigster Preis
    counts: dict[float, int] = {}
    for p in prices:
        counts[p] = counts.get(p, 0) + 1
    return max(counts.items(), key=lambda kv: kv[1])[0]


def surcharge_breakdown(line: PvePackageLine, *, baseline_postpac: float) -> dict[str, Any]:
    extras: list[dict[str, Any]] = []
    reasons: list[str] = []
    surcharge = 0.0
    if line.is_bulky:
        delta = round(max(line.package_chf - baseline_postpac, 0.0), 2)
        extras.append(
            {
                "code": "SPERRGUT",
                "chf": delta,
                "gross_chf": line.package_chf,
                "reason": (
                    f"Sperrgut statt PostPac (CHF {line.package_chf:.2f} statt ca. CHF {baseline_postpac:.2f})"
                ),
            }
        )
        reasons.append(extras[-1]["reason"])
        surcharge += delta
    if line.zl_code:
        amt = float(line.zl_chf or 0.0)
        desc = _ZL_DESC.get(line.zl_code, line.zl_code)
        detail = f"Zusatzleistung {line.zl_code}: {desc}"
        if line.zl_code == "ZFZ" and line.weight_stage:
            # oft enthält weight_stage das Fenster, z.B. 0900-1200
            detail += f" ({line.weight_stage})"
        detail += f" → CHF {amt:.2f}"
        extras.append({"code": line.zl_code, "chf": amt, "reason": detail})
        reasons.append(detail)
        surcharge += amt
    return {
        "extras": extras,
        "reasons": reasons,
        "surcharge_chf": round(surcharge, 2),
        "is_surcharge": bool(extras),
    }


def parse_pve_pdf(content: bytes, filename: str = "") -> ParseResult:
    text = extract_pdf_text(content)
    if "Verarbeitungsnachweis" not in text and "Identcode" not in text:
        raise ValueError("PDF scheint kein Post-Verarbeitungsnachweis (PvE) zu sein.")
    packages, meta = parse_pve_text(text)
    if not packages:
        raise ValueError("Im PDF wurden keine Identcode-Positionen gefunden.")

    baseline = typical_postpac_price(packages)
    period = str(meta.get("billing_period") or "")
    invoice = str(meta.get("franking_license") or "")
    warnings: list[str] = [
        "Import aus Post-Verarbeitungsnachweis (PvE-PDF).",
        f"Typischer PostPac-Preis in dieser Datei: CHF {baseline:.2f} (Referenz für Sperrgut-Differenz).",
    ]
    parsed: list[ParsedBillingLine] = []
    for pkg in packages:
        br = surcharge_breakdown(pkg, baseline_postpac=baseline)
        label = pkg.product
        if pkg.zl_code:
            label = f"{pkg.product} + {pkg.zl_code}"
        if pkg.weight_stage:
            label = f"{label} · {pkg.weight_stage}"
        cents = amount_to_cents(pkg.total_chf)
        if cents is None:
            continue
        parsed.append(
            ParsedBillingLine(
                identcode=pkg.identcode,
                amount_cents=cents,
                product_label=label,
                invoice_number=invoice,
                billing_period=period,
                customer_ref="",
                raw={
                    "source": "pve_pdf",
                    "filename": filename,
                    "product": pkg.product,
                    "weight_stage": pkg.weight_stage,
                    "package_chf": pkg.package_chf,
                    "zl_code": pkg.zl_code,
                    "zl_chf": pkg.zl_chf,
                    "total_chf": pkg.total_chf,
                    "baseline_postpac_chf": baseline,
                    "surcharge_chf": br["surcharge_chf"],
                    "extras": br["extras"],
                    "reasons": br["reasons"],
                    "is_surcharge": br["is_surcharge"],
                    "line_raw": pkg.raw,
                },
            )
        )

    return ParseResult(
        lines=parsed,
        header_row=0,
        columns={"identcode": 0, "amount": 1, "product": 2},
        invoice_number=invoice,
        billing_period=period,
        warnings=warnings,
    )
