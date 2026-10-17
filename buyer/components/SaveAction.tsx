"use client";
import { useStore } from "@/lib/store";

/** Wide labelled save toggle for the listing action area. */
export default function SaveAction({ itemId, title }: { itemId: string; title: string }) {
  const { isSaved, toggleSaved } = useStore();
  const on = isSaved(itemId);
  return (
    <button
      type="button"
      aria-pressed={on}
      aria-label={on ? "Saved" : `Save ${title}`}
      onClick={() => toggleSaved(itemId)}
      className="inline-flex min-h-11 flex-1 items-center justify-center gap-2 rounded-full font-semibold transition-colors hover:bg-surface-2 active:scale-[0.97]"
    >
      <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" fill={on ? "currentColor" : "none"} stroke="currentColor" strokeWidth="2" className={on ? "text-coral" : ""}>
        <path d="M12 21s-7-4.4-9.3-9A5.3 5.3 0 0 1 12 6.6 5.3 5.3 0 0 1 21.3 12C19 16.6 12 21 12 21z" />
      </svg>
      <span aria-hidden>{on ? "Saved" : "Save"}</span>
    </button>
  );
}
