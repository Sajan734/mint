import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/listing/x",
  useSearchParams: () => new URLSearchParams(),
  notFound: () => {
    throw new Error("notFound");
  },
}));

import ListingPage from "@/app/listing/[id]/page";
import ContactSeller from "@/components/ContactSeller";
import LocalListing from "@/components/LocalListing";
import { LOCAL_KEY, type LocalListing as Entry } from "@/lib/local-listings";
import { garageSales, listings, sellers } from "@/lib/data/mock";

// jsdom has no modal <dialog>: open/close by attribute, and fire "close" like the browser does.
beforeAll(() => {
  HTMLDialogElement.prototype.showModal = function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function (this: HTMLDialogElement) {
    this.removeAttribute("open");
    this.dispatchEvent(new Event("close"));
  };
});
afterEach(() => {
  cleanup();
  localStorage.clear();
});

const raj = sellers.find((s) => s.id === "sel_raj")!;
const pots = listings.find((m) => m.listing.item_id === "pots_i1")!;
const published: Entry = {
  id: "loc-1",
  state: "published",
  source: "mock",
  suggested_price_cad: pots.listing.price_cad,
  market: { ...pots, seller_id: "sel_raj", garage_sale_id: "gs_agincourt_tech" },
  created_at: "2026-10-17T10:00:00Z",
  updated_at: "2026-10-17T10:00:00Z",
  published_at: "2026-10-17T10:00:00Z",
};

describe("ContactSeller", () => {
  it("opens the demo contact details and gives focus back on close", async () => {
    const user = userEvent.setup();
    render(<ContactSeller seller={raj} itemTitle="Clay pots" />);
    const open = screen.getByRole("button", { name: "Contact seller" });
    await user.click(open);
    const dlg = screen.getByRole("dialog", { name: `Contact ${raj.name}` });
    expect(dlg).toHaveAttribute("open");
    expect(within(dlg).getByText("Demo contact details")).toBeInTheDocument();
    expect(within(dlg).getByRole("link", { name: raj.email })).toHaveAttribute(
      "href",
      `mailto:${raj.email}?subject=${encodeURIComponent("About: Clay pots")}`,
    );
    expect(within(dlg).getByRole("link", { name: raj.phone })).toHaveAttribute("href", "tel:4165550106");
    await user.click(within(dlg).getByRole("button", { name: "Close" }));
    expect(dlg).not.toHaveAttribute("open");
    expect(open).toHaveFocus();
  });

  it("says so when the seller has no contact details", async () => {
    render(<ContactSeller seller={{ ...raj, email: undefined, phone: undefined }} itemTitle="x" />);
    await userEvent.click(screen.getByRole("button", { name: "Contact seller" }));
    expect(screen.getByText("This seller has no contact details yet.")).toBeInTheDocument();
  });
});

describe("Listing page, local listings", () => {
  it("an id the catalog does not know renders the local fallback, not a 404", async () => {
    render(await ListingPage({ params: Promise.resolve({ id: "nope" }) }));
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("This listing was published on another device.");
    expect(screen.getByRole("link", { name: "Back to Mint" })).toHaveAttribute("href", "/");
  });

  it("renders a listing published in this browser with the full layout", () => {
    localStorage.setItem(LOCAL_KEY, JSON.stringify([published]));
    render(<LocalListing id="loc-1" sellers={sellers} sales={garageSales} />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(pots.listing.title);
    expect(screen.getByText("Published on this device")).toBeInTheDocument();
    expect(screen.getByText("Mint fair value $30")).toBeInTheDocument(); // PriceBadge size lg
    expect(screen.getByText("Why this price?")).toBeInTheDocument();
    expect(screen.getByText("Got the item? Scan it to compare with the seller's scan.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Scan" })).toHaveAttribute("href", "/listing/loc-1/check");
    expect(screen.getByRole("button", { name: "Contact seller" })).toBeInTheDocument();
    expect(screen.queryByText(/Message \(demo\)/)).toBeNull();
    expect(screen.getAllByRole("button", { name: /^Reserve for/ }).length).toBeGreaterThan(0);
    expect(screen.getByRole("slider", { name: `360 degree view of ${pots.listing.title}` })).toBeInTheDocument();
  });

  it("a draft says it is only on this device", () => {
    localStorage.setItem(LOCAL_KEY, JSON.stringify([{ ...published, state: "draft", published_at: undefined }]));
    render(<LocalListing id="loc-1" sellers={sellers} sales={garageSales} />);
    expect(screen.getByText("Draft, only on this device")).toBeInTheDocument();
  });
});
