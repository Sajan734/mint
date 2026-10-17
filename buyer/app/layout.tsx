import type { Metadata } from "next";
import { Bricolage_Grotesque, Figtree } from "next/font/google";
import SiteFooter from "@/components/SiteFooter";
import SiteHeader from "@/components/SiteHeader";
import "./globals.css";

// Bricolage Grotesque for headings and the wordmark, Figtree for everything else.
const bricolage = Bricolage_Grotesque({ variable: "--font-bricolage", subsets: ["latin"], weight: ["600", "700"], display: "swap" });
const figtree = Figtree({ variable: "--font-figtree", subsets: ["latin"], weight: ["400", "500", "600", "700"], display: "swap" });

export const metadata: Metadata = {
  title: "Mint",
  description: "Second-hand finds from your neighbours, scanned in 3D and fairly priced.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${bricolage.variable} ${figtree.variable}`}>
      <body className="flex min-h-svh flex-col">
        <a href="#main" className="skip-link">
          Skip to content
        </a>
        <SiteHeader />
        <main id="main" tabIndex={-1} className="mx-auto w-full max-w-[1240px] flex-1 px-4 pb-24 pt-4 sm:px-6 md:pt-6 lg:px-10">
          {children}
        </main>
        <SiteFooter />
      </body>
    </html>
  );
}
