"""Run isolated Go HTTP/SQL/real object-store verification without touching pilot state."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
subprocess.run(
    ["docker", "compose", "run", "--rm", "--no-deps", "-T", "trip-verifier"],
    cwd=ROOT,
    check=True,
)
