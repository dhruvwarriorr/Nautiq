"""Scientific/failure invariants, with real-format NetCDF fixtures built in tests."""

import gzip
import hashlib
import io
import json
import urllib.error
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
netCDF4 = pytest.importorskip("netCDF4")
pytest.importorskip("lightgbm")
from nautiuq_ml.phase0.acquire import ProbeError, Store, public_url  # noqa: E402
from nautiuq_ml.phase0.argo import discover, interpolate, parse_profile, text  # noqa: E402
from nautiuq_ml.phase0.cli import (  # noqa: E402
    validate_advisory_index,
    validate_config,
    validate_forecast,
)
from nautiuq_ml.phase0.science import benchmark, conformal_offset  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def test_masked_netcdf_identifier_padding_is_not_missing():
    identifier = np.ma.array(
        np.array(list("1900001 "), dtype="S1"), mask=[False] * 7 + [True]
    )
    assert text(identifier) == "1900001"
    assert text(np.ma.array(np.array(["1"], dtype="S1"), mask=[True])) == ""


@pytest.fixture
def config():
    return json.loads((ROOT / "packages/source-catalog/phase0.json").read_text())


def test_interpolation_does_not_cross_gaps_extrapolate_or_invent_missing():
    actual = interpolate(
        np.array([10.0, 20.0, 100.0]),
        np.array([1.0, np.nan, 3.0]),
        [0, 10, 50, 100, 110],
        50,
    )
    np.testing.assert_allclose(actual, [np.nan, 1, np.nan, 3, np.nan], equal_nan=True)
    with pytest.raises(ProbeError, match="duplicate_pressure"):
        interpolate(np.array([10.0, 10.0]), np.array([1.0, 2.0]), [10], 50)


def test_catalog_rejects_overlap_and_invalid_grid(config):
    config["splits"]["calibration_end"] = config["splits"]["tune_end"]
    with pytest.raises(ValueError, match="split"):
        validate_config(config)
    config["splits"]["calibration_end"] = 2021
    config["standard_depths_m"] = [10, 10]
    with pytest.raises(ValueError, match="grid"):
        validate_config(config)


@pytest.mark.parametrize(
    "url",
    [
        "http://data-argo.ifremer.fr/file",
        "https://example.com/file",
        "https://user:secret@data-argo.ifremer.fr/file",
        "https://data-argo.ifremer.fr:8443/file",
    ],
)
def test_provider_allowlist(url):
    with pytest.raises(ProbeError, match="url_not_allowed"):
        public_url(url, ["data-argo.ifremer.fr"])


def test_cache_corruption_is_not_silently_refetched(tmp_path, config):
    url = "https://data-argo.ifremer.fr/sample"
    digest = hashlib.sha256(b"original").hexdigest()
    store = Store(tmp_path, config["limits"], offline=True)
    (tmp_path / "raw" / digest).write_bytes(b"corrupted")
    (
        tmp_path / "receipts" / f"{hashlib.sha256(url.encode()).hexdigest()}.json"
    ).write_text(json.dumps({"url": url, "sha256": digest}))
    with pytest.raises(ProbeError, match="checksum"):
        store.fetch(url, ["data-argo.ifremer.fr"])
    with pytest.raises(ProbeError, match="missing_offline"):
        store.fetch(url + "new", ["data-argo.ifremer.fr"])


def test_acquisition_retries_truncation_and_never_publishes_oversized(
    monkeypatch, tmp_path, config
):
    import nautiuq_ml.phase0.acquire as acquire

    monkeypatch.setattr(acquire, "public_url", lambda *args: None)
    monkeypatch.setattr(acquire.time, "sleep", lambda seconds: None)

    class Response(io.BytesIO):
        headers = {"Content-Length": "4", "Content-Type": "application/octet-stream"}

    responses = iter([Response(b"x"), Response(b"data")])
    store = Store(tmp_path, config["limits"])
    monkeypatch.setattr(store.opener, "open", lambda *args, **kwargs: next(responses))
    path, receipt = store.fetch(
        "https://data-argo.ifremer.fr/test", ["data-argo.ifremer.fr"]
    )
    assert path.read_bytes() == b"data" and receipt["bytes"] == 4
    assert len(list((tmp_path / "raw").iterdir())) == 1
    config["limits"]["max_object_bytes"] = 3
    limited = Store(tmp_path / "limited", config["limits"])
    monkeypatch.setattr(
        limited.opener, "open", lambda *args, **kwargs: Response(b"data")
    )
    with pytest.raises(ProbeError, match="too_large"):
        limited.fetch("https://data-argo.ifremer.fr/test", ["data-argo.ifremer.fr"])
    assert not list((tmp_path / "limited/raw").iterdir())


