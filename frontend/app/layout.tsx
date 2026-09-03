import type { Metadata } from "next";
import { Poppins, Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import AuthGate from "./components/AuthGate";
import AppShell from "./components/AppShell";

export const BUILD_ID = process.env.NEXT_PUBLIC_BUILD_ID || "dev";

// Google Fonts'u next/font ile yükle: render-blocking @import yerine
// self-hosted, optimize edilmiş font (CLS + FCP iyileşir).
const poppins = Poppins({ subsets: ["latin"], weight: ["600", "700"], variable: "--font-display", display: "swap" });
const inter = Inter({ subsets: ["latin"], weight: ["400", "500", "700"], variable: "--font-sans", display: "swap" });
const jetbrains = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono", display: "swap" });

export const metadata: Metadata = {
  title: "Scalper Agent V4 — Paper Trading",
  description: "Binance TR public-data paper scalping terminal",
  manifest: "/manifest.webmanifest",
  icons: {
    icon: "/icon.svg",
    // iOS home-screen: apple-touch-icon PNG (180/152/120), SVG yalnız tarayıcı sekmesi.
    apple: [
      { url: "/icons/iOS/Icon-180.png", sizes: "180x180", type: "image/png" },
      { url: "/icons/iOS/Icon-152.png", sizes: "152x152", type: "image/png" },
      { url: "/icons/iOS/Icon-120.png", sizes: "120x120", type: "image/png" }
    ]
  },
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
    // suppressHydrationWarning: browser extensions inject attributes onto <html>
    // before hydration (e.g. rtrvr-*); ignore mismatches on this element only.
    <html lang="tr" className="dark" suppressHydrationWarning data-build-id={BUILD_ID}>
      <head><meta name="mobile-web-app-capable" content="yes" /><meta name="build-id" content={BUILD_ID} /></head>
      {/* Extension noise lands on <body> too; same suppression, children unaffected. */}
      <body suppressHydrationWarning className={`${poppins.variable} ${inter.variable} ${jetbrains.variable}`}>
        <AuthGate>
        <AppShell>{children}</AppShell>
        </AuthGate>
      </body>
    </html>
  );
}
