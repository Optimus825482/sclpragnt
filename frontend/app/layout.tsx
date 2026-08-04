import type { Metadata } from "next";
import "./globals.css";
import Sidebar from "./components/Sidebar";

export const metadata: Metadata = {
  title: "Scalper Agent V4 — Paper Trading",
  description: "Binance TR public-data paper scalping terminal",
  manifest: "/manifest.webmanifest"
};

export default function RootLayout({
  children
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="tr" className="dark">
      <body>
        <div className="flex min-h-screen">
          <Sidebar />
          <main className="flex-1 p-6 lg:p-8 overflow-y-auto">{children}</main>
        </div>
      </body>
    </html>
  );
}
