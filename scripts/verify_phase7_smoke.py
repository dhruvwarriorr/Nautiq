"""Live profile-score contracts, immutable registry pins and rendered depth evidence."""

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
    spec = json.loads((ROOT / "packages/schemas/anomaly.openapi.json").read_text())

    def validate(value, name):
        validator = Draft202012Validator(
            {"$ref": f"#/components/schemas/{name}", "components": spec["components"]},
            format_checker=Draft202012Validator.FORMAT_CHECKER,
        )
        errors = list(validator.iter_errors(value))
        assert not errors, (name, [(list(e.path), e.validator) for e in errors])

    selected = fetch("/api/v1/anomaly-releases/selected")
    validate(selected, "AnomalySelection")
    rid = selected["release_id"]
    release = fetch(f"/api/v1/anomaly-releases/{rid}")
    validate(release, "AnomalyRelease")
    assert release["selected"] and not release["release_approved"]
    for parent, path in (
        ("uncertainty_id", "uncertainty"),
        ("expected_id", "expected-state"),
        ("reference_id", "climatology"),
    ):
        assert (
            release[parent] == fetch(f"/api/v1/{path}-releases/selected")["release_id"]
        )
    page = fetch("/api/v1/anomaly-releases?limit=200")
    validate(page, "AnomalyPage")
    assert any(r["release_id"] == rid for r in page["items"])
    report = release["report"]
    assert not any(report["policy"]["scientific_review"].values())
    assert math.isclose(sum(report["weights"]), 1)
    for info in report["variables"].values():
        assert not info["qualified"]
        if info["status"] == "diagnostic":
            assert (
                info["covariance_condition"]
                <= report["policy"]["max_covariance_condition"]
            )
            assert len(info["basis_loadings"]) == 3
            assert len(info["resampling_stability"]) == len(
                report["policy"]["stability_seeds"]
            )
    fit = fetch("/api/v1/calculations/" + release["calculation_id"])
    assert (
        fit["kind"] == "anomaly_fit"
        and fit["state"] == "frozen"
        and fit["manifest"] == release["manifest"]
    )
    tracking = release["tracking"]
    assert tracking and tracking["registered_model"] == "nautiq-profile-anomaly"
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
    )["items"]
    supported = 0
    example = None
    for profile in profiles[:50]:
        value = fetch(f"/api/v1/profiles/{profile['id']}/anomaly")
        validate(value, "AnomalyProfile")
        assert value["release_id"] == rid
        if value["calculation_id"] is None:
            continue
        calc = fetch("/api/v1/calculations/" + value["calculation_id"])
        assert calc["kind"] == "anomaly_comparison" and calc["state"] == "current"
        assert calc["manifest"]["output"] == value["result"]
        assert any(
            r["profile_id"] == profile["id"]
            and r["revision_sha256"] == value["revision_sha256"]
            for r in calc["manifest"]["inputs"]
        )
        for evidence in value["result"]["variables"].values():
            if not evidence["complete"]:
                assert (
                    evidence["score_evidence"] is None
                    and evidence["percentiles"] is None
                )
                continue
            scored = evidence["score_evidence"]
            if scored is None:
                continue
            supported += 1
            example = example or profile["id"]
            for key, total in (
                ("weighted_contribution", "weighted_squared_residual"),
                ("mahalanobis_contribution", "mahalanobis_squared"),
            ):
                assert math.isclose(
                    sum(x[key] for x in evidence["points"]),
                    scored["scores"][total],
                    rel_tol=1e-10,
                    abs_tol=1e-8,
                )
            for point in evidence["points"]:
                assert math.isclose(
                    point["residual"], point["observed"] - point["expected_mean"]
                )
                assert math.isclose(
                    point["standardized_residual"], point["residual"] / point["scale"]
                )
            for rank in evidence["percentiles"]["values"].values():
                assert rank is None or 0 <= rank <= 100
    assert supported > 0, "No supported current profiles were checked"
    caps = fetch("/api/v1/capabilities")["capabilities"]
    assert (
        caps["profile_anomaly_diagnostics"]
        and caps["expected_state"]
        and caps["predictive_intervals"]
    )
    assert not any(
        caps[k]
        for k in (
            "profile_anomaly",
            "calibrated_uncertainty",
            "official_advisories",
            "trip_assessment",
        )
    )
    for path, text in (
        ("/anomalies", "Magnitude and vertical structure."),
        (f"/anomalies/{rid}", "Vertical basis patterns"),
        (f"/profiles/{example}", "Profile magnitude and shape"),
    ):
        with urllib.request.urlopen(WEB + path, timeout=20) as response:
            html = response.read().decode()
            assert response.status == 200 and text in html and "Nautiq" in html
    for path, status, code in (
        ("/api/v1/anomaly-releases?limit=201", 400, "invalid_limit"),
        (
            "/api/v1/anomaly-releases?limit=1&limit=2",
            400,
            "unknown_or_repeated_parameter",
        ),
        ("/api/v1/anomaly-releases/not-a-uuid", 404, "evidence_not_found"),
        (
            f"/api/v1/anomaly-releases/{rid}?unknown=1",
            400,
            "unknown_or_repeated_parameter",
        ),
    ):
        problem(path, status, code)
    print(
        "Live profile scoring gate passed: API schemas, exact selected parents/registry hash, current revision evidence, nullable coverage, residual/score/contribution arithmetic, finite historical ranks, truthful capabilities and rendered Nautiq pages."
    )


if __name__ == "__main__":
    main()
