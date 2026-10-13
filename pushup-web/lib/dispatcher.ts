import "server-only";
import type { FetchLike } from "./supabase-server";

/** Error from the EC2 dispatcher (CONTRACTS §C4). `status` is the HTTP status (504 = unreachable/timeout). */
export class DispatcherError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "DispatcherError";
  }
}

/** DISPATCHER_URL is server-only config (never NEXT_PUBLIC): the browser talks to this site, never the dispatcher. */
function dispatcherUrl(): string {
  const url = process.env.DISPATCHER_URL;
  if (!url) throw new DispatcherError("DISPATCHER_URL / DISPATCHER_TOKEN not set", 500);
  return url.replace(/\/+$/, "");
}

/** JSON request to the dispatcher; non-2xx throws DispatcherError carrying FastAPI's `detail` when present. */
export async function dispatcherFetch<T = unknown>(
  method: "GET" | "POST",
  path: string,
  opts: { headers?: Record<string, string>; body?: unknown; timeoutMs?: number } = {},
  fetchImpl: FetchLike = fetch,
): Promise<T> {
  const url = dispatcherUrl();
  const headers: Record<string, string> = { Accept: "application/json", ...opts.headers };
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  let res: Response;
  try {
    res = await fetchImpl(`${url}${path}`, {
      method,
      headers,
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
      cache: "no-store",
      signal: AbortSignal.timeout(opts.timeoutMs ?? 30_000),
    });
  } catch (e) {
    throw new DispatcherError(e instanceof Error ? e.message : "request failed", 504);
  }
  const text = await res.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text) as unknown;
    } catch {
      body = text;
    }
  }
  if (!res.ok) {
    const detail =
      body && typeof body === "object" && "detail" in body ? JSON.stringify((body as { detail: unknown }).detail) : "";
    throw new DispatcherError(detail || (typeof body === "string" && body ? body.slice(0, 300) : `HTTP ${res.status}`), res.status);
  }
  return body as T;
}
