import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import SiteHeader from "@/components/SiteHeader";

describe("SiteHeader", () => {
  it("renders the main links", () => {
    render(<SiteHeader />);
    for (const name of ["Home", "Saved", "Orders", "How it works"]) {
      expect(screen.getByRole("link", { name })).toBeInTheDocument();
    }
  });
});
