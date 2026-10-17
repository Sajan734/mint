import type { Metadata } from "next";
import { Figtree, Fraunces } from "next/font/google";
import SiteFooter from "@/components/SiteFooter";
import SiteHeader from "@/components/SiteHeader";
import "./globals.css";

// Two faces (docs/design/DESIGN.md §3): Fraunces at its softest for signs, Figtree for everything read or pressed.
const fraunces = Fraunces({ variable: "--font-fraunces", subsets: ["latin"], axes: ["SOFT", "WONK", "opsz"], display: "swap" });
const figtree = Figtree({ variable: "--font-figtree", subsets: ["latin"], weight: ["400", "500", "600", "700"], display: "swap" });

export const metadata: Metadata = {
  title: "Mint for sellers",
  description: "Scan an item with your phone; Mint writes the listing and suggests a fair price.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${fraunces.variable} ${figtree.variable}`}>
      <body className="flex min-h-svh flex-col">
        <a href="#main" className="skip-link">
          Skip to content
        </a>
        <SiteHeader />
        <main id="main" tabIndex={-1} className="mx-auto w-full max-w-[1240px] flex-1 px-4 pb-24 pt-6 sm:px-6 lg:px-10">
          {children}
        </main>
        <SiteFooter />
      </body>
    </html>
  );
}
