"""Phase 0: acquire real samples, replay offline, and report unproven gates."""

import argparse
import hashlib
import importlib.metadata
import json
import platform
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import xarray as xr

from .acquire import ProbeError, Store
from .argo import QC_VERSION, discover, parse_profile
from .science import benchmark


def validate_config(config):
    if config["schema_version"] != 1:
        raise ValueError("unsupported_catalog_schema")
    d = config["domain"]
    if not (
        -90 <= d["south"] < d["north"] <= 90 and -180 <= d["west"] < d["east"] <= 180
    ):
        raise ValueError("invalid_domain; dateline domains require two explicit boxes")
    b, s = config["baseline"], config["splits"]
    if (
        not b["start_year"]
        <= s["train_end"]
        < s["tune_end"]
        < s["calibration_end"]
        < b["end_year"]
    ):
        raise ValueError("invalid_split_boundaries")
    depths = config["standard_depths_m"]
    if (
        not depths
        or any(not np.isfinite(z) or z < 0 for z in depths)
        or any(a >= b for a, b in zip(depths, depths[1:]))
    ):
        raise ValueError("invalid_depth_grid")
    if not 4 <= config["max_profiles"] <= 192 or config["max_interpolation_gap_m"] <= 0:
        raise ValueError("invalid_sample_budget_or_gap")
    if any(not isinstance(v, int) or v <= 0 for v in config["limits"].values()):
        raise ValueError("invalid_acquisition_limits")
    if len({s["id"] for s in config["sources"]}) != len(config["sources"]):
        raise ValueError("duplicate_source_id")
    required = {
        "argo_gdac",
        "noaa_oisst",
        "open_meteo_marine",
        "open_meteo_weather",
        "incois_advisories",
    }
    if not required <= {s["id"] for s in config["sources"]}:
        raise ValueError("missing_required_source")


def validate_forecast(path, source, received_at):
    data = json.loads(path.read_text())
    expected = (
        {"wave_height": "m", "wave_period": "s", "wave_direction": "°"}
        if source["kind"] == "wave_forecast"
        else {
            "wind_speed_10m": "m/s",
            "wind_gusts_10m": "m/s",
            "wind_direction_10m": "°",
        }
    )
    hours, units = data.get("hourly", {}), data.get("hourly_units", {})
    times = hours.get("time", [])
    if len(times) < 24 or any(units.get(key) != unit for key, unit in expected.items()):
        raise ProbeError("forecast_units_or_horizon")
    if data.get("utc_offset_seconds") != 0:
        raise ProbeError("forecast_not_utc")
    parsed = [datetime.fromisoformat(t).replace(tzinfo=timezone.utc) for t in times]
    if any((b - a).total_seconds() != 3600 for a, b in zip(parsed, parsed[1:])):
        raise ProbeError("forecast_time_gap_or_duplicate")
    missing = {}
    for key in expected:
        series = hours.get(key, [])
        if len(series) != len(times):
            raise ProbeError("forecast_shape")
        finite = [
            v
            for v in series
            if isinstance(v, (float, int))
            and not isinstance(v, bool)
            and np.isfinite(v)
        ]
        if not finite:
            raise ProbeError(f"forecast_missing_{key}")
        if len(finite) != sum(v is not None for v in series):
            raise ProbeError("forecast_invalid_value")
        if any(v < 0 or ("direction" in key and v > 360) for v in finite):
            raise ProbeError("forecast_range")
        missing[key] = len(times) - len(finite)
    lat, lon = data.get("latitude"), data.get("longitude")
    if (
        not isinstance(lat, (float, int))
        or not isinstance(lon, (float, int))
        or not np.isfinite(lat + lon)
    ):
        raise ProbeError("forecast_missing_coordinates")
    # Coordinate shifts are recorded; this is not evidence for arbitrary coastal routes.
    received = datetime.fromisoformat(received_at)
    horizon = (parsed[-1] - received).total_seconds() / 3600
    if horizon <= 0:
        raise ProbeError("forecast_expired_at_acquisition")
    return {
        "schema_valid": True,
        "sample_coordinates": {"latitude": lat, "longitude": lon},
        "valid_start": times[0] + "Z",
        "valid_end": times[-1] + "Z",
        "hours": len(times),
        "future_horizon_hours_at_acquisition": horizon,
        "missing_hours": missing,
        "forecast_cycle": None,
        "cycle_provenance_confirmed": False,
        "limitation": "Point forecast accessible; model initialization time absent. Not accepted for reproducible trip verdicts.",
    }


