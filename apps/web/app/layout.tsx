import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = { title: "Nautiuq · Local platform", description: "Local development platform dependency health" };
export default function Layout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
