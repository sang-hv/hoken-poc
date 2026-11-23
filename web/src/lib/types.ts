export type Role = "admin" | "reviewer" | "viewer";

export interface User {
  id: string;
  email: string;
  name: string;
  role: Role;
  provider: string;
  active: boolean;
  created_at: string;
  last_login_at: string;
}

export type DocStatus =
  | "processing"
  | "stitching"
  | "ocr_review"
  | "ready_for_chunking"
  | "chunking"
  | "chunk_review"
  | "indexing"
  | "indexed"
  | "failed";

export interface Doc {
  id: string;
  name: string;
  kind: string;
  filename: string;
  book_page_start: number;
  page_from: number;
  page_to: number;
  total_pdf_pages: number;
  enabled: boolean;
  status: DocStatus;
  created_by: string;
  created_at: string;
  updated_at: string;
  config_version: number;
  review_mode?: "auto" | "warn" | "manual" | ""; // review.mode lúc upload ("" = tài liệu cũ → theo auto_review)
  auto_review?: boolean; // review_mode != manual
  review_hold?: "ocr" | "chunk" | ""; // (warn) đang dừng chờ người ở bước review nào
  file_type?: "pdf" | "image";
  stats: Record<string, number>;
}

export type PageStatus = "queued" | "docling" | "routed" | "cu" | "ready" | "review" | "approved" | "failed";

export interface PageScores {
  parse_score: number | null;
  layout_score: number | null;
  ocr_score: number | null;
  table_score: number | null;
  mean_score: number | null;
  low_score: number | null;
  mean_grade: string;
  low_grade: string;
}

export interface PageFeatures {
  has_text_layer: boolean;
  n_tables: number;
  complex_tables: number;
  table_at_bottom: boolean;
  table_at_top: boolean;
  n_figures: number;
  max_figure_area: number;
  removed: Record<string, number>;
}

export interface PageVersion {
  v: number;
  source: "stitched" | "human" | "llm";
  by: string;
  at: string;
  note: string;
}

export interface Page {
  id: string;
  doc_id: string;
  page: number;
  book_page: number;
  status: PageStatus;
  engine: string;
  scores: PageScores;
  features: PageFeatures;
  route: "easy" | "hard" | null;
  route_reasons: string[];
  route_override: "auto" | "force_cu" | "skip_cu";
  cu_status: string;
  continues_next: boolean;
  table_continues_next: boolean;
  current_version: number;
  versions: PageVersion[];
  reviewed_by: string;
  reviewed_at: string;
  updated_at: string;
  error: string;
}

export interface Element {
  label: string;
  bbox: [number, number, number, number];
  class?: string;
  removed?: boolean;
  figure?: number;
  confidence?: number;
  text?: string;
}

/** Vùng confidence thấp (chữ CU hoặc phần tử Docling) — chỉ để viền đỏ, không bỏ qua review. */
export interface LowConfidenceBox {
  source: "docling" | "cu";
  label: string;
  text: string;
  confidence: number;
  bbox: [number, number, number, number];
  span: [number, number] | null;
}

export interface PageDetail extends Page {
  markdown: string;
  sources: Partial<Record<"docling" | "cu" | "stitched", string>>;
  elements: Element[];
  image_size: [number, number] | null;
  low_confidence: { threshold: number; boxes: LowConfidenceBox[] };
}

export interface Chunk {
  id: string;
  doc_id: string;
  seq: number;
  item_code: string;
  title: string;
  text: string;
  page_from: number;
  page_to: number;
  confidence: number;
  rule_score: number;
  llm_score: number | null;
  violations: string[];
  rounds: number;
  status: "draft" | "approved" | "indexed";
  edited_by: string;
  updated_at: string;
}

export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";

export interface Job {
  id: string;
  doc_id: string;
  doc_name?: string;
  step: string;
  queue: string;
  page: number | null;
  params: Record<string, unknown>;
  status: JobStatus;
  attempts: number;
  max_attempts: number;
  config_version: number;
  error: string;
  created_at: string;
  started_at: string;
  finished_at: string;
  updated_at: string;
  created_by: string;
}

export interface JobEvent {
  id: string;
  doc_id: string;
  job_id: string;
  step: string;
  page: number | null;
  level: "debug" | "info" | "warn" | "error";
  code: string;
  params: Record<string, unknown>;
  ts: string;
}

/** Lỗi cấu hình lớp 2 (biến môi trường): mã + tên biến, không có giá trị. */
export interface EnvError {
  code: "type_missing" | "type_unsupported" | "required" | "not_number" | "invalid";
  env: string;
}

export interface ProviderField {
  name: string;
  env: string;
  kind: "text" | "secret" | "number" | "select" | "bool" | "textarea";
  /** Trường thường: giá trị đang dùng */
  value?: unknown;
  /** Trường thường: lấy giá trị mặc định (biến chưa đặt) */
  default?: boolean;
  /** Trường secret: đã đặt hay chưa */
  set?: boolean;
}

export interface ProviderStatus {
  type_env: string;
  type: string | null;
  service?: string;
  ok: boolean;
  error?: EnvError;
  fields: ProviderField[];
}

/** GET /settings/providers — lớp 2 đọc từ biến môi trường, chỉ xem. */
export interface ProvidersResponse {
  app_env: string;
  components: Record<string, ProviderStatus>;
}

export interface SearchHit {
  id: string;
  doc_id: string;
  doc_name: string;
  item_code: string;
  title: string;
  page_from: number;
  page_to: number;
  content: string;
  score: number;
  scores: Record<string, number>;
}
