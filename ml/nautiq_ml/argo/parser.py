"""Original-level R/A/D core and S-profile parsing with per-parameter QC."""

import hashlib
import json
import re
from datetime import datetime, timezone

import gsw
import netCDF4
import numpy as np

NORMALIZER_VERSION = "argo-original-levels-v1"
QC_VERSION = "argo-display-1-v1"
DEPTH_VERSION = f"TEOS-10-gsw-{gsw.__version__}"


class InvalidProfile(ValueError):
    pass


def text(value):
    # Preserve masked padding as spaces, so sampling-scheme words do not merge.
    a = np.ma.asarray(value)
    return "".join(
        " " if masked else (v.decode("ascii") if isinstance(v, bytes) else str(v))
        for v, masked in zip(
            a.data.reshape(-1), np.ma.getmaskarray(a).reshape(-1), strict=True
        )
    ).strip()


def scalar(ds, name, i):
    if name not in ds.variables:
        raise InvalidProfile("missing_" + name.lower())
    return ds[name][i]


def parameter(ds, p, i, mode, n):
    key = p if mode == "R" else p + "_ADJUSTED"
    flag = key + "_QC"
    if key not in ds.variables or flag not in ds.variables:
        return [None] * n, [""] * n, ["missing_selected_field"] * n, key
    units = getattr(ds[key], "units", "").lower().strip()
    allowed = {
        "PRES": {"decibar", "decibars", "dbar"},
        "TEMP": {"degree_celsius", "degrees_celsius", "degree_c", "degc"},
        "PSAL": {"psu", "pss-78", "1", "dimensionless"},
    }
    if units not in allowed[p]:
        raise InvalidProfile(p.lower() + "_units")
    values = np.ma.asarray(ds[key][i], dtype=float).filled(np.nan)
    flags = [text(x) for x in ds[flag][i]]
    if len(values) != n or len(flags) != n:
        raise InvalidProfile("parameter_shape")
    bounds = {"PRES": (0, 12000), "TEMP": (-3, 45), "PSAL": (0, 42)}[p]
    accepted, reasons = [], []
    for value, qc in zip(values, flags, strict=True):
        reason = (
            ""
            if qc == "1" and np.isfinite(value) and bounds[0] <= value <= bounds[1]
            else ("source_qc_not_1" if qc != "1" else "missing_or_out_of_range")
        )
        accepted.append(float(value) if not reason else None)
        reasons.append(reason)
    return accepted, flags, reasons, key


