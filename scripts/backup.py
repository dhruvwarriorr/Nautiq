"""Quiesce only currently running writers, create encrypted backup, restore service state."""

import argparse
import fcntl
import json
import os
import subprocess
from pathlib import Path

WRITERS = {
    "api",
    "notifications",
    "ingestion",
    "normalizer",
    "field-ingestion",
    "ml-inference",
    "export-worker",
    "advisory-worker",
    "event-worker",
}
ROOT = Path(__file__).resolve().parents[1]


def compose(*args, **kwargs):
    return subprocess.run(["docker", "compose", *args], cwd=ROOT, check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--key-file", type=Path, required=True)
    args = parser.parse_args()
    destination = args.directory.resolve()
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    if destination.stat().st_mode & 0o077 or args.key_file.stat().st_mode & 0o077:
        raise ValueError("backup_directory_and_key_must_be_private")
    with (destination / ".backup.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = compose("ps", "--format", "json", capture_output=True, text=True)
        running = [
            item["Service"]
            for line in result.stdout.splitlines()
            if (item := json.loads(line))["Service"] in WRITERS
            and item["State"] == "running"
        ]
        filename = "nautiq-" + __import__("uuid").uuid4().hex + ".backup"
        try:
            if running:
                compose("stop", "--timeout", "40", *running)
            compose(
                "run",
                "--rm",
                "--no-deps",
                "-T",
                "-v",
                str(destination) + ":/backup",
                "-v",
                str(args.key_file.resolve()) + ":/run/secrets/backup_key:ro",
                "-e",
                "BACKUP_KEY_FILE=/run/secrets/backup_key",
                "operations-tools",
                "create",
                "/backup/" + filename,
                "--writers-quiesced",
            )
            print("Encrypted backup created: " + str(destination / filename))
        finally:
            if running:
                compose("start", *running)
    if os.getenv("NAUTIQ_DEPLOYMENT") == "production":
        print(
            "Use the selected production Compose files through COMPOSE_FILE; retain a separately secured backup key."
        )


if __name__ == "__main__":
    main()
