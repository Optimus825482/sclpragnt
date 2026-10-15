// Açık pozisyon K/Z matematiği — koyu tema `lib/pnl.ts` ile aynı sözleşme.
// Kanonik kural: gidiş-dönüş komisyonu = commission_pct × (giriş + çıkış değeri).
//
// Denetim 2026-10-15: `netOpenPnlTry` / `netOpenPnlPct` bu arayüzde hiçbir
// yerden çağrılmıyordu (ölü kod); kaldırıldı. Açık K/Z değerleri backend'in
// `/api/binance/positions` yanıtındaki `pnl_try` / `pnl_pct` alanlarından gelir.

export const COMMISSION_PCT_FALLBACK = 0.0015;
let _commissionPct = COMMISSION_PCT_FALLBACK;

/** Backend'den gelen gerçek komisyon oranını uygular (WS `portfolio` / /api/config). */
export function applyCommissionPct(value: unknown): void {
  const n = Number(value);
  if (Number.isFinite(n) && n > 0 && n < 0.05) _commissionPct = n;
}
export function commissionPct(): number {
  return _commissionPct;
}
