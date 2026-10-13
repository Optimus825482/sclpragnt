import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import AuthGate from "./components/AuthGate";
import TopNav from "./components/TopNav";
import SideNav from "./components/SideNav";

const inter = Inter({ subsets: ["latin"], weight: ["400", "500", "600", "700"], variable: "--font-sans", display: "swap" });
const jetbrains = JetBrains_Mono({ subsets: ["latin"], weight: ["400", "500", "600"], variable: "--font-mono", display: "swap" });

export const metadata: Metadata = {
  title: "Scalper Intelligent Trade Systems",
  description: "Scalper Intelligent Trade Systems — PANEL",
  icons: { icon: `${process.env.NEXT_BASE_PATH || ""}/icon.svg` },
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
          <div className="mx-auto flex max-w-[1800px] items-start">
            <SideNav />
            <main className="min-w-0 flex-1 px-4 py-6 sm:px-6">{children}</main>
          </div>
        </AuthGate>
      </body>
    </html>
  );
}
