/**
 * Bildirim işlem planı (backend/app/notification_plan.py ile aynı alanlar ve aynı metin).
 * `planSummary` backend `plan_text` çıktısını birebir üretir; ikisi aynı test örnekleriyle sabitlenmiştir.
 * Ağ çağrısı yapmaz, emir göndermez.
 */
import { TP_PCT_MIN, amountFromFree } from "./buyDialogMath";

export type TradePlan = {
  symbol: string;
  bucket: string;
  entry_ref_price: number;
  max_amount_try: number;          // yuvarlanmamış; gösterimde 1.000 TL'ye aşağı yuvarlanır
  max_amount_binding: string;
  target_net_pct: number;
  target_gross_pct: number;
  /** "signal": sinyal hedefi defter hedefini geçti → etiket BRÜT. Eski planlarda yok (= defter). */
  target_source?: "book" | "signal";
  target_price: number;
  stop_pct: number | null;
  stop_price: number | null;
  eta_minutes: number | null;
  exit_at: number | null;          // epoch SANİYE
  grace_minutes: number | null;
  hit_rate: number | null;         // 0..1
  sample_n: number | null;
  profile_exit: boolean;
  warnings: string[];
  created_at: number;              // epoch SANİYE
};

const TZ = "Europe/Istanbul";
const num = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n);

/** Python round(): yarımlar en yakın ÇİFTE (banker's). */
function pyRound(x: number): number {
  const f = Math.floor(x);
  const d = x - f;
  if (d < 0.5) return f;
  if (d > 0.5) return f + 1;
  return f % 2 === 0 ? f : f + 1;
}

/** Python `{:g}` (6 anlamlı hane, sondaki sıfırsız, nokta ondalık). Plan yüzdeleri için yeterli aralıkta. */
function fmtG(x: number): string {
  return String(Number(x.toPrecision(6)));
}

/** Backend `_fmt_price`: 4 anlamlı hane, sondaki sıfırlar atılır, ondalık virgül. */
export function fmtPlanPrice(x: number): string {
  if (x === 0) return "0";
  const decimals = Math.max(3 - Math.floor(Math.log10(Math.abs(x))), 0);
  let s = x.toFixed(Math.min(decimals, 100));
  if (s.includes(".")) s = s.replace(/0+$/, "").replace(/\.$/, "");
  return s.replace(".", ",");
}

/** Backend `_fmt_amount`: 1.000 TL'ye aşağı, binlik nokta. */
export function fmtPlanAmount(x: number): string {
  const v = Math.floor(x / 1000) * 1000;
  return `${String(v).replace(/\B(?=(\d{3})+(?!\d))/g, ".")} TL`;
}

function fmtEta(minutes: number): string {
  const m = pyRound(minutes);
  return m < 60 ? `~${m} dk` : `~${Math.floor(m / 60)} sa ${m % 60} dk`;
}

type IstParts = { day: string; month: string; hm: string; key: string };
const istParts = (sec: number): IstParts => {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).formatToParts(new Date(sec * 1000));
  const g = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  return { day: g("day"), month: g("month"), hm: `${g("hour")}:${g("minute")}`, key: `${g("year")}-${g("month")}-${g("day")}` };
};

/** Backend `plan_shows_gross`: profil çıkışı ya da sinyal hedefi kazandıysa hedef etiketi BRÜT. */
export function planShowsGross(plan: TradePlan): boolean {
  return !!plan.profile_exit || plan.target_source === "signal";
}

/** Backend `plan_text` ile aynı metin. `now` (epoch sn) yalnız `created_at` yoksa kullanılır. */
export function planSummary(plan: TradePlan, now: number): string {
  const warnings = plan.warnings || [];
  const tag = planShowsGross(plan) ? `(+%${fmtG(plan.target_gross_pct)} brüt)` : `(+%${fmtG(plan.target_net_pct)} net)`;
  const parts = [`Maks: ${fmtPlanAmount(plan.max_amount_try)}`, `Hedef ${fmtPlanPrice(plan.target_price)} ${tag}`];
  const lacking = warnings.includes("veri_yetersiz");
  if (lacking) {
    parts.push("Süre: veri yetersiz");
  } else if (num(plan.eta_minutes)) {
    let eta = fmtEta(plan.eta_minutes);
    if (num(plan.hit_rate)) eta += ` (geçmişte %${pyRound(plan.hit_rate * 100)})`;
    parts.push(eta);
  }
  // Profil çıkışında istatistik yoksa yalnız süre bilinmez; profil çıkış saati / stop yine gösterilir.
  if (!lacking || plan.profile_exit) {
    if (num(plan.exit_at)) {
      const ex = istParts(plan.exit_at);
      const cr = istParts(plan.created_at || now);
      const prefix = ex.key === cr.key ? "" : `${ex.day}.${ex.month} `;
      parts.push(`Çıkış ${prefix}${ex.hm}'e kadar`);
    }
    if (num(plan.stop_price)) parts.push(`Stop ${fmtPlanPrice(plan.stop_price)}`);
  }
  let text = parts.join(" | ");
  if (warnings.includes("hedef_gercekci_degil")) text = `⚠ %${fmtG(plan.target_net_pct)} net bu defterde zor · ${text}`;
  return text;
}

