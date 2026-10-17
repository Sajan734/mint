import type { Metadata } from "next";
import { Bricolage_Grotesque, DM_Mono, Figtree } from "next/font/google";
import SiteHeader from "@/components/SiteHeader";
import "./globals.css";

const bricolage = Bricolage_Grotesque({ variable: "--font-bricolage", subsets: ["latin"], weight: ["600", "700"], display: "swap" });
const figtree = Figtree({ variable: "--font-figtree", subsets: ["latin"], weight: ["400", "500", "600"], display: "swap" });
const dmMono = DM_Mono({ variable: "--font-dm-mono", subsets: ["latin"], weight: ["500"], display: "swap" });

export const metadata: Metadata = {
  title: "Mint for sellers",
  description: "Scan an item with your phone; Mint writes the listing and suggests a fair price.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${bricolage.variable} ${figtree.variable} ${dmMono.variable}`}>
      <body className="flex min-h-screen flex-col">
        <SiteHeader />
        <main className="mx-auto w-full max-w-[1200px] flex-1 px-4 pb-16 pt-6 md:px-6 lg:px-8">{children}</main>
      </body>
    </html>
  );
}
