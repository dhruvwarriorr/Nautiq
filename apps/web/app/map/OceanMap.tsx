"use client";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import type { Map as MLMap, GeoJSONSource, MapMouseEvent, RasterTileSource, LngLatBoundsLike } from "maplibre-gl";
import type { MapOverview } from "../../lib/product";
import type { FieldEvidence, FieldSample, FieldRelease } from "../../lib/fields";
import { nautiqStyle, labelLayers } from "../../lib/map-style";
import { ago, beaufort, coords, knots, label, reading, seaState, span, when, humanizeText } from "../../lib/humanize";
import Icon, { type IconName } from "../components/ui/Icon";
import { Signal } from "../components/ui/Signal";

type LayerKey = "waves" | "wind" | "current" | "sst" | "none";
const layerDefs: { key: Exclude<LayerKey, "none">; label: string; icon: IconName; product: string; variable: string }[] = [
  { key: "waves", label: "Waves", icon: "waves", product: "cmems_wave", variable: "wave_height_m" },
  { key: "wind", label: "Wind", icon: "windsock", product: "noaa_gfs_weather", variable: "wind_speed_m_s" },
  { key: "current", label: "Currents", icon: "current", product: "cmems_currents", variable: "current_speed_m_s" },
  { key: "sst", label: "Sea temp", icon: "thermo", product: "cmems_sst", variable: "sst_c" },
];
const INDIA: LngLatBoundsLike = [[60, 2], [96, 26]];

type Selected =
  | { kind: "float"; id: string; platform: string; observed: string; lat: number; lon: number }
  | { kind: "event"; id: string; title: string; start: string; end: string }
  | { kind: "probe"; lat: number; lon: number; loading: boolean; sample: FieldSample | null; error?: string };

function geometry(value: { type: string; coordinates: unknown } | null): GeoJSON.Geometry | null {
  if (!value || !Array.isArray(value.coordinates)) return null;
  if (["Polygon", "MultiPolygon", "MultiPoint", "Point", "LineString"].includes(value.type))
    return value as unknown as GeoJSON.Geometry;
  return null;
}
const fc = (features: GeoJSON.Feature[]): GeoJSON.FeatureCollection => ({ type: "FeatureCollection", features });

function displayValue(key: LayerKey, v: number) {
  if (key === "wind") return { big: `${reading(knots(v), knots(v) < 10 ? 1 : 0)} kn`, word: beaufort(v) };
  if (key === "current") return { big: `${reading(knots(v), 1)} kn`, word: `${reading(v, 2)} m/s` };
  if (key === "waves") return { big: `${reading(v, 1)} m`, word: `${seaState(v)} sea` };
  return { big: `${reading(v, 1)} °C`, word: "Surface water" };
}
function legendText(key: LayerKey, v: number) {
  if (key === "wind" || key === "current") return `${reading(knots(v), 0)} kn`;
  if (key === "waves") return `${reading(v, 0)} m`;
  return `${reading(v, 0)}°C`;
}

