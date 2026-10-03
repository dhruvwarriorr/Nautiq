import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { apiURL } from "../../../../lib/profiles";
import { sessionCookie, webOrigin } from "../../../../lib/product-server";
import { boundedTripBody } from "../../../../lib/trip-proxy";
export const dynamic = "force-dynamic";
const uuid = "[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}";
const allowed = new RegExp(
  `^(auth/(register|login|session|logout)|account|saved-trips(?:/${uuid})?|alerts(?:/${uuid}/acknowledge)?|(?:routes|watchlists|alert-rules)(?:/${uuid})?|(?:reports|exports)(?:/${uuid}(?:/(cancel|download-grants|download))?)?)$`,
);
async function proxy(
  request: Request,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const path = (await params).path.join("/");
  if (!allowed.test(path))
    return NextResponse.json({ code: "not_found" }, { status: 404 });
  const mutation = request.method !== "GET";
  if (mutation && request.headers.get("origin") !== webOrigin)
    return NextResponse.json({ code: "origin_required" }, { status: 403 });
  const cookieStore = await cookies();
  const token = cookieStore.get(sessionCookie)?.value;
  const headers: Record<string, string> = {};
  if (token && /^[a-f0-9]{64}$/.test(token))
    headers.Authorization = `Bearer ${token}`;
  for (const name of [
    "Content-Type",
    "X-CSRF-Token",
    "X-Account-Scope",
    "Idempotency-Key",
    "If-Match",
  ]) {
    const value = request.headers.get(name);
    if (value) headers[name] = value;
  }
  if (mutation) headers.Origin = webOrigin;
  let body: string | undefined;
  try {
    if (request.body) body = await boundedTripBody(request);
  } catch {
    return NextResponse.json(
      { code: "body_budget_or_encoding" },
      { status: 400 },
    );
  }
  try {
    const response = await fetch(
      `${apiURL}/api/v1/${path}${new URL(request.url).search}`,
      {
        method: request.method,
        headers,
        body,
        cache: "no-store",
        signal: AbortSignal.any([request.signal, AbortSignal.timeout(9000)]),
        redirect: "error",
      },
    );
    if (path === "auth/login" || path === "auth/register") {
      const data = await response.json();
      if (!response.ok)
        return NextResponse.json(data, {
          status: response.status,
          headers: { "Cache-Control": "no-store" },
        });
      if (
        !/^[a-f0-9]{64}$/.test(data.session_token) ||
        !/^[a-f0-9]{64}$/.test(data.csrf_token)
      )
        throw Error("auth_contract");
      cookieStore.set(sessionCookie, data.session_token, {
        httpOnly: true,
        sameSite: "lax",
        secure: webOrigin.startsWith("https:"),
        path: "/",
        maxAge: 86400,
      });
      return NextResponse.json(
        {
          signed_in: true,
          csrf_token: data.csrf_token,
          expires_at: data.expires_at,
        },
        { headers: { "Cache-Control": "no-store" } },
      );
    }
    if (
      response.status === 401 ||
      (response.ok &&
        (path === "auth/logout" ||
          (request.method === "DELETE" && path === "account")))
    )
      cookieStore.delete(sessionCookie);
    if (response.ok && request.method === "PATCH" && path === "account") {
      const data = await response.json();
      if (data.sign_in_again) cookieStore.delete(sessionCookie);
      return NextResponse.json(data, {
        headers: { "Cache-Control": "no-store" },
      });
    }
    const returned = new Headers({
      "Cache-Control": "private, no-store",
      "X-Content-Type-Options": "nosniff",
      "Referrer-Policy": "no-referrer",
    });
    for (const name of [
      "Content-Type",
      "Content-Disposition",
      "X-Artifact-SHA256",
      "Content-Security-Policy",
      "ETag",
    ]) {
      const value = response.headers.get(name);
      if (value) returned.set(name, value);
    }
    return new Response(response.body, {
      status: response.status,
      headers: returned,
    });
  } catch {
    return NextResponse.json(
      { code: "account_service_unavailable" },
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
  }
}
export {
  proxy as GET,
  proxy as POST,
  proxy as PUT,
  proxy as PATCH,
  proxy as DELETE,
};
