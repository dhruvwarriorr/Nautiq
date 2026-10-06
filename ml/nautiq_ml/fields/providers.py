"""Bounded NOAA, HYCOM and Copernicus Marine adapters with provider-derived valid times."""

import hashlib
import json
import os
import re
import tempfile
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

import netCDF4
import numpy as np

from ..argo.storage import put_immutable
from ..phase0.acquire import ProbeError, Store
from .core import FieldError, POLICY, iso, utc, validate_grid

HYCOM_RUNS = (
    "https://tds.hycom.org/thredds/catalog/FMRC_ESPC-D-V02_uv3z/runs/catalog.xml"
)
HOSTS = ["www.ncei.noaa.gov", "nomads.ncep.noaa.gov", "tds.hycom.org", "ncss.hycom.org"]

# Copernicus Marine global forecasts on a 1/12° grid. Each run of the toolbox is retained as a raw
# receipt under a canonical cmems:// request URL so replay never needs the network or credentials.
CMEMS = {
    "cmems_wave": {
        "dataset": "cmems_mod_glo_wav_anfc_0.083deg_PT3H-i",
        "step_hours": 3,
        "hours": 48,
        "depth": False,
        "variables": {
            "VHM0": ("wave_height_m", ("m",)),
            "VTM10": ("primary_wave_mean_period_s", ("s",)),
            "VMDR": ("primary_wave_direction_from_deg", ("degree", "degrees")),
        },
    },
    "cmems_currents": {
        "dataset": "cmems_mod_glo_phy-cur_anfc_0.083deg_PT6H-i",
        "step_hours": 6,
        "hours": 72,
        "depth": True,
        "variables": {
            "uo": ("current_east_m_s", ("m s-1",)),
            "vo": ("current_north_m_s", ("m s-1",)),
        },
    },
    "cmems_sst": {
        "dataset": "cmems_mod_glo_phy-thetao_anfc_0.083deg_PT6H-i",
        "step_hours": 6,
        "hours": 72,
        "depth": True,
        "variables": {"thetao": ("sst_c", ("degrees_C", "degree_Celsius"))},
    },
}


def cmems_url(dataset, action, params):
    return f"cmems://{dataset}/{action}?" + urllib.parse.urlencode(sorted(params.items()))


def cmems_request(url, directory):
    """Run one Copernicus Marine toolbox call for a canonical cmems:// URL and return its bytes."""
    import copernicusmarine

    parsed = urllib.parse.urlsplit(url)
    dataset, action = parsed.netloc, parsed.path.strip("/")
    if dataset not in {spec["dataset"] for spec in CMEMS.values()}:
        raise FieldError("source_url_denied")
    if action == "describe":
        catalogue = copernicusmarine.describe(
            dataset_id=dataset, disable_progress_bar=True
        )
        version = catalogue.products[0].datasets[0].versions[0]
        part = version.parts[0]
        if not part.arco_updated_date:
            raise FieldError("cmems_update_time_missing")
        return json.dumps(
            {
                "dataset_id": dataset,
                "version": version.label,
                "arco_updated_date": part.arco_updated_date,
            },
            sort_keys=True,
        ).encode()
    if action != "subset":
        raise FieldError("source_url_denied")
    username, password = os.getenv("CMEMS_USERNAME"), os.getenv("CMEMS_PASSWORD")
    if not username or not password:
        raise FieldError("cmems_credentials_missing")
    q = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
    depth = {"minimum_depth": 0, "maximum_depth": 1} if q.get("depth") == "surface" else {}
    try:
        result = copernicusmarine.subset(
            dataset_id=dataset,
            variables=q["variables"].split(","),
            minimum_longitude=float(q["west"]),
            maximum_longitude=float(q["east"]),
            minimum_latitude=float(q["south"]),
            maximum_latitude=float(q["north"]),
            start_datetime=q["start"],
            end_datetime=q["end"],
            output_directory=directory,
            output_filename="cmems.nc",
            username=username,
            password=password,
            disable_progress_bar=True,
            overwrite=True,
            **depth,
        )
    except Exception:
        raise FieldError("cmems_unavailable") from None
    path = Path(result.file_path)
    if not path.is_file() or path.stat().st_size > POLICY["limits"]["raw_bytes"]:
        raise FieldError("object_too_large")
    data = path.read_bytes()
    path.unlink()
    return data


