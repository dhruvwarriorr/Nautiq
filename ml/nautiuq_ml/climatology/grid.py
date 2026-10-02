"""Versioned standard depths with per-variable coverage; never extrapolate."""

import math
from bisect import bisect_left
from collections import defaultdict
from datetime import datetime, timezone

VARIABLES = ("temperature_c", "practical_salinity")


def instant(value):
    t = datetime.fromisoformat(value)
    if t.tzinfo is None:
        raise ValueError("explicit_timezone_required")
    return t.astimezone(timezone.utc)


def phase(value):
    t = instant(value)
    start = datetime(t.year, 1, 1, tzinfo=timezone.utc)
    end = datetime(t.year + 1, 1, 1, tzinfo=timezone.utc)
    return 2 * math.pi * (t - start).total_seconds() / (end - start).total_seconds()


def sample(levels, targets, variable, policy):
    ordered = sorted(levels, key=lambda x: x["depth_m"])
    depths = [p["depth_m"] for p in ordered]
    if any(not math.isfinite(z) or z < 0 for z in depths) or any(
        a >= b for a, b in zip(depths, depths[1:])
    ):
        raise ValueError("invalid_standard_grid_input")
    answer = []
    for z in targets:
        i = bisect_left(depths, z)
        value, reason, method = None, "outside_sampled_range", None
        if i < len(depths) and depths[i] == z:
            value = ordered[i][variable]
            reason = None if value is not None else "missing_measurement"
            method = "exact" if value is not None else None
        elif 0 < i < len(depths):
            a, b = ordered[i - 1], ordered[i]
            if a[variable] is None or b[variable] is None:
                reason = "missing_bracket"
            elif b["depth_m"] - a["depth_m"] > policy["max_interpolation_gap_m"]:
                reason = "wide_gap"
            elif (
                policy["require_adjacent_native_levels"]
                and abs(int(a["source_level_index"]) - int(b["source_level_index"]))
                != 1
            ):
                reason = "rejected_native_gap"
            else:
                fraction = (z - a["depth_m"]) / (b["depth_m"] - a["depth_m"])
                value = a[variable] + fraction * (b[variable] - a[variable])
                reason, method = None, "linear_interpolation"
        if value is not None and not math.isfinite(value):
            raise ValueError("nonfinite_standard_grid_input")
        answer.append({"value": value, "reason": reason, "method": method})
    return answer


def standardize(rows, policy):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["profile_id"]].append(row)
    if len(rows) > policy["max_source_levels"] or len(grouped) > policy["max_profiles"]:
        raise ValueError("climatology_input_budget")
    grid = []
    for pid, levels in sorted(grouped.items()):
        p = levels[0]
        identity = (
            "revision_sha256",
            "raw_sha256",
            "platform_id",
            "observed_at",
            "latitude",
            "longitude",
            "split",
        )
        if any(any(r[k] != p[k] for k in identity) for r in levels):
            raise ValueError("profile_split_or_revision_leakage")
        if len({r["source_level_index"] for r in levels}) != len(levels):
            raise ValueError("duplicate_native_level")
        variables = {
            v: sample(levels, policy["standard_depths_m"], v, policy) for v in VARIABLES
        }
        for i, z in enumerate(policy["standard_depths_m"]):
            grid.append(
                {
                    "profile_id": pid,
                    **{k: p[k] for k in identity},
                    "depth_m": float(z),
                    **{v: variables[v][i]["value"] for v in VARIABLES},
                    "coverage": {v: variables[v][i] for v in VARIABLES},
                    "grid_version": policy["grid_version"],
                }
            )
    return grid


def profile_grid(profile, policy):
    rows = [
        {
            "profile_id": str(profile["profile_id"]),
            "revision_sha256": profile["revision_sha256"],
            "raw_sha256": profile["raw_sha"],
            "platform_id": profile["platform_id"],
            "observed_at": profile["observed_at"].isoformat(),
            "latitude": profile["latitude"],
            "longitude": profile["longitude"],
            "split": "observation",
            "depth_m": p["depth_m"],
            "source_level_index": int(p["qc_flags"]["source_level_index"]),
            **{v: p[v] for v in VARIABLES},
        }
        for p in profile["levels"]
    ]
    return standardize(rows, policy)
