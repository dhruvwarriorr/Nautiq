"""Train-only ridge harmonics with declared spatial/depth fallback and spread."""

import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from ..argo.evidence import canonical
from ..argo.storage import digest
from .grid import VARIABLES, instant, phase

METHOD = "harmonic-climatology-v1"


def load_policy(path):
    p = json.loads(Path(path).read_bytes())
    depths = p["standard_depths_m"]
    if (
        p.get("schema_version") != 1
        or p.get("method_version") != METHOD
        or p.get("grid_version") != "argo-standard-grid-v1"
        or p.get("release_approved") is not False
        or p.get("require_adjacent_native_levels") is not True
        or not 1 <= len(depths) <= 32
        or any(
            not isinstance(z, (float, int)) or not math.isfinite(z) or not 0 < z <= 2000
            for z in depths
        )
        or depths != sorted(set(depths))
        or not 0 < p["max_interpolation_gap_m"] <= 250
        or not 12 <= p["min_profiles"] <= 2000
        or not 3 <= p["min_platforms"] <= 2000
        or not 4 <= p["min_months"] <= 12
        or not 2 <= p["min_years"] <= 50
        or not 0 < p["ridge_alpha"] <= 100
        or not 1 <= p["cell_degrees"] <= 10
        or not 1 <= p["max_profiles"] <= 2000
        or not 1 <= p["max_source_levels"] <= 100000
        or not 10 <= p["bootstrap_replicates"] <= 1000
    ):
        raise ValueError("unsupported_climatology_policy")
    b = p["domain"]
    if (
        not -180 <= b["west"] < p["basin_boundary_longitude"] < b["east"] <= 180
        or not -90 <= b["south"] < b["north"] <= 90
    ):
        raise ValueError("invalid_climatology_domain")
    bands = p["depth_bands_m"]
    if (
        bands != [[0, 100], [100, 500], [500, 2000]]
        or any(not 0 < p["spread_floor"][v] < 1 for v in VARIABLES)
        or p["physical_bounds"]
        != {"temperature_c": [-3, 45], "practical_salinity": [0, 42]}
    ):
        raise ValueError("invalid_climatology_bounds")
    return p


def region(row, p):
    return (
        "arabian" if row["longitude"] < p["basin_boundary_longitude"] else "bay_bengal"
    )


def cell(row, p):
    return f"{math.floor(row['latitude'] / p['cell_degrees'])}:{math.floor(row['longitude'] / p['cell_degrees'])}"


def band(z, p):
    for i, (a, b) in enumerate(p["depth_bands_m"]):
        if (a < z <= b) or (i == 0 and z == 0):
            return i
    return None


def features(row, p, pooled=False):
    b = p["domain"]
    theta = phase(row["observed_at"])
    x = [
        1,
        (row["latitude"] - b["south"]) / (b["north"] - b["south"]) - 0.5,
        (row["longitude"] - b["west"]) / (b["east"] - b["west"]) - 0.5,
        math.sin(theta),
        math.cos(theta),
        math.sin(2 * theta),
        math.cos(2 * theta),
    ]
    if pooled:
        a, b = p["depth_bands_m"][band(row["depth_m"], p)]
        z = (row["depth_m"] - a) / (b - a) - 0.5
        x += [z, z * z]
    return x


def fit_group(rows, variable, p, pooled):
    counts = Counter(r["profile_id"] for r in rows)
    support = {
        "profile_count": len(counts),
        "platform_count": len({r["platform_id"] for r in rows}),
        "months": sorted({instant(r["observed_at"]).month for r in rows}),
        "years": sorted({instant(r["observed_at"]).year for r in rows}),
    }
    if (
        len(counts) < p["min_profiles"]
        or support["platform_count"] < p["min_platforms"]
        or len(support["months"]) < p["min_months"]
        or len(support["years"]) < p["min_years"]
    ):
        return None
    x = np.asarray([features(r, p, pooled) for r in rows], dtype=float)
    y = np.asarray([r[variable] for r in rows], dtype=float)
    w = np.asarray([1 / counts[r["profile_id"]] for r in rows])
    penalty = np.eye(x.shape[1]) * p["ridge_alpha"]
    penalty[0, 0] = 0
    matrix = x.T @ (w[:, None] * x) + penalty
    if np.linalg.cond(matrix) > 1e10:
        return None
    coef = np.linalg.solve(matrix, x.T @ (w * y))
    residual = y - x @ coef
    rms = math.sqrt(float(np.sum(w * residual**2) / np.sum(w)))
    return {
        "coefficients": coef.tolist(),
        "pooled_depth": pooled,
        "spread": max(rms, p["spread_floor"][variable]),
        "spread_estimator": "training_residual_rms_profile_weighted",
        "spread_floor": p["spread_floor"][variable],
        "rows": len(rows),
        **support,
        "latitude_range": [
            min(r["latitude"] for r in rows),
            max(r["latitude"] for r in rows),
        ],
        "longitude_range": [
            min(r["longitude"] for r in rows),
            max(r["longitude"] for r in rows),
        ],
        "depth_range": [
            min(r["depth_m"] for r in rows),
            max(r["depth_m"] for r in rows),
        ],
    }


