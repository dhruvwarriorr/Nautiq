import {apiURL} from "../../../../../../../../lib/profiles";
export const dynamic = "force-dynamic";
export async function GET(request: Request, {params}: {params: Promise<{id: string; variable: string; z: string; x: string; y: string}>}) {
  const p = await params;
  const time = new URL(request.url).searchParams.get("time") ?? "";
  if (!/^[a-f0-9-]{36}$/.test(p.id) || !/^[a-z][a-z0-9_]{0,63}$/.test(p.variable) || ![p.z, p.x, p.y].every(n => /^\d{1,4}$/.test(n)) || time.length > 40) return new Response(null, {status: 400});
  try {
    const response = await fetch(`${apiURL}/api/v1/fields/${p.id}/tiles/${p.variable}/${p.z}/${p.x}/${p.y}?${new URLSearchParams({time})}`, {cache: "no-store", signal: AbortSignal.timeout(8000)});
    const data = await response.arrayBuffer();
    const headers = new Headers({"Content-Type": response.headers.get("Content-Type") ?? "application/problem+json", "Cache-Control": "private, max-age=60"});
    for (const name of ["X-Field-Release-ID", "X-Field-Manifest-SHA256", "X-Field-Cycle", "X-Field-Valid-Time", "X-Field-Freshness"]) {const value = response.headers.get(name); if (value) headers.set(name, value);}
    return new Response(data, {status: response.status, headers});
  } catch {return new Response(null, {status: 503});}
}
