import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
}));

import Home from "@/app/page";
import JustListed, { JUST_LISTED_MAX, justListed } from "@/components/JustListed";
import { LOCAL_KEY, type LocalListing } from "@/lib/local-listings";
import { garageSales, listings, sellers } from "@/lib/data/mock";

afterEach(() => {
  cleanup();
  localStorage.clear();
});

const pots = listings.find((m) => m.listing.item_id === "pots_i1")!;
// A listing published from the seller app: the real pots listing re-wrapped for the demo seller (PLAN_UX §8).
const entry = (id: string, state: LocalListing["state"], at: string): LocalListing => ({
  id,
  state,
  source: "mock",
  suggested_price_cad: pots.listing.price_cad,
  market: {
    ...pots,
    seller_id: "sel_raj",
    garage_sale_id: "gs_agincourt_tech",
    listing: { ...pots.listing, item_id: id, title: `Pots ${id}` },
  },
  created_at: at,
  updated_at: at,
  ...(state === "published" ? { published_at: at } : {}),
});

const home = async (params: Record<string, string> = {}) => render(await Home({ searchParams: Promise.resolve(params) }));
const itemHrefs = (list: HTMLElement) =>
  within(list)
    .getAllByRole("listitem")
    .map((li) => within(li).getAllByRole("link").map((a) => a.getAttribute("href")).find((h) => /^\/listing\/[^#/]+$/.test(h ?? "")));

describe("justListed", () => {
  it("keeps published entries only, newest first, at most 8", () => {
    const all = [
      entry("a", "published", "2026-10-17T10:00:00Z"),
      entry("d", "draft", "2026-10-17T12:00:00Z"),
      entry("b", "published", "2026-10-17T11:00:00Z"),
    ];
    expect(justListed(all).map((e) => e.id)).toEqual(["b", "a"]);
    const many = Array.from({ length: 10 }, (_, i) => entry(`p${i}`, "published", `2026-10-17T1${i}:00:00Z`));
    expect(justListed(many)).toHaveLength(JUST_LISTED_MAX);
    expect(justListed(many)[0].id).toBe("p9");
  });
});

describe("JustListed", () => {
  it("renders nothing with an empty store", () => {
    const { container } = render(<JustListed sellers={sellers} sales={garageSales} />);
    expect(container).toBeEmptyDOMElement();
  });
  it("shows published listings from this browser and links to them", () => {
    localStorage.setItem(
      LOCAL_KEY,
      JSON.stringify([entry("loc1", "published", "2026-10-17T10:00:00Z"), entry("loc2", "draft", "2026-10-17T11:00:00Z")]),
    );
    render(<JustListed sellers={sellers} sales={garageSales} />);
    expect(screen.getByRole("heading", { name: "Just listed" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Pots loc1" })).toHaveAttribute("href", "/listing/loc1");
    expect(screen.queryByRole("link", { name: "Pots loc2" })).toBeNull();
  });
});

// Renders the whole page (60-odd cards): about 1 s alone, slower on a busy machine.
describe("Landing page", { timeout: 20_000 }, () => {
  it("shows the intro strip, the shelves and the full grid", async () => {
    await home();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Second-hand finds, scanned and priced fairly.");
    expect(screen.getByText("Every item is a 360° scan")).toBeInTheDocument();
    expect(screen.getByText("Fair price, checked")).toBeInTheDocument();
    for (const name of ["Recommended for you", "Great deals", "Garage sales near you", "Fresh scans"]) {
      expect(screen.getByRole("heading", { name })).toBeInTheDocument();
    }
    expect(screen.queryByRole("heading", { name: "Just listed" })).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent(`${listings.length} items`);
    expect(screen.queryByRole("search")).toBeNull(); // the header has the search
  });

  it("Great deals: great or fair prices only, nothing sold, reserved or our own", async () => {
    await home();
    const row = screen.getByRole("list", { name: "Great deals" });
    const cards = within(row).getAllByRole("listitem");
    expect(cards.length).toBeGreaterThan(0);
    expect(cards.length).toBeLessThanOrEqual(8);
    for (const li of cards) expect(within(li).getByText(/^(Great|Fair) price$/)).toBeInTheDocument();
    const byId = new Map(listings.map((m) => [m.listing.item_id, m]));
    for (const href of itemHrefs(row)) {
      const m = byId.get(href!.split("/").pop()!)!;
      expect(m.status).toBe("available");
      expect(m.seller_id).not.toBe("sel_raj");
    }
    expect(screen.getByRole("link", { name: "See all deals" })).toHaveAttribute("href", "/?fair=1&sort=best_deal#items-h");
  });

  it("Recommended: one per category, no repeats from Great deals, nothing overpriced", async () => {
    await home();
    const row = screen.getByRole("list", { name: "Recommended for you" });
    const picks = itemHrefs(row);
    const deals = itemHrefs(screen.getByRole("list", { name: "Great deals" }));
    expect(picks.length).toBeGreaterThan(0);
    expect(picks.filter((h) => deals.includes(h))).toEqual([]);
    expect(within(row).queryByText("Overpriced")).toBeNull();
    const cats = picks.map((h) => listings.find((m) => `/listing/${m.listing.item_id}` === h)!.category);
    expect(new Set(cats).size).toBe(cats.length);
  });

  it("a search shows its results without the shelves", async () => {
    await home({ q: "headphones" });
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Results for “headphones”");
    expect(screen.queryByRole("heading", { name: "Great deals" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Recommended for you" })).toBeNull();
    expect(screen.getByRole("list", { name: "Items for sale" })).toBeInTheDocument();
  });

  it("no hits keeps the empty state", async () => {
    await home({ q: "zzzz-no-such-item" });
    expect(screen.getByRole("status")).toHaveTextContent("0 items");
    expect(screen.getByText("Nothing here yet. Try a wider search.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Clear filters" })).toHaveAttribute("href", "/");
  });
});
