"""Fail-closed release review: implementation checks never grant external approval."""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    policy = json.loads((ROOT / "packages/source-catalog/production.json").read_text())
    evidence = json.loads(args.evidence.read_text()) if args.evidence else {}
    missing = []
    for name in policy["required_external_gates"]:
        record = evidence.get(name, {})
        if (
            record.get("approved") is not True
            or not record.get("reviewer")
            or not record.get("evidence_uri")
            or not record.get("sha256")
        ):
            missing.append(name)
    print(
        json.dumps(
            {
                "production_approved": False,
                "scientific_approved": False,
                "unproven_external_gates": missing,
                "meaning": "Review records are evidence inputs only. This release policy does not authorize promotion.",
            },
            sort_keys=True,
        )
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
