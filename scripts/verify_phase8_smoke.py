"""Live bounded field API/schema/HTML checks and optional measured evidence capture."""

import argparse
import io
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

import jsonschema
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
API = os.environ.get("API_URL", "http://localhost:8080")
WEB = os.environ.get("WEB_URL", "http://localhost:3000")
CONTRACT = json.loads((ROOT / "packages/schemas/fields.openapi.json").read_text())


def http(url, body=None, expected=200):
    headers = {"Content-Type": "application/json"} if body is not None else {}
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode() if body is not None else None,
        headers=headers,
    )
    try:
        response = urllib.request.urlopen(request, timeout=12)
    except urllib.error.HTTPError as e:
        response = e
    with response:
        data = response.read(2 * 1024 * 1024 + 1)
        assert response.status == expected, (response.status, url, data[:150])
        assert len(data) <= 2 * 1024 * 1024
        return data, dict(response.headers)


def get(path, body=None, expected=200):
    data, _ = http(API + "/api/v1" + path, body, expected)
    return json.loads(data)


def validate(name, value):
    jsonschema.Draft202012Validator(
        {**CONTRACT, "$ref": "#/components/schemas/" + name}
    ).validate(value)


def sample(release, variable, latitude=12.0, longitude=72.0, when=None):
    query = urllib.parse.urlencode(
        {
            "release_id": release["release_id"],
            "variable": variable,
            "latitude": latitude,
            "longitude": longitude,
            "time": when or release["metadata"]["times"][0],
        }
    )
    result = get("/fields/sample?" + query)
    validate("PointEvidence", result)
    assert (
        result["release_id"] == release["release_id"]
        and result["manifest_sha256"] == release["manifest_sha256"]
    )
    assert result["metadata"] == release["metadata"] and not result["release_approved"]
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture", action="store_true")
    args = parser.parse_args()
    catalog = get("/fields?limit=50")
    validate("Catalog", catalog)
    selected = [r for r in catalog["items"] if r["selected"]]
    assert {r["product_id"] for r in selected} == {
        "noaa_oisst",
        "noaa_gfs_wave",
        "noaa_gfs_weather",
        "hycom_espc",
    }
    reports = []
    for r in selected:
        detail = get("/fields/" + r["release_id"])
        validate("Release", detail)
        assert detail["status"] == "ready" and not detail["release_approved"]
        assert bool(detail["cycle"]) == (detail["metadata"]["kind"] == "forecast")
        variable = next(
            (v for v in r["metadata"]["derived_variables"] if "speed" in v),
            r["metadata"]["variables"][0],
        )
        start = time.perf_counter()
        point = sample(r, variable)
        elapsed = (time.perf_counter() - start) * 1000
        assert (
            point["result"]["status"] == "available"
            and point["result"]["value"] is not None
        )
        assert sample(r, variable, 0.0, 0.0)["result"]["status"] == "outside_domain"
        assert (
            sample(r, variable, when="2030-01-01T00:00:00Z")["result"]["status"]
            == "outside_horizon"
        )
        # Mumbai lies inside the regional box; no search for a nearby water cell is permitted.
        land = sample(r, variable, 19.1, 72.9)
        assert (
            land["result"]["value"] is None
            and land["result"]["status"] == "unavailable"
        )
        native_time = datetime.fromisoformat(
            r["metadata"]["times"][0].replace("Z", "+00:00")
        )
        body = {
            "release_id": r["release_id"],
            "variable": variable,
            "waypoints": [
                {"latitude": 12.0, "longitude": 72.0, "time": native_time.isoformat()},
                {
                    "latitude": 12.2,
                    "longitude": 72.2,
                    "time": (native_time + timedelta(hours=1)).isoformat(),
                },
                {
                    "latitude": 12.0,
                    "longitude": 72.0,
                    "time": (native_time + timedelta(hours=2)).isoformat(),
                },
            ],
        }
        route = get("/fields/route", body)
        validate("RouteEvidence", route)
        assert (
            route["result"]["available_fraction"] == 1
            and route["result"]["assessment"] == "not_assessed"
        )
        assert route["result"]["sampling"]["sample_count"] > 3
        assert (
            route["release_id"] == r["release_id"]
            and route["metadata"]["cycle"] == r["metadata"]["cycle"]
        )
        invalid = {**body, "waypoints": [body["waypoints"][1], body["waypoints"][0]]}
        validate("Problem", get("/fields/route", invalid, 400))
        geo = {
            "type": "Polygon",
            "coordinates": [
                [[71.5, 11.5], [72.5, 11.5], [72.5, 12.5], [71.5, 12.5], [71.5, 11.5]]
            ],
        }
        poly = get(
            "/fields/polygon",
            {
                "release_id": r["release_id"],
                "variable": variable,
                "time": r["metadata"]["times"][0],
                "geometry": geo,
            },
        )
        validate("PolygonEvidence", poly)
        assert poly["result"]["available_cells"] > 0
        tile_url = (
            f"/fields/{r['release_id']}/tiles/{variable}/4/11/7?"
            + urllib.parse.urlencode({"time": r["metadata"]["times"][0]})
        )
        png, headers = http(API + "/api/v1" + tile_url)
        image = Image.open(io.BytesIO(png))
        assert (
            image.size == (256, 256)
            and image.mode == "RGBA"
            and np.asarray(image)[:, :, 3].min() == 0
        )
        assert (
            headers["X-Field-Release-Id"] == r["release_id"]
            and headers["X-Field-Manifest-Sha256"] == r["manifest_sha256"]
        )
        frontend, _ = http(WEB + tile_url)
        assert frontend == png
        proxy, _ = http(
            WEB
            + "/api/fields/sample?"
            + urllib.parse.urlencode(
                {
                    "release_id": r["release_id"],
                    "variable": variable,
                    "latitude": 12,
                    "longitude": 72,
                    "time": r["metadata"]["times"][0],
                }
            )
        )
        validate("PointEvidence", json.loads(proxy))
        html, _ = http(WEB + "/fields/" + r["release_id"])
        assert (
            r["release_id"].encode() in html
            and b"Sample a timed route" in html
            and r["metadata"]["attribution"].encode() in html
        )
        if r["product_id"] == "noaa_gfs_weather":
            east, north = [
                sample(r, v)["result"]["value"]
                for v in ["wind_east_m_s", "wind_north_m_s"]
            ]
            assert abs(math.hypot(east, north) - point["result"]["value"]) < 1e-9
        reports.append(
            {
                "product_id": r["product_id"],
                "release_id": r["release_id"],
                "calculation_id": r["calculation_id"],
                "manifest_sha256": r["manifest_sha256"],
                "metadata": r["metadata"],
                "source_version": r["source_version"],
                "raw_artifacts": len(detail["manifest"]["raw"]),
                "zarr_objects": len(detail["manifest"]["files"]),
                "zarr_bytes": sum(
                    f["bytes"] for f in detail["manifest"]["files"].values()
                ),
                "release_code_sha256": detail["manifest"]["code_sha256"],
                "source_git_commit": detail["manifest"]["source_git_commit"],
                "runtime": detail["manifest"]["runtime"],
                "point_evidence": point,
                "point_request_ms": elapsed,
                "route_samples": route["result"]["sampling"]["sample_count"],
                "route_available_fraction": route["result"]["available_fraction"],
                "polygon_available_cells": poly["result"]["available_cells"],
                "tile_bytes": len(png),
            }
        )
    first = selected[0]
    query = urllib.parse.urlencode(
        {
            "release_id": first["release_id"],
            "variable": first["metadata"]["variables"][0],
            "latitude": 12,
            "longitude": 72,
            "time": first["metadata"]["times"][0],
        }
    )
    for suffix in ["&unknown=1", "&latitude=1"]:
        validate("Problem", get("/fields/sample?" + query + suffix, expected=400))
    validate(
        "Problem",
        get(
            "/fields/sample?" + query.replace("latitude=12", "latitude=nan"),
            expected=400,
        ),
    )
    validate(
        "Problem",
        get(
            "/fields/route",
            {
                "release_id": first["release_id"],
                "variable": first["metadata"]["variables"][0],
                "waypoints": [],
            },
            400,
        ),
    )
    capabilities = get("/capabilities")["capabilities"]
    assert (
        capabilities["field_sampling"]
        and capabilities["observations"]
        and capabilities["expected_state"]
        and capabilities["profile_anomaly_diagnostics"]
    )
    assert not any(
        capabilities[k]
        for k in ["profile_anomaly", "official_advisories", "trip_assessment"]
    )
    html, _ = http(WEB + "/fields")
    assert b"Retained releases" in html
    if args.capture:
        (ROOT / "docs/evidence/phase8-summary.json").write_text(
            json.dumps(
                {
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                    "scope": "Local retained real provider fields, API and rendered HTML; a single acquisition/replay does not prove cadence or scientific production approval. Browser interactions are recorded separately in delivery documentation.",
                    "capabilities": capabilities,
                    "products": reports,
                },
                indent=2,
            )
            + "\n"
        )
    print(
        "Live field gate passed: all four real products, schemas/exact release pins, time/domain/land refusal, timed outward/return routes, component-derived wind speed, polygon summaries, PNG and web proxies, malformed requests, rendered explorer pages and independent scientific capabilities."
    )


if __name__ == "__main__":
    main()