class Acquisition:
    def __init__(self, directory, s3=None):
        self.s3, self.receipts, self.directory = s3, [], directory
        self.store = Store(
            Path(directory),
            {
                # HYCOM's subset service builds the file before it answers; 60 s was too short.
                "request_deadline_seconds": 300,
                "timeout_seconds": 150,
                "attempts": 2,
                "max_object_bytes": POLICY["limits"]["raw_bytes"],
                "max_total_download_bytes": POLICY["limits"]["total_download_bytes"],
            },
        )

    def fetch(self, url):
        if url.startswith("cmems://"):
            data = cmems_request(url, self.directory)
            receipt = {
                "url": url,
                "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
                "last_modified": None,
                "etag": None,
                "content_type": "application/json"
                if "/describe?" in url
                else "application/x-netcdf",
            }
        else:
            try:
                path, receipt = self.store.fetch(url, HOSTS)
            except ProbeError as error:
                raise FieldError(str(error)) from None
            data = path.read_bytes()
        key = "fields/raw/" + receipt["sha256"]
        if self.s3:
            put_immutable(self.s3, key, data)
        # Receipt identity survives retries without manufacturing a new release for identical bytes.
        identity = {
            k: receipt[k]
            for k in ("url", "sha256", "bytes", "last_modified", "etag", "content_type")
        }
        identity["raw_key"] = key
        if identity not in self.receipts:
            self.receipts.append(identity)
        return data


def bbox_values(bbox):
    if len(bbox) != 4 or not np.isfinite(bbox).all():
        raise FieldError("invalid_bbox")
    west, south, east, north = map(float, bbox)
    if (
        not -180 <= west < east <= 180
        or not -80 <= south < north <= 80
        or east - west > 60
        or north - south > 50
    ):
        raise FieldError("invalid_bbox")
    return west, south, east, north


def epochs(variable):
    if getattr(variable, "calendar", "standard") not in (
        "standard",
        "gregorian",
        "proleptic_gregorian",
    ):
        raise FieldError("unsupported_calendar")
    dates = netCDF4.num2date(
        variable[:],
        variable.units,
        calendar=getattr(variable, "calendar", "standard"),
        only_use_cftime_datetimes=False,
    )
    result = []
    for d in np.atleast_1d(dates).flat:
        if not isinstance(d, datetime):
            raise FieldError("unsupported_calendar")
        result.append(d.replace(tzinfo=timezone.utc).timestamp())
    return np.asarray(result)


def subset_axes(ds, bbox):
    west, south, east, north = bbox_values(bbox)
    lat, lon = np.asarray(ds["lat"][:]), np.asarray(ds["lon"][:])
    if lat.ndim != 1 or lon.ndim != 1 or lat.size > 10000 or lon.size > 10000:
        raise FieldError("curvilinear_or_coordinate_budget")
    if getattr(ds["lat"], "units", "") not in (
        "degrees_north",
        "degree_north",
    ) or getattr(ds["lon"], "units", "") not in ("degrees_east", "degree_east"):
        raise FieldError("coordinate_units")
    lon = (lon + 180) % 360 - 180
    yi, xi = (
        np.flatnonzero((lat >= south) & (lat <= north)),
        np.flatnonzero((lon >= west) & (lon <= east)),
    )
    if len(yi) < 2 or len(xi) < 2 or len(yi) * len(xi) > POLICY["limits"]["cells"]:
        raise FieldError("empty_subset_or_grid_budget")
    return lat[yi], lon[xi], yi, xi


def netcdf_surface(ds, name, yi, xi, expected_units):
    var = ds[name]
    if getattr(var, "units", "") not in expected_units:
        raise FieldError("variable_units")
    dims = list(var.dimensions)
    if set(dims) != {"time", "lat", "lon", "depth"} and set(dims) != {
        "time",
        "lat",
        "lon",
        "zlev",
    }:
        raise FieldError("unsupported_dimension_order")
    zname = "depth" if "depth" in dims else "zlev"
    if len(ds[zname]) < 1 or float(ds[zname][0]) != 0:
        raise FieldError("surface_depth_required")
    if len(ds["time"]) * len(yi) * len(xi) > POLICY["limits"]["cells"]:
        raise FieldError("grid_budget")
    selection = {"time": slice(None), "lat": yi, "lon": xi, zname: 0}
    data = np.asarray(
        np.ma.filled(var[tuple(selection[d] for d in dims)], np.nan), dtype="float32"
    )
    remaining = [d for d in dims if d != zname]
    return np.transpose(data, [remaining.index(d) for d in ("time", "lat", "lon")])


