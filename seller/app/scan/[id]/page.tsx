import { notFound } from "next/navigation";
import QRCode from "qrcode";
import ScanSession from "@/components/ScanSession";
import { isScanId, scanDeepLink } from "@/lib/scan";

export default async function ScanPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!isScanId(id)) notFound();
  const deepLink = scanDeepLink(id);
  const qrSvg = await QRCode.toString(deepLink, { type: "svg", margin: 1, errorCorrectionLevel: "M" });

  return (
    <div className="flex flex-col gap-8">
      <header className="flex max-w-2xl flex-col gap-2">
        <h1 className="text-[length:var(--t-2xl)] font-bold">Scan your item</h1>
        <p className="text-ink-2">
          Put the item on a sheet of paper. Scan the code with your iPhone, then turn the paper slowly while the app
          records. This page updates by itself.
        </p>
      </header>
      <ScanSession scanId={id} qrSvg={qrSvg} deepLink={deepLink} />
    </div>
  );
}