def test_long_retry_after_stops_and_auth_is_not_retried(monkeypatch, tmp_path, config):
    import nautiuq_ml.phase0.acquire as acquire

    monkeypatch.setattr(acquire, "public_url", lambda *args: None)
    monkeypatch.setattr(acquire.time, "sleep", lambda seconds: None)
    store = Store(tmp_path, config["limits"])
    calls = []

    def fail(*args, **kwargs):
        calls.append(1)
        raise urllib.error.HTTPError(
            "https://data-argo.ifremer.fr/test", 429, "", {"Retry-After": "600"}, None
        )

    monkeypatch.setattr(store.opener, "open", fail)
    with pytest.raises(ProbeError, match="retry_window"):
        store.fetch("https://data-argo.ifremer.fr/test", ["data-argo.ifremer.fr"])
    assert len(calls) == 1

    def unauthorized(*args, **kwargs):
        calls.append(1)
        raise urllib.error.HTTPError(
            "https://data-argo.ifremer.fr/test", 401, "", {}, None
        )

    monkeypatch.setattr(store.opener, "open", unauthorized)
    with pytest.raises(ProbeError, match="http_401"):
        store.fetch("https://data-argo.ifremer.fr/test", ["data-argo.ifremer.fr"])
    assert len(calls) == 2


def test_discovery_is_deterministic_and_rejects_path_traversal(tmp_path, config):
    header = "# comment\nfile,date,latitude,longitude,ocean,profiler_type,institution,date_update\n"
    records = [
        f"aoml/1900001/profiles/D1900001_{i:03d}.nc,20100101000000,15,70,I,846,US,20200101000000\n"
        for i in range(1, 6)
    ]
    records += [
        "aoml/1900001/profiles/../../secret,20100101000000,15,70,I,846,US,20200101000000\n"
    ]
    path = tmp_path / "index.gz"
    path.write_bytes(gzip.compress((header + "".join(records)).encode()))
    selected, counts = discover(path, config)
    assert len(selected) == 2 and counts["invalid_index_rows"] == 1
    assert discover(path, config)[0] == selected
    config["limits"]["max_index_expanded_bytes"] = 10
    with pytest.raises(ProbeError, match="expansion"):
        discover(path, config)


def create_argo(path):
    with netCDF4.Dataset(path, "w") as ds:
        for name, size in (("N_PROF", 1), ("N_LEVELS", 5), ("STRING8", 8)):
            ds.createDimension(name, size)
        for key, value in (
            ("DATA_MODE", "D"),
            ("DIRECTION", "A"),
            ("POSITION_QC", "1"),
            ("JULD_QC", "1"),
        ):
            ds.createVariable(key, "S1", ("N_PROF",))[:] = np.array([value], dtype="S1")
        ds.createVariable("PLATFORM_NUMBER", "S1", ("N_PROF", "STRING8"))[:] = np.array(
            list("1900001 "), dtype="S1"
        )
        for key, value in (
            ("LATITUDE", 15),
            ("LONGITUDE", 70),
            ("CYCLE_NUMBER", 1),
            ("JULD", 21915),
        ):
            ds.createVariable(key, "f8", ("N_PROF",))[:] = [value]
        ds["JULD"].units = "days since 1950-01-01 00:00:00"
        for param, unit, values_ in (
            ("PRES", "decibar", [0, 20, 50, 100, 200]),
            ("TEMP", "degree_Celsius", [28, 27, 26, 25, 24]),
            ("PSAL", "psu", [35, 35, 35, 35, 35]),
        ):
            var = ds.createVariable(
                f"{param}_ADJUSTED", "f8", ("N_PROF", "N_LEVELS"), fill_value=99999.0
            )
            var.units = unit
            var[:] = [values_]
            ds.createVariable(f"{param}_ADJUSTED_QC", "S1", ("N_PROF", "N_LEVELS"))[
                :
            ] = np.array([list("11111")], dtype="S1")


