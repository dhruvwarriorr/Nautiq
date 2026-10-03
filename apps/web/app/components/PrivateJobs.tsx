"use client";
import { useEffect, useState, useCallback } from "react";
import { privateQuery, type Job } from "../../lib/product";
import type { AccountContext } from "./AccountGate";
export default function PrivateJobs({
  account,
  kind,
  request,
}: {
  account: AccountContext;
  kind: "exports" | "reports";
  request?: Record<string, unknown>;
}) {
  const [items, setItems] = useState<Job[]>([]);
  const [format, setFormat] = useState(kind === "exports" ? "csv" : "html");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [next, setNext] = useState<string | null>(null);
  const session = account.session;
  const expire = account.expire;
  const load = useCallback(
    async (after?: string) => {
      try {
        const data = await privateQuery<{
          items: Job[];
          next_cursor: string | null;
        }>(`${kind}?limit=100${after ? `&after=${after}` : ""}`, session);
        setItems((old) => (after ? [...old, ...data.items] : data.items));
        setNext(data.next_cursor);
      } catch (e) {
        const message = e instanceof Error ? e.message : "jobs_unavailable";
        setError(message);
        if (message === "session_expired") expire();
      }
    },
    [kind, session, expire],
  );
  useEffect(() => {
    let active = true;
    const refresh = () => {
      if (active) void load();
    };
    refresh();
    const timer = setInterval(refresh, 5000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [load]);
  async function action(path: string, body?: unknown, version?: number) {
    setBusy(true);
    setError("");
    try {
      const data = await privateQuery<Record<string, unknown>>(
        path,
        session,
        "POST",
        body,
        version,
      );
      if (typeof data.path === "string") {
        const link = document.createElement("a");
        link.href = `/api/product${data.path}`;
        link.download = "";
        link.click();
      } else await load();
    } catch (e) {
      const message = e instanceof Error ? e.message : "job_unavailable";
      setError(message);
      if (message === "session_expired") expire();
    } finally {
      setBusy(false);
    }
  }
  return (
    <section>
      <h2>Private {kind}</h2>
      <p>
        Snapshots remain historical. Jobs expire after 72 hours. A download
        grant lasts five minutes, works once, and requires this account’s
        session.
      </p>
      {request ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void action(kind, { ...request, format });
          }}
        >
          <div className="field-controls">
            <label>
              Format
              <select
                value={format}
                onChange={(e) => setFormat(e.target.value)}
              >
                {(kind === "reports"
                  ? ["html", "json"]
                  : [
                      "csv",
                      "json",
                      "parquet",
                      ...(request.scope === "research" ? ["netcdf"] : []),
                    ]
                ).map((f) => (
                  <option key={f}>{f}</option>
                ))}
              </select>
            </label>
            <button disabled={busy}>
              Create frozen {kind === "exports" ? "export" : "report"}
            </button>
          </div>
        </form>
      ) : null}
      <p role="status">{error.replaceAll("_", " ")}</p>
      {items.length === 0 ? (
        <p>
          No {kind} for this account. Create one from a saved route, watchlist,
          retained trip, or research query.
        </p>
      ) : (
        <div
          className="table-scroll"
          role="region"
          tabIndex={0}
          aria-label={`${kind} jobs`}
        >
          <table>
            <thead>
              <tr>
                <th>Snapshot</th>
                <th>State</th>
                <th>Format</th>
                <th>Created / expires</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {items.map((j) => (
                <tr key={j.id}>
                  <td>
                    {String(j.input.scope ?? "evidence")}
                    <small className="digest">
                      {j.id}
                      <br />
                      Input {j.input_sha256}
                    </small>
                    {j.artifact_sha256 ? (
                      <small className="digest">
                        Artifact {j.artifact_sha256} · {j.artifact_bytes} bytes
                      </small>
                    ) : null}
                  </td>
                  <td>
                    {j.state}
                    {j.reason ? (
                      <small>{j.reason.replaceAll("_", " ")}</small>
                    ) : null}
                  </td>
                  <td>{j.format}</td>
                  <td>
                    {j.created_at}
                    <small>{j.expires_at}</small>
                  </td>
                  <td>
                    {j.state === "ready" ? (
                      <button
                        disabled={busy}
                        onClick={() =>
                          void action(`${kind}/${j.id}/download-grants`)
                        }
                      >
                        Download
                      </button>
                    ) : ["queued", "running"].includes(j.state) ? (
                      <button
                        disabled={busy}
                        onClick={() =>
                          void action(
                            `${kind}/${j.id}/cancel`,
                            undefined,
                            j.version,
                          )
                        }
                      >
                        Cancel
                      </button>
                    ) : (
                      <span>Unavailable</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {next ? <button onClick={() => void load(next)}>More jobs</button> : null}
      <button onClick={() => void load()}>Refresh job status</button>
    </section>
  );
}
