import type { Grade } from "@/lib/types";
import { conditionLabel } from "@/lib/format";

const DOTS: Record<Grade, number> = { like_new: 4, light_wear: 3, moderate_wear: 2, heavy_wear: 1 };

export default function ConditionPill({ grade, sellerChecking = false }: { grade: Grade; sellerChecking?: boolean }) {
  return (
    <span className="inline-flex flex-wrap gap-2">
      <span className="inline-flex items-center gap-2 whitespace-nowrap rounded-sm bg-surface-2 px-2 py-0.5 text-sm text-ink">
        <span aria-hidden className="flex gap-0.5">
          {[0, 1, 2, 3].map((i) => (
            <span key={i} className={`size-1.5 rounded-full ${i < DOTS[grade] ? "bg-ink" : "bg-line"}`} />
          ))}
        </span>
        {conditionLabel(grade)}
      </span>
      {sellerChecking && (
        <span className="inline-flex items-center rounded-sm border border-dashed border-line-strong px-2 py-0.5 text-sm text-ink-2">
          Seller checking
        </span>
      )}
    </span>
  );
}
