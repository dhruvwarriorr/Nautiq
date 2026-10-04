"""Offline experiment: do static coastal features (bathymetry, distance to coast) help? (design 03 sections 6, 25)

This does not create, select or serve a release. It acquires a real bathymetry source, derives the two
documented static features, refits the complete expected-mean pipeline (including the spatial and platform
independence audits) with and without them on identical rows, and reports the measured difference.
A conclusion of "supported" would only justify a new release proposal under the frozen gates.
"""

import argparse
import io
import json
import math
import re
import urllib.request
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import lightgbm as lgb
import numpy as np
import pyarrow.parquet as pq
from scipy.interpolate import RegularGridInterpolator
from scipy.spatial import cKDTree

from ..argo import evidence
from ..argo.storage import digest, put_immutable, read_object, store
from ..climatology import pipeline as climate
from . import features, model
from .model import VARIABLES, fit, load_policy

SOURCE = {
    "id": "noaa_ncei_etopo_2022_60s_bed",
    "url": "https://www.ngdc.noaa.gov/thredds/dodsC/global/ETOPO2022/60s/60s_bed_elev_netcdf/ETOPO_2022_v1_60s_N90W180_bed.nc",
    "doi": "10.25921/fd45-gt74",
    "attribution": "NOAA National Centers for Environmental Information. 2022: ETOPO 2022 15 Arc-Second Global Relief Model (60 arc-second bedrock product).",
    "vertical_datum": "EGM2008 height; positive up",
    "licence_state": "Terms and redistribution have not been reviewed by Nautiq. Use is limited to this offline experiment until they are.",
}
HOST = "www.ngdc.noaa.gov"
CELLS_PER_DEGREE = 60
STRIDE = 3
MARGIN_DEGREES = 3.0
MAX_BYTES = 64 * 1024 * 1024
STATIC_NAMES = ("bathymetry_m", "distance_to_coast_km")
EARTH_KM = 6371.0088
POLICY = {
    "version": "static-coastal-feature-experiment-v1",
    "min_relative_test_improvement_over_v1": 0.02,
    "max_subgroup_regressions_allowed": 0,
    "note": "Engineering criteria for whether a new release proposal is worth reviewing. They are not promotion gates.",
}


def code_hash():
    return digest(Path(__file__).read_bytes())


def request_url(domain):
    south = max(-90.0, domain["south"] - MARGIN_DEGREES)
    north = min(90.0, domain["north"] + MARGIN_DEGREES)
    west = max(-180.0, domain["west"] - MARGIN_DEGREES)
    east = min(180.0, domain["east"] + MARGIN_DEGREES)
    la, lb = (
        math.floor((south + 90) * CELLS_PER_DEGREE),
        math.ceil((north + 90) * CELLS_PER_DEGREE) - 1,
    )
    oa, ob = (
        math.floor((west + 180) * CELLS_PER_DEGREE),
        math.ceil((east + 180) * CELLS_PER_DEGREE) - 1,
    )
    query = f"z%5B{la}:{STRIDE}:{lb}%5D%5B{oa}:{STRIDE}:{ob}%5D"
    return f"{SOURCE['url']}.ascii?{query}", {
        "lat_index": [la, STRIDE, lb],
        "lon_index": [oa, STRIDE, ob],
    }


def fetch(domain):
    url, indices = request_url(domain)
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != HOST:
        raise ValueError("static_source_not_allowed")
    with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310 (host/scheme pinned above)
        data = response.read(MAX_BYTES + 1)
    if not 0 < len(data) <= MAX_BYTES:
        raise ValueError("static_source_budget")
    return url, indices, data


_ROW = re.compile(r"^\[(\d+)\],\s*(.*)$")


def parse_ascii(raw):
    """Parse an OPeNDAP ASCII grid: z.z rows, then z.lat and z.lon vectors."""
    text = raw.decode("ascii")
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.startswith("z.z["))
        shape = [int(v) for v in re.findall(r"\[(\d+)\]", lines[start])]
        rows = {}
        index = start + 1
        while index < len(lines) and (m := _ROW.match(lines[index])):
            rows[int(m.group(1))] = [float(v) for v in m.group(2).split(",")]
            index += 1
        lat = next(
            [float(v) for v in lines[i + 1].split(",")]
            for i, line in enumerate(lines)
            if line.startswith("z.lat[")
        )
        lon = next(
            [float(v) for v in lines[i + 1].split(",")]
            for i, line in enumerate(lines)
            if line.startswith("z.lon[")
        )
    except (StopIteration, ValueError) as error:
        raise ValueError("static_source_format") from error
    z = np.asarray([rows[i] for i in range(shape[0])], dtype=float)
    if z.shape != (shape[0], shape[1]) or len(lat) != shape[0] or len(lon) != shape[1]:
        raise ValueError("static_source_shape")
    z[z <= -99990] = np.nan
    return np.asarray(lat), np.asarray(lon), z


