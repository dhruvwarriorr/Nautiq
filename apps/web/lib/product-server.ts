import "server-only";
import { cookies } from "next/headers";
import { apiURL } from "./profiles";
import type { Session } from "./product";
export const sessionCookie = "nautiq_session";
export const webOrigin =
  process.env.PRODUCT_WEB_ORIGIN ?? "http://localhost:3000";
export async function accountEvidence<T>(path: string): Promise<T | null> {
  const token = (await cookies()).get(sessionCookie)?.value;
  if (!token || !/^[a-f0-9]{64}$/.test(token)) return null;
  try {
    const r = await fetch(`${apiURL}/api/v1/${path}`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
      signal: AbortSignal.timeout(9000),
    });
    return r.ok ? ((await r.json()) as T) : null;
  } catch {
    return null;
  }
}
export async function session(): Promise<Session | null> {
  return accountEvidence<Session>("auth/session");
}
