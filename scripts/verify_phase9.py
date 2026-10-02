"""Independent arithmetic, coverage, geometry and bounded archive/array contracts."""

import io
import tempfile
from pathlib import Path

import netCDF4
import numpy as np
from shapely.geometry import shape

from nautiq_ml.events import core
from nautiq_ml.events.providers import decode, source_url
from nautiq_ml.events.storage import pack, unpack


def refuses(fn):
    try:
        fn()
    except (ValueError, KeyError):
        return
    raise AssertionError("unsupported event input accepted")


def thermal_fixture():
    dates = core.days("2026-09-01", "2026-09-15", 366)
    lat, lon = np.array([11.125, 11.375]), np.array([71.125, 71.375])
    values = np.full((15, 2, 2), 20, dtype="float32")
    values[3:8] = 23
    baseline = {
        "mean": np.full((366, 2, 2), 20, dtype="float32"),
        "threshold": np.full((366, 2, 2), 21, dtype="float32"),
        "count": np.full((366, 2, 2), 330, dtype="int16"),
        "years": np.full((366, 2, 2), 30, dtype="int16"),
    }
    return values, dates, lat, lon, baseline


def point(i, platform=None, when=None, lat=11, lon=71):
    when = when or f"2026-09-{i + 1:02d}T12:00:00Z"
    return dict(
        profile_id=str(i),
        platform_id=platform or str(i),
        variable="temperature_c",
        direction="positive",
        latitude=lat,
        longitude=lon,
        observed_at=when,
        day=when[:10],
        percentile=96,
        intensity=4,
    )


