import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ListingEditor, { applyEdits, seedEntry, validateFields } from "../components/ListingEditor";
import { getLocal, LOCAL_KEY } from "../lib/local-listings";
import { MOCK_KEY } from "../lib/mock-mode";
import type { ListingDoc, MarketListing } from "../lib/types";
import scanResult from "../mock/scan-result.json";

afterEach(cleanup);

// The 3D panel is T3's and needs WebGL; the editor only cares that it is there.
vi.mock("../components/MediaPanel", () => ({
  MediaProvider: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  MediaViewer: () => <div data-testid="viewer" />,
  MediaTiles: () => <div data-testid="tiles" />,
}));
vi.mock("next/link", () => ({
  default: ({ href, children, ...p }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...p}>
      {children}
    </a>
  ),
}));

const ID = "0b9c6a2e-5f1d-4c3b-9a8e-7d6c5b4a3f21";
const pots = scanResult as unknown as MarketListing;

describe("validateFields", () => {
  const ok = { title: "Pots", description: "Twenty plants.", price: "30" };
  it("accepts a normal listing", () => {
    expect(validateFields(ok)).toEqual({});
  });
  it.each([
    [{ title: "  " }, "title"],
    [{ title: "x".repeat(121) }, "title"],
    [{ description: " \n " }, "description"],
    [{ price: "" }, "price"],
    [{ price: "0" }, "price"],
    [{ price: "12.5" }, "price"],
    [{ price: "-3" }, "price"],
    [{ price: "1e3" }, "price"],
  ])("rejects %o", (bad, field) => {
    expect(Object.keys(validateFields({ ...ok, ...bad }))).toEqual([field]);
  });
  it("allows exactly 120 characters and a price of 1", () => {
    expect(validateFields({ ...ok, title: "x".repeat(120), price: "1" })).toEqual({});
  });
});

describe("seedEntry and applyEdits", () => {
  it("demo seed: the wrapper becomes Raj's, the agent's text and prices stay", () => {
    const e = seedEntry(ID, pots, "mock");
    expect(e.market.listing.item_id).toBe(ID);
    expect(e.market).toMatchObject({ seller_id: "sel_raj", garage_sale_id: "gs_agincourt_tech", status: "available" });
    expect(e.market.location).toEqual({ neighbourhood: "Agincourt", city: "Toronto" });
    expect(e.market.listing.title).toBe(pots.listing.title);
    expect(e.suggested_price_cad).toBe(30);
    expect(e.market.reference_price_cad).toBe(30);
    expect(e.state).toBe("draft");
  });
  it("publish writes the edits and never touches the reference price", () => {
    const seed = seedEntry(ID, pots, "mock");
    const out = applyEdits(seed, { title: " My pots ", description: "Plants.", price: "45" }, "published", "2026-10-17T15:00:00Z");
    expect(out.state).toBe("published");
    expect(out.published_at).toBe("2026-10-17T15:00:00Z");
    expect(out.market.listing).toMatchObject({ title: "My pots", description: "Plants.", price_cad: 45 });
    expect(out.market.reference_price_cad).toBe(30);
    expect(out.suggested_price_cad).toBe(30);
    expect(out.market.status).toBe("available");
    expect(seed.market.listing.title).toBe(pots.listing.title); // no mutation
  });
});

describe("ListingEditor", () => {
  beforeEach(() => localStorage.clear());

  it("demo mode: prefills from the recorded result and saves it as a draft", () => {
    localStorage.setItem(MOCK_KEY, "1");
    render(<ListingEditor id={ID} doc={null} />);
    expect(screen.getByLabelText("Name")).toHaveValue(pots.listing.title);
    expect(screen.getByLabelText("Your price")).toHaveValue("30");
    expect(screen.getByText("Suggested price $30")).toBeInTheDocument();
    expect(getLocal(ID)?.state).toBe("draft");
  });

  it("shows the message under the field and focuses it", () => {
    localStorage.setItem(MOCK_KEY, "1");
    render(<ListingEditor id={ID} doc={null} />);
    const price = screen.getByLabelText("Your price");
    fireEvent.change(price, { target: { value: "2.5" } });
    fireEvent.click(screen.getByRole("button", { name: "Publish" }));
    expect(screen.getByText("Enter a whole dollar amount, 1 or more.")).toBeInTheDocument();
    expect(price).toHaveFocus();
    expect(price).toHaveAttribute("aria-invalid", "true");
    expect(getLocal(ID)?.state).toBe("draft");
  });

  it("publish writes the store, keeps the reference price, and shows the success panel", () => {
    localStorage.setItem(MOCK_KEY, "1");
    render(<ListingEditor id={ID} doc={null} />);
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Twenty houseplants" } });
    fireEvent.change(screen.getByLabelText("Your price"), { target: { value: "40" } });
    fireEvent.click(screen.getByRole("button", { name: "Publish" }));
    const saved = JSON.parse(localStorage.getItem(LOCAL_KEY)!)[0];
    expect(saved.state).toBe("published");
    expect(saved.market.listing.title).toBe("Twenty houseplants");
    expect(saved.market.listing.price_cad).toBe(40);
    expect(saved.market.reference_price_cad).toBe(30);
    expect(saved.market.seller_id).toBe("sel_raj");
    expect(screen.getByText("Published on this device.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View listing" })).toHaveAttribute("href", `/listing/${ID}`);
    expect(screen.getByRole("link", { name: "Back to your listings" })).toHaveAttribute("href", "/");
  });

  it("save draft says Saved", () => {
    localStorage.setItem(MOCK_KEY, "1");
    render(<ListingEditor id={ID} doc={null} />);
    fireEvent.change(screen.getByLabelText("Description"), { target: { value: "Plants on a shelf." } });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    expect(screen.getByRole("status")).toHaveTextContent("Saved");
    expect(getLocal(ID)?.market.listing.description).toBe("Plants on a shelf.");
  });

  it("live: a listed document becomes a draft; nothing yet keeps the old copy", () => {
    const doc: ListingDoc = { v: 1, scan_id: ID, status: "listed", market_listing: pots };
    const { unmount } = render(<ListingEditor id={ID} doc={doc} />);
    expect(getLocal(ID)?.source).toBe("live");
    unmount();
    localStorage.clear();
    render(<ListingEditor id={ID} doc={null} />);
    expect(screen.getByRole("heading", { name: "Still working on it" })).toBeInTheDocument();
  });

  it("live: rejected shows the pipeline's reason", () => {
    const doc: ListingDoc = { v: 1, scan_id: ID, status: "rejected", rejection: { match_check: { verdict: "no", reason: "Too blurry." } } };
    render(<ListingEditor id={ID} doc={doc} />);
    expect(screen.getByRole("heading", { name: "We couldn't list this one" })).toBeInTheDocument();
    expect(screen.getByText("Too blurry.")).toBeInTheDocument();
  });
});
