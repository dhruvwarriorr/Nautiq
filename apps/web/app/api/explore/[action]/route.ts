import { apiURL } from "../../../../lib/profiles";
import { boundedTripBody } from "../../../../lib/trip-proxy";
export const dynamic = "force-dynamic";
const actions: Record<string, { path: string; method: string }> = {
  conditions: { path: "conditions/point", method: "GET" },
  map: { path: "map/overview", method: "GET" },
  research: { path: "research", method: "POST" },
  query: { path: "query", method: "POST" },
};
async function proxy(
  request: Request,
  { params }: { params: Promise<{ action: string }> },
) {
  const action = (await params).action;
  const item = actions[action];
  const q = new URL(request.url).searchParams;
  if (action === "profile" && request.method === "GET") {
    const id = q.get("id");
    if (q.size !== 1 || !id || !/^[a-f0-9-]{36}$/.test(id))
      return Response.json({ code: "invalid_profile" }, { status: 400 });
    try {
      const views = [
        "",
        "/climatology",
        "/expected-state",
        "/uncertainty",
        "/anomaly",
      ];
      const names = [
        "profile",
        "climatology",
        "expected",
        "uncertainty",
        "anomaly",
      ];
      const settled = await Promise.allSettled(
        views.map(async (suffix) => {
          const response = await fetch(
            `${apiURL}/api/v1/profiles/${id}${suffix}`,
            {
              cache: "no-store",
              signal: AbortSignal.any([
                request.signal,
                AbortSignal.timeout(9000),
              ]),
            },
          );
          return response.ok ? response.json() : null;
        }),
      );
      return Response.json(
        Object.fromEntries(
          names.map((name, i) => [
            name,
            settled[i].status === "fulfilled" ? settled[i].value : null,
          ]),
        ),
        { headers: { "Cache-Control": "no-store" } },
      );
    } catch {
      return Response.json(
        { code: "profile_evidence_unavailable" },
        { status: 503 },
      );
    }
  }
  if (!item || item.method !== request.method)
    return Response.json({ code: "not_found" }, { status: 404 });
  let body: string | undefined;
  if (request.method === "POST") {
    if (request.headers.get("Content-Type") !== "application/json")
      return Response.json({ code: "json_required" }, { status: 415 });
    try {
      body = await boundedTripBody(request);
    } catch {
      return Response.json({ code: "body_budget" }, { status: 400 });
    }
  }
  try {
    const response = await fetch(
      `${apiURL}/api/v1/${item.path}${new URL(request.url).search}`,
      {
        method: request.method,
        headers: body ? { "Content-Type": "application/json" } : undefined,
        body,
        cache: "no-store",
        signal: AbortSignal.any([request.signal, AbortSignal.timeout(9000)]),
        redirect: "error",
      },
    );
    return new Response(response.body, {
      status: response.status,
      headers: {
        "Content-Type": "application/json",
        "Cache-Control": "no-store",
      },
    });
  } catch {
    return Response.json({ code: "evidence_unavailable" }, { status: 503 });
  }
}
export { proxy as GET, proxy as POST };
