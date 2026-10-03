"""Actual retained-source notification worker acceptance; no external email sends."""

import json
import os
import time
import urllib.error
import urllib.request
import uuid

BASE = os.getenv("API_BASE_URL", "http://localhost:8080") + "/api/v1/"
ORIGIN = os.getenv("PRODUCT_WEB_ORIGIN", "http://localhost:3000")
token = csrf = ""


def call(method, path, body=None, version=None):
    headers = {"Origin": ORIGIN, "Idempotency-Key": str(uuid.uuid4())}
    if token:
        headers.update(Authorization="Bearer " + token, **{"X-CSRF-Token": csrf})
    if version is not None:
        headers["If-Match"] = '"' + str(version) + '"'
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise AssertionError(
            f"{method} {path.split('/')[0]} refused ({error.code}); details suppressed"
        ) from None


def main():
    global token, csrf
    password = "Synthetic-notification-fixture-" + uuid.uuid4().hex
    registered = False
    try:
        auth = call(
            "POST",
            "auth/register",
            {"handle": "verify13_" + uuid.uuid4().hex[:16], "password": password},
        )
        token, csrf = auth["session_token"], auth["csrf_token"]
        registered = True
        watch = call(
            "POST",
            "watchlists",
            {
                "name": "Retained source verification",
                "data": {
                    "type": "point",
                    "latitude": 12,
                    "longitude": 72,
                    "radius_km": 0,
                },
            },
        )
        rules = []
        for kind in ["source_stale", "field_threshold", "official_advisory"]:
            data = {
                "type": kind,
                "watchlist_id": watch["id"],
                "channel": "in_app",
                "enabled": True,
            }
            if kind == "field_threshold":
                data.update(variable="wave_height_m", units="m", limit=2)
            rules.append(call("POST", "alert-rules", {"name": kind, "data": data}))
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            status = call("GET", "notification-status")
            if (
                status["worker_available"]
                and len(status["items"]) == 3
                and all(r["last_evaluated_at"] for r in status["items"])
            ):
                break
            time.sleep(2)
        else:
            raise AssertionError(
                "Notification worker did not evaluate all three retained-source rules"
            )
        outcomes = {r["name"]: r["last_outcome"] for r in status["items"]}
        assert all(v in {"unknown", "triggered", "clear"} for v in outcomes.values())
        inbox = call("GET", "alerts")
        for item in inbox["items"]:
            assert call("POST", "alerts/" + item["alert_id"] + "/replay")["matched"]
            call("POST", "alerts/" + item["alert_id"] + "/acknowledge")
            for sha in item["evidence"]["observation"].get("field_evidence_sha256", []):
                evidence = call("GET", "notification-evidence/" + sha)
                assert evidence["release_approved"] is False
            assert all(d["channel"] == "in_app" for d in item["deliveries"])
        print(
            json.dumps(
                {
                    "worker_available": True,
                    "rules_evaluated": 3,
                    "retained_source_outcomes": outcomes,
                    "alerts": len(inbox["items"]),
                    "frozen_replay": True,
                    "external_email_sent": False,
                },
                sort_keys=True,
            )
        )
    finally:
        if registered:
            session = call("GET", "auth/session")
            call("DELETE", "account", {"password": password}, session["version"])
            print("Temporary notification account and its private evidence deleted.")


if __name__ == "__main__":
    main()
