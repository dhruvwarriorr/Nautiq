"""Independent, bounded event arithmetic with unknown-day and point-support semantics."""

import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
from shapely.geometry import box, mapping
from shapely.ops import unary_union

from ..fields.core import canonical, haversine, number, utc

POLICY = json.loads(
    next(
        p
        for p in (
            Path("/events.json"),
            Path(__file__).parents[3] / "packages/source-catalog/events.json",
        )
        if p.exists()
    ).read_text()
)
METHOD = POLICY["method"]


class EventError(ValueError):
    """Stable reason, never source payloads or connection details."""


def day(value):
    if not isinstance(value, str) or len(value) != 10:
        raise EventError("explicit_utc_day_required")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise EventError("invalid_utc_day") from None


def days(start, end, maximum):
    start, end = day(start), day(end)
    n = (end - start).days + 1
    if not 1 <= n <= maximum:
        raise EventError("day_window_budget")
    return [(start + timedelta(days=i)).isoformat() for i in range(n)]


def seasonal_index(value):
    d = day(value)
    return (date(2000, d.month, d.day) - date(2000, 1, 1)).days


def axes(lat, lon):
    lat, lon = np.asarray(lat, dtype="float64"), np.asarray(lon, dtype="float64")
    if (
        lat.ndim != 1
        or lon.ndim != 1
        or not 2 <= len(lat) <= 128
        or not 2 <= len(lon) <= 128
        or len(lat) * len(lon) > POLICY["limits"]["cells"]
        or not np.isfinite(lat).all()
        or not np.isfinite(lon).all()
    ):
        raise EventError("event_grid_budget")
    for a in (lat, lon):
        if not np.allclose(np.diff(a), 0.25, atol=1e-5, rtol=0):
            raise EventError("compatible_native_oisst_grid_required")
    if lat[0] < -89.875 or lat[-1] > 89.875 or lon[0] < -179.875 or lon[-1] > 179.875:
        raise EventError("split_dateline_grid_required")
    return lat, lon


def daily(values, dates, lat, lon, maximum):
    lat, lon = axes(lat, lon)
    if not dates or list(dates) != days(dates[0], dates[-1], maximum):
        raise EventError("continuous_daily_axis_required")
    if len(dates) * len(lat) * len(lon) * 4 > POLICY["limits"]["array_bytes"]:
        raise EventError("expanded_array_budget")
    a = np.asarray(values, dtype="float32")
    if a.shape != (len(dates), len(lat), len(lon)) or np.isinf(a).any():
        raise EventError("invalid_daily_array")
    if ((np.isfinite(a)) & ((a < -3) | (a > 45))).any():
        raise EventError("sst_physical_bounds")
    return a


def fit_baseline(values, dates, lat, lon):
    a = daily(values, dates, lat, lon, POLICY["limits"]["history_days"])
    first, last = POLICY["baseline_years"]
    if dates != days(
        f"{first}-01-01", f"{last}-12-31", POLICY["limits"]["history_days"]
    ):
        raise EventError("fixed_thirty_year_baseline_required")
    indices = np.array([seasonal_index(d) for d in dates])
    years = np.array([day(d).year for d in dates])
    flat = a.reshape(len(dates), -1)
    mean = np.full((366, flat.shape[1]), np.nan, dtype="float32")
    threshold = mean.copy()
    count = np.zeros(mean.shape, dtype="int16")
    year_count = np.zeros(mean.shape, dtype="int16")
    for d in range(366):
        if d == 59:  # February 29 is interpolated before cyclic smoothing.
            continue
        selected = np.zeros(len(dates), dtype=bool)
        for center in np.flatnonzero(indices == d):
            half = POLICY["pool_half_window_days"]
            selected[max(0, center - half) : min(len(dates), center + half + 1)] = True
        for start in range(0, flat.shape[1], 64):
            sample = flat[selected, start : start + 64]
            finite = np.isfinite(sample)
            n = finite.sum(axis=0)
            ny = np.array(
                [
                    sum(
                        np.any(finite[years[selected] == y, c])
                        for y in range(first, last + 1)
                    )
                    for c in range(sample.shape[1])
                ]
            )
            valid = (n >= np.ceil(selected.sum() * POLICY["min_baseline_fraction"])) & (
                ny >= POLICY["min_baseline_years"]
            )
            count[d, start : start + 64], year_count[d, start : start + 64] = n, ny
            if valid.any():
                mean[d, start : start + 64][valid] = np.nanmean(
                    sample[:, valid], axis=0
                )
                threshold[d, start : start + 64][valid] = np.nanpercentile(
                    sample[:, valid], POLICY["percentile"], axis=0, method="linear"
                )
    for array in (mean, threshold):
        array[59] = (array[58] + array[60]) / 2
        half = POLICY["smooth_window_days"] // 2
        window = np.stack(
            [np.roll(array, shift, axis=0) for shift in range(-half, half + 1)]
        )
        array[:] = window.mean(
            axis=0
        )  # Missing seasonal support is never smoothed away.
    count[59], year_count[59] = (
        np.minimum(count[58], count[60]),
        np.minimum(year_count[58], year_count[60]),
    )
    shape = (366, len(lat), len(lon))
    return {
        "mean": mean.reshape(shape),
        "threshold": threshold.reshape(shape),
        "count": count.reshape(shape),
        "years": year_count.reshape(shape),
    }


