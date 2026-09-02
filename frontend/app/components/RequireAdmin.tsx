"use client";

import { ReactNode } from "react";
import { useAuth } from "../lib/auth";
import Link from "next/link";

/** Admin-only sayfa koruması: rol admin değilse yetkisiz ekranı gösterir. */
export default function RequireAdmin({ children }: { children: ReactNode }) {
  const { role } = useAuth();
  if (role === "admin") return <>{children}</>;
  return (
    <main className="page-shell">
      <div className="card mt-10 flex flex-col items-center gap-4 border-neon-red/30 bg-neon-red/5 px-6 py-12 text-center">
        <p className="eyebrow">YETKİSİZ ERİŞİM</p>
        <h1 className="font-mono text-xl font-bold text-white">Bu sayfa yalnız sistem yöneticisine açıktır</h1>
        <p className="max-w-md text-sm text-bunker-muted">
          Ayarlar, Raporlar ve Kullanıcı Yönetimi sayfalarına yalnız admin rolündeki kullanıcılar erişebilir.
        </p>
        <Link href="/" className="ui-button ui-button-primary">ANA SAYFAYA DÖN</Link>
      </div>
    </main>
  );
}
