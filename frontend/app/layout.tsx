import type { Metadata } from "next";
import "./globals.css";
import Sidebar from "./components/Sidebar";
import TopBar from "./components/TopBar";
import AuthGate from "./components/AuthGate";

export const metadata: Metadata = {
  title: "Scalper Agent V4 — Paper Trading",
  description: "Binance TR public-data paper scalping terminal",
  manifest: "/manifest.webmanifest",
  icons: { icon: "/icon.svg", apple: "/icon.svg" },
  // Next's appleWebApp metadata emits the deprecated apple-mobile-web-app-capable tag.
};

export const viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#05080d"
};

export default function RootLayout({
  children
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="tr" className="dark">
      <head><meta name="mobile-web-app-capable" content="yes" /></head>
      <body>
        <AuthGate>
        <div className="flex min-h-screen">
          <Sidebar />
          <main className="flex-1 min-w-0 min-h-screen overflow-y-auto"><TopBar /><div className="content-shell">{children}</div></main>
        </div>
        </AuthGate>
      </body>
    </html>
  );
}