def oisst(acquire, day, bbox, preliminary=False):
    date = utc(day + "T00:00:00Z")
    suffix = "_preliminary" if preliminary else ""
    url = f"https://www.ncei.noaa.gov/data/sea-surface-temperature-optimum-interpolation/v2.1/access/avhrr/{date:%Y%m}/oisst-avhrr-v02r01.{date:%Y%m%d}{suffix}.nc"
    data = acquire.fetch(url)
    with netCDF4.Dataset("oisst.nc", memory=data) as ds:
        lat, lon, yi, xi = subset_axes(ds, bbox)
        times = epochs(ds["time"])
        if (
            len(times) != 1
            or not date.timestamp() <= times[0] < date.timestamp() + 86400
        ):
            raise FieldError("source_day_mismatch")
        arrays = {
            "sst_c": netcdf_surface(
                ds, "sst", yi, xi, ("Celsius", "degree_Celsius", "degrees_C")
            )
        }
    return validate_grid(
        lat,
        lon,
        times,
        arrays,
        "noaa_oisst",
        None,
        iso(date.timestamp()),
        iso(date.timestamp() + 86400),
    ), "preliminary" if preliminary else "final"


def grib_url(product, cycle, lead, bbox):
    west, south, east, north = bbox_values(bbox)
    cycle = utc(cycle)
    if (
        cycle.hour not in (0, 6, 12, 18)
        or cycle.minute
        or cycle.second
        or not isinstance(lead, int)
        or not 0 <= lead <= 72
    ):
        raise FieldError("invalid_forecast_cycle_or_lead")
    if product == "noaa_gfs_wave":
        file = f"gfswave.t{cycle:%H}z.global.0p25.f{lead:03}.grib2"
        endpoint = "filter_gfswave.pl"
        directory = f"/gfs.{cycle:%Y%m%d}/{cycle:%H}/wave/gridded"
        fields = {
            "var_HTSGW": "on",
            "var_PERPW": "on",
            "var_DIRPW": "on",
            "lev_surface": "on",
        }
    elif product == "noaa_gfs_weather":
        file = f"gfs.t{cycle:%H}z.pgrb2.0p25.f{lead:03}"
        endpoint = "filter_gfs_0p25.pl"
        directory = f"/gfs.{cycle:%Y%m%d}/{cycle:%H}/atmos"
        fields = {
            "var_UGRD": "on",
            "var_VGRD": "on",
            "var_TMP": "on",
            "var_PRES": "on",
            "var_LAND": "on",
            "lev_10_m_above_ground": "on",
            "lev_2_m_above_ground": "on",
            "lev_surface": "on",
        }
    else:
        raise FieldError("unknown_grib_product")
    return (
        "https://nomads.ncep.noaa.gov/cgi-bin/"
        + endpoint
        + "?"
        + urllib.parse.urlencode(
            {
                "file": file,
                "dir": directory,
                **fields,
                "subregion": "",
                "leftlon": west,
                "rightlon": east,
                "toplat": north,
                "bottomlat": south,
            }
        )
    )


