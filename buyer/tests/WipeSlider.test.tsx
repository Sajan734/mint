import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import WipeSlider from "@/components/WipeSlider";

afterEach(cleanup);

const flagged = new Map([[0, ["part_diff" as const, "color_diff" as const]]]);
const setup = (onIndex = vi.fn(), index = 0) =>
  render(<WipeSlider run8="435e1251" count={3} index={index} onIndex={onIndex} flagged={flagged} />);

describe("WipeSlider", () => {
  it("shows the listing view under the buyer's view of the same pair, both labelled", () => {
    setup();
    expect(screen.getByAltText("Listing, view 1")).toHaveAttribute("src", "/local/compare/435e1251/a_00.webp");
    expect(screen.getByAltText("Your scan, view 1")).toHaveAttribute("src", "/local/compare/435e1251/b_00.webp");
    expect(screen.getByText("Listing")).toBeInTheDocument();
    expect(screen.getByText("Your scan")).toBeInTheDocument();
  });

  it("is a keyboard-reachable native range input that moves the wipe", async () => {
    setup();
    await userEvent.tab();
    const slider = screen.getByRole("slider", { name: "Compare the listing with your scan" });
    expect(slider).toHaveFocus();
    expect(slider).toHaveValue("50");
    const top = screen.getByAltText("Your scan, view 1");
    expect(top.style.clipPath).toBe("inset(0 0 0 50%)");
    fireEvent.change(slider, { target: { value: "80" } }); // what ArrowRight / End do natively
    expect(top.style.clipPath).toBe("inset(0 0 0 80%)");
    expect(slider).toHaveAttribute("aria-valuetext", "80% listing, 20% your scan");
  });

  it("drags with a pointer", () => {
    setup();
    const stage = screen.getByTestId("wipe-stage");
    stage.getBoundingClientRect = () => ({ left: 100, width: 400, top: 0, height: 225, right: 500, bottom: 225, x: 100, y: 0, toJSON: () => ({}) });
    fireEvent.pointerDown(stage, { clientX: 400, pointerId: 1 });
    expect(screen.getByAltText("Your scan, view 1").style.clipPath).toBe("inset(0 0 0 75%)");
  });

  it("switches pairs from the thumbnail strip with the keyboard, flagged views in words", async () => {
    const onIndex = vi.fn();
    setup(onIndex);
    const first = screen.getByRole("button", { name: /View 1: A part looks different or missing; Colours look different/ });
    expect(first).toHaveAttribute("aria-pressed", "true");
    const third = screen.getByRole("button", { name: "View 3" });
    third.focus();
    await userEvent.keyboard("{Enter}");
    expect(onIndex).toHaveBeenCalledWith(2);
  });

  it("explains how to get the photos when they are not on this machine", () => {
    setup();
    fireEvent.error(screen.getByAltText("Listing, view 1"));
    expect(screen.getByText(/Comparison photos are not on this machine/)).toHaveTextContent(
      "Comparison photos are not on this machine. Run python buyer/scripts/make_demo_assets.py.",
    );
    expect(screen.queryByRole("slider")).toBeNull();
  });
});
