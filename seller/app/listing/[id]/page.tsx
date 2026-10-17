import { notFound } from "next/navigation";
import ListingEditor from "@/components/ListingEditor";
import { isScanId } from "@/lib/scan";
import { getPublicJson, listingDocUrl } from "@/lib/supabase";
import type { ListingDoc } from "@/lib/types";

export const dynamic = "force-dynamic";

/**
 * The listing editor. The server reads the pipeline's document (live); the client prefers this device's copy, and in
 * demo mode replays the recorded result instead.
 */
export default async function EditorPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!isScanId(id)) notFound();
  const doc = await getPublicJson<ListingDoc>(listingDocUrl(id));
  return <ListingEditor id={id} doc={doc} />;
}
