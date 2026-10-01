#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
for tool in go npm uv docker; do
  command -v "$tool" >/dev/null || { echo "Missing prerequisite: $tool" >&2; exit 1; }
done
[ -f .env ] || cp .env.example .env
[ -x .venv/bin/python ] || uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e './ml[dev]'
(cd apps/web && npm ci)
GOBIN="$PWD/.tools/bin" go install google.golang.org/protobuf/cmd/protoc-gen-go@v1.36.11
GOBIN="$PWD/.tools/bin" go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@v1.6.1
bash scripts/generate-proto.sh
(cd services/api && go mod download)
(cd services/ingestion && go mod download)
uv pip install --python .venv/bin/python -r ml/requirements-argo.lock
