// Nautiq chart style for MapLibre over OpenFreeMap's key-less OpenMapTiles vector tiles.
// Sea is the subject: deep sea-blue water, quiet sky-white land, navy labels, no road clutter.
import type { StyleSpecification } from "maplibre-gl";

export const SEA = "#123f6b";
const LAND = "#eef2f3";
const LAND_EDGE = "#c9d6de";
const INK = "#0b2341";
const INK_SOFT = "#536b83";
const SEA_LABEL = "#a9c3d9";

export const nautiqStyle: StyleSpecification = {
  version: 8,
  name: "Nautiq chart",
  glyphs: "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf",
  sources: {
    omt: { type: "vector", url: "https://tiles.openfreemap.org/planet", attribution: "© OpenMapTiles © OpenStreetMap contributors" },
  },
  layers: [
    { id: "land", type: "background", paint: { "background-color": LAND } },
    {
      id: "landcover-quiet",
      type: "fill",
      source: "omt",
      "source-layer": "landcover",
      filter: ["in", ["get", "class"], ["literal", ["wood", "grass", "farmland"]]],
      paint: { "fill-color": "#e6ecee", "fill-opacity": 0.6 },
    },
    {
      id: "water",
      type: "fill",
      source: "omt",
      "source-layer": "water",
      paint: { "fill-color": SEA, "fill-antialias": true },
    },
    {
      id: "water-shelf",
      type: "line",
      source: "omt",
      "source-layer": "water",
      filter: ["==", ["get", "class"], "ocean"],
      paint: { "line-color": "#2f6d9f", "line-width": ["interpolate", ["linear"], ["zoom"], 2, 4, 8, 14], "line-blur": ["interpolate", ["linear"], ["zoom"], 2, 4, 8, 12], "line-opacity": 0.5 },
    },
    {
      id: "coast",
      type: "line",
      source: "omt",
      "source-layer": "water",
      filter: ["==", ["get", "class"], "ocean"],
      paint: { "line-color": "#8fb1cc", "line-width": ["interpolate", ["linear"], ["zoom"], 2, 0.6, 8, 1.4] },
    },
    {
      id: "rivers",
      type: "line",
      source: "omt",
      "source-layer": "waterway",
      minzoom: 6,
      paint: { "line-color": "#9fbcd2", "line-width": 0.8 },
    },
    {
      id: "roads-major",
      type: "line",
      source: "omt",
      "source-layer": "transportation",
      minzoom: 6,
      filter: ["in", ["get", "class"], ["literal", ["motorway", "trunk", "primary"]]],
      paint: { "line-color": LAND_EDGE, "line-width": ["interpolate", ["linear"], ["zoom"], 6, 0.5, 12, 2] },
    },
    {
      id: "boundary-country",
      type: "line",
      source: "omt",
      "source-layer": "boundary",
      filter: ["all", ["==", ["get", "admin_level"], 2], ["!=", ["get", "maritime"], 1]],
      paint: { "line-color": INK_SOFT, "line-width": 0.9, "line-dasharray": [3, 2], "line-opacity": 0.55 },
    },
    {
      id: "boundary-state",
      type: "line",
      source: "omt",
      "source-layer": "boundary",
      minzoom: 4,
      filter: ["all", ["==", ["get", "admin_level"], 4], ["!=", ["get", "maritime"], 1]],
      paint: { "line-color": LAND_EDGE, "line-width": 0.7 },
    },
  ],
};

/** Label layers go on top of Nautiq's data layers, added after them. */
export const labelLayers: StyleSpecification["layers"] = [
  {
    id: "city-dot",
    type: "circle",
    source: "omt",
    "source-layer": "place",
    filter: ["all", ["==", ["get", "class"], "city"], ["<=", ["coalesce", ["get", "rank"], 99], 3]],
    minzoom: 4,
    paint: { "circle-radius": ["interpolate", ["linear"], ["zoom"], 4, 1.8, 10, 3.5], "circle-color": INK, "circle-stroke-color": LAND, "circle-stroke-width": 1 },
  },
  {
    id: "label-sea",
    type: "symbol",
    source: "omt",
    "source-layer": "water_name",
    layout: {
      "text-field": ["get", "name:en"],
      "text-font": ["Noto Sans Italic"],
      "text-size": ["interpolate", ["linear"], ["zoom"], 2, 11, 6, 15],
      "text-letter-spacing": 0.3,
      "text-transform": "uppercase",
      "text-max-width": 8,
    },
    paint: { "text-color": SEA_LABEL, "text-halo-color": SEA, "text-halo-width": 1 },
  },
  {
    id: "label-country",
    type: "symbol",
    source: "omt",
    "source-layer": "place",
    filter: ["==", ["get", "class"], "country"],
    maxzoom: 7,
    layout: {
      "text-field": ["coalesce", ["get", "name:en"], ["get", "name"]],
      "text-font": ["Noto Sans Bold"],
      "text-size": ["interpolate", ["linear"], ["zoom"], 2, 10, 6, 14],
      "text-transform": "uppercase",
      "text-letter-spacing": 0.18,
    },
    paint: { "text-color": INK_SOFT, "text-halo-color": LAND, "text-halo-width": 1.2 },
  },
  {
    id: "label-town",
    type: "symbol",
    source: "omt",
    "source-layer": "place",
    filter: ["in", ["get", "class"], ["literal", ["city", "town"]]],
    minzoom: 6.5,
    layout: {
      "text-field": ["coalesce", ["get", "name:en"], ["get", "name"]],
      "text-font": ["Noto Sans Regular"],
      "text-size": 12,
      "symbol-sort-key": ["get", "rank"],
    },
    paint: { "text-color": INK_SOFT, "text-halo-color": LAND, "text-halo-width": 1.2 },
  },
  {
    id: "label-city",
    type: "symbol",
    source: "omt",
    "source-layer": "place",
    filter: ["all", ["==", ["get", "class"], "city"], ["<=", ["coalesce", ["get", "rank"], 99], 3]],
    minzoom: 4,
    maxzoom: 6.5,
    layout: {
      "text-field": ["coalesce", ["get", "name:en"], ["get", "name"]],
      "text-font": ["Noto Sans Regular"],
      "text-size": ["interpolate", ["linear"], ["zoom"], 4, 11, 10, 15],
      "text-anchor": "left",
      "text-offset": [0.6, 0],
      "symbol-sort-key": ["get", "rank"],
    },
    paint: { "text-color": INK, "text-halo-color": LAND, "text-halo-width": 1.4 },
  },
];
