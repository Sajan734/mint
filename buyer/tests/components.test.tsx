import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
});

// The card's 3D viewer needs WebGL: stand in a stub that exposes its props and can fail on demand.
vi.mock("@/components/SplatViewer", () => ({
  default: (p: { src: string; label: string; onError?: (e: Error) => void }) => (
    <div data-testid="splat" data-src={p.src} aria-label={p.label}>
      <button onClick={() => p.onError?.(new Error("webglcontextlost"))}>fail</button>
    </div>
  ),
  preloadSplatScene: () => {},
}));
import ListingCard from "@/components/ListingCard";
import ListingGrid from "@/components/ListingGrid";
import PriceBadge from "@/components/PriceBadge";
import ConditionPill from "@/components/ConditionPill";
import VerifiedBadge from "@/components/VerifiedBadge";
import SellerCard from "@/components/SellerCard";
import GarageSaleHeader from "@/components/GarageSaleHeader";
import GarageSaleRail from "@/components/GarageSaleRail";
import type { GarageSale, MarketListing, Seller } from "@/lib/types";
import { sampleSplatFor } from "@/lib/mock-mode";

const seller: Seller = {
  id: "s1", name: "Priya", avatar: "", neighbourhood: "Riverside", member_since: "2025-01-01",
  rating: 4.8, rating_count: 12, response_time: "usually replies within an hour",
};
const sale: GarageSale = {
  id: "g1", seller_id: "s1", name: "Saturday Clear-Out", blurb: "", starts_at: "2026-10-17T13:00:00Z",
  ends_at: "2026-10-17T18:00:00Z", pickup_slots: [], ships: true, location: { neighbourhood: "Riverside", city: "Toronto" },
};
const item: MarketListing = {
  listing: {
    item_id: "i1", title: "Clay pot", description: "A nice pot. Has a chip.", attributes: {}, tags: [],
    condition_grade: "light_wear", condition_notes: [], price_cad: 20, price_justification: [], preview_images: [],
    viewer_url: null, needs_seller_check: true, seller_check_reasons: [],
  },
  seller_id: "s1", garage_sale_id: "g1", category: "garden_plants", location: sale.location,
  reference_price_cad: 30, frames: ["/a.png"], splat_url: null, usable_view_count: 12,
  listed_at: "2026-10-01T00:00:00Z", status: "available",
};

