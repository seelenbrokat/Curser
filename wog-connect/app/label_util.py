from __future__ import annotations

import io
import zipfile
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


def stamp_logo_on_pdf(
    pdf_bytes: bytes,
    logo_path: Path,
    *,
    width_pt: float = 68.0,
    margin_pt: float = 6.0,
) -> bytes:
    if not logo_path.is_file():
        return pdf_bytes

    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()
    img = ImageReader(str(logo_path))
    iw, ih = img.getSize()
    height_pt = width_pt * ih / iw

    for page in reader.pages:
        w = float(page.mediabox.width)
        h = float(page.mediabox.height)
        packet = io.BytesIO()
        c = canvas.Canvas(packet, pagesize=(w, h))
        x = w - width_pt - margin_pt
        y = h - height_pt - margin_pt
        c.drawImage(img, x, y, width=width_pt, height=height_pt, mask="auto", preserveAspectRatio=True)
        c.save()
        page.merge_page(PdfReader(packet).pages[0])
        writer.add_page(page)

    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def merge_pdf_files(
    paths: list[Path],
    *,
    logo_path: Path | None = None,
    logo_width_pt: float = 68.0,
) -> bytes:
    writer = PdfWriter()
    added = 0
    for path in paths:
        if not path.is_file() or path.suffix.lower() != ".pdf":
            continue
        data = path.read_bytes()
        if logo_path:
            data = stamp_logo_on_pdf(data, logo_path, width_pt=logo_width_pt)
        reader = PdfReader(io.BytesIO(data))
        for page in reader.pages:
            writer.add_page(page)
            added += 1
    if added == 0:
        raise ValueError("Keine PDF-Labels zum Zusammenführen")
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def merge_zpl_files(paths: list[Path]) -> bytes:
    parts: list[bytes] = []
    for path in paths:
        if path.is_file():
            parts.append(path.read_bytes())
            if not parts[-1].endswith(b"\n"):
                parts.append(b"\n")
    return b"".join(parts)


def build_labels_zip(entries: list[tuple[str, Path]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for arcname, path in entries:
            if path.is_file():
                zf.write(path, arcname=arcname)
    return buf.getvalue()
