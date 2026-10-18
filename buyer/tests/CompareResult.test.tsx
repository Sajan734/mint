import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import type { CompareResponse, VerdictCause, VerdictLabel } from "@/lib/compare-types";
import r435 from "@/mock/compare/435e1251.json";
import rcce from "@/mock/compare/cce6fb01.json";
import rfc4 from "@/mock/compare/fc4b95cb.json";

// jsdom has no WebGL: record what the 3D wipe hands each viewer.
const viewers: { src: string; label: string; sharedPose?: object }[] = [];
vi.mock("@/components/SplatViewer", () => ({
  default: (p: { src: string; label: string; sharedPose?: object }) => {
    viewers.push(p);
    return <div role="img" aria-label={p.label} />;
  },
}));
import CompareResult from "@/components/CompareResult";

afterEach(() => {
  cleanup();
  viewers.length = 0;
});

const R435 = r435 as unknown as CompareResponse;
const RCCE = rcce as unknown as CompareResponse;
const RFC4 = rfc4 as unknown as CompareResponse;
const show = (result: CompareResponse, extra: Partial<Parameters<typeof CompareResult>[0]> = {}) =>
  render(<CompareResult result={result} listingId="pots_i1" {...extra} />);
const withLabel = (label: VerdictLabel): CompareResponse => ({ ...R435, verdict: { ...R435.verdict!, label } });