class Static:
    """Bathymetry (positive metres of water) and great-circle distance to the nearest land cell."""

    def __init__(self, lat, lon, z):
        self.lat, self.lon, self.z = lat, lon, z
        filled = np.where(np.isnan(z), 0.0, z)
        self._bilinear = RegularGridInterpolator(
            (lat, lon), filled, bounds_error=False, fill_value=np.nan
        )
        la, lo = np.meshgrid(lat, lon, indexing="ij")
        land = np.isfinite(z) & (z >= 0)
        self.land_cells = int(land.sum())
        if not self.land_cells:
            raise ValueError("static_source_without_land")
        self._tree = cKDTree(self._xyz(la[land], lo[land]))

    @staticmethod
    def _xyz(lat, lon):
        p, q = np.radians(lat), np.radians(lon)
        return np.column_stack(
            (np.cos(p) * np.cos(q), np.cos(p) * np.sin(q), np.sin(p))
        )

    def at(self, lat, lon):
        """Return (bathymetry_m, distance_to_coast_km) or None when the point is not open water here."""
        elevation = float(self._bilinear([[lat, lon]])[0])
        if not math.isfinite(elevation) or elevation >= 0:
            return None
        chord, _ = self._tree.query(self._xyz(np.array([lat]), np.array([lon])))
        km = 2 * EARTH_KM * math.asin(min(1.0, float(chord[0]) / 2))
        return -elevation, km


def augmented_vector(grid_static):
    base = features.vector

    def vector(row, policy):
        values = base(row, policy)
        extra = grid_static[(row["latitude"], row["longitude"])]
        return [*values, extra[0], extra[1]]

    return vector


@contextmanager
def patched(grid_static):
    original = (model.vector, model.NAMES)
    model.vector = augmented_vector(grid_static)
    model.NAMES = (*features.NAMES, *STATIC_NAMES)
    try:
        yield
    finally:
        model.vector, model.NAMES = original


def partition_summary(result):
    out = {}
    for v, report in result["variables"].items():
        if report["status"] != "trained":
            out[v] = {"status": report["status"], "reason": report.get("reason")}
            continue
        row = {"status": "trained", "profile_counts": report["profile_counts"]}
        for split in ("tune", "calibration", "test"):
            e = report["evaluation"][split]
            base = e["climatology"]["overall"]["profile_weighted_mae"]
            row[split] = {
                "profiles": e["climatology"]["overall"]["profiles"],
                "climatology_profile_mae": base,
                "lightgbm_profile_mae": e["lightgbm"]["overall"][
                    "profile_weighted_mae"
                ],
                "hgbr_profile_mae": e["hgbr"]["overall"]["profile_weighted_mae"],
            }
        row["promotion_reasons"] = report["promotion"]["reasons"]
        row["subgroup_regressions"] = sorted(
            r.split(":", 1)[1]
            for r in report["promotion"]["reasons"]
            if r.startswith("subgroup_regression:")
        )
        out[v] = row
    return out


def audit_summary(result):
    """Held-group profile MAE for every independence fold, including folds that could not be trained."""
    out = {}
    for fold in result["independence_audits"]:
        for v, item in fold["variables"].items():
            entry = {
                "fold": fold["fold"],
                "complement_profiles": fold["complement_profiles"],
                "held_profiles": fold["held_profiles"],
            }
            comparison = item.get("held_comparison")
            if comparison:
                for name in ("climatology", "hgbr", "lightgbm"):
                    entry[f"{name}_profile_mae"] = comparison[name][
                        "profile_weighted_mae"
                    ]
            else:
                entry["status"] = item.get("status", "not_trained")
                entry["reason"] = item.get("reason")
            out.setdefault(f"{fold['kind']}:{v}", []).append(entry)
    return out


def relative(new, old):
    return None if new is None or old is None or old <= 1e-12 else (old - new) / old


def verdict(baseline, extended):
    """Whether the pilot evidence is worth a release proposal. Never a promotion."""
    notes, supported = [], True
    for v in VARIABLES:
        a, b = baseline[v], extended[v]
        if a.get("status") != "trained" or b.get("status") != "trained":
            supported = False
            notes.append(f"{v}: not trained in both runs")
            continue
        gain = relative(
            b["test"]["lightgbm_profile_mae"], a["test"]["lightgbm_profile_mae"]
        )
        tune = relative(
            b["tune"]["lightgbm_profile_mae"], a["tune"]["lightgbm_profile_mae"]
        )
        notes.append(
            f"{v}: test profile MAE change {gain:+.1%}, tuning change {tune:+.1%} versus the v1 feature set"
            if gain is not None and tune is not None
            else f"{v}: not comparable"
        )
        if (
            gain is None
            or tune is None
            or gain < POLICY["min_relative_test_improvement_over_v1"]
            or tune <= 0
        ):
            supported = False
        if (
            len(b["subgroup_regressions"])
            > len(a["subgroup_regressions"])
            + POLICY["max_subgroup_regressions_allowed"]
        ):
            supported = False
            notes.append(f"{v}: more subgroup regressions than v1")
    return {
        "conclusion": "worth_a_release_proposal"
        if supported
        else "not_supported_by_pilot_evidence",
        "notes": notes,
        "criteria": POLICY,
        "interpretation": "Test years were inspected before. Even a positive result cannot approve a release; it can only justify a new proposal with an untouched audit block.",
    }


