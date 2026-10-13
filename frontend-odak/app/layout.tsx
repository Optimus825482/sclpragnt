import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import AuthGate from "./components/AuthGate";
import TopNav from "./components/TopNav";

const inter = Inter({ subsets: ["latin"], weight: ["400", "500", "600", "700"], variable: "--font-sans", display: "swap" });
const jetbrains = JetBrains_Mono({ subsets: ["latin"], weight: ["400", "500", "600"], variable: "--font-mono", display: "swap" });

export const metadata: Metadata = {
  title: "Scalper Intelligent Trade Systems",
  description: "Scalper Intelligent Trade Systems — PANEL",
  icons: { icon: "/icon.svg" },
};

export const viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#0066ff",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="tr" suppressHydrationWarning>
      <body className={`${inter.variable} ${jetbrains.variable} font-sans`}>
        <AuthGate>
          <TopNav />
          <main className="mx-auto max-w-[1500px] px-4 py-6 sm:px-6">{children}</main>
        </AuthGate>
      </body>
    </html>
  );
}
