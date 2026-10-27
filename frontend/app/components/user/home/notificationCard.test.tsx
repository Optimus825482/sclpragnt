/**
 * "Bugün #N" rozeti (2026-10-24): kart yalnız `daily_seq` sayı olduğunda rozeti çizer.
 * jsdom yok; bileşen `react-dom/server` ile statik HTML'e çevrilir (vitest node ortamı).
 */
import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import NotificationCard, { type CardActions, type RecentRow } from "./NotificationCard";
import DailySeqChip, { dailySeqAria, dailySeqText } from "./DailySeqChip";

const actions: CardActions = {
  isFavorite: () => false,
  isPinned: () => false,
  onToggleFavorite: () => {},
  onTogglePin: () => {},
  onBuy: () => {},
};

const NOW = 1_800_000_000;
const row: RecentRow = { id: 4, symbol: "TREETRY", price: 1.23, detected_at: NOW - 120, target_pct: 3, horizon_minutes: 15 };

const render = (r: RecentRow) =>
  renderToStaticMarkup(<NotificationCard row={r} rank={1} live={null} nowSec={NOW} actions={actions} />);

describe("DailySeqChip", () => {
  it("metin ve erişilebilirlik etiketi Türkçe", () => {
    expect(dailySeqText(3)).toBe("Bugün #3");
    expect(dailySeqAria(3)).toBe("Bugün bu coin için 3. bildirim");
  });

  it("sayı değilse hiçbir şey çizmez", () => {
    expect(renderToStaticMarkup(<DailySeqChip seq={null} />)).toBe("");
    expect(renderToStaticMarkup(<DailySeqChip seq={undefined} />)).toBe("");
    expect(renderToStaticMarkup(<DailySeqChip seq={Number.NaN} />)).toBe("");
  });

  it("sayıysa u-chip rozetini çizer", () => {
    const html = renderToStaticMarkup(<DailySeqChip seq={2} />);
    expect(html).toContain("Bugün #2");
    expect(html).toContain('aria-label="Bugün bu coin için 2. bildirim"');
    expect(html).toMatch(/class="u-chip u-chip-wait/);
  });
});

describe("NotificationCard daily_seq", () => {
  it("daily_seq=3 → başlıkta 'Bugün #3' rozeti", () => {
    const html = render({ ...row, daily_seq: 3 });
    expect(html).toContain("Bugün #3");
    expect(html).toContain('aria-label="Bugün bu coin için 3. bildirim"');
    // Sıra rozeti (liste konumu) korunur.
    expect(html).toContain('aria-label="Sıra 1"');
  });

  it("daily_seq yok / null → rozet yok", () => {
    expect(render(row)).not.toContain("Bugün #");
    expect(render({ ...row, daily_seq: null })).not.toContain("Bugün #");
  });
});

describe("NotificationCard işlem planı", () => {
  const plan = {
    symbol: "TREETRY", bucket: "radar", entry_ref_price: 1.23, max_amount_try: 40_999.7, max_amount_binding: "depth",
    target_net_pct: 3, target_gross_pct: 3.4, target_price: 6.2199, stop_pct: 4.2, stop_price: 5.82,
    eta_minutes: 35, exit_at: NOW + 2100, grace_minutes: 90, hit_rate: 0.62, sample_n: 50,
    profile_exit: false, warnings: ["hedef_gercekci_degil"], created_at: NOW,
  };
  it("plan varsa kutucuklar, özet satırı ve uyarı rozeti görünür", () => {
    const html = render({ ...row, trade_plan: plan, plan_key: "k1" });
    expect(html).toContain("MAKS TUTAR");
    expect(html).toContain("40.000 TL");
    expect(html).toContain("HEDEF (+%3 net)");
    expect(html).toContain("STOP");
    expect(html).toContain("Hedef gerçekçi değil");
    expect(html).toContain("Maks: 40.000 TL | Hedef 6,22 (+%3 net)");
  });
  it("plan yoksa plan arayüzü çizilmez", () => {
    expect(render(row)).not.toContain("MAKS TUTAR");
    expect(render({ ...row, trade_plan: null })).not.toContain("MAKS TUTAR");
  });
});

describe("NotificationCard Alım yap + plan", () => {
  it("onBuy plan ve plan_key ile çağrılır (uygulama içi alım)", () => {
    const calls: unknown[][] = [];
    const a: CardActions = { ...actions, onBuy: (...args) => { calls.push(args); } };
    const plan = { symbol: "TREETRY", bucket: "radar", entry_ref_price: 1.23, max_amount_try: 5000, max_amount_binding: "depth",
      target_net_pct: 3, target_gross_pct: 3.4, target_price: 1.27, stop_pct: 4, stop_price: 1.18, eta_minutes: null, exit_at: null,
      grace_minutes: null, hit_rate: null, sample_n: null, profile_exit: false, warnings: [], created_at: NOW };
    const el = NotificationCard({ row: { ...row, trade_plan: plan, plan_key: "k9" }, rank: 1, live: null, nowSec: NOW, actions: a });
    // Alım yap düğmesinin onClick'ini React ağacından bul.
    const find = (n: any): any => {
      if (!n || typeof n !== "object") return null;
      if (n.props?.onClick && JSON.stringify(n.props.children ?? "").includes("Alım yap")) return n;
      const kids = n.props?.children;
      for (const k of Array.isArray(kids) ? kids.flat(Infinity) : [kids]) { const r = find(k); if (r) return r; }
      return null;
    };
    const walk = (n: any): any => {
      if (!n || typeof n !== "object") return null;
      if (typeof n.type === "function") { const r = walk(n.type(n.props)); if (r) return r; }
      return find(n) ?? (Array.isArray(n.props?.children) ? n.props.children.flat(Infinity).map(walk).find(Boolean) : walk(n.props?.children));
    };
    const btn = walk(el);
    expect(btn).toBeTruthy();
    btn.props.onClick();
    expect(calls[0]).toEqual(["TREETRY", row.price, plan, "k9"]);
  });
});
