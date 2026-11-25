"use client";
import Link from "next/link";
import { useIsUserView } from "../lib/adminView";
import UserRisk from "../components/user/UserRisk";

export default function RiskPage() {
  const userView = useIsUserView();
  if (!userView) {
    return <p className="p-4 text-sm text-bunker-muted">Risk Merkezi basit arayüzde görünür. Yönetici olarak pozisyon ayarlarına <Link href="/binance-tr" className="text-white underline">Binance TR sayfasından</Link> ulaşabilirsiniz.</p>;
  }
  return <UserRisk />;
}
