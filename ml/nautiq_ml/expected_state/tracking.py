"""Idempotent MLflow tracking; registry metadata never chooses a serving release."""

import json
import sys
from contextlib import redirect_stdout
import os
import tempfile
from pathlib import Path


from ..climatology.pipeline import connect
from ..argo.evidence import canonical


def log_release(release, bundle):
    with redirect_stdout(sys.stderr):
        return _log_release(release, bundle)


def _log_release(release, bundle):
    from mlflow import MlflowClient
    from mlflow.exceptions import MlflowException

    uri = os.environ.get("MLFLOW_TRACKING_URI")
    if not uri:
        raise ValueError("mlflow_tracking_uri_required")
    os.environ.setdefault("MLFLOW_HTTP_REQUEST_TIMEOUT", "15")
    os.environ.setdefault("MLFLOW_HTTP_REQUEST_MAX_RETRIES", "1")
    client = MlflowClient(tracking_uri=uri, registry_uri=uri)
    rid = str(release["release_id"])
    with connect() as db:
        existing = db.execute(
            "SELECT * FROM expected_state_tracking WHERE release_id=%s", (rid,)
        ).fetchone()
    if existing:
        assert client.get_run(existing["run_id"]).info.status == "FINISHED"
        return {k: existing[k] for k in ("run_id", "registered_model", "model_version")}
    name = "Nautiq residual references"
    experiment = client.get_experiment_by_name(name)
    experiment_id = (
        experiment.experiment_id
        if experiment
        else client.create_experiment(
            name, artifact_location=os.environ.get("MLFLOW_ARTIFACT_ROOT")
        )
    )
    runs = client.search_runs(
        [experiment_id], filter_string=f"tags.release_id = '{rid}'", max_results=5
    )
    completed = next((r for r in runs if r.info.status == "FINISHED"), None)
    run_id = (
        completed.info.run_id
        if completed
        else client.create_run(
            experiment_id,
            tags={
                "release_id": rid,
                "bundle_sha256": release["bundle_sha256"],
                "scope": "local prototype; scientific production approval false",
            },
        ).info.run_id
    )
    if not completed:
        try:
            for key, value in {
                "feature_version": bundle["feature_schema"]["version"],
                "climatology_id": bundle["reference_id"],
                "snapshot_id": bundle["snapshot_id"],
                "code_sha256": bundle["code_sha256"],
                "policy": bundle["policy"],
                "environment": bundle["environment"],
                "estimand": "conditional_mean",
            }.items():
                client.log_param(
                    run_id,
                    key,
                    json.dumps(value, sort_keys=True)
                    if isinstance(value, dict)
                    else value,
                )
            for variable, result in bundle["variables"].items():
                if result["status"] != "trained":
                    continue
                for family, config in result["selected"].items():
                    client.log_param(
                        run_id,
                        f"{variable}.{family}.parameters",
                        json.dumps(config["parameters"], sort_keys=True),
                    )
                    client.log_metric(
                        run_id,
                        f"{variable}.{family}.tune_profile_mae",
                        config["tuning_profile_weighted_mae"],
                    )
                for split, groups in result["evaluation"].items():
                    for family, metrics in groups.items():
                        for key, value in metrics["overall"].items():
                            if isinstance(value, (int, float)):
                                client.log_metric(
                                    run_id, f"{variable}.{family}.{split}.{key}", value
                                )
                client.set_tag(
                    run_id,
                    f"{variable}.promotion_reasons",
                    json.dumps(result["promotion"]["reasons"]),
                )
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory)
                (path / "bundle.json").write_bytes(canonical(bundle))
                (path / "release-manifest.json").write_bytes(
                    canonical(release["manifest"])
                )
                for variable, model in bundle["models"].items():
                    (path / (variable + ".lightgbm.txt")).write_text(
                        model["model_text"]
                    )
                client.log_artifacts(run_id, directory, "release")
            client.set_terminated(run_id, "FINISHED")
        except Exception:
            client.set_terminated(run_id, "FAILED")
            raise
    registered = "nautiq-expected-mean"
    try:
        client.create_registered_model(registered)
    except MlflowException:
        client.get_registered_model(registered)
    versions = client.search_model_versions(f"name='{registered}'", max_results=1000)
    version = next((v for v in versions if v.run_id == run_id), None)
    if not version:
        version = client.create_model_version(
            registered,
            f"runs:/{run_id}/release/bundle.json",
            run_id=run_id,
            tags={
                "release_id": rid,
                "bundle_sha256": release["bundle_sha256"],
                "format": "hash-verified native LightGBM JSON bundle; no executable pickle",
            },
        )
    result = {
        "run_id": run_id,
        "registered_model": registered,
        "model_version": str(version.version),
    }
    with connect() as db:
        db.execute(
            "INSERT INTO expected_state_tracking(release_id,run_id,registered_model,model_version) VALUES(%s,%s,%s,%s) ON CONFLICT(release_id) DO NOTHING",
            (rid, *result.values()),
        )
    return result
