const api = process.env.API_INTERNAL_URL ?? "http://localhost:8080";
export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  if (!/^[a-f0-9-]{36}$/.test(id))
    return Response.json({ code: "evidence_not_found" }, { status: 404 });
  const auth = request.headers.get("authorization") ?? "";
  if (!/^Bearer [a-f0-9]{64}$/.test(auth))
    return Response.json({ code: "evidence_not_found" }, { status: 404 });
  try {
    const result = await fetch(`${api}/api/v1/trips/${id}/replay`, {
      method: "POST",
      headers: { Authorization: auth },
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
    return Response.json({ code: "trip_replay_unavailable" }, { status: 503 });
  }
}
