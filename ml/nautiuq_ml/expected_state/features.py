"""The same label-free, year-free reference features for fitting and inference."""

import hashlib
import math

from ..climatology.grid import instant, phase

VERSION = "ocean-reference-features-v1"
NAMES = (
    "latitude",
    "longitude",
    "depth_m",
    "season_sin",
    "season_cos",
    "season_sin2",
    "season_cos2",
    "basin_id",
)


def vector(row, policy):
    lat, lon, depth = (float(row[k]) for k in ("latitude", "longitude", "depth_m"))
    b = policy["domain"]
    if (
        not all(math.isfinite(v) for v in (lat, lon, depth))
        or not b["south"] <= lat <= b["north"]
        or not b["west"] <= lon <= b["east"]
        or depth not in policy["standard_depths_m"]
    ):
        raise ValueError("outside_reference_features")
    angle = phase(row["observed_at"])
    return [
        lat,
        lon,
        depth,
        math.sin(angle),
        math.cos(angle),
        math.sin(2 * angle),
        math.cos(2 * angle),
        int(lon >= policy["basin_boundary_longitude"]),
    ]


def validate_profiles(grid, training_policy):
    from ..argo.snapshots import split

    assignments = {}
    seen = set()
    for row in grid:
        stamp = instant(row["observed_at"]).isoformat()
        expected = split(stamp, training_policy)
        identity = (
            row["revision_sha256"],
            row["platform_id"],
            stamp,
            row["latitude"],
            row["longitude"],
            expected,
        )
        if (
            expected != row["split"]
            or assignments.setdefault(row["profile_id"], identity) != identity
        ):
            raise ValueError("profile_split_or_identity_leakage")
        key = (row["profile_id"], row["depth_m"])
        if key in seen:
            raise ValueError("duplicate_profile_depth")
        seen.add(key)


def fold(value, count):
    return int(hashlib.sha256(str(value).encode()).hexdigest()[:8], 16) % count


def audit_partitions(grid, policy, kind):
    # Group all depths/years of a stable profile/platform or cell together.
    if kind == "platform":
        return [
            (
                f"platform-{i}",
                [
                    r
                    for r in grid
                    if fold(r["platform_id"], policy["platform_folds"]) != i
                ],
                [
                    r
                    for r in grid
                    if fold(r["platform_id"], policy["platform_folds"]) == i
                ],
            )
            for i in range(policy["platform_folds"])
        ]
    width = policy["audit_cell_degrees"]

    def cell(r):
        return (math.floor(r["latitude"] / width), math.floor(r["longitude"] / width))

    results = []
    for i in range(policy["spatial_folds"]):
        cells = {cell(r) for r in grid if fold(cell(r), policy["spatial_folds"]) == i}
        held = [r for r in grid if cell(r) in cells]
        buffer = policy["spatial_buffer_degrees"]

        def excluded(r):
            return any(
                a * width - buffer <= r["latitude"] <= (a + 1) * width + buffer
                and b * width - buffer <= r["longitude"] <= (b + 1) * width + buffer
                for a, b in cells
            )

        results.append((f"spatial-{i}", [r for r in grid if not excluded(r)], held))
    return results