def cell_intervals(values, mean, threshold):
    valid = (
        np.isfinite(values)
        & np.isfinite(mean)
        & np.isfinite(threshold)
        & (threshold > mean)
    )
    above = valid & (values > threshold)
    ranges, begin = [], None
    for i, flag in enumerate(np.r_[above, False]):
        if flag and begin is None:
            begin = i
        elif not flag and begin is not None:
            if i - begin >= POLICY["min_duration_days"]:
                ranges.append([begin, i - 1])
            begin = None
    merged = []
    for start, end in ranges:
        if (
            merged
            and start - merged[-1][1] - 1 <= POLICY["max_observed_gap_days"]
            and valid[merged[-1][1] + 1 : start].all()
        ):
            merged[-1][1] = end
        else:
            merged.append([start, end])
    qualified = np.zeros(len(values), dtype=bool)
    for start, end in merged:
        qualified[start : end + 1] = True
    return qualified, above, valid, merged


def components(mask):
    """4-neighbor space; consecutive-day same/adjacent cells in time. No time-gap edges."""
    tmax, ymax, xmax = mask.shape
    if int(mask.sum()) > POLICY["limits"]["qualified_cell_days"]:
        raise EventError("component_cell_day_budget")
    seeds = [tuple(map(int, x)) for x in np.argwhere(mask)]
    remaining = set(seeds)
    for seed in seeds:
        if seed not in remaining:
            continue
        remaining.remove(seed)
        stack, group = [seed], []
        while stack:
            t, y, x = stack.pop()
            group.append((t, y, x))
            for dt in (-1, 0, 1):
                for dy, dx in ((0, 0), (-1, 0), (1, 0), (0, -1), (0, 1)):
                    p = (t + dt, y + dy, x + dx)
                    if (
                        0 <= p[0] < tmax
                        and 0 <= p[1] < ymax
                        and 0 <= p[2] < xmax
                        and p in remaining
                    ):
                        remaining.remove(p)
                        stack.append(p)
        yield sorted(group)


