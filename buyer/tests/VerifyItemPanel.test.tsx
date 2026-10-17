import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import VerifyItemPanel from "@/components/VerifyItemPanel";
import sample from "@/mock/verify-sample.json";
import type { Explanation } from "@/lib/types";

afterEach(() => { cleanup(); vi.useRealTimers(); });
const ex = sample.explanation as Explanation;

function runScan(onVerify = () => {}) {
  vi.useFakeTimers();
  render(<VerifyItemPanel explanation={ex} verified={false} onVerify={onVerify} />);
  fireEvent.click(screen.getByRole("button", { name: "Start rescan" }));
  act(() => { vi.advanceTimersByTime(2000); });
}

describe("VerifyItemPanel", () => {
  it("explains first and hides the result until the demo rescan finishes", () => {
    render(<VerifyItemPanel explanation={ex} verified={false} onVerify={() => {}} />);
    expect(screen.getByText(/Rescan what you received/)).toBeInTheDocument();
    expect(screen.queryByText("Sample result")).toBeNull();
  });

  it("renders every section and the Sample pill", () => {
    runScan();
    expect(screen.getByText("Sample result")).toBeInTheDocument();
    const text = document.body.textContent ?? "";
    for (const t of [ex.headline, ex.what_we_compared, ex.how_sure, ex.disclaimer, ...ex.what_we_found, ...ex.listing_vs_item, ...ex.what_to_do, ...ex.caveats]) {
      expect(text).toContain(t);
    }
  });

  it("makes no price or payment claim beyond the disclaimer, and verifies on click", () => {
    const onVerify = vi.fn();
    runScan(onVerify);
    const text = (document.body.textContent ?? "").replace(ex.disclaimer, "");
    expect(text).not.toMatch(/\$|refund|payment|price/i);
    fireEvent.click(screen.getByRole("button", { name: "Mark as verified" }));
    expect(onVerify).toHaveBeenCalled();
  });
});
