"use client";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import BuyDialog from "./user/home/BuyDialog";
import type { TradePlan } from "./user/home/tradePlan";
import { API_BASE, apiRequest } from "../lib/api";

/** Plan çekimi bu süreyi aşarsa pencere plansız açılır. */
export const PLAN_FETCH_TIMEOUT_MS = 5000;

/**
 * Push bildirimindeki "Alım yap" aksiyonu (sw.template.js) `?buy=SEMBOL&buy_price=FIYAT[&key=PLAN_ANAHTARI]` ile gelir.
 * Hangi sayfaya düşerse düşsün alım penceresini açar; kapanınca yalnız bu parametreler URL'den silinir.
 * `key` varsa dondurulmuş işlem planı çekilir; 404/hata/zaman aşımında pencere plansız (eski davranış) açılır.
 */
export default function QuickBuyFromUrl() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const symbol = params.get("buy");
  const price = Number(params.get("buy_price"));
  const key = params.get("key");
  // Plan çekimi bitene (başarı ya da hata) kadar pencere AÇILMAZ; böylece plan sonradan gelip alanları ezmez.
  const [loaded, setLoaded] = useState<{ key: string | null; plan: TradePlan | null } | null>(null);

  useEffect(() => {
    if (!symbol) return;
    if (!key) { setLoaded({ key: null, plan: null }); return; }
    let cancelled = false;
    setLoaded(null);
    (async () => {
      let plan: TradePlan | null = null;
      const ctl = new AbortController();
      const timer = setTimeout(() => ctl.abort(), PLAN_FETCH_TIMEOUT_MS);
      try {
        const res = await apiRequest(`${API_BASE}/api/monitoring/trade-plan?key=${encodeURIComponent(key)}`, { cache: "no-store", signal: ctl.signal });
        if (res.ok) {
          const data = await res.json();
          plan = data?.plan && typeof data.plan === "object" ? (data.plan as TradePlan) : null;
        }
      } catch { /* ağ/zaman aşımı/ayrıştırma hatası: plansız aç */ } finally { clearTimeout(timer); }
      if (!cancelled) setLoaded({ key, plan });
    })();
    return () => { cancelled = true; };
  }, [symbol, key]);

  const close = useCallback(() => {
    const next = new URLSearchParams(params.toString());
    next.delete("buy");
    next.delete("buy_price");
    next.delete("key");
    const q = next.toString();
    router.replace(q ? `${pathname}?${q}` : pathname, { scroll: false });
  }, [params, pathname, router]);

  if (!symbol || !loaded || loaded.key !== (key || null)) return null;
  return (
    <BuyDialog
      open
      symbol={symbol}
      referencePrice={Number.isFinite(price) && price > 0 ? price : null}
      tradePlan={loaded.plan}
      planKey={loaded.plan ? key : null}
      onClose={close}
    />
  );
}
