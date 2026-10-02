"""Live pinned model/registry, revision evidence and rendered-page contract gate."""

import hashlib
import json
import math
import os
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from jsonschema import Draft202012Validator

from verify_phase2 import ROOT, WEB, fetch, problem


def main():
    spec = json.loads(
        (ROOT / "packages/schemas/expected-state.openapi.json").read_text()
    )

    def validate(value, name):
        validator = Draft202012Validator(
            {"$ref": f"#/components/schemas/{name}", "components": spec["components"]},
            format_checker=Draft202012Validator.FORMAT_CHECKER,
        )
        errors = sorted(validator.iter_errors(value), key=lambda e: str(e.path))
        assert not errors, f"{name}: {[(list(e.path), e.validator) for e in errors]}"

    selected = fetch("/api/v1/expected-state-releases/selected")
    validate(selected, "SelectedModel")
    rid = selected["release_id"]
    model = fetch(f"/api/v1/expected-state-releases/{rid}")
    validate(model, "Model")
    assert model["selected"] and model["release_approved"] is False
    assert selected["fitting_period"] == {"start_year": 2005, "end_year": 2016}
    assert (
        selected["reference_id"]
        == fetch("/api/v1/climatology-releases/selected")["release_id"]
    )
    report = model["report"]
    policy = report["policy"]
    assert policy["promotion"]["untouched_test"] is False
    assert not policy["promotion"]["reviewed_gate_id"]
    assert report["feature_schema"]["names"] == [
        "latitude",
        "longitude",
        "depth_m",
        "season_sin",
        "season_cos",
        "season_sin2",
        "season_cos2",
        "basin_id",
    ]
    for variable in report["variables"].values():
        assert variable["promotion"]["active_method"] == "climatology"
        assert not variable["promotion"]["eligible"]
        assert "test_block_previously_inspected" in variable["promotion"]["reasons"]
        for partition in variable["evaluation"].values():
            assert set(partition) == {"climatology", "lightgbm", "hgbr"}
            for groups in partition.values():
                assert len([k for k in groups if k.startswith("depth:")]) == 15
                assert len([k for k in groups if k.startswith("season:")]) == 4
                assert len([k for k in groups if k.startswith("region:")]) == 2
                assert len([k for k in groups if k.startswith("depth_band:")]) == 3
    for audit in report["independence_audits"]:
        for variable in audit["variables"].values():
            if variable["status"] == "trained":
                assert set(variable["held_comparison"]) == {
                    "climatology",
                    "lightgbm",
                    "hgbr",
                }
    calc = fetch("/api/v1/calculations/" + model["calculation_id"])
    assert calc["kind"] == "expected_state_fit" and calc["state"] == "frozen"
    assert calc["manifest"] == model["manifest"]
    inventory = fetch("/api/v1/expected-state-releases?limit=200")
    validate(inventory, "ModelPage")
    assert any(v["release_id"] == rid and v["selected"] for v in inventory["items"])
    for _ in range(15):
        caps = fetch("/api/v1/capabilities")["capabilities"]
        if caps["expected_state"]:
            break
        time.sleep(1)
    assert caps["expected_state"] and caps["climatology"] and caps["observations"]
    assert all(
        not caps[k]
        for k in (
            "ml_residual",
            "profile_anomaly",
            "field_sampling",
            "official_advisories",
            "trip_assessment",
        )
    )
    tracking = model["tracking"]
    assert tracking and tracking["registered_model"] == "nautiq-expected-mean"
    tracking_root = "http://127.0.0.1:" + os.environ.get("MLFLOW_PORT", "5001")

    def tracked(path):
        with urllib.request.urlopen(tracking_root + path, timeout=15) as response:
            return json.load(response)

    run = tracked(
        "/api/2.0/mlflow/runs/get?" + urlencode({"run_id": tracking["run_id"]})
    )["run"]
    assert run["info"]["status"] == "FINISHED"
    tags = {t["key"]: t["value"] for t in run["data"]["tags"]}
    assert tags["release_id"] == rid
    sha = model["manifest"]["output"]["bundle_sha256"]
    assert tags["bundle_sha256"] == sha
    version = tracked(
        "/api/2.0/mlflow/model-versions/get?"
        + urlencode(
            {"name": tracking["registered_model"], "version": tracking["model_version"]}
        )
    )["model_version"]
    assert version["run_id"] == tracking["run_id"]
    artifact = tracked(
        "/api/2.0/mlflow/artifacts/list?"
        + urlencode({"run_id": tracking["run_id"], "path": "release"})
    )
    assert any(f["path"] == "release/bundle.json" for f in artifact["files"])
    uri = run["info"]["artifact_uri"]
    assert uri.startswith("mlflow-artifacts:/")
    with urllib.request.urlopen(
        tracking_root
        + "/api/2.0/mlflow-artifacts/artifacts/"
        + uri.removeprefix("mlflow-artifacts:/").lstrip("/")
        + "/release/bundle.json",
        timeout=15,
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
        comparison = fetch(f"/api/v1/profiles/{item['id']}/expected-state")
        validate(comparison, "ProfileModel")
        if comparison["result"] and comparison["result"]["supported_pairs"]:
            supported = comparison
            break
    assert supported, "No supported recent pinned-model comparison available"
    pid = supported["profile_id"]
    profile = fetch(f"/api/v1/profiles/{pid}")
    assert supported["revision_sha256"] == profile["revision_sha256"]
    comparison_calc = fetch("/api/v1/calculations/" + supported["calculation_id"])
    assert (
        comparison_calc["kind"] == "expected_state_comparison"
        and comparison_calc["state"] == "current"
    )
    assert comparison_calc["manifest"]["policy"]["release_id"] == rid
    assert comparison_calc["manifest"]["policy"]["bundle_sha256"] == sha
    assert (
        comparison_calc["manifest"]["inputs"][0]["revision_sha256"]
        == profile["revision_sha256"]
    )
    assert comparison_calc["manifest"]["output"] == supported["result"]
    baseline = fetch(f"/api/v1/profiles/{pid}/climatology")
    base_rows = {r["depth_m"]: r for r in baseline["result"]["rows"]}
    pairs = 0
    for row in supported["result"]["rows"]:
        for variable in ("temperature_c", "practical_salinity"):
            p = row[variable]
            assert p["active_method"] == (
                "climatology" if p["expected_mean"] is not None else "unavailable"
            )
            assert (
                p["expected_mean"]
                == base_rows[row["depth_m"]][variable]["expected_mean"]
            )
            if p["candidate_mean"] is not None:
                assert math.isclose(
                    p["candidate_mean"],
                    p["climatology_mean"] + p["candidate_residual"],
                    abs_tol=1e-10,
                )
                assert len(p["feature_contributions"]) == 8
                assert math.isclose(
                    sum(c["contribution"] for c in p["feature_contributions"])
                    + p["contribution_bias"],
                    p["candidate_residual"],
                    abs_tol=1e-8,
                )
            if p["difference"] is None:
                assert p["direction"] == "unavailable"
                continue
            pairs += 1
            assert math.isclose(
                p["difference"], p["observed"] - p["expected_mean"], abs_tol=1e-12
            )
            pos, neg = (
                ("warmer", "cooler")
                if variable == "temperature_c"
                else ("saltier", "fresher")
            )
            assert p["direction"] == (
                pos if p["difference"] > 0 else neg if p["difference"] < 0 else "equal"
            )
    assert pairs == supported["result"]["supported_pairs"]
    for path, needle in (
        ("/models", "The reference, and the model to beat it."),
        (f"/models/{rid}", "An expected mean, with its evidence."),
        (f"/profiles/{pid}", "Expected state and residual model"),
    ):
        with urllib.request.urlopen(WEB + path, timeout=25) as response:
            assert response.status == 200 and needle in response.read().decode(), path
    problem("/api/v1/expected-state-releases?limit=201", 400, "invalid_limit")
    problem(
        "/api/v1/expected-state-releases?limit=1&limit=2",
        400,
        "unknown_or_repeated_parameter",
    )
    problem(
        "/api/v1/expected-state-releases?future=true",
        400,
        "unknown_or_repeated_parameter",
    )
    problem("/api/v1/expected-state-releases/not-an-id", 404, "evidence_not_found")
    problem(
        "/api/v1/profiles/00000000-0000-0000-0000-000000000000/expected-state",
        404,
        "evidence_not_found",
    )
    print(
        f"Live residual model gate passed: exact release/registry checksums, grouped comparisons, fallback/SHAP arithmetic, current revision/calculation pins, bounded APIs and rendered pages; release={rid}, profile={pid}, pairs={pairs}"
    )


if __name__ == "__main__":
    main()