def decode_grib(data, product, cycle, lead):
    import eccodes as ec

    expected = {
        "noaa_gfs_wave": {
            (10, 0, 3, "surface", 0): ("wave_height_m", "m"),
            (10, 0, 11, "surface", 0): ("primary_wave_mean_period_s", "s"),
            (10, 0, 10, "surface", 0): (
                "primary_wave_direction_from_deg",
                "Degree true",
            ),
        },
        "noaa_gfs_weather": {
            (0, 2, 2, "heightAboveGround", 10): ("wind_east_m_s", "m s**-1"),
            (0, 2, 3, "heightAboveGround", 10): ("wind_north_m_s", "m s**-1"),
            (0, 0, 0, "heightAboveGround", 2): ("air_temperature_c", "K"),
            (0, 0, 0, "surface", 0): ("surface_temperature_excluded", "K"),
            (0, 3, 0, "surface", 0): ("surface_pressure_pa", "Pa"),
            (2, 0, 0, "surface", 0): ("land", "(0 - 1)"),
        },
    }[product]
    arrays, axes = {}, None
    valid = utc(cycle) + timedelta(hours=lead)
    if not data.startswith(b"GRIB"):
        raise FieldError("not_grib")
    with tempfile.TemporaryFile() as file:
        file.write(data)
        file.seek(0)
        count = 0
        while (gid := ec.codes_grib_new_from_file(file)) is not None:
            try:
                count += 1
                if count > 32:
                    raise FieldError("grib_message_budget")
                key = tuple(
                    ec.codes_get(gid, k)
                    for k in (
                        "discipline",
                        "parameterCategory",
                        "parameterNumber",
                        "typeOfLevel",
                        "level",
                    )
                )
                # NOAA encodes its wave surface flag as level 1; standard GRIB2
                # surface messages use the absent scaled level (decoded as 0).
                if product == "noaa_gfs_wave" and key[-2:] == ("surface", 1):
                    key = (*key[:-1], 0)
                if key not in expected:
                    raise FieldError("unexpected_grib_parameter")
                name, units = expected[key]
                if (
                    name in arrays
                    or ec.codes_get(gid, "units") != units
                    or ec.codes_get(gid, "gridType") != "regular_ll"
                    or ec.codes_get(gid, "uvRelativeToGrid") != 0
                ):
                    raise FieldError("grib_grid_units_or_vector_convention")
                if (
                    str(ec.codes_get(gid, "dataDate")) != utc(cycle).strftime("%Y%m%d")
                    or int(ec.codes_get(gid, "dataTime")) != utc(cycle).hour * 100
                    or str(ec.codes_get(gid, "validityDate"))
                    != valid.strftime("%Y%m%d")
                    or int(ec.codes_get(gid, "validityTime")) != valid.hour * 100
                    or ec.codes_get(gid, "stepType") != "instant"
                ):
                    raise FieldError("grib_cycle_or_valid_time_mismatch")
                ni, nj = ec.codes_get(gid, "Ni"), ec.codes_get(gid, "Nj")
                if (
                    not 2 <= ni <= 2000
                    or not 2 <= nj <= 2000
                    or ni * nj > POLICY["limits"]["cells"]
                ):
                    raise FieldError("grib_grid_budget")
                lats, lons = [
                    ec.codes_get_array(gid, k).reshape(nj, ni)
                    for k in ("latitudes", "longitudes")
                ]
                if not np.allclose(lats, lats[:, :1]) or not np.allclose(
                    lons, lons[:1, :]
                ):
                    raise FieldError("curvilinear_or_scanning_grid")
                lat, lon = lats[:, 0], (lons[0] + 180) % 360 - 180
                if axes is not None and (
                    not np.array_equal(axes[0], lat) or not np.array_equal(axes[1], lon)
                ):
                    raise FieldError("inconsistent_variable_grid")
                axes = lat, lon
                values = ec.codes_get_values(gid).reshape(nj, ni).astype("float32")
                if ec.codes_get(gid, "bitmapPresent"):
                    values[ec.codes_get_array(gid, "bitmap").reshape(nj, ni) == 0] = (
                        np.nan
                    )
                values[values == ec.codes_get(gid, "missingValue")] = np.nan
                if name == "air_temperature_c":
                    values -= np.float32(273.15)
                arrays[name] = values
            finally:
                ec.codes_release(gid)
    if set(arrays) != {v[0] for v in expected.values()}:
        raise FieldError("incomplete_grib_parameters")
    if "land" in arrays:
        arrays.pop("surface_temperature_excluded")
        land = arrays.pop("land")
        for a in arrays.values():
            a[(land != 0) | ~np.isfinite(land)] = np.nan
    return axes, arrays, valid.timestamp()


def gfs(acquire, product, cycle, leads, bbox):
    all_arrays, times, axes = {}, [], None
    for lead in leads:
        current_axes, arrays, t = decode_grib(
            acquire.fetch(grib_url(product, cycle, lead, bbox)), product, cycle, lead
        )
        if axes is not None and any(
            not np.array_equal(a, b) for a, b in zip(axes, current_axes)
        ):
            raise FieldError("inconsistent_forecast_grid")
        axes = current_axes
        for name, a in arrays.items():
            all_arrays.setdefault(name, []).append(a)
        times.append(t)
    return validate_grid(
        *axes, times, {v: np.stack(a) for v, a in all_arrays.items()}, product, cycle
    ), "forecast"


