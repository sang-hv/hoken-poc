"""Tiện ích cho step: khoá blob, xử lý PDF/ảnh trang."""

from __future__ import annotations

import io

from app.domain.models import page_key


def k_source(doc_id: str) -> str:
    return f"docs/{doc_id}/source.pdf"


def k_page(doc_id: str, page: int, name: str) -> str:
    return f"docs/{doc_id}/pages/{page_key(page)}/{name}"


def k_version(doc_id: str, page: int, v: int) -> str:
    return k_page(doc_id, page, f"review/v{v:03d}.md")


def pdf_page_count(pdf: bytes) -> int:
    import pypdfium2 as pdfium

    return len(pdfium.PdfDocument(pdf))


def single_page_pdf(pdf: bytes, page: int) -> bytes:
    import pypdfium2 as pdfium

    src = pdfium.PdfDocument(pdf)
    dst = pdfium.PdfDocument.new()
    dst.import_pages(src, [page - 1])
    buf = io.BytesIO()
    dst.save(buf)
    return buf.getvalue()


def render_page_png(pdf: bytes, page: int, scale: float = 2.0) -> tuple[bytes, tuple[int, int]]:
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(pdf)
    img = doc[page - 1].render(scale=scale).to_pil()
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue(), img.size


def page_text_pdfium(pdf: bytes, page: int) -> str:
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(pdf)
    return doc[page - 1].get_textpage().get_text_range()


def crop_png(png: bytes, bbox: list[float]) -> bytes:
    """bbox chuẩn hoá [x0, y0, x1, y1] gốc trên-trái, giá trị 0..1."""
    from PIL import Image

    img = Image.open(io.BytesIO(png))
    w, h = img.size
    x0, y0, x1, y1 = bbox
    pad = 0.01
    box = (
        max(0, int((x0 - pad) * w)),
        max(0, int((y0 - pad) * h)),
        min(w, int((x1 + pad) * w)),
        min(h, int((y1 + pad) * h)),
    )
    buf = io.BytesIO()
    img.crop(box).save(buf, format="PNG")
    return buf.getvalue()
