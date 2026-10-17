export const PX_PER_FRAME = 12;
export const FRICTION = 0.92;
export const STOP_VELOCITY = 0.002;

export const wrapIndex = (i: number, n: number): number => ((i % n) + n) % n;

/** One inertia step; returns 0 once slow enough to stop. */
export const decay = (v: number): number =>
  Math.abs(v * FRICTION) < STOP_VELOCITY ? 0 : v * FRICTION;

/** Frame indices ordered nearest-first (alternating forward/back) from `from`. */
export function loadOrder(from: number, n: number): number[] {
  const out = [wrapIndex(from, n)];
  for (let d = 1; out.length < n; d++) {
    const f = wrapIndex(from + d, n);
    const b = wrapIndex(from - d, n);
    out.push(f);
    if (b !== f && out.length < n) out.push(b);
  }
  return out;
}