def model_key(variable, kind, area, z):
    if kind != "basin_depth_band":
        z = float(z)
    return f"{variable}|{kind}|{area}|{z}"


def fit(grid, p):
    train = sorted(
        (r for r in grid if r["split"] == "train"),
        key=lambda r: (r["profile_id"], r["depth_m"]),
    )
    groups = defaultdict(list)
    for row in train:
        if not inside(row, p["domain"]):
            raise ValueError("training_outside_domain")
        for variable in VARIABLES:
            value = row[variable]
            if value is None:
                continue
            low, high = p["physical_bounds"][variable]
            if not math.isfinite(value) or not low <= value <= high:
                raise ValueError("invalid_training_label")
            for kind, area, z in (
                ("cell_depth", cell(row, p), row["depth_m"]),
                ("basin_depth", region(row, p), row["depth_m"]),
                ("basin_depth_band", region(row, p), band(row["depth_m"], p)),
            ):
                groups[model_key(variable, kind, area, z)].append(row)
    models = {}
    for key, rows in sorted(groups.items()):
        variable, kind, _, _ = key.split("|")
        model = fit_group(rows, variable, p, kind == "basin_depth_band")
        if model:
            models[key] = model
    return {
        "schema_version": 1,
        "method_version": METHOD,
        "policy": p,
        "fit_hash": digest(canonical({"policy": p, "training_grid": train})),
        "fit_profile_count": len({r["profile_id"] for r in train}),
        "fit_observed_range": [
            min(r["observed_at"] for r in train),
            max(r["observed_at"] for r in train),
        ]
        if train
        else None,
        "models": models,
        "estimand": "conditional_mean",
        "release_approved": False,
        "spread_interpretation": "Training residual variability around the fixed reference; not a calibrated predictive interval or confidence interval for the mean.",
    }


def inside(row, box):
    return (
        all(math.isfinite(row[k]) for k in ("latitude", "longitude", "depth_m"))
        and box["south"] <= row["latitude"] <= box["north"]
        and box["west"] <= row["longitude"] <= box["east"]
    )


def predict(row, variable, bundle):
    p = bundle["policy"]
    z = row["depth_m"]
    if not inside(row, p["domain"]):
        return {"expected_mean": None, "reason": "outside_domain"}
    if z not in p["standard_depths_m"]:
        return {"expected_mean": None, "reason": "unsupported_depth"}
    candidates = [
        ("cell_depth", cell(row, p), z),
        ("basin_depth", region(row, p), z),
        ("basin_depth_band", region(row, p), band(z, p)),
    ]
    rejected = []
    for kind, area, target in candidates:
        key = model_key(variable, kind, area, target)
        m = bundle["models"].get(key)
        if not m:
            rejected.append("insufficient_training_support")
            continue
        if not (
            m["latitude_range"][0] <= row["latitude"] <= m["latitude_range"][1]
            and m["longitude_range"][0] <= row["longitude"] <= m["longitude_range"][1]
            and m["depth_range"][0] <= z <= m["depth_range"][1]
        ):
            rejected.append("outside_training_envelope")
            continue
        value = float(
            np.asarray(features(row, p, m["pooled_depth"]))
            @ np.asarray(m["coefficients"])
        )
        low, high = p["physical_bounds"][variable]
        if not math.isfinite(value) or not low <= value <= high:
            rejected.append("implausible_reference")
            continue
        return {
            "expected_mean": value,
            "spread": m["spread"],
            "spread_estimator": m["spread_estimator"],
            "method_group": kind,
            "model_key": key,
            "fallback": kind != "cell_depth",
            "fallback_reasons": rejected,
            "training_profiles": m["profile_count"],
            "training_platforms": m["platform_count"],
            "training_months": m["months"],
            "reason": None,
        }
    return {"expected_mean": None, "reason": rejected[-1], "fallback_reasons": rejected}


