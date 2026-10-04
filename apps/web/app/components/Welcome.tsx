"use client";
import Link from "next/link";
import { setStored, useHydrated, useStored } from "../../lib/device";
const key = "nautiq.welcome.v1";
export default function Welcome() {
  const dismissed = useStored(key) === "dismissed";
  const hydrated = useHydrated();
  if (dismissed || !hydrated) return null;
  return (
    <aside className="welcome" aria-label="Welcome">
      <p>
        <strong>New to Nautiq?</strong> A two-minute guide explains what the
        labels mean and what Nautiq will not tell you.
      </p>
      <div>
        <Link className="button-secondary" href="/start">
          Take the guide
        </Link>
        <button onClick={() => setStored(key, "dismissed")}>Dismiss</button>
      </div>
    </aside>
  );
}
