"""Core Argo Phase 0 QC and bounded, stratified historical discovery."""

import csv
import gzip
import hashlib
import heapq
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone

import gsw
import netCDF4
import numpy as np

from .acquire import ProbeError

QC_VERSION = "argo-phase0-D1-v1"


def split_for_year(year, config):
    for name, boundary in (
        ("train", "train_end"),
        ("tune", "tune_end"),
        ("calibration", "calibration_end"),
    ):
        if year <= config["splits"][boundary]:
            return name
    return "test"


def discover(path, config):
    counts, strata, platforms = Counter(), defaultdict(list), set()
    total_bytes, seen = 0, set()
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        # Comments/header are retained in the immutable original.
        def bounded_lines():
            nonlocal total_bytes
            while line := stream.readline(4097):
                total_bytes += len(line.encode())
                if (
                    len(line) > 4096
                    or total_bytes > config["limits"]["max_index_expanded_bytes"]
                ):
                    raise ProbeError("index_expansion_limit")
                if not line.startswith("#"):
                    yield line

        for record in csv.DictReader(bounded_lines()):
            counts["index_rows"] += 1
            try:
                lat, lon = float(record["latitude"]), float(record["longitude"])
                date = datetime.strptime(record["date"], "%Y%m%d%H%M%S").replace(
                    tzinfo=timezone.utc
                )
                filename = record["file"]
                parts = filename.split("/")
                if (
                    len(parts) != 4
                    or parts[2] != "profiles"
                    or not re.fullmatch(r"[A-Za-z0-9_]+\.nc", parts[3])
                ):
                    raise ValueError
                if not re.fullmatch(r"[a-z]+", parts[0]) or not re.fullmatch(
                    r"\d{7}", parts[1]
                ):
                    raise ValueError
                if not math.isfinite(lat + lon) or not (
                    -90 <= lat <= 90 and -180 <= lon <= 180
                ):
                    raise ValueError
            except (KeyError, ValueError, TypeError):
                counts["invalid_index_rows"] += 1
                continue
            domain = config["domain"]
            if not (
                domain["south"] <= lat <= domain["north"]
                and domain["west"] <= lon <= domain["east"]
            ):
                continue
            counts["domain_profiles_all_years"] += 1
            if not (
                config["baseline"]["start_year"]
                <= date.year
                <= config["baseline"]["end_year"]
            ):
                continue
            counts["baseline_domain_profiles"] += 1
            counts[f"year:{date.year}"] += 1
            counts[f"month:{date.month:02}"] += 1
            counts[f"cell:{int(lat // 5)}:{int(lon // 5)}"] += 1
            platforms.add(parts[1])
            # Indexed D filename is discovery only; DATA_MODE is checked in bytes.
            if not parts[3].startswith("D"):
                continue
            if filename in seen:
                counts["duplicate_index_paths"] += 1
                continue
            seen.add(filename)
            counts["delayed_mode_candidates"] += 1
            split = split_for_year(date.year, config)
            basin = "arabian" if lon < 80 else "bay_bengal"
            key = (split, basin, date.month)
            score = int(
                hashlib.sha256(f"{config['seed']}:{filename}".encode()).hexdigest(), 16
            )
            heap = strata[key]
            # Two profiles per split/basin/month: at most 192 candidates.
            item = (-score, filename)
            if len(heap) < 2:
                heapq.heappush(heap, item)
            elif item > heap[0]:
                heapq.heapreplace(heap, item)
    selected = []
    # Round-robin strata: reducing the budget must not erase later splits.
    queues = [sorted(heap, reverse=True) for _, heap in sorted(strata.items())]
    for rank in range(2):
        selected.extend(queue[rank][1] for queue in queues if len(queue) > rank)
    counts["baseline_platforms"] = len(platforms)
    counts["selected_profiles"] = min(len(selected), config["max_profiles"])
    return selected[: config["max_profiles"]], dict(sorted(counts.items()))


def text(value):
    value = np.ma.asarray(value)
    # NetCDF pads fixed-length identifiers with masked NULs; padding is not a
    # missing identifier. Entirely masked QC characters still decode as empty.
    return "".join(
        x.decode("ascii") if isinstance(x, bytes) else str(x)
        for x in value.compressed()
    ).strip()


def values(var, profile=0):
    return np.ma.asarray(var[profile], dtype=float).filled(np.nan)


def interpolate(depth, measured, targets, max_gap):
    """No extrapolation; conflicting duplicate depths are not silently averaged."""
    valid = np.isfinite(depth) & np.isfinite(measured)
    depth, measured = depth[valid], measured[valid]
    order = np.argsort(depth, kind="stable")
    depth, measured = depth[order], measured[order]
    if len(depth) > 1 and np.any(np.diff(depth) == 0):
        raise ProbeError("duplicate_pressure_levels")
    result = np.full(len(targets), np.nan)
    for i, z in enumerate(targets):
        upper = np.searchsorted(depth, z)
        if upper < len(depth) and depth[upper] == z:
            result[i] = measured[upper]
        elif 0 < upper < len(depth) and depth[upper] - depth[upper - 1] <= max_gap:
            result[i] = np.interp(
                z, depth[upper - 1 : upper + 1], measured[upper - 1 : upper + 1]
            )
    return result


