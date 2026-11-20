from __future__ import annotations

import os

import pytest

os.environ.setdefault("JWT_SECRET", "test-secret-test-secret-test-secret-1234")
os.environ.setdefault("SECRET_MASTER_KEY", "test-master-key")

from app.adapters.memory import MemoryBlob, MemoryQueue, MemorySecrets, MemoryStore  # noqa: E402
from app.core.settings import BootstrapSettings  # noqa: E402
from app.services.container import Container, set_container  # noqa: E402


def make_pdf(pages: list[list[str]]) -> bytes:
    """PDF tối giản có lớp text (Helvetica, ASCII) — đủ để pdfium trích text."""
    objs: list[bytes] = []
    n = len(pages)
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n))
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode())
    font_id = 3 + 2 * n
    for i, lines in enumerate(pages):
        content_id = 4 + 2 * i
        objs.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents {content_id} 0 R "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> >>".encode()
        )
        ops = ["BT", "/F1 11 Tf", "14 TL", "50 800 Td"]
        for ln in lines:
            safe = ln.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            ops.append(f"({safe}) Tj T*")
        ops.append("ET")
        stream = "\n".join(ops).encode()
        objs.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


SAMPLE_PAGES = [
    [
        "Dental fee schedule header",
        "M015-2 CAD/CAM crown",
        "The crown is calculated per tooth 1,200 points.",
        "Conditions apply to molars only.",
        "",
        "1",
    ],
    [
        "Dental fee schedule header",
        "However the exception applies to premolars",
        "",
        "M016 Metal crown",
        "Metal crowns are calculated per tooth 800 points.",
        "2",
    ],
    [
        "Dental fee schedule header",
        "A000 First visit",
        "First visit fee 264 points.",
        "Includes basic examination.",
        "",
        "3",
    ],
]


@pytest.fixture
def container():
    s = BootstrapSettings(
        app_env="dev", db_type="memory", queue_type="memory", jwt_secret="x" * 40, secret_master_key="k"
    )
    c = Container.build(s, store=MemoryStore(), queue=MemoryQueue(), blob=MemoryBlob(), secrets=MemorySecrets())
    set_container(c)
    yield c
    set_container(None)


@pytest.fixture
def sample_pdf() -> bytes:
    return make_pdf(SAMPLE_PAGES)


def manual_review(container) -> None:
    """Tắt tự chạy (review.auto_review) cho test luồng duyệt tay từng trang / chunk."""
    from app.domain.options import PipelineOptions

    opts = PipelineOptions()
    opts.review.auto_review = False
    container.repo.put_setting("pipeline", {"version": 1, "options": opts.model_dump(mode="json")})
