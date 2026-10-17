import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

afterEach(cleanup);
import ListingCard from "@/components/ListingCard";
import ListingGrid from "@/components/ListingGrid";
import PriceBadge from "@/components/PriceBadge";
import ConditionPill from "@/components/ConditionPill";
import VerifiedBadge from "@/components/VerifiedBadge";
import SellerCard from "@/components/SellerCard";
import GarageSaleHeader from "@/components/GarageSaleHeader";
import GarageSaleRail from "@/components/GarageSaleRail";
import type { GarageSale, MarketListing, Seller } from "@/lib/types";

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
  it("ListingCard links and shows badge, pill, save slot", () => {
    render(<ListingCard item={item} seller={seller} sale={sale} saveSlot={<button>Save</button>} />);
    expect(screen.getByRole("link", { name: "Clay pot" })).toHaveAttribute("href", "/listing/i1");
    expect(screen.getByText("Great price")).toBeInTheDocument();
    expect(screen.getByText("Light wear")).toBeInTheDocument();
    expect(screen.getByText("Seller checking")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Reserve" })).toBeInTheDocument();
  });
  it("ListingCard hides Reserve and shows ribbon when sold", () => {
    render(<ListingCard item={{ ...item, status: "sold" }} seller={seller} sale={sale} />);
    expect(screen.queryByRole("link", { name: "Reserve" })).toBeNull();
    expect(screen.getByText("Sold")).toBeInTheDocument();
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
