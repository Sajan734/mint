import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import SpinViewer from "@/components/SpinViewer";

afterEach(cleanup);
const frames = Array.from({ length: 8 }, (_, i) => `/f${i}.jpg`);

describe("SpinViewer", () => {
  it("steps and wraps with arrow keys", () => {
    render(<SpinViewer frames={frames} alt="Mug" variant="detail" />);
    const s = screen.getByRole("slider", { name: "360 degree view of Mug" });
    fireEvent.keyDown(s, { key: "ArrowLeft" });
    expect(s).toHaveAttribute("aria-valuenow", "7");
    fireEvent.keyDown(s, { key: "ArrowRight" });
    expect(s).toHaveAttribute("aria-valuenow", "0");
    expect(screen.getByText("360")).toBeInTheDocument();
  });
  it("single frame is a static image, no slider", () => {
    render(<SpinViewer frames={["/a.jpg"]} alt="Mug" variant="card" />);
    expect(screen.queryByRole("slider")).toBeNull();
  });
  it("renders the splat slot when viewerUrl is set", () => {
    render(<SpinViewer frames={frames} alt="Mug" variant="detail" viewerUrl="/x.spz" splat={<p>splat</p>} />);
    expect(screen.getByText("splat")).toBeInTheDocument();
  });
  it("falls back to frame 0 when the shown frame errors", () => {
    render(<SpinViewer frames={frames} alt="Mug" variant="card" />);
    fireEvent.error(screen.getByAltText("Mug"));
    expect(screen.getByAltText("Mug")).toHaveAttribute("src", "/f0.jpg");
  });
});
