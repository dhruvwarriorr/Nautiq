import type { Metadata, Viewport } from "next";
import { Big_Shoulders, Overpass, Overpass_Mono } from "next/font/google";
import "./globals.css";
import ProductNav from "./components/ProductNav";
import SiteFooter from "./components/SiteFooter";

const shoulders = Big_Shoulders({ subsets: ["latin"], variable: "--font-shoulders", display: "swap", axes: ["opsz"] });
const overpass = Overpass({ subsets: ["latin"], variable: "--font-overpass", display: "swap" });
const overpassMono = Overpass_Mono({ subsets: ["latin"], variable: "--font-overpass-mono", display: "swap" });

export const metadata: Metadata = {
  title: "Nautiq · What is the sea doing?",
  description:
    "Plain answers about the sea near India's coast: waves, wind, currents and sea temperature, with honest limits.",
};
export const viewport: Viewport = { themeColor: "#0a2747" };

export default function Layout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${shoulders.variable} ${overpass.variable} ${overpassMono.variable}`}>
      <body>
        <a className="skip-link" href="#content">
          Skip to content
        </a>
        <ProductNav />
        <div id="content" tabIndex={-1}>
          {children}
        </div>
        <SiteFooter />
      </body>
    </html>
  );
}