export default function OceanMap({ value }: { value: MapOverview }) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MLMap | null>(null);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  const [painted, setPainted] = useState(false);
  const [layer, setLayer] = useState<LayerKey>("waves");
  const [showFloats, setFloats] = useState(true);
  const [showEvents, setEvents] = useState(true);
  const [selected, setSelected] = useState<Selected | null>(null);
  const [playing, setPlaying] = useState(false);
  // null = automatic: open on desktop, closed on phones (decided in CSS, so server and client agree).
  const [panelOpen, setPanelOpen] = useState<boolean | null>(null);

  const releases = useMemo(() => {
    const out: Partial<Record<LayerKey, FieldRelease>> = {};
    for (const d of layerDefs) {
      const list = value.fields.filter((f) => f.product_id === d.product);
      out[d.key] = list.find((f) => f.selected) ?? list[0];
    }
    return out;
  }, [value.fields]);
  const def = layerDefs.find((d) => d.key === layer);
  const release = layer === "none" ? undefined : releases[layer];
  const times = useMemo(() => release?.metadata.times ?? [], [release]);
  const [openedAt] = useState(() => Date.now());
  const nearest = useMemo(() => {
    const now = openedAt;
    let best = 0;
    times.forEach((t, i) => {
      if (Math.abs(Date.parse(t) - now) < Math.abs(Date.parse(times[best]) - now)) best = i;
    });
    return best;
  }, [times, openedAt]);
  const [timeIndex, setTimeIndex] = useState<number | null>(null);
  const ti = Math.min(timeIndex ?? nearest, Math.max(0, times.length - 1));
  const time = times[ti];
  const variable = def && release ? (release.metadata.derived_variables.includes(def.variable) || release.metadata.variables.includes(def.variable) ? def.variable : release.metadata.variables[0]) : undefined;
  const vm = variable && release ? release.metadata.variable_metadata[variable] : undefined;
  const tileUrl = release && variable && time ? `/fields/${release.release_id}/tiles/${variable}/{z}/{x}/{y}?${new URLSearchParams({ time })}` : null;

  const data = useMemo(() => {
    const floats = fc(
      value.profiles.map((p) => ({
        type: "Feature",
        geometry: { type: "Point", coordinates: [p.longitude, p.latitude] },
        properties: { id: p.id, platform: p.platform_id, observed: p.observed_at },
      })),
    );
    const events = fc(
      value.events.flatMap((e) => {
        const g = geometry(e.geometry);
        return g ? [{ type: "Feature" as const, geometry: g, properties: { id: e.event_id, title: label(e.kind), start: e.start, end: e.end } }] : [];
      }),
    );
    return { floats, events };
  }, [value]);

  // Create the map once.
  useEffect(() => {
    let cancelled = false;
    let map: MLMap | null = null;
    (async () => {
      try {
        const ml = await import("maplibre-gl");
        if (cancelled || !container.current) return;
        // The worker ships from /public so the bundler never has to resolve it (same version as the package).
        ml.setWorkerUrl("/maplibre/maplibre-gl-worker.mjs");
        map = new ml.Map({
          container: container.current,
          style: nautiqStyle,
          bounds: INDIA,
          fitBoundsOptions: { padding: { top: 40, bottom: 40, left: window.innerWidth > 900 ? 400 : 20, right: 40 } },
          attributionControl: { compact: true },
          dragRotate: false,
          pitchWithRotate: false,
          maxZoom: 10,
          minZoom: 2,
        });
        map.touchZoomRotate.disableRotation();
        mapRef.current = map;
        map.on("error", () => {});
        map.on("load", () => {
          if (!map) return;
          map.addSource("events", { type: "geojson", data: data.events });
          map.addSource("floats", { type: "geojson", data: data.floats, cluster: true, clusterRadius: 44, clusterMaxZoom: 6 });
          map.addSource("probe", { type: "geojson", data: fc([]) });
          // Forecast coverage is a fixed box; frame it as a chart neatline so its edge reads as intended.
          const ext = value.fields[0]?.metadata.extent;
          if (ext) {
            const [w, s, e, n] = ext;
            map.addSource("coverage", {
              type: "geojson",
              data: fc([
                { type: "Feature", properties: { line: 1 }, geometry: { type: "LineString", coordinates: [[w, s], [w, n], [e, n], [e, s], [w, s]] } },
              ]),
            });
          }
          if (map.getSource("coverage")) {
            map.addLayer({ id: "coverage-line", type: "line", source: "coverage", filter: ["==", ["geometry-type"], "LineString"], paint: { "line-color": "#b7cadb", "line-width": 1, "line-dasharray": [4, 3], "line-opacity": 0.7 } });
          }
          map.addLayer({ id: "events-fill", type: "fill", source: "events", filter: ["==", ["geometry-type"], "Polygon"], paint: { "fill-color": "#9fd0f5", "fill-opacity": 0.14 } });
          map.addLayer({ id: "events-line", type: "line", source: "events", filter: ["==", ["geometry-type"], "Polygon"], paint: { "line-color": "#9fd0f5", "line-width": 1.6, "line-dasharray": [2, 1.5] } });
          map.addLayer({ id: "events-points", type: "circle", source: "events", filter: ["==", ["geometry-type"], "Point"], paint: { "circle-radius": 7, "circle-color": "rgba(159,208,245,0.16)", "circle-stroke-color": "#9fd0f5", "circle-stroke-width": 1.6 } });
          map.addLayer({ id: "floats-cluster", type: "circle", source: "floats", filter: ["has", "point_count"], paint: { "circle-radius": ["step", ["get", "point_count"], 13, 10, 16, 30, 20], "circle-color": "rgba(238,244,248,0.14)", "circle-stroke-color": "#eef4f8", "circle-stroke-width": 1.4 } });
          map.addLayer({ id: "floats-count", type: "symbol", source: "floats", filter: ["has", "point_count"], layout: { "text-field": ["get", "point_count_abbreviated"], "text-font": ["Noto Sans Bold"], "text-size": 12 }, paint: { "text-color": "#eef4f8" } });
          map.addLayer({ id: "floats-halo", type: "circle", source: "floats", filter: ["!", ["has", "point_count"]], paint: { "circle-radius": ["interpolate", ["linear"], ["zoom"], 3, 6, 8, 11], "circle-color": "rgba(238,244,248,0.16)" } });
          map.addLayer({ id: "floats", type: "circle", source: "floats", filter: ["!", ["has", "point_count"]], paint: { "circle-radius": ["interpolate", ["linear"], ["zoom"], 3, 3.6, 8, 5.5], "circle-color": "#eef4f8", "circle-stroke-color": "#0b2341", "circle-stroke-width": 1.2 } });
          map.addLayer({ id: "probe-staff", type: "circle", source: "probe", paint: { "circle-radius": 14, "circle-color": "rgba(255,255,255,0.18)", "circle-stroke-color": "#ffffff", "circle-stroke-width": 2 } });
          map.addLayer({ id: "probe", type: "circle", source: "probe", paint: { "circle-radius": 5, "circle-color": "#ffffff", "circle-stroke-color": "#0b2341", "circle-stroke-width": 1.5 } });
          for (const l of labelLayers) map.addLayer(l);
          const hit = ["floats-cluster", "floats", "events-fill", "events-points"];
          for (const id of hit) {
            map.on("mouseenter", id, () => map && (map.getCanvas().style.cursor = "pointer"));
            map.on("mouseleave", id, () => map && (map.getCanvas().style.cursor = ""));
          }
          map.on("click", (e: MapMouseEvent) => {
            if (!map) return;
            const features = map.queryRenderedFeatures(e.point, { layers: hit.filter((h) => map!.getLayer(h)) });
            const f = features[0];
            const set = map.getSource("probe") as GeoJSONSource;
            if (f) {
              set.setData(fc([]));
              const p = f.properties as Record<string, string>;
              if (f.layer.id === "floats-cluster") {
                const [lon, lat] = (f.geometry as GeoJSON.Point).coordinates;
                map.easeTo({ center: [lon, lat], zoom: Math.min(map.getZoom() + 2, 9), duration: 500 });
                return;
              }
              if (f.layer.id === "floats") {
                const [lon, lat] = (f.geometry as GeoJSON.Point).coordinates;
                setSelected({ kind: "float", id: p.id, platform: p.platform, observed: p.observed, lat, lon });
              } else setSelected({ kind: "event", id: p.id, title: p.title, start: p.start, end: p.end });
              return;
            }
            const { lng, lat } = e.lngLat;
            set.setData(fc([{ type: "Feature", geometry: { type: "Point", coordinates: [lng, lat] }, properties: {} }]));
            window.dispatchEvent(new CustomEvent("nautiq:probe", { detail: { lat, lon: lng } }));
          });
          setReady(true);
        });
        // Reveal as soon as the first chart tile arrives, rather than waiting for every layer.
        const reveal = (e: { sourceId?: string; tile?: unknown }) => {
          if (e.sourceId === "omt" && e.tile) {
            setPainted(true);
            map?.off("sourcedata", reveal);
          }
        };
        map.on("sourcedata", reveal);
        map.once("idle", () => setPainted(true));
      } catch {
        if (!cancelled) setFailed(true);
      }
    })();
    return () => {
      cancelled = true;
      map?.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Probe: sample the active forecast layer where the user tapped the water.
  const probeArgs = useRef({ release, variable, time, layer });
  useEffect(() => {
    probeArgs.current = { release, variable, time, layer };
  }, [release, variable, time, layer]);
  useEffect(() => {
    let control: AbortController | null = null;
    async function onProbe(e: Event) {
      const { lat, lon } = (e as CustomEvent<{ lat: number; lon: number }>).detail;
      const a = probeArgs.current;
      control?.abort();
      if (!a.release || !a.variable || !a.time) {
        setSelected({ kind: "probe", lat, lon, loading: false, sample: null, error: "Choose a forecast layer to read the sea here." });
        return;
      }
      control = new AbortController();
      setSelected({ kind: "probe", lat, lon, loading: true, sample: null });
      try {
        const r = await fetch(`/api/fields/sample?${new URLSearchParams({ release_id: a.release.release_id, variable: a.variable, latitude: String(lat), longitude: String(lon), time: a.time })}`, { signal: control.signal });
        if (!r.ok) throw Error();
        const ev = (await r.json()) as FieldEvidence<FieldSample>;
        setSelected({ kind: "probe", lat, lon, loading: false, sample: ev.result });
      } catch {
        if (!control.signal.aborted) setSelected({ kind: "probe", lat, lon, loading: false, sample: null, error: "No reading here. This spot may be land or outside the forecast area." });
      }
    }
    window.addEventListener("nautiq:probe", onProbe);
    return () => {
      window.removeEventListener("nautiq:probe", onProbe);
      control?.abort();
    };
  }, []);

  // Forecast raster.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const src = map.getSource("field") as RasterTileSource | undefined;
    if (!tileUrl) {
      if (map.getLayer("field")) map.removeLayer("field");
      if (src) map.removeSource("field");
      return;
    }
    if (src && "setTiles" in src) src.setTiles([tileUrl]);
    else {
      map.addSource("field", { type: "raster", tiles: [tileUrl], tileSize: 256, maxzoom: 8 });
      map.addLayer({ id: "field", type: "raster", source: "field", paint: { "raster-opacity": 0.82, "raster-fade-duration": 250, "raster-resampling": "linear" } }, "coast");
    }
  }, [tileUrl, ready]);

  // Overlay visibility.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const vis = (ids: string[], on: boolean) => ids.forEach((id) => map.getLayer(id) && map.setLayoutProperty(id, "visibility", on ? "visible" : "none"));
    vis(["floats", "floats-halo", "floats-cluster", "floats-count"], showFloats);
    vis(["events-fill", "events-line", "events-points"], showEvents);
  }, [showFloats, showEvents, ready]);

  // Play through forecast hours.
  useEffect(() => {
    if (!playing || times.length < 2) return;
    const id = window.setInterval(() => setTimeIndex((i) => ((i ?? nearest) + 1) % times.length), 1400);
    return () => window.clearInterval(id);
  }, [playing, times.length, nearest]);

  const zoom = (d: number) => mapRef.current?.easeTo({ zoom: (mapRef.current.getZoom() ?? 4) + d, duration: 300 });

  return (
    <div className="map-shell">
      {!painted && !failed ? (
        <p className="map-loading" role="status">
          Loading the chart…
        </p>
      ) : null}
      <div ref={container} className="map-canvas" data-painted={painted} role="application" aria-label="Ocean map of India's seas. Tap the water to read the forecast at that spot." />
      {failed ? (
        <div className="map-failed">
          <p>The map couldn’t start in this browser. The list below has everything on it.</p>
        </div>
      ) : null}

      <aside className="map-panel" data-open={panelOpen === null ? "auto" : String(panelOpen)} aria-label="Map controls">
        <button className="map-panel-handle" onClick={() => setPanelOpen((o) => !(o ?? false))} aria-expanded={panelOpen ?? undefined}>
          <Icon name="layers" size={20} />
          <span>{panelOpen ? "Hide controls" : "Layers and time"}</span>
        </button>
        <div className="map-panel-body">
          <div className="map-panel-head">
            <h1>Ocean map</h1>
            <p>Tap the water to read the sea at that spot.</p>
          </div>

          <fieldset className="map-group">
            <legend>Forecast layer</legend>
            <div className="layer-picker" role="radiogroup" aria-label="Forecast layer">
              {layerDefs.map((d) => {
                const r = releases[d.key];
                return (
                  <button
                    key={d.key}
                    role="radio"
                    aria-checked={layer === d.key}
                    disabled={!r}
                    onClick={() => {
                      setLayer(layer === d.key ? "none" : d.key);
                      setTimeIndex(null);
                      setPlaying(false);
                    }}
                  >
                    <Icon name={d.icon} size={22} />
                    <span>{d.label}</span>
                  </button>
                );
              })}
            </div>
            {release && vm ? (
              <div className="layer-info">
                <div className="legend-bar" aria-hidden="true" />
                <div className="legend-ends">
                  <span>{legendText(layer, vm.colors[0])}</span>
                  <span>{legendText(layer, vm.colors[1])}</span>
                </div>
                <p className="layer-source">
                  <Signal status={release.freshness === "available" ? "available" : release.freshness === "stale" ? "stale" : "unknown"} size={13}>
                    {release.freshness === "available" ? "Fresh" : label(release.freshness)}
                  </Signal>
                  <span>
                    {release.metadata.kind === "forecast" ? `Issued ${when(release.cycle ?? release.metadata.cycle)}` : "Daily satellite analysis"}
                  </span>
                </p>
              </div>
            ) : (
              <p className="layer-source muted">No forecast layer shown.</p>
            )}
          </fieldset>

          {times.length > 1 ? (
            <fieldset className="map-group">
              <legend>Forecast time</legend>
              <div className="scrubber">
                <button className="scrub-play" onClick={() => setPlaying((p) => !p)} aria-label={playing ? "Pause" : "Play through forecast hours"}>
                  <Icon name={playing ? "pause" : "play"} size={18} />
                </button>
                <div className="scrub-track">
                  <p className="scrub-label" aria-live="polite">{time ? when(time) : ""}</p>
                  <input
                    type="range"
                    min={0}
                    max={times.length - 1}
                    value={ti}
                    aria-label="Forecast time"
                    aria-valuetext={time ? when(time) : undefined}
                    onChange={(e) => {
                      setPlaying(false);
                      setTimeIndex(Number(e.target.value));
                    }}
                  />
                  <div className="scrub-ends">
                    <span>{when(times[0])}</span>
                    <span>{when(times[times.length - 1])}</span>
                  </div>
                </div>
              </div>
            </fieldset>
          ) : time ? (
            <p className="layer-source muted">Showing {when(time)}</p>
          ) : null}

          <fieldset className="map-group">
            <legend>On the map</legend>
            <label className="toggle">
              <span className="toggle-icon toggle-float" aria-hidden="true" />
              <span className="toggle-text">
                <b>Argo floats</b>
                <span>{value.profiles.length >= 200 ? "Latest 200 readings" : `${value.profiles.length} readings`} · grouped until you zoom in</span>
              </span>
              <input type="checkbox" role="switch" checked={showFloats} onChange={(e) => setFloats(e.target.checked)} />
            </label>
            <label className="toggle">
              <span className="toggle-icon toggle-event" aria-hidden="true" />
              <span className="toggle-text">
                <b>Unusual patches</b>
                <span>{value.events.length ? `${value.events.length} found in past data` : "None found"}</span>
              </span>
              <input type="checkbox" role="switch" checked={showEvents} onChange={(e) => setEvents(e.target.checked)} />
            </label>
          </fieldset>
          <p className="map-note">
            <Icon name="info" size={16} /> Floats and patches cover {span(value.start, value.end)}.
          </p>
        </div>
      </aside>

      {selected ? (
        <section className="map-card" aria-live="polite">
          <button className="map-card-close" onClick={() => setSelected(null)} aria-label="Close">
            <Icon name="close" size={18} />
          </button>
          {selected.kind === "float" ? (
            <>
              <p className="map-card-kind"><Icon name="float" size={18} /> Argo float</p>
              <h2>Float {selected.platform}</h2>
              <p>Reading taken {ago(selected.observed)}, {when(selected.observed)}</p>
              <p className="muted">{coords(selected.lat, selected.lon)}</p>
              <Link className="btn" href={`/profiles/${selected.id}`}>See readings by depth <Icon name="arrow" size={18} /></Link>
            </>
          ) : selected.kind === "event" ? (
            <>
              <p className="map-card-kind"><Icon name="ripple" size={18} /> Unusual patch</p>
              <h2>{selected.title}</h2>
              <p>{span(selected.start, selected.end)}</p>
              <p className="muted">Found in past data. It is not a live warning.</p>
              <Link className="btn" href={`/events/${selected.id}`}>Open the evidence <Icon name="arrow" size={18} /></Link>
            </>
          ) : (
            <>
              <p className="map-card-kind"><Icon name="pin" size={18} /> {def ? def.label : "This spot"}</p>
              {selected.loading ? (
                <h2 className="loading-line">Reading the sea…</h2>
              ) : selected.sample && selected.sample.value != null ? (
                <>
                  <h2 className="probe-value">{displayValue(layer, selected.sample.value).big}</h2>
                  <p className="probe-word">{displayValue(layer, selected.sample.value).word}</p>
                  <p>Forecast for {when(selected.sample.requested_time)}</p>
                </>
              ) : (
                <>
                  <h2>No reading here</h2>
                  <p className="muted">{selected.error ?? (selected.sample?.reason ? humanizeText(selected.sample.reason) : "This spot has no forecast value.")}</p>
                </>
              )}
              <p className="muted">{coords(selected.lat, selected.lon)}</p>
              <Link className="btn-ghost" href={`/trips?lat=${selected.lat.toFixed(3)}&lon=${selected.lon.toFixed(3)}`}>
                <Icon name="voyage" size={18} /> Plan a trip from here
              </Link>
            </>
          )}
        </section>
      ) : null}

      <div className="map-zoom" role="group" aria-label="Zoom">
        <button onClick={() => zoom(1)} aria-label="Zoom in"><Icon name="plus" size={20} /></button>
        <button onClick={() => zoom(-1)} aria-label="Zoom out"><Icon name="minus" size={20} /></button>
        <button onClick={() => mapRef.current?.fitBounds(INDIA, { padding: 40, duration: 600 })} aria-label="Show all of India's seas"><Icon name="compass" size={20} /></button>
      </div>
    </div>
  );
}
