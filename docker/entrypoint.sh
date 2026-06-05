#!/usr/bin/env bash
# Apply migrations, then serve the API. The DB lives on a mounted volume so run
# history survives container restarts.
set -euo pipefail

mkdir -p /data

echo "Applying database migrations..."
alembic upgrade head

echo "Starting BenchBot API on 0.0.0.0:8000..."
exec uvicorn benchbot.api.app:create_app --factory --host 0.0.0.0 --port 8000
