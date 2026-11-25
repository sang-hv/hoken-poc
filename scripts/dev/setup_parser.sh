#!/usr/bin/env bash
# Tạo .venv-parser (Python 3.12) có parser theo PARSER_TYPE trong .env (docling | paddleocr) để chạy ngoài Docker.
# Docling / Paddle chưa có wheel cho mọi bản Python mới, nên parser dùng venv riêng; API + worker khác vẫn dùng .venv.
#   scripts/dev/setup_parser.sh                 # theo PARSER_TYPE trong .env (mặc định docling)
#   PARSER_TYPE=paddleocr scripts/dev/setup_parser.sh
#   PARSER_TYPE=paddleocr PARSER_VENV=.venv-paddleocr scripts/dev/setup_parser.sh   # venv khác (so sánh parser)
# Sau đó scripts/demo/up.sh tự chạy worker hàng đợi "docling" bằng .venv-parser. Cần `uv` (https://docs.astral.sh/uv/).
set -euo pipefail
cd "$(dirname "$0")/../.."
if [[ -z "${PARSER_TYPE:-}" && -f .env ]]; then
  PARSER_TYPE="$(grep -E '^PARSER_TYPE=' .env | tail -1 | cut -d= -f2 | awk '{print $1}')"
fi
PARSER_TYPE="${PARSER_TYPE:-docling}"
case "$PARSER_TYPE" in docling|paddleocr) ;; *) echo "PARSER_TYPE phải là docling hoặc paddleocr" >&2; exit 1 ;; esac

VENV="${PARSER_VENV:-.venv-parser}"

uv venv -q -p 3.12 --allow-existing "$VENV"
VIRTUAL_ENV="$VENV" uv pip install -q -e ".[${PARSER_TYPE}]"
echo "${PARSER_TYPE}" > "$VENV/PARSER_TYPE"
if [[ "$PARSER_TYPE" == "paddleocr" ]]; then
  "$VENV/bin/python" -m app.steps.paddle_engine warmup   # tải model PP-StructureV3 (~ vài trăm MB) một lần
else
  "$VENV/bin/docling-tools" models download >/dev/null   # tải model Docling một lần
fi
echo "OK: $VENV (${PARSER_TYPE})."
if [[ "$VENV" == ".venv-parser" ]]; then
  echo "Đặt PARSER_TYPE=${PARSER_TYPE} trong .env rồi chạy scripts/demo/up.sh"
fi
