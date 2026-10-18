// Twin: seller/tests/twins.test.ts (keep identical)
// Files shared by the buyer and seller apps must stay identical after line 1 (line 1 names the twin).
// docs/web-handoff/HANDOFF.md section 5. Change both copies in the same commit.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const TWINS = [
  "lib/local-listings.ts",
  "lib/mock-mode.ts",
  "lib/compare-types.ts",
  "lib/listing-doc.ts",
  "lib/scan-feed.ts",
  "lib/progress.ts",
  "lib/splat-scene.ts",
  "lib/viewer-slots.ts",
  "components/ScanFlow.tsx",
  "components/PhoneRing.tsx",
  "components/SplatViewer.tsx",
  "components/MediaPanel.tsx",
  "tests/twins.test.ts",
];

const root = resolve(__dirname, "..", "..");
const body = (app: string, file: string) =>
  readFileSync(resolve(root, app, file), "utf8").replace(/\r\n/g, "\n").split("\n").slice(1).join("\n");

describe("twin files", () => {
  it.each(TWINS)("%s is identical in buyer/ and seller/ after line 1", (file) => {
    expect(body("seller", file)).toBe(body("buyer", file));
  });
});
