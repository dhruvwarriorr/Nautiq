"use client";
import { useEffect, useState } from "react";
import { privateQuery } from "../../lib/product";
import type { AccountContext } from "./AccountGate";

function useNotification<T>(path: string, account: AccountContext) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const session = account.session, expire = account.expire;
  useEffect(() => {
    let active = true;
    privateQuery<T>(path, session).then((value) => {
      if (active) { setData(value); setError(""); }
    }).catch((e) => {
      if (!active) return;
      const message = e instanceof Error ? e.message : "notification_service_unavailable";
      setError(message); if (message === "session_expired") expire();
    });
    return () => { active = false; };
  }, [path, session, expire, revision]);
  return { data, error, refresh: () => setRevision((v) => v + 1) };
}
type Monitoring = {
  worker_available: boolean; last_success_at: string | null;
  email_transport_configured: boolean; notifications_enabled: boolean;
  items: { rule_id: string; name: string; enabled: string; last_evaluated_at: string | null;
    last_outcome: string | null; last_reason: string | null; next_evaluation_at: string | null;
    active: boolean | null; recovery_confirmations: number | null; }[];
};
export function NotificationStatus({ account }: { account: AccountContext }) {
  const { data, error, refresh } = useNotification<Monitoring>("notification-status", account);
  return <section>
    <h2>Monitoring status</h2>
    <p role="status">{error.replaceAll("_", " ") || (data ? (data.worker_available ? "Notification worker is responding." : "Monitoring is unavailable or delayed. Existing evidence remains historical.") : "Loading monitoring status…")}</p>
    {data ? <>
      <p>Last worker success: {data.last_success_at ?? "No successful sweep retained"}. Email transport: {data.email_transport_configured ? "configured" : "unconfigured"}.</p>
      {!data.notifications_enabled ? <p className="notice">Delivery is opted out. Evaluation evidence may still be retained in your inbox.</p> : null}
      <p>A healthy worker does not establish fresh source coverage. Each rule has its own evaluation time. Personal limits are preferences; unknown conditions never establish recovery or safe conditions.</p>
      {data.items.length ? <div className="table-scroll"><table><thead><tr><th>Rule</th><th>Evaluation</th><th>Last evaluated (UTC)</th><th>Condition</th><th>Recovery confirmations</th></tr></thead><tbody>
        {data.items.map((r) => <tr key={r.rule_id}><td>{r.name} {r.enabled !== "true" ? "(disabled)" : ""}</td><td>{r.last_outcome ?? "Not evaluated"}{r.last_reason ? ` · ${r.last_reason.replaceAll("_", " ")}` : ""}</td><td>{r.last_evaluated_at ?? "—"}</td><td>{r.active ? "Active retained condition" : "No active lifecycle recorded"}</td><td>{r.recovery_confirmations ?? 0} / 2</td></tr>)}
      </tbody></table></div> : <p>No saved rules. Add an enabled rule below to request evaluation.</p>}
    </> : null}
    <button onClick={refresh}>Refresh monitoring status</button>
  </section>;
}
type EmailState = { email_transport_configured: boolean; settings: { email: string | null; verified_at: string | null; email_version: number } };
export function NotificationEmail({ account }: { account: AccountContext }) {
  const { data, error, refresh } = useNotification<EmailState>("notification-settings", account);
  const [email, setEmail] = useState("");
  const [proof, setProof] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  async function act(path: string, method: "POST" | "DELETE", body?: unknown) {
    setBusy(true); setMessage("");
    try {
      await privateQuery(path, account.session, method, body);
      setProof(""); setMessage(path.endsWith("verify") ? "Notification email verified." : method === "DELETE" ? "Notification email and pending email delivery removed." : "Check your email for a verification proof. Paste it here within 15 minutes."); refresh();
    } catch (e) {
      const m = e instanceof Error ? e.message : "email_settings_unavailable";
      setMessage(m.replaceAll("_", " ")); if (m === "session_expired") account.expire();
    } finally { setBusy(false); }
  }
  return <section>
    <h2>Notification email</h2>
    <p>Notification email is separate from sign-in and password recovery. Email alerts link to your private inbox and contain no forecast measurements, bulletin text or private coordinates.</p>
    <p role="status">{error.replaceAll("_", " ") || message}</p>
    <p>Verified recipient: {data?.settings.email ?? "None"}{data?.settings.verified_at ? ` · verified ${data.settings.verified_at}` : ""}.</p>
    {data && !data.email_transport_configured ? <p className="notice">Email transport is unconfigured. In-app evidence remains available when the worker is healthy.</p> : null}
    <form onSubmit={(e) => { e.preventDefault(); void act("notification-email", "POST", { email }); }}>
      <label className="wide-label">Email address to verify<input required type="email" autoComplete="email" maxLength={254} value={email} onChange={(e) => setEmail(e.target.value)} /></label>
      <p><button disabled={busy || !data?.email_transport_configured}>Send verification email</button></p>
    </form>
    <form onSubmit={(e) => { e.preventDefault(); void act("notification-email/verify", "POST", { proof }); }}>
      <label className="wide-label">Verification proof<input required autoComplete="off" minLength={64} maxLength={64} pattern="[a-f0-9]{64}" value={proof} onChange={(e) => setProof(e.target.value)} /></label>
      <p><button disabled={busy || !proof}>Verify notification email</button></p>
    </form>
    <button disabled={busy || !data?.settings.email} onClick={() => void act("notification-email", "DELETE")}>Remove notification email</button>
    <p>Changing or removing a recipient blocks previously queued mail for the old recipient. Repeated verification requests are limited. Delivery opt-out also applies before retries.</p>
  </section>;
}
