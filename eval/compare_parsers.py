#!/usr/bin/env python3
"""
So sánh parser 標準解析 (Docling ↔ PaddleOCR) trên cùng các trang PDF.

Bước 1 — `run`: chạy MỘT engine (bằng venv có thư viện engine đó), mỗi trang ghi:
    data/ocr/<engine>/<tên>.md              Markdown của parser → đầu vào cho eval_cer.py
    data/report/parser_<engine>.csv         thời gian, điểm parser, định tuyến dễ/khó + lý do, số phần tử ⚠
Bước 2 — `eval_cer.py data`: CER + lỗi số 点 so với data/gt/<tên>.txt (nếu đã có ground truth).
Bước 3 — `report`: gộp hai bước trên thành bảng so sánh theo engine (chỉ cần thư viện chuẩn).

Chọn trang:
    --pdf data/raw/x.pdf --pages 1,3,10-12  → tên trang page_001, page_003, ... (số trang trong PDF)
    --manifest data/gt/manifest.csv          → CSV `name,pdf,page`, khi trang lấy từ nhiều PDF;
                                               `name` trùng tên file ground truth (data/gt/<name>.txt),
                                               `pdf` tính từ thư mục chứa manifest (hoặc từ thư mục hiện tại)

Chạy (thường gọi qua scripts/dev/compare_parsers.sh, script đó tạo sẵn venv từng engine):
    .venv-docling/bin/python   eval/compare_parsers.py run --engine docling   --pdf data/raw/x.pdf --pages 1-10
    .venv-paddleocr/bin/python eval/compare_parsers.py run --engine paddleocr --pdf data/raw/x.pdf --pages 1-10
    python3 eval/eval_cer.py data
    python3 eval/compare_parsers.py report data

Điểm parser, định tuyến và ngưỡng ⚠ dùng mặc định trong code (DoclingOptions, RoutingOptions, QualityOptions) —
giống pipeline khi Admin chưa đổi ngưỡng. Không in nội dung tài liệu ra màn hình, chỉ tên trang + số đo.
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

ENGINES = ("docling", "paddleocr")

RUN_FIELDS = [
    "name", "pdf", "page", "engine", "seconds",
    "parse_score", "layout_score", "ocr_score", "table_score", "mean_score", "low_score", "low_grade",
    "has_text_layer", "n_tables", "complex_tables", "n_figures", "max_figure_area",
    "route", "route_reasons", "n_elements", "n_conf", "n_weak", "n_reread", "chars",
]  # fmt: skip


# ================================================================== chọn trang
def parse_pages(spec: str, n_pages: int) -> list[int]:
    """'1,3,10-12' → [1, 3, 10, 11, 12]; 'all' → mọi trang. Giữ thứ tự, bỏ trùng, báo lỗi khi vượt số trang."""
    if spec.strip().lower() == "all":
        return list(range(1, n_pages + 1))
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        a, _, b = part.partition("-")
        lo, hi = int(a), int(b or a)
        if lo < 1 or hi > n_pages or lo > hi:
            raise ValueError(f"trang {part} ngoài khoảng 1..{n_pages}")
        out.extend(range(lo, hi + 1))
    return list(dict.fromkeys(out))


def pdf_page_count(path: Path) -> int:
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(path))
    try:
        return len(doc)
    finally:
        doc.close()


def items_from_args(args) -> list[tuple[str, Path, int]]:
    """Danh sách (tên, pdf, số trang)."""
    if args.manifest:
        man = Path(args.manifest)
        items = []
        with open(man, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                pdf = Path(row["pdf"])
                if not pdf.is_absolute() and (man.parent / pdf).exists():
                    pdf = man.parent / pdf
                items.append((row["name"].strip(), pdf, int(row["page"])))
        return items
    pdf = Path(args.pdf)
    return [(f"page_{n:03d}", pdf, n) for n in parse_pages(args.pages, pdf_page_count(pdf))]


# ================================================================== bước 1: chạy một engine
def page_row(name: str, pdf: Path, page: int, a, seconds: float, routing, quality) -> dict:
    """Số đo một trang từ PageAnalysis — định tuyến bằng đúng luật của pipeline (rules.decide_route)."""
    from app.domain.models import Page
    from app.steps import rules

    p = Page(id=f"{page:04d}", doc_id="compare", page=page, book_page=page,
             engine=a.engine, scores=a.scores, features=a.features)  # fmt: skip
    route, reasons = rules.decide_route(p, routing)
    kept = [e for e in a.elements if not e.get("removed")]
    confs = [e["confidence"] for e in kept if e.get("confidence") is not None]
    s, f = a.scores, a.features
    return {
        "name": name, "pdf": pdf.name, "page": page, "engine": a.engine, "seconds": f"{seconds:.2f}",
        "parse_score": _fmt(s.parse_score), "layout_score": _fmt(s.layout_score), "ocr_score": _fmt(s.ocr_score),
        "table_score": _fmt(s.table_score), "mean_score": _fmt(s.mean_score), "low_score": _fmt(s.low_score),
        "low_grade": s.low_grade, "has_text_layer": int(f.has_text_layer), "n_tables": f.n_tables,
        "complex_tables": f.complex_tables, "n_figures": f.n_figures, "max_figure_area": f"{f.max_figure_area:.3f}",
        "route": route, "route_reasons": ";".join(reasons), "n_elements": len(kept), "n_conf": len(confs),
        "n_weak": sum(c < quality.weak_confidence for c in confs),
        "n_reread": sum(c < quality.auto_vlm_below for c in confs),
        "chars": len(a.markdown.strip()),
    }  # fmt: skip


def _fmt(v: float | None) -> str:
    return "" if v is None else f"{v:.3f}"


def run_engine(engine: str, items, data_dir: Path, allow_fallback: bool = False, analyze=None) -> list[dict]:
    from app.domain.options import DoclingOptions, QualityOptions, RoutingOptions
    from app.steps.parser import analyze_page, parser_available

    if not allow_fallback and not parser_available(engine):
        raise SystemExit(
            f"Venv này chưa có thư viện {engine}. Tạo bằng: PARSER_TYPE={engine} PARSER_VENV=.venv-{engine} "
            "scripts/dev/setup_parser.sh"
        )
    analyze = analyze or analyze_page
    opts, routing, quality = DoclingOptions(), RoutingOptions(), QualityOptions()
    out_dir = data_dir / "ocr" / engine
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_cache: dict[Path, bytes] = {}
    rows = []
    for i, (name, pdf, page) in enumerate(items, 1):
        data = pdf_cache.setdefault(pdf, pdf.read_bytes())
        t0 = time.perf_counter()
        a = analyze(data, page, opts, parser=engine)
        dt = time.perf_counter() - t0
        if a.engine != engine and not allow_fallback:
            raise SystemExit(f"{name}: engine trả về '{a.engine}' thay vì '{engine}' — kiểm tra venv")
        (out_dir / f"{name}.md").write_text(a.markdown, encoding="utf-8")
        row = page_row(name, pdf, page, a, dt, routing, quality)
        rows.append(row)
        print(f"[{engine}] {i}/{len(items)} {name}  {dt:6.1f}s  {row['route']:<4} {row['route_reasons']}", flush=True)

    report = data_dir / "report"
    report.mkdir(parents=True, exist_ok=True)
    with open(report / f"parser_{engine}.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=RUN_FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"→ {out_dir}/  ·  {report / f'parser_{engine}.csv'}")
    return rows


# ================================================================== bước 3: bảng so sánh
def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def summarize(data_dir: Path) -> list[dict]:
    """Một dòng mỗi engine: tốc độ, định tuyến, phần tử ⚠ (từ parser_<engine>.csv) + CER / số 点 (từ per_page.csv)."""
    report = data_dir / "report"
    cer_rows = _read_csv(report / "per_page.csv")
    out = []
    for path in sorted(report.glob("parser_*.csv")):
        engine = path.stem.removeprefix("parser_")
        rows = _read_csv(path)
        if not rows:
            continue
        secs = [float(r["seconds"]) for r in rows]
        # trang đầu gồm cả thời gian nạp model → trung vị tính từ trang thứ hai (nếu có)
        steady = secs[1:] or secs
        reasons = Counter(x for r in rows for x in r["route_reasons"].split(";") if x)
        mine = [r for r in cer_rows if r["engine"] == engine]
        chars = sum(int(r["chars_gt"]) for r in mine)
        errs = sum(int(r["S_thay"]) + int(r["D_thieu"]) + int(r["I_thua"]) for r in mine)
        out.append({
            "engine": engine,
            "pages": len(rows),
            "fallback": sum(r["engine"] != engine for r in rows),
            "first_s": f"{secs[0]:.1f}",
            "median_s": f"{statistics.median(steady):.1f}",
            "total_s": f"{sum(secs):.0f}",
            "easy": sum(r["route"] == "easy" for r in rows),
            "hard": sum(r["route"] == "hard" for r in rows),
            "reasons": " ".join(f"{k}={v}" for k, v in reasons.most_common()),
            "elements": sum(int(r["n_elements"]) for r in rows),
            "with_conf": sum(int(r["n_conf"]) for r in rows),
            "weak": sum(int(r["n_weak"]) for r in rows),
            "reread": sum(int(r["n_reread"]) for r in rows),
            "gt_pages": len(mine),
            "cer": f"{errs / chars:.2%}" if chars else "-",
            "points": sum(int(r["so_diem_gt"]) for r in mine) if mine else "-",
            "point_errors": sum(int(r["so_diem_sai"]) for r in mine) if mine else "-",
        })  # fmt: skip
    return out


def print_report(data_dir: Path) -> int:
    rows = summarize(data_dir)
    if not rows:
        print(f"Chưa có {data_dir / 'report'}/parser_*.csv — chạy bước `run` trước.", file=sys.stderr)
        return 1
    cols = [
        ("engine", "engine"), ("pages", "trang"), ("first_s", "trang đầu s"), ("median_s", "trung vị s"),
        ("easy", "dễ"), ("hard", "khó→CU"), ("weak", "⚠ yếu"), ("reread", "AI đọc lại"),
        ("gt_pages", "trang GT"), ("cer", "CER"), ("point_errors", "sai 点"),
    ]  # fmt: skip
    # chỉ thư viện chuẩn, chạy được cả python3 hệ thống (3.9)
    width = {k: max(len(h), *(len(str(r[k])) for r in rows)) + 2 for k, h in cols}
    print("\n=== SO SÁNH PARSER ===")
    print("".join(h.rjust(width[k]) for k, h in cols))
    for r in rows:
        print("".join(str(r[k]).rjust(width[k]) for k, _ in cols))
    print()
    for r in rows:
        print(f"{r['engine']}: lý do khó → {r['reasons'] or '-'}")
        if r["fallback"]:
            print(f"{r['engine']}: ⚠ {r['fallback']} trang chạy bằng fallback pdfium, không phải {r['engine']}")
        if r["point_errors"] not in ("-", 0):
            print(f"{r['engine']}: ⚠ có lỗi số 点 — xem {data_dir / 'report' / 'errors.csv'}")
    if not any(r["gt_pages"] for r in rows):
        print("Chưa có CER: thêm data/gt/<tên>.txt rồi chạy `python3 eval/eval_cer.py data`.")
    path = data_dir / "report" / "compare.csv"
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"\nChi tiết: {path}")
    return 0


# ================================================================== CLI
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="chạy một engine trên các trang đã chọn")
    r.add_argument("--engine", required=True, choices=ENGINES)
    src = r.add_mutually_exclusive_group(required=True)
    src.add_argument("--pdf")
    src.add_argument("--manifest")
    r.add_argument("--pages", default="all", help="vd 1,3,10-12 (mặc định all); chỉ dùng với --pdf")
    r.add_argument("--data", default="data")
    r.add_argument("--allow-fallback", action="store_true", help="cho chạy khi thiếu thư viện (chỉ để thử)")
    s = sub.add_parser("report", help="gộp kết quả thành bảng so sánh")
    s.add_argument("data_dir", nargs="?", default="data")
    args = ap.parse_args(argv)

    if args.cmd == "report":
        return print_report(Path(args.data_dir))
    run_engine(args.engine, items_from_args(args), Path(args.data), args.allow_fallback)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
