#!/usr/bin/env bash
# Benchmark parser 標準解析 (Docling + RapidOCR) trên các trang PDF chọn sẵn (chạy ngoài Docker, trên máy dev).
#   scripts/dev/compare_parsers.sh --pdf data/raw/x.pdf --pages 1-10
#   scripts/dev/compare_parsers.sh --manifest data/gt/manifest.csv        # CSV name,pdf,page (trang từ nhiều PDF)
# Dùng venv riêng .venv-docling, tạo lần đầu bằng setup_parser.sh (tải thư viện + model).
# Có data/gt/*.txt thì chạy thêm eval_cer.py (CER + lỗi số 点).
# Kết quả: data/ocr/docling/*.md, data/report/{parser_docling,per_page,errors,compare}.csv
set -euo pipefail
cd "$(dirname "$0")/../.."
[[ $# -gt 0 ]] || { sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }

venv=".venv-docling"
if [[ ! -x "$venv/bin/python" ]] || ! "$venv/bin/python" -c "import docling" 2>/dev/null; then
  echo "== Tạo $venv (lần đầu, tải thư viện + model)"
  PARSER_VENV="$venv" scripts/dev/setup_parser.sh
fi
"$venv/bin/python" eval/compare_parsers.py run --engine docling "$@"

if compgen -G "data/gt/*.txt" >/dev/null; then
  python3 eval/eval_cer.py data
fi
python3 eval/compare_parsers.py report data