def main():
    # Independent constant-within-year reference: 30 equally weighted year values.
    dates = core.days("1982-01-01", "2011-12-31", 11323)
    values = np.array(
        [20 + 0.05 * (int(d[:4]) - 1982) for d in dates], dtype="float32"
    )[:, None, None] * np.ones((1, 2, 2), dtype="float32")
    values[:, 1, 1] = np.nan
    fitted = core.fit_baseline(values, dates, [11.125, 11.375], [71.125, 71.375])
    july = core.seasonal_index("2000-07-15")
    np.testing.assert_allclose(fitted["mean"][july, 0, 0], 20.725, atol=1e-5)
    np.testing.assert_allclose(fitted["threshold"][july, 0, 0], 21.305, atol=1e-5)
    assert fitted["count"][july, 0, 0] == 330 and fitted["years"][july, 0, 0] == 30
    assert (
        np.isnan(fitted["threshold"][:, 1, 1]).all()
        and (fitted["count"][:, 1, 1] == 0).all()
    )
    assert core.seasonal_index("2024-03-01") == core.seasonal_index("2025-03-01") == 60
    # Linear leap interpolation before a symmetric cyclic mean retains the midpoint.
    np.testing.assert_allclose(
        fitted["mean"][59], (fitted["mean"][58] + fitted["mean"][60]) / 2, atol=1e-5
    )
    refuses(
        lambda: core.fit_baseline(
            values[1:], dates[1:], [11.125, 11.375], [71.125, 71.375]
        )
    )
    missing = values.copy()
    missing[: 365 * 4] = np.nan
    unsupported = core.fit_baseline(missing, dates, [11.125, 11.375], [71.125, 71.375])
    assert np.isnan(unsupported["threshold"][july]).all()

    def runs(v):
        a = np.asarray(v, dtype=float)
        return core.cell_intervals(a, np.full(a.shape, 20), np.full(a.shape, 21))

    assert runs([23] * 4)[3] == []
    assert runs([23] * 5)[3] == [[0, 4]]
    assert runs([21] * 8)[3] == []  # Strict exceedance, not equality.
    assert runs([23] * 5 + [20] * 2 + [23] * 5)[3] == [[0, 11]]
    assert runs([23] * 5 + [20] * 3 + [23] * 5)[3] == [[0, 4], [8, 12]]
    assert runs([23] * 5 + [np.nan] + [23] * 5)[3] == [[0, 4], [6, 10]]
    assert (
        runs([23] * 4 + [20] + [23] * 4)[3] == []
    )  # Short runs cannot qualify by joining.
    assert runs([np.nan])[2].tolist() == [False]

    a, d, y, x, b = thermal_fixture()
    report = core.detect_thermal(a, d, y, x, b)
    assert len(report["events"]) == 1
    e = report["events"][0]
    assert e["duration_days"] == e["persistence_days"] == 5 and e["cell_days"] == 20
    assert (
        np.isclose(e["mean_intensity"], 3)
        and e["maximum_intensity"] == 3
        and e["maximum_category"] == 3
    )
    assert (
        not e["left_censored"]
        and not e["right_censored"]
        and e["release_approved"] is False
    )
    assert shape(e["geometry"]).area == 0.25
    one = np.full(a.shape, 20, dtype="float32")
    one[3:8, 0, 0] = 23
    r = core.detect_thermal(one, d, y, x, b)
    assert (
        not r["events"]
        and r["rejected_small_components"] == 1
        and r["qualified_cell_days"] == 5
    )
    a[5] = np.nan
    r = core.detect_thermal(a, d, y, x, b)
    assert not r["events"] and r["coverage"][5]["unknown_cells"] == 4
    a[:] = 23
    r = core.detect_thermal(a, d, y, x, b)
    assert r["events"][0]["left_censored"] and r["events"][0]["right_censored"]
    refuses(
        lambda: core.detect_thermal(
            a, core.days("2011-09-01", "2011-09-15", 366), y, x, b
        )
    )
    mask = np.ones((5, 3, 3), dtype=bool)
    mask[:, 1, 1] = False
    g, _ = core.group_cells(
        mask,
        np.ones(mask.shape),
        np.ones(mask.shape),
        d[:5],
        np.array([11.125, 11.375, 11.625]),
        np.array([71.125, 71.375, 71.625]),
        mask,
    )
    assert len(shape(g[0]["geometry"]).interiors) == 1 and np.isclose(
        shape(g[0]["geometry"]).area, 0.5
    )
    moving = np.zeros((2, 2, 2), dtype=bool)
    moving[0, 0, 0] = moving[1, 0, 1] = True
    assert len(list(core.components(moving))) == 1
    moving[1, 0, 1] = False
    moving[1, 1, 1] = True
    assert len(list(core.components(moving))) == 2

    assert core.group_profiles([point(0)])[0]["kind"] == "isolated_profile_anomalies"
    pts = [point(i) for i in range(3)]
    g = core.group_profiles(pts)
    assert (
        len(g) == 1
        and g[0]["kind"] == "regional_profile_candidate"
        and g[0]["geometry"]["type"] == "MultiPoint"
    )
    assert (
        core.group_profiles([point(i, platform="one") for i in range(3)])[0]["kind"]
        == "isolated_profile_anomalies"
    )
    assert len(core.group_profiles([point(0), point(1, lon=75)])) == 2
    assert len(core.group_profiles([point(0, lon=179.9), point(1, lon=-179.9)])) == 1
    # Same day labels 2 days apart must not hide a true 71-hour gap.
    assert (
        len(
            core.group_profiles(
                [
                    point(0, when="2026-09-01T00:01:00Z"),
                    point(1, when="2026-09-03T23:59:00Z"),
                ]
            )
        )
        == 2
    )
    assert (
        len(core.group_profiles([point(0), {**point(1), "direction": "negative"}])) == 2
    )
    refuses(lambda: core.group_profiles([point(0), point(0)]))
    refuses(lambda: core.group_profiles([{**point(0), "percentile": 94}]))
    refuses(lambda: core.group_profiles([{**point(0), "latitude": float("nan")}]))

    # Packed provider NetCDF: preserve native mask and a missing whole day as unknown.
    with tempfile.TemporaryDirectory() as temp:
        p = Path(temp) / "input.nc"
        with netCDF4.Dataset(p, "w", format="NETCDF3_CLASSIC") as ds:
            for n, k in [("time", 2), ("lat", 2), ("lon", 2)]:
                ds.createDimension(n, k)
            yy = ds.createVariable("lat", "f4", ("lat",))
            yy.units = "degrees_north"
            yy[:] = y
            xx = ds.createVariable("lon", "f4", ("lon",))
            xx.units = "degrees_east"
            xx[:] = x
            t = ds.createVariable("time", "f8", ("time",))
            t.units = "days since 2026-09-01 00:00:00"
            t[:] = [0, 2]
            v = ds.createVariable(
                "sst", "i2", ("time", "lat", "lon"), fill_value=-32768
            )
            v.units = "degC"
            v.scale_factor = 0.01
            v[:] = np.ma.array(
                np.full((2, 2, 2), 22.5), mask=[[[0, 0], [0, 1]], [[0, 0], [0, 1]]]
            )
        a, dates, yy, xx = decode(
            p.read_bytes(), [71, 11, 72, 12], "2026-09-01", "2026-09-03"
        )
        assert (
            a.shape == (3, 2, 2) and np.isnan(a[1]).all() and np.isnan(a[:, 1, 1]).all()
        )
        assert a[0, 0, 0] == 22.5 and len(dates) == 3
        with netCDF4.Dataset(p, "a") as ds:
            ds["sst"].units = "kelvin"
        refuses(
            lambda: decode(p.read_bytes(), [71, 11, 72, 12], "2026-09-01", "2026-09-03")
        )
    arrays = {"lat": y, "lon": x, "sst": a}
    data = pack(arrays)
    assert data == pack(arrays)
    for k, v in unpack(data, arrays).items():
        np.testing.assert_equal(v, arrays[k])
    refuses(lambda: unpack(data, ["lat"]))
    bad = io.BytesIO()
    np.savez_compressed(bad, lat=np.array([{}], dtype=object))
    refuses(lambda: unpack(bad.getvalue(), ["lat"]))
    refuses(lambda: source_url(1982, "1982-01-01", "1982-12-31", [-180, -80, 180, 80]))
    print(
        "Event arithmetic checks passed: independent seasonal mean/percentile, leap/support/masks, persistence/equality/gaps, native geometry/holes/area, spatial edges, isolated versus regional profile points, exact UTC gaps/dateline, packed/missing-day archive and safe deterministic arrays."
    )


if __name__ == "__main__":
    main()
