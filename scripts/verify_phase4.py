"""Offline grid, leakage, pooling, harmonic numerical and spread verification."""

import copy
import json
import math
from pathlib import Path

from nautiq_ml.argo.evidence import canonical
from nautiq_ml.climatology.grid import phase, sample, standardize
from nautiq_ml.climatology.model import compare, evaluate, fit, load_policy, predict

ROOT = Path(__file__).resolve().parents[1]


def fixture(policy):
    rows = []
    for i in range(48):
        year = 2005 + i // 12
        month = i % 12 + 1
        observed = f"{year}-{month:02}-15T12:00:00Z"
        for j, z in enumerate(policy["standard_depths_m"]):
            rows.append(
                {
                    "profile_id": f"toy-{i:03}",
                    "revision_sha256": "a" * 64,
                    "raw_sha256": "b" * 64,
                    "platform_id": str(9000000 + i % 4),
                    "observed_at": observed,
                    "latitude": 8 + i % 5 * 3,
                    "longitude": 60 + i % 5 * 3,
                    "split": "train" if i < 36 else "test",
                    "source_level_index": j,
                    "depth_m": float(z),
                    "temperature_c": 24 + 2 * math.sin(phase(observed)) - 0.003 * z,
                    "practical_salinity": 35 + 0.5 * math.cos(phase(observed)),
                }
            )
    return rows


def main():
    policy = load_policy(ROOT / "packages/source-catalog/climatology.json")
    levels = [
        {
            "depth_m": 10.0,
            "source_level_index": 0,
            "temperature_c": 30.0,
            "practical_salinity": None,
        },
        {
            "depth_m": 20.0,
            "source_level_index": 1,
            "temperature_c": 28.0,
            "practical_salinity": 35.0,
        },
        {
            "depth_m": 300.0,
            "source_level_index": 2,
            "temperature_c": 18.0,
            "practical_salinity": 34.0,
        },
    ]
    result = sample(levels, [0, 10, 15, 20, 100, 500], "temperature_c", policy)
    assert [r["value"] for r in result] == [None, 30, 29, 28, None, None]
    assert result[4]["reason"] == "wide_gap"
    assert (
        sample(levels, [15], "practical_salinity", policy)[0]["reason"]
        == "missing_bracket"
    )
    skipped = copy.deepcopy(levels)
    skipped[1]["source_level_index"] = 2
    assert (
        sample(skipped, [15], "temperature_c", policy)[0]["reason"]
        == "rejected_native_gap"
    )
    duplicate = levels + [levels[0]]
    try:
        sample(duplicate, [10], "temperature_c", policy)
    except ValueError:
        pass
    else:
        raise AssertionError("Duplicate depths accepted")
    assert (
        abs(
            math.sin(phase("2009-12-31T23:59:59Z"))
            - math.sin(phase("2010-01-01T00:00:00Z"))
        )
        < 1e-6
    )
    rows = fixture(policy)
    grid = standardize(rows, policy)
    bundle = fit(grid, policy)
    assert canonical(bundle) == canonical(fit(grid, policy))
    perturbed = copy.deepcopy(grid)
    for row in perturbed:
        if row["split"] != "train":
            row["temperature_c"] = 10000
            row["latitude"] = 29.9
            row["longitude"] = 99
    assert canonical(bundle) == canonical(fit(perturbed, policy)), (
        "Held-out data altered fitted state"
    )
    anchor = dict(
        grid[0],
        latitude=14.0,
        longitude=66.0,
        depth_m=10.0,
        observed_at="2022-06-15T12:00:00Z",
    )
    reference = predict(anchor, "temperature_c", bundle)
    assert predict(dict(anchor, depth_m=10), "temperature_c", bundle) == reference
    frozen = json.loads(
        (ROOT / "packages/scientific-fixtures/climatology/reference.json").read_text()
    )
    assert math.isclose(
        reference["expected_mean"], frozen["expected_mean"], rel_tol=0, abs_tol=1e-8
    )
    assert math.isclose(reference["spread"], frozen["spread"], rel_tol=0, abs_tol=1e-8)
    assert reference["method_group"] == frozen["method_group"]
    assert reference["training_profiles"] == frozen["training_profiles"]
    comparison = compare(
        [dict(anchor, temperature_c=reference["expected_mean"] + 1)], bundle
    )
    assert comparison["rows"][0]["temperature_c"]["direction"] == "warmer"
    assert comparison["rows"][0]["temperature_c"]["difference"] == 1
    assert comparison["spread_interpretation"] and not comparison["release_approved"]
    assert (
        predict(dict(anchor, latitude=90), "temperature_c", bundle)["reason"]
        == "outside_domain"
    )
    assert (
        predict(dict(anchor, latitude=29.9), "temperature_c", bundle)["expected_mean"]
        is None
    )
    assert (
        predict(dict(anchor, depth_m=11), "temperature_c", bundle)["reason"]
        == "unsupported_depth"
    )
    pooled = copy.deepcopy(grid)
    for row in pooled:
        if row["split"] == "train" and row["depth_m"] == 30:
            row["temperature_c"] = None
    fallback = predict(dict(anchor, depth_m=30), "temperature_c", fit(pooled, policy))
    assert fallback["method_group"] == "basin_depth_band" and fallback["fallback"]
    constant = copy.deepcopy(grid)
    for row in constant:
        row["temperature_c"] = 25
    assert (
        predict(anchor, "temperature_c", fit(constant, policy))["spread"]
        == policy["spread_floor"]["temperature_c"]
    )
    scarce = [r for r in grid if r["profile_id"] in {"toy-000", "toy-001"}]
    assert not fit(scarce, policy)["models"]
    implausible = copy.deepcopy(bundle)
    for model in implausible["models"].values():
        model["coefficients"][0] = 10000
    assert predict(anchor, "temperature_c", implausible)["expected_mean"] is None
    mixed = copy.deepcopy(rows)
    mixed[0]["split"] = "test"
    try:
        standardize(mixed, policy)
    except ValueError:
        pass
    else:
        raise AssertionError("One profile crossed splits")
    report = evaluate(grid, bundle)
    test = report["variables"]["temperature_c"]["test"]
    assert (
        test["overall"]["evaluated_rows"] > 0
        and test["overall"]["profile_bootstrap_mae_95"] is not None
    )
    assert test["regions"]["bay_bengal"]["mae"] is None
    assert set(test["depths"]) == {str(z) for z in policy["standard_depths_m"]}
    assert not report["spread_is_calibrated"]
    print(
        "Climatology offline gate passed: frozen harmonic reference, no holdout leakage, UTC season continuity, per-variable grid coverage, no extrapolation/gap bridging, spatial/depth fallback, support masks, spread floors, direction and grouped evaluation"
    )


if __name__ == "__main__":
    main()
