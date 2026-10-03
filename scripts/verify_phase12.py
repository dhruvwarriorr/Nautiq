"""Independent file readback and export policy contracts, with no live dependencies."""

import csv
import io
import json
import tempfile
from pathlib import Path

import pyarrow.parquet as pq
from netCDF4 import Dataset
from nautiq_ml.product import exports as worker

ROOT = Path(__file__).resolve().parents[1]


def fixture():
    return {
        "schema_version": 1,
        "scope": "research",
        "method_version": "bounded-original-levels-export-v1",
        "generated_at": "2026-10-03T00:00:00Z",
        "product_policy_sha256": worker.digest(worker.POLICY_BYTES),
        "query": {"variable": "temperature_c"},
        "row_count": 2,
        "attribution": "Argo test credit",
        "terms_url": "https://argo.ucsd.edu/data/acknowledging-argo/",
        "limitations": ["Original instrument position; diagnostic only."],
        "observations": [
            {
                "profile_id": "fixture",
                "revision_sha256": "a" * 64,
                "raw_sha256": "b" * 64,
                "source_url": "https://example.invalid/original.nc",
                "platform_id": '\t=HYPERLINK("unsafe")',
                "observed_at": "2026-10-02T12:00:00Z",
                "received_at": "2026-10-03T00:00:00Z",
                "latitude": -12.0,
                "longitude": 72.0,
                "data_mode": "D",
                "qc_version": "qc1",
                "source_id": "argo_gdac",
                "levels": [
                    {
                        "depth_m": 0.0,
                        "pressure_dbar": 0.0,
                        "temperature_c": 24.5,
                        "qc_flags": {"temperature": "1"},
                    },
                    {
                        "depth_m": 10.0,
                        "pressure_dbar": 10.1,
                        "temperature_c": 23.0,
                        "qc_flags": {"temperature": "1"},
                    },
                ],
            }
        ],
    }


def main():
    assert (ROOT / "packages/source-catalog/product.json").read_bytes() == (
        ROOT / "services/api/internal/product/policy.json"
    ).read_bytes()
    assert worker.POLICY["export_permissions"]["source_profile_rows"]
    assert not worker.POLICY["export_permissions"]["source_forecast_rows"]
    snapshot = fixture()
    csv_data = worker.build(snapshot, "exports", "csv", "c" * 64)
    rows = list(csv.DictReader(io.StringIO(csv_data.decode())))
    assert len(rows) == 2 and rows[0]["platform_id"].startswith("'")
    assert rows[0]["latitude"] == "-12.0" and rows[1]["temperature_c"] == "23.0"
    assert all(
        row["raw_sha256"] == "b" * 64 and row["attribution"] == "Argo test credit"
        for row in rows
    )
    table = pq.read_table(
        io.BytesIO(worker.build(snapshot, "exports", "parquet", "c" * 64))
    )
    assert table.num_rows == 2 and table["temperature_c"].to_pylist() == [24.5, 23.0]
    assert (
        json.loads(table.schema.metadata[b"nautiq:evidence"])["input_sha256"]
        == "c" * 64
    )
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "observations.nc"
        path.write_bytes(worker.build(snapshot, "exports", "netcdf", "c" * 64))
        with Dataset(path) as dataset:
            assert len(dataset.dimensions["obs"]) == 2
            assert dataset["temperature_c"].units == "degree_Celsius"
            assert dataset["depth_m"].positive == "down"
            assert dataset["temperature_c"][:].tolist() == [24.5, 23.0]
            assert dataset["latitude"][:].tolist() == [-12.0, -12.0]
            assert dataset.nautiq_input_sha256 == "c" * 64
    snapshot["row_count"] = 3
    try:
        worker.build(snapshot, "exports", "csv", "c" * 64)
        raise AssertionError("row count mismatch accepted")
    except ValueError as error:
        assert str(error) == "row_count_integrity"
    snapshot["product_policy_sha256"] = "0" * 64
    try:
        worker.build(snapshot, "reports", "json", "c" * 64)
        raise AssertionError("policy drift accepted")
    except ValueError as error:
        assert str(error) == "pinned_policy_unavailable"
    print(
        "Product file contracts passed: policy parity, CSV formula protection, original values/units, independent Parquet and NetCDF readback, row and policy integrity."
    )


if __name__ == "__main__":
    main()
