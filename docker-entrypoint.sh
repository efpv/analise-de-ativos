#!/bin/sh
set -eu

# Cloud Run Job passa os argumentos do CLI (ex.: --full, --incremental).
# O serviço HTTP continua usando o CMD do Dockerfile (uvicorn).
case "${1:-}" in
  -*)
    exec python -m src.cli "$@"
    ;;
esac

exec "$@"
