// Twin: buyer/lib/splat-scene.ts (keep identical)
// Imperative three + Spark scene. Browser only: import it with `await import("@/lib/splat-scene")` from an effect,
// never at module top level of a server-rendered file. Tests mock this module (jsdom has no WebGL).
export type CameraPose = { azimuth: number; polar: number; distance: number }; // distance in framing radii

export type SceneOptions = {
  src: string;
  autoRotate: boolean;
  interactive: boolean;
  maxPixelRatio: number;
  sharedPose?: { current: CameraPose };
  onReady: () => void;
  onError: (err: Error) => void;
};
export type SceneHandle = { dispose: () => void };

const FOV = 50;
const DISPOSE_WAIT_MS = 8000;
const KEY_TURN = Math.PI / 12; // 15 degrees per arrow press
const KEY_ZOOM = 1.15;

type Engine = [typeof import("three"), typeof import("three/addons/controls/OrbitControls.js"), typeof import("@sparkjsdev/spark")];
let engine: Promise<Engine> | undefined;
/** Loads three + Spark once (about 1.9 MB gzip). Call it on idle to warm the first hover. */
export function loadEngine(): Promise<Engine> {
  engine ??= Promise.all([import("three"), import("three/addons/controls/OrbitControls.js"), import("@sparkjsdev/spark")]);
  engine.catch(() => { engine = undefined; }); // a failed chunk load can be retried on the next mount
  return engine;
}

function poseOf(p: { x: number; y: number; z: number }, c: { x: number; y: number; z: number }, r: number): CameraPose {
  const dx = p.x - c.x, dy = p.y - c.y, dz = p.z - c.z;
  const d = Math.hypot(dx, dy, dz);
  return { azimuth: Math.atan2(dx, dz), polar: Math.acos(dy / d), distance: d / r };
}

