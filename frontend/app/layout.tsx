import type { Metadata } from "next";
import "./globals.css";
import AuthGate from "./components/AuthGate";
import AppShell from "./components/AppShell";

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
        <AppShell>{children}</AppShell>
        </AuthGate>
      </body>
    </html>
  );
}