def validate_sst(path, config):
    with xr.open_dataset(path, engine="netcdf4") as data:
        if "sst" not in data or not {"lat", "lon", "time"} <= set(data.coords):
            raise ProbeError("sst_schema")
        if data.sst.attrs.get("units", "").lower() not in (
            "celsius",
            "degree_celsius",
            "degrees_celsius",
        ):
            raise ProbeError("sst_units")
        if data.sst.size > 5_000_000 or data.sizes["time"] != 1:
            raise ProbeError("sst_dimension_budget")
        d = config["domain"]
        # OISST longitudes use [0, 360); configured pilot box is positive.
        sample = data.sst.where(
            (data.lat >= d["south"])
            & (data.lat <= d["north"])
            & (data.lon >= d["west"])
            & (data.lon <= d["east"]),
            drop=True,
        ).values
        valid = sample[np.isfinite(sample)]
        if not len(valid) or np.any((valid < -3) | (valid > 45)):
            raise ProbeError("sst_empty_or_implausible")
        return {
            "schema_valid": True,
            "valid_time": str(data.time.values[0]),
            "domain_valid_cells": int(len(valid)),
            "domain_missing_cells": int(sample.size - len(valid)),
            "range_c": [float(valid.min()), float(valid.max())],
            "role": "historical_blended_analysis",
            "limitation": "OISST blends satellite and in-situ data; not independent satellite truth or proof of current freshness.",
        }


def validate_advisory_index(path, source):
    body = path.read_bytes()
    if (
        len(body) > 2_000_000
        or b"<!DOCTYPE" in body.upper()
        or b"<!ENTITY" in body.upper()
    ):
        raise ProbeError("advisory_xml_budget_or_entity")
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        raise ProbeError("advisory_xml_invalid") from None
    if root.tag != "rss" or root.find("channel") is None:
        raise ProbeError("advisory_index_schema")
    items = root.findall("./channel/item")
    if len(items) > 5000:
        raise ProbeError("advisory_index_item_budget")
    identifiers, dates, authors = set(), [], Counter()
    for item in items:
        guid, link = item.findtext("guid"), item.findtext("link")
        if not guid or guid in identifiers or not link:
            raise ProbeError("advisory_missing_or_duplicate_identity")
        identifiers.add(guid)
        parsed = urllib.parse.urlsplit(link)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in source["allowed_hosts"]
            or parsed.username
            or parsed.password
        ):
            raise ProbeError("advisory_link_not_allowed")
        try:
            dates.append(parsedate_to_datetime(item.findtext("pubDate")))
        except (TypeError, ValueError):
            raise ProbeError("advisory_publication_time") from None
        if dates[-1].tzinfo is None:
            raise ProbeError("advisory_time_missing_zone")
        # Author counts describe index content; they do not prove issuer coverage.
        authors[item.findtext("author") or "unknown"] += 1
    return {
        "schema_valid": True,
        "items": len(items),
        "newest_published_at": max(dates).isoformat() if dates else None,
        "distinct_author_labels": len(authors),
        "advisory_state": "unknown",
        "marine_completeness_confirmed": False,
        "limitation": "Official RSS index accessible; CAP validity/geometry/cancellations, marine coverage and operational completeness remain unverified. Empty feed is not known-none.",
    }


def atomic_json(path, value):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temp.replace(path)


