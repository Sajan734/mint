// Procedural turntable frames: tiny software 3D (rotate, tilt, cull, painter sort, flat shade) -> SVG string.
export const SHAPES = ["mug", "lamp", "vase", "headphones", "jacket", "helmet", "boardgame", "book"] as const;
export type Shape = (typeof SHAPES)[number];
export const PALETTES = {
  sage: { main: "#8FA68A", accent: "#F1E6CC" },
  clay: { main: "#C27B5A", accent: "#F3E3D0" },
  ink: { main: "#2F3438", accent: "#3DDC97" },
  sand: { main: "#D9C29C", accent: "#6B7F6A" },
  mint: { main: "#3DDC97", accent: "#FAF7F2" },
  coral: { main: "#FF6B5A", accent: "#2F3438" },
} as const;
export type PaletteName = keyof typeof PALETTES;
export const PALETTE_NAMES = Object.keys(PALETTES) as PaletteName[];
export const FRAME_COUNT = 24;

type V = [number, number, number];
type RGB = [number, number, number];
type Face = { p: V[]; n: V; c: RGB; two?: boolean };

const rgb = (h: string): RGB => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16)) as RGB;
const sub = (a: V, b: V): V => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const dot = (a: V, b: V) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a: V, b: V): V => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const norm = (a: V): V => {
  const l = Math.hypot(...a) || 1;
  return [a[0] / l, a[1] / l, a[2] / l];
};
const centroid = (p: V[]): V => [0, 1, 2].map((i) => p.reduce((s, q) => s + q[i], 0) / p.length) as V;

/** Build a face whose normal points away from `ref`. */
function face(p: V[], c: RGB, ref: V, two = false): Face {
  let cr = cross(sub(p[1], p[0]), sub(p[2], p[0]));
  if (Math.hypot(...cr) < 1e-9 && p.length > 3) cr = cross(sub(p[2], p[0]), sub(p[3], p[0]));
  let n = norm(cr);
  if (dot(n, sub(centroid(p), ref)) < 0) n = [-n[0], -n[1], -n[2]];
  return { p, n, c, two };
}

type XF = (v: V) => V;
const place = (fs: Face[], f: XF): Face[] => fs.map((x) => ({ ...x, p: x.p.map(f), n: norm(sub(f(x.n), f([0, 0, 0]))) }));
const rotZ = (a: number): XF => (v) => [v[0] * Math.cos(a) - v[1] * Math.sin(a), v[0] * Math.sin(a) + v[1] * Math.cos(a), v[2]];
const move = (x: number, y: number, z: number): XF => (v) => [v[0] + x, v[1] + y, v[2] + z];

function box(cx: number, cy: number, cz: number, w: number, h: number, d: number, c: RGB): Face[] {
  const [x0, x1, y0, y1, z0, z1] = [cx - w / 2, cx + w / 2, cy - h / 2, cy + h / 2, cz - d / 2, cz + d / 2];
  const q = (...a: V[]) => face(a, c, [cx, cy, cz]);
  return [
    q([x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]),
    q([x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0]),
    q([x0, y1, z0], [x1, y1, z0], [x1, y1, z1], [x0, y1, z1]),
    q([x0, y0, z0], [x1, y0, z0], [x1, y0, z1], [x0, y0, z1]),
    q([x0, y0, z0], [x0, y1, z0], [x0, y1, z1], [x0, y0, z1]),
    q([x1, y0, z0], [x1, y1, z0], [x1, y1, z1], [x1, y0, z1]),
  ];
}

/** Revolve [radius, y] profile around Y. color(segment, angleIndex) picks the colour. */
function lathe(prof: [number, number][], color: (s: number, a: number) => RGB, segs = 28, two = false): Face[] {
  const ys = prof.map((q) => q[1]);
  const yMid = (Math.min(...ys) + Math.max(...ys)) / 2;
  const out: Face[] = [];
  for (let s = 0; s < prof.length - 1; s++) {
    const [r0, y0] = prof[s];
    const [r1, y1] = prof[s + 1];
    for (let a = 0; a < segs; a++) {
      const t0 = (a / segs) * Math.PI * 2;
      const t1 = ((a + 1) / segs) * Math.PI * 2;
      const p: V[] = [
        [r0 * Math.cos(t0), y0, r0 * Math.sin(t0)],
        [r0 * Math.cos(t1), y0, r0 * Math.sin(t1)],
        [r1 * Math.cos(t1), y1, r1 * Math.sin(t1)],
        [r1 * Math.cos(t0), y1, r1 * Math.sin(t0)],
      ];
      const c = centroid(p);
      out.push(face(p, color(s, a), [0, y0 === y1 ? yMid : c[1], 0], two));
    }
  }
  return out;
}

