// "Scan an item": start a new scan session and go to its page. The id is the scan id end to end
// (scans/{id}/video.mp4 -> splats/{id} -> listings/{id}).
export const dynamic = "force-dynamic";

export function GET(req: Request) {
  return Response.redirect(new URL(`/scan/${crypto.randomUUID()}`, req.url), 303);
}
