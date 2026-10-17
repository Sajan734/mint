import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(cleanup);
const path = vi.hoisted(() => ({ current: "/" }));
vi.mock("next/navigation", () => ({ usePathname: () => path.current }));
vi.mock("next/link", () => ({
  default: ({ href, children, ...p }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...p}>
      {children}
    </a>
  ),
}));

describe("seller SiteHeader", () => {
  it("leaves New listing out on Your listings, which has its own", async () => {
    const { default: SiteHeader } = await import("../components/SiteHeader");
    path.current = "/";
    render(<SiteHeader />);
    expect(screen.queryByRole("link", { name: "New listing" })).toBeNull();
  });
  it("shows New listing on every other seller page", async () => {
    const { default: SiteHeader } = await import("../components/SiteHeader");
    path.current = "/listing/abc";
    render(<SiteHeader />);
    expect(screen.getByRole("link", { name: "New listing" })).toHaveAttribute("href", "/scan/new");
  });
});
