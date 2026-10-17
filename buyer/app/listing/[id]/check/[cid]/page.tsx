import { notFound } from "next/navigation";
import QRCode from "qrcode";
import { getListing } from "@/lib/data";
import CheckFlow from "@/components/CheckFlow";

export const metadata = { title: "Check your item · Mint" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

// Buyer rescan, then "how it matches". A listing published on this device is not on the server: CheckFlow then
// reads it from the browser store, or says it was published on another device.
export default async function CheckPage({ params }: { params: Promise<{ id: string; cid: string }> }) {
  const { id, cid } = await params;
  if (!UUID.test(cid)) notFound();
  const item = await getListing(id);
  // The phone's verify link (scanner/DASHBOARD.md; iOS DashboardLink.swift).
  const deepLink = `mint://verify?id=${cid}&listing=${encodeURIComponent(id)}`;
  const qrSvg = await QRCode.toString(deepLink, { type: "svg", margin: 1, errorCorrectionLevel: "M" });
  return (
    <CheckFlow
      listingId={id}
      cid={cid}
      deepLink={deepLink}
      qrSvg={qrSvg}
      listing={item && { title: item.listing.title, frames: item.frames, splatUrl: item.splat_url }}
    />
  );
}