def parse(path):
    profiles, rejected, qc_rejections = [], [], []
    with netCDF4.Dataset(path) as ds:
        if "N_PROF" not in ds.dimensions or "N_LEVELS" not in ds.dimensions:
            raise InvalidProfile("missing_dimensions")
        nprof, nlevels = len(ds.dimensions["N_PROF"]), len(ds.dimensions["N_LEVELS"])
        if (
            not 1 <= nprof <= 64
            or not 1 <= nlevels <= 10000
            or nprof * nlevels > 100000
        ):
            raise InvalidProfile("dimension_budget")
        datatype = text(ds["DATA_TYPE"][:]) if "DATA_TYPE" in ds.variables else ""
        if "profile" not in datatype.lower() or "B-Argo" in datatype:
            raise InvalidProfile("unsupported_non_core_profile")
        updated = (
            datetime.strptime(text(ds["DATE_UPDATE"][:]), "%Y%m%d%H%M%S")
            .replace(tzinfo=timezone.utc)
            .isoformat()
        )
        for i in range(nprof):
            try:
                platform = text(scalar(ds, "PLATFORM_NUMBER", i))
                cycle = scalar(ds, "CYCLE_NUMBER", i)
                if np.ma.is_masked(cycle) or not re.fullmatch(r"[0-9]{5,8}", platform):
                    raise InvalidProfile("native_identity")
                cycle = int(cycle)
                direction, mode = (
                    text(scalar(ds, "DIRECTION", i)),
                    text(scalar(ds, "DATA_MODE", i)),
                )
                if (
                    cycle < 0
                    or direction not in {"A", "D"}
                    or mode not in {"R", "A", "D"}
                ):
                    raise InvalidProfile("native_identity_or_mode")
                if (
                    text(scalar(ds, "POSITION_QC", i)) != "1"
                    or text(scalar(ds, "JULD_QC", i)) != "1"
                ):
                    raise InvalidProfile("position_or_time_qc")
                lat, lon, juld = [
                    scalar(ds, p, i) for p in ("LATITUDE", "LONGITUDE", "JULD")
                ]
                if (
                    any(
                        np.ma.is_masked(x) or not np.isfinite(x)
                        for x in (lat, lon, juld)
                    )
                    or not -90 <= lat <= 90
                    or not -180 <= lon <= 360
                ):
                    raise InvalidProfile("position_or_time_invalid")
                lat, lon = float(lat), (float(lon) + 180) % 360 - 180
                calendar = getattr(ds["JULD"], "calendar", "standard")
                if calendar not in {"standard", "gregorian", "proleptic_gregorian"}:
                    raise InvalidProfile("unsupported_calendar")
                date = netCDF4.num2date(
                    juld,
                    ds["JULD"].units,
                    calendar=calendar,
                    only_use_cftime_datetimes=False,
                )
                observed = datetime(
                    date.year,
                    date.month,
                    date.day,
                    date.hour,
                    date.minute,
                    date.second,
                    tzinfo=timezone.utc,
                )
                if observed > datetime.now(timezone.utc):
                    raise InvalidProfile("future_observation")
                scheme = text(scalar(ds, "VERTICAL_SAMPLING_SCHEME", i))
                if not scheme:
                    raise InvalidProfile("sampling_scheme_missing")
                modes = {p: mode for p in ("PRES", "TEMP", "PSAL")}
                if "PARAMETER_DATA_MODE" in ds.variables:
                    if "STATION_PARAMETERS" not in ds.variables:
                        raise InvalidProfile("parameter_modes_without_names")
                    for name, pmode in zip(
                        ds["STATION_PARAMETERS"][i],
                        ds["PARAMETER_DATA_MODE"][i],
                        strict=True,
                    ):
                        p = text(name)
                        if p in modes:
                            m = text(pmode)
                            if m not in {"R", "A", "D"}:
                                raise InvalidProfile("parameter_mode_invalid")
                            modes[p] = m
                values = {p: parameter(ds, p, i, modes[p], nlevels) for p in modes}
                for variable in modes:
                    reasons = values[variable][2]
                    for reason in sorted(set(reasons) - {""}):
                        indices = [j for j, r in enumerate(reasons) if r == reason]
                        qc_rejections.append(
                            {
                                "profile_index": i,
                                "variable": variable,
                                "rule_id": "parameter.source_qc_units_range",
                                "reason_code": reason,
                                "rejected_count": len(indices),
                                "context": {
                                    "source_level_indices": indices[:100],
                                    "indices_truncated": len(indices) > 100,
                                    "selected_field": values[variable][3],
                                    "parameter_mode": modes[variable],
                                },
                            }
                        )
                levels = []
                for j, pres in enumerate(values["PRES"][0]):
                    if pres is None:
                        continue
                    flags = {p: values[p][1][j] for p in modes}
                    flags.update({p + "_selected_field": values[p][3] for p in modes})
                    flags["source_level_index"] = str(j)
                    # Adjustment uncertainties remain recoverable in the immutable raw file.
                    levels.append(
                        {
                            "pressure_dbar": pres,
                            "depth_m": float(-gsw.z_from_p(pres, lat)),
                            "temperature_c": values["TEMP"][0][j],
                            "practical_salinity": values["PSAL"][0][j],
                            "missing_reasons": {
                                p: values[p][2][j]
                                for p in ("TEMP", "PSAL")
                                if values[p][2][j]
                            },
                            "qc_flags": flags,
                        }
                    )
                levels.sort(key=lambda row: row["pressure_dbar"])
                if any(
                    a["pressure_dbar"] == b["pressure_dbar"]
                    for a, b in zip(levels, levels[1:])
                ):
                    raise InvalidProfile("duplicate_pressure_levels")
                if not levels or not any(
                    v["temperature_c"] is not None
                    or v["practical_salinity"] is not None
                    for v in levels
                ):
                    raise InvalidProfile("no_accepted_levels")
                # Sampling scheme plus native N_PROF discriminator keeps secondary profiles distinct.
                native = f"argo|{platform}|{cycle}|{direction}|{scheme.split(chr(58))[0].strip().lower()}|{i}"
                profiles.append(
                    {
                        "native_key": native,
                        "platform_id": platform,
                        "cycle_number": cycle,
                        "direction": direction,
                        "sampling_scheme": scheme,
                        "profile_index": i,
                        "source_updated_at": updated,
                        "observed_at": observed.isoformat(),
                        "latitude": lat,
                        "longitude": lon,
                        "data_mode": mode,
                        "parameter_modes": modes,
                        "qc_version": QC_VERSION,
                        "normalizer_version": NORMALIZER_VERSION,
                        "depth_conversion_version": DEPTH_VERSION,
                        "levels": levels,
                    }
                )
            except (InvalidProfile, KeyError, ValueError, TypeError) as error:
                rejected.append(
                    {
                        "profile_index": i,
                        "reason_code": str(error)
                        if isinstance(error, InvalidProfile)
                        else "invalid_metadata",
                    }
                )
    return {
        "profiles": profiles,
        "rejections": rejected,
        "qc_rejections": qc_rejections,
    }


def revision_digest(profile, raw_sha):
    manifest = {"raw_sha256": raw_sha, "profile": profile}
    return hashlib.sha256(
        json.dumps(
            manifest, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
