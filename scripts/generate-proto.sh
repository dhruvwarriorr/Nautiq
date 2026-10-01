#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p services/api/gen ml/nautiuq_ml/gen
PATH="$PWD/.tools/bin:$PATH" .venv/bin/python -m grpc_tools.protoc \
  -I packages/proto \
  --go_out=services/api/gen --go_opt=paths=source_relative \
  --go-grpc_out=services/api/gen --go-grpc_opt=paths=source_relative \
  --python_out=ml/nautiuq_ml/gen --grpc_python_out=ml/nautiuq_ml/gen \
  packages/proto/nautiuq/platform/v1/platform.proto
# Python protoc emits absolute imports; qualify them within the scientific package.
.venv/bin/python - <<'FIX'
from pathlib import Path
root = Path('ml/nautiuq_ml/gen')
for path in root.rglob('*_pb2_grpc.py'):
    path.write_text(path.read_text().replace('from nautiuq.platform.v1 import', 'from nautiuq_ml.gen.nautiuq.platform.v1 import'))
for directory in [root, *[p for p in root.rglob('*') if p.is_dir()]]:
    (directory / '__init__.py').touch()
FIX
