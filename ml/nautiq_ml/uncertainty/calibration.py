"""Profile-level CQR scores, finite ranks and a frozen Mondrian fallback hierarchy."""

import math
from collections import defaultdict

import numpy as np

from ..climatology.model import band, region

UNIT = "stable_profile_maximum_within_group"


def groups(row, climate_policy):
    area = region(row, climate_policy)
    depth = band(row["depth_m"], climate_policy)
    return (
        f"region_depth:{area}:{depth}",
        f"region:{area}",
        f"depth:{depth}",
        "global",
    )


def cutoff(scores, alpha, minimum):
    n = len(scores)
    rank = math.ceil((n + 1) * (1 - alpha))
    return {
        "profiles": n,
        "rank": rank,
        "correction": float(sorted(scores)[rank - 1])
        if n >= minimum and rank <= n
        else None,
        "reason": None
        if n >= minimum and rank <= n
        else "insufficient_calibration_profiles_or_rank",
    }


def fit(rows, truth, ordered, climate_policy, policy):
    values = defaultdict(dict)
    for row, y, q in zip(rows, truth, ordered, strict=True):
        if row["split"] != "calibration":
            continue
        score = max(float(q[0] - y), float(y - q[2]), 0.0)
        for key in groups(row, climate_policy):
            values[key][row["profile_id"]] = max(
                score, values[key].get(row["profile_id"], 0.0)
            )
    expected = {"global", "region:arabian", "region:bay_bengal"}
    expected.update(f"depth:{i}" for i in range(len(climate_policy["depth_bands_m"])))
    expected.update(
        f"region_depth:{area}:{i}"
        for area in ("arabian", "bay_bengal")
        for i in range(len(climate_policy["depth_bands_m"]))
    )
    return {
        "unit": UNIT,
        "alpha": policy["alpha"],
        "fitting_partition": "calibration",
        "hierarchy": policy["hierarchy"],
        "groups": {
            key: cutoff(
                list(values[key].values()),
                policy["alpha"],
                policy["min_calibration_profiles"],
            )
            for key in sorted(expected)
        },
        "coverage_claim": "Nominal coverage is per profile within the named region/depth group; no conditional or full-profile joint guarantee is asserted.",
    }


def choose(row, climate_policy, calibration):
    keys = groups(row, climate_policy)
    for i, key in enumerate(keys):
        info = calibration["groups"][key]
        if info["correction"] is not None:
            return {
                **info,
                "group": key,
                "requested_group": keys[0],
                "fallback": i > 0,
                "fallback_reasons": [k for k in keys[:i]],
            }
    return {
        "group": None,
        "requested_group": keys[0],
        "profiles": 0,
        "rank": None,
        "correction": None,
        "fallback": True,
        "fallback_reasons": list(keys),
        "reason": "calibration_unavailable",
    }


def apply(rows, ordered, climate_policy, calibration):
    selected = [choose(r, climate_policy, calibration) for r in rows]
    offset = np.array(
        [v["correction"] if v["correction"] is not None else np.nan for v in selected]
    )
    return np.column_stack((ordered[:, 0] - offset, ordered[:, 2] + offset)), selected


def wilson(successes, count):
    if not count:
        return None
    p, z = successes / count, 1.959963984540054
    denominator = 1 + z * z / count
    center = (p + z * z / (2 * count)) / denominator
    radius = (
        z * math.sqrt(p * (1 - p) / count + z * z / (4 * count * count)) / denominator
    )
    return [max(0.0, center - radius), min(1.0, center + radius)]


def metrics(
    rows, truth, quantiles, intervals, raw=None, selections=None, climate_policy=None
):
    n = len(rows)
    if not n:
        return {
            "rows": 0,
            "profiles": 0,
            "pinball_loss": None,
            "quantile_pinball": None,
            "crossing_rate": None,
            "raw_row_coverage": None,
            "calibrated_rows": 0,
            "row_coverage": None,
            "profile_group_count": 0,
            "profile_group_coverage": None,
            "profile_group_coverage_95": None,
            "full_profile_coverage": None,
            "mean_width": None,
            "profile_weighted_width": None,
            "fallback_rows": 0,
            "unavailable_rows": 0,
        }
    y = np.asarray(truth)
    errors = y[:, None] - quantiles
    loss = np.maximum(
        np.array([0.1, 0.5, 0.9]) * errors, (np.array([0.1, 0.5, 0.9]) - 1) * errors
    )
    profiles = defaultdict(list)
    for i, row in enumerate(rows):
        profiles[row["profile_id"]].append(i)
    per_q = np.mean([loss[idx].mean(axis=0) for idx in profiles.values()], axis=0)
    valid = np.isfinite(intervals).all(axis=1)
    inside = (y >= intervals[:, 0]) & (y <= intervals[:, 1])
    units, complete = defaultdict(list), defaultdict(list)
    widths = defaultdict(list)
    for i, row in enumerate(rows):
        complete[row["profile_id"]].append(bool(valid[i] and inside[i]))
        if valid[i]:
            key = groups(row, climate_policy)[0] if climate_policy else "overall"
            units[(row["profile_id"], key)].append(bool(inside[i]))
            widths[row["profile_id"]].append(float(intervals[i, 1] - intervals[i, 0]))
    successes = sum(all(v) for v in units.values())
    count = int(valid.sum())
    return {
        "rows": n,
        "profiles": len(profiles),
        "pinball_loss": float(per_q.mean()),
        "quantile_pinball": {
            str(q): float(v) for q, v in zip((0.1, 0.5, 0.9), per_q, strict=True)
        },
        "crossing_rate": float(
            np.any(
                np.diff(raw if raw is not None else quantiles, axis=1) < 0, axis=1
            ).mean()
        ),
        "raw_row_coverage": float(
            ((y >= quantiles[:, 0]) & (y <= quantiles[:, 2])).mean()
        ),
        "calibrated_rows": count,
        "row_coverage": float(inside[valid].mean()) if count else None,
        "profile_group_count": len(units),
        "profile_group_coverage": successes / len(units) if units else None,
        "profile_group_coverage_95": wilson(successes, len(units)),
        "full_profile_coverage": sum(all(v) for v in complete.values()) / len(complete)
        if count
        else None,
        "mean_width": float((intervals[valid, 1] - intervals[valid, 0]).mean())
        if count
        else None,
        "profile_weighted_width": float(np.mean([np.mean(v) for v in widths.values()]))
        if widths
        else None,
        "fallback_rows": sum(bool(s["fallback"]) for s in selections)
        if selections
        else 0,
        "unavailable_rows": n - count,
    }