/** Chain of small boxes along an arc in the XY plane (handles, headphone band). */
function arc(cx: number, cy: number, rx: number, ry: number, a0: number, a1: number, th: number, depth: number, c: RGB, n = 9): Face[] {
  const out: Face[] = [];
  for (let i = 0; i < n; i++) {
    const a = a0 + ((a1 - a0) * (i + 0.5)) / n;
    const len = (Math.abs(a1 - a0) / n) * Math.max(rx, ry) * 1.15;
    const tang = Math.atan2(ry * Math.cos(a), -rx * Math.sin(a));
    out.push(...place(box(0, 0, 0, len, th, depth, c), (v) => move(cx + rx * Math.cos(a), cy + ry * Math.sin(a), 0)(rotZ(tang)(v))));
  }
  return out;
}

type Model = (m: RGB, a: RGB) => { faces: Face[]; shadow: number };
const dark = (c: RGB, k: number): RGB => c.map((x) => x * k) as RGB;
const stripe = (i: number) => i % 14 < 3;

const MODELS: Record<Shape, Model> = {
  mug: (m, a) => ({
    shadow: 0.85,
    faces: [
      ...lathe([[0, 0], [0.5, 0], [0.5, 0.75], [0.43, 0.75], [0.43, 0.7], [0, 0.7]], (s, i) => (s === 4 ? [70, 44, 32] : s === 1 && stripe(i) ? a : m)),
      ...place(arc(0, 0, 0.3, 0.26, -Math.PI / 2, Math.PI / 2, 0.09, 0.09, m), move(0.62, 0.4, 0)),
    ],
  }),
  lamp: (m, a) => ({
    shadow: 0.9,
    faces: [
      ...lathe([[0, 0], [0.5, 0], [0.5, 0.08], [0.1, 0.12], [0.06, 1.15]], (s) => (s < 3 ? dark(m, 0.7) : a)),
      ...lathe([[0.2, 1.1], [0.62, 0.62]], (_s, i) => (stripe(i) ? a : m), 28, true),
    ],
  }),
  vase: (m, a) => ({
    shadow: 0.8,
    faces: lathe([[0, 0], [0.32, 0], [0.5, 0.35], [0.55, 0.65], [0.38, 1.0], [0.2, 1.2], [0.27, 1.4]], (s, i) => ((s === 2 || s === 3) && i % 14 < 4 ? a : m)),
  }),
  headphones: (m, a) => ({
    shadow: 0.95,
    faces: [
      ...arc(0, 0.55, 0.62, 0.78, 0, Math.PI, 0.1, 0.16, m, 14),
      ...[-1, 1].flatMap((s) =>
        place(lathe([[0, -0.08], [0.3, -0.08], [0.3, 0.08], [0, 0.08]], (k) => (k === 1 ? a : dark(m, 0.7)), 20), (v) => move(s * 0.62, 0.52, 0)([v[1], v[0], v[2]])),
      ),
    ],
  }),
  jacket: (m, a) => ({
    shadow: 0.9,
    faces: [
      ...box(0, 0.5, 0, 0.95, 1.05, 0.3, m),
      ...box(0, 0.5, 0.155, 0.08, 1.05, 0.02, a),
      ...[-1, 1].flatMap((s) => place(box(0, 0, 0, 0.3, 0.95, 0.26, dark(m, 0.85)), (v) => move(s * 0.7, 0.55, 0)(rotZ(s * 0.18)(v)))),
      ...box(0, 1.08, 0, 0.5, 0.1, 0.32, dark(m, 0.8)),
      ...box(0, 1.2, 0, 0.7, 0.04, 0.04, [90, 90, 90]),
      ...box(0, 1.35, 0, 0.03, 0.2, 0.03, [90, 90, 90]),
    ],
  }),
  helmet: (m, a) => ({
    shadow: 0.95,
    faces: [
      ...lathe(Array.from({ length: 9 }, (_, i): [number, number] => [0.62 * Math.cos((i / 8) * (Math.PI / 2)), 0.1 + 0.7 * Math.sin((i / 8) * (Math.PI / 2))]), (_s, i) => (stripe(i) ? a : m)),
      ...lathe([[0, 0.05], [0.64, 0.05], [0.64, 0.14], [0, 0.14]], () => dark(m, 0.6)),
      ...box(0, 0.38, 0.5, 0.7, 0.22, 0.2, [30, 34, 38]),
    ],
  }),
  boardgame: (m, a) => ({
    shadow: 1.1,
    faces: [...box(0, 0.14, 0, 1.4, 0.28, 1.0, m), ...box(0, 0.14, 0, 1.44, 0.07, 1.04, a), ...box(0, 0.16, 0.51, 0.8, 0.14, 0.02, a)],
  }),
  book: (m, a) => ({
    shadow: 0.9,
    faces: [
      ...box(0, 0.025, 0, 1.0, 0.05, 1.3, m),
      ...box(0, 0.35, 0, 1.0, 0.05, 1.3, m),
      ...box(0.02, 0.2, 0.01, 0.94, 0.26, 1.24, [244, 238, 222]),
      ...box(-0.5, 0.2, 0, 0.06, 0.4, 1.3, dark(m, 0.8)),
      ...box(0, 0.38, 0, 0.5, 0.02, 0.4, a),
    ],
  }),
};