def run(config, output, offline=False, on_progress=print):
    validate_config(config)
    output.mkdir(parents=True, exist_ok=True)
    store = Store(output, config["limits"], offline=offline)
    sources, rows, rejected = {}, [], Counter()
    discovery = {}
    for source in config["sources"]:
        on_progress(f"Probe {source['id']}", flush=True)
        result = {
            "kind": source["kind"],
            "license_state": source["license_state"],
            "production_approved": source["production_approved"],
            "terms_url": source["terms_url"],
            "attribution": source["attribution"],
        }
        if source["access"] == "unconfirmed":
            sources[source["id"]] = result | {
                "status": "blocked",
                "advisory_state": "unknown",
                "reason": "No verified machine-readable feed, completeness contract or redistribution permission; webpage reachability is not a feed probe.",
            }
            continue
        try:
            if source["kind"] == "profiles":
                path, receipt = store.fetch(
                    source["index_url"], source["allowed_hosts"]
                )
                files, discovery = discover(path, config)
                result["index_receipt"] = receipt
                result["discovery"] = discovery
                canonical = set()
                rejection_records = []
                for index, filename in enumerate(files):
                    if index % 12 == 0:
                        on_progress(
                            f"  Argo sample {index + 1}/{len(files)}", flush=True
                        )
                    receipt = None
                    try:
                        path, receipt = store.fetch(
                            source["base_url"] + filename, source["allowed_hosts"]
                        )
                        parsed = parse_profile(path, receipt, config)
                        key = parsed[0]["profile_key"]
                        if key in canonical:
                            rejected["duplicate_stable_profile"] += 1
                            continue
                        canonical.add(key)
                        rows.extend(parsed)
                    except (
                        ProbeError,
                        OSError,
                        ValueError,
                        KeyError,
                        IndexError,
                        AttributeError,
                        TypeError,
                        EOFError,
                        OverflowError,
                    ) as error:
                        reason = (
                            str(error)
                            if isinstance(error, ProbeError)
                            else type(error).__name__
                        )
                        rejected[reason] += 1
                        rejection_records.append(
                            {
                                "source_file": filename,
                                "sha256": receipt["sha256"] if receipt else None,
                                "reason": reason,
                            }
                        )
                result.update(
                    status="sample_validated" if rows else "blocked",
                    accepted_profiles=len(canonical),
                    qc_rejections=dict(rejected),
                    rejected_artifacts=rejection_records,
                )
            else:
                path, receipt = store.fetch(
                    source["sample_url"], source["allowed_hosts"]
                )
                if source["kind"] == "sst_analysis":
                    detail = validate_sst(path, config)
                elif source["kind"] == "advisory_index":
                    detail = validate_advisory_index(path, source)
                else:
                    detail = validate_forecast(path, source, receipt["received_at"])
                result.update(status="sample_validated", receipt=receipt, sample=detail)
        except (
            ProbeError,
            OSError,
            ValueError,
            KeyError,
            IndexError,
            AttributeError,
            TypeError,
            EOFError,
            OverflowError,
        ) as error:
            result.update(
                status="blocked",
                reason=str(error)
                if isinstance(error, ProbeError)
                else type(error).__name__,
            )
        sources[source["id"]] = result
    rows.sort(key=lambda r: (r["profile_key"], r["variable"], r["depth_m"]))
    dataset_path = output / "observations.parquet"
    if rows:
        pq.write_table(pa.Table.from_pylist(rows), dataset_path, compression="zstd")
    else:
        dataset_path.unlink(missing_ok=True)
    on_progress("Run train-only scientific benchmarks", flush=True)
    science = (
        benchmark(rows, config)
        if rows
        else {"status": "blocked", "reason": "no_accepted_profiles"}
    )
    snapshot = {
        "catalog_sha256": hashlib.sha256(
            json.dumps(config, sort_keys=True).encode()
        ).hexdigest(),
        "qc_version": QC_VERSION,
        "rows": len(rows),
        "profiles": len({r["profile_key"] for r in rows}),
        "parquet_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest()
        if rows
        else None,
        "split_profiles": dict(
            Counter(r["split"] for r in {r["profile_key"]: r for r in rows}.values())
        ),
        "profile_coverage_by_depth": dict(
            Counter(f"{r['variable']}:{r['depth_m']:g}" for r in rows)
        ),
        "selected_artifacts": sorted({r["revision_sha256"] for r in rows}),
        "code_sha256": hashlib.sha256(
            b"".join(p.read_bytes() for p in sorted(Path(__file__).parent.glob("*.py")))
        ).hexdigest(),
        "environment": {
            "python": platform.python_version(),
            **{
                p: importlib.metadata.version(p)
                for p in (
                    "numpy",
                    "scipy",
                    "scikit-learn",
                    "lightgbm",
                    "netCDF4",
                    "xarray",
                    "pyarrow",
                    "gsw",
                )
            },
        },
    }
    atomic_json(output / "catalog.json", config)
    argo_ok = sources["argo_gdac"]["status"] == "sample_validated"
    science_ok = bool(science.get("variables")) and all(
        v["status"] == "exploratory" for v in science["variables"].values()
    )
    gates = {
        "argo_slice_feasible": argo_ok,
        "scientific_prototype_executed": science_ok,
        "sst_sample_accessible": sources["noaa_oisst"]["status"] == "sample_validated",
        "wave_and_wind_samples_accessible": all(
            sources[s]["status"] == "sample_validated"
            for s in ("open_meteo_marine", "open_meteo_weather")
        ),
        "operational_source_cadence_validated": False,
        "trip_forecast_cycles_reproducible": False,
        "official_advisory_feed_verified": False,
        "production_licenses_approved": all(
            s["production_approved"] for s in config["sources"]
        ),
        "scientific_release_validated": False,
    }
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "offline_replay" if offline else "live_probe",
        "status": "ready" if all(gates.values()) else "partial",
        "gates": gates,
        "sources": sources,
        "snapshot": snapshot,
        "science": science,
        "download_bytes_this_run": store.downloaded,
        "limitations": [
            "Counts from a GDAC index are availability counts, not QC-passed training counts.",
            "One acquisition cannot establish cadence, uptime or coastal representativeness.",
            "No trip verdicts, official advisories, production model or event detector are released.",
        ],
    }
    atomic_json(output / "report.json", report)
    atomic_json(output / "snapshot.json", snapshot)
    lines = [
        "# Phase 0 feasibility evidence",
        "",
        f"Status: **{report['status']}**. Mode: {report['mode']}. Generated: {report['generated_at']}.",
        "",
        "## Gates",
        "",
        "| Gate | Result |",
        "| --- | --- |",
    ]
    lines += [
        f"| {key} | {'passed' if value else 'unproven / blocked'} |"
        for key, value in gates.items()
    ]
    lines += [
        "",
        "## Pilot snapshot",
        "",
        f"{snapshot['profiles']} profiles; {snapshot['rows']} rows; splits: {snapshot['split_profiles']}.",
        "",
        "## Sources",
        "",
    ]
    lines += [
        f"- {name}: {result['status']}. {result.get('reason', result.get('sample', {}).get('limitation', 'See structured report for QC and discovery counts.'))}"
        for name, result in sources.items()
    ]
    lines += ["", "## Limits", ""] + [
        f"- {value}" for value in report["limitations"] + science.get("limitations", [])
    ]
    lines += [
        "",
        "Full metrics, source receipts, hashes and environment are in `report.json` and `snapshot.json`.",
    ]
    (output / "report.md").write_text("\n".join(lines) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog", type=Path, default=Path("packages/source-catalog/phase0.json")
    )
    parser.add_argument("--output", type=Path, default=Path("artifacts/phase0"))
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Replay verified cached bytes; no network",
    )
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help="Exit 2 when any readiness gate is unproven",
    )
    args = parser.parse_args()
    try:
        report = run(json.loads(args.catalog.read_text()), args.output, args.offline)
    except (ValueError, OSError, KeyError) as error:
        parser.exit(1, f"Phase 0 failed: {type(error).__name__}\n")
    print(f"Phase 0 {report['status']}: {args.output / 'report.md'}")
    sys.exit(2 if args.require_ready and report["status"] != "ready" else 0)


if __name__ == "__main__":
    main()
