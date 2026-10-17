// "New listing": start a new scan session and go to its page. The id is the scan id end to end
// (scans/{id}/video.mp4 -> splats/{id} -> listings/{id}).
export const dynamic = "force-dynamic";

// Seller runs under basePath "/sell" behind the buyer's rewrite. A route handler does not add the basePath to a
// redirect, and an absolute URL built from req.url would point at this app's own port. So send a RELATIVE Location
// that already includes /sell: the browser resolves it against the public origin.
const BASE_PATH = "/sell";

export function GET() {
  return new Response(null, { status: 303, headers: { Location: `${BASE_PATH}/scan/${crypto.randomUUID()}` } });
}
