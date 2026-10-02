"""Local live event evidence, schema, bounds, exact pins and rendered user-flow checks."""

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
API = os.environ.get("API_URL", "http://localhost:8080")
WEB = os.environ.get("WEB_URL", "http://localhost:3000")
SPEC = json.loads((ROOT / "packages/schemas/events.openapi.json").read_text())


def http(url, status=200):
    try:
        r = urllib.request.urlopen(url, timeout=12)
    except urllib.error.HTTPError as e:
        r = e
    with r:
        raw = r.read(16777217)
        assert r.status == status, (url, r.status, raw[:150])
        assert len(raw) <= 16777216
        return raw


def get(path, schema, status=200):
    value = json.loads(http(API + "/api/v1/" + path, status))
    jsonschema.Draft202012Validator(
        {**SPEC, "$ref": "#/components/schemas/" + schema},
        format_checker=jsonschema.FormatChecker(),
    ).validate(value)
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture", action="store_true")
    args = parser.parse_args()
    catalog = get("event-runs?limit=50", "RunPage")
    datasets = get("event-datasets?limit=50", "DatasetPage")
    assert {r["kind"] for r in catalog["items"]} == {
        "surface_thermal",
        "profile_groups",
    }
    evidence = []
    for r in catalog["items"]:
        t = time.perf_counter()
        detail = get("event-runs/" + r["run_id"], "Run")
        elapsed = (time.perf_counter() - t) * 1000
        assert (
            detail["run_id"] == r["run_id"]
            and detail["report_sha256"] == r["report_sha256"]
            and not detail["report"]["release_approved"]
        )
        assert len(detail["report"]["events"]) == r["event_count"]
        listed = get("events?run_id=" + r["run_id"], "EventPage")
        assert len(listed["items"]) == r["event_count"]
        for e in detail["report"]["events"]:
            item = get("events/" + e["event_id"], "EventDetail")
            assert item["event"] == e and item["run_id"] == r["run_id"]
            assert (e["kind"] == "surface_thermal_candidate") == (
                e["geometry"]["type"] != "MultiPoint"
            )
            if e["kind"] == "isolated_profile_anomalies":
                assert e["support_kind"] == "observed_profile_points"
            html = http(WEB + "/events/" + e["event_id"])
            assert e["event_id"].encode() in html
        report = detail["report"]
        html = http(WEB + "/events/runs/" + r["run_id"])
        assert r["report_sha256"].encode() in html and b"Source coverage" in html
        calc = http(WEB + "/calculations/" + r["calculation_id"])
        assert r["calculation_id"].encode() in calc
        evidence.append(
            dict(
                run_id=r["run_id"],
                kind=r["kind"],
                calculation_id=r["calculation_id"],
                report_sha256=r["report_sha256"],
                input_state=detail["input_state"],
                manifest=detail["manifest"],
                start=report["start"],
                end=report["end"],
                extent=report["extent"],
                event_count=len(report["events"]),
                coverage=report["coverage"],
                components=[
                    {k: v for k, v in e.items() if k != "members"}
                    for e in report["events"]
                ],
                request_ms=elapsed,
            )
        )
    ds = []
    for d in datasets["items"]:
        item = get("event-datasets/" + d["dataset_id"], "Dataset")
        assert item["manifest_sha256"] == d["manifest_sha256"]
        ds.append(item)
        html = http(WEB + "/events/datasets/" + d["dataset_id"])
        assert d["dataset_id"].encode() in html
    for path in [
        "event-runs?limit=201",
        "event-runs?limit=1&limit=2",
        "event-runs?kind=alert",
        "event-datasets?kind=live",
        "events?bbox=nan,0,2,3",
        "events?bbox=2,0,1,3",
        "events?start=2026-09-01",
        "events?start=2024-01-01&end=2026-09-01",
        "events?run_id=invalid",
        "events?unknown=1",
        "event-runs/" + catalog["items"][0]["run_id"] + "?limit=1",
    ]:
        get(path, "Problem", 400)
    get("event-runs/00000000-0000-0000-0000-000000000000", "Problem", 404)
    cap = json.loads(http(API + "/api/v1/capabilities"))["capabilities"]
    assert (
        cap["event_detection_diagnostics"]
        and not cap["regional_events"]
        and not cap["profile_anomaly"]
        and not cap["trip_assessment"]
    )
    assert b"Separate a departure" in http(WEB + "/events")
    if args.capture:
        (ROOT / "docs/evidence/phase9-summary.json").write_text(
            json.dumps(
                dict(
                    captured_at=datetime.now(timezone.utc).isoformat(),
                    scope="Local real retained NOAA daily archive and Argo comparison evidence. Synthetic positive fixtures run only in disposable SQL. This does not validate expert events, quiet-period false-alert rates, live cadence or scientific approval.",
                    capabilities=cap,
                    datasets=ds,
                    runs=evidence,
                ),
                indent=2,
            )
            + "\n"
        )
    print(
        "Live event gate passed: both methods, typed catalogs/reports/components and dataset/calculation pages, exact report/input pins, native versus sparse point geometry, UTC windows/bbox/query limits, missing evidence and independent diagnostic/scientific flags."
    )


if __name__ == "__main__":
    main()
