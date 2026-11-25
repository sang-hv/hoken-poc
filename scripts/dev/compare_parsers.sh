#!/usr/bin/env bash
# So sánh Docling ↔ PaddleOCR trên cùng các trang PDF (chạy ngoài Docker, trên máy dev).
#   scripts/dev/compare_parsers.sh --pdf data/raw/x.pdf --pages 1-10
#   scripts/dev/compare_parsers.sh --manifest data/gt/manifest.csv        # CSV name,pdf,page (trang từ nhiều PDF)
#   ENGINES=paddleocr scripts/dev/compare_parsers.sh --pdf ...             # chỉ chạy lại một engine
# Mỗi engine một venv riêng (.venv-docling, .venv-paddleocr — torch và paddle không chung venv), tạo lần đầu bằng
# setup_parser.sh (tải model vài trăm MB → vài GB). Có data/gt/*.txt thì chạy thêm eval_cer.py (CER + lỗi số 点).
# Kết quả: data/ocr/<engine>/*.md, data/report/{parser_<engine>,per_page,errors,compare}.csv
set -euo pipefail
cd "$(dirname "$0")/../.."
[[ $# -gt 0 ]] || { sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }

for engine in ${ENGINES:-docling paddleocr}; do
  venv=".venv-$engine"
  if [[ ! -x "$venv/bin/python" ]] || ! "$venv/bin/python" -c "import $engine" 2>/dev/null; then
    echo "== Tạo $venv (lần đầu, tải thư viện + model)"
    PARSER_TYPE="$engine" PARSER_VENV="$venv" scripts/dev/setup_parser.sh
  fi
  echo "== $engine"
  "$venv/bin/python" eval/compare_parsers.py run --engine "$engine" "$@"
done

if compgen -G "data/gt/*.txt" >/dev/null; then
  python3 eval/eval_cer.py data
fi
python3 eval/compare_parsers.py report data
