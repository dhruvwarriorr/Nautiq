"""Offline, independent arithmetic and malformed-grid checks; synthetic data is testing only."""

import io
from datetime import datetime, timezone
from types import SimpleNamespace

import numpy as np
import zarr
from minio.error import S3Error
from PIL import Image

from nautiq_ml.fields.core import FieldError, POLICY, canonical, validate_grid
from nautiq_ml.fields.sampling import FieldGrid, polygon, route, route_points, tile
from nautiq_ml.fields.storage import open_grid, stage


def grid_fixture(
    product="noaa_gfs_weather", offset=0, masked=False, cycle="2026-10-02T00:00:00Z"
):
    t = datetime.fromisoformat(cycle.replace("Z", "+00:00")).timestamp()
    lat, lon, times = (
        np.array([12.0, 11.0, 10.0]),
        np.array([70.0, 70.25, 70.5]),
        np.array([t, t + 10800]),
    )
    plane = np.array(
        [
            [[4 * y + x + 8 * k + offset for x in range(3)] for y in range(3)]
            for k in range(2)
        ],
        dtype="float32",
    )
    defaults = {
        "wind_east_m_s": plane + 2,
        "wind_north_m_s": np.full_like(plane, 4),
        "air_temperature_c": plane + 20,
        "surface_pressure_pa": plane * 10 + 100000,
        "wave_height_m": plane / 10,
        "primary_wave_mean_period_s": plane / 10 + 10,
        "primary_wave_direction_from_deg": np.full_like(plane, 359),
        "current_east_m_s": plane / 10,
        "current_north_m_s": np.full_like(plane, 0.2),
        "sst_c": plane + 20,
    }
    arrays = {name: defaults[name] for name in POLICY["products"][product]["variables"]}
    if masked:
        for a in arrays.values():
            a[:, 1, 1] = np.nan
    if product == "noaa_oisst":
        times = np.array([t + 43200])
        arrays = {v: a[:1] for v, a in arrays.items()}
        return validate_grid(
            lat,
            lon,
            times,
            arrays,
            product,
            None,
            cycle,
            datetime.fromtimestamp(t + 86400, timezone.utc).isoformat(),
        )
    return validate_grid(lat, lon, times, arrays, product, cycle)


def memory_grid(grid):
    lat, lon, times, arrays, metadata = grid
    g = zarr.group()
    for name, a in [
        ("latitude", lat),
        ("longitude", lon),
        ("time", times),
        *arrays.items(),
    ]:
        g.create_dataset(name, data=a)
    return FieldGrid(g, metadata)


class Response(io.BytesIO):
    def release_conn(self):
        pass


class MemoryObjects:
    def __init__(self):
        self.data, self.metadata = {}, {}

    def stat_object(self, bucket, key):
        if key not in self.data:
            raise S3Error(None, "NoSuchKey", "missing", key, "test", "test")
        return SimpleNamespace(
            size=len(self.data[key]),
            metadata={"x-amz-meta-sha256": self.metadata[key]["sha256"]},
        )

    def put_object(self, bucket, key, stream, size, metadata):
        self.data[key], self.metadata[key] = stream.read(), metadata

    def get_object(self, bucket, key):
        return Response(self.data[key])


def fails(fn, reason):
    try:
        fn()
    except FieldError as e:
        assert str(e) == reason, str(e)
    else:
        raise AssertionError("Expected refusal: " + reason)


