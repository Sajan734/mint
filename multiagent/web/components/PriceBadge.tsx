import { priceBadge, type BadgeKind } from "@/lib/price-badge";
import { formatPrice } from "@/lib/format";

const STYLE: Record<BadgeKind, string> = {
  great: "bg-mint-wash text-mint-ink border-transparent",
  fair: "bg-surface text-ink border-mint-ink",
  high: "bg-amber/25 text-ink border-transparent",
  overpriced: "bg-coral/20 text-ink border-transparent",
  unknown: "bg-surface-2 text-ink-2 border-dashed border-slate",
};
// Never colour-only: each state has its own glyph.
const ICON: Record<BadgeKind, string> = {
  great: "M12 5v14m0 0-5-5m5 5 5-5",
  fair: "m5 12 5 5 9-10",
  high: "M12 19V5m0 0-5 5m5-5 5 5",
  overpriced: "M12 19V7m0 0-5 5m5-5 5 5M6 3h12",
  unknown: "M6 12h12",
};

export default function PriceBadge({
  price,
  reference,
  size = "sm",
}: {
  price: number;
  reference: number | null;
  size?: "sm" | "lg";
}) {
  const b = priceBadge(price, reference);
  const pct =
    b.pctVsFair === null || b.pctVsFair === 0
      ? null
      : b.pctVsFair < 0
        ? `${-b.pctVsFair}% below fair value`
        : `${b.pctVsFair}% above fair value`;
  return (
    <span className="inline-flex flex-col items-start gap-1">
      <span
        data-kind={b.kind}
        title={
          reference !== null
            ? `Compared with ${formatPrice(reference)} typical resale in this condition.`
            : undefined
        }
        className={`inline-flex h-6 items-center gap-1 rounded-sm border px-2 text-xs font-semibold ${STYLE[b.kind]}`}
      >
        <svg aria-hidden viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <path d={ICON[b.kind]} />
        </svg>
        {b.label}
      </span>
      {size === "lg" && reference !== null && (
        <span className="text-sm text-ink-2">
          Mint fair value {formatPrice(reference)}
          {pct ? ` · ${pct}` : ""}
        </span>
      )}
    </span>
  );
}
