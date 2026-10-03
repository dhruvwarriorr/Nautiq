"use client";
import { useState } from "react";
import Link from "next/link";
import {
  privateQuery,
  clearPrivateRequests,
  type Session,
} from "../../lib/product";
import AuthForm from "./AuthForm";
export type AccountContext = {
  session: Session;
  expire: () => void;
  clear: () => void;
  update: (session: Session) => void;
};
export default function AccountGate({
  initial,
  children,
}: {
  initial: Session | null;
  children: (context: AccountContext) => React.ReactNode;
}) {
  const [current, setCurrent] = useState(initial);
  const [last, setLast] = useState(initial);
  const [error, setError] = useState("");
  function signedIn(session: Session) {
    if (last && last.account_id !== session.account_id)
      clearPrivateRequests(last.account_id);
    setCurrent(session);
    setLast(session);
    setError("");
  }
  async function logout() {
    if (!current) return;
    try {
      await privateQuery("auth/logout", current, "POST");
      clearPrivateRequests(current.account_id);
      setCurrent(null);
      setLast(null);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "sign_out_unavailable");
    }
  }
  return (
    <>
      {current ? (
        <div className="account-bar">
          <span>Signed in as {current.handle}</span>
          <button onClick={() => void logout()}>
            Sign out and clear this tab’s private drafts
          </button>
        </div>
      ) : (
        <section>
          <h2>
            {last
              ? "Your session ended. Your draft remains in this tab."
              : "Sign in to save and export evidence."}
          </h2>
          <p>
            Public exploration stays available. Signing in as a different
            account clears the previous account’s draft.
          </p>
          <AuthForm onSuccess={signedIn} />
        </section>
      )}
      {error ? (
        <p role="alert" className="notice">
          {error.replaceAll("_", " ")}
        </p>
      ) : null}
      {last ? (
        <div hidden={!current} key={last.account_id}>
          {children({
            session: current ?? last,
            expire: () => setCurrent(null),
            clear: () => {
              clearPrivateRequests(last.account_id);
              setCurrent(null);
              setLast(null);
            },
            update: signedIn,
          })}
        </div>
      ) : null}
      <p>
        <Link href="/map">Public map</Link> ·{" "}
        <Link href="/research">Public research explorer</Link>
      </p>
    </>
  );
}
