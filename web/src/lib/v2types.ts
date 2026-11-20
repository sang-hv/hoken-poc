/** Hợp đồng dữ liệu UI v2 (xem docs/UI_V2_SPEC.md). Backend trả đúng các field này. Không sửa riêng lẻ —
 *  đổi hợp đồng thì đổi cả backend lẫn frontend. */
import type { DocStatus } from "./types";

// ------------------------------------------------------------------ Kiểm tra
export type QualityGrade = "good" | "fair" | "poor"; // 良好 / 要注意 / 不良  (Tốt / Tạm / Kém)

export type ElementLabel =
  | "title"
  | "section_header"
  | "text"
  | "list"
  | "toc"
  | "table"
  | "picture"
  | "caption"
  | "formula"
  | "footnote"
  | "page_header"
  | "page_footer";

export type WeakCode =
  | "low_confidence"
  | "picture_no_desc"
  | "missing_text"
  | "table_suspect"
  | "reread"
  | "blank_page"
  | "ocr_weak";

export interface WeakFlag {
  code: WeakCode;
  severity: "warn" | "error";
  detail?: string; // vd "0.62" — không dịch, chỉ hiển thị kèm
}

export type ElementStatus = "ok" | "weak" | "fixed" | "accepted";

export interface Element {
  id: string; // "e1", "e2"… ổn định trong trang
  order: number; // thứ tự đọc, 1-based
  label: ElementLabel;
  bbox: [number, number, number, number]; // x0,y0,x1,y1 gốc trên-trái, 0..1
  text: string; // Markdown đọc được
  confidence: number | null;
  source: "docling" | "cu" | "vlm" | "manual" | "pdfium";
  weak: WeakFlag[];
  status: ElementStatus;
  edited_by: string;
  edited_at: string;
}

export interface PageElements {
  page: number;
  book_page: number;
  image_size: [number, number] | null;
  score: number; // 0..100
  grade: QualityGrade;
  elements: Element[];
}

export interface DocQuality {
  score: number; // 0..100
  grade: QualityGrade;
  worst_page: { page: number; score: number; grade: QualityGrade } | null;
  counts: Partial<Record<WeakCode, number>>; // điểm yếu CHƯA xử lý theo loại
  weak_total: number;
  weak_open: number;
  pages: { page: number; score: number; grade: QualityGrade; weak_open: number }[];
}

export interface WeakItem {
  page: number;
  element_id: string;
  order: number;
  label: ElementLabel;
  code: WeakCode;
  severity: "warn" | "error";
  status: ElementStatus;
  preview: string; // 80 ký tự đầu
}

export interface DocInfo {
  doc_id: string;
  name: string;
  filename: string;
  file_type: "pdf" | "image";
  language: string; // "ja" | "en" | …
  pages: number;
  size_bytes: number;
  created_at: string;
  created_by: string;
  origin: "upload";
  mode: "full"; // 全文
  status: DocStatus;
}

export interface PageText {
  page: number;
  book_page: number;
  markdown: string;
}

export interface Insights {
  summary: string;
  key_points: string[];
  generated_at: string;
}

export interface PageScore {
  page: number;
  score: number;
  grade: QualityGrade;
  comment: string;
}

export interface HistoryItem {
  at: string;
  by: string;
  kind: "page_version" | "element_edit" | "element_reread" | "element_accept";
  element_id: string;
  summary: string; // vd "v3 · stitched" hoặc "e4 · 0.62 → manual"
}
