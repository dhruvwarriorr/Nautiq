"""One explicit rectilinear grid contract; no implicit coastal extrapolation."""

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

POLICY_PATH = next(
    p
    for p in (
        Path("/fields.json"),
        Path(__file__).parents[3] / "packages/source-catalog/fields.json",
    )
    if p.exists()
)
POLICY = json.loads(POLICY_PATH.read_text())
VERSION = POLICY["normalizer"]


class FieldError(ValueError):
    """A stable, public reason without provider payloads or credentials."""


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def utc(value):
    if not isinstance(value, str) or len(value) > 40:
        raise FieldError("invalid_utc_time")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise FieldError("invalid_utc_time") from None
    if result.tzinfo is None or result.utcoffset() is None:
        raise FieldError("timezone_required")
    return result.astimezone(timezone.utc)


def iso(value):
    return (
        datetime.fromtimestamp(float(value), timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def number(value, lo, hi, code="invalid_coordinate"):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not lo <= value <= hi
    ):
        raise FieldError(code)
    return float(value)


def validate_grid(
    lat, lon, times, arrays, product_id, cycle, valid_start=None, valid_end=None
):
    if product_id not in POLICY["products"]:
        raise FieldError("unknown_product")
    spec = POLICY["products"][product_id]
    lat, lon, times = [np.asarray(a, dtype="float64") for a in (lat, lon, times)]
    if any(a.ndim != 1 or not np.isfinite(a).all() for a in (lat, lon, times)):
        raise FieldError("unsupported_grid_or_calendar")
    if (
        not 2 <= len(lat) <= 2000
        or not 2 <= len(lon) <= 2000
        or not 1 <= len(times) <= POLICY["limits"]["max_times"]
    ):
        raise FieldError("grid_budget")
    if (
        np.prod((len(times), len(lat), len(lon))) * len(arrays)
        > POLICY["limits"]["cells"]
    ):
        raise FieldError("grid_budget")
    # Retain a continuous longitude branch even for regions across the dateline.
    lon = np.rad2deg(np.unwrap(np.deg2rad(lon)))
    lat_order, lon_order, time_order = [np.argsort(a) for a in (lat, lon, times)]
    lat, lon, times = lat[lat_order], lon[lon_order], times[time_order]
    for a in (lat, lon):
        steps = np.diff(a)
        if (
            not (steps > 0).all()
            or not np.allclose(steps, steps[0], rtol=2e-3, atol=1e-4)
            or steps[0] > 1
        ):
            raise FieldError("non_regular_or_duplicate_grid")
    if lat[0] < -90 or lat[-1] > 90 or lon[-1] - lon[0] > 180:
        raise FieldError("unsupported_global_or_coordinate_grid")
    if (
        not (np.diff(times) > 0).all()
        or (np.diff(times) > spec["max_time_gap_hours"] * 3600 + 1).any()
    ):
        raise FieldError("duplicate_or_gapped_times")
    if not (0 < times[0] <= times[-1] < 7258118400):
        raise FieldError("unsupported_calendar")
    cycle_seconds = utc(cycle).timestamp() if cycle else None
    if (spec["kind"] == "forecast") != (cycle_seconds is not None):
        raise FieldError("forecast_cycle_required_analysis_cycle_absent")
    if cycle_seconds is not None and (
        times[0] < cycle_seconds or times[-1] > cycle_seconds + 192 * 3600
    ):
        raise FieldError("cycle_or_lead_mismatch")
    if set(arrays) != set(spec["variables"]):
        raise FieldError("incomplete_or_unknown_variables")
    cleaned = {}
    for name, array in arrays.items():
        a = np.asarray(np.ma.filled(array, np.nan), dtype="float32")
        if a.shape != (len(times), len(lat), len(lon)):
            raise FieldError("dimension_mismatch")
        a = a[np.ix_(time_order, lat_order, lon_order)]
        low, high = POLICY["variables"][name]["bounds"]
        if np.isinf(a).any() or ((np.isfinite(a)) & ((a < low) | (a > high))).any():
            raise FieldError("variable_bounds")
        cleaned[name] = np.ascontiguousarray(a)
    for prefix in ("wind", "current"):
        east, north = prefix + "_east_m_s", prefix + "_north_m_s"
        if east in cleaned and north in cleaned:
            missing = np.isnan(cleaned[east]) | np.isnan(cleaned[north])
            cleaned[east][missing] = np.nan
            cleaned[north][missing] = np.nan
    derived = []
    if "wind_east_m_s" in cleaned:
        derived += ["wind_speed_m_s", "wind_direction_from_deg"]
    if "current_east_m_s" in cleaned:
        derived += ["current_speed_m_s", "current_direction_to_deg"]
    start = utc(valid_start).timestamp() if valid_start else times[0]
    end = utc(valid_end).timestamp() if valid_end else times[-1]
    if (
        start > times[0]
        or end < times[-1]
        or end < start
        or (spec["kind"] == "forecast" and (start != times[0] or end != times[-1]))
    ):
        raise FieldError("invalid_valid_window")
    if spec["kind"] == "analysis" and (
        len(times) != 1 or end - start != 86400 or not start <= times[0] < end
    ):
        raise FieldError("daily_analysis_window_required")
    metadata = {
        "product_id": product_id,
        **spec,
        "cycle": iso(cycle_seconds) if cycle_seconds is not None else None,
        "valid_time_start": iso(start),
        "valid_time_end": iso(end),
        "times": [iso(t) for t in times],
        "extent": [float(lon[0]), float(lat[0]), float(lon[-1]), float(lat[-1])],
        "resolution": {
            "longitude_degrees": float(np.diff(lon)[0]),
            "latitude_degrees": float(np.diff(lat)[0]),
        },
        "crs": "EPSG:4326",
        "grid": "rectilinear",
        "shape": [len(times), len(lat), len(lon)],
        "normalizer_version": VERSION,
        "sampling_version": POLICY["sampling"],
        "derived_variables": derived,
        "variable_metadata": {v: POLICY["variables"][v] for v in [*cleaned, *derived]},
        "mask_counts": {v: int(np.isnan(a).sum()) for v, a in cleaned.items()},
        "limitations": POLICY["limitations"],
        "release_approved": False,
    }
    return lat, lon, times, cleaned, metadata


def freshness(metadata, now=None):
    now = now or datetime.now(timezone.utc)
    base = utc(metadata["cycle"] or metadata["valid_time_end"])
    age = (now - base).total_seconds() / 3600
    return "stale" if age > metadata["max_age_hours"] else "available"


def haversine(a, b):
    la, lb = math.radians(a[0]), math.radians(b[0])
    dlon = math.radians((b[1] - a[1] + 180) % 360 - 180)
    h = (
        math.sin((lb - la) / 2) ** 2
        + math.cos(la) * math.cos(lb) * math.sin(dlon / 2) ** 2
    )
    return 6371.0088 * 2 * math.asin(min(1, math.sqrt(h)))
