import {apiURL} from "../../../../lib/profiles";
export const dynamic = "force-dynamic";
async function proxy(request: Request, context: {params: Promise<{action: string}>}) {
  const {action} = await context.params;
  if ((request.method === "GET" && action !== "sample") || (request.method === "POST" && !["route", "polygon"].includes(action))) return new Response(null, {status: 404});
  const url = new URL(request.url);
  if (url.search.length > 4096) return new Response(null, {status: 400});
  let body: string | undefined;
  if (request.method === "POST") {
    if (request.headers.get("Content-Type") !== "application/json") return new Response(null, {status: 415});
    if (Number(request.headers.get("Content-Length")) > 32768) return new Response(null, {status: 413});
    const reader = request.body?.getReader();
    if (!reader) return new Response(null, {status: 400});
    const chunks: Uint8Array[] = []; let bytes = 0;
    while (true) {const next = await reader.read(); if (next.done) break; bytes += next.value.length; if (bytes > 32768) {await reader.cancel(); return new Response(null, {status: 413});} chunks.push(next.value);}
    const data = new Uint8Array(bytes); let offset = 0; for (const chunk of chunks) {data.set(chunk, offset); offset += chunk.length;} body = new TextDecoder().decode(data);
  }
  try {
    const response = await fetch(`${apiURL}/api/v1/fields/${action}${url.search}`, {method: request.method, headers: {"Content-Type": "application/json"}, body, cache: "no-store", signal: AbortSignal.timeout(8000)});
    return new Response(await response.text(), {status: response.status, headers: {"Content-Type": response.headers.get("Content-Type") ?? "application/problem+json", "Cache-Control": "no-store"}});
  } catch {return Response.json({status: 503, code: "field_service_unavailable"}, {status: 503});}
}
export const GET = proxy;
export const POST = proxy;
