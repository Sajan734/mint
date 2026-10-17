// Twin: seller/lib/viewer-slots.ts (keep identical)
// At most MAX live WebGL viewers on a page (Chrome keeps ~16 contexts, Safari fewer). Every SplatViewer takes a slot;
// the oldest holder is told to drop its viewer when a new one needs room.
const MAX = 2;
const holders: Array<{ id: string; evict: () => void }> = [];

export function acquireSlot(id: string, evict: () => void): () => void {
  releaseSlot(id);
  while (holders.length >= MAX) holders.shift()?.evict();
  holders.push({ id, evict });
  return () => releaseSlot(id);
}
export function releaseSlot(id: string): void {
  const i = holders.findIndex((h) => h.id === id);
  if (i >= 0) holders.splice(i, 1);
}
export const liveSlots = (): number => holders.length;
