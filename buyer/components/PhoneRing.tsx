// Twin: seller/components/PhoneRing.tsx (keep identical)
// The iOS app's sending ring (scanner/ios/Mint/Screens.swift SendingScreen): mint arc with round caps, a big
// rounded % number and a "SENDING" caps label. Drawn for a dark panel.
export const ROUNDED = 'ui-rounded, "SF Pro Rounded", system-ui, sans-serif';

const R = 86;
const C = 2 * Math.PI * R;

export default function PhoneRing({ pct, label = "SENDING" }: { pct: number; label?: string }) {
  const p = Math.min(100, Math.max(0, Math.round(pct)));
  return (
    <div
      role="progressbar"
      aria-label="Uploading your scan"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={p}
      className="relative grid size-52 place-items-center"
    >
      <svg viewBox="0 0 200 200" className="absolute inset-0 size-full -rotate-90" aria-hidden>
        <circle cx="100" cy="100" r={R} fill="none" stroke="rgb(255 255 255 / 0.12)" strokeWidth="14" />
        <circle
          cx="100"
          cy="100"
          r={R}
          fill="none"
          stroke="var(--mint)"
          strokeWidth="14"
          strokeLinecap="round"
          strokeDasharray={C}
          strokeDashoffset={C * (1 - Math.max(0.02, p / 100))}
          className="transition-[stroke-dashoffset] duration-300 ease-out motion-reduce:transition-none"
          style={{ filter: "drop-shadow(0 0 6px rgb(61 220 151 / 0.55))" }}
        />
      </svg>
      <div className="relative flex flex-col items-center" style={{ fontFamily: ROUNDED }}>
        <span className="text-5xl font-black tabular-nums leading-none">{p}%</span>
        <span className="mt-1.5 text-xs font-bold tracking-[0.2em] text-mint">{label}</span>
      </div>
    </div>
  );
}
