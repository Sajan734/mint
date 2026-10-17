// Twin: buyer/tests/SplatViewer.test.tsx (keep identical)
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SceneOptions } from "@/lib/splat-scene";
import { acquireSlot, liveSlots, releaseSlot } from "@/lib/viewer-slots";

// jsdom has no WebGL: the whole three + Spark scene is behind this one module, so mock it.
const mounts: Array<{ opts: SceneOptions; dispose: ReturnType<typeof vi.fn> }> = [];
let gate: Promise<void> = Promise.resolve();
vi.mock("@/lib/splat-scene", () => ({
  mountSplatScene: vi.fn(async (_host: HTMLElement, opts: SceneOptions) => {
    await gate;
    const dispose = vi.fn();
    mounts.push({ opts, dispose });
    return { dispose };
  }),
}));

import SplatViewer from "@/components/SplatViewer";

beforeEach(() => { mounts.length = 0; gate = Promise.resolve(); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("SplatViewer", () => {
  it("shows the poster until the scene reports ready, then calls onLoad", async () => {
    const onLoad = vi.fn();
    const { container } = render(<SplatViewer src="a.spz" label="Lamp" poster="p.jpg" onLoad={onLoad} />);
    const poster = container.querySelector("img")!;
    expect(poster).toHaveStyle({ opacity: "1" });
    await waitFor(() => expect(mounts).toHaveLength(1));
    act(() => mounts[0].opts.onReady());
    expect(poster).toHaveStyle({ opacity: "0" });
    expect(onLoad).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("img", { name: "Lamp" })).toBeInTheDocument();
  });

  it("on a scene error tells the parent, frees the scene and shows the poster with a note", async () => {
    const onError = vi.fn();
    const { container } = render(<SplatViewer src="a.spz" label="Lamp" poster="p.jpg" onError={onError} />);
    await waitFor(() => expect(mounts).toHaveLength(1));
    act(() => mounts[0].opts.onReady());
    act(() => mounts[0].opts.onError(new Error("webglcontextlost")));
    expect(onError).toHaveBeenCalledWith(expect.objectContaining({ message: "webglcontextlost" }));
    expect(mounts[0].dispose).toHaveBeenCalledTimes(1);
    expect(container.querySelector("img")).toHaveStyle({ opacity: "1" });
    expect(screen.getByText("3D view not available")).toBeInTheDocument();
  });

  it("disposes the scene on unmount", async () => {
    const { unmount } = render(<SplatViewer src="a.spz" label="Lamp" />);
    await waitFor(() => expect(mounts).toHaveLength(1));
    unmount();
    expect(mounts[0].dispose).toHaveBeenCalledTimes(1);
    expect(liveSlots()).toBe(0);
  });

  it("disposes a scene that finishes mounting after the component is gone", async () => {
    let release!: () => void;
    gate = new Promise((r) => { release = r; });
    const { unmount } = render(<SplatViewer src="a.spz" label="Lamp" />);
    unmount();
    release();
    await waitFor(() => expect(mounts).toHaveLength(1));
    await waitFor(() => expect(mounts[0].dispose).toHaveBeenCalledTimes(1));
  });

  it("rebuilds only when src changes, not when callbacks change", async () => {
    const { rerender } = render(<SplatViewer src="a.spz" label="Lamp" onLoad={() => {}} />);
    await waitFor(() => expect(mounts).toHaveLength(1));
    rerender(<SplatViewer src="a.spz" label="Lamp" onLoad={() => {}} />);
    expect(mounts).toHaveLength(1);
    rerender(<SplatViewer src="b.spz" label="Lamp" />);
    await waitFor(() => expect(mounts).toHaveLength(2));
    expect(mounts[0].dispose).toHaveBeenCalledTimes(1);
  });

  it("ignores events from a scene that was already torn down", async () => {
    const onLoad = vi.fn();
    const { unmount } = render(<SplatViewer src="a.spz" label="Lamp" onLoad={onLoad} />);
    await waitFor(() => expect(mounts).toHaveLength(1));
    unmount();
    mounts[0].opts.onReady();
    expect(onLoad).not.toHaveBeenCalled();
  });

  it("turns auto-rotate off under prefers-reduced-motion", async () => {
    vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("reduce") }));
    render(<SplatViewer src="a.spz" label="Lamp" autoRotate />);
    await waitFor(() => expect(mounts).toHaveLength(1));
    expect(mounts[0].opts.autoRotate).toBe(false);
  });

  it("a third viewer evicts the oldest, which can come back with Show 3D", async () => {
    render(<SplatViewer src="a.spz" label="A" interactive />);
    await waitFor(() => expect(mounts).toHaveLength(1));
    render(<SplatViewer src="b.spz" label="B" />);
    await waitFor(() => expect(mounts).toHaveLength(2));
    render(<SplatViewer src="c.spz" label="C" />);
    await waitFor(() => expect(mounts).toHaveLength(3));
    expect(mounts[0].dispose).toHaveBeenCalledTimes(1);
    expect(liveSlots()).toBe(2);
    fireEvent.click(screen.getByRole("button", { name: "Show 3D" }));
    await waitFor(() => expect(mounts).toHaveLength(4));
    expect(mounts[1].dispose).toHaveBeenCalledTimes(1); // B was now the oldest
  });

  it("is a focusable, described 3D viewer when interactive", async () => {
    render(<SplatViewer src="a.spz" label="Lamp" interactive />);
    const viewer = screen.getByRole("application", { name: "Lamp" });
    expect(viewer).toHaveAttribute("tabindex", "0");
    expect(viewer).toHaveAccessibleDescription(/arrow keys/);
    await waitFor(() => expect(mounts).toHaveLength(1));
    expect(mounts[0].opts.interactive).toBe(true);
  });
});

describe("viewer slots", () => {
  it("keeps at most two live viewers and evicts the oldest first", () => {
    const evicted: string[] = [];
    const a = acquireSlot("a", () => evicted.push("a"));
    acquireSlot("b", () => evicted.push("b"));
    acquireSlot("c", () => evicted.push("c"));
    expect(evicted).toEqual(["a"]);
    expect(liveSlots()).toBe(2);
    a(); // releasing an evicted slot is harmless
    releaseSlot("b");
    releaseSlot("c");
    expect(liveSlots()).toBe(0);
  });
});
