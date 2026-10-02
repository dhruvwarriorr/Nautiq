"""Live reference, matching profile arithmetic, provenance and rendered-page gate."""

import json
import math
import urllib.request
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from jsonschema import Draft202012Validator

from verify_phase2 import ROOT, WEB, fetch, problem


def main():
    spec = json.loads((ROOT / "packages/schemas/climatology.openapi.json").read_text())

    def validate(value, name):
        Draft202012Validator(
            {"$ref": f"#/components/schemas/{name}", "components": spec["components"]},
            format_checker=Draft202012Validator.FORMAT_CHECKER,
        ).validate(value)

    selected = fetch("/api/v1/climatology-releases/selected")
    validate(selected, "SelectedReference")
    rid = selected["release_id"]
    reference = fetch(f"/api/v1/climatology-releases/{rid}")
    validate(reference, "Reference")
    assert reference["selected"] and reference["release_approved"] is False
    assert selected["fitting_period"] == {"start_year": 2005, "end_year": 2016}
    assert reference["manifest"]["output"]["dataset_baseline"] == {
        "start_year": 2005,
        "end_year": 2024,
    }
    assert reference["evaluation"]["spread_is_calibrated"] is False
    for variable in reference["evaluation"]["variables"].values():
        assert set(variable) == {"train", "tune", "calibration", "test"}
        for split in variable.values():
            assert set(split["regions"]) == {"arabian", "bay_bengal"}
            assert len(split["depths"]) == 15
    calc = fetch("/api/v1/calculations/" + reference["calculation_id"])
    assert calc["kind"] == "climatology_fit" and calc["state"] == "frozen"
    assert calc["manifest"] == reference["manifest"]
    page = fetch("/api/v1/climatology-releases?limit=200")
    validate(page, "ReferencePage")
    assert any(v["release_id"] == rid and v["selected"] for v in page["items"])
    caps = fetch("/api/v1/capabilities")["capabilities"]
    assert caps["climatology"] is True
    assert all(
        caps[k] is False
        for k in (
            "expected_state",
            "profile_anomaly",
            "field_sampling",
            "official_advisories",
            "trip_assessment",
        )
    )
    end = datetime.now(timezone.utc) + timedelta(minutes=1)
    profiles = fetch(
        "/api/v1/profiles?"
        + urlencode(
            {
                "bbox": "45,0,100,30",
                "start": (end - timedelta(days=366)).isoformat(),
                "end": end.isoformat(),
                "limit": 200,
            }
        )
    )
    supported = None
    for item in profiles["items"]:
        comparison = fetch(f"/api/v1/profiles/{item['id']}/climatology")
        validate(comparison, "ProfileComparison")
        assert comparison["release_id"] == rid
        if comparison["result"] and comparison["result"]["supported_pairs"]:
            supported = comparison
            break
    assert supported, "No supported recent profile comparison available"
    pid = supported["profile_id"]
    profile = fetch(f"/api/v1/profiles/{pid}")
    assert supported["revision_sha256"] == profile["revision_sha256"]
    comparison_calc = fetch("/api/v1/calculations/" + supported["calculation_id"])
    assert (
        comparison_calc["kind"] == "climatology_comparison"
        and comparison_calc["state"] == "current"
    )
    assert (
        comparison_calc["manifest"]["policy"]["reference_calculation_id"]
        == reference["calculation_id"]
    )
    assert (
        comparison_calc["manifest"]["inputs"][0]["revision_sha256"]
        == profile["revision_sha256"]
    )
    assert comparison_calc["manifest"]["output"] == supported["result"]
    pairs = 0
    for row in supported["result"]["rows"]:
        for variable in ("temperature_c", "practical_salinity"):
            point = row[variable]
            if point["difference"] is None:
                assert point["direction"] == "unavailable"
                continue
            pairs += 1
            assert math.isclose(
                point["difference"],
                point["observed"] - point["expected_mean"],
                abs_tol=1e-12,
            )
            pos, neg = (
                ("warmer", "cooler")
                if variable == "temperature_c"
                else ("saltier", "fresher")
            )
            assert point["direction"] == (
                pos
                if point["difference"] > 0
                else neg
                if point["difference"] < 0
                else "equal"
            )
            assert (
                point["spread"] > 0
                and point["training_profiles"] >= 12
                and point["training_platforms"] >= 3
            )
    assert pairs == supported["result"]["supported_pairs"]
    for path, needle in (
        ("/climatology", "Normal, with its evidence."),
        (f"/climatology/{rid}", "Held-out performance"),
        (f"/profiles/{pid}", "Observed, expected, difference"),
    ):
        with urllib.request.urlopen(WEB + path, timeout=20) as response:
            assert response.status == 200
            assert needle in response.read().decode(), path
    problem("/api/v1/climatology-releases?limit=201", 400, "invalid_limit")
    problem(
        "/api/v1/climatology-releases?future=true", 400, "unknown_or_repeated_parameter"
    )
    problem("/api/v1/climatology-releases/not-an-id", 404, "evidence_not_found")
    problem(
        "/api/v1/profiles/00000000-0000-0000-0000-000000000000/climatology",
        404,
        "evidence_not_found",
    )
    print(
        f"Live climatology gate passed: selected immutable reference, partition/depth evaluation, matching revision arithmetic, signed directions, independent capability flags, bounds and rendered pages; profile={pid}, release={rid}, supported_pairs={pairs}"
    )


if __name__ == "__main__":
    main()
