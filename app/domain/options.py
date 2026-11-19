"""Lớp 4 — tuỳ chọn pipeline. Lưu trong DB có phiên bản; mỗi job ghi lại phiên bản đã dùng."""

from __future__ import annotations

from pydantic import BaseModel, Field

DEFAULT_VISION_PROMPT = (
    "You convert a figure from a Japanese dental insurance document into text. "
    "If it is a flowchart or diagram, output Mermaid inside ```mermaid. "
    "If it is a table, output a Markdown table. Keep all Japanese text and numbers (especially 点) exactly. "
    "Output only the result."
)

DEFAULT_RERUN_PROMPT = (
    "You correct OCR output of one page of a Japanese dental insurance document. "
    "You get the page image and the current Markdown. Return the corrected full-page Markdown only. "
    "Keep tables as Markdown tables, keep item codes (e.g. M015-2) and all numbers/点 exactly as in the image."
)

DEFAULT_CHUNK_PROMPT = (
    "You split one section of a Japanese dental insurance document into retrieval chunks. "
    'Lines are numbered. Return JSON {"chunks": [{"start": int, "end": int, "item_code": str, '
    '"title": str}]} where start/end are inclusive line numbers. Rules: cover every line exactly once, '
    "in order; never split a table; every chunk has the item code it belongs to; keep conditions together "
    "with their exceptions (lines starting with ただし, なお, この場合, 注 stay with the previous text)."
)


class DoclingOptions(BaseModel):
    do_ocr: bool = True
    ocr_lang: list[str] = Field(default_factory=lambda: ["ja", "en"])
    table_mode: str = "accurate"  # accurate | fast
    images_scale: float = 2.0
    picture_classification: bool = True
    remove_picture_classes: list[str] = Field(default_factory=lambda: ["logo", "stamp", "signature"])


class RoutingOptions(BaseModel):
    """Tiêu chí 'trang dễ' theo điểm Docling (grade: <0.5 poor, <0.8 fair, <0.9 good, ≥0.9 excellent)."""

    min_low_score: float = 0.8  # low_grade phải từ GOOD trở lên
    min_parse_score: float = 0.8  # PDF số, lớp text sạch
    ocr_page_is_hard: bool = True  # trang phải OCR (scan) → CU
    complex_table_is_hard: bool = True  # bảng có ô gộp → CU
    table_crossing_page_is_hard: bool = True
    figure_min_area: float = 0.05  # hình chiếm > 5% trang (sau khi loại logo/con dấu/chữ ký) → CU


class CuOptions(BaseModel):
    enabled: bool = True
    figure_vision: bool = True
    vision_prompt: str = DEFAULT_VISION_PROMPT


class ReviewOptions(BaseModel):
    rerun_prompt: str = DEFAULT_RERUN_PROMPT


class StitchOptions(BaseModel):
    header_lines: int = 3
    footer_lines: int = 3
    repeat_ratio: float = 0.5  # dòng lặp lại ở ≥ 50% số trang → header/footer


class ChunkOptions(BaseModel):
    llm_refine: bool = True
    max_rounds: int = 20
    min_chars: int = 80
    max_chars: int = 1500
    item_code_regex: str = r"[A-Z]\d{3}(?:-\d+){0,3}"
    prompt: str = DEFAULT_CHUNK_PROMPT
    llm_confidence: bool = True  # LLM-mini chấm điểm chunk


class IndexOptions(BaseModel):
    embed_batch: int = 16
    top_k: int = 5


class PipelineOptions(BaseModel):
    docling: DoclingOptions = Field(default_factory=DoclingOptions)
    routing: RoutingOptions = Field(default_factory=RoutingOptions)
    cu: CuOptions = Field(default_factory=CuOptions)
    review: ReviewOptions = Field(default_factory=ReviewOptions)
    stitch: StitchOptions = Field(default_factory=StitchOptions)
    chunk: ChunkOptions = Field(default_factory=ChunkOptions)
    index: IndexOptions = Field(default_factory=IndexOptions)
