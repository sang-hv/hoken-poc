#!/usr/bin/env bash
# Dừng các tiến trình do scripts/demo/up.sh khởi động.
pkill -f "scripts.demo.mock_ai:app" || true
pkill -f "app.main serve" || true
pkill -f "app.main worker" || true
pkill -f "vite --host 0.0.0.0 --port 5173" || true
echo stopped
