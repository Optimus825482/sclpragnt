// Açık pozisyon K/Z matematiği — koyu tema `lib/pnl.ts` ile aynı sözleşme.
// Kanonik kural: gidiş-dönüş komisyonu = commission_pct × (giriş + çıkış değeri).

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

function positive(value: unknown): number | null {
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? n : null;
}
function sideSign(side: unknown): 1 | -1 {
  return String(side ?? "").toUpperCase() === "SHORT" ? -1 : 1;
}

/** Net açık pozisyon K/Z (₺) — gidiş-dönüş komisyonu düşülmüş. Eksik girdi → null. */
export function netOpenPnlTry(entry: unknown, current: unknown, quantity: unknown, side?: unknown): number | null {
  const e = positive(entry);
  const c = positive(current);
  const q = positive(quantity);
  if (e === null || c === null || q === null) return null;
  const gross = (c - e) * q * sideSign(side);
  const fees = _commissionPct * q * (e + c);
  return gross - fees;
}

/** Net getiri (%). Eksik girdi → null. */
export function netOpenPnlPct(entry: unknown, current: unknown, quantity: unknown, side?: unknown): number | null {
  const e = positive(entry);
  const q = positive(quantity);
  const net = netOpenPnlTry(entry, current, quantity, side);
  if (e === null || q === null || net === null) return null;
  return (net / (e * q)) * 100;
}
