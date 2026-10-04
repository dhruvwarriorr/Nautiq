import type { Metadata } from "next";
import "./globals.css";
import ProductNav from "./components/ProductNav";
import SiteFooter from "./components/SiteFooter";
export const metadata: Metadata = {
  title: "Nautiq · Ocean evidence",
  description:
    "Explore original observations, native forecasts and private timed trip evidence with source and scientific limitations.",
};
export default function Layout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
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
