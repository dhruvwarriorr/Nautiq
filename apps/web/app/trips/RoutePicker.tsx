"use client";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useRef, useState } from "react";
import type { Map as MLMap, GeoJSONSource, MapMouseEvent } from "maplibre-gl";
import { nautiqStyle, labelLayers } from "../../lib/map-style";

type Stop = { latitude: number; longitude: number };

function collection(stops: Stop[], active: number): GeoJSON.FeatureCollection {
  const valid = stops.map((s, i) => ({ ...s, i })).filter((s) => Number.isFinite(s.latitude) && Number.isFinite(s.longitude));
  return {
    type: "FeatureCollection",
    features: [
      ...(valid.length > 1
        ? [{ type: "Feature" as const, properties: { kind: "route" }, geometry: { type: "LineString" as const, coordinates: valid.map((s) => [s.longitude, s.latitude]) } }]
        : []),
      ...valid.map((s) => ({
        type: "Feature" as const,
        properties: { kind: "stop", label: String(s.i + 1), active: s.i === active ? 1 : 0, first: s.i === 0 ? 1 : 0 },
        geometry: { type: "Point" as const, coordinates: [s.longitude, s.latitude] },
      })),
    ],
  };
}

/** Tap the chart to place the active stop. Numbered stops and the route follow the form. */
export default function RoutePicker({ stops, active, onPick }: { stops: Stop[]; active: number; onPick: (latitude: number, longitude: number) => void }) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MLMap | null>(null);
  const pick = useRef(onPick);
  const [ready, setReady] = useState(false);
  const [painted, setPainted] = useState(false);
  const initial = useRef({ stops, active });

  useEffect(() => {
    pick.current = onPick;
  }, [onPick]);

  useEffect(() => {
    let cancelled = false;
    let map: MLMap | null = null;
    (async () => {
      const ml = await import("maplibre-gl");
      if (cancelled || !container.current) return;
      ml.setWorkerUrl("/maplibre/maplibre-gl-worker.mjs");
      const pts = initial.current.stops.filter((s) => Number.isFinite(s.latitude) && Number.isFinite(s.longitude));
      const lons = pts.map((s) => s.longitude), lats = pts.map((s) => s.latitude);
      const pad = 1.2;
      map = new ml.Map({
        container: container.current,
        style: nautiqStyle,
        bounds: pts.length
          ? [[Math.min(...lons) - pad, Math.min(...lats) - pad], [Math.max(...lons) + pad, Math.max(...lats) + pad]]
          : [[66, 6], [90, 24]],
        attributionControl: { compact: true },
        dragRotate: false,
        pitchWithRotate: false,
        maxZoom: 12,
        minZoom: 3,
      });
      map.touchZoomRotate.disableRotation();
      mapRef.current = map;
      map.on("load", () => {
        if (!map) return;
        map.addSource("trip", { type: "geojson", data: collection(initial.current.stops, initial.current.active) });
        map.addLayer({ id: "trip-route", type: "line", source: "trip", filter: ["==", ["get", "kind"], "route"], paint: { "line-color": "#eef4f8", "line-width": 2.5, "line-dasharray": [0.4, 2.4] }, layout: { "line-cap": "round" } });
        map.addLayer({
          id: "trip-stop",
          type: "circle",
          source: "trip",
          filter: ["==", ["get", "kind"], "stop"],
          paint: {
            "circle-radius": ["case", ["==", ["get", "active"], 1], 13, 10],
            "circle-color": ["case", ["==", ["get", "first"], 1], "#0b2341", "#eef4f8"],
            "circle-stroke-color": ["case", ["==", ["get", "active"], 1], "#ffffff", "#0b2341"],
            "circle-stroke-width": ["case", ["==", ["get", "active"], 1], 3, 1.5],
          },
        });
        map.addLayer({
          id: "trip-stop-label",
          type: "symbol",
          source: "trip",
          filter: ["==", ["get", "kind"], "stop"],
          layout: { "text-field": ["get", "label"], "text-font": ["Noto Sans Bold"], "text-size": 12, "text-allow-overlap": true, "icon-allow-overlap": true },
          paint: { "text-color": ["case", ["==", ["get", "first"], 1], "#eef4f8", "#0b2341"] },
        });
        for (const l of labelLayers) map.addLayer(l);
        map.getCanvas().style.cursor = "crosshair";
        map.on("click", (e: MapMouseEvent) => pick.current(Number(e.lngLat.lat.toFixed(4)), Number(e.lngLat.lng.toFixed(4))));
        setReady(true);
      });
      const reveal = (e: { sourceId?: string; tile?: unknown }) => {
        if (e.sourceId === "omt" && e.tile) {
          setPainted(true);
          map?.off("sourcedata", reveal);
        }
      };
      map.on("sourcedata", reveal);
      map.once("idle", () => setPainted(true));
    })();
    return () => {
      cancelled = true;
      map?.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    (map.getSource("trip") as GeoJSONSource | undefined)?.setData(collection(stops, active));
  }, [stops, active, ready]);

  return (
    <figure className="route-picker">
      <div className="route-picker-map">
        {!painted ? <p className="map-loading">Loading the chart…</p> : null}
        <div ref={container} className="map-canvas" data-painted={painted} role="application" aria-label={`Chart for placing stops. Tap to move stop ${active + 1}.`} />
      </div>
      <figcaption>
        Tap the chart to put <b>stop {active + 1}</b> there. Choose another stop in the list to move it instead.
      </figcaption>
    </figure>
  );
}