export async function mountSplatScene(host: HTMLElement, o: SceneOptions): Promise<SceneHandle> {
  const [THREE, { OrbitControls }, { SparkRenderer, SplatMesh, SplatFileType }] = await loadEngine();
  let disposed = false;
  const renderer = new THREE.WebGLRenderer({ antialias: false, alpha: true, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, o.maxPixelRatio));
  const canvas = renderer.domElement;
  // pan-y: one finger sideways turns the item, up/down still scrolls the page, two fingers zoom.
  canvas.style.cssText = `position:absolute;inset:0;opacity:0;transition:opacity 200ms;display:block;width:100%;height:100%;touch-action:${o.interactive ? "pan-y" : "auto"};pointer-events:${o.interactive ? "auto" : "none"};cursor:${o.interactive ? "grab" : "default"}`;
  host.appendChild(canvas);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(FOV, 1, 0.01, 100);
  const spark = new SparkRenderer({ renderer });
  scene.add(spark);
  const controls = new OrbitControls(camera, canvas);
  controls.enabled = o.interactive;
  controls.enablePan = false; // keep the item centred
  controls.enableDamping = !o.sharedPose;
  controls.autoRotate = o.autoRotate;
  controls.autoRotateSpeed = o.interactive ? 1.5 : 4; // 60 / speed = seconds per turn: 40 s on a page, 15 s on a card
  const center = new THREE.Vector3();
  let radius = 1;
  let userActive = false;
  const stopAuto = () => { controls.autoRotate = false; };
  controls.addEventListener("start", () => { userActive = true; stopAuto(); });
  controls.addEventListener("end", () => { userActive = false; });

  // Arrow keys orbit, +/- zoom (OrbitControls' own keys pan, and turn under a degree per press).
  const onKey = (e: KeyboardEvent) => {
    const turn: Record<string, [number, number]> = { ArrowLeft: [KEY_TURN, 0], ArrowRight: [-KEY_TURN, 0], ArrowUp: [0, KEY_TURN], ArrowDown: [0, -KEY_TURN] };
    const zoom: Record<string, number> = { "+": 1 / KEY_ZOOM, "=": 1 / KEY_ZOOM, "-": KEY_ZOOM, _: KEY_ZOOM };
    if (!(e.key in turn) && !(e.key in zoom)) return;
    e.preventDefault();
    stopAuto();
    const s = new THREE.Spherical().setFromVector3(camera.position.clone().sub(controls.target));
    const [dTheta, dPhi] = turn[e.key] ?? [0, 0];
    s.theta += dTheta;
    s.phi = THREE.MathUtils.clamp(s.phi - dPhi, 0.05, Math.PI - 0.05);
    s.radius = THREE.MathUtils.clamp(s.radius * (zoom[e.key] ?? 1), controls.minDistance, controls.maxDistance);
    camera.position.setFromSpherical(s).add(controls.target);
    if (o.sharedPose) o.sharedPose.current = poseOf(camera.position, center, radius);
  };
  if (o.interactive) host.addEventListener("keydown", onKey);

  const resize = () => {
    const w = host.clientWidth || 1, h = host.clientHeight || 1;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  };
  const ro = new ResizeObserver(resize);
  ro.observe(host);
  resize();

  const fail = (e: unknown) => { if (!disposed) o.onError(e instanceof Error ? e : new Error(String(e))); };
  const onLost = (e: Event) => { e.preventDefault(); fail(new Error("webglcontextlost")); };
  canvas.addEventListener("webglcontextlost", onLost);

  let visible = true; // draw only while on screen and the tab is visible
  const io = new IntersectionObserver(([en]) => { visible = en.isIntersecting; });
  io.observe(host);

  const ext = new URL(o.src, window.location.href).pathname.split(".").pop()?.toLowerCase();
  const fileType = Object.values(SplatFileType).find((t) => t === ext) ?? SplatFileType.SPZ;
  const mesh = new SplatMesh({ url: o.src, fileType });
  scene.add(mesh);

  let drawn = false;
  let last = 0;
  renderer.setAnimationLoop((t: number) => {
    const dt = last ? Math.min((t - last) / 1000, 0.1) : 0; // seconds, so auto-rotate speed ignores refresh rate
    last = t;
    if (!visible || document.hidden) return;
    const sp = o.sharedPose;
    if (sp) {
      if (userActive) sp.current = poseOf(camera.position, center, radius);
      else {
        const p = sp.current, d = p.distance * radius;
        camera.position.set(
          center.x + d * Math.sin(p.polar) * Math.sin(p.azimuth),
          center.y + d * Math.cos(p.polar),
          center.z + d * Math.sin(p.polar) * Math.cos(p.azimuth),
        );
      }
    }
    controls.update(dt);
    renderer.render(scene, camera);
    if (!drawn && mesh.isInitialized) { drawn = true; canvas.style.opacity = "1"; o.onReady(); }
  });

  mesh.initialized
    .then(() => {
      if (disposed) return;
      const box = mesh.getBoundingBox();
      if (box.isEmpty()) throw new Error("empty splat");
      box.getCenter(center);
      radius = box.getSize(new THREE.Vector3()).length() / 2;
      controls.target.copy(center);
      const d = (radius / Math.sin((FOV / 2) * (Math.PI / 180))) * 0.9;
      camera.position.set(center.x, center.y + radius * 0.6, center.z + d);
      camera.near = radius / 100;
      camera.far = radius * 100;
      camera.updateProjectionMatrix();
      controls.minDistance = radius * 0.5;
      controls.maxDistance = radius * 8;
      const sp = o.sharedPose;
      if (sp && sp.current.distance === 0) sp.current = poseOf(camera.position, center, radius);
    })
    .catch(fail);

  return {
    dispose() {
      if (disposed) return;
      disposed = true;
      renderer.setAnimationLoop(null);
      io.disconnect();
      ro.disconnect();
      canvas.removeEventListener("webglcontextlost", onLost);
      host.removeEventListener("keydown", onKey);
      controls.dispose();
      scene.remove(mesh);
      canvas.remove();
      // Spark rejects in-flight worker calls when disposed (unhandled rejections; Next's dev overlay shows "N Issues").
      // Wait until its sort worker and the loader are idle (measured: 0 rejections over 16 mount/unmount cycles).
      const t0 = performance.now();
      const free = () => {
        if ((spark.sorting || !mesh.isInitialized) && performance.now() - t0 < DISPOSE_WAIT_MS) { setTimeout(free, 50); return; }
        try { mesh.dispose(); } catch { /* already disposed */ }
        spark.dispose();
        renderer.dispose();
        renderer.forceContextLoss(); // frees the context slot now, not at GC
      };
      free();
    },
  };
}
