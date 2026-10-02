"""Offline residual-model leakage, feature/audit, fallback and native round-trip gate."""

import copy
import math
from pathlib import Path

import lightgbm as lgb
import numpy as np

from nautiuq_ml.argo.evidence import canonical
from nautiuq_ml.climatology.grid import standardize
from nautiuq_ml.climatology.model import (
    fit as fit_reference,
    load_policy as climate_policy,
)
from nautiuq_ml.expected_state.features import (
    NAMES,
    audit_partitions,
    validate_profiles,
    vector,
)
from nautiuq_ml.expected_state.model import fit, infer, load_policy, promotion

ROOT = Path(__file__).resolve().parents[1]


def fixture(p):
    from nautiuq_ml.climatology.grid import phase

    rows = []
    for i in range(96):
        split = (
            "train"
            if i < 48
            else "tune"
            if i < 64
            else "calibration"
            if i < 80
            else "test"
        )
        year = {"train": 2008, "tune": 2018, "calibration": 2020, "test": 2023}[
            split
        ] + (i % 2 if split == "train" else 0)
        date = f"{year}-{i % 12 + 1:02}-15T12:00:00Z"
        lat = 5 + i % 6 * 3
        lon = 60 + i % 8 * 4
        for j, z in enumerate(p["standard_depths_m"]):
            rows.append(
                {
                    "profile_id": f"synthetic-{i:03}",
                    "revision_sha256": "a" * 64,
                    "raw_sha256": "b" * 64,
                    "platform_id": str(9000000 + i % 12),
                    "observed_at": date,
                    "latitude": lat,
                    "longitude": lon,
                    "split": split,
                    "depth_m": float(z),
                    "source_level_index": j,
                    "temperature_c": 27
                    - 0.01 * z
                    + 2 * math.sin(phase(date))
                    + 0.7 * (lat > 10 and z <= 100),
                    "practical_salinity": 35
                    + 0.3 * math.cos(phase(date))
                    + 0.02 * (lon - 60),
                }
            )
    return rows


def main():
    cp = climate_policy(ROOT / "packages/source-catalog/climatology.json")
    p = load_policy(ROOT / "packages/source-catalog/expected-state.json")
    import json
    import tempfile

    malformed = copy.deepcopy(p)
    malformed["promotion"]["untouched_test"] = "false"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json") as f:
        json.dump(malformed, f)
        f.flush()
        try:
            load_policy(f.name)
        except ValueError:
            pass
        else:
            raise AssertionError("Nonboolean promotion approval accepted")
    p = {**p, "max_rounds": 20, "bootstrap_replicates": 10}
    grid = standardize(fixture(cp), cp)
    reference = fit_reference(grid, cp)
    training = {
        "baseline": {"start_year": 2005, "end_year": 2024},
        "splits": {"train_end": 2016, "tune_end": 2019, "calibration_end": 2021},
    }
    validate_profiles(grid, training)
    f = vector(grid[0], cp)
    assert len(f) == len(NAMES) == 8
    assert (
        vector(
            dict(
                grid[0], platform_id="leaked", temperature_c=9999, practical_salinity=-9
            ),
            cp,
        )
        == f
    )
    assert (
        vector(
            dict(grid[0], observed_at=grid[0]["observed_at"].replace("2008", "2012")),
            cp,
        )
        == f
    )
    result = fit(grid, reference, p, audits=False)
    assert result["models"]
    assert canonical(result["models"]) == canonical(
        fit(grid, reference, p, audits=False)["models"]
    )
    changed = copy.deepcopy(grid)
    for r in changed:
        if r["split"] in ("test", "calibration"):
            r["temperature_c"] += 10
            r["practical_salinity"] -= 10
    assert canonical(result["models"]) == canonical(
        fit(changed, reference, p, audits=False)["models"]
    ), "Held-out labels affected fitted models"
    for kind in ("spatial", "platform"):
        for name, complement, held in audit_partitions(grid, p, kind):
            assert not (
                {r["profile_id"] for r in complement} & {r["profile_id"] for r in held}
            )
            if kind == "platform":
                assert not (
                    {r["platform_id"] for r in complement}
                    & {r["platform_id"] for r in held}
                )
            train_reference = fit_reference(complement, cp)
            perturbed = copy.deepcopy(complement)
            for r in perturbed:
                if r["split"] != "train":
                    r["temperature_c"] += 7
            assert train_reference == fit_reference(perturbed, cp)
            assert name
    bundle = {**result, "climatology": reference}
    points = [r for r in grid if r["split"] == "test"][:15]
    prediction = infer(points, bundle, True)
    assert (
        prediction["estimand"] == "conditional_mean"
        and prediction["interval_status"] == "unavailable_not_calibrated"
    )
    for row in prediction["rows"]:
        for variable in ("temperature_c", "practical_salinity"):
            item = row[variable]
            assert item["active_method"] != "lightgbm_residual"
            assert item["expected_mean"] == item["climatology_mean"]
            if item["candidate_mean"] is not None:
                assert math.isclose(
                    item["candidate_mean"],
                    item["climatology_mean"] + item["candidate_residual"],
                    abs_tol=1e-10,
                )
                assert math.isclose(
                    sum(c["contribution"] for c in item["feature_contributions"])
                    + item["contribution_bias"],
                    item["candidate_residual"],
                    abs_tol=1e-8,
                )
    for variable, model in result["models"].items():
        booster = lgb.Booster(model_str=model["model_text"])
        assert booster.feature_name() == list(NAMES)
        assert np.isfinite(
            booster.predict([vector(points[0], cp)], num_threads=1)
        ).all()
        gate = promotion(result["variables"][variable], variable, p)
        assert (
            not gate["eligible"]
            and "test_block_previously_inspected" in gate["reasons"]
        )
    fake = copy.deepcopy(grid)
    fake[0]["split"] = "test"
    try:
        validate_profiles(fake, training)
    except ValueError:
        pass
    else:
        raise AssertionError("Cross-partition stable profile accepted")
    try:
        infer(points * 3, bundle)
    except ValueError:
        pass
    else:
        raise AssertionError("Over-budget inference accepted")
    assert not fit(
        [r for r in grid if r["profile_id"] in {"synthetic-000", "synthetic-001"}],
        reference,
        p,
        audits=False,
    )["models"]
    print(
        "Residual-model offline gate passed: shared label/year-free features, grouped partitions/buffers, train-only fits, tuning selection, test/calibration isolation, reproducible native models, contribution additivity, fallback and promotion refusal"
    )


if __name__ == "__main__":
    main()
