import { describe, expect, it } from "vitest";
import { GET } from "../app/scan/new/route";

const UUID = "[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}";
const get = (path = "/sell/scan/new") => GET(new Request(`http://localhost:3001${path}`));

describe("GET /scan/new", () => {
  it("redirects with a relative Location that keeps the /sell base path", () => {
    const res = get();
    expect(res.status).toBe(303);
    expect(res.headers.get("location")).toMatch(new RegExp(`^/sell/scan/${UUID}$`));
  });
  it("keeps the query string, so ?mock=1 survives the redirect", () => {
    expect(get("/sell/scan/new?mock=1").headers.get("location")).toMatch(new RegExp(`^/sell/scan/${UUID}\\?mock=1$`));
    expect(get("/sell/scan/new?mock=0&x=a%20b").headers.get("location")).toMatch(new RegExp(`\\?mock=0&x=a%20b$`));
  });
  it("makes a new scan id every time", () => {
    expect(get().headers.get("location")).not.toBe(get().headers.get("location"));
  });
});