def group_cells(mask, intensity, category, dates, lat, lon, observed, min_days=None):
    result, rejected = [], 0
    min_days = min_days or POLICY["min_duration_days"]
    areas = (
        6371.0088**2
        * np.deg2rad(0.25)
        * (
            np.sin(np.deg2rad(np.asarray(lat) + 0.125))
            - np.sin(np.deg2rad(np.asarray(lat) - 0.125))
        )
    )
    for group in components(mask):
        per_day = {}
        for t, y, x in group:
            per_day.setdefault(t, []).append((y, x))
        supported_dates = [
            t
            for t, cells in per_day.items()
            if len(cells) >= POLICY["regional_min_cells"]
            and sum(areas[y] for y, x in cells) >= POLICY["regional_min_area_km2"]
        ]
        longest, current, prior = 0, 0, -2
        for t in sorted(supported_dates):
            current = current + 1 if t == prior + 1 else 1
            longest, prior = max(longest, current), t
        if longest < min_days:
            rejected += 1
            continue
        if (
            len(result) >= POLICY["limits"]["events"]
            or len(group) > POLICY["limits"]["array_bytes"] // 32
        ):
            raise EventError("regional_event_budget")
        cells = sorted({(y, x) for t, y, x in group})
        geometry = mapping(
            unary_union(
                [
                    box(
                        float(lon[x] - 0.125),
                        float(lat[y] - 0.125),
                        float(lon[x] + 0.125),
                        float(lat[y] + 0.125),
                    )
                    for y, x in cells
                ]
            )
        )
        weights = np.array([areas[y] for t, y, x in group])
        values = np.array([intensity[t, y, x] for t, y, x in group])
        maximum = int(np.argmax(values))
        start, end = group[0][0], group[-1][0]
        result.append(
            {
                "kind": "surface_thermal_candidate",
                "variable": "sst_c",
                "units": "degree_Celsius",
                "start": dates[start],
                "end": dates[end],
                "duration_days": end - start + 1,
                "persistence_days": longest,
                "geometry": geometry,
                "support_kind": "native_grid_cells",
                "cell_count": len(cells),
                "cell_days": len(group),
                "maximum_intensity": float(values.max()),
                "mean_intensity": float(np.average(values, weights=weights)),
                "peak_date": dates[group[maximum][0]],
                "maximum_category": int(max(category[t, y, x] for t, y, x in group)),
                "left_censored": start == 0
                or not all(
                    observed[t, y, x]
                    for t in range(max(0, start - 2), start)
                    for y, x in cells
                ),
                "right_censored": end >= len(dates) - 3
                or not all(
                    observed[t, y, x]
                    for t in range(end + 1, min(len(dates), end + 3))
                    for y, x in cells
                ),
                "daily_support": [
                    {
                        "day": dates[t],
                        "cells": len(per_day[t]),
                        "area_km2": float(sum(areas[y] for y, x in per_day[t])),
                        "observed_cells": int(observed[t].sum()),
                        "mean_intensity": float(
                            np.average(
                                [intensity[t, y, x] for y, x in per_day[t]],
                                weights=[areas[y] for y, x in per_day[t]],
                            )
                        ),
                        "maximum_intensity": float(
                            max(intensity[t, y, x] for y, x in per_day[t])
                        ),
                        "supported_regional_day": t in supported_dates,
                    }
                    for t in sorted(per_day)
                ],
                "members": [[int(t), int(y), int(x)] for t, y, x in group],
                "release_approved": False,
            }
        )
    return result, rejected


def detect_thermal(values, dates, lat, lon, baseline):
    a = daily(values, dates, lat, lon, POLICY["limits"]["detection_days"])
    if day(dates[0]).year <= POLICY["baseline_years"][1]:
        raise EventError("detection_overlaps_fixed_baseline")
    index = [seasonal_index(d) for d in dates]
    mean, threshold = baseline["mean"][index], baseline["threshold"][index]
    if mean.shape != a.shape or threshold.shape != a.shape:
        raise EventError("baseline_grid_mismatch")
    qualified, above, observed = [np.zeros(a.shape, dtype=bool) for _ in range(3)]
    intervals = []
    for y in range(len(lat)):
        for x in range(len(lon)):
            qualified[:, y, x], above[:, y, x], observed[:, y, x], runs = (
                cell_intervals(a[:, y, x], mean[:, y, x], threshold[:, y, x])
            )
            intervals.extend([[y, x, start, end] for start, end in runs])
    if len(intervals) > POLICY["limits"]["intervals"]:
        raise EventError("cell_interval_budget")
    intensity = a - mean
    category = np.zeros(a.shape, dtype="uint8")
    ratio = np.divide(
        intensity, threshold - mean, out=np.zeros(a.shape), where=observed
    )
    category[above] = np.minimum(4, np.floor(ratio[above])).astype("uint8")
    events, rejected = group_cells(
        qualified, intensity, category, dates, lat, lon, observed
    )
    return {
        "kind": "surface_thermal",
        "method_version": METHOD,
        "status": "diagnostic",
        "start": dates[0],
        "end": dates[-1],
        "dates": dates,
        "baseline_years": POLICY["baseline_years"],
        "extent": [
            float(lon[0] - 0.125),
            float(lat[0] - 0.125),
            float(lon[-1] + 0.125),
            float(lat[-1] + 0.125),
        ],
        "shape": list(a.shape),
        "events": events,
        "cell_intervals": intervals,
        "rejected_small_components": rejected,
        "qualified_cell_days": int(qualified.sum()),
        "coverage": [
            {
                "day": d,
                "observed_cells": int(observed[t].sum()),
                "unknown_cells": int(observed[t].size - observed[t].sum()),
                "above_threshold_cells": int(above[t].sum()),
                "qualified_cells": int(qualified[t].sum()),
            }
            for t, d in enumerate(dates)
        ],
        "release_approved": False,
        "limitations": POLICY["limitations"],
    }