def verify():
    provider_checks()
    from nautiq_ml.fields.providers import bbox_values, decode_grib, hycom_runs

    grid = grid_fixture()
    assert list(grid[0]) == [10, 11, 12]
    f = memory_grid(grid)
    # Source row order is reversed. Half-space/half-time interpolation: (6.5 + 14.5)/2 + 2 = 12.5.
    time = "2026-10-02T01:30:00Z"
    sample = f.sample("wind_east_m_s", 10.5, 70.125, time)
    assert sample["value"] == 12.5
    assert sum(p["weight"] for p in sample["spatial_support"]) == 1
    assert sum(p["weight"] for p in sample["temporal_support"]) == 1
    assert (
        abs(f.sample("wind_speed_m_s", 10.5, 70.125, time)["value"] - np.hypot(12.5, 4))
        < 1e-10
    )
    assert f.sample("wind_east_m_s", 9, 70.125, time)["status"] == "outside_domain"
    assert (
        f.sample("wind_east_m_s", 10.5, 70.125, "2026-10-03T00:00:00Z")["status"]
        == "outside_horizon"
    )
    assert (
        memory_grid(grid_fixture(masked=True)).sample(
            "wind_east_m_s", 10.5, 70.125, time
        )["value"]
        is None
    )
    assert f.sample("wind_east_m_s", 10, 70, time)["value"] == 14
    fails(
        lambda: f.sample("wind_east_m_s", float("nan"), 70, time), "invalid_coordinate"
    )
    fails(lambda: f.sample("sst_c", 10, 70, time), "variable_not_in_product")
    from nautiq_ml.fields.core import utc, freshness

    fails(lambda: utc("2026-10-02T00:00:00"), "timezone_required")
    assert freshness(grid[-1], datetime(2026, 10, 4, tzinfo=timezone.utc)) == "stale"
    assert (
        freshness(grid[-1], datetime(2026, 10, 2, 1, tzinfo=timezone.utc))
        == "available"
    )
    lat, lon, times, arrays, _ = grid
    fails(
        lambda: validate_grid(lat, lon, times, arrays, "noaa_gfs_weather", None),
        "forecast_cycle_required_analysis_cycle_absent",
    )
    fails(
        lambda: validate_grid(
            lat, [70, 70, 71], times, arrays, "noaa_gfs_weather", grid[-1]["cycle"]
        ),
        "non_regular_or_duplicate_grid",
    )
    fails(
        lambda: validate_grid(
            lat,
            lon,
            [times[0], times[0] + 14400],
            arrays,
            "noaa_gfs_weather",
            grid[-1]["cycle"],
        ),
        "duplicate_or_gapped_times",
    )
    fails(
        lambda: validate_grid(
            lat,
            lon,
            times,
            {"wind_east_m_s": arrays["wind_east_m_s"]},
            "noaa_gfs_weather",
            grid[-1]["cycle"],
        ),
        "incomplete_or_unknown_variables",
    )
    bad = {
        **arrays,
        "surface_pressure_pa": np.full_like(arrays["surface_pressure_pa"], np.inf),
    }
    fails(
        lambda: validate_grid(
            lat, lon, times, bad, "noaa_gfs_weather", grid[-1]["cycle"]
        ),
        "variable_bounds",
    )
    analysis = memory_grid(grid_fixture("noaa_oisst"))
    assert analysis.sample("sst_c", 10, 70, "2026-10-02T00:00:00Z")["value"] is not None
    assert (
        analysis.sample("sst_c", 10, 70, "2026-10-03T00:00:00Z")["status"]
        == "outside_horizon"
    )
    # Circular interpolation cannot average 359 and 1 to 180; vectors are interpolated before speed/direction.
    wave = grid_fixture("noaa_gfs_wave")
    wave[3]["primary_wave_direction_from_deg"][:, :, 0] = 359
    wave[3]["primary_wave_direction_from_deg"][:, :, 1] = 1
    circular = memory_grid(wave).sample(
        "primary_wave_direction_from_deg", 10, 70.125, time
    )["value"]
    assert min(abs(circular), abs(circular - 360)) < 1e-8
    waypoints = [
        {"latitude": 10.0, "longitude": 70.0, "time": "2026-10-02T00:00:00Z"},
        {"latitude": 10.0, "longitude": 70.2, "time": "2026-10-02T01:00:00Z"},
        {"latitude": 10.0, "longitude": 70.0, "time": "2026-10-02T02:00:00Z"},
    ]
    points, report = route_points(waypoints)
    assert (
        len(points) == report["sample_count"]
        and points[0]["longitude"] == points[-1]["longitude"]
    )
    assert any(abs(p["longitude"] - 70.2) < 1e-6 for p in points)
    route_result = route(f, "wind_east_m_s", waypoints)
    assert (
        len(route_result["samples"]) == len(points)
        and route_result["assessment"] == "not_assessed"
    )
    fails(
        lambda: route_points([waypoints[1], waypoints[0]]), "route_times_must_increase"
    )
    fails(lambda: route_points(waypoints, 0.01), "route_spacing_budget")
    fails(
        lambda: route_points([waypoints[0], {**waypoints[1], "longitude": 78}], 0.5, 1),
        "route_sample_budget",
    )
    dateline, _ = route_points(
        [
            {"latitude": 10, "longitude": 179, "time": "2026-10-02T00:00:00Z"},
            {"latitude": 10, "longitude": -179, "time": "2026-10-02T02:00:00Z"},
        ]
    )
    assert all(abs(p["longitude"]) >= 179 for p in dateline)
    geom = {
        "type": "Polygon",
        "coordinates": [
            [[69.9, 9.9], [70.6, 9.9], [70.6, 12.1], [69.9, 12.1], [69.9, 9.9]]
        ],
    }
    poly = polygon(f, "wind_east_m_s", geom, time)
    assert poly["native_cells"] == 9 and poly["status"] == "outside_domain"
    fails(
        lambda: polygon(
            f, "wind_east_m_s", {"type": "Point", "coordinates": [70, 10]}, time
        ),
        "bounded_geojson_polygon_required",
    )
    png = tile(f, "wind_speed_m_s", time, 3, 5, 3)
    image = Image.open(io.BytesIO(png))
    assert image.size == (256, 256) and image.mode == "RGBA"
    assert np.asarray(image)[:, :, 3].min() == 0
    fails(lambda: tile(f, "wind_speed_m_s", time, 13, 0, 0), "invalid_tile_coordinate")
    fails(
        lambda: tile(f, "wind_speed_m_s", "2026-10-03T00:00:00Z", 1, 0, 0),
        "outside_horizon",
    )
    fails(lambda: bbox_values([70, 10, 69, 15]), "invalid_bbox")
    fails(lambda: hycom_runs(b"<!DOCTYPE x><x/>"), "catalog_budget_or_entities")
    fails(lambda: hycom_runs(b"<catalog/>"), "missing_run_metadata")
    fails(
        lambda: decode_grib(b"not-grib", "noaa_gfs_wave", grid[-1]["cycle"], 0),
        "not_grib",
    )
    objects = MemoryObjects()
    manifest, key, sha = stage(objects, *grid, [], "forecast")
    repeat = stage(objects, *grid, [], "forecast")
    assert canonical(manifest) == canonical(repeat[0]) and sha == repeat[2]
    row = {
        "manifest_key": key,
        "manifest_sha256": sha,
        "manifest": manifest,
        "release_sha256": manifest["release_sha256"],
        "product_id": "noaa_gfs_weather",
    }
    group, metadata = open_grid(objects, row, full=True)
    assert (
        FieldGrid(group, metadata).sample("wind_east_m_s", 10.5, 70.125, time)["value"]
        == 12.5
    )
    chunk = manifest["zarr_prefix"] + "wind_east_m_s/0.0.0"
    original = objects.data[chunk]
    objects.data[chunk] = b"corrupt"
    from nautiq_ml.argo.parser import InvalidProfile

    try:
        open_grid(objects, row, full=True)
    except InvalidProfile:
        pass
    else:
        raise AssertionError("corrupt chunk accepted")
    objects.data[chunk] = original
    open_grid(objects, row, full=True)
    print(
        "Offline field checks passed: normalization, separate cycle/time, masks, independent bilinear/vector/circular arithmetic, daily windows, staleness, timed routes/stops/dateline/budgets, polygons, PNG transparency, deterministic Zarr and corruption refusal."
    )