def hycom_runs(data):
    if len(data) > 1024 * 1024 or b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise FieldError("catalog_budget_or_entities")
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        raise FieldError("invalid_run_catalog") from None
    runs = []
    for node in root.iter():
        path = node.attrib.get("urlPath", "")
        match = re.fullmatch(
            r"FMRC_ESPC-D-V02_uv3z/runs/FMRC_ESPC-D-V02_uv3z_RUN_(\d{4}-\d{2}-\d{2}T\d{2}:00:00Z)",
            path,
        )
        if match:
            runs.append(match[1])
    if not runs or len(runs) > 40:
        raise FieldError("missing_run_metadata")
    return sorted(runs, reverse=True)


def hycom(acquire, cycle, leads, bbox):
    west, south, east, north = bbox_values(bbox)
    runs = hycom_runs(acquire.fetch(HYCOM_RUNS))
    if cycle not in runs:
        raise FieldError("requested_cycle_not_in_provider_catalog")
    start, end = (
        utc(cycle) + timedelta(hours=min(leads)),
        utc(cycle) + timedelta(hours=max(leads)),
    )
    path = "FMRC_ESPC-D-V02_uv3z/runs/FMRC_ESPC-D-V02_uv3z_RUN_" + cycle
    query = urllib.parse.urlencode(
        {
            "var": ["water_u", "water_v"],
            "north": north,
            "south": south,
            "west": west,
            "east": east,
            # Every second point (~1/6°) keeps a 72 h current horizon inside the grid budget.
            "horizStride": 2,
            "time_start": iso(start.timestamp()),
            "time_end": iso(end.timestamp()),
            "timeStride": 1,
            "vertCoord": 0,
            "addLatLon": "true",
            "accept": "netcdf4",
        },
        doseq=True,
    )
    data = acquire.fetch(
        "https://ncss.hycom.org/thredds/ncss/grid/" + path + "?" + query
    )
    with netCDF4.Dataset("hycom.nc", memory=data) as ds:
        lat, lon, yi, xi = subset_axes(ds, bbox)
        times = epochs(ds["time"])
        required = [utc(cycle).timestamp() + h * 3600 for h in leads]
        if not np.array_equal(times, required):
            raise FieldError("incomplete_single_run_horizon")
        # Single-run URL is pinned by the raw, retained provider catalog. Reject an internal run discrepancy too.
        if "forecast_reference_time" in ds.variables and not np.all(
            epochs(ds["forecast_reference_time"]) == utc(cycle).timestamp()
        ):
            raise FieldError("netcdf_cycle_mismatch")
        arrays = {
            out: netcdf_surface(ds, name, yi, xi, ("m/s", "m s-1"))
            for name, out in (
                ("water_u", "current_east_m_s"),
                ("water_v", "current_north_m_s"),
            )
        }
    return validate_grid(lat, lon, times, arrays, "hycom_espc", cycle), "forecast"


