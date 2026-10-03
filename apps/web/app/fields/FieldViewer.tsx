"use client";

import {useEffect, useRef, useState, type MouseEvent} from "react";
import {fieldNumber, type FieldMetadata, type FieldSample, type FieldEvidence, type FieldRoute} from "../../lib/fields";

type Waypoint = {key: number; latitude: string; longitude: string; time: string};
const iso = (t: number) => new Date(t).toISOString();
function formTime(value: string) {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$/.test(value)) throw new Error("Enter a valid UTC time for every waypoint.");
  const result = Date.parse(`${value}${value.length === 16 ? ":00" : ""}Z`);
  if (!Number.isFinite(result)) throw new Error("Enter a valid UTC time for every waypoint.");
  return result;
}
function world(latitude: number, longitude: number, zoom: number) {
  const size = 256 * 2 ** zoom;
  const lat = Math.max(-85, Math.min(85, latitude)) * Math.PI / 180;
  return {x: (longitude + 180) / 360 * size, y: (1 - Math.asinh(Math.tan(lat)) / Math.PI) / 2 * size};
}
function inverse(x: number, y: number, zoom: number) {
  const size = 256 * 2 ** zoom;
  return {longitude: ((x / size * 360) % 360 + 540) % 360 - 180, latitude: Math.atan(Math.sinh(Math.PI * (1 - 2 * y / size))) * 180 / Math.PI};
}
const units = (value: number | null, unit: string) => `${fieldNumber(value)}${value == null ? "" : ` ${unit}`}`;