def parse_profile(path, receipt, config):
    rows = []
    with netCDF4.Dataset(path) as ds:
        required = [
            "DATA_MODE",
            "PLATFORM_NUMBER",
            "CYCLE_NUMBER",
            "DIRECTION",
            "JULD",
            "JULD_QC",
            "LATITUDE",
            "LONGITUDE",
            "POSITION_QC",
        ]
        if any(key not in ds.variables for key in required):
            raise ProbeError("missing_profile_metadata")
        if len(ds.dimensions["N_PROF"]) != 1:
            raise ProbeError("multiprofile_file_requires_phase2_parser")
        if "N_LEVELS" not in ds.dimensions or len(ds.dimensions["N_LEVELS"]) > 10000:
            raise ProbeError("profile_dimension_budget")
        if text(ds["DATA_MODE"][0]) != "D":
            raise ProbeError("not_delayed_mode")
        if text(ds["POSITION_QC"][0]) != "1" or text(ds["JULD_QC"][0]) != "1":
            raise ProbeError("position_or_time_qc")
        lat, lon = float(ds["LATITUDE"][0]), float(ds["LONGITUDE"][0])
        if not np.isfinite(lat + lon):
            raise ProbeError("invalid_position")
        domain = config["domain"]
        if not (
            domain["south"] <= lat <= domain["north"]
            and domain["west"] <= lon <= domain["east"]
        ):
            raise ProbeError("outside_configured_domain")
        date = netCDF4.num2date(
            ds["JULD"][0],
            ds["JULD"].units,
            only_use_cftime_datetimes=False,
            only_use_python_datetimes=True,
        )
        if not (
            config["baseline"]["start_year"]
            <= date.year
            <= config["baseline"]["end_year"]
        ):
            raise ProbeError("outside_baseline")
        platform = text(ds["PLATFORM_NUMBER"][0])
        direction = text(ds["DIRECTION"][0])
        cycle = int(ds["CYCLE_NUMBER"][0])
        if (
            not re.fullmatch(r"\d{7}", platform)
            or direction not in ("A", "D")
            or cycle < 0
        ):
            raise ProbeError("invalid_profile_identity")
        key = f"argo:{platform}:{cycle}:{direction}"
        required_pressure = ["PRES_ADJUSTED", "PRES_ADJUSTED_QC"]
        if any(key not in ds.variables for key in required_pressure):
            raise ProbeError("missing_adjusted_pressure")
        if ds["PRES_ADJUSTED"].units.lower() not in ("decibar", "decibars", "dbar"):
            raise ProbeError("pressure_units")
        pressure = values(ds["PRES_ADJUSTED"])
        pressure_qc = np.array([text(x) == "1" for x in ds["PRES_ADJUSTED_QC"][0]])
        pressure[~pressure_qc | (pressure < 0) | (pressure > 12000)] = np.nan
        depth = -gsw.z_from_p(pressure, lat)
        for variable, parameter, bounds, units in (
            (
                "temperature_c",
                "TEMP",
                (-3, 45),
                {"degree_celsius", "degrees_celsius", "degree_c", "degc"},
            ),
            (
                "practical_salinity",
                "PSAL",
                (0, 42),
                {"psu", "pss-78", "1", "dimensionless"},
            ),
        ):
            value_key, flag_key = f"{parameter}_ADJUSTED", f"{parameter}_ADJUSTED_QC"
            if value_key not in ds.variables or flag_key not in ds.variables:
                continue
            if ds[value_key].units.lower() not in units:
                raise ProbeError(f"{parameter.lower()}_units")
            y = values(ds[value_key])
            qc = np.array([text(x) == "1" for x in ds[flag_key][0]])
            y[~qc | (y < bounds[0]) | (y > bounds[1])] = np.nan
            sampled = interpolate(
                depth, y, config["standard_depths_m"], config["max_interpolation_gap_m"]
            )
            for z, value in zip(config["standard_depths_m"], sampled, strict=True):
                if np.isfinite(value):
                    rows.append(
                        {
                            "profile_key": key,
                            "platform_id": platform,
                            "revision_sha256": receipt["sha256"],
                            "observed_at": date.isoformat() + "Z",
                            "year": date.year,
                            "month": date.month,
                            "day_of_year": date.timetuple().tm_yday,
                            "latitude": lat,
                            "longitude": lon,
                            "depth_m": float(z),
                            "variable": variable,
                            "value": float(value),
                            "data_mode": "D",
                            "qc_version": QC_VERSION,
                            "split": split_for_year(date.year, config),
                            "source_url": receipt["url"],
                            "received_at": receipt["received_at"],
                        }
                    )
    if not rows:
        raise ProbeError("no_qc_passed_standard_levels")
    return rows