/** Çıkış saati kutucuğu: "20:45" ya da başka günse "28.10 20:00". */
export function planExitLabel(plan: TradePlan): string | null {
  if (!num(plan.exit_at)) return null;
  const ex = istParts(plan.exit_at);
  const cr = istParts(plan.created_at || plan.exit_at);
  return ex.key === cr.key ? ex.hm : `${ex.day}.${ex.month} ${ex.hm}`;
}

const WARNING_LABELS: Record<string, string> = {
  veri_yetersiz: "Veri yetersiz",
  hedef_gercekci_degil: "Hedef gerçekçi değil",
};
export function planWarningLabels(warnings: string[] | null | undefined): string[] {
  return (warnings || []).map((w) => WARNING_LABELS[w]).filter((x): x is string => !!x);
}

/** Canlı fiyatın plan giriş fiyatından yüzde sapması (mutlak). Veri yoksa null. */
export function priceDeviationPct(entryRef: number, live: number | null | undefined): number | null {
  if (!num(entryRef) || entryRef <= 0 || !num(live) || live <= 0) return null;
  return Math.abs(live - entryRef) / entryRef * 100;
}
export const DEVIATION_WARN_PCT = 1;

/** Alım penceresinin başlangıç değerleri. Plan yoksa bugünkü varsayılan (%25 serbest bakiye, SL/TP yok). */
export function planDialogDefaults(
  plan: TradePlan | null,
  freeTry: number,
): { amountTry: number; slPct: number | null; tpPct: number | null; oco: boolean } {
  if (!plan) return { amountTry: amountFromFree(freeTry, 25), slPct: null, tpPct: null, oco: false };
  const free = num(freeTry) ? freeTry : 0;
  const slPct = num(plan.stop_pct) ? plan.stop_pct : null;
  const tp = num(plan.target_gross_pct) ? Math.max(plan.target_gross_pct, TP_PCT_MIN) : null;
  return {
    amountTry: Math.floor(Math.min(plan.max_amount_try, free)),
    slPct,
    tpPct: tp,
    oco: slPct != null,
  };
}

export type PlanTile = { label: string; value: string; sub?: string };

/** Modal/kart kutucukları: MAKS TUTAR, HEDEF, STOP, SÜRE, ÇIKIŞ. Değeri olmayan kutucuk atlanır. */
export function planTiles(plan: TradePlan): PlanTile[] {
  const lacking = (plan.warnings || []).includes("veri_yetersiz");
  const tiles: PlanTile[] = [
    { label: "MAKS TUTAR", value: fmtPlanAmount(plan.max_amount_try) },
    {
      label: planShowsGross(plan) ? "HEDEF (brüt)" : `HEDEF (+%${fmtG(plan.target_net_pct)} net)`,
      value: fmtPlanPrice(plan.target_price),
      sub: `+%${fmtG(Number(plan.target_gross_pct.toFixed(2)))} brüt`,
    },
  ];
  if (num(plan.stop_price)) tiles.push({ label: "STOP", value: fmtPlanPrice(plan.stop_price), sub: num(plan.stop_pct) ? `-%${fmtG(Number(plan.stop_pct.toFixed(2)))}` : undefined });
  if (lacking) tiles.push({ label: "SÜRE", value: "veri yetersiz" });
  else if (num(plan.eta_minutes)) {
    tiles.push({ label: "SÜRE", value: fmtEta(plan.eta_minutes), sub: num(plan.hit_rate) ? `geçmişte %${pyRound(plan.hit_rate * 100)}` : undefined });
  }
  const exit = lacking && !plan.profile_exit ? null : planExitLabel(plan);
  if (exit) tiles.push({ label: "ÇIKIŞ", value: exit });
  return tiles;
}
