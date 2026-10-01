import { apiURL } from "../../../../lib/profiles";
export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const query = new URL(request.url).searchParams;
  if (!/^[a-f0-9]{64}$/.test(query.get("revision_sha256") ?? ""))
    return new Response("Revision digest required", { status: 400 });
  try {
    const upstream = await fetch(
      `${apiURL}/api/v1/profiles/${encodeURIComponent(id)}/raw?${query}`,
      { cache: "no-store", signal: AbortSignal.timeout(9000) },
    );
    const headers = new Headers();
    for (const name of [
      "content-type",
      "content-disposition",
      "content-length",
      "etag",
      "x-raw-sha256",
    ]) {
      const value = upstream.headers.get(name);
      if (value) headers.set(name, value);
    }
    headers.set("Cache-Control", "private, no-store");
    return new Response(upstream.body, { status: upstream.status, headers });
  } catch {
    return new Response("Raw artifact unavailable", { status: 503 });
  }
}
