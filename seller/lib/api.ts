// The website's one write path to the backend (gsplat/app.py `api` on Modal; it holds the Supabase key, the browser
// holds none). Publish puts a live scan's listing on Mint for every buyer; Save draft takes it off again.
import type { Fields } from "@/components/ListingEditor";

const DEFAULT_API_URL = "https://doalnikhil--mint-gsplat-api.us-east.modal.run";
export const API_URL = (process.env.NEXT_PUBLIC_MINT_API_URL || DEFAULT_API_URL).replace(/\/$/, "");
const TIMEOUT_MS = 20_000; // the endpoint may cold-start

export type PublishResult = { ok: true } | { ok: false; error: string };

/** Never throws. `fields` are already validated (validateFields); price is whole dollars. */
export async function publishRemote(scanId: string, fields: Fields, state: "published" | "draft"): Promise<PublishResult> {
  try {
    const res = await fetch(`${API_URL}/listings/${scanId}/publish`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        state,
        title: fields.title.trim(),
        description: fields.description.trim(),
        price_cad: Number(fields.price),
      }),
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    if (res.ok) return { ok: true };
    const body = (await res.json().catch(() => null)) as { detail?: unknown } | null;
    return { ok: false, error: typeof body?.detail === "string" ? body.detail : `HTTP ${res.status}` };
  } catch {
    return { ok: false, error: "Mint could not be reached" };
  }
}
