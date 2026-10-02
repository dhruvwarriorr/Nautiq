"""Phase 2 scientific verification; does not restore the user's deleted tests."""

import json
import tempfile
from pathlib import Path

import netCDF4
import numpy as np

from nautiq_ml.argo.parser import InvalidProfile, parse, revision_digest


def fixture(
    path,
    mode="R",
    *,
    bad_salinity=False,
    duplicate=False,
    unit="decibar",
    per_parameter=False,
    levels=3,
):
    with netCDF4.Dataset(path, "w") as ds:
        for name, size in [
            ("N_PROF", 2),
            ("N_LEVELS", levels),
            ("N_PARAM", 3),
            ("STRING8", 8),
            ("STRING32", 32),
            ("DATE_TIME", 14),
            ("STRING16", 16),
        ]:
            ds.createDimension(name, size)

        def chars(name, dims, values):
            variable = ds.createVariable(name, "S1", dims)
            length = ds.dimensions[dims[-1]].size
            encoded = np.array(values, dtype=f"S{length}")
            variable[:] = np.frombuffer(encoded.tobytes(), dtype="S1").reshape(
                encoded.shape + (length,)
            )

        chars("PLATFORM_NUMBER", ("N_PROF", "STRING8"), ["2902768", "2902768"])
        chars(
            "VERTICAL_SAMPLING_SCHEME",
            ("N_PROF", "STRING32"),
            ["Primary sampling: discrete", "Secondary sampling: discrete"],
        )
        chars("DATA_TYPE", ("STRING16",), "Argo profile")
        chars("DATE_UPDATE", ("DATE_TIME",), "20261001000000")
        for name, values in [
            ("DIRECTION", ["A", "A"]),
            ("DATA_MODE", [mode, mode]),
            ("POSITION_QC", ["1", "1"]),
            ("JULD_QC", ["1", "1"]),
        ]:
            ds.createVariable(name, "S1", ("N_PROF",))[:] = np.array(values, dtype="S1")
        for name, values in [
            ("CYCLE_NUMBER", [1, 1]),
            ("LATITUDE", [15, 15]),
            ("LONGITUDE", [70, 70]),
            ("JULD", [27600, 27600]),
        ]:
            v = ds.createVariable(name, "f8", ("N_PROF",))
            v[:] = values
            if name == "JULD":
                v.units = "days since 1950-01-01 00:00:00 UTC"
        for parameter, raw, adjusted, units in [
            ("PRES", [0, 10, 20], [0, 10, 20], unit),
            ("TEMP", [28, 27, 26], [25, 24, 23], "degree_Celsius"),
            ("PSAL", [35, 35.1, 35.2], [34, 34.1, 34.2], "psu"),
        ]:
            if duplicate and parameter == "PRES":
                raw = adjusted = [0, 10, 10]
            if levels != 3:
                raw = np.linspace(raw[0], raw[-1], levels).tolist()
                adjusted = np.linspace(adjusted[0], adjusted[-1], levels).tolist()
            for suffix, values in [("", raw), ("_ADJUSTED", adjusted)]:
                v = ds.createVariable(
                    parameter + suffix, "f8", ("N_PROF", "N_LEVELS"), fill_value=99999
                )
                v.units = units
                v[:] = [values, values]
                flags = [["1"] * levels, ["1"] * levels]
                if bad_salinity and parameter == "PSAL":
                    flags[0][1] = "4"
                ds.createVariable(
                    parameter + suffix + "_QC", "S1", ("N_PROF", "N_LEVELS")
                )[:] = np.array(flags, dtype="S1")
        if per_parameter:
            chars(
                "STATION_PARAMETERS",
                ("N_PROF", "N_PARAM", "STRING16"),
                [["PRES", "TEMP", "PSAL"]] * 2,
            )
            ds.createVariable("PARAMETER_DATA_MODE", "S1", ("N_PROF", "N_PARAM"))[:] = (
                np.array([["D", "R", "D"]] * 2, dtype="S1")
            )


def main():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "profile.nc"
        fixture(path)
        raw = parse(path)
        assert len(raw["profiles"]) == 2
        assert raw["profiles"][0]["levels"][0]["temperature_c"] == 28
        assert raw["profiles"][0]["native_key"] != raw["profiles"][1]["native_key"]
        primary = raw["profiles"][0]["native_key"]
        fixture(path, "D", bad_salinity=True)
        adjusted = parse(path)
        p = adjusted["profiles"][0]
        assert p["native_key"] == primary
        assert p["levels"][0]["temperature_c"] == 25
        assert p["levels"][1]["practical_salinity"] is None
        assert p["levels"][1]["temperature_c"] == 24
        assert p["levels"][1]["missing_reasons"]["PSAL"] == "source_qc_not_1"
        assert p["levels"][1]["depth_m"] > 0
        assert len(p["levels"]) == 3
        json.dumps(p, allow_nan=False)
        assert revision_digest(p, "a" * 64) == revision_digest(p, "a" * 64)
        assert revision_digest(p, "a" * 64) != revision_digest(p, "b" * 64)
        fixture(path, "D", per_parameter=True)
        assert parse(path)["profiles"][0]["levels"][0]["temperature_c"] == 28
        fixture(path, duplicate=True)
        assert not parse(path)["profiles"]
        fixture(path, unit="metres")
        assert not parse(path)["profiles"]
        fixture(path)
        with netCDF4.Dataset(path, "a") as ds:
            ds["PRES"][:] = [[20, 10, 0], [20, 10, 0]]
        reversed_profile = parse(path)["profiles"][0]
        assert reversed_profile["levels"][0]["pressure_dbar"] == 0
        assert reversed_profile["levels"][0]["temperature_c"] == 26
        assert reversed_profile["levels"][0]["qc_flags"]["source_level_index"] == "2"
        fixture(path, "D")
        with netCDF4.Dataset(path, "a") as ds:
            ds.renameVariable("PRES_ADJUSTED", "UNAVAILABLE_ADJUSTED")
        assert not parse(path)["profiles"], (
            "Adjusted pressure silently fell back to raw"
        )
        for nprof, nlevels in [(65, 1), (1, 10001)]:
            with netCDF4.Dataset(path, "w") as ds:
                ds.createDimension("N_PROF", nprof)
                ds.createDimension("N_LEVELS", nlevels)
            try:
                parse(path)
            except InvalidProfile as error:
                assert str(error) == "dimension_budget"
            else:
                raise AssertionError("Oversized dimensions accepted")
        fixture(path)
        with netCDF4.Dataset(path, "a") as ds:
            ds["JULD"].calendar = "360_day"
        assert not parse(path)["profiles"]
        path.write_bytes(b"malformed NetCDF")
        try:
            parse(path)
        except (OSError, InvalidProfile):
            pass
        else:
            raise AssertionError("corrupt file accepted")
    print(
        "Argo parser verified: R/D selection, per-parameter modes, multiprofile identity, variable QC, original levels, units, duplicates, corrupt files, deterministic revisions"
    )


if __name__ == "__main__":
    main()
