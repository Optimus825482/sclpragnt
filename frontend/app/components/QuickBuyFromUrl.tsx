"use client";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";
import BuyDialog from "./user/home/BuyDialog";

/**
 * Push bildirimindeki "Alım yap" aksiyonu (sw.template.js) `?buy=SEMBOL&buy_price=FIYAT` ile gelir.
 * Hangi sayfaya düşerse düşsün alım penceresini açar; kapanınca yalnız bu parametreler URL'den silinir.
 */
export default function QuickBuyFromUrl() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const symbol = params.get("buy");
  const price = Number(params.get("buy_price"));

  const close = useCallback(() => {
    const next = new URLSearchParams(params.toString());
    next.delete("buy");
    next.delete("buy_price");
    const q = next.toString();
    router.replace(q ? `${pathname}?${q}` : pathname, { scroll: false });
  }, [params, pathname, router]);

  if (!symbol) return null;
  return <BuyDialog open symbol={symbol} referencePrice={Number.isFinite(price) && price > 0 ? price : null} onClose={close} />;
}
