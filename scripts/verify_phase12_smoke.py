"""Live typed public/private flows, actual worker artifacts and secret-free summary."""

import csv
import hashlib
import io
import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pyarrow.parquet as pq
from netCDF4 import Dataset
import tempfile
from pathlib import Path

BASE = "http://localhost:8080/api/v1/"


def call(
    path, body=None, session=None, method=None, expected=200, version=None, binary=False
):
    headers = {"Origin": "http://localhost:3000"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if session:
        headers.update(
            {
                "Authorization": "Bearer " + session["session_token"],
                "X-CSRF-Token": session["csrf_token"],
                "X-Account-Scope": session["account_id"],
            }
        )
    if method and method != "GET" or body is not None:
        headers["Idempotency-Key"] = str(uuid.uuid4())
    if version:
        headers["If-Match"] = f'"{version}"'
    request = Request(
        BASE + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers=headers,
        method=method,
    )
    try:
        response = urlopen(request, timeout=15)
    except HTTPError as error:
        response = error
    with response:
        assert response.status == expected, (path, response.status, expected)
        data = response.read()
        if binary:
            assert (
                hashlib.sha256(data).hexdigest()
                == response.headers["X-Artifact-SHA256"]
            )
            return data
        return json.loads(data)


def main():
    now = datetime.now(timezone.utc)
    query = {
        "bbox": [45, 0, 100, 30],
        "start": (now - timedelta(days=365)).isoformat(),
        "end": now.isoformat(),
        "min_depth_m": 0,
        "max_depth_m": 2000,
        "variable": "temperature_c",
        "source": "argo_gdac",
        "qc": "accepted",
        "limit": 3,
    }
    first = call("research", query)
    assert first["items"] and all(row["level_count"] > 0 for row in first["items"])
    assert first["next_cursor"]
    next_page = call("research", {**query, "cursor": first["next_cursor"]})
    assert first["snapshot_at"] == next_page["snapshot_at"]
    assert not set(r["id"] for r in first["items"]) & set(
        r["id"] for r in next_page["items"]
    )
    call(
        "research",
        {**query, "bbox": [50, 0, 90, 30], "cursor": first["next_cursor"]},
        expected=400,
    )
    empty = call("research", {**query, "bbox": [-175, -80, -174, -79]})
    assert empty["items"] == []
    plan = call(
        "query",
        {
            "text": "temperature profiles in Arabian Sea from 2026-09-01 to 2026-10-01",
            "time_zone": "UTC",
        },
    )
    assert plan["plan"]["state"] == "ready" and not plan["executed"]
    assert (
        call("query", {"text": "fishing tomorrow near Goa", "time_zone": "UTC"})[
            "plan"
        ]["state"]
        == "clarification_required"
    )
    conditions = call("conditions/point?latitude=19&longitude=72.3")
    assert (
        len(conditions["fields"]) == 4
        and conditions["expected_at_point"]["state"] == "unavailable"
    )
    overview = call("map/overview")
    assert overview["advisory_state"] == "unknown"
    handle = "verify12_" + uuid.uuid4().hex[:12]
    password = uuid.uuid4().hex + "aA!"
    account = call("auth/register", {"handle": handle, "password": password})
    account.update(call("auth/session", session={**account, "account_id": ""}))
    states = []
    try:
        route = {
            "activity": "fishing",
            "threshold_version": call("trip-policy")["policy"]["version"],
            "spacing_km": 5,
            "step_minutes": 30,
            "preferences": {},
            "fields": [],
            "waypoints": [
                {
                    "latitude": 12,
                    "longitude": 72,
                    "time": (now + timedelta(hours=1)).isoformat(),
                },
                {
                    "latitude": 12.02,
                    "longitude": 72.02,
                    "time": (now + timedelta(hours=2)).isoformat(),
                },
            ],
        }
        owned = call(
            "routes",
            {"name": "verification route", "data": route},
            account,
            expected=201,
        )
        report = call(
            "reports",
            {"scope": "route", "target_id": owned["id"], "format": "html"},
            account,
            expected=202,
        )
        row = first["items"][0]
        observed = datetime.fromisoformat(row["observed_at"])
        bounded = {
            **query,
            "bbox": [
                row["longitude"] - 0.001,
                row["latitude"] - 0.001,
                row["longitude"] + 0.001,
                row["latitude"] + 0.001,
            ],
            "start": (observed - timedelta(seconds=1)).isoformat(),
            "end": (observed + timedelta(seconds=1)).isoformat(),
            "limit": 100,
        }
        observations = call("research", bounded)
        jobs = [
            call(
                "exports",
                {"scope": "research", "query": bounded, "format": fmt},
                account,
                expected=202,
            )
            for fmt in ("csv", "parquet", "netcdf")
        ]
        jobs.append(report)
        jobs.append(
            call(
                "reports",
                {"scope": "location", "place": "mumbai-offshore", "format": "json"},
                account,
                expected=202,
            )
        )
        if overview["events"]:
            jobs.append(
                call(
                    "reports",
                    {
                        "scope": "event",
                        "target_id": overview["events"][0]["event_id"],
                        "format": "json",
                    },
                    account,
                    expected=202,
                )
            )
        counts = {}
        for job in jobs:
            for _ in range(30):
                latest = call(job["kind"] + "/" + job["id"], session=account)
                if latest["state"] not in ("queued", "running"):
                    break
                time.sleep(0.2)
            assert latest["state"] == "ready", latest.get("reason")
            states.append(latest["state"])
            grant = call(
                job["kind"] + "/" + job["id"] + "/download-grants",
                session=account,
                method="POST",
                expected=201,
            )
            data = call(grant["path"].lstrip("/"), session=account, binary=True)
            call(grant["path"].lstrip("/"), session=account, expected=404)
            expected_rows = sum(r["level_count"] for r in observations["items"])
            if job["format"] == "csv":
                parsed = list(csv.DictReader(io.StringIO(data.decode())))
                assert (
                    len(parsed) == expected_rows
                    and parsed[0]["source_id"] == "argo_gdac"
                )
                counts["csv"] = len(parsed)
            elif job["format"] == "parquet":
                table = pq.read_table(io.BytesIO(data))
                assert table.num_rows == expected_rows
                counts["parquet"] = table.num_rows
            elif job["format"] == "netcdf":
                with tempfile.TemporaryDirectory() as folder:
                    path = Path(folder) / "observations.nc"
                    path.write_bytes(data)
                    with Dataset(path) as dataset:
                        assert len(dataset.dimensions["obs"]) == expected_rows
                        assert dataset["temperature_c"].units == "degree_Celsius"
                        counts["netcdf"] = expected_rows
            elif job["format"] == "json":
                payload = json.loads(data)
                assert (
                    payload["snapshot"]["provenance_only"]
                    and payload["input_sha256"] == latest["input_sha256"]
                )
            else:
                assert b"Frozen evidence" in data and b"verification route" in data
        summary = {
            "public_research_pagination": True,
            "empty_state": True,
            "typed_query_clarification": True,
            "location_variables": len(conditions["fields"]),
            "map_profiles": len(overview["profiles"]),
            "private_jobs_ready": len(states),
            "actual_argo_export_rows": counts,
            "single_use_downloads": True,
            "verification_account_deleted": True,
        }
    finally:
        call(
            "account",
            {"password": password},
            account,
            method="DELETE",
            version=account["version"],
        )
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
