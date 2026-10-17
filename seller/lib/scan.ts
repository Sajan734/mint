// A scan session is a UUID made by this site. The QR code hands it to the iPhone app, which records and uploads
// to scans/{id}/video.mp4; the pipeline then publishes everything under the same id.
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

/** The app's deep link scheme (it registers mint://); override with NEXT_PUBLIC_MINT_SCAN_LINK. */
export const SCAN_LINK = process.env.NEXT_PUBLIC_MINT_SCAN_LINK || "mint://scan";

export const isScanId = (s: string) => UUID.test(s);

/** What the QR code encodes: opens the Mint app straight into a capture for this session. */
export const scanDeepLink = (scanId: string) => `${SCAN_LINK}?id=${scanId}`;
