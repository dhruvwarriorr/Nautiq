"""Idempotent MLflow diagnostic registry; serving uses explicit content pins."""

import os
import sys
from contextlib import redirect_stdout
import tempfile
from pathlib import Path

from psycopg.types.json import Jsonb

from ..argo.evidence import canonical
from ..climatology.pipeline import connect
from .model import benchmark_latency


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
            "SELECT * FROM anomaly_tracking WHERE release_id=%s", (rid,)
        ).fetchone()
    if existing:
        if client.get_run(existing["run_id"]).info.status != "FINISHED":
            raise ValueError("anomaly_tracking_not_finished")
        return {k: existing[k] for k in ("run_id", "registered_model", "model_version")}
    name = "Nautiq profile anomaly diagnostics"
    experiment = client.get_experiment_by_name(name)
    eid = (
        experiment.experiment_id
        if experiment
        else client.create_experiment(
            name, artifact_location=os.environ.get("MLFLOW_ARTIFACT_ROOT")
        )
    )
    runs = client.search_runs(
        [eid], filter_string=f"tags.release_id = '{rid}'", max_results=5
    )
    complete = next((r for r in runs if r.info.status == "FINISHED"), None)
    run_id = (
        complete.info.run_id
        if complete
        else client.create_run(
            eid,
            tags={
                "release_id": rid,
                "bundle_sha256": release["bundle_sha256"],
                "scope": "diagnostic prototype; scientific approval false",
            },
        ).info.run_id
    )
    performance = benchmark_latency(bundle)
    if not complete:
        try:
            for key in (
                "uncertainty_id",
                "expected_id",
                "reference_id",
                "snapshot_id",
                "code_sha256",
                "method_version",
                "coverage_policy",
                "scale_estimator",
            ):
                client.log_param(run_id, key, bundle[key])
            for v, info in bundle["variables"].items():
                client.set_tag(run_id, v + ".status", info["status"])
                for split, n in info["complete_profiles"].items():
                    client.log_metric(run_id, f"{v}.{split}.complete_profiles", n)
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder)
                (path / "bundle.json").write_bytes(canonical(bundle))
                (path / "release-manifest.json").write_bytes(
                    canonical(release["manifest"])
                )
                (path / "latency.json").write_bytes(canonical(performance))
                client.log_artifacts(run_id, folder, "release")
            client.set_terminated(run_id, "FINISHED")
        except Exception:
            client.set_terminated(run_id, "FAILED")
            raise
    registered = "nautiq-profile-anomaly"
    try:
        client.create_registered_model(registered)
    except MlflowException:
        client.get_registered_model(registered)
    versions = client.search_model_versions(f"name='{registered}'", max_results=1000)
    version = next((v for v in versions if v.run_id == run_id), None)
    if version is None:
        version = client.create_model_version(
            registered,
            f"runs:/{run_id}/release/bundle.json",
            run_id=run_id,
            tags={
                "release_id": rid,
                "bundle_sha256": release["bundle_sha256"],
                "format": "hash-verified JSON arrays and tree nodes; no executable pickle",
            },
        )
    result = {
        "run_id": run_id,
        "registered_model": registered,
        "model_version": str(version.version),
    }
    with connect() as db:
        db.execute(
            "INSERT INTO anomaly_tracking(release_id,run_id,registered_model,model_version,performance) VALUES(%s,%s,%s,%s,%s) ON CONFLICT(release_id) DO NOTHING",
            (rid, *result.values(), Jsonb(performance)),
        )
    return result
