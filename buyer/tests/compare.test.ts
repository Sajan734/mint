import { describe, expect, it } from "vitest";
import {
  CATEGORY_WORDS,
  CLAIM_WORDS,
  FAILED_HEADING,
  OTHER_ITEM_NOTE,
  flaggedByView,
  heading,
  mockRun,
  pairSrc,
  pickRun,
  runFooter,
  viewIndex,
  viewLabel,
  viewName,
} from "@/lib/compare";
import type { CompareResponse } from "@/lib/compare-types";
import r435 from "@/mock/compare/435e1251.json";
import rcce from "@/mock/compare/cce6fb01.json";
import rfc4 from "@/mock/compare/fc4b95cb.json";

const runs = [r435, rcce, rfc4] as unknown as CompareResponse[];

describe("word maps", () => {
  it("has a heading for every verdict label and for a failed check", () => {
    expect(heading(runs[0])).toBe("Does not match the listing");
    const base = runs[0];
    const v = base.verdict!;
    const cases = {
      same: "Looks like the same item",
      different: "Does not match the listing",
      uncertain: "We cannot tell",
      alignment_failed: "The two scans do not line up",
      scan_quality_poor: "Your scan is not clear enough",
      listing_rejected: "The listing scan cannot be used",
    } as const;
    for (const [label, text] of Object.entries(cases)) {
      expect(heading({ ...base, verdict: { ...v, label: label as keyof typeof cases } })).toBe(text);
    }
    expect(heading({ ...base, status: "failed", verdict: null })).toBe(FAILED_HEADING);
  });

  it("names every evidence category and claim status in plain words", () => {
    expect(CATEGORY_WORDS).toEqual({
      part_diff: "A part looks different or missing",
      color_diff: "Colours look different",
      shape_diff: "The shape looks different",
      any_diff: "Something looks different",
    });
    expect(CLAIM_WORDS).toEqual({
      supported: "Seen in your scan",
      contradicted: "Not seen in your scan",
      unverifiable: "Cannot check from a scan",
    });
  });
});

describe("view mapping (file a_NN / b_NN, NN 0-based = label view_{NN+1})", () => {
  it("maps both ways", () => {
    expect(viewLabel(0)).toBe("view_01");
    expect(viewLabel(11)).toBe("view_12");
    expect(viewIndex("view_01")).toBe(0);
    expect(viewIndex("view_12")).toBe(11);
    for (let i = 0; i < 12; i++) expect(viewIndex(viewLabel(i))).toBe(i);
  });
  it("rejects labels that are not views", () => {
    expect(viewIndex("view_00")).toBeNull();
    expect(viewIndex("front")).toBeNull();
    expect(viewIndex("")).toBeNull();
  });
  it("builds image paths and display names", () => {
    expect(pairSrc("435e1251", 0, "a")).toBe("/local/compare/435e1251/a_00.webp");
    expect(pairSrc("435e1251", 10, "b")).toBe("/local/compare/435e1251/b_10.webp");
    expect(viewName("view_03")).toBe("View 3");
  });
  it("lists the flagged categories per view index", () => {
    const m = flaggedByView(runs[2]); // fc4b95cb: part_diff flagged; color_diff has a view but is not flagged
    expect(m.get(0)).toEqual(["part_diff"]);
    expect(m.get(9)).toEqual(["part_diff"]);
    expect(m.has(2)).toBe(false); // view_03 is in no flagged category
    expect(flaggedByView(runs[0]).get(0)).toEqual(["part_diff", "color_diff"]);
    expect(flaggedByView(runs[0]).get(6)).toEqual(["part_diff"]); // view_07: part only
  });
});

describe("pickRun", () => {
  it("uses the pots run for pots listings, with no note", () => {
    expect(pickRun("pots_i1")).toEqual({ run: "435e1251", note: null });
    // a listing published from the seller demo: random id, pots photos
    expect(pickRun("9b1c2d3e-0000-4000-8000-000000000000", ["/local/pots/f00.webp"])).toEqual({ run: "435e1251", note: null });
  });
  it("uses the zen run for zen", () => {
    expect(pickRun("zen_i1")).toEqual({ run: "cce6fb01", note: null });
  });
  it("falls back to the pots run with an honest note", () => {
    expect(pickRun("itm_0003", ["/frames/mug/sage/0"])).toEqual({ run: "435e1251", note: OTHER_ITEM_NOTE });
    expect(OTHER_ITEM_NOTE).toBe("This recorded check is from a different item (a plant shelf).");
  });
  it("loads the real recorded responses", () => {
    expect(mockRun("435e1251").comparison_id).toBe("435e1251-4d67-4a65-ac2f-a8fcff39dd0c");
    expect(mockRun("cce6fb01").comparison_id).toBe("cce6fb01-06fb-47de-803d-bb06a2b5e1a3");
  });
});

describe("runFooter", () => {
  it("shows the short run id and total seconds", () => {
    expect(runFooter(runs[0])).toBe("Run 435e1251 · 5.0 s");
    expect(runFooter(runs[1])).toBe("Run cce6fb01 · 6.4 s");
    expect(runFooter({ ...runs[0], timings_ms: {} })).toBe("Run 435e1251");
  });
});
