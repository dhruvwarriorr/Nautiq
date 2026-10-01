"""Live Argo slice gate: contracts, cursor binding, and exact retained raw bytes."""

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
API = f"http://127.0.0.1:{os.environ.get('API_PORT', '8080')}"
WEB = f"http://127.0.0.1:{os.environ.get('WEB_PORT', '3000')}"


def fetch(path):
    with urllib.request.urlopen(API + path, timeout=12) as response:
        return json.load(response)


def problem(path, status, code):
    try:
        fetch(path)
    except urllib.error.HTTPError as error:
        assert error.code == status
        assert error.headers["Content-Type"] == "application/problem+json"
        value = json.load(error)
        assert value["code"] == code, value
        assert value["request_id"]
    else:
        raise AssertionError("Invalid request accepted")


def main():
    end = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    ) + timedelta(days=1)
    start = end - timedelta(days=366)
    query = {
        "bbox": "45,0,100,30",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "limit": "1",
    }
    route = "/api/v1/profiles?" + urllib.parse.urlencode(query)
    page = None
    for attempt in range(120):
        try:
            page = fetch(route)
            if page["items"]:
                break
        except (OSError, KeyError):
            pass
        if attempt == 119:
            raise SystemExit(
                "No accepted profiles became queryable; inspect ingestion/normalizer logs."
            )
        time.sleep(2)
    spec = json.loads((ROOT / "packages/schemas/profiles.openapi.json").read_text())

    def validate(value, name):
        Draft202012Validator(
            {"$ref": f"#/components/schemas/{name}", "components": spec["components"]}
        ).validate(value)

    validate(page, "ProfilePage")
    selected = page["items"][0]
    profile = fetch("/api/v1/profiles/" + selected["id"])
    validate(profile, "Profile")
    raw_path = f"/api/v1/profiles/{profile['id']}/raw?revision_sha256={profile['revision_sha256']}"
    with urllib.request.urlopen(API + raw_path, timeout=12) as response:
        raw = response.read()
        assert hashlib.sha256(raw).hexdigest() == profile["provenance"]["raw_sha256"]
        assert response.headers["X-Raw-SHA256"] == profile["provenance"]["raw_sha256"]
    if page["next_cursor"]:
        second = dict(query, cursor=page["next_cursor"])
        other = fetch("/api/v1/profiles?" + urllib.parse.urlencode(second))
        assert other["snapshot_at"] == page["snapshot_at"]
        assert other["items"][0]["id"] != selected["id"]
        validate(other, "ProfilePage")
        changed = dict(second, bbox="46,0,100,30")
        problem(
            "/api/v1/profiles?" + urllib.parse.urlencode(changed),
            400,
            "invalid_or_expired_cursor",
        )
        changed = dict(second, cursor=second["cursor"][:-5] + "xxxxx")
        problem(
            "/api/v1/profiles?" + urllib.parse.urlencode(changed),
            400,
            "invalid_or_expired_cursor",
        )
    problem(route + "&unknown=1", 400, "unknown_or_repeated_parameter")
    problem(route + "&limit=1", 400, "unknown_or_repeated_parameter")
    problem(route.replace("limit=1", "limit="), 400, "invalid_limit")
    problem(route + "&extra=%ZZ", 400, "invalid_query")
    problem(
        "/api/v1/profiles?" + urllib.parse.urlencode(dict(query, limit="201")),
        400,
        "invalid_limit",
    )
    problem(
        "/api/v1/profiles?"
        + urllib.parse.urlencode(dict(query, start="2026-01-01T00:00:00")),
        400,
        "invalid_start",
    )
    problem(raw_path + "&unknown=1", 400, "revision_required")
    problem(
        "/api/v1/profiles?" + urllib.parse.urlencode(dict(query, bbox="100,0,45,30")),
        400,
        "invalid_bbox",
    )
    problem(
        "/api/v1/profiles?"
        + urllib.parse.urlencode(dict(query, start="2020-01-01T00:00:00Z")),
        422,
        "time_range_budget",
    )
    problem("/api/v1/profiles/not-an-id", 404, "profile_not_found")
    empty = fetch(
        "/api/v1/profiles?"
        + urllib.parse.urlencode(dict(query, bbox="-40,-40,-39,-39"))
    )
    assert empty["items"] == [] and empty["next_cursor"] is None
    with urllib.request.urlopen(WEB + "/profiles", timeout=15) as response:
        html = response.read().decode()
        assert (
            "A view into the water column." in html and profile["platform_id"] in html
        )
        assert "Profile location map" in html
    with urllib.request.urlopen(
        WEB + "/profiles/" + profile["id"], timeout=15
    ) as response:
        html = response.read().decode()
        assert (
            "The observed profile." in html
            and profile["provenance"]["raw_sha256"] in html
        )
    with urllib.request.urlopen(
        WEB + raw_path.removeprefix("/api/v1"), timeout=15
    ) as response:
        assert (
            hashlib.sha256(response.read()).hexdigest()
            == profile["provenance"]["raw_sha256"]
        )
    (ROOT / "artifacts" / "phase2").mkdir(parents=True, exist_ok=True)
    evidence = {
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "profile_id": profile["id"],
        "platform_id": profile["platform_id"],
        "observed_at": profile["observed_at"],
        "raw_sha256": profile["provenance"]["raw_sha256"],
        "source_url": profile["provenance"]["source_url"],
        "accepted_levels": len(profile["levels"]),
        "checks": [
            "OpenAPI",
            "pagination snapshot",
            "filter-bound signed cursor",
            "invalid/empty queries",
            "raw SHA-256",
            "rendered profile evidence",
            "web raw download",
        ],
    }
    (ROOT / "artifacts" / "phase2" / "verification.json").write_text(
        json.dumps(evidence, indent=2) + "\n"
    )
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
