import { timelineFor } from "@/lib/orders";
import type { FulfilmentMethod, OrderStatus } from "@/lib/types";

export default function OrderTimeline({ method, status }: { method: FulfilmentMethod; status: OrderStatus }) {
  return (
    <ol aria-label="Order progress" className="grid gap-2">
      {timelineFor(method, status).map((s) => (
        <li key={s.status} aria-current={s.state === "current" ? "step" : undefined} className="flex items-center gap-3">
          <span
            aria-hidden
            className={`size-3 rounded-full ${s.state === "done" ? "bg-mint" : s.state === "current" ? "bg-ink" : "border border-line"}`}
          />
          <span className={s.state === "upcoming" ? "text-ink-2" : "font-semibold"}>
            {s.label}
            <span className="sr-only"> ({s.state === "done" ? "done" : s.state === "current" ? "current step" : "upcoming"})</span>
          </span>
        </li>
      ))}
    </ol>
  );
}