def cmems(acquire, product, cycle, hours, bbox, start=None):
    spec = CMEMS[product]
    west, south, east, north = bbox_values(bbox)
    info = json.loads(acquire.fetch(cmems_url(spec["dataset"], "describe", {})))
    if info.get("dataset_id") != spec["dataset"]:
        raise FieldError("cmems_catalog_mismatch")
    step = spec["step_hours"] * 3600
    if start is None:
        now = datetime.now(timezone.utc).timestamp()
        first = now // step * step
    else:
        first = utc(start).timestamp()
        if first % step:
            raise FieldError("invalid_forecast_start")
    # The dataset's last update stands in for the forecast cycle; it never post-dates the first time.
    updated = utc(info["arco_updated_date"]).timestamp() // 3600 * 3600
    issued = min(updated, first)
    if cycle and utc(cycle).timestamp() != issued:
        raise FieldError("netcdf_cycle_mismatch")
    last = first + hours * 3600
    params = {
        "variables": ",".join(spec["variables"]),
        "west": west,
        "south": south,
        "east": east,
        "north": north,
        "start": iso(first),
        "end": iso(last),
    }
    if spec["depth"]:
        params["depth"] = "surface"
    data = acquire.fetch(cmems_url(spec["dataset"], "subset", params))
    with netCDF4.Dataset("cmems.nc", memory=data) as ds:
        lat, lon = np.asarray(ds["latitude"][:]), np.asarray(ds["longitude"][:])
        if lat.ndim != 1 or lon.ndim != 1:
            raise FieldError("curvilinear_or_coordinate_budget")
        if getattr(ds["latitude"], "units", "") not in (
            "degrees_north",
            "degree_north",
        ) or getattr(ds["longitude"], "units", "") not in (
            "degrees_east",
            "degree_east",
        ):
            raise FieldError("coordinate_units")
        times = epochs(ds["time"])
        expected = np.arange(first, last + 1, step)
        if not np.array_equal(times, expected):
            raise FieldError("incomplete_single_run_horizon")
        arrays = {}
        for name, (out, units) in spec["variables"].items():
            var = ds[name]
            if getattr(var, "units", "") not in units:
                raise FieldError("variable_units")
            dims = list(var.dimensions)
            index = []
            for d in dims:
                if d == "depth":
                    # CMEMS's top model level is about 0.5 m; accept nothing deeper than 1 m.
                    if len(ds["depth"]) < 1 or float(ds["depth"][0]) > 1:
                        raise FieldError("surface_depth_required")
                    index.append(0)
                elif d in ("time", "latitude", "longitude"):
                    index.append(slice(None))
                else:
                    raise FieldError("unsupported_dimension_order")
            values = np.asarray(np.ma.filled(var[tuple(index)], np.nan), dtype="float32")
            kept = [d for d in dims if d != "depth"]
            arrays[out] = np.transpose(
                values, [kept.index(d) for d in ("time", "latitude", "longitude")]
            )
    return validate_grid(lat, lon, times, arrays, product, iso(issued)), "forecast"


def acquire_product(
    acquire, product, cycle=None, day=None, hours=24, bbox=None, start=None
):
    bbox = bbox or POLICY["bbox"]
    if (
        product not in POLICY["products"]
        or not isinstance(hours, int)
        or hours < 0
        or hours > 72
        or hours % 3
    ):
        raise FieldError("invalid_product_or_horizon")
    leads = list(range(0, hours + 1, 3))
    if product in CMEMS:
        if day:
            raise FieldError("forecast_requires_cycle")
        return cmems(acquire, product, cycle, hours, bbox, start)
    if product == "noaa_oisst":
        if cycle:
            raise FieldError("analysis_has_no_forecast_cycle")
        if day:
            try:
                return oisst(acquire, day, bbox)
            except FieldError as error:
                if str(error) != "http_404":
                    raise
                return oisst(acquire, day, bbox, preliminary=True)
        # Try newest complete daily analysis; 404 is never a green availability check.
        for days in (1, 2, 3):
            candidate = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
                "%Y-%m-%d"
            )
            for preliminary in (False, True):
                try:
                    return oisst(acquire, candidate, bbox, preliminary)
                except FieldError as error:
                    if str(error) != "http_404":
                        raise
        raise FieldError("no_recent_analysis")
    if day:
        raise FieldError("forecast_requires_cycle")
    if product == "hycom_espc":
        if cycle:
            return hycom(acquire, cycle, leads, bbox)
        for candidate in hycom_runs(acquire.fetch(HYCOM_RUNS))[:2]:
            try:
                return hycom(acquire, candidate, leads, bbox)
            except FieldError as error:
                if str(error) not in (
                    "incomplete_single_run_horizon",
                    "http_400",
                    "http_404",
                ):
                    raise
        raise FieldError("no_complete_current_forecast_run")
    if cycle:
        return gfs(acquire, product, cycle, leads, bbox)
    now = datetime.now(timezone.utc) - timedelta(hours=5)
    base = now.replace(hour=now.hour // 6 * 6, minute=0, second=0, microsecond=0)
    for back in (0, 6):
        try:
            return gfs(
                acquire,
                product,
                iso((base - timedelta(hours=back)).timestamp()),
                leads,
                bbox,
            )
        except FieldError as error:
            if str(error) != "http_404":
                raise
    raise FieldError("no_complete_forecast_cycle")
