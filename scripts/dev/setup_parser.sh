#!/usr/bin/env bash
# Tạo .venv-parser (Python 3.12) có Docling + RapidOCR (OCR tiếng Nhật) để chạy parser 標準解析 ngoài Docker.
# Docling chưa có wheel cho mọi bản Python mới, nên parser dùng venv riêng; API + worker khác vẫn dùng .venv.
#   scripts/dev/setup_parser.sh
#   PARSER_VENV=.venv-docling scripts/dev/setup_parser.sh   # venv khác (benchmark parser)
# Sau đó scripts/demo/up.sh tự chạy worker hàng đợi "docling" bằng .venv-parser. Cần `uv` (https://docs.astral.sh/uv/).
set -euo pipefail
cd "$(dirname "$0")/../.."
VENV="${PARSER_VENV:-.venv-parser}"

uv venv -q -p 3.12 --allow-existing "$VENV"
VIRTUAL_ENV="$VENV" uv pip install -q -e ".[docling]"
"$VENV/bin/docling-tools" models download >/dev/null   # tải model Docling + RapidOCR một lần
echo "OK: $VENV (docling)."
if [[ "$VENV" == ".venv-parser" ]]; then
  echo "Chạy scripts/demo/up.sh để dùng parser thật."
fi
