import { boundedTripBody } from "../../../lib/trip-proxy";
const api = process.env.API_INTERNAL_URL ?? "http://localhost:8080";
export async function POST(request: Request) {
  if (request.headers.get("content-type") !== "application/json")
    return Response.json({ code: "json_required" }, { status: 415 });
  let body: string;
  try {
    body = await boundedTripBody(request);
  } catch {
    return Response.json(
      { code: "invalid_or_oversized_body" },
      { status: 413 },
    );
  }

  try {
    const result = await fetch(`${api}/api/v1/trips`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
      cache: "no-store",
      signal: AbortSignal.timeout(10000),
    });
    return new Response(await result.text(), {
      status: result.status,
      headers: {
        "Content-Type": "application/json",
        "Cache-Control": "no-store",
      },
    });
  } catch {
    return Response.json({ code: "trip_api_unavailable" }, { status: 503 });
  }
}
