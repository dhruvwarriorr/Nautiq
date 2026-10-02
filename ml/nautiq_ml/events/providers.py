"""Retained, bounded annual NOAA PSL NCSS subsets; no arbitrary remote URL input."""

import tempfile
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from datetime import datetime, timezone
from pathlib import Path

import netCDF4
import numpy as np
from psycopg.types.json import Jsonb

from ..argo.storage import read_object, put_immutable
from ..fields.providers import epochs, subset_axes
from ..phase0.acquire import Store, ProbeError
from .core import EventError, POLICY, days, daily


def source_url(year, start, end, bbox):
    west, south, east, north = map(float, bbox)
    if (
        not -180 <= west < east <= 180
        or not -80 <= south < north <= 80
        or (east - west) * (north - south) > 256
    ):
        raise EventError("event_bbox_budget")
    params = {
        "var": "sst",
        "north": north,
        "south": south,
        "west": west,
        "east": east,
        "time_start": start + "T00:00:00Z",
        "time_end": end + "T00:00:00Z",
        "accept": "netcdf",
    }
    return (
        POLICY["source"]["endpoint"]
        + f"sst.day.mean.{year}.nc?"
        + urllib.parse.urlencode(params)
    )


class Acquisition:
    def __init__(self, db, s3, directory, offline=False, receipts=None, refresh=False):
        self.db, self.s3, self.receipts, self.offline = db, s3, [], offline
        self.refresh = refresh
        self.retained = {r["url"]: r for r in (receipts or [])}
        self.directory = Path(directory)
        self.lock = Lock()
        self.bytes = 0

    def fetch(self, url):
        prior = self.retained.get(url)
        if prior is None and not self.offline and not self.refresh:
            row = self.db.execute(
                "SELECT receipt FROM event_source_requests WHERE url=%s", (url,)
            ).fetchone()
            prior = row["receipt"] if row else None
        if prior:
            data = read_object(
                self.s3, prior["raw_key"], prior["sha256"], limit=prior["bytes"]
            )
            receipt = prior
        elif self.offline:
            raise EventError("retained_request_missing")
        else:
            try:
                from ..argo.storage import digest

                cache = Store(
                    self.directory / digest(url.encode()),
                    {
                        "request_deadline_seconds": POLICY["limits"][
                            "source_deadline_seconds"
                        ],
                        "timeout_seconds": POLICY["limits"]["source_timeout_seconds"],
                        "attempts": 2,
                        "max_object_bytes": POLICY["limits"]["raw_bytes"],
                        "max_total_download_bytes": POLICY["limits"]["raw_bytes"] * 2,
                    },
                )
                path, r = cache.fetch(url, ["www.psl.noaa.gov"])
            except ProbeError as error:
                raise EventError(str(error)) from None
            data = path.read_bytes()
            receipt = {
                k: r[k]
                for k in (
                    "url",
                    "sha256",
                    "bytes",
                    "last_modified",
                    "etag",
                    "content_type",
                )
            }
            receipt["raw_key"] = "events/raw/" + r["sha256"]
            put_immutable(self.s3, receipt["raw_key"], data)
            self.db.execute(
                "INSERT INTO event_source_requests(url,receipt) VALUES(%s,%s) ON CONFLICT(url) DO UPDATE SET receipt=excluded.receipt,checked_at=now()",
                (url, Jsonb(receipt)),
            )
        with self.lock:
            self.bytes += len(data)
            if self.bytes > POLICY["limits"]["download_bytes"]:
                raise EventError("history_download_budget")
            self.receipts.append(receipt)
        return data


def decode(data, bbox, start, end):
    with netCDF4.Dataset("oisst-archive.nc", memory=data) as ds:
        lat, lon, yi, xi = subset_axes(ds, bbox)
        if len(lat) * len(lon) > POLICY["limits"]["cells"]:
            raise EventError("event_grid_budget")
        variable = ds["sst"]
        if set(variable.dimensions) != {"time", "lat", "lon"} or getattr(
            variable, "units", ""
        ) not in ("degC", "degree_Celsius", "degrees_C", "Celsius"):
            raise EventError("archive_sst_units_or_dimensions")
        times = epochs(ds["time"])
        expected = days(start, end, POLICY["limits"]["history_days"])
        actual = [
            datetime.fromtimestamp(t, timezone.utc).date().isoformat() for t in times
        ]
        if (
            not actual
            or len(set(actual)) != len(actual)
            or actual != sorted(actual)
            or not set(actual).issubset(expected)
            or len(expected) * len(lat) * len(lon) * 4 > POLICY["limits"]["array_bytes"]
        ):
            raise EventError("incomplete_daily_archive_window")
        selection = {"time": slice(None), "lat": yi, "lon": xi}
        values = np.asarray(
            np.ma.filled(
                variable[tuple(selection[d] for d in variable.dimensions)], np.nan
            ),
            dtype="float32",
        )
        values = np.transpose(
            values, [variable.dimensions.index(d) for d in ("time", "lat", "lon")]
        )
    lat_order, lon_order = np.argsort(lat), np.argsort(lon)
    lat, lon = lat[lat_order], lon[lon_order]
    values = values[:, lat_order][:, :, lon_order]
    complete = np.full((len(expected), len(lat), len(lon)), np.nan, dtype="float32")
    positions = {d: i for i, d in enumerate(expected)}
    complete[[positions[d] for d in actual]] = values
    daily(complete, expected, lat, lon, POLICY["limits"]["history_days"])
    return complete, expected, lat, lon


def acquire(db, s3, start, end, bbox, offline=False, receipts=None, refresh=False):
    requested = days(start, end, POLICY["limits"]["history_days"])
    values, dates, lat, lon = [], [], None, None
    with tempfile.TemporaryDirectory() as directory:
        fetcher = Acquisition(db, s3, directory, offline, receipts, refresh)
        requests = []
        for year in range(int(start[:4]), int(end[:4]) + 1):
            for a, b in (
                (f"{year}-01-01", f"{year}-03-31"),
                (f"{year}-04-01", f"{year}-06-30"),
                (f"{year}-07-01", f"{year}-09-30"),
                (f"{year}-10-01", f"{year}-12-31"),
            ):
                a, b = max(a, start), min(b, end)
                if a <= b:
                    requests.append((a, b, source_url(year, a, b, bbox)))
        with ThreadPoolExecutor(
            max_workers=POLICY["limits"]["source_concurrency"]
        ) as pool:
            for (a, b, _), data in zip(
                requests, pool.map(fetcher.fetch, (r[2] for r in requests))
            ):
                # NetCDF decoding stays sequential: its C library is not thread safe.
                array, part, y, x = decode(data, bbox, a, b)
                if lat is not None and (
                    not np.array_equal(y, lat) or not np.array_equal(x, lon)
                ):
                    raise EventError("incompatible_archive_grids")
                lat, lon = y, x
                values.append(array)
                dates.extend(part)
                if (
                    len(dates) * len(lat) * len(lon) * 4
                    > POLICY["limits"]["array_bytes"]
                ):
                    raise EventError("history_expanded_budget")
        if dates != requested:
            raise EventError("incomplete_archive")
        return (
            np.concatenate(values),
            dates,
            lat,
            lon,
            sorted(fetcher.receipts, key=lambda r: r["url"]),
        )
