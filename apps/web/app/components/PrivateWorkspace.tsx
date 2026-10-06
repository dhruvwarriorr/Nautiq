"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  privateQuery,
  type SavedObject,
  type Session,
  type ProductPolicy,
  type ResearchFilter,
} from "../../lib/product";
import type {
  TripPolicy,
  TripRequest,
  TripResult,
  TripVerdict,
} from "../../lib/trips";
import type { FieldRelease } from "../../lib/fields";
import AccountGate, { type AccountContext } from "./AccountGate";
import PrivateJobs from "./PrivateJobs";
import ResearchExplorer from "./ResearchExplorer";
import RouteDiagram from "./RouteDiagram";
import { TripForm } from "../trips/TripForm";
import { when } from "../../lib/humanize";
import Icon, { type IconName } from "./ui/Icon";
const surfaceNames: Record<string, string> = { map: "Map", routes: "Routes", watchlists: "Places", explorer: "Research", reports: "Reports", exports: "Downloads", settings: "Settings" };
const surfaceIcons: Record<string, IconName> = { map: "chart", routes: "voyage", watchlists: "anchorline", explorer: "float", reports: "logbook", exports: "export", settings: "compass" };
const surfaces = [
  "map",
  "routes",
  "watchlists",
  "explorer",
  "reports",
  "exports",
  "settings",
];
export default function PrivateWorkspace(props: {
  surface: string;
  initial: Session | null;
  policy: ProductPolicy | null;
  tripPolicy: TripPolicy | null;
  releases: FieldRelease[];
  research: ResearchFilter;
}) {
  return (
    <>
      <nav className="workspace-nav" aria-label="Private workspace">
        <Link href="/app" aria-current={props.surface === "overview" ? "page" : undefined}>
          <Icon name="logbook" size={17} /> Overview
        </Link>
        {surfaces.map((s) => (
          <Link key={s} href={`/app/${s}`} aria-current={s === props.surface ? "page" : undefined}>
            <Icon name={surfaceIcons[s] ?? "info"} size={17} />
            {surfaceNames[s] ?? s[0].toUpperCase() + s.slice(1)}
          </Link>
        ))}
      </nav>
      <AccountGate initial={props.initial}>
        {(account) => <WorkspaceContent {...props} account={account} />}
      </AccountGate>
    </>
  );
}
function WorkspaceContent({
  surface,
  account,
  policy,
  tripPolicy,
  releases,
  research,
}: {
  surface: string;
  account: AccountContext;
  policy: ProductPolicy | null;
  tripPolicy: TripPolicy | null;
  releases: FieldRelease[];
  research: ResearchFilter;
}) {
  return surface === "settings" ? (
    <Settings account={account} />
  ) : surface === "explorer" ? (
    <ResearchExplorer initial={research} session={account.session} />
  ) : surface === "routes" ? (
    <Routes account={account} tripPolicy={tripPolicy} releases={releases} />
  ) : surface === "watchlists" ? (
    <ObjectEditor account={account} kind="watchlists" policy={policy} />
  ) : surface === "reports" || surface === "exports" ? (
    <JobCreator account={account} kind={surface} policy={policy} />
  ) : (
    <section>
      <h2>Your evidence workspace</h2>
      <p>
        Saved routes, places, trip receipts and files belong to this account.
      </p>
      <div className="place-grid">
        {surfaces.map((s) => (
          <article key={s}>
            <h2>
              <Link href={s === "map" ? "/map" : `/app/${s}`}>
                {s === "map"
                  ? "Open ocean map"
                  : s[0].toUpperCase() + s.slice(1)}
              </Link>
            </h2>
            <p>
              {s === "routes"
                ? "Save timed waypoints and retain exact trip receipts."
                : s === "watchlists"
                  ? "Save a point, named location, polygon or owned route."
                  : s === "exports"
                      ? "Create bounded private source files with attribution."
                      : s === "reports"
                        ? "Capture versioned provenance and limitations."
                        : s === "settings"
                          ? "Change your password or delete your account."
                          : s === "explorer"
                            ? "Explore original depth records and diagnostics."
                            : "Public source evidence with explicit unknown layers."}
            </p>
          </article>
        ))}
      </div>
    </section>
  );
}
function useOwned(account: AccountContext, kind: string) {
  const [items, setItems] = useState<SavedObject[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const session = account.session,
    expire = account.expire;
  const handle = useCallback(
    (e: unknown) => {
      const m = e instanceof Error ? e.message : "saved_state_unavailable";
      setError(m);
      if (m === "session_expired") expire();
    },
    [expire],
  );
  const load = useCallback(
    async (after?: string) => {
      setLoading(true);
      try {
        const data = await privateQuery<{
          items: SavedObject[];
          next_cursor: string | null;
        }>(`${kind}${after ? `?after=${after}` : ""}`, session);
        setItems((old) => (after ? [...old, ...data.items] : data.items));
        setNext(data.next_cursor);
        setError("");
      } catch (e) {
        handle(e);
      } finally {
        setLoading(false);
      }
    },
    [kind, session, handle],
  );
  useEffect(() => {
    let active = true;
    privateQuery<{ items: SavedObject[]; next_cursor: string | null }>(
      kind,
      session,
    )
      .then((d) => {
        if (active) {
          setItems(d.items);
          setNext(d.next_cursor);
          setLoading(false);
        }
      })
      .catch((e) => {
        if (active) {
          handle(e);
          setLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, [kind, session, handle]);
  async function save(name: string, data: unknown, old?: SavedObject | null) {
    try {
      const obj = await privateQuery<SavedObject>(
        `${kind}${old ? `/${old.id}` : ""}`,
        session,
        old ? "PUT" : "POST",
        { name, data },
        old?.version,
      );
      await load();
      return obj;
    } catch (e) {
      handle(e);
      return null;
    }
  }
  async function remove(obj: SavedObject) {
    try {
      await privateQuery(
        `${kind}/${obj.id}`,
        session,
        "DELETE",
        undefined,
        obj.version,
      );
      await load();
    } catch (e) {
      handle(e);
    }
  }
  return { items, next, error, loading, load, save, remove, handle, setError };
}
function Routes({
  account,
  tripPolicy,
  releases,
}: {
  account: AccountContext;
  tripPolicy: TripPolicy | null;
  releases: FieldRelease[];
}) {
  const owned = useOwned(account, "routes");
  const [editing, setEditing] = useState<SavedObject | null>(null);
  const [name, setName] = useState("");
  const [editorKey, setEditorKey] = useState(0);
  const [message, setMessage] = useState("");
  const [trips, setTrips] = useState<
    { calculation_id: string; name: string; as_of: string; status: string }[]
  >([]);
  const [receipt, setReceipt] = useState<{
    input: { request: TripRequest };
    output: TripVerdict;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const session = account.session,
    handle = owned.handle;
  const loadTrips = useCallback(async () => {
    try {
      const data = await privateQuery<{ items: typeof trips }>(
        "saved-trips",
        session,
      );
      setTrips(data.items);
    } catch (e) {
      handle(e);
    }
  }, [session, handle]);
  useEffect(() => {
    let active = true;
    privateQuery<{ items: typeof trips }>("saved-trips?limit=100", session)
      .then((d) => {
        if (active) setTrips(d.items);
      })
      .catch((e) => {
        if (active) handle(e);
      });
    return () => {
      active = false;
    };
  }, [session, handle]);
  async function saveRoute(request: TripRequest) {
    if (!name.trim()) throw Error("route_name_required");
    const saved = await owned.save(name, request, editing);
    if (saved) {
      setEditing(saved);
      setMessage("Saved route version " + saved.version);
    } else throw Error("route_not_saved");
  }
  async function saveTrip(result: TripResult) {
    try {
      await privateQuery("saved-trips", session, "POST", {
        calculation_id: result.calculation_id,
        name: name || "Retained trip",
        access_token: result.access_token,
      });
      setMessage("Saved private trip receipt. Evidence remains historical.");
      await loadTrips();
    } catch (e) {
      handle(e);
      throw e;
    }
  }
  return (
    <>
      <h2>Saved timed routes</h2>
      <p>
        At most 100 routes per account. Saved waypoints are unassessed until a
        new future trip is inspected. Edits require the version you loaded.
      </p>
      <p role="status">{owned.error.replaceAll("_", " ") || message}</p>
      {owned.loading ? (
        <p>Loading owned routes…</p>
      ) : owned.items.length === 0 ? (
        <p>No saved routes yet.</p>
      ) : (
        <ul className="owned-list">
          {owned.items.map((o) => (
            <li key={o.id}>
              <span>
                {o.name} · version {o.version}
              </span>
              <button
                onClick={() => {
                  setEditing(o);
                  setName(o.name);
                  setEditorKey((k) => k + 1);
                  setMessage("");
                }}
              >
                Edit route
              </button>
              <button onClick={() => void owned.remove(o)}>Delete route</button>
            </li>
          ))}
        </ul>
      )}
      {owned.next ? (
        <button onClick={() => void owned.load(owned.next!)}>
          More routes
        </button>
      ) : null}
      <button
        onClick={() => {
          setEditing(null);
          setName("");
          setEditorKey((k) => k + 1);
        }}
      >
        New route
      </button>
      <label className="wide-label">
        Route name
        <input
          maxLength={80}
          required
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </label>
      {tripPolicy ? (
        <TripForm
          key={editorKey}
          policy={tripPolicy}
          releases={releases}
          initialRequest={editing?.data as TripRequest | undefined}
          onSaveRoute={saveRoute}
          onSaveTrip={saveTrip}
        />
      ) : (
        <p className="notice">
          Trip policy is unavailable. Existing routes remain accessible.
        </p>
      )}
      <h2>Retained private trips</h2>
      {trips.length === 0 ? (
        <p>
          No saved trip receipts. Inspect a timed trip above, then save its
          private receipt.
        </p>
      ) : (
        <ul className="owned-list">
          {trips.map((t) => (
            <li key={t.calculation_id}>
              <span>
                {t.name} · {t.status} · {when(t.as_of)}
              </span>
              <button
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  try {
                    setReceipt(
                      await privateQuery(
                        `saved-trips/${t.calculation_id}`,
                        session,
                      ),
                    );
                  } catch (e) {
                    handle(e);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                Inspect frozen receipt
              </button>
              <button
                onClick={async () => {
                  try {
                    await privateQuery(
                      `saved-trips/${t.calculation_id}`,
                      session,
                      "DELETE",
                    );
                    setReceipt(null);
                    await loadTrips();
                  } catch (e) {
                    handle(e);
                  }
                }}
              >
                Unlink receipt
              </button>
            </li>
          ))}
        </ul>
      )}
      {receipt ? (
        <section>
          <h2>{receipt.output.wording}</h2>
          <p>
            Historical as of {when(receipt.output.as_of)}; source freshness has not
            been renewed.
          </p>
          <RouteDiagram
            points={receipt.input.request.waypoints}
            verdict={receipt.output}
          />
          <ul>
            {receipt.output.limitations.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
          <details>
            <summary>Exact frozen calculation evidence</summary>
            <pre className="audit-json">{JSON.stringify(receipt, null, 2)}</pre>
          </details>
        </section>
      ) : null}
    </>
  );
}
function ObjectEditor({
  account,
  kind,
  policy,
}: {
  account: AccountContext;
  kind: "watchlists";
  policy: ProductPolicy | null;
}) {
  const owned = useOwned(account, kind);
  const refs = useOwned(account, "routes");
  const [old, setOld] = useState<SavedObject | null>(null);
  const [name, setName] = useState("");
  const [type, setType] = useState("point");
  const [lat, setLat] = useState("19");
  const [lon, setLon] = useState("72.3");
  const [radius, setRadius] = useState("10");
  const [place, setPlace] = useState("mumbai-offshore");
  const [polygon, setPolygon] = useState("");
  const [reference, setReference] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  function edit(o: SavedObject) {
    setOld(o);
    setName(o.name);
    setType(String(o.data.type));
    setLat(String(o.data.latitude ?? 19));
    setLon(String(o.data.longitude ?? 72.3));
    setRadius(String(o.data.radius_km ?? 10));
    setPlace(String(o.data.place ?? "mumbai-offshore"));
    setPolygon(o.data.polygon ? JSON.stringify(o.data.polygon) : "");
    setReference(String(o.data.route_id ?? ""));
    setMessage("");
  }
  async function save() {
    setBusy(true);
    owned.setError("");
    try {
      const data: Record<string, unknown> = { type };
      if (type === "point") {
          if (!lat.trim() || !lon.trim() || !radius.trim())
            throw Error("coordinates_and_radius_required");
          Object.assign(data, {
            latitude: Number(lat),
            longitude: Number(lon),
            radius_km: Number(radius),
          });
      } else if (type === "place") data.place = place;
      else if (type === "route") data.route_id = reference;
      else data.polygon = JSON.parse(polygon);
      const obj = await owned.save(name, data, old);
      if (obj) {
        setOld(obj);
        setMessage("Saved version " + obj.version);
      }
    } catch (e) {
      owned.handle(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section>
      <h2>Saved places</h2>
      <p>
        Save a point with a radius up to 100 km, a named location, a closed
        polygon, or an owned timed route.
      </p>
      <p role="status">{owned.error.replaceAll("_", " ") || message}</p>
      {owned.loading ? (
        <p>Loading owned objects…</p>
      ) : owned.items.length === 0 ? (
        <p>No places saved.</p>
      ) : (
        <ul className="owned-list">
          {owned.items.map((o) => (
            <li key={o.id}>
              <span>
                {o.name} · {String(o.data.type)} · version {o.version}
              </span>
              <button onClick={() => edit(o)}>Edit</button>
              <button onClick={() => void owned.remove(o)}>Delete</button>
            </li>
          ))}
        </ul>
      )}
      {owned.next ? (
        <button onClick={() => void owned.load(owned.next!)}>
          More saved objects
        </button>
      ) : null}
      <button
        onClick={() => {
          setOld(null);
          setName("");
          setMessage("");
        }}
      >
        New place
      </button>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
      >
        <div className="field-controls">
          <label>
            Name
            <input
              required
              maxLength={80}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <label>
            Type
            <select value={type} onChange={(e) => setType(e.target.value)}>
              {["point", "place", "polygon", "route"].map((t) => (
                <option key={t} value={t}>
                  {t.replaceAll("_", " ")}
                </option>
              ))}
            </select>
          </label>
          {type === "point" ? (
            <>
              <label>
                Latitude
                <input
                  required
                  type="number"
                  step="any"
                  min={-85}
                  max={85}
                  value={lat}
                  onInput={(e) => setLat(e.currentTarget.value)}
                />
              </label>
              <label>
                Longitude
                <input
                  required
                  type="number"
                  step="any"
                  min={-180}
                  max={180}
                  value={lon}
                  onInput={(e) => setLon(e.currentTarget.value)}
                />
              </label>
              <label>
                Radius (km)
                <input
                  required
                  type="number"
                  step="any"
                  min={0}
                  max={100}
                  value={radius}
                  onInput={(e) => setRadius(e.currentTarget.value)}
                />
              </label>
            </>
          ) : null}
          {type === "place" ? (
            <label>
              Named place
              <select value={place} onChange={(e) => setPlace(e.target.value)}>
                {policy?.policy.locations.map((p) => (
                  <option key={p.slug} value={p.slug}>
                    {p.name}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          {type === "route" ? (
            <label>
              Owned route
              <select
                required
                value={reference}
                onChange={(e) => setReference(e.target.value)}
              >
                <option value="">Choose saved object</option>
                {refs.items.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
        </div>
        {type === "polygon" ? (
          <label className="wide-label">
            Closed polygon: longitude, latitude pairs
            <textarea
              required
              rows={4}
              value={polygon}
              onChange={(e) => setPolygon(e.target.value)}
              placeholder="[[65,10],[66,10],[66,11],[65,10]]"
            />
          </label>
        ) : null}
        <p>
          <button disabled={busy}>
            {busy ? "Saving…" : "Save place"}
          </button>
        </p>
      </form>
    </section>
  );
}
function JobCreator({
  account,
  kind,
  policy,
}: {
  account: AccountContext;
  kind: "exports" | "reports";
  policy: ProductPolicy | null;
}) {
  const [scope, setScope] = useState("route");
  const [target, setTarget] = useState("");
  const [place, setPlace] = useState("mumbai-offshore");
  const [trips, setTrips] = useState<
    { calculation_id: string; name: string }[]
  >([]);
  const routes = useOwned(account, "routes"),
    watches = useOwned(account, "watchlists");
  const session = account.session;
  const handle = routes.handle;
  useEffect(() => {
    privateQuery<{ items: typeof trips }>("saved-trips?limit=100", session)
      .then((d) => setTrips(d.items))
      .catch(handle);
  }, [session, handle]);
  const options =
    scope === "route"
      ? routes.items.map((o) => ({ id: o.id, name: o.name }))
      : scope === "watchlist"
        ? watches.items.map((o) => ({ id: o.id, name: o.name }))
        : trips.map((o) => ({ id: o.calculation_id, name: o.name }));
  return (
    <>
      <p>
        Reports capture provenance, references, policy and owned state. Original
        accepted Argo observations can be exported from the research explorer.
        Forecast redistribution remains unavailable.
      </p>
      <div className="field-controls">
        <label>
          Snapshot scope
          <select
            value={scope}
            onChange={(e) => {
              setScope(e.target.value);
              setTarget("");
            }}
          >
            {(kind === "exports"
              ? ["route", "watchlist"]
              : ["route", "watchlist", "trip", "location", "event"]
            ).map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
        {scope === "location" ? (
          <label>
            Location
            <select value={place} onChange={(e) => setPlace(e.target.value)}>
              {policy?.policy.locations.map((p) => (
                <option key={p.slug} value={p.slug}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
        ) : scope === "event" ? (
          <label>
            Retained event ID
            <input
              required
              value={target}
              onChange={(e) => setTarget(e.target.value)}
            />
          </label>
        ) : (
          <label>
            Owned snapshot
            <select value={target} onChange={(e) => setTarget(e.target.value)}>
              <option value="">Choose saved evidence</option>
              {options.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.name}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      <p role="status">{routes.error || watches.error}</p>
      <PrivateJobs
        account={account}
        kind={kind}
        request={
          scope === "location"
            ? { scope, place }
            : target
              ? { scope, target_id: target }
              : undefined
        }
      />
      <Link href="/app/explorer">
        Export original Argo research observations
      </Link>
    </>
  );
}
function Settings({ account }: { account: AccountContext }) {
  const [oldPassword, setOld] = useState("");
  const [newPassword, setNew] = useState("");
  const [deletePassword, setDelete] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  async function change(body: unknown, remove = false) {
    setBusy(true);
    setMessage("");
    try {
      const result = await privateQuery<{
        version: number;
        sign_in_again?: boolean;
      }>(
        "account",
        account.session,
        remove ? "DELETE" : "PATCH",
        body,
        account.session.version,
      );
      setOld("");
      setNew("");
      setDelete("");
      if (remove) account.clear();
      else if (result.sign_in_again) account.expire();
      setMessage(remove ? "Account deleted. Private files are queued for removal." : "Password changed. Sign in again.");
    } catch (e) {
      const m = e instanceof Error ? e.message : "account_unavailable";
      setMessage(m.replaceAll("_", " "));
      if (m === "session_expired") account.expire();
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <h2>Account settings</h2>
      <p>
        Local handle account: {account.session.handle}. There is no
        password recovery, so keep your password safe.
      </p>
      <p role="status">{message}</p>
      <h2>Change password</h2>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void change({ old_password: oldPassword, new_password: newPassword });
        }}
      >
        <div className="field-controls">
          <label>
            Current password
            <input
              required
              type="password"
              autoComplete="current-password"
              value={oldPassword}
              onChange={(e) => setOld(e.target.value)}
            />
          </label>
          <label>
            New password (12–128 bytes)
            <input
              required
              type="password"
              autoComplete="new-password"
              minLength={12}
              maxLength={128}
              value={newPassword}
              onChange={(e) => setNew(e.target.value)}
            />
          </label>
        </div>
        <button disabled={busy}>Change password and revoke all sessions</button>
      </form>
      <h2>Delete account</h2>
      <p>
        Deletion removes saved objects and jobs, revokes all
        sessions and schedules private artifacts and claimed trip receipts for
        removal. Unlinked anonymous receipts keep their original retention.
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void change({ password: deletePassword }, true);
        }}
      >
        <label className="wide-label">
          Confirm password
          <input
            required
            type="password"
            autoComplete="current-password"
            value={deletePassword}
            onChange={(e) => setDelete(e.target.value)}
          />
        </label>
        <p>
          <label>
            <input
              required
              type="checkbox"
              checked={confirm}
              onChange={(e) => setConfirm(e.target.checked)}
            />{" "}
            Delete this account and its private saved state
          </label>
        </p>
        <button disabled={busy || !confirm}>Delete my account</button>
      </form>
    </>
  );
}