const f1 = (x: number) => Math.round(x * 10) / 10;

/** Pure: same inputs, same SVG. n is the frame index; yaw = n / total of a full turn. */
export function renderTurntableFrame(shape: Shape, palette: PaletteName, n: number, total = FRAME_COUNT): string {
  const pal = PALETTES[palette];
  const { faces, shadow } = MODELS[shape](rgb(pal.main), rgb(pal.accent));
  const yaw = ((n % total) / total) * Math.PI * 2;
  const tilt = (15 * Math.PI) / 180;
  const [cy, sy, ct, st] = [Math.cos(yaw), Math.sin(yaw), Math.cos(tilt), Math.sin(tilt)];
  const view = (v: V): V => {
    const x = v[0] * cy + v[2] * sy;
    const z = -v[0] * sy + v[2] * cy;
    return [x, v[1] * ct - z * st, v[1] * st + z * ct];
  };
  const L = norm([-0.5, 0.8, 0.6]);
  const S = 150;
  const [ox, oy] = [200, 300];
  const drawn = faces
    .map((f) => {
      const p = f.p.map(view);
      let nn = view(f.n);
      if (nn[2] <= 0) {
        if (!f.two) return null;
        nn = [-nn[0], -nn[1], -nn[2]];
      }
      const k = 0.5 + 0.55 * Math.max(0, dot(nn, L));
      const col = f.c.map((x, i) => Math.min(255, Math.round(x * k + (i === 2 ? 6 : 0)))).join(",");
      return { z: p.reduce((s, q) => s + q[2], 0) / p.length, d: p.map((q) => `${f1(ox + q[0] * S)},${f1(oy - q[1] * S)}`).join(" "), col };
    })
    .filter((x): x is { z: number; d: string; col: string } => x !== null)
    .sort((a, b) => a.z - b.z || (a.d < b.d ? -1 : 1));
  const polys = drawn.map((d) => `<polygon points="${d.d}" fill="rgb(${d.col})" stroke="rgb(${d.col})" stroke-width="0.6" stroke-linejoin="round"/>`).join("");
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400" width="400" height="400"><defs><filter id="b" x="-30%" y="-100%" width="160%" height="300%"><feGaussianBlur stdDeviation="7"/></filter></defs><ellipse cx="200" cy="304" rx="170" ry="34" fill="#15302A" opacity="0.05"/><ellipse cx="205" cy="306" rx="${f1(S * shadow * 0.62)}" ry="${f1(S * shadow * 0.16)}" fill="#2F3438" opacity="0.22" filter="url(#b)"/>${polys}</svg>`;
}
