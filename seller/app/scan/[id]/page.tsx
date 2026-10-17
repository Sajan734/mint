import { notFound } from "next/navigation";
import QRCode from "qrcode";
import ScanFlow from "@/components/ScanFlow";
import scanResult from "@/mock/scan-result.json";
import { isScanId, scanDeepLink } from "@/lib/scan";
import type { MarketListing } from "@/lib/types";

export default async function ScanPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!isScanId(id)) notFound();
  const deepLink = scanDeepLink(id);
  const qrSvg = await QRCode.toString(deepLink, { type: "svg", margin: 1, errorCorrectionLevel: "M" });

  return (
    <div className="flex flex-col gap-6">
      <header className="flex max-w-2xl flex-col gap-2">
        <h1 className="text-[length:var(--t-2xl)] font-bold">New listing</h1>
        <p className="text-ink-2">
          Scan this code with your iPhone. The Mint app records the item and sends it here. This page updates by itself.
        </p>
      </header>
      {/* Demo mode replays the recorded pots listing (real listing-agent output); live mode never reads it. */}
      <ScanFlow kind="listing" scanId={id} deepLink={deepLink} qrSvg={qrSvg} mockResult={scanResult as MarketListing} />
    </div>
  );
}
