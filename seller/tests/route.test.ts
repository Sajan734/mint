import { describe, expect, it } from "vitest";
import { GET } from "../app/scan/new/route";

describe("GET /scan/new", () => {
  it("redirects with a relative Location that keeps the /sell base path", () => {
    const res = GET();
    expect(res.status).toBe(303);
    expect(res.headers.get("location")).toMatch(/^\/sell\/scan\/[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  });
  it("makes a new scan id every time", () => {
    expect(GET().headers.get("location")).not.toBe(GET().headers.get("location"));
  });
});
