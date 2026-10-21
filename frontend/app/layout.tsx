import type { Metadata } from "next";
// 2026-10-21: fontlar npm paketinden (fontsource) — derleme Google Fonts'a bağlı DEĞİL. Coolify derlemesi
// next/font/google ile fonts.gstatic.com'a ulaşamayınca Turbopack "next/font/google queries have exactly one entry"
// hatasıyla düşüyordu (aralıklı ağ hatası; yerelde aynı ağaç geçiyor). Fontsource CSS'i her ağırlık için tüm alt
// kümeleri (latin, latin-ext = Türkçe, …) unicode-range ile tanımlar; tarayıcı yalnız gerekeni indirir. Aile adları
// globals.css'teki --font-* değişkenlerinde (tailwind.config.ts fontFamily bunları okur).
import "@fontsource/poppins/600.css";
import "@fontsource/poppins/700.css";
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/700.css";
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-sans/700.css";
import "@fontsource-variable/jetbrains-mono/index.css";
import "./globals.css";
import "./user-theme.generated.css";
import "./user-palette.generated.css";
import "./user-theme.manual.css";
import AuthGate from "./components/AuthGate";
import AppShell from "./components/AppShell";
import AppUpdater from "./components/AppUpdater";
import QuickBuyFromUrl from "./components/QuickBuyFromUrl";
import { Suspense } from "react";

export const BUILD_ID = process.env.NEXT_PUBLIC_BUILD_ID || "dev";

// 2026-10-17 (basit arayüz): uygulama genelinde IBM Plex Sans (Roboto beğenilmedi; Plex'in açık
// harf aralığı ve belirgin rakamları yoğun sayı tablolarında daha okunaklı; latin-ext = Türkçe).
// Ağırlıklar: Poppins 600/700 (başlık), Inter 400/500/700 (yedek), IBM Plex Sans 400–700, JetBrains Mono (değişken).

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
  themeColor: "#0f1131"
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
      <body suppressHydrationWarning>
        <AppUpdater />
        <AuthGate>
        <AppShell>{children}</AppShell>
        {/* Push "Alım yap" aksiyonu: ?buy=SEMBOL ile her sayfada alım penceresi (useSearchParams → Suspense). */}
        <Suspense fallback={null}><QuickBuyFromUrl /></Suspense>
        </AuthGate>
      </body>
    </html>
  );
}
