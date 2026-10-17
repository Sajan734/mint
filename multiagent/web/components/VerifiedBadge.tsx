export default function VerifiedBadge({ usableViews }: { usableViews: number }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-mint-wash px-3 py-1 text-sm font-semibold text-mint-ink">
      <svg aria-hidden viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2.5">
        <circle cx="12" cy="12" r="9" />
        <path d="m8 12 3 3 5-6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      Verified by Mint scan · {usableViews} {usableViews === 1 ? "view" : "views"}
    </span>
  );
}
