"use client";
import { useIsUserView } from "../lib/adminView";
import UserRisk from "../components/user/UserRisk";

export default function RiskPage() {
  const userView = useIsUserView();
  if (!userView) {
    return <p className="p-4 text-sm text-bunker-muted">Risk Merkezi basit arayüzde görünür. Yönetici arayüzünde pozisyon ayarları Binance TR sayfasındadır.</p>;
  }
  return <UserRisk />;
}
