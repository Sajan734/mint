// Supabase Edge Function: the hand-off between the seller's dashboard (website) and the Mint scanner
// app on the phone. The dashboard asks for a scan, the phone (waiting on its home screen) picks it
// up, scans, uploads, and reports progress; the dashboard shows it live. Optional: the website can
// also just show a QR code of the same scan as a mint:// link (scanner/DASHBOARD.md). No keys on either side:
// this function holds the service role and keeps each session as a small JSON file in Storage.
//
// Deploy with JWT verification OFF (the phone and the browser send no key):
//   supabase functions deploy scan-session --no-verify-jwt --project-ref <ref>
// or paste this file into Dashboard → Edge Functions → new function "scan-session" and untick
// "Enforce JWT verification".
//
// POST JSON, one of:
//   { "action": "request", "title"?: str, "seller"?: str }   dashboard: "New product"  → session (status "waiting")
//   { "action": "request", "kind": "verify", "listing_scan_id": uuid, "title"?: str }   listing page: a buyer's "Scan"
//   { "action": "status", "scan_id": uuid }                  dashboard: poll           → session
//   { "action": "next" }                                     phone: poll               → { "request": session | null }
//   { "action": "update", "scan_id": uuid, "status": s, "passes"?: n, "progress"?: 0…1 }   phone → session
// status: waiting → scanning → uploading → uploaded (or cancelled). After "uploaded" the splat pipeline
// takes over; its result appears in assets/listings/index.json under the same scan_id.
// Storage (bucket "scans", private): {scan_id}/session.json, and _requests/current.json → the latest request.

export const STATUSES = ["waiting", "scanning", "uploading", "uploaded", "cancelled"] as const;
export type Status = (typeof STATUSES)[number];

export interface Session {
  v: 1;
  scan_id: string;
  kind: "listing" | "verify";
  listing_scan_id: string | null;   // verify: the listing this rescan is checked against
  status: Status;
  source: "dashboard" | "phone";
  title: string | null;
  seller: string | null;
  passes: number;
  progress: number;
  created_at: string;
  updated_at: string;
}

/** Where sessions live: JSON documents by key (Storage in production, a Map in tests). */
export interface Store {
  read(key: string): Promise<unknown | null>;
  write(key: string, value: unknown): Promise<void>;
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const CURRENT = "_requests/current.json";
/** A request the phone hasn't picked up within this long is stale (the seller walked away). */
export const REQUEST_TTL_MS = 10 * 60 * 1000;

const sessionKey = (id: string) => `${id}/session.json`;
const text = (v: unknown) => (typeof v === "string" && v.trim() ? v.trim().slice(0, 120) : null);

export async function handle(body: Record<string, unknown>, store: Store, now = new Date(),
                             newId = () => crypto.randomUUID()): Promise<[number, unknown]> {
  const at = now.toISOString();
  switch (body.action) {
    case "request": {
      const verify = body.kind === "verify";
      if (verify && (typeof body.listing_scan_id !== "string" || !UUID.test(body.listing_scan_id))) {
        return [400, { error: "verify needs listing_scan_id: uuid" }];
      }
      const s: Session = {
        v: 1, scan_id: newId(), kind: verify ? "verify" : "listing", listing_scan_id: verify ? body.listing_scan_id as string : null,
        status: "waiting", source: "dashboard", title: text(body.title), seller: text(body.seller),
        passes: 0, progress: 0, created_at: at, updated_at: at,
      };
      await store.write(sessionKey(s.scan_id), s);
      await store.write(CURRENT, { scan_id: s.scan_id, created_at: at });
      return [200, s];
    }
    case "status": {
      if (typeof body.scan_id !== "string" || !UUID.test(body.scan_id)) return [400, { error: "scan_id: uuid" }];
      const s = await store.read(sessionKey(body.scan_id));
      return s ? [200, s] : [404, { error: "no such scan" }];
    }
    case "next": {
      const cur = (await store.read(CURRENT)) as { scan_id?: string } | null;
      if (!cur?.scan_id) return [200, { request: null }];
      const s = (await store.read(sessionKey(cur.scan_id))) as Session | null;
      const fresh = s && s.status === "waiting" && now.getTime() - Date.parse(s.created_at) < REQUEST_TTL_MS;
      return [200, { request: fresh ? s : null }];
    }
    case "update": {
      const { scan_id, status } = body;
      if (typeof scan_id !== "string" || !UUID.test(scan_id)) return [400, { error: "scan_id: uuid" }];
      if (typeof status !== "string" || !STATUSES.includes(status as Status)) {
        return [400, { error: `status: one of ${STATUSES.join(", ")}` }];
      }
      // A scan started on the phone without the dashboard has no session yet: create it.
      const old = (await store.read(sessionKey(scan_id))) as Session | null;
      const s: Session = old ?? {
        v: 1, scan_id, kind: "listing", listing_scan_id: null, status: "waiting", source: "phone", title: null, seller: null,
        passes: 0, progress: 0, created_at: at, updated_at: at,
      };
      s.status = status as Status;
      if (typeof body.passes === "number" && Number.isInteger(body.passes) && body.passes >= 0 && body.passes < 100) s.passes = body.passes;
      if (typeof body.progress === "number" && body.progress >= 0 && body.progress <= 1) s.progress = body.progress;
      if (s.status === "uploaded") s.progress = 1;
      s.updated_at = at;
      await store.write(sessionKey(scan_id), s);
      return [200, s];
    }
    default:
      return [400, { error: "action: request | status | next | update" }];
  }
}

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "content-type, authorization, apikey, x-client-info",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { ...CORS, "Content-Type": "application/json", "Cache-Control": "no-store" } });
}

// Only on Supabase (Deno); tests import `handle` with an in-memory store.
// deno-lint-ignore no-explicit-any
const deno = (globalThis as any).Deno;
if (deno?.serve) {
  const { createClient } = await import("npm:@supabase/supabase-js@2.45.4");
  // SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are provided to every Edge Function by Supabase.
  const bucket = createClient(deno.env.get("SUPABASE_URL"), deno.env.get("SUPABASE_SERVICE_ROLE_KEY")).storage.from("scans");
  const store: Store = {
    async read(key) {
      const { data, error } = await bucket.download(key);
      if (error || !data) return null;
      try { return JSON.parse(await data.text()); } catch { return null; }
    },
    async write(key, value) {
      const { error } = await bucket.upload(key, new Blob([JSON.stringify(value)], { type: "application/json" }),
                                            { upsert: true, contentType: "application/json", cacheControl: "0" });
      if (error) throw new Error(error.message);
    },
  };
  deno.serve(async (req: Request) => {
    if (req.method === "OPTIONS") return new Response(null, { headers: CORS });
    if (req.method !== "POST") return json({ error: "POST only" }, 405);
    let body: Record<string, unknown>;
    try { body = await req.json(); } catch { return json({ error: "bad JSON" }, 400); }
    try {
      const [status, out] = await handle(body ?? {}, store);
      return json(out, status);
    } catch (e) {
      return json({ error: String((e as Error)?.message ?? e) }, 500);
    }
  });
}
