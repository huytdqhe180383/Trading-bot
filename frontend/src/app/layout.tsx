import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "BTC/ETH Analyst",
  description: "TradingView-style analyst-only crypto dashboard",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