def compare(grid, bundle):
    result = []
    supported = 0
    for row in grid:
        entry = {"depth_m": row["depth_m"]}
        for variable in VARIABLES:
            reference = predict(row, variable, bundle)
            observed = row[variable]
            expected = reference["expected_mean"]
            difference = (
                observed - expected
                if observed is not None and expected is not None
                else None
            )
            supported += difference is not None
            entry[variable] = {
                **reference,
                "observed": observed,
                "observed_reason": row["coverage"][variable]["reason"],
                "observed_method": row["coverage"][variable]["method"],
                "difference": difference,
                "direction": (
                    "warmer"
                    if difference > 0
                    else "cooler"
                    if difference < 0
                    else "equal"
                )
                if difference is not None and variable == "temperature_c"
                else (
                    "saltier"
                    if difference > 0
                    else "fresher"
                    if difference < 0
                    else "equal"
                )
                if difference is not None
                else "unavailable",
            }
        result.append(entry)
    return {
        "rows": result,
        "supported_pairs": supported,
        "status": "ready"
        if supported == len(grid) * 2
        else "partial"
        if supported
        else "unavailable",
        "estimand": bundle["estimand"],
        "method_version": METHOD,
        "release_approved": False,
        "spread_interpretation": bundle["spread_interpretation"],
    }


def metrics(rows, variable, bundle, p):
    evaluated = []
    counts = Counter()
    for row in rows:
        prediction = predict(row, variable, bundle)
        value = row[variable]
        if value is None:
            counts["missing_observed"] += 1
            continue
        if prediction["expected_mean"] is None:
            counts[prediction["reason"]] += 1
            continue
        evaluated.append((row, value - prediction["expected_mean"]))
        counts[prediction["method_group"]] += 1
    if not evaluated:
        return {
            "evaluated_rows": 0,
            "profiles": 0,
            "candidate_rows": len(rows),
            "coverage_counts": dict(counts),
            "mae": None,
            "rmse": None,
            "bias": None,
            "profile_weighted_mae": None,
            "profile_bootstrap_mae_95": None,
        }
    errors = np.array([v for _, v in evaluated])
    by_profile = defaultdict(list)
    for row, error in evaluated:
        by_profile[row["profile_id"]].append(abs(error))
    scores = np.array([np.mean(v) for _, v in sorted(by_profile.items())])
    interval = None
    if len(scores) >= 3:
        rng = np.random.default_rng(p["seed"])
        bootstrap = [
            float(rng.choice(scores, len(scores), replace=True).mean())
            for _ in range(p["bootstrap_replicates"])
        ]
        interval = np.quantile(bootstrap, [0.025, 0.975]).tolist()
    return {
        "evaluated_rows": len(errors),
        "profiles": len(scores),
        "candidate_rows": len(rows),
        "coverage_counts": dict(counts),
        "mae": float(np.abs(errors).mean()),
        "rmse": float(np.sqrt(np.mean(errors**2))),
        "bias": float(errors.mean()),
        "profile_weighted_mae": float(scores.mean()),
        "profile_bootstrap_mae_95": interval,
    }


def evaluate(grid, bundle):
    p = bundle["policy"]
    report = {
        "variables": {},
        "selection": "fixed_policy_no_holdout_tuning",
        "release_approved": False,
        "bootstrap_unit": "stable_profile",
        "bootstrap_limitations": "Exploratory profile bootstrap does not resolve serial float dependence or spatial independence.",
        "fitting_split": "train",
        "spread_is_calibrated": False,
    }
    for variable in VARIABLES:
        partitions = {}
        for split in ("train", "tune", "calibration", "test"):
            rows = [r for r in grid if r["split"] == split]
            partitions[split] = {
                "overall": metrics(rows, variable, bundle, p),
                "regions": {
                    name: metrics(
                        [r for r in rows if region(r, p) == name], variable, bundle, p
                    )
                    for name in ("arabian", "bay_bengal")
                },
                "depths": {
                    str(z): metrics(
                        [r for r in rows if r["depth_m"] == z], variable, bundle, p
                    )
                    for z in p["standard_depths_m"]
                },
            }
        report["variables"][variable] = partitions
    return report
