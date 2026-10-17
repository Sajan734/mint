import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

// The 3D viewer needs WebGL: stand in a stub that exposes its props and can fail on demand.
vi.mock("@/components/SplatViewer", () => ({
  default: (p: { src: string; label: string; onError?: (e: Error) => void }) => (
    <div data-testid="splat" data-src={p.src} aria-label={p.label}>
      <button onClick={() => p.onError?.(new Error("webglcontextlost"))}>fail</button>
    </div>
  ),
}));

import MediaPanel, { MediaProvider, MediaTiles, MediaViewer } from "@/components/MediaPanel";

afterEach(cleanup);
const frames = Array.from({ length: 8 }, (_, i) => `/f${i}.webp`);
const photos = ["/p1.webp", "/p2.webp", "/p3.webp", "/p4.webp"];
const pressed = (name: string) => screen.getByRole("button", { name }).getAttribute("aria-pressed");

describe("MediaPanel", () => {
  it("starts on 3D and shows the 3D tile plus at most 3 photo tiles", () => {
    render(<MediaPanel title="Mouse" splatUrl="/m.spz" frames={frames} photos={photos} />);
    expect(screen.getByTestId("splat")).toHaveAttribute("data-src", "/m.spz");
    expect(pressed("3D view")).toBe("true");
    expect(screen.getAllByRole("button", { name: /^Photo/ })).toHaveLength(3);
    expect(screen.queryByText("Sample 3D, not this item")).toBeNull();
  });

  it("clicking a tile shows that photo, clicking 3D goes back", () => {
    render(<MediaPanel title="Mouse" splatUrl="/m.spz" frames={frames} photos={photos} />);
    fireEvent.click(screen.getByRole("button", { name: "Photo 2" }));
    expect(screen.getByAltText("Mouse, photo 2")).toHaveAttribute("src", "/p2.webp");
    expect(pressed("Photo 2")).toBe("true");
    expect(pressed("3D view")).toBe("false");
    expect(screen.queryByTestId("splat")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "3D view" }));
    expect(screen.getByTestId("splat")).toBeInTheDocument();
  });

  it("works from the keyboard", async () => {
    const user = userEvent.setup();
    render(<MediaPanel title="Mouse" splatUrl={null} frames={frames} photos={photos} />);
    const tile = screen.getByRole("button", { name: "Photo 3" });
    tile.focus();
    await user.keyboard("{Enter}");
    expect(screen.getByAltText("Mouse, photo 3")).toBeInTheDocument();
    screen.getByRole("button", { name: "3D view" }).focus();
    await user.keyboard(" ");
    expect(pressed("3D view")).toBe("true");
  });

  it("labels a sample splat on the 3D view only", () => {
    render(<MediaPanel title="Mouse" splatUrl="/sample.spz" frames={[]} photos={photos} sample />);
    expect(screen.getByText("Sample 3D, not this item")).toBeInTheDocument();
    expect(screen.getByLabelText("Sample 3D view, not Mouse")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Photo 1" }));
    expect(screen.queryByText("Sample 3D, not this item")).toBeNull();
  });

  it("without a splat the 3D view is the frame spinner, and a failed splat falls back to it", () => {
    const { unmount } = render(<MediaPanel title="Mouse" splatUrl={null} frames={frames} photos={[]} />);
    expect(screen.getByRole("slider", { name: "360 degree view of Mouse" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "3D view" })).toBeNull(); // one view needs no tiles
    unmount();
    render(<MediaPanel title="Mouse" splatUrl="/m.spz" frames={frames} photos={photos} />);
    fireEvent.click(screen.getByRole("button", { name: "fail" }));
    expect(screen.getByRole("slider", { name: "360 degree view of Mouse" })).toBeInTheDocument();
  });

  it("with no 3D at all it opens on the first photo and has no 3D tile", () => {
    render(<MediaPanel title="Mouse" splatUrl={null} frames={[]} photos={photos} />);
    expect(screen.getByAltText("Mouse, photo 1")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "3D view" })).toBeNull();
    expect(pressed("Photo 1")).toBe("true");
  });

  it("says so when a photo file is missing", () => {
    render(<MediaPanel title="Mouse" splatUrl={null} frames={[]} photos={photos} />);
    fireEvent.error(screen.getByAltText("Mouse, photo 1"));
    expect(screen.getByText("Photo not on this machine")).toBeInTheDocument();
  });

  it("the viewer and tiles can be placed apart and share one selection", () => {
    render(
      <MediaProvider title="Mouse" splatUrl="/m.spz" frames={frames} photos={photos}>
        <section aria-label="left"><MediaViewer /></section>
        <section aria-label="right"><MediaTiles /></section>
      </MediaProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Photo 1" }));
    expect(screen.getByAltText("Mouse, photo 1")).toBeInTheDocument();
  });
});
