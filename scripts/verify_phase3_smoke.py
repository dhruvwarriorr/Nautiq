"""Live scientific evidence contracts, rendered pages and exact Parquet checksums."""

import hashlib
import io
import json
import urllib.request
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import pyarrow.parquet as pq
from jsonschema import Draft202012Validator

from verify_phase2 import API, ROOT, WEB, fetch, problem


def main():
    spec = json.loads((ROOT / "packages/schemas/science.openapi.json").read_text())

    def validate(value, name):
        Draft202012Validator(
            {"$ref": f"#/components/schemas/{name}", "components": spec["components"]},
            format_checker=Draft202012Validator.FORMAT_CHECKER,
        ).validate(value)

    sources = fetch("/api/v1/sources")
    validate(sources, "SourcePage")
    assert sources["items"]
    source = next(s for s in sources["items"] if s["source_id"] == "argo_gdac")
    assert source["monitor_state"] == "current", source
    assert source["health"]["source_freshness"] == "unverified"
    assert source["health"]["cadence_verified"] is False
    rejections = fetch("/api/v1/qc-rejections?limit=50")
    validate(rejections, "RejectionPage")
    assert rejections["items"]
    end = datetime.now(timezone.utc) + timedelta(minutes=1)
    page = fetch(
        "/api/v1/profiles?"
        + urlencode(
            {
                "bbox": "45,0,100,30",
                "start": (end - timedelta(days=366)).isoformat(),
                "end": end.isoformat(),
                "limit": 1,
            }
        )
    )
    profile = fetch("/api/v1/profiles/" + page["items"][0]["id"])
    pid = profile["id"]
    history = fetch(f"/api/v1/profiles/{pid}/revisions")
    validate(history, "RevisionPage")
    assert any(
        r["revision_sha256"] == profile["revision_sha256"]
        and r["selection_state"] == "current"
        for r in history["items"]
    )
    cid = profile["provenance"]["calculation_id"]
    assert cid
    calc = fetch("/api/v1/calculations/" + cid)
    validate(calc, "Calculation")
    assert (
        calc["state"] == "current"
        and calc["manifest"]["inputs"][0]["revision_sha256"]
        == profile["revision_sha256"]
    )
    stats = fetch(f"/api/v1/profiles/{pid}/statistics")
    validate(stats, "Statistics")
    assert (
        stats["status"] == "ready"
        and stats["revision_sha256"] == profile["revision_sha256"]
    )
    summary = fetch("/api/v1/calculations/" + stats["calculation_id"])
    validate(summary, "Calculation")
    assert summary["manifest"]["output"] == stats["statistics"]
    snapshots = fetch("/api/v1/training-snapshots")
    validate(snapshots, "SnapshotPage")
    assert snapshots["items"], "Build a frozen training snapshot first"
    sid = snapshots["items"][0]["snapshot_id"]
    snapshot = fetch("/api/v1/training-snapshots/" + sid)
    validate(snapshot, "Snapshot")
    assert (
        snapshot["row_count"] > 0
        and snapshot["manifest"]["output"]["release_approved"] is False
    )
    frozen_calc = fetch("/api/v1/calculations/" + snapshot["calculation_id"])
    validate(frozen_calc, "Calculation")
    assert frozen_calc["state"] == "frozen"
    expected = snapshot["parquet_sha256"]
    route = f"/api/v1/training-snapshots/{sid}/parquet"
    with urllib.request.urlopen(API + route, timeout=15) as response:
        data = response.read(134217729)
        assert hashlib.sha256(data).hexdigest() == expected
        assert response.headers["X-Parquet-SHA256"] == expected
    rows = pq.read_table(io.BytesIO(data)).to_pylist()
    assert len(rows) == snapshot["row_count"]
    splits = {}
    for row in rows:
        splits.setdefault(row["profile_id"], row["split"])
        assert splits[row["profile_id"]] == row["split"]
    assert len(splits) == snapshot["profile_count"]
    with urllib.request.urlopen(
        WEB + f"/training-snapshots/{sid}/parquet", timeout=15
    ) as response:
        assert response.read() == data
        assert response.headers["X-Parquet-SHA256"] == expected
    for path, phrase in (
        ("/data", "Know the evidence."),
        (f"/calculations/{cid}", cid),
        (f"/training-snapshots/{sid}", sid),
        (f"/profiles/{pid}", cid),
    ):
        with urllib.request.urlopen(WEB + path, timeout=15) as response:
            assert phrase in response.read().decode(), path
    for path in (
        "/sources?extra=1",
        "/qc-rejections?limit=1&limit=2",
        "/training-snapshots?limit=0",
        f"/calculations/{cid}?limit=1",
        f"/profiles/{pid}/statistics?extra=1",
        f"/training-snapshots/{sid}/parquet?extra=1",
    ):
        problem(
            "/api/v1" + path,
            400,
            "invalid_limit" if "limit=0" in path else "unknown_or_repeated_parameter",
        )
    problem("/api/v1/calculations/not-a-uuid", 404, "evidence_not_found")
    print(
        f"Live evidence passed: OpenAPI, source monitor, QC audit, retained revisions, normalization/summary manifests, frozen splits, API/web exact Parquet hashes, rendered pages and bounded errors; snapshot={sid}, profiles={len(splits)}, rows={len(rows)}"
    )


if __name__ == "__main__":
    main()
