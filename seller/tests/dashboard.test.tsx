import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ListingRow, { buildRows, countByStatus, type DashRow } from "../components/ListingRow";
import type { LocalListing } from "../lib/local-listings";
import { LOCAL_KEY } from "../lib/local-listings";
import { MOCK_KEY } from "../lib/mock-mode";
import type { MarketListing } from "../lib/types";
import mine from "../mock/my-listings.json";
import sellers from "../../buyer/mock/sellers.json";

afterEach(cleanup);

vi.mock("next/link", () => ({
  default: ({ href, children, ...p }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...p}>
      {children}
    </a>
  ),
}));

const mock = mine as unknown as MarketListing[];
const local = (id: string, state: LocalListing["state"], over: Partial<MarketListing["listing"]> = {}): LocalListing => ({
  id,
  state,
  source: "mock",
  suggested_price_cad: 30,
  market: { ...mock[1], listing: { ...mock[1].listing, item_id: id, ...over } },
  created_at: "2026-10-17T10:00:00Z",
  updated_at: "2026-10-17T11:00:00Z",
  published_at: state === "published" ? "2026-10-17T11:00:00Z" : undefined,
});

describe("buildRows", () => {
  it("puts this device first and drops demo rows with the same id", () => {
    const newer = { ...local("abc", "draft"), updated_at: "2026-10-17T12:00:00Z" };
    const rows = buildRows([local("itm_0027", "published", { title: "Edited cookbook" }), newer], mock);
    expect(rows.map((r) => r.id)).toEqual(["abc", "itm_0027", "itm_0030", "itm_0029", "itm_0028", "itm_0026"]);
    const edited = rows.find((r) => r.id === "itm_0027")!;
    expect(edited).toMatchObject({ source: "local", title: "Edited cookbook", status: "available" });
    expect(rows.filter((r) => r.id === "itm_0027")).toHaveLength(1);
  });
  it("drafts are drafts, everything else uses the market status", () => {
    const rows = buildRows([local("d", "draft")], mock);
    expect(rows[0]).toMatchObject({ status: "draft", date: "2026-10-17T11:00:00Z" });
    expect(rows.find((r) => r.id === "itm_0026")).toMatchObject({ status: "sold", source: "mock", date: "2026-10-09T16:15:00Z" });
  });
});

describe("countByStatus", () => {
  it("counts the demo data: 2 listed, 1 reserved, 2 sold, no drafts", () => {
    expect(countByStatus(buildRows([], mock))).toEqual({ draft: 0, available: 2, reserved: 1, sold: 2 });
  });
  it("adds drafts and published entries from this device", () => {
    expect(countByStatus(buildRows([local("a", "draft"), local("b", "published")], mock))).toEqual({
      draft: 1, available: 3, reserved: 1, sold: 2,
    });
  });
});

describe("ListingRow", () => {
  const row = (over: Partial<DashRow>): DashRow => ({
    id: "itm_0026", title: "Paperback mystery bundle", price: 15, reference: 16, thumb: null, status: "sold",
    date: "2026-10-09T16:15:00Z", source: "mock", ...over,
  });
  it("sold rows say what they sold for, and only offer View in the buyer zone", () => {
    render(<ListingRow row={row({})} />);
    expect(screen.getByText(/^Sold for \$15 · Listed/)).toBeInTheDocument();
    expect(screen.getByText("Demo data")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /View/ })).toHaveAttribute("href", "/listing/itm_0026");
    expect(screen.queryByRole("link", { name: /Edit/ })).toBeNull();
  });
  it("reserved and listed rows never invent buyers", () => {
    const { unmount } = render(<ListingRow row={row({ status: "reserved" })} />);
    expect(screen.getByText("Reserved")).toBeInTheDocument(); // the pill, once
    expect(screen.queryByText(/offers|Sold for/)).toBeNull();
    unmount();
    render(<ListingRow row={row({ status: "available" })} />);
    expect(screen.getByText(/^No offers yet/)).toBeInTheDocument();
  });
  it("drafts on this device get Finish listing; published ones get Edit and View", () => {
    const { unmount } = render(<ListingRow row={row({ id: "x", status: "draft", source: "local" })} />);
    expect(screen.getByRole("link", { name: /Finish listing/ })).toHaveAttribute("href", "/listing/x");
    expect(screen.getByText("On this device")).toBeInTheDocument();
    unmount();
    render(<ListingRow row={row({ id: "y", status: "available", source: "local" })} />);
    expect(screen.getByRole("link", { name: /Edit/ })).toHaveAttribute("href", "/listing/y");
    expect(screen.getByRole("link", { name: /View/ })).toHaveAttribute("href", "/listing/y");
  });
});

describe("dashboard page", () => {
  beforeEach(() => localStorage.clear());
  it("shows the empty state with demo data off and nothing on this device", async () => {
    const { default: Page } = await import("../app/page");
    render(<Page />);
    expect(screen.getByText("Nothing listed yet. Scan something to sell it.")).toBeInTheDocument();
  });
  it("shows demo rows, count chips without zeros, and the real scans in demo mode", async () => {
    localStorage.setItem(MOCK_KEY, "1");
    localStorage.setItem(LOCAL_KEY, JSON.stringify([local("d1", "draft")]));
    const { default: Page } = await import("../app/page");
    render(<Page />);
    expect(screen.getByText("Raj S. · Agincourt")).toBeInTheDocument();
    expect(screen.getByText("1 Draft")).toBeInTheDocument();
    expect(screen.getByText("2 Listed")).toBeInTheDocument();
    expect(screen.getByText("2 Sold")).toBeInTheDocument();
    expect(screen.getAllByText("Waiting for the listing agent")).toHaveLength(5);
  });
});

it("the demo seller name matches buyer/mock/sellers.json", () => {
  const raj = sellers.find((s) => s.id === "sel_raj")!;
  expect(`${raj.name} · ${raj.neighbourhood}`).toBe("Raj S. · Agincourt");
});
