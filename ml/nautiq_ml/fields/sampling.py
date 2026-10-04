"""Conservative bilinear/circular/vector sampling, timed great-circle routes and tiles."""

import io
import math
from datetime import datetime, timezone

import numpy as np
from PIL import Image

from .core import FieldError, POLICY, freshness, haversine, iso, number, utc


class FieldGrid:
    def __init__(self, group, metadata):
        self.group, self.metadata = group, metadata
        self.as_of = datetime.now(timezone.utc)
        self.chunks = {}
        self.chunk_bytes = 0
        self.lat, self.lon, self.times = [
            np.asarray(group[n][:]) for n in ("latitude", "longitude", "time")
        ]
        if any(
            a.ndim != 1 or not np.isfinite(a).all() or not (np.diff(a) > 0).all()
            for a in (self.lat, self.lon, self.times)
        ):
            raise FieldError("invalid_normalized_axes")
        if (
            [iso(t) for t in self.times] != metadata["times"]
            or list(self.lat[[0, -1]]) != [metadata["extent"][1], metadata["extent"][3]]
            or list(self.lon[[0, -1]]) != [metadata["extent"][0], metadata["extent"][2]]
        ):
            raise FieldError("coordinate_manifest_mismatch")

    def variable(self, variable):
        if (
            variable
            not in self.metadata["variables"] + self.metadata["derived_variables"]
        ):
            raise FieldError("variable_not_in_product")
        return self.metadata["variable_metadata"][variable]

    def temporal(self, time):
        t = utc(time).timestamp()
        if self.metadata["kind"] == "analysis":
            if (
                not utc(self.metadata["valid_time_start"]).timestamp()
                <= t
                < utc(self.metadata["valid_time_end"]).timestamp()
            ):
                return None
            return [(0, 1.0)]
        if t < self.times[0] or t > self.times[-1]:
            return None
        index = int(np.searchsorted(self.times, t))
        if index < len(self.times) and self.times[index] == t:
            return [(index, 1.0)]
        left, right = index - 1, index
        if (
            self.times[right] - self.times[left]
            > self.metadata["max_time_gap_hours"] * 3600 + 1
        ):
            return None
        weight = (t - self.times[left]) / (self.times[right] - self.times[left])
        return [(left, float(1 - weight)), (right, float(weight))]

    def spatial(self, lat, lon, nearest=False):
        lat, lon = number(lat, -90, 90), number(lon, -180, 180)
        lon += 360 * round((float(np.mean(self.lon)) - lon) / 360)
        if (
            lat < self.lat[0]
            or lat > self.lat[-1]
            or lon < self.lon[0]
            or lon > self.lon[-1]
        ):
            return None
        if nearest:
            return [
                (
                    int(np.argmin(abs(self.lat - lat))),
                    int(np.argmin(abs(self.lon - lon))),
                    1.0,
                )
            ]

        def bracket(axis, value):
            index = int(np.searchsorted(axis, value))
            if index < len(axis) and math.isclose(
                float(axis[index]), value, abs_tol=1e-8
            ):
                return [(index, 1.0)]
            left = max(0, min(index - 1, len(axis) - 2))
            weight = (value - axis[left]) / (axis[left + 1] - axis[left])
            return [(left, float(1 - weight)), (left + 1, float(weight))]

        return [
            (y, x, wy * wx)
            for y, wy in bracket(self.lat, lat)
            for x, wx in bracket(self.lon, lon)
            if wy * wx > 1e-12
        ]

    def native_value(self, variable, temporal, spatial):
        terms = []
        for ti, tw in temporal:
            for y, x, sw in spatial:
                key = (variable, ti, y // 64, x // 64)
                if key not in self.chunks:
                    chunk = self.group[variable][
                        ti,
                        y // 64 * 64 : (y // 64 + 1) * 64,
                        x // 64 * 64 : (x // 64 + 1) * 64,
                    ]
                    self.chunk_bytes += chunk.nbytes
                    if self.chunk_bytes > 64 * 1024 * 1024:
                        raise FieldError("query_decoded_chunk_budget")
                    self.chunks[key] = chunk
                value = float(self.chunks[key][y % 64, x % 64])
                if not math.isfinite(value):
                    return None
                terms.append((value, tw * sw))
        if variable == "primary_wave_direction_from_deg":
            east = sum(math.sin(math.radians(v)) * w for v, w in terms)
            north = sum(math.cos(math.radians(v)) * w for v, w in terms)
            if math.hypot(east, north) < 1e-8:
                return None
            return math.degrees(math.atan2(east, north)) % 360
        return sum(v * w for v, w in terms)

    def value(self, variable, temporal, spatial):
        if variable in self.metadata["variables"]:
            return self.native_value(variable, temporal, spatial)
        prefix = "wind" if variable.startswith("wind_") else "current"
        u, v = [
            self.native_value(prefix + axis + "_m_s", temporal, spatial)
            for axis in ("_east", "_north")
        ]
        if u is None or v is None:
            return None
        speed = math.hypot(u, v)
        if "speed" in variable:
            return speed
        if speed < 1e-8:
            return None
        sign = -1 if prefix == "wind" else 1
        return math.degrees(math.atan2(sign * u, sign * v)) % 360

    def sample(self, variable, lat, lon, time):
        units = self.variable(variable)["units"]
        lat, lon = number(lat, -90, 90), number(lon, -180, 180)
        result = {
            "latitude": lat,
            "longitude": lon,
            "requested_time": iso(utc(time).timestamp()),
            "value": None,
            "units": units,
            "status": "unavailable",
            "reason": None,
            "spatial_support": [],
            "temporal_support": [],
            "method": POLICY["sampling"],
            "source_distance_km": None,
        }
        temporal, spatial = self.temporal(time), self.spatial(lat, lon)
        if spatial is None:
            return {
                **result,
                "status": "outside_domain",
                "reason": "outside_native_cell_centers",
            }
        if temporal is None:
            return {
                **result,
                "status": "outside_horizon",
                "reason": "no_supported_valid_time",
            }
        value = self.value(variable, temporal, spatial)
        result["spatial_support"] = [
            {
                "latitude": float(self.lat[y]),
                "longitude": float((self.lon[x] + 180) % 360 - 180),
                "weight": w,
            }
            for y, x, w in spatial
        ]
        result["temporal_support"] = [
            {"valid_time": iso(self.times[i]), "weight": w} for i, w in temporal
        ]
        result["source_distance_km"] = min(
            haversine((lat, lon), (p["latitude"], p["longitude"]))
            for p in result["spatial_support"]
        )
        if value is None:
            return {**result, "reason": "masked_cell_or_undefined_direction"}
        return {
            **result,
            "value": value,
            "status": freshness(self.metadata, self.as_of),
            "reason": "source_age_exceeds_budget"
            if freshness(self.metadata, self.as_of) == "stale"
            else None,
        }


def route_points(waypoints, spacing_km=5, step_minutes=30):
    if (
        not isinstance(waypoints, list)
        or not 2 <= len(waypoints) <= POLICY["limits"]["route_waypoints"]
    ):
        raise FieldError("route_waypoint_budget")
    spacing_km = number(spacing_km, 0.5, 5, "route_spacing_budget")
    step_minutes = number(step_minutes, 1, 30, "route_time_step_budget")
    points = []
    for w in waypoints:
        if not isinstance(w, dict) or set(w) != {"latitude", "longitude", "time"}:
            raise FieldError("timed_waypoints_required")
        points.append(
            (
                number(w["latitude"], -85, 85),
                number(w["longitude"], -180, 180),
                utc(w["time"]).timestamp(),
            )
        )
    if any(b[2] <= a[2] for a, b in zip(points, points[1:])):
        raise FieldError("route_times_must_increase")
    distances = [haversine(a, b) for a, b in zip(points, points[1:])]
    if (
        sum(distances) > POLICY["limits"]["route_km"]
        or points[-1][2] - points[0][2] > POLICY["limits"]["route_hours"] * 3600
    ):
        raise FieldError("route_distance_or_duration_budget")
    counts = [
        max(
            1, math.ceil(d / spacing_km), math.ceil((b[2] - a[2]) / (step_minutes * 60))
        )
        for d, a, b in zip(distances, points, points[1:])
    ]
    if sum(counts) + 1 > POLICY["limits"]["route_samples"]:
        raise FieldError("route_sample_budget")

    def xyz(p):
        lat, lon = map(math.radians, p[:2])
        return np.array(
            [
                math.cos(lat) * math.cos(lon),
                math.cos(lat) * math.sin(lon),
                math.sin(lat),
            ]
        )

    samples = []
    for a, b, count in zip(points, points[1:], counts):
        x, y = xyz(a), xyz(b)
        angle = math.acos(float(np.clip(x @ y, -1, 1)))
        for index in range(count):
            weight = index / count
            v = (
                (1 - weight) * x + weight * y
                if angle < 1e-8
                else (math.sin((1 - weight) * angle) * x + math.sin(weight * angle) * y)
                / math.sin(angle)
            )
            samples.append(
                {
                    "latitude": math.degrees(math.atan2(v[2], math.hypot(v[0], v[1]))),
                    "longitude": math.degrees(math.atan2(v[1], v[0])),
                    "time": iso(a[2] + weight * (b[2] - a[2])),
                }
            )
    samples.append(
        {
            "latitude": points[-1][0],
            "longitude": points[-1][1],
            "time": iso(points[-1][2]),
        }
    )
    return samples, {
        "distance_km": sum(distances),
        "spacing_km": spacing_km,
        "step_minutes": step_minutes,
        "path": "shortest great-circle segments through every timed waypoint; stops retained",
        "sample_count": len(samples),
    }


def route(grid, variable, waypoints, spacing_km=5, step_minutes=30, check=lambda: None):
    points, sampling = route_points(waypoints, spacing_km, step_minutes)
    samples = []
    for p in points:
        check()
        samples.append(grid.sample(variable, p["latitude"], p["longitude"], p["time"]))
    available = [s["value"] for s in samples if s["status"] == "available"]
    retained = [s["value"] for s in samples if s["value"] is not None]
    return {
        "sampling": sampling,
        "samples": samples,
        "status": "available"
        if len(available) == len(samples)
        else "partial"
        if available
        else "unavailable",
        "available_fraction": len(available) / len(samples),
        "sampled_minimum": min(retained) if retained else None,
        "sampled_maximum": max(retained) if retained else None,
        "extrema_scope": "retained samples including explicitly stale values; no guarantee of unsampled extremes",
        "assessment": "not_assessed",
        "limitations": POLICY["limitations"],
    }


def polygon(grid, variable, geometry, time, check=lambda: None):
    from shapely.geometry import shape
    from shapely import contains_xy

    utc(time)
    grid.variable(variable)

    if (
        not isinstance(geometry, dict)
        or geometry.get("type") != "Polygon"
        or len(str(geometry)) > 16000
    ):
        raise FieldError("bounded_geojson_polygon_required")
    try:
        area = shape(geometry)
    except Exception:
        raise FieldError("invalid_polygon") from None
    if (
        not area.is_valid
        or area.is_empty
        or area.has_z
        or not -180 <= area.bounds[0] <= area.bounds[2] <= 180
        or not -85 <= area.bounds[1] <= area.bounds[3] <= 85
        or area.bounds[2] - area.bounds[0] > 180
    ):
        raise FieldError("invalid_polygon_or_split_dateline_required")
    # Branch the grid to the polygon's longitude convention. Native cell centers, no upsampling.
    lons = (grid.lon + 180) % 360 - 180
    yi = np.flatnonzero((grid.lat >= area.bounds[1]) & (grid.lat <= area.bounds[3]))
    xi = np.flatnonzero((lons >= area.bounds[0]) & (lons <= area.bounds[2]))
    if len(yi) * len(xi) > POLICY["limits"]["polygon_cells"]:
        raise FieldError("polygon_cell_budget")
    xs, ys = np.meshgrid(lons[xi], grid.lat[yi])
    included = contains_xy(area, xs, ys)
    values, weights, total = [], [], int(included.sum())
    for iy, ix in zip(*np.where(included)):
        check()
        sample = grid.sample(
            variable, float(grid.lat[yi[iy]]), float(lons[xi[ix]]), time
        )
        if sample["status"] == "available":
            values.append(sample["value"])
            weights.append(math.cos(math.radians(sample["latitude"])))
    outside = (
        area.bounds[1] < grid.lat[0]
        or area.bounds[3] > grid.lat[-1]
        or area.bounds[0] < min(lons)
        or area.bounds[2] > max(lons)
    )
    circular = "direction" in variable
    return {
        "status": "outside_domain"
        if outside
        else "available"
        if total and len(values) == total
        else "partial"
        if values
        else "unavailable",
        "native_cells": total,
        "available_cells": len(values),
        "available_fraction": len(values) / total if total else None,
        "area_weighted_mean": float(np.average(values, weights=weights))
        if values and not circular
        else None,
        "minimum": min(values) if values and not circular else None,
        "maximum": max(values) if values and not circular else None,
        "method": "native cell centers inside polygon; cosine-latitude area weights; excluded/masked cells never count as zero",
        "reason": "circular_direction_aggregate_undefined"
        if circular
        else "polygon_extends_outside_domain"
        if outside
        else None,
    }


def tile(grid, variable, time, z, x, y, check=lambda: None):
    grid.variable(variable)
    if (
        any(isinstance(n, bool) or not isinstance(n, int) for n in (z, x, y))
        or not 0 <= z <= POLICY["limits"]["tile_zoom"]
        or not 0 <= x < 2**z
        or not 0 <= y < 2**z
    ):
        raise FieldError("invalid_tile_coordinate")
    temporal = grid.temporal(time)
    if temporal is None:
        raise FieldError("outside_horizon")
    # Sample native nearest cells on a Web Mercator raster; transparent outside/masked support.
    pixels = np.arange(256) + 0.5
    lons = ((x + pixels / 256) / (2**z)) * 360 - 180
    lats = np.rad2deg(
        np.arctan(np.sinh(math.pi * (1 - 2 * (y + pixels / 256) / (2**z))))
    )
    yy, xx = np.meshgrid(lats, lons, indexing="ij")
    branch = xx + 360 * np.round((float(np.mean(grid.lon)) - xx) / 360)
    supported = (
        (yy >= grid.lat[0])
        & (yy <= grid.lat[-1])
        & (branch >= grid.lon[0])
        & (branch <= grid.lon[-1])
    )
    iy = np.clip(
        np.rint((yy - grid.lat[0]) / (grid.lat[1] - grid.lat[0])).astype(int),
        0,
        len(grid.lat) - 1,
    )
    ix = np.clip(
        np.rint((branch - grid.lon[0]) / (grid.lon[1] - grid.lon[0])).astype(int),
        0,
        len(grid.lon) - 1,
    )
    values = np.full((256, 256), np.nan)
    # Only read the native subset intersecting this tile. Deduplicate cells before decompression.
    cells = np.unique(np.stack((iy[supported], ix[supported]), axis=1), axis=0)
    lookup = {}
    for cy, cx in cells:
        check()
        lookup[(cy, cx)] = grid.value(variable, temporal, [(int(cy), int(cx), 1.0)])
    for py, px in zip(*np.where(supported)):
        value = lookup[(iy[py, px], ix[py, px])]
        if value is not None:
            values[py, px] = value
    low, high = POLICY["variables"][variable]["colors"]
    t = np.clip(np.nan_to_num((values - low) / (high - low)), 0, 1)
    # Sequential sea ramp: calm reads as the deep chart sea, higher values brighten towards
    # foam white. No red or orange end, so a forecast field never mimics an official warning.
    anchors = np.array(
        [[14, 52, 92], [22, 92, 140], [46, 140, 176], [126, 196, 214], [226, 244, 247]]
    )
    rgba = np.zeros((256, 256, 4), dtype="uint8")
    for c in range(3):
        rgba[:, :, c] = np.interp(t, np.linspace(0, 1, 5), anchors[:, c]).astype(
            "uint8"
        )
    rgba[:, :, 3] = np.isfinite(values).astype("uint8") * 255
    output = io.BytesIO()
    Image.fromarray(rgba).save(output, format="PNG")
    return output.getvalue()
