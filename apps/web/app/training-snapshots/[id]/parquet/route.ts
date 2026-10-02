import { apiURL } from "../../../../lib/profiles";
export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  if (new URL(request.url).searchParams.size)
    return new Response("Unexpected query parameters", { status: 400 });
  try {
    const upstream = await fetch(
      `${apiURL}/api/v1/training-snapshots/${encodeURIComponent(id)}/parquet`,
      { cache: "no-store", signal: AbortSignal.timeout(9000) },
    );
    const headers = new Headers();
    for (const name of [
      "content-type",
      "content-disposition",
      "content-length",
      "x-parquet-sha256",
    ]) {
      const v = upstream.headers.get(name);
      if (v) headers.set(name, v);
    }
    headers.set("Cache-Control", "private, no-store");
    return new Response(upstream.body, { status: upstream.status, headers });
  } catch {
    return new Response("Snapshot download unavailable", { status: 503 });
  }
}