describe("CompareResult", () => {
  it.each([
    ["same", "Looks like the same item"],
    ["different", "Does not match the listing"],
  ] as const)("heads a %s verdict with %s", (label, text) => {
    show(withLabel(label));
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(text);
  });

  it.each([
    ["low_quality", "Your scan was not clear enough to confirm a match"],
    ["misaligned", "The two scans did not line up"],
    ["listing_rejected", "The listing scan could not be used"],
  ] as const)("shows the %s cause line under a different verdict", (cause: VerdictCause, text) => {
    show({ ...R435, verdict: { ...R435.verdict!, label: "different", cause } });
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Does not match the listing");
    expect(screen.getByText(text)).toBeInTheDocument();
    expect(document.querySelector('[data-icon="check"]')?.closest("h1")).toBeNull();
  });

  it("shows no cause line when there is no cause (old recorded runs)", () => {
    show(R435);
    expect(screen.queryByText(/not clear enough|did not line up|could not be used/)).toBeNull();
  });

  it("only a same verdict gets the match mark; different gets a cross, never a dash", () => {
    for (const label of ["same", "different"] as const) {
      const { container, unmount } = show(withLabel(label));
      const icons = [...container.querySelectorAll("h1 svg")].map((s) => (s as SVGElement).dataset.icon);
      expect(icons).toEqual([label === "same" ? "check" : "cross"]);
      unmount();
    }
  });

  it("shows how sure, the views compared, the flagged differences and the next step", () => {
    show(R435);
    expect(screen.getByText("We have fairly strong evidence. This is not proof.")).toBeInTheDocument();
    expect(screen.getByText("11 usable views of 12")).toBeInTheDocument();
    const diff = screen.getByRole("region", { name: "What looks different" });
    expect(within(diff).getByText("A part looks different or missing")).toBeInTheDocument();
    expect(within(diff).getByText("Colours look different")).toBeInTheDocument();
    expect(within(diff).getAllByText("in 11 of 11 views")).toHaveLength(1);
    expect(within(diff).getByText("in 10 of 11 views")).toBeInTheDocument();
    expect(screen.getByText(R435.next_step!.summary)).toBeInTheDocument();
    expect(screen.getByText(R435.next_step!.message_to_seller!)).toBeInTheDocument();
    expect(screen.getByText("Drafted by AI")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Contact seller" })).toHaveAttribute("href", "/listing/pots_i1#contact");
    expect(screen.getByText("This is an automated visual comparison and can be wrong. It does not check price or payment.")).toBeInTheDocument();
  });

  it("says how many views failed", () => {
    const ev = R435.verdict!.evidence;
    show({ ...R435, verdict: { ...R435.verdict!, evidence: { ...ev, failed_views: [{ view: "view_04", code: "timeout" }] } } });
    expect(screen.getByText("11 usable views of 12")).toBeInTheDocument();
    expect(screen.getByText("1 failed")).toBeInTheDocument();
  });

  it("leaves out how sure when the run has no explanation", () => {
    show(RCCE); // a real run with no explanation
    expect(screen.queryByText(/evidence\. This is not proof/)).toBeNull();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Does not match the listing");
    expect(screen.getByText("9 usable views of 12")).toBeInTheDocument();
  });

  it("marks every claim with an icon and a word, never colour alone", () => {
    show(R435);
    const claims = within(screen.getByRole("region", { name: "What the listing says" })).getAllByRole("listitem").filter((li) => li.dataset.status);
    expect(claims.map((li) => [li.dataset.status, li.querySelector("svg")?.dataset.icon])).toEqual([
      ["supported", "check"],
      ["contradicted", "cross"],
      ["unverifiable", "dash"],
    ]);
    expect(within(claims[0]).getByText("Seen in your scan")).toBeInTheDocument();
    expect(within(claims[1]).getByText("Not seen in your scan")).toBeInTheDocument();
    expect(within(claims[2]).getByText("Cannot check from a scan")).toBeInTheDocument();
    expect(within(claims[0]).getByText("watering can")).toBeInTheDocument();
  });

  it("says so when the listing has no claims", () => {
    show({ ...R435, claims_available: false, claims_findings: [] });
    expect(screen.getByText("The listing has no claims to check.")).toBeInTheDocument();
  });

  it("explains a failed check and offers Try again", () => {
    show({ ...R435, status: "failed", verdict: null, next_step: null, explanation: null, error: { code: "jev_down", message: "The comparison service did not answer." } });
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Could not run the check, try again");
    expect(screen.getByText("The comparison service did not answer.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Try again" })).toHaveAttribute("href", "/listing/pots_i1/check");
    expect(screen.queryByRole("slider")).toBeNull();
  });

  it("never renders a failed check as a match or with any verdict mark", () => {
    const { container } = show({ ...R435, status: "failed", verdict: R435.verdict, error: { code: "x", message: "Nope." } });
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Could not run the check, try again");
    expect(screen.getByRole("heading", { level: 1 })).not.toHaveTextContent(/Looks like the same/);
    expect(container.querySelector("h1 svg")).toBeNull();
  });

  it("has no view-by-view compare UI", () => {
    show(R435);
    expect(screen.queryByRole("heading", { name: "Compare views" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Show view/ })).toBeNull();
    expect(screen.queryByRole("slider")).toBeNull();
  });

  it("copies the drafted message", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    show(R435);
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Copy message" })));
    expect(writeText).toHaveBeenCalledWith(R435.next_step!.message_to_seller);
    expect(screen.getByRole("button", { name: "Copied" })).toBeInTheDocument();
  });

  it("hides the AI tag for a template message", () => {
    show({ ...R435, next_step: { ...R435.next_step!, is_template: true, drafted_by: "template" } });
    expect(screen.queryByText("Drafted by AI")).toBeNull();
  });

  it("labels a recorded run in the footer, with the note for another item", () => {
    show(R435, { recorded: true, note: "This recorded check is from a different item (a plant shelf)." });
    expect(screen.getByText("Recorded result")).toBeInTheDocument();
    expect(screen.getByText("Run 435e1251 · 5.0 s")).toBeInTheDocument();
    expect(screen.getByText("This recorded check is from a different item (a plant shelf).")).toBeInTheDocument();
  });

  it("never prints a score, a probability or a percentage", () => {
    for (const r of [R435, RCCE, RFC4]) {
      const { container, unmount } = show(r, { recorded: true });
      const text = container.textContent ?? "";
      expect(text).not.toMatch(/%/);
      const ev = r.verdict!.evidence;
      const scores = [
        r.verdict!.evidence_score!,
        ...Object.values(ev.categories).flatMap((c) => [c!.evidence, c!.max]),
        ...r.claims_findings.flatMap((f) => (f.p_present === null ? [] : [f.p_present])),
      ];
      for (const n of scores) {
        expect(text).not.toContain(String(n));
        expect(text).not.toContain(n.toFixed(2).replace(/^0/, "")); // ".97"
      }
      unmount();
    }
  });

  it("shows the 3D wipe only when both scans have a splat, with one shared camera", () => {
    show(R435);
    expect(screen.queryByRole("region", { name: "Both scans in 3D" })).toBeNull();
    cleanup();
    show(R435, { splats: { listing: "https://x.test/a.spz", buyer: "https://x.test/b.spz" } });
    expect(screen.getByRole("region", { name: "Both scans in 3D" })).toBeInTheDocument();
    expect(viewers.map((v) => v.src).slice(-2)).toEqual(["https://x.test/a.spz", "https://x.test/b.spz"]);
    const [a, b] = viewers.slice(-2);
    expect(a.sharedPose).toBeDefined();
    expect(a.sharedPose).toBe(b.sharedPose);
    fireEvent.change(screen.getByRole("slider", { name: "Compare the listing's 3D scan with yours" }), { target: { value: "30" } });
    expect(screen.getByTestId("splat-wipe-top").style.clipPath).toBe("inset(0 0 0 30%)");
  });
});
