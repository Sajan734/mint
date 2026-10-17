// Supabase Edge Function: hands the Mint scanner one-time signed upload URLs for a scan, so the
// phone uploads straight into Storage without holding any key.
//
// Deploy with JWT verification OFF (the app sends no key):
//   supabase functions deploy scan-upload --no-verify-jwt --project-ref <ref>
// or paste this file into Dashboard → Edge Functions → new function "scan-upload" and untick
// "Enforce JWT verification".
//
// POST { "scan_id": "<uuid>", "files": ["video.mp4", "poses.jsonl", "capture.json", "thumb.jpg"] }
//  →   { "uploads": [{ "file": "video.mp4", "path": "scans/<uuid>/video.mp4", "signed_url": "https://…" }, …] }
// The app then PUTs each file to its signed_url.
import { createClient } from "npm:@supabase/supabase-js@2.45.4";

const BUCKET = "scans";
const ALLOWED = new Set(["video.mp4", "poses.jsonl", "capture.json", "thumb.jpg"]);
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

Deno.serve(async (req) => {
  if (req.method !== "POST") return json({ error: "POST only" }, 405);
  let body: { scan_id?: string; files?: string[] };
  try {
    body = await req.json();
  } catch {
    return json({ error: "bad JSON" }, 400);
  }
  const { scan_id, files } = body;
  if (!scan_id || !UUID.test(scan_id) || !Array.isArray(files) || files.length === 0 || !files.every((f) => ALLOWED.has(f))) {
    return json({ error: "expected { scan_id: uuid, files: [video.mp4 | poses.jsonl | capture.json | thumb.jpg] }" }, 400);
  }

  // SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are provided to every Edge Function by Supabase.
  const supabase = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);
  const uploads = [];
  for (const file of files) {
    const key = `${scan_id}/${file}`;
    const { data, error } = await supabase.storage.from(BUCKET).createSignedUploadUrl(key, { upsert: true });
    if (error) return json({ error: error.message }, 500);
    uploads.push({ file, path: `${BUCKET}/${key}`, signed_url: data.signedUrl });
  }
  return json({ uploads });
});

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}
