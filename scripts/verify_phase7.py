"""Deterministic residual/FPCA fitting, held-out separation and depth explanations."""

import copy
import math
from pathlib import Path

import numpy as np

from nautiq_ml.argo.evidence import canonical
from nautiq_ml.climatology.grid import standardize
from nautiq_ml.climatology.model import (
    fit as reference_fit,
    load_policy as reference_policy,
)
from nautiq_ml.expected_state.model import fit as mean_fit, load_policy as mean_policy
from nautiq_ml.uncertainty.quantiles import (
    fit as interval_fit,
    load_policy as interval_policy,
)
from nautiq_ml.anomaly.model import fit, infer, load_policy, weights
from nautiq_ml.anomaly import METHOD
from nautiq_ml.anomaly.jobs import decode
from nautiq_ml.gen.nautiq.platform.v1 import platform_pb2 as pb

ROOT = Path(__file__).resolve().parents[1]


def fixture(cp):
    from verify_phase5 import fixture as original

    rows = original(cp)
    for i in range(16):
        for split in ("calibration", "test"):
            source = [
                r
                for r in rows
                if r["profile_id"]
                == f"synthetic-{64 + i if split == 'calibration' else 80 + i:03}"
            ]
            rows.extend({**r, "profile_id": r["profile_id"] + "-extra"} for r in source)
    for r in rows:
        # Independent depth modes give a full-rank covariance, unlike a single offset fixture.
        index = int(r["profile_id"].split("-")[1]) + (
            100 if "extra" in r["profile_id"] else 0
        )
        z = r["depth_m"]
        perturb = (
            sum(
                math.sin(index * (k + 1) * 1.73) * math.cos(z / (20 + 50 * k))
                for k in range(5)
            )
            * 0.15
        )
        r["temperature_c"] += perturb
        r["practical_salinity"] += perturb * 0.1
    return rows


def bundles():
    cp = reference_policy(ROOT / "packages/source-catalog/climatology.json")
    grid = standardize(fixture(cp), cp)
    ref = reference_fit(grid, cp)
    mp = {
        **mean_policy(ROOT / "packages/source-catalog/expected-state.json"),
        "max_rounds": 8,
        "bootstrap_replicates": 10,
    }
    mean = {**mean_fit(grid, ref, mp, audits=False), "climatology": ref}
    ip = {
        **interval_policy(ROOT / "packages/source-catalog/uncertainty.json"),
        "max_rounds": 8,
    }
    parent = {
        **interval_fit(grid, ref, ip, audits=False),
        "climatology": ref,
        "expected_state": mean,
        "policy": ip,
    }
    return grid, parent, load_policy(ROOT / "packages/source-catalog/anomaly.json")


def main():
    grid, parent, p = bundles()
    first = fit(grid, parent, p)
    assert set(first["models"]) == {"temperature_c", "practical_salinity"}
    assert canonical(first) == canonical(fit(grid, parent, p))
    assert np.isclose(sum(weights(p["depths_m"])), 1)
    changed = copy.deepcopy(grid)
    for r in changed:
        if r["split"] == "test":
            r["temperature_c"] += 1
    second = fit(changed, parent, p)
    assert canonical(first["models"]) == canonical(second["models"]), (
        "Test labels affected fitted basis/reference ranks"
    )
    for r in changed:
        if r["split"] == "calibration":
            r["temperature_c"] += 1
    third = fit(changed, parent, p)
    for v in first["models"]:
        assert {
            k: a for k, a in first["models"][v].items() if k != "percentile_reference"
        } == {
            k: a for k, a in third["models"][v].items() if k != "percentile_reference"
        }, "Calibration labels fitted covariance/basis/forest"
    points = [
        r
        for r in grid
        if r["profile_id"] == "synthetic-080" and r["depth_m"] in p["depths_m"]
    ]
    bundle = {**first, "policy": p, "uncertainty": parent}
    result = infer(points, bundle)
    assert result["supported_variables"] == 2 and not result["release_approved"]
    reply = pb.AnomalyResponse(method_version=METHOD, result_json=canonical(result))
    assert decode(reply, points) == result
    for change in (
        "missing_field",
        "wrong_component_count",
        "nonfinite",
        "unsupported_rank",
    ):
        malformed = copy.deepcopy(result)
        variable = malformed["variables"]["temperature_c"]
        if change == "missing_field":
            del variable["points"][0]["observed"]
        elif change == "wrong_component_count":
            variable["score_evidence"]["component_scores"] = [1, 2]
        elif change == "nonfinite":
            # Standard JSON's permissive decoder must still refuse nonfinite values.
            import json

            variable["points"][0]["scale"] = float("nan")
            reply.result_json = json.dumps(malformed).encode()
        else:
            variable["percentiles"]["profiles"] = 1
        if change != "nonfinite":
            reply.result_json = canonical(malformed)
        try:
            decode(reply, points)
        except ValueError:
            pass
        else:
            raise AssertionError("Malformed scientific RPC result accepted")
    for v, info in result["variables"].items():
        scores = info["score_evidence"]["scores"]
        assert np.isclose(
            sum(x["weighted_contribution"] for x in info["points"]),
            scores["weighted_squared_residual"],
        )
        assert np.isclose(
            sum(x["mahalanobis_contribution"] for x in info["points"]),
            scores["mahalanobis_squared"],
        )
        assert info["percentiles"]["profiles"] >= 20
        assert not info["qualified"]
        components = np.array(first["models"][v]["components"])
        assert np.allclose(components @ components.T, np.eye(3))
        assert all(c[np.argmax(np.abs(c))] >= 0 for c in components)
    sparse = copy.deepcopy(points)
    sparse[0]["temperature_c"] = None
    output = infer(sparse, bundle)
    assert output["variables"]["temperature_c"]["score_evidence"] is None
    assert output["variables"]["practical_salinity"]["score_evidence"] is not None
    assert (
        output["variables"]["temperature_c"]["points"][0]["standardized_residual"]
        is None
    )
    frozen = canonical(bundle)
    no_calibration = [r for r in grid if r["split"] != "calibration"]
    unranked = infer(
        points, {**fit(no_calibration, parent, p), "policy": p, "uncertainty": parent}
    )
    assert all(x["status"] == "scores_only" for x in unranked["variables"].values())
    for invalid in (
        points[:-1],
        points[::-1],
        [{**r, "latitude": float("nan")} for r in points],
        [{**r, "temperature_c": 50} for r in points],
    ):
        try:
            infer(invalid, bundle)
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid profile accepted")
    leakage = copy.deepcopy(grid)
    leakage[0]["split"] = "test"
    try:
        fit(leakage, parent, p)
    except ValueError:
        pass
    else:
        raise AssertionError("Split leakage accepted")
    assert canonical(bundle) == frozen
    print(
        "Profile anomaly offline gate passed: deterministic train-only shrinkage/PCA/forest, held-out percentile reference, safe tree parity, depth contribution sums, missing-variable refusal, fixed-grid budgets, sparse reference ranks and split-leakage refusal."
    )


if __name__ == "__main__":
    main()
