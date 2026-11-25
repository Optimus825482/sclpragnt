"use client";
import dynamic from "next/dynamic";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import type { TradePlan } from "./user/home/tradePlan";
import { API_BASE, apiRequest } from "../lib/api";
import { createRequestDeadline } from "../lib/fetchTimeout";

const BuyDialog = dynamic(() => import("./user/home/BuyDialog"));

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
  const [loaded, setLoaded] = useState<{ symbol: string; key: string; plan: TradePlan | null } | null>(null);

  useEffect(() => {
    if (!symbol || !key) return;
    const request = new AbortController();
    const deadline = createRequestDeadline(PLAN_FETCH_TIMEOUT_MS, request.signal);
    setLoaded(null);
    (async () => {
      let plan: TradePlan | null = null;
      try {
        const res = await apiRequest(`${API_BASE}/api/monitoring/trade-plan?key=${encodeURIComponent(key)}`, {
          signal: deadline.signal, timeoutMs: 0,
        });
        if (res.ok) {
          const data = await res.json();
          plan = data?.plan && typeof data.plan === "object" ? (data.plan as TradePlan) : null;
        }
      } catch { /* ağ/zaman aşımı/ayrıştırma hatası: plansız aç */ } finally { deadline.dispose?.(); }
      if (!request.signal.aborted) setLoaded({ symbol, key, plan });
    })();
    return () => {
      request.abort();
      deadline.dispose?.();
    };
  }, [symbol, key]);

  const close = useCallback(() => {
    const next = new URLSearchParams(params.toString());
    next.delete("buy");
    next.delete("buy_price");
    next.delete("key");
    const q = next.toString();
    router.replace(q ? `${pathname}?${q}` : pathname, { scroll: false });
  }, [params, pathname, router]);

  if (!symbol || (key && (loaded?.key !== key || loaded.symbol !== symbol))) return null;
  const plan = key ? loaded?.plan ?? null : null;
  return (
    <BuyDialog
      open
      symbol={symbol}
      referencePrice={Number.isFinite(price) && price > 0 ? price : null}
      tradePlan={plan}
      planKey={plan ? key : null}
      onClose={close}
    />
  );
}
