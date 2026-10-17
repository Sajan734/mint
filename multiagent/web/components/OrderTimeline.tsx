import { timelineFor } from "@/lib/orders";
import type { FulfilmentMethod, OrderStatus } from "@/lib/types";

const STATE_TEXT = { done: "done", current: "current step", upcoming: "upcoming" } as const;

export default function OrderTimeline({ method, status }: { method: FulfilmentMethod; status: OrderStatus }) {
  const steps = timelineFor(method, status);
  return (
    <ol aria-label="Order progress" className="m-0 list-none p-0">
      {steps.map((s, i) => (
        <li key={s.status} aria-current={s.state === "current" ? "step" : undefined} className="relative flex gap-4 pb-6 last:pb-0">
          {i < steps.length - 1 && (
            <span aria-hidden className={`absolute left-[13px] top-7 h-[calc(100%-1.75rem)] w-0.5 ${s.state === "done" ? "bg-mint-ink" : "bg-line"}`} />
          )}
          <span
            aria-hidden
            className={`relative grid size-7 shrink-0 place-items-center rounded-full border-2 ${
              s.state === "done"
                ? "border-mint-ink bg-mint-ink text-bg"
                : s.state === "current"
                  ? "border-ink bg-surface"
                  : "border-line bg-surface"
            }`}
          >
            {s.state === "done" && (
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round"><path d="m5 12 5 5 9-10" /></svg>
            )}
            {s.state === "current" && <span className="size-2.5 rounded-full bg-ink" />}
          </span>
          <span className={`pt-0.5 ${s.state === "upcoming" ? "text-ink-2" : "font-semibold"}`}>
            {s.label}
            <span className="sr-only"> ({STATE_TEXT[s.state]})</span>
          </span>
        </li>
      ))}
    </ol>
  );
}
