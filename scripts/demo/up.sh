#!/usr/bin/env bash
# Chạy khu A ngoài Docker (dev): mock AI + API + worker + Vite.
# Parser thật (Docling): chạy scripts/dev/setup_parser.sh một lần → worker parser dùng .venv-parser.
#   ENV_FILE=path/to/env scripts/demo/up.sh          # mặc định .env
#   SEED=1 scripts/demo/up.sh                         # seed dữ liệu giả (lần đầu)
#   SEED=reset scripts/demo/up.sh                     # xoá tài liệu cũ rồi seed lại
#   MOCK_AI=0 scripts/demo/up.sh                      # dịch vụ AI thật theo .env (full pipeline)
# Log ghi vào out/demo/logs/. Dừng: scripts/demo/down.sh
# Chạy được trên Linux và macOS (macOS không có setsid → dùng nohup).
set -euo pipefail
cd "$(dirname "$0")/../.."
ENV_FILE="${ENV_FILE:-.env}"
LOGS=out/demo/logs
mkdir -p "$LOGS"
# MOCK_AI=1 (mặc định): dịch vụ AI → mock (demo.env). MOCK_AI=0: dùng LLM_* / EMBEDDING_* / CU_* / SEARCH_* trong .env
MOCK_AI="${MOCK_AI:-1}"
set -a; . "$ENV_FILE"; [[ "$MOCK_AI" == "1" ]] && . scripts/demo/demo.env; set +a

detach() { # log, lệnh...
  local log=$1; shift
  if command -v setsid >/dev/null 2>&1; then
    setsid nohup "$@" > "$log" 2>&1 < /dev/null &
  else
    nohup "$@" > "$log" 2>&1 < /dev/null &
  fi
}

start() { # tên, lệnh...
  local name=$1; shift
  pkill -f "$*" 2>/dev/null || true
  detach "$LOGS/$name.log" "$@"
  echo "started $name (log: $LOGS/$name.log)"
}

[[ "$MOCK_AI" == "1" ]] && start mock-ai .venv/bin/python -m uvicorn scripts.demo.mock_ai:app --port 8100
sleep 2
if [[ "${SEED:-0}" == "1" || "${SEED:-0}" == "reset" ]]; then
  [[ -f out/demo/akahon_sample_536-543.pdf ]] || NODE_PATH="$(npm root -g)" node scripts/demo/make_pdfs.js out/demo
  pkill -f "app.main worker" 2>/dev/null || true
  .venv/bin/python -m scripts.demo.seed $([[ "${SEED}" == "reset" ]] && echo --reset)
fi
start api .venv/bin/python -m app.main serve --port 8000
pkill -f "app.main worker" 2>/dev/null || true
# Có .venv-parser (scripts/dev/setup_parser.sh) → worker parser thật chạy riêng; không có → parser fallback pdfium
if [[ -x .venv-parser/bin/python ]]; then
  start worker .venv/bin/python -m app.main worker --queues ai,light
  start worker-parser .venv-parser/bin/python -m app.main worker --queues docling
else
  start worker .venv/bin/python -m app.main worker --queues docling,ai,light
fi
pkill -f "vite --host 0.0.0.0 --port 5173" 2>/dev/null || true
(cd web && detach "../$LOGS/web.log" npx vite --host 0.0.0.0 --port 5173)
echo "started web (http://localhost:5173)"
