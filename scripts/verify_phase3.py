"""Offline frozen scientific fixtures and deterministic training/freshness policy gate."""

import copy
import hashlib
import json
import math
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nautiq_ml.argo.evidence import canonical
from nautiq_ml.argo.freshness import evaluate
from nautiq_ml.argo.parser import InvalidProfile, parse, revision_digest
from nautiq_ml.argo.snapshots import load_policy, split, training_rows, utc
from verify_argo_parser import fixture

ROOT = Path(__file__).resolve().parents[1]


def main():
    directory = ROOT / "packages/scientific-fixtures/argo"
    expected = json.loads((directory / "manifest.json").read_text())
    raw = directory / "delayed-profile.nc"
    assert hashlib.sha256(raw.read_bytes()).hexdigest() == expected["raw_sha256"]
    assert raw.stat().st_size == expected["bytes"]
    result = parse(raw)
    assert canonical(result) == canonical(parse(raw))
    for profile, reference in zip(
        result["profiles"], expected["profiles"], strict=True
    ):
        for key in ("native_key", "observed_at", "data_mode"):
            assert profile[key] == reference[key]
        assert len(profile["levels"]) == reference["level_count"]
        for level, baseline in (
            (profile["levels"][0], reference["first_level"]),
            (profile["levels"][-1], reference["last_level"]),
        ):
            for key in (
                "pressure_dbar",
                "depth_m",
                "temperature_c",
                "practical_salinity",
            ):
                assert math.isclose(
                    level[key], baseline[key], rel_tol=0, abs_tol=1e-7
                ), key
            assert level["qc_flags"] == baseline["qc_flags"]
            assert level["missing_reasons"] == baseline["missing_reasons"]
        assert revision_digest(profile, expected["raw_sha256"]) == revision_digest(
            parse(raw)["profiles"][0], expected["raw_sha256"]
        )
    malformed = directory / "malformed.nc"
    assert (
        hashlib.sha256(malformed.read_bytes()).hexdigest()
        == expected["malformed_sha256"]
    )
    try:
        parse(malformed)
    except (OSError, InvalidProfile):
        pass
    else:
        raise AssertionError("Frozen malformed fixture accepted")
    policy = load_policy(ROOT / "packages/source-catalog/argo-training.json")
    for year, assignment in (
        (2004, None),
        (2005, "train"),
        (2016, "train"),
        (2017, "tune"),
        (2019, "tune"),
        (2020, "calibration"),
        (2021, "calibration"),
        (2022, "test"),
        (2024, "test"),
        (2025, None),
    ):
        assert split(f"{year}-01-01T00:00:00Z", policy) == assignment
    assert split("2017-01-01T00:30:00+01:00", policy) == "train"
    try:
        utc("2024-01-01T00:00:00")
    except ValueError:
        pass
    else:
        raise AssertionError("Naive training time accepted")
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "fixture.nc"
        fixture(path, "D", bad_salinity=True)
        profile = parse(path)["profiles"][0]
        profile.update(
            profile_id="frozen",
            revision_sha256="a" * 64,
            raw_sha256="b" * 64,
            observed_at="2010-01-01T00:00:00Z",
        )
        rows, reason = training_rows(profile, policy)
        assert reason is None and len(rows) == 3
        assert rows[1]["temperature_c"] == 24 and rows[1]["practical_salinity"] is None
        assert len({r["split"] for r in rows}) == 1
        profile["parameter_modes"]["TEMP"] = "R"
        rows, reason = training_rows(profile, policy)
        assert len(rows) == 2 and all(r["temperature_c"] is None for r in rows)
        bad_policy = copy.deepcopy(policy)
        bad_policy["splits"]["train_end"] = 2024
        path = Path(temp) / "policy.json"
        path.write_text(json.dumps(bad_policy))
        try:
            load_policy(path)
        except ValueError:
            pass
        else:
            raise AssertionError("Overlapping splits accepted")
    now = datetime(2026, 10, 2, tzinfo=timezone.utc)
    metadata = {
        "cadence_verified": False,
        "ingestion_budget_hours": 14,
        "coverage_state": "unverified",
    }
    run = {
        "upstream_checked_at": now - timedelta(hours=1),
        "started_at": now - timedelta(hours=2),
        "status": "complete",
    }

    def health(latest=run, success=run, newest=now - timedelta(hours=1), meta=metadata):
        return evaluate(meta, latest, success, newest, 0, None, 0, now)

    assert health()["source_freshness"] == "unverified"
    assert health()["ingestion_state"] == "on_schedule"
    assert health(None, None)["ingestion_state"] == "unknown"
    failed = dict(
        run, started_at=now, status="failed", reason_code="index_fetch_failed"
    )
    assert health(failed)["ingestion_state"] == "degraded"
    stale = dict(run, upstream_checked_at=now - timedelta(hours=15))
    assert health(stale, stale)["ingestion_state"] == "stale"
    future = dict(run, upstream_checked_at=now + timedelta(hours=1))
    assert health(future, future)["ingestion_state"] == "invalid_clock"
    verified = dict(metadata, cadence_verified=True, freshness_budget_hours=24)
    assert health(meta=verified)["source_freshness"] == "fresh"
    assert (
        health(meta=verified, newest=now - timedelta(hours=25))["source_freshness"]
        == "stale"
    )
    print(
        "Frozen GDAC fixture passed: source hashes, original levels, TEOS-10 depth tolerance, repeatable revisions, malformed quarantine, strict D/QC1 labels, independent missing variables, UTC temporal splits, explicit freshness states"
    )


if __name__ == "__main__":
    main()
