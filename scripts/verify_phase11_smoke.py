"""Actual forecast/advisory trip receipt, privacy and replay contracts."""

import json
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError


def call(path, body=None, token=None, expected=200, method=None, web=False):
    headers = {}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    request = Request(
        ("http://localhost:3000/api" if web else "http://localhost:8080/api/v1") + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers=headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=15) as response:
            assert response.status == expected
            return json.load(response)
    except HTTPError as e:
        assert e.code == expected, (path, e.code)
        return json.load(e)


def main():
    policy = call("/trip-policy")
    assert not policy["engine_available"] and not policy["policy"]["approved"]
    fields = call("/fields?limit=200")["items"]
    bindings = [
        {
            "variable": s["variable"],
            "release_id": next(
                r["release_id"]
                for r in fields
                if r["product_id"] == s["product_id"]
                and r["selected"]
                and r["status"] == "ready"
            ),
        }
        for s in policy["policy"]["inputs"]
        if s["required"]
    ]
    now = datetime.now(timezone.utc)
    body = {
        "activity": "fishing",
        "threshold_version": policy["policy"]["version"],
        "waypoints": [
            {
                "latitude": 12,
                "longitude": 72,
                "time": (now + timedelta(minutes=20)).isoformat(),
            },
            {
                "latitude": 12.05,
                "longitude": 72.05,
                "time": (now + timedelta(minutes=80)).isoformat(),
            },
            {
                "latitude": 12,
                "longitude": 72,
                "time": (now + timedelta(minutes=140)).isoformat(),
            },
        ],
        "fields": bindings,
        "spacing_km": 5,
        "step_minutes": 30,
        "preferences": {},
    }
    result = call("/trips", body, expected=201)
    v = result["verdict"]
    assert (
        v["status"] == "insufficient_data"
        and not v["engine_available"]
        and not v["production_approved"]
    )
    assert (
        "threshold_release_unapproved_or_invalid" in v["missing_inputs"]
        and "advisory_coverage_unknown" in v["missing_inputs"]
    )
    assert len(v["worst_samples"]) == 2 and all(
        w["point"]["time"].startswith("2026-") and w["sample_status"] == "available"
        for w in v["worst_samples"]
    )
    assert len(v["source_cycles"]) == 2 and all(
        len(c["evidence_sha256"]) == 64 for c in v["source_cycles"]
    )
    cid, token = result["calculation_id"], result["access_token"]
    assert len(token) == 64
    call("/calculations/" + cid, expected=404)
    call("/trips/" + cid, expected=404)
    call("/trips/" + cid, token="0" * 64, expected=404)
    receipt = call("/trips/" + cid, token=token)
    assert receipt["receipt"]["output"] == v
    replay = call("/trips/" + cid + "/replay", token=token, method="POST")
    assert (
        replay["replayed"]
        and not replay["freshness_renewed"]
        and replay["verdict"] == v
    )
    via_web = call("/trips/" + cid, token=token, web=True)
    assert via_web["receipt"]["output"] == v
    call("/trips/" + cid, web=True, expected=404)
    bad = {**body, "preferences": {"wave_height_m": {"critical": 9}}}
    call("/trips", bad, expected=400)
    call("/trips", {**body, "threshold_version": "unapproved-other"}, expected=400)
    call(
        "/trips",
        {**body, "waypoints": [body["waypoints"][0], body["waypoints"][0]]},
        expected=400,
    )
    call("/trips", {**body, "fields": [bindings[0], bindings[0]]}, expected=400)
    call("/trip-policy?unknown=1", expected=400)
    cap = call("/capabilities")["capabilities"]
    assert (
        cap["trip_diagnostics"]
        and not cap["trip_assessment"]
        and not cap["official_advisories"]
    )
    with urlopen("http://localhost:3000/trips") as response:
        assert (
            "Current trips cannot receive a favorable assessment."
            in response.read().decode()
        )
    summary = {
        "calculation_id": cid,
        "manifest_sha256": result["manifest_sha256"],
        "status": v["status"],
        "as_of": v["as_of"],
        "threshold_version": v["threshold_version"],
        "sample_count": v["sampling"]["sample_count"],
        "worst_variable_count": len(v["worst_samples"]),
        "source_cycles": v["source_cycles"],
        "engine_available": False,
        "production_approved": False,
        "validation": [
            "real NOAA wave and wind route samples",
            "registered NDMA CAP source and unknown INCOIS/completeness",
            "private header access and public calculation exclusion",
            "frozen replay without renewed freshness",
            "strict input bounds and web proxy",
        ],
    }
    from pathlib import Path

    Path("/tmp/nautiq-trip-live-summary.json").write_text(
        json.dumps(summary, indent=2) + "\n"
    )
    print(
        "Live trip contracts passed: real wave/wind samples, explicit unavailable policy and unknown advisories, private receipts, exact replay, strict bounds and web proxy."
    )


if __name__ == "__main__":
    main()
