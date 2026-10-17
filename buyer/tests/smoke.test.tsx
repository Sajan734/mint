import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import SiteHeader from "@/components/SiteHeader";

describe("SiteHeader", () => {
  it("renders the logo (Home), the main links and Sell an item", () => {
    render(<SiteHeader />);
    expect(screen.getByRole("link", { name: "Home" })).toHaveAttribute("href", "/");
    for (const name of ["Saved", "Orders", "How it works"]) {
      expect(screen.getByRole("link", { name })).toBeInTheDocument();
    }
    // The seller zone: a plain <a href="/sell">, never next/link.
    expect(screen.getByRole("link", { name: "Sell an item" })).toHaveAttribute("href", "/sell");
    expect(screen.getByRole("searchbox", { name: "Search items" })).toBeInTheDocument();
  });
});
