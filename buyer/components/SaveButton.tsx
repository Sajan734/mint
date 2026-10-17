"use client";
import { useStore } from "@/lib/store";

export default function SaveButton({ itemId, title }: { itemId: string; title: string }) {
  const { isSaved, toggleSaved } = useStore();
  const on = isSaved(itemId);
  return (
    <button
      type="button"
      aria-pressed={on}
      aria-label={on ? "Saved" : `Save ${title}`}
      onClick={(e) => { e.preventDefault(); e.stopPropagation(); toggleSaved(itemId); }}
      style={{
        width: "var(--save-size, 2.5rem)", height: "var(--save-size, 2.5rem)",
        display: "inline-grid", placeItems: "center", cursor: "pointer", transition: "transform var(--dur-feedback) var(--ease), border-color var(--dur-feedback) var(--ease)",
        border: "1px solid var(--save-border, transparent)", borderRadius: "50%",
        background: "var(--save-bg, var(--raised))", color: on ? "var(--save-on, var(--coral))" : "var(--ink)",
      }}
    >
      <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" fill={on ? "currentColor" : "none"} stroke="currentColor" strokeWidth="2">
        <path d="M12 21s-7-4.4-9.3-9A5.3 5.3 0 0 1 12 6.6 5.3 5.3 0 0 1 21.3 12C19 16.6 12 21 12 21z" />
      </svg>
    </button>
  );
}
