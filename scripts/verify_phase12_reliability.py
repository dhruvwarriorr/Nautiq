"""Run isolated private API and worker acceptance with disposable databases."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
subprocess.run(
    ["docker", "compose", "run", "--rm", "--no-deps", "-T", "product-verifier"],
    cwd=ROOT,
    check=True,
)
subprocess.run(
    [
        "docker",
        "compose",
        "run",
        "--rm",
        "--no-deps",
        "-T",
        "-v",
        str(ROOT / "migrations") + ":/migrations:ro",
        "export-worker",
        "python",
        "-",
    ],
    cwd=ROOT,
    input=(ROOT / "scripts/verify_phase12_worker.py").read_bytes(),
    check=True,
)