export type MapOverlay={id:string;kind:"profile"|"event"|"advisory";label:string;href:string;paths:number[][][];points:number[][]};
export default function FieldViewer({releaseId, metadata, overlays=[]}: {releaseId: string; metadata: FieldMetadata; overlays?:MapOverlay[]}) {
  const defaultVariable = metadata.derived_variables.find(v => v.includes("speed")) ?? metadata.variables[0];
  const [variable, setVariable] = useState(defaultVariable);
  const [timeIndex, setTimeIndex] = useState(0);
  const [zoom, setZoom] = useState(4);
  const [center, setCenter] = useState({latitude: (metadata.extent[1] + metadata.extent[3]) / 2, longitude: (metadata.extent[0] + metadata.extent[2]) / 2});
  const [latitude, setLatitude] = useState("12");
  const [longitude, setLongitude] = useState("72");
  const [point, setPoint] = useState<FieldEvidence<FieldSample> | null>(null);
  const [route, setRoute] = useState<FieldEvidence<FieldRoute> | null>(null);
  const [pointBusy, setPointBusy] = useState(false);
  const [routeBusy, setRouteBusy] = useState(false);
  const [error, setError] = useState("");
  const [failedTiles, setFailedTiles] = useState<string[]>([]);
  const [waypoints, setWaypoints] = useState<Waypoint[]>(() => [
    {key: 0, latitude: "12", longitude: "72", time: metadata.times[0].slice(0, 16)},
    {key: 1, latitude: "12.2", longitude: "72.2", time: iso(Date.parse(metadata.times[0]) + 3600000).slice(0, 16)},
  ]);
  const waypointKey = useRef(2);
  const pointController = useRef<AbortController | null>(null);
  const routeController = useRef<AbortController | null>(null);
  useEffect(() => () => {pointController.current?.abort(); routeController.current?.abort();}, []);
  const time = metadata.times[timeIndex];
  const variableMetadata = metadata.variable_metadata[variable];
  const origin = world(center.latitude, center.longitude, zoom);
  const tileX = Math.floor((origin.x - 384) / 256), tileY = Math.floor((origin.y - 256) / 256);
  const tiles = Array.from({length: 12}, (_, index) => {
    const x = tileX + index % 4, y = tileY + Math.floor(index / 4);
    const wrapped = ((x % 2 ** zoom) + 2 ** zoom) % 2 ** zoom;
    const href = `/fields/${releaseId}/tiles/${variable}/${zoom}/${wrapped}/${y}?${new URLSearchParams({time})}`;
    return {x: x * 256 - origin.x + 384, y: y * 256 - origin.y + 256, href, valid: y >= 0 && y < 2 ** zoom};
  });
  function invalidate() {
    pointController.current?.abort(); routeController.current?.abort(); setPoint(null); setRoute(null); setError(""); setPointBusy(false); setRouteBusy(false); setFailedTiles([]);
  }
  async function queryPoint(lat = Number(latitude), lon = Number(longitude)) {
    if (!Number.isFinite(lat) || !Number.isFinite(lon) || lat < -90 || lat > 90 || lon < -180 || lon > 180) {setError("Enter valid latitude and longitude."); return;}
    pointController.current?.abort(); const controller = new AbortController(); pointController.current = controller;
    setPointBusy(true); setError(""); setPoint(null);
    try {
      const response = await fetch(`/api/fields/sample?${new URLSearchParams({release_id: releaseId, variable, latitude: String(lat), longitude: String(lon), time})}`, {signal: controller.signal});
      if (!response.ok) throw new Error("This point query is unavailable or invalid. Check the field, time and coordinates.");
      const evidence = await response.json() as FieldEvidence<FieldSample>;
      if (!controller.signal.aborted) setPoint(evidence);
    } catch (e) {if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "Point query unavailable.");}
    finally {if (!controller.signal.aborted) setPointBusy(false);}
  }
  function mapClick(event: MouseEvent<SVGSVGElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    const p = inverse(origin.x - 384 + (event.clientX - rect.left) / rect.width * 768, origin.y - 256 + (event.clientY - rect.top) / rect.height * 512, zoom);
    setLatitude(p.latitude.toFixed(5)); setLongitude(p.longitude.toFixed(5)); void queryPoint(p.latitude, p.longitude);
  }
  async function queryRoute() {
    routeController.current?.abort(); const controller = new AbortController(); routeController.current = controller;
    setRouteBusy(true); setError(""); setRoute(null);
    try {
      const points = waypoints.map(w => ({latitude: Number(w.latitude), longitude: Number(w.longitude), time: iso(formTime(w.time))}));
      if (waypoints.some(w => !w.latitude.trim() || !w.longitude.trim()) || points.some(p => !Number.isFinite(p.latitude) || !Number.isFinite(p.longitude))) throw new Error("Complete every timed waypoint.");
      const response = await fetch("/api/fields/route", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({release_id: releaseId, variable, waypoints: points, spacing_km: 5, step_minutes: 30}), signal: controller.signal});
      if (!response.ok) throw new Error("Route unavailable or outside its limits. Use increasing UTC times, at most 32 waypoints, 1,000 km, 96 hours and 512 samples.");
      const result = await response.json() as FieldEvidence<FieldRoute>; if (!controller.signal.aborted) setRoute(result);
    } catch (e) {if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "Route query unavailable.");}
    finally {if (!controller.signal.aborted) setRouteBusy(false);}
  }
  function updateWaypoint(key: number, patch: Partial<Waypoint>) {
    routeController.current?.abort(); setRoute(null); setRouteBusy(false); setWaypoints(items => items.map(w => w.key === key ? {...w, ...patch} : w));
  }
  function addWaypoint() {
    const last = waypoints[waypoints.length - 1];
    try {
      const next = {...last, key: waypointKey.current++, time: iso(formTime(last.time) + 3600000).slice(0, 16)};
      routeController.current?.abort(); setRouteBusy(false); setRoute(null); setError(""); setWaypoints(items => [...items, next]);
    } catch (e) {setError(e instanceof Error ? e.message : "Complete the previous waypoint first.");}
  }
  const marker = point ? world(point.result.latitude, point.result.longitude, zoom) : null;
  return <section className="field-viewer"><h2>Inspect a field</h2><div className="field-controls"><label>Variable<select value={variable} onChange={e => {invalidate(); setVariable(e.target.value);}}>{[...metadata.derived_variables, ...metadata.variables].map(v => <option value={v} key={v}>{metadata.variable_metadata[v].label}</option>)}</select></label><label>Valid time (UTC)<select value={timeIndex} onChange={e => {invalidate(); setTimeIndex(Number(e.target.value));}}>{metadata.times.map((t, i) => <option value={i} key={t}>{t}</option>)}</select></label></div>
  {metadata.times.length > 1 ? <label className="field-timeline">Forecast timeline<input aria-label="Forecast timeline" type="range" min="0" max={metadata.times.length - 1} value={timeIndex} onChange={e => {invalidate(); setTimeIndex(Number(e.target.value));}} /></label> : <p>One daily analysis; the displayed representative time belongs to its full UTC day.</p>}
  <p className="footnote">{metadata.cycle ? `Cycle ${metadata.cycle} · valid ${time}` : `Daily ${metadata.kind} · representative time ${time}`} · {variableMetadata.units}</p>
  <div className="field-map-controls"><button onClick={() => {setZoom(z => Math.min(8, z + 1)); setFailedTiles([]);}} aria-label="Zoom in">+</button><button onClick={() => {setZoom(z => Math.max(0, z - 1)); setFailedTiles([]);}} aria-label="Zoom out">−</button><button onClick={() => setCenter(c => ({...c, longitude: (c.longitude + 170) % 360 - 180}))}>West</button><button onClick={() => setCenter(c => ({...c, longitude: (c.longitude + 190) % 360 - 180}))}>East</button><button onClick={() => setCenter(c => ({...c, latitude: Math.min(80, c.latitude + 10)}))}>North</button><button onClick={() => setCenter(c => ({...c, latitude: Math.max(-80, c.latitude - 10)}))}>South</button></div>
  <figure><svg className="field-map" viewBox="0 0 768 512" onClick={mapClick} role={overlays.length ? "group" : "img"} aria-label={`${variableMetadata.label} at ${time}. Click to inspect a point; the coordinate form provides keyboard access.`}><defs><pattern id="field-unavailable" width="16" height="16" patternUnits="userSpaceOnUse"><rect width="16" height="16" fill="#edf0eb"/><path d="M0 16L16 0" stroke="#d1d8cf" /></pattern></defs><rect width="768" height="512" fill="url(#field-unavailable)"/>{tiles.filter(t => t.valid).map(t => <image key={t.href} href={t.href} x={t.x} y={t.y} width="256" height="256" onError={() => setFailedTiles(ids => ids.includes(t.href) ? ids : [...ids, t.href])} />)}{route ? <polyline points={route.result.samples.map(s => {const p = world(s.latitude, s.longitude, zoom); return `${p.x - origin.x + 384},${p.y - origin.y + 256}`;}).join(" ")} fill="none" stroke="#fff" strokeWidth="3" /> : null}{overlays.map(o => <a key={o.id} href={o.href} aria-label={o.label}><title>{o.label}</title>{o.paths.map((path,i)=><path key={i} d={path.map((p,j)=>{const xy=world(p[1],p[0],zoom);return `${j?"L":"M"}${xy.x-origin.x+384},${xy.y-origin.y+256}`}).join(" ")+" Z"} fill={o.kind==="advisory"?"#c26e3733":"#23644322"} stroke={o.kind==="advisory"?"#99401e":"#236443"} strokeWidth="2"/>)}{o.points.map((p,i)=>{const xy=world(p[1],p[0],zoom);return <circle key={i} cx={xy.x-origin.x+384} cy={xy.y-origin.y+256} r="5" fill={o.kind==="event"?"#c26e37":"#163c40"} stroke="white" strokeWidth="2"/>})}</a>)}{marker ? <circle cx={marker.x - origin.x + 384} cy={marker.y - origin.y + 256} r="7" fill="#151f24" stroke="#fff" strokeWidth="3" /> : null}<text x="16" y="28" fill="#142d38" fontSize="14">Center {center.latitude.toFixed(2)}°, {center.longitude.toFixed(2)}° · zoom {zoom}</text></svg><figcaption>Web Mercator view of native cells. Hatched areas are masked or outside coverage; they do not mean zero. Click the field or enter coordinates below.</figcaption></figure>
  <div className="field-legend"><span>{variableMetadata.colors[0]} {variableMetadata.units}</span><div aria-hidden="true"/><span>{variableMetadata.colors[1]} {variableMetadata.units}</span></div>
  {failedTiles.some(href => tiles.some(t => t.href === href)) ? <p role="status">Some raster tiles are unavailable. Use the point query to check supported evidence.</p> : null}
  <form className="field-controls" onSubmit={e => {e.preventDefault(); void queryPoint();}}><label>Latitude<input type="number" step="any" min="-90" max="90" required value={latitude} onInput={e => {invalidate(); setLatitude(e.currentTarget.value);}} /></label><label>Longitude<input type="number" step="any" min="-180" max="180" required value={longitude} onInput={e => {invalidate(); setLongitude(e.currentTarget.value);}} /></label><button disabled={pointBusy}>{pointBusy ? "Sampling…" : "Sample point"}</button><button type="button" onClick={() => {const lat = Number(latitude), lon = Number(longitude); if (Number.isFinite(lat) && Number.isFinite(lon) && Math.abs(lat) <= 85 && Math.abs(lon) <= 180) setCenter({latitude: lat, longitude: lon});}}>Center view</button></form>
  <div aria-live="polite">{error ? <p className="notice">{error}</p> : null}{point ? <section><h3>{units(point.result.value, point.result.units)}</h3><p>{point.result.status} {point.result.reason ? `· ${point.result.reason}` : ""}</p><p>Requested: {point.result.latitude.toFixed(5)}°, {point.result.longitude.toFixed(5)}° at {point.result.requested_time}. Nearest contributing cell: {fieldNumber(point.result.source_distance_km)} km.</p><p>Spatial support: {point.result.spatial_support.map(p => `${p.latitude.toFixed(3)}°, ${p.longitude.toFixed(3)}° (${(p.weight * 100).toFixed(1)}%)`).join("; ") || "Unavailable"}.</p><p>Time support: {point.result.temporal_support.map(p => `${p.valid_time} (${(p.weight * 100).toFixed(1)}%)`).join("; ") || "Unavailable"}.</p></section> : null}</div>
  <section><h2>Sample a timed route</h2><p>Include outward and return legs and any stops. Every sample uses this same field release and forecast cycle. Times below are UTC. Spacing is at most 5 km and 30 minutes; this does not guarantee conditions between samples.</p><div className="table-scroll"><table><thead><tr><th>Waypoint</th><th>Latitude</th><th>Longitude</th><th>Arrival / stop time (UTC)</th><th>Action</th></tr></thead><tbody>{waypoints.map((w, i) => <tr key={w.key}><td>{i + 1}</td><td><input aria-label={`Waypoint ${i + 1} latitude`} type="number" step="any" value={w.latitude} onChange={e => updateWaypoint(w.key, {latitude: e.target.value})}/></td><td><input aria-label={`Waypoint ${i + 1} longitude`} type="number" step="any" value={w.longitude} onChange={e => updateWaypoint(w.key, {longitude: e.target.value})}/></td><td><input aria-label={`Waypoint ${i + 1} UTC time`} type="datetime-local" value={w.time} onChange={e => updateWaypoint(w.key, {time: e.target.value})}/></td><td><button disabled={waypoints.length <= 2} onClick={() => {routeController.current?.abort(); setRoute(null); setRouteBusy(false); setWaypoints(items => items.filter(p => p.key !== w.key));}}>Remove</button></td></tr>)}</tbody></table></div><div className="field-map-controls"><button disabled={waypoints.length >= 32} onClick={addWaypoint}>Add waypoint</button><button disabled={routeBusy} onClick={() => void queryRoute()}>{routeBusy ? "Sampling route…" : "Sample timed route"}</button></div>
  <div aria-live="polite">{route ? <><h3>{route.result.status} · {(route.result.available_fraction * 100).toFixed(1)}% available</h3><p>{route.result.sampling.sample_count} samples across {fieldNumber(route.result.sampling.distance_km)} km. Retained sampled range: {units(route.result.sampled_minimum, variableMetadata.units)} to {units(route.result.sampled_maximum, variableMetadata.units)}. No trip assessment.</p><details><summary>Inspect every route sample</summary><div className="table-scroll" tabIndex={0} role="region" aria-label="Route sample evidence"><table><thead><tr><th>Position</th><th>Time (UTC)</th><th>Value</th><th>State / reason</th></tr></thead><tbody>{route.result.samples.map((s, i) => <tr key={i}><td>{s.latitude.toFixed(4)}°, {s.longitude.toFixed(4)}°</td><td>{s.requested_time}</td><td>{units(s.value, s.units)}</td><td>{s.status} · {s.reason ?? "Supported"}</td></tr>)}</tbody></table></div></details></> : null}</div></section>
  </section>;
}
