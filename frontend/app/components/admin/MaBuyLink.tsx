"use client";

import Link from "next/link";
import { useAuth } from "../../lib/auth";

/**
 * "MA BUY sinyal kaydı" sayfasına giden düğme. Yalnız admin rolünde çizilir (başka rolde null);
 * sayfa ayrıca RequireAdmin + backend 401/403 ile korunur. Menüye KONMAZ — yalnız Ayarlar'da görünür.
 */
export default function MaBuyLink({ className = "ui-button ui-button-secondary" }: { className?: string }) {
  const { role } = useAuth();
  if (role !== "admin") return null;
  return (
    <Link href="/ma-buy-signals" className={className} data-testid="ma-buy-signals-link">
      MA BUY sinyal kaydı →
    </Link>
  );
}
