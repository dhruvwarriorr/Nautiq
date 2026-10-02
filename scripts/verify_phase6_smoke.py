"""Live uncertainty contracts, exact registry pins, scientific limits and rendered UI."""

import hashlib
import json
import math
import os
import urllib.request
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from jsonschema import Draft202012Validator
from verify_phase2 import ROOT, WEB, fetch, problem


def main():
    spec = json.loads((ROOT / "packages/schemas/uncertainty.openapi.json").read_text())

    def validate(value, name):
        validator = Draft202012Validator(
            {"$ref": f"#/components/schemas/{name}", "components": spec["components"]},
            format_checker=Draft202012Validator.FORMAT_CHECKER,
        )
        errors = list(validator.iter_errors(value))
        assert not errors, (name, [(list(e.path), e.validator) for e in errors])

    selected = fetch("/api/v1/uncertainty-releases/selected")
    validate(selected, "IntervalSelection")
    rid = selected["release_id"]
    release = fetch(f"/api/v1/uncertainty-releases/{rid}")
    validate(release, "IntervalRelease")
    assert release["selected"] and not release["release_approved"]
    assert (
        release["expected_id"]
        == fetch("/api/v1/expected-state-releases/selected")["release_id"]
    )
    assert (
        release["reference_id"]
        == fetch("/api/v1/climatology-releases/selected")["release_id"]
    )
    inventory = fetch("/api/v1/uncertainty-releases?limit=200")
    validate(inventory, "IntervalPage")
    assert any(x["release_id"] == rid and x["selected"] for x in inventory["items"])
    report = release["report"]
    assert report["coverage_unit"] == "stable_profile_maximum_within_group"
    assert report["nominal_coverage"] == 0.8
    assert report["policy"]["hierarchy"] == [
        "region_depth",
        "region",
        "depth",
        "global",
    ]
    assert not report["policy"]["coverage_gate"]["untouched_test"]
    for v in report["variables"].values():
        assert v["status"] == "trained" and not v["coverage_gate"]["qualified"]
        assert set(v["families"]) == {"lightgbm", "catboost"}
        for family in v["families"].values():
            assert set(family["evaluation"]) == {"train", "tune", "calibration", "test"}
            assert (
                len(
                    [
                        g
                        for g in family["evaluation"]["test"]
                        if g.startswith("region_depth:")
                    ]
                )
                == 6
            )
            for group in family["calibration"]["groups"].values():
                assert group["rank"] == math.ceil((group["profiles"] + 1) * 0.8)
                if group["correction"] is not None:
                    assert (
                        group["profiles"] >= 20
                        and group["rank"] <= group["profiles"]
                        and group["correction"] >= 0
                    )
    fit = fetch("/api/v1/calculations/" + release["calculation_id"])
    assert (
        fit["kind"] == "uncertainty_fit"
        and fit["state"] == "frozen"
        and fit["manifest"] == release["manifest"]
    )
    caps = fetch("/api/v1/capabilities")["capabilities"]
    assert (
        caps["predictive_intervals"] and caps["expected_state"] and caps["climatology"]
    )
    assert not any(
        caps[k]
        for k in (
            "calibrated_uncertainty",
            "profile_anomaly",
            "field_sampling",
            "official_advisories",
            "trip_assessment",
        )
    )
    coverage = fetch(f"/api/v1/uncertainty-releases/{rid}/coverage")
    validate(coverage, "IntervalCoverage")
    assert coverage["status"] == "monitored" and not coverage["calibration_updated"]
    assert coverage["report"] and not coverage["report"]["calibration_updated"]
    health_calc = fetch("/api/v1/calculations/" + coverage["calculation_id"])
    assert (
        health_calc["kind"] == "uncertainty_monitor"
        and health_calc["state"] == "current"
    )
    tracking = release["tracking"]
    assert tracking and tracking["registered_model"] == "nautiq-predictive-intervals"
    root = "http://127.0.0.1:" + os.environ.get("MLFLOW_PORT", "5001")

    def tracked(path):
        with urllib.request.urlopen(root + path, timeout=15) as response:
            return json.load(response)

    run = tracked(
        "/api/2.0/mlflow/runs/get?" + urlencode({"run_id": tracking["run_id"]})
    )["run"]
    assert run["info"]["status"] == "FINISHED"
    tags = {t["key"]: t["value"] for t in run["data"]["tags"]}
    sha = release["manifest"]["output"]["bundle_sha256"]
    assert tags["bundle_sha256"] == sha and tags["release_id"] == rid
    version = tracked(
        "/api/2.0/mlflow/model-versions/get?"
        + urlencode(
            {"name": tracking["registered_model"], "version": tracking["model_version"]}
        )
    )["model_version"]
    assert version["run_id"] == tracking["run_id"]
    uri = run["info"]["artifact_uri"]
    assert uri.startswith("mlflow-artifacts:/")
    with urllib.request.urlopen(
        root
        + "/api/2.0/mlflow-artifacts/artifacts/"
        + uri.removeprefix("mlflow-artifacts:/").lstrip("/")
        + "/release/bundle.json",
        timeout=20,
    ) as response:
        assert hashlib.sha256(response.read()).hexdigest() == sha
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
        comparison = fetch(f"/api/v1/profiles/{item['id']}/uncertainty")
        validate(comparison, "IntervalProfile")
        if comparison["result"] and comparison["result"]["supported_intervals"]:
            supported = comparison
            break
    assert supported, "No supported current interval comparison"
    pid = supported["profile_id"]
    profile = fetch("/api/v1/profiles/" + pid)
    assert supported["revision_sha256"] == profile["revision_sha256"]
    assert (
        supported["release_id"] == rid
        and supported["expected_id"] == release["expected_id"]
    )
    calc = fetch("/api/v1/calculations/" + supported["calculation_id"])
    assert calc["kind"] == "uncertainty_comparison" and calc["state"] == "current"
    assert calc["manifest"]["policy"]["bundle_sha256"] == sha
    assert (
        calc["manifest"]["inputs"][0]["revision_sha256"] == profile["revision_sha256"]
    )
    assert calc["manifest"]["output"] == supported["result"]
    mean = fetch("/api/v1/profiles/" + pid + "/expected-state")
    means = {r["depth_m"]: r for r in mean["result"]["rows"]}
    count = 0
    for row in supported["result"]["rows"]:
        for variable in ("temperature_c", "practical_salinity"):
            p = row[variable]
            assert (
                p["expected_mean"] == means[row["depth_m"]][variable]["expected_mean"]
            )
            assert not p["coverage_qualified"]
            if p["lower"] is None:
                assert (
                    p["upper"] is None and p["width"] is None and p["covered"] is None
                )
                continue
            count += 1
            assert p["lower"] <= p["q10"] <= p["q50"] <= p["q90"] <= p["upper"]
            assert math.isclose(p["lower"], p["q10"] - p["correction"], abs_tol=1e-10)
            assert math.isclose(p["upper"], p["q90"] + p["correction"], abs_tol=1e-10)
            assert math.isclose(p["width"], p["upper"] - p["lower"], abs_tol=1e-10)
            assert (
                p["calibration_profiles"] >= 20
                and p["calibration_rank"] <= p["calibration_profiles"]
            )
            assert (
                p["covered"] is None
                if p["observed"] is None
                else p["covered"] == (p["lower"] <= p["observed"] <= p["upper"])
            )
    assert count == supported["result"]["supported_intervals"]
    for path, required in (
        ("/uncertainty", ("Nautiq", "coverage evidence", rid)),
        ("/uncertainty/" + rid, ("calibration", "CatBoost", "coverage", sha)),
        (
            "/profiles/" + pid,
            (
                "Predictive intervals",
                "Median q50",
                "CQR lower",
                supported["calculation_id"],
            ),
        ),
    ):
        with urllib.request.urlopen(WEB + path, timeout=20) as response:
            html = response.read().decode()
        assert all(s in html for s in required), (path, required)
        assert "<title>Nautiq" in html
    problem("/api/v1/uncertainty-releases?limit=201", 400, "invalid_limit")
    problem("/api/v1/uncertainty-releases/not-a-uuid", 404, "evidence_not_found")
    print(
        "Live interval gate passed: contracts, both family benchmarks, profile/rank calibration, exact parents and registry hash, current revision calculations, CQR arithmetic, nullable support, coverage monitoring, truthful capabilities and rendered Nautiq pages."
    )


if __name__ == "__main__":
    main()
