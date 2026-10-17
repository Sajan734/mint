// "Scan": a new comparison id for this listing, then its check page. The id goes to the phone in the QR
// (mint://verify?id=<cid>&listing=<id>) and names the result (assets/comparisons/<cid>.json).
// Relative Location: the browser resolves it against the public origin (the zones proxy), never this server's port.
export async function GET(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const mock = new URL(req.url).searchParams.get("mock");
  const query = mock === null ? "" : `?mock=${encodeURIComponent(mock)}`;
  return new Response(null, {
    status: 303,
    headers: { Location: `/listing/${encodeURIComponent(id)}/check/${crypto.randomUUID()}${query}` },
  });
}
