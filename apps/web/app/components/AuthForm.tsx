"use client";
import { useState } from "react";
import type { Session } from "../../lib/product";
export default function AuthForm({
  onSuccess,
}: {
  onSuccess: (session: Session) => void;
}) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [handle, setHandle] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const response = await fetch(`/api/product/auth/${mode}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ handle, password }),
      });
      const data = await response.json();
      if (!response.ok) throw Error(data.code ?? "sign_in_unavailable");
      const check = await fetch("/api/product/auth/session", {
        cache: "no-store",
      });
      if (!check.ok) throw Error("session_unavailable");
      const session = (await check.json()) as Session;
      setPassword("");
      onSuccess(session);
    } catch (e) {
      setError(e instanceof Error ? e.message : "sign_in_unavailable");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="auth-form field-viewer">
      <div className="field-map-controls">
        <button
          disabled={busy}
          aria-pressed={mode === "login"}
          onClick={() => {
            setMode("login");
            setError("");
          }}
        >
          Sign in
        </button>
        <button
          disabled={busy}
          aria-pressed={mode === "register"}
          onClick={() => {
            setMode("register");
            setError("");
          }}
        >
          Create account
        </button>
      </div>
      <form onSubmit={submit} className="field-controls">
        <label>
          Username
          <input
            required
            autoComplete="username"
            pattern="[a-z0-9_]{3,32}"
            minLength={3}
            maxLength={32}
            disabled={busy}
            value={handle}
            onChange={(e) => setHandle(e.target.value)}
          />
          <small>3–32 lowercase letters, digits or underscores.</small>
        </label>
        <label>
          Password
          <input
            type="password"
            required
            minLength={12}
            maxLength={128}
            autoComplete={
              mode === "register" ? "new-password" : "current-password"
            }
            disabled={busy}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <small>At least 12 characters.</small>
        </label>
        <button disabled={busy}>
          {busy
            ? "Signing in…"
            : mode === "register"
              ? "Create my account"
              : "Sign in to my workspace"}
        </button>
      </form>
      {error ? (
        <p role="alert" className="notice">
          {error.replaceAll("_", " ")}. Retry when the account service is
          available.
        </p>
      ) : null}
      <p className="footnote">
        Local accounts protect saved state. Password recovery, verified email
        and multi-factor sign-in are not configured. Avoid reusing a password
        from another service.
      </p>
    </div>
  );
}