describe("display components", () => {
  it("ListingCard is one link with price, fair-price badge and title, nothing else", () => {
    render(<ListingCard item={item} seller={seller} sale={sale} saveSlot={<button>Save</button>} />);
    expect(screen.getByRole("link", { name: "Clay pot" })).toHaveAttribute("href", "/listing/i1");
    expect(screen.getAllByRole("link")).toHaveLength(1);
    expect(screen.getByText("$20")).toBeInTheDocument();
    expect(screen.getByText("Great price")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeInTheDocument();
    // Removed from the card (PLAN_UX 2.1, docs/design/DESIGN.md §4): description, condition pill, Reserve, seller
    // footer, and the scan-views counter.
    expect(screen.queryByText(/\d+ views/)).toBeNull();
    expect(screen.queryByText(/A nice pot/)).toBeNull();
    expect(screen.queryByText("Light wear")).toBeNull();
    expect(screen.queryByRole("link", { name: "Reserve" })).toBeNull();
    expect(screen.queryByText("Priya")).toBeNull();
    expect(screen.queryByText("3D")).toBeNull();
  });
  it("ListingCard shows the ribbon when sold and a 3D pill for splat items", () => {
    render(<ListingCard item={{ ...item, status: "sold", splat_url: "/s.spz" }} seller={seller} sale={sale} />);
    expect(screen.getByText("Sold")).toBeInTheDocument();
    expect(screen.getByText("3D")).toBeInTheDocument();
  });
  it("ListingGrid wraps children in list items", () => {
    render(<ListingGrid label="Items"><b>a</b><b>b</b></ListingGrid>);
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });
  it("PriceBadge states", () => {
    render(<PriceBadge price={50} reference={null} />);
    expect(screen.getByText("No price check")).toBeInTheDocument();
    render(<PriceBadge price={50} reference={30} size="lg" />);
    expect(screen.getByText("Overpriced")).toBeInTheDocument();
    expect(screen.getByText(/Mint fair value \$30 · 67% above fair value/)).toBeInTheDocument();
  });
  it("ConditionPill and VerifiedBadge", () => {
    render(<><ConditionPill grade="heavy_wear" /><VerifiedBadge usableViews={12} /></>);
    expect(screen.getByText("Heavy wear")).toBeInTheDocument();
    expect(screen.getByText(/Verified by Mint scan · 12 views/)).toBeInTheDocument();
  });
  it("SellerCard, header and rail link to seller and sale", () => {
    render(
      <>
        <SellerCard seller={seller} sale={sale} />
        <GarageSaleHeader sale={sale} seller={seller} total={14} available={11} />
        <GarageSaleRail tiles={[{ sale, seller, cover: "/a.png", itemCount: 14 }]} />
      </>,
    );
    expect(screen.getByRole("link", { name: "Priya" })).toHaveAttribute("href", "/seller/s1");
    expect(screen.getByRole("heading", { level: 1, name: "Saturday Clear-Out" })).toBeInTheDocument();
    expect(screen.getByText("14 items · 11 available")).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Garage sales" })).toBeInTheDocument();
  });
});

describe("ListingCard hover to 3D", () => {
  const desktop = (reduce = false) =>
    vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("pointer: fine") || (reduce && q.includes("reduce")) }));
  const card = () => screen.getByRole("article");
  const many = Array.from({ length: 8 }, (_, i) => `/f${i}.jpg`);

  it("mounts the splat after a short hover and drops it on leave", async () => {
    desktop();
    render(<ListingCard item={{ ...item, splat_url: "/s.spz" }} seller={seller} sale={sale} />);
    fireEvent.pointerEnter(card(), { pointerType: "mouse" });
    expect(screen.queryByTestId("splat")).toBeNull(); // dwell first
    expect(await screen.findByTestId("splat")).toHaveAttribute("data-src", "/s.spz");
    fireEvent.pointerLeave(card(), { pointerType: "mouse" });
    expect(screen.queryByTestId("splat")).toBeNull();
  });

  it("in demo mode a card with no splat spins a labelled sample", async () => {
    desktop();
    localStorage.setItem("mint.mock", "1");
    render(<ListingCard item={item} seller={seller} sale={sale} />);
    fireEvent.focus(screen.getByRole("link", { name: "Clay pot" })); // keyboard focus counts as hover
    expect(await screen.findByTestId("splat")).toHaveAttribute("data-src", sampleSplatFor("i1"));
    expect(screen.getByText("Sample 3D")).toBeInTheDocument();
  });

  it("live mode with no splat uses the frame spinner, and a splat error falls back to it", async () => {
    desktop();
    const { unmount } = render(<ListingCard item={{ ...item, frames: many }} seller={seller} sale={sale} />);
    fireEvent.pointerEnter(card(), { pointerType: "mouse" });
    expect(await screen.findByRole("slider", { name: "360 degree view of Clay pot" })).toBeInTheDocument();
    unmount();

    render(<ListingCard item={{ ...item, frames: many, splat_url: "/s.spz" }} seller={seller} sale={sale} />);
    fireEvent.pointerEnter(card(), { pointerType: "mouse" });
    fireEvent.click(await screen.findByRole("button", { name: "fail" }));
    expect(screen.queryByTestId("splat")).toBeNull();
    expect(screen.getByRole("slider", { name: "360 degree view of Clay pot" })).toBeInTheDocument();
  });

  it("stays a still photo on touch and under reduced motion", async () => {
    vi.stubGlobal("matchMedia", () => ({ matches: false })); // coarse pointer
    const { unmount } = render(<ListingCard item={{ ...item, splat_url: "/s.spz" }} seller={seller} sale={sale} />);
    fireEvent.pointerEnter(card(), { pointerType: "touch" });
    fireEvent.focus(screen.getByRole("link", { name: "Clay pot" }));
    await new Promise((r) => setTimeout(r, 300));
    expect(screen.queryByTestId("splat")).toBeNull();
    unmount();
    desktop(true);
    render(<ListingCard item={{ ...item, splat_url: "/s.spz" }} seller={seller} sale={sale} />);
    fireEvent.pointerEnter(card(), { pointerType: "mouse" });
    await new Promise((r) => setTimeout(r, 300));
    expect(screen.queryByTestId("splat")).toBeNull();
  });
});
