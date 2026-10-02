"""Real-source API contracts. Empty or unverified feed never becomes an all-clear."""

import json
from datetime import datetime, timedelta, timezone
from urllib.request import urlopen
from urllib.error import HTTPError
from urllib.parse import urlencode


def get(path, expected=200):
    try:
        with urlopen("http://localhost:8080/api/v1" + path, timeout=12) as r:
            assert r.status == expected
            return json.load(r)
    except HTTPError as e:
        assert e.code == expected, (path, e.code)
        return json.load(e)


def main():
    catalog = get("/advisories")
    assert catalog["production_approved"] is False
    assert {s["source_id"] for s in catalog["sources"]} == {
        "ndma_cap_rss",
        "incois_advisories",
    }
    assert any(s["coverage"] != "verified_complete" for s in catalog["sources"])
    if catalog["items"]:
        first = catalog["items"][0]
        detail = get("/advisories/" + first["message"]["revision_id"])
        assert detail["bulletin"] == first
    now = datetime.now(timezone.utc)
    params = {
        "longitude": "72",
        "latitude": "12",
        "start": now.isoformat(),
        "end": (now + timedelta(hours=6)).isoformat(),
    }
    state = get("/advisories/state?" + urlencode(params))
    assert (
        state["status"] in ("unknown", "official_warning") and state["unknown_reasons"]
    )
    get("/advisories?limit=1", 400)
    get("/advisories/state?longitude=NaN&latitude=12&start=x&end=x", 400)
    get("/advisories/state?" + urlencode({**params, "end": params["start"]}), 400)
    get("/advisories/state?" + urlencode(params) + "&longitude=72", 400)
    get("/advisories/not-an-id", 404)
    cap = get("/capabilities")["capabilities"]
    assert (
        cap["advisory_diagnostics"]
        and not cap["official_advisories"]
        and not cap["trip_assessment"]
    )
    for path in (
        "/advisories",
        ("/advisories/" + catalog["items"][0]["message"]["revision_id"])
        if catalog["items"]
        else "/advisories",
    ):
        with urlopen("http://localhost:3000" + path, timeout=20) as r:
            html = r.read().decode()
            assert (
                "Marine advisory coverage is unknown" in html
                or "EXACT REVISION" in html
            )
    print(
        f"Live official advisory contracts passed: {len(catalog['items'])} retained real bulletins, explicit unknown coverage, strict input bounds and rendered pages."
    )


if __name__ == "__main__":
    main()
