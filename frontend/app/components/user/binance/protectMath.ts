/**
 * Pozisyon koruma (SL / TP / OCO) penceresi için saf hesap. Ağ çağrısı yapmaz.
 *
 * Kullanıcı fiyat yazmaz, YÜZDE seçer: zarar durdur güncel fiyatın %x altı, kâr al %y üstü; miktar elindekinin %z'si.
 * Sonuç doğrudan `/api/binance/set-sl-tp` gövdesidir; `cancel_existing: true` → sunucu önce coindeki açık satış
 * emirlerini iptal eder, sonra yenisini kurar (yeni emir kurulamazsa eskileri geri kurar).
 */
import { checkSlTpInputs, floorQty, roundPriceStr } from "../../../binance-tr/orderSafety";

export type ProtectMode = "OCO" | "SL_ONLY" | "TP_ONLY";

export const PROTECT_SL_CHIPS: readonly number[] = [1, 2, 3, 5];
export const PROTECT_TP_CHIPS: readonly number[] = [2, 3, 5, 8];
export const PROTECT_QTY_CHIPS: readonly number[] = [25, 50, 100];
/** Stop tetiklenince gönderilen limit emir, stop fiyatının bu kadar altında (dolum garantisi için pay). */
export const SL_LIMIT_GAP = 0.995;

export type ProtectInput = {
  mode: ProtectMode;
  /** Güncel fiyat (yüzdelerin bazı). */
  price: number | null | undefined;
  slPct: number | null;
  tpPct: number | null;
  qtyPct: number;
  /** Toplam adet (serbest + emirde kilitli; mevcut emirler iptal edileceği için kilitli kısım da kullanılabilir). */
  total: number;
};

export type ProtectBody = {
  asset?: string;
  mode: ProtectMode;
  quantity: number | "all";
  sl_price?: number;
  sl_limit_price?: number;
  tp_price?: number;
  cancel_existing: true;
};

const pos = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n) && n > 0;

export function protectOrder(input: ProtectInput): { ok: true; body: ProtectBody } | { ok: false; error: string } {
  const { mode, price, slPct, tpPct, qtyPct, total } = input;
  if (!pos(price)) return { ok: false, error: "Güncel fiyat alınamadı; birazdan tekrar dene." };
  if (!pos(total)) return { ok: false, error: "Bu coinde bakiye yok." };
  const wantSl = mode !== "TP_ONLY";
  const wantTp = mode !== "SL_ONLY";
  if (wantSl && !(pos(slPct) && slPct < 100)) return { ok: false, error: "Zarar durdur yüzdesini seç (örn. %2)." };
  if (wantTp && !pos(tpPct)) return { ok: false, error: "Kâr al yüzdesini seç (örn. %5)." };

  const sl = wantSl ? Number(roundPriceStr(price * (1 - (slPct as number) / 100), price)) : undefined;
  const tp = wantTp ? Number(roundPriceStr(price * (1 + (tpPct as number) / 100), price)) : undefined;
  const relErr = checkSlTpInputs(mode, tp, sl, price);
  if (relErr) return { ok: false, error: relErr };

  const quantity = qtyPct >= 100 ? "all" : floorQty((total * qtyPct) / 100, 8);
  if (quantity !== "all" && !(quantity > 0)) return { ok: false, error: "Miktar çok küçük." };

  const body: ProtectBody = { mode, quantity, cancel_existing: true };
  if (sl !== undefined) {
    body.sl_price = sl;
    body.sl_limit_price = Number(roundPriceStr(sl * SL_LIMIT_GAP, price));
  }
  if (tp !== undefined) body.tp_price = tp;
  return { ok: true, body };
}
