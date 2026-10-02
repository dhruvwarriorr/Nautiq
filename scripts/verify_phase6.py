"""Offline quantile reproducibility, profile CQR, leakage, fallback and monitoring gate."""

import copy
import json
from pathlib import Path

import numpy as np

from nautiq_ml.argo.evidence import canonical
from nautiq_ml.climatology.grid import standardize
from nautiq_ml.climatology.model import (
    fit as reference_fit,
    load_policy as reference_policy,
)
from nautiq_ml.expected_state.model import fit as mean_fit, load_policy as mean_policy
from nautiq_ml.uncertainty import calibration
from nautiq_ml.uncertainty.monitoring import summarize
from nautiq_ml.uncertainty.quantiles import fit, load_policy
from nautiq_ml.uncertainty.serving import infer
from verify_phase5 import fixture

ROOT = Path(__file__).resolve().parents[1]


def main():
    cp = reference_policy(ROOT / "packages/source-catalog/climatology.json")
    p = load_policy(ROOT / "packages/source-catalog/uncertainty.json")
    p = {**p, "max_rounds": 8, "min_calibration_profiles": 10}
    grid = standardize(fixture(cp), cp)
    for i, row in enumerate(grid):
        perturbation = np.sin(int(row["profile_id"].split("-")[1]) * 7) * (
            0.4 if row["depth_m"] < 100 else 0.1
        )
        row["temperature_c"] += perturbation
        row["practical_salinity"] += perturbation / 10
    ref = reference_fit(grid, cp)
    first = fit(grid, ref, p, audits=False)
    assert all(v["status"] == "trained" for v in first["variables"].values())
    assert canonical(first) == canonical(fit(grid, ref, p, audits=False)), (
        "Native quantile bundle is not reproducible"
    )
    changed = copy.deepcopy(grid)
    for row in changed:
        if row["split"] in ("test", "calibration"):
            row["temperature_c"] += 6
            row["practical_salinity"] += 1
    second = fit(changed, ref, p, audits=False)
    for v in first["models"]:
        assert first["variables"][v]["selected"] == second["variables"][v]["selected"]
        assert (
            first["variables"][v]["selected_family"]
            == second["variables"][v]["selected_family"]
        )
        for family in first["models"][v]:
            assert (
                first["models"][v][family]["model_texts"]
                == second["models"][v][family]["model_texts"]
            ), "Calibration/test labels changed quantile fitting"
    only_test = copy.deepcopy(grid)
    for row in only_test:
        if row["split"] == "test":
            row["temperature_c"] += 10
    altered = fit(only_test, ref, p, audits=False)
    assert canonical(first["models"]) == canonical(altered["models"]), (
        "Test changed calibration/model artifacts"
    )
    assert calibration.cutoff([1, 2, 3], 0.1, 1)["correction"] is None
    assert calibration.cutoff([1, 2, 3, 4], 0.2, 4)["correction"] == 4
    rows = [
        {
            "profile_id": str(i // 2),
            "latitude": 15,
            "longitude": 70,
            "depth_m": 10 + 10 * (i % 2),
            "split": "calibration",
        }
        for i in range(40)
    ]
    truth = np.zeros(40)
    q = np.array([[float(i % 2), 2, 3] for i in range(40)])
    cal = calibration.fit(rows, truth, q, cp, {**p, "min_calibration_profiles": 20})
    assert cal["groups"]["global"]["profiles"] == 20
    assert cal["groups"]["global"]["correction"] == 1
    selection = calibration.choose(
        {**rows[0], "longitude": 90, "depth_m": 1000}, cp, cal
    )
    assert selection["group"] == "global" and selection["fallback"]
    mp = {
        **mean_policy(ROOT / "packages/source-catalog/expected-state.json"),
        "max_rounds": 8,
        "bootstrap_replicates": 10,
    }
    parent = {**mean_fit(grid, ref, mp, audits=False), "climatology": ref}
    bundle = {**first, "climatology": ref, "expected_state": parent, "policy": p}
    points = [r for r in grid if r["split"] == "test"][:15]
    response = infer(points, bundle)
    assert not response["release_approved"] and response["nominal_coverage"] == 0.8
    supported = 0
    records = []
    for original, row in zip(points, response["rows"], strict=True):
        record = {**original}
        for v in ("temperature_c", "practical_salinity"):
            prediction = row[v]
            record[v] = {**prediction, "observed": original[v]}
            assert prediction["coverage_qualified"] is False
            if prediction["lower"] is not None:
                supported += 1
                assert (
                    prediction["lower"]
                    <= prediction["q10"]
                    <= prediction["q50"]
                    <= prediction["q90"]
                    <= prediction["upper"]
                )
                assert np.isclose(
                    prediction["lower"], prediction["q10"] - prediction["correction"]
                )
                assert np.isclose(
                    prediction["upper"], prediction["q90"] + prediction["correction"]
                )
        records.append(record)
    assert supported > 0
    frozen = canonical(bundle)
    monitor = summarize(records, "temperature_c", cp, p)
    records[0]["temperature_c"]["observed"] = 1000
    degraded = summarize(records, "temperature_c", cp, p)
    assert degraded["suspect_profiles_for_adaptation"] > 0
    assert degraded["profile_group_coverage"] <= monitor["profile_group_coverage"]
    assert canonical(bundle) == frozen, "Monitoring changed calibration"
    no_calibration = [r for r in grid if r["split"] != "calibration"]
    sparse = fit(no_calibration, ref, p, audits=False)
    unsupported = infer(
        points, {**sparse, "climatology": ref, "expected_state": parent, "policy": p}
    )
    assert all(r["temperature_c"]["lower"] is None for r in unsupported["rows"])
    for points_to_refuse in (
        [points[0]] * 33,
        [{**points[0], "latitude": float("nan")}],
        [{**points[0], "depth_m": -1}],
    ):
        try:
            infer(points_to_refuse, bundle)
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid uncertainty request accepted")
    for v in first["variables"].values():
        assert not v["coverage_gate"]["qualified"]
        assert set(v["families"]) == {"lightgbm", "catboost"}
        assert set(v["families"]["lightgbm"]["evaluation"]) == {
            "train",
            "tune",
            "calibration",
            "test",
        }
    json.loads(canonical(first))
    print(
        "Uncertainty offline gate passed: deterministic native quantiles, tuning/calibration/test separation, profile maximum scores and finite ranks, Mondrian fallback, monotone CQR bounds, unavailable support, independent mean/median, coverage refusal and immutable monitoring"
    )


if __name__ == "__main__":
    main()
