import { describe, expect, it } from "vitest";
import { phaseOf, splatFraction, stepState } from "../lib/progress";
import { isScanId, scanDeepLink } from "../lib/scan";
import type { ListingDoc } from "../lib/types";

const doc = (status: ListingDoc["status"]): ListingDoc => ({ v: 3, scan_id: "x", status });

describe("phaseOf", () => {
  it("waits for the phone until anything happens", () => {
    expect(phaseOf({ stages: {}, manifest: false, listing: null })).toBe("waiting");
  });
  it("is scanning once the splat job reports a stage", () => {
    expect(phaseOf({ stages: { "1_frames": "started" }, manifest: false, listing: null })).toBe("scanning");
  });
  it("is writing once the 3D scan is published or the listing step started", () => {
    expect(phaseOf({ stages: {}, manifest: true, listing: null })).toBe("writing");
    expect(phaseOf({ stages: { "7_listing": "started" }, manifest: false, listing: null })).toBe("writing");
  });
  it("ends with the listing document's status", () => {
    for (const s of ["listed", "rejected", "failed"] as const) {
      expect(phaseOf({ stages: {}, manifest: true, listing: doc(s) })).toBe(s);
    }
  });
});

describe("splatFraction", () => {
  it("counts finished splat stages, per-video names once", () => {
    expect(splatFraction({})).toBe(0);
    expect(splatFraction({ "1_frames": "done", "2_masks_top": "done", "2_masks_bottom": "done", "3_poses_top": "started" })).toBeCloseTo(2 / 6);
    expect(splatFraction({ "1_frames": "done", "2_masks_top": "done", "3_poses_top": "done", "4_train": "done", "5_clean_export": "done", "6_views": "done" })).toBe(1);
  });
});

describe("stepState", () => {
  it("marks earlier steps done, the current one active, later ones todo", () => {
    expect(stepState("waiting", "writing")).toBe("done");
    expect(stepState("writing", "writing")).toBe("active");
    expect(stepState("listed", "writing")).toBe("todo");
    expect(stepState("listed", "listed")).toBe("done");
  });
  it("stops at the listing step when the scan is rejected or failed", () => {
    expect(stepState("writing", "rejected")).toBe("active");
    expect(stepState("listed", "failed")).toBe("todo");
  });
});

describe("scan ids and the deep link", () => {
  it("accepts only lowercase UUIDs (what the upload function accepts)", () => {
    expect(isScanId("0f8b7c1e-2a3d-4e5f-8a9b-0c1d2e3f4a5b")).toBe(true);
    expect(isScanId("../etc/passwd")).toBe(false);
    expect(isScanId("0F8B7C1E-2A3D-4E5F-8A9B-0C1D2E3F4A5B")).toBe(false);
  });
  it("hands the scan id to the app", () => {
    expect(scanDeepLink("0f8b7c1e-2a3d-4e5f-8a9b-0c1d2e3f4a5b")).toBe("mint://scan?id=0f8b7c1e-2a3d-4e5f-8a9b-0c1d2e3f4a5b");
  });
});