def test_real_netcdf_qc_mode_identity_and_variable_specific_missing(tmp_path, config):
    path = tmp_path / "profile.nc"
    create_argo(path)
    receipt = {
        "sha256": "a" * 64,
        "url": "https://data-argo.ifremer.fr/example",
        "received_at": "2026-10-01T00:00:00+00:00",
    }
    rows = parse_profile(path, receipt, config)
    assert rows and all(row["profile_key"] == "argo:1900001:1:A" for row in rows)
    with netCDF4.Dataset(path, "a") as ds:
        ds["PSAL_ADJUSTED_QC"][:] = np.array([list("44444")], dtype="S1")
    assert all(
        row["variable"] == "temperature_c"
        for row in parse_profile(path, receipt, config)
    )
    with netCDF4.Dataset(path, "a") as ds:
        ds["DATA_MODE"][:] = np.array(["R"], dtype="S1")
    with pytest.raises(ProbeError, match="not_delayed"):
        parse_profile(path, receipt, config)


def forecast(path, null=False):
    hours = [f"2026-10-02T{hour:02}:00" for hour in range(24)]
    data = {
        "latitude": 15.0,
        "longitude": 70.0,
        "utc_offset_seconds": 0,
        "hourly_units": {"wave_height": "m", "wave_period": "s", "wave_direction": "°"},
        "hourly": {
            "time": hours,
            "wave_height": [None if null else 1.0] * 24,
            "wave_period": [6.0] * 24,
            "wave_direction": [180.0] * 24,
        },
    }
    path.write_text(json.dumps(data))
    return data


def test_forecast_missing_units_duplicates_expiry_are_not_valid(tmp_path):
    path = tmp_path / "forecast.json"
    source = {"kind": "wave_forecast"}
    data = forecast(path)
    assert (
        validate_forecast(path, source, "2026-10-01T00:00:00+00:00")["forecast_cycle"]
        is None
    )
    with pytest.raises(ProbeError, match="expired"):
        validate_forecast(path, source, "2026-10-04T00:00:00+00:00")
    data["hourly"]["time"][1] = data["hourly"]["time"][0]
    path.write_text(json.dumps(data))
    with pytest.raises(ProbeError, match="gap_or_duplicate"):
        validate_forecast(path, source, "2026-10-01T00:00:00+00:00")
    forecast(path, null=True)
    with pytest.raises(ProbeError, match="missing"):
        validate_forecast(path, source, "2026-10-01T00:00:00+00:00")


def test_conformal_finite_sample_rank_and_bad_scores():
    assert conformal_offset([1, 2, 3, 4]) == 4
    assert conformal_offset([1]) is None
    with pytest.raises(ValueError):
        conformal_offset([float("nan")])


def test_empty_official_rss_still_means_unknown_and_entities_are_rejected(tmp_path):
    path = tmp_path / "rss.xml"
    source = {"allowed_hosts": ["sachet.ndma.gov.in"]}
    path.write_text("<rss><channel/></rss>")
    result = validate_advisory_index(path, source)
    assert result["items"] == 0 and result["advisory_state"] == "unknown"
    path.write_text("<!DOCTYPE rss [<!ENTITY x 'test'>]><rss><channel/></rss>")
    with pytest.raises(ProbeError, match="entity"):
        validate_advisory_index(path, source)
    path.write_text("<html>Service unavailable</html>")
    with pytest.raises(ProbeError, match="schema"):
        validate_advisory_index(path, source)


def synthetic_rows(config):
    rows = []
    rng = np.random.default_rng(42)
    for split, year in (
        ("train", 2010),
        ("tune", 2018),
        ("calibration", 2020),
        ("test", 2023),
    ):
        for profile in range(24):
            day = 1 + profile * 15
            for depth in config["standard_depths_m"]:
                rows.append(
                    {
                        "profile_key": f"{split}:{profile}",
                        "split": split,
                        "depth_m": depth,
                        "day_of_year": day,
                        "latitude": 10 + profile % 12,
                        "longitude": 65 + profile % 24,
                        "year": year,
                        "variable": "temperature_c",
                        "value": 28
                        - depth / 100
                        + np.sin(day / 365.25 * 2 * np.pi)
                        + rng.normal(0, 0.1),
                    }
                )
    return rows


def test_heldout_labels_cannot_change_tuning_or_calibration(config):
    rows = synthetic_rows(config)
    before = benchmark(rows, config)["variables"]["temperature_c"]
    for row in rows:
        if row["split"] == "test":
            row["value"] += 3
    after = benchmark(rows, config)["variables"]["temperature_c"]
    assert before["selected_on_tuning_only"] == after["selected_on_tuning_only"]
    assert before["uncertainty"]["offset"] == after["uncertainty"]["offset"]
    assert (
        after["test_metrics"]["climatology"]["mae"]
        > before["test_metrics"]["climatology"]["mae"]
    )
    rows[-1]["profile_key"] = rows[0]["profile_key"]
    with pytest.raises(ValueError, match="split_leakage"):
        benchmark(rows, config)