def gain_report(result_model):
    out = {}
    for v, m in result_model["models"].items():
        booster = lgb.Booster(model_str=m["model_text"])
        gains = booster.feature_importance(importance_type="gain")
        total = float(sum(gains)) or 1.0
        out[v] = {
            n: float(g) / total
            for n, g in zip(booster.feature_name(), gains, strict=True)
        }
    return out


def run(reference_id, policy_path, s3=None, offline_raw=None):
    policy = load_policy(policy_path)
    s3 = s3 or store()
    climate.verify(reference_id, s3)
    with climate.connect() as db:
        source = db.execute(
            "SELECT * FROM climatology_releases WHERE release_id=%s", (reference_id,)
        ).fetchone()
        snapshot = db.execute(
            "SELECT * FROM training_snapshots WHERE snapshot_id=%s",
            (source["snapshot_id"],),
        ).fetchone()
    reference = climate.release_bundle(source, s3)
    grid = pq.read_table(
        io.BytesIO(
            read_object(s3, source["grid_key"], source["grid_sha256"], limit=16777216)
        )
    ).to_pylist()
    for row in grid:
        row["coverage"] = json.loads(row["coverage"])
    features.validate_profiles(grid, snapshot["manifest"]["policy"]["training_policy"])
    domain = reference["policy"]["domain"]
    if offline_raw:
        raw, url, indices = Path(offline_raw).read_bytes(), "offline-replay", None
    else:
        url, indices, raw = fetch(domain)
    raw_sha = digest(raw)
    put_immutable(s3, f"lake/static/etopo2022-60s/{raw_sha}.ascii", raw)
    lat, lon, z = parse_ascii(raw)
    static = Static(lat, lon, z)
    attached, dropped = {}, 0
    keep = []
    for row in grid:
        key = (row["latitude"], row["longitude"])
        if key not in attached:
            attached[key] = static.at(*key)
        if attached[key] is None:
            dropped += 1
        else:
            keep.append(row)
    if not keep:
        raise ValueError("no_rows_with_static_features")
    static_for_rows = {k: v for k, v in attached.items() if v is not None}
    baseline = fit(keep, reference, policy)
    with patched(static_for_rows):
        extended = fit(keep, reference, policy)
    base_summary, ext_summary = partition_summary(baseline), partition_summary(extended)
    positions = list(static_for_rows.values())
    report = {
        "schema_version": 1,
        "method_version": POLICY["version"],
        "computed_at": datetime.now(UTC).isoformat(),
        "release_approved": False,
        "serving_effect": "none: no release is created, selected or served",
        "source": {
            **SOURCE,
            "request_url": url,
            "indices": indices,
            "raw_sha256": raw_sha,
            "raw_bytes": len(raw),
            "stride_cells": STRIDE,
            "resolution_degrees": STRIDE / CELLS_PER_DEGREE,
            "grid_shape": list(z.shape),
            "land_cells": static.land_cells,
            "object_key": f"lake/static/etopo2022-60s/{raw_sha}.ascii",
        },
        "inputs": {
            "reference_id": str(reference_id),
            "snapshot_id": str(source["snapshot_id"]),
            "grid_sha256": source["grid_sha256"],
            "policy_sha256": digest(evidence.canonical(policy)),
            "code_sha256": code_hash(),
            "rows": len(keep),
            "rows_dropped_not_open_water_at_source_resolution": dropped,
            "distinct_positions": len(static_for_rows),
        },
        "feature_ranges": {
            "bathymetry_m": [
                min(p[0] for p in positions),
                max(p[0] for p in positions),
            ],
            "distance_to_coast_km": [
                min(p[1] for p in positions),
                max(p[1] for p in positions),
            ],
        },
        "v1_features": baseline["feature_schema"]["names"],
        "v2_features": [*features.NAMES, *STATIC_NAMES],
        "v1": base_summary,
        "v2": ext_summary,
        "v1_audits": audit_summary(baseline),
        "v2_audits": audit_summary(extended),
        "v2_static_feature_gain_share": {
            v: {k: x for k, x in g.items() if k in STATIC_NAMES}
            for v, g in gain_report(extended).items()
        },
        "verdict": verdict(base_summary, ext_summary),
        "limitations": [
            "Same frozen grid and splits as the v1 release; the 2022-2024 test block was inspected before and cannot approve anything.",
            "A 0.05-degree bathymetry grid cannot resolve coastal shelves, reefs or channels; points that fall on land at source resolution were dropped from both runs.",
            "Distance to coast is measured to the nearest land cell centre of the same grid, so it is quantised to about 5 km.",
            "Profile-bootstrap intervals do not remove serial float dependence.",
            "Bathymetry and coast distance describe where a float is, not what the water is doing; gains may reflect sampling geography rather than skill.",
        ],
    }
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference-id", required=True)
    parser.add_argument("--policy", default="/expected-state.json")
    parser.add_argument("--raw")
    args = parser.parse_args()
    print(
        json.dumps(
            run(args.reference_id, args.policy, offline_raw=args.raw),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
