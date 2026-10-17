import { describe, expect, it } from "vitest";
import { STEPS, stepMark, subStepLabel } from "../lib/progress";
import { isScanId, scanDeepLink } from "../lib/scan";

describe("STEPS", () => {
  it("has the same five steps for a listing and a check, in order", () => {
    const ids = ["waiting", "connected", "uploading", "processing", "ready"];
    expect(STEPS.listing.map((s) => s.id)).toEqual(ids);
    expect(STEPS.verify.map((s) => s.id)).toEqual(ids);
    expect(STEPS.listing[0].label).toBe("Scan this code with your iPhone");
    expect(STEPS.listing[4].label).toBe("Your listing is ready");
    expect(STEPS.verify[3].label).toBe("Comparing with the listing");
  });
});

describe("stepMark", () => {
  it("marks earlier steps done, the current one active, later ones todo", () => {
    expect(stepMark("waiting", "uploading")).toBe("done");
    expect(stepMark("uploading", "uploading")).toBe("active");
    expect(stepMark("processing", "uploading")).toBe("todo");
  });
  it("marks everything done when ready", () => {
    for (const s of STEPS.listing) expect(stepMark(s.id, "ready")).toBe("done");
  });
  it("stops at processing when rejected or failed, at the phone when cancelled", () => {
    expect(stepMark("uploading", "failed")).toBe("done");
    expect(stepMark("processing", "rejected")).toBe("stopped");
    expect(stepMark("ready", "failed")).toBe("todo");
    expect(stepMark("waiting", "cancelled")).toBe("done");
    expect(stepMark("connected", "cancelled")).toBe("stopped");
    expect(stepMark("uploading", "cancelled")).toBe("todo");
  });
});

describe("subStepLabel", () => {
  it("names every splat stage by prefix, per-video names included", () => {
    expect(subStepLabel("1_frames", "listing")).toBe("Reading the video");
    expect(subStepLabel("2_masks_bottom", "listing")).toBe("Finding the item");
    expect(subStepLabel("3_poses_top", "listing")).toBe("Working out the angles");
    expect(subStepLabel("4_train", "listing")).toBe("Building the 3D model");
    expect(subStepLabel("5_clean_export", "listing")).toBe("Cleaning up");
  });
  it("names a check's recorded steps", () => {
    expect(subStepLabel("judge", "verify")).toBe("Comparing views");
    expect(subStepLabel("claims", "verify")).toBe("Checking the listing's claims");
    expect(subStepLabel("advise", "verify")).toBe("Writing advice");
  });
  it("returns null for a stage it does not know", () => {
    expect(subStepLabel("0_unknown", "listing")).toBeNull();
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