def provider_checks():
    import tempfile
    from pathlib import Path
    import netCDF4
    import eccodes as ec
    from nautiq_ml.fields.providers import decode_grib, oisst, epochs, subset_axes

    # Synthetic packed CF input exercises dimension transposition, scaled fill,
    # descending latitude and a 0..360 longitude convention independently of the grid fixture.
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "packed.nc"
        with netCDF4.Dataset(path, "w") as ds:
            for name, size in [("time", 1), ("zlev", 1), ("lat", 3), ("lon", 3)]:
                ds.createDimension(name, size)
            lat = ds.createVariable("lat", "f8", ("lat",))
            lat.units = "degrees_north"
            lat[:] = [12, 11, 10]
            lon = ds.createVariable("lon", "f8", ("lon",))
            lon.units = "degrees_east"
            lon[:] = [350, 350.25, 350.5]
            t = ds.createVariable("time", "f8", ("time",))
            t.units = "hours since 2026-10-02 00:00:00"
            t[:] = [12]
            z = ds.createVariable("zlev", "f8", ("zlev",))
            z[:] = [0]
            s = ds.createVariable(
                "sst", "i2", ("lon", "time", "lat", "zlev"), fill_value=-32768
            )
            s.units = "Celsius"
            s.scale_factor = 0.01
            values = np.ma.array(np.full((3, 1, 3, 1), 25.0), mask=False)
            values.mask[1, 0, 1, 0] = True
            s[:] = values

        class Retained:
            def fetch(self, url):
                return path.read_bytes()

        grid, version = oisst(Retained(), "2026-10-02", [-10, 10, -9.5, 12])
        assert version == "final" and grid[-1]["mask_counts"]["sst_c"] == 1
        assert list(grid[1]) == [-10, -9.75, -9.5] and list(grid[0]) == [10, 11, 12]
        assert np.isnan(grid[3]["sst_c"][0, 1, 1]) and grid[3]["sst_c"][0, 0, 0] == 25
        with netCDF4.Dataset(path, "a") as ds:
            ds["time"].calendar = "360_day"
        with netCDF4.Dataset(path) as ds:
            fails(lambda: epochs(ds["time"]), "unsupported_calendar")
            ds_lat = ds["lat"]
            assert ds_lat.shape == (3,)
        with netCDF4.Dataset(path, "a") as ds:
            ds["lat"].units = "radians"
        with netCDF4.Dataset(path) as ds:
            fails(lambda: subset_axes(ds, [-10, 10, -9.5, 12]), "coordinate_units")
    messages = []
    for parameter, value in [(3, 1.0), (11, 8.0), (10, 359.0)]:
        gid = ec.codes_grib_new_from_samples("regular_ll_sfc_grib2")
        try:
            for key, val in {
                "discipline": 10,
                "parameterCategory": 0,
                "parameterNumber": parameter,
                "typeOfLevel": "surface",
                "dataDate": 20261002,
                "dataTime": 0,
                "forecastTime": 3,
                "Ni": 3,
                "Nj": 3,
                "latitudeOfFirstGridPointInDegrees": 12,
                "latitudeOfLastGridPointInDegrees": 10,
                "longitudeOfFirstGridPointInDegrees": 70,
                "longitudeOfLastGridPointInDegrees": 70.5,
                "iDirectionIncrementInDegrees": 0.25,
                "jDirectionIncrementInDegrees": 1,
                "jScansPositively": 0,
                "iScansNegatively": 0,
            }.items():
                ec.codes_set(gid, key, val)
            ec.codes_set(gid, "bitmapPresent", 1)
            ec.codes_set(gid, "missingValue", 9999.0)
            ec.codes_set_values(gid, [value] * 8 + [9999.0])
            messages.append(ec.codes_get_message(gid))
        finally:
            ec.codes_release(gid)
    axes, arrays, valid = decode_grib(
        b"".join(messages), "noaa_gfs_wave", "2026-10-02T00:00:00Z", 3
    )
    assert (
        np.isnan(arrays["wave_height_m"][-1, -1]) and arrays["wave_height_m"][0, 0] == 1
    )
    assert (
        valid == datetime(2026, 10, 2, 3, tzinfo=timezone.utc).timestamp()
        and axes[0][0] == 12
    )
    fails(
        lambda: decode_grib(
            b"".join(messages), "noaa_gfs_wave", "2026-10-02T00:00:00Z", 6
        ),
        "grib_cycle_or_valid_time_mismatch",
    )
    fails(
        lambda: decode_grib(
            b"".join(messages[:2]), "noaa_gfs_wave", "2026-10-02T00:00:00Z", 3
        ),
        "incomplete_grib_parameters",
    )


if __name__ == "__main__":
    verify()
