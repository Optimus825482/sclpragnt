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
