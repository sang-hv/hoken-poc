"""Lớp 4 — tuỳ chọn pipeline.

Mọi giá trị mặc định nằm trong code (file này). Chỉ vài mục trong `EDITABLE` cho Admin chỉnh trên UI; các mục
đó lưu trong DB có phiên bản, mỗi job ghi lại phiên bản đã dùng. Mục còn lại (prompt, luật chunk, tiêu chí trang
dễ, ...) đổi bằng code + review, để người dùng prod không chỉnh nhầm.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

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
    # OCR bên trong Docling cho vùng ảnh / trang scan. rapidocr = PP-OCRv6 tiếng Nhật (ONNX): trên sách scan F1 ký tự
    # 98,5 % so với 84,9 % của easyocr (EasyOCR bỏ sót chữ, đọc MOO1 / 揖げる) — benchmark 25/11/2026.
    ocr_engine: str = "rapidocr"  # rapidocr | easyocr
    # Ngôn ngữ OCR: easyocr dùng cả danh sách; rapidocr chỉ chạy một ngôn ngữ → lấy phần tử đầu (ja).
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


ReviewMode = Literal["auto", "warn", "manual"]


class ReviewOptions(BaseModel):
    # Cách duyệt cho tài liệu upload (ghi vào tài liệu lúc upload):
    #   auto   — tự chạy hết OCR → chunk → index, tự duyệt với người duyệt "auto"; chỗ kém chỉ gắn ⚠.
    #   warn   — tự chạy, nhưng DỪNG ở OCR レビュー khi còn điểm yếu ⚠ và ở チャンクレビュー khi có chunk cần xem;
    #            người review hoặc bấm 「すべて承認」 để đi tiếp. Không có cảnh báo thì tự đi tiếp như auto.
    #   manual — luôn dừng ở hai bước review chờ duyệt tay.
    mode: ReviewMode = "warn"
    # (warn) chunk vi phạm luật hoặc có confidence dưới mức này → dừng ở チャンクレビュー
    chunk_warn_below: float = Field(0.7, ge=0, le=1)
    # Vùng (chữ CU / phần tử Docling) có confidence dưới ngưỡng được viền đỏ trên ảnh trang.
    # Chỉ để tô màu — trang nào cũng vẫn phải review.
    low_confidence: float = 0.8
    rerun_prompt: str = DEFAULT_RERUN_PROMPT

    @model_validator(mode="before")
    @classmethod
    def _legacy_auto_review(cls, v):
        """Cấu hình cũ có `auto_review: false` (duyệt tay) → mode manual."""
        if isinstance(v, dict) and "mode" not in v and v.get("auto_review") is False:
            return {**v, "mode": "manual"}
        return v


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
    top_k: int = 5  # số đoạn lấy về mặc định khi tìm thử / chat thử


DEFAULT_CHAT_PROMPT = (
    "You are a dental insurance (保険点数) assistant for Japanese dental clinics. Answer ONLY from the numbered "
    "sources given (public MHLW documents). Answer in the language of the question, concisely, keep item codes "
    "(e.g. M015-2) and 点 numbers exactly as in the sources, and cite sources inline as [1], [2]. "
    'Return JSON {"answer": string, "cited": [source numbers], "handoff": boolean}. If the sources do not '
    'contain the answer, return {"answer": "", "cited": [], "handoff": true} so the question goes to customer '
    "support — never guess."
)


class ChatOptions(BaseModel):
    """Chat thử (khu B, bản test trong Admin): tìm đoạn liên quan rồi để LLM trả lời có căn cứ."""

    system_prompt: str = DEFAULT_CHAT_PROMPT
    min_score: float = 0.0  # đoạn tốt nhất dưới điểm này → chuyển CSKH luôn, không gọi LLM
    max_history: int = 6  # số lượt hỏi đáp trước đó gửi kèm


DEFAULT_REREAD_PROMPT = (
    "Keep all Japanese text, item codes (e.g. M015-2) and numbers/点 exactly as in the image. "
    "Tables → Markdown table; flowcharts/diagrams → Mermaid inside ```mermaid; other pictures → "
    "a short factual description. Headings keep their # level."
)


class QualityOptions(BaseModel):
    """Chấm chất lượng sau pipeline + phát hiện điểm yếu (UI v2, tab 検査). Chủ: backend A2."""

    weak_confidence: float = Field(0.8, ge=0, le=1)  # phần tử có confidence dưới mức này → điểm yếu low_confidence
    auto_vlm_below: float = Field(0.6, ge=0, le=1)  # phần tử dưới mức này được tự gọi VLM đọc lại trong pipeline
    picture_needs_description: bool = True  # hình chưa có mô tả → điểm yếu picture_no_desc
    grade_good: int = 85  # điểm trang/tài liệu ≥ mức này = good (良好)
    grade_fair: int = 60  # ≥ mức này = fair (要注意), thấp hơn = poor (不良)
    # Hướng dẫn cho AI khi đọc lại phần tử (tự đọc lại trong pipeline, 「弱点をAIで修正」, đọc lại từng phần tử).
    # Người dùng sửa được cho từng lần chạy 「弱点をAIで修正」; khung JSON trả về cố định trong code.
    reread_prompt: str = DEFAULT_REREAD_PROMPT


class PipelineOptions(BaseModel):
    docling: DoclingOptions = Field(default_factory=DoclingOptions)
    routing: RoutingOptions = Field(default_factory=RoutingOptions)
    cu: CuOptions = Field(default_factory=CuOptions)
    review: ReviewOptions = Field(default_factory=ReviewOptions)
    stitch: StitchOptions = Field(default_factory=StitchOptions)
    chunk: ChunkOptions = Field(default_factory=ChunkOptions)
    index: IndexOptions = Field(default_factory=IndexOptions)
    chat: ChatOptions = Field(default_factory=ChatOptions)
    quality: QualityOptions = Field(default_factory=QualityOptions)


# Mục Admin chỉnh được trên UI (section → các khoá). Còn lại luôn lấy theo code.
# review.mode cố định "warn" (tự chạy, chỉ dừng khi có cảnh báo); auto / manual chỉ còn cho test và seed demo.
# cu.enabled cố định bật: trang khó luôn qua 精密解析.
EDITABLE: dict[str, tuple[str, ...]] = {
    "review": ("chunk_warn_below",),
    "quality": ("weak_confidence", "auto_vlm_below"),
}


def editable_dump(opts: PipelineOptions) -> dict:
    """Chỉ các mục chỉnh được — dạng lưu DB và trả cho UI."""
    full = opts.model_dump(mode="json")
    return {sec: {k: full[sec][k] for k in keys} for sec, keys in EDITABLE.items()}


def options_from(stored: dict | None) -> PipelineOptions:
    """Mặc định theo code + các mục chỉnh được lấy từ `stored`; khoá khác trong `stored` bị bỏ qua."""
    base = PipelineOptions().model_dump()
    for sec, keys in EDITABLE.items():
        for k in keys:
            if stored and k in (stored.get(sec) or {}):
                base[sec][k] = stored[sec][k]
    return PipelineOptions(**base)
