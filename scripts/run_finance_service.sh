#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
HOST="${FINANCE_SERVICE_HOST:-127.0.0.1}"
PORT="${FINANCE_SERVICE_PORT:-8000}"

cd "$PROJECT_DIR"
exec uv run --project "$PROJECT_DIR" uvicorn finance_service.app:app --app-dir "$PROJECT_DIR/src" --host "$HOST" --port "$PORT"
