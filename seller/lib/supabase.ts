// Public Supabase access for the seller site: public objects in the `assets` bucket (no key), plus live progress
// events over Realtime when the public anon key is set. The service-role key never comes near a web app.
const DEFAULT_URL = "https://jpanyhsifoxxiizkgjno.supabase.co"; // public project URL, not a secret

export const SUPABASE_URL = (process.env.NEXT_PUBLIC_SUPABASE_URL || DEFAULT_URL).replace(/\/$/, "");
export const ANON_KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "";

export const publicUrl = (path: string) => `${SUPABASE_URL}/storage/v1/object/public/assets/${path}`;
/** Written by the splat job when the 3D scan is done (gsplat/mintsplat/publish.py). */
export const splatManifestUrl = (scanId: string) => publicUrl(`splats/${scanId}.json`);
/** Written by the listing step: listed, rejected or failed (gsplat/mintsplat/market.py). */
export const listingDocUrl = (scanId: string) => publicUrl(`listings/${scanId}.json`);

/** A public JSON object, never from a cache; null until it exists (or when the network fails). */
export async function getPublicJson<T>(url: string): Promise<T | null> {
  try {
    const res = await fetch(`${url}?t=${Date.now()}`, { cache: "no-store" });
    return res.ok ? ((await res.json()) as T) : null;
  } catch {
    return null;
  }
}