def group_profiles(points):
    if len(points) > POLICY["limits"]["profile_points"]:
        raise EventError("profile_group_budget")
    identities = set()
    times = []
    for p in points:
        number(p["latitude"], -90, 90)
        number(p["longitude"], -180, 180)
        number(p["percentile"], POLICY["profile_percentile"], 100)
        number(p["intensity"], 0, 1e12)
        day(p["day"])
        instant = utc(p["observed_at"])
        if (
            instant.date().isoformat() != p["day"]
            or p["variable"] not in ("temperature_c", "practical_salinity")
            or p["direction"] not in ("positive", "negative")
        ):
            raise EventError("invalid_profile_event_support")
        times.append(instant.timestamp())
        key = (p["profile_id"], p["variable"])
        if key in identities:
            raise EventError("duplicate_profile_support")
        identities.add(key)
    remaining, groups = set(range(len(points))), []
    while remaining:
        i = min(remaining)
        remaining.remove(i)
        stack, members = [i], []
        while stack:
            j = stack.pop()
            members.append(j)
            a = points[j]
            neighbors = []
            for k in sorted(remaining):
                b = points[k]
                if a["variable"] != b["variable"] or a["direction"] != b["direction"]:
                    continue
                if (
                    abs(times[j] - times[k]) <= POLICY["profile_time_gap_hours"] * 3600
                    and haversine(
                        (a["latitude"], a["longitude"]), (b["latitude"], b["longitude"])
                    )
                    <= POLICY["profile_radius_km"]
                ):
                    neighbors.append(k)
            remaining.difference_update(neighbors)
            stack.extend(neighbors)
        support = [points[j] for j in sorted(members)]
        dates = sorted({p["day"] for p in support})
        regional = (
            len(support) >= POLICY["profile_min_profiles"]
            and len({p["platform_id"] for p in support})
            >= POLICY["profile_min_platforms"]
            and len(dates) >= POLICY["profile_min_dates"]
            and (day(dates[-1]) - day(dates[0])).days >= 2
        )
        groups.append(
            {
                "kind": "regional_profile_candidate"
                if regional
                else "isolated_profile_anomalies",
                "variable": support[0]["variable"],
                "direction": support[0]["direction"],
                "start": dates[0],
                "end": dates[-1],
                "duration_days": (day(dates[-1]) - day(dates[0])).days + 1,
                "persistence_days": len(dates),
                "profile_count": len(support),
                "platform_count": len({p["platform_id"] for p in support}),
                "support_kind": "observed_profile_points",
                "geometry": {
                    "type": "MultiPoint",
                    "coordinates": [[p["longitude"], p["latitude"]] for p in support],
                },
                "units": "dimensionless weighted squared standardized residual",
                "maximum_intensity": max(p["intensity"] for p in support),
                "mean_intensity": sum(p["intensity"] for p in support) / len(support),
                "members": support,
                "coverage_state": "sparse_point_support_unknown_between_observations",
                "release_approved": False,
            }
        )
    if len(groups) > POLICY["limits"]["events"]:
        raise EventError("profile_component_budget")
    return groups


def event_key(value):
    return hashlib.sha256(canonical(value)).hexdigest()
