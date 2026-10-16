import { describe, expect, it } from "vitest";
import palette from "../../scripts/user-palette.json";

/** WCAG 2.1 göreli parlaklık ve kontrast oranı. */
function lum(hex: string): number {
  const n = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(n.slice(i, i + 2), 16) / 255)
    .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
function ratio(a: string, b: string): number {
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}
/** `fg`'yi `alpha` ile `bg` üzerine karıştırır (ör. bg-neon-green/10 zemin). */
function mix(fg: string, bg: string, alpha: number): string {
  const p = (h: string, i: number) => parseInt(h.replace("#", "").slice(i, i + 2), 16);
  const c = (i: number) => Math.round(p(fg, i) * alpha + p(bg, i) * (1 - alpha)).toString(16).padStart(2, "0");
  return `#${c(0)}${c(2)}${c(4)}`;
}

const AA = 4.5;
const tones = ["good", "warn", "bad", "info", "wait"] as const;

describe("kullanıcı paleti kontrastı (WCAG AA)", () => {
  it("metin / sayfa ve kart", () => {
    expect(ratio(palette.ink, palette.page)).toBeGreaterThanOrEqual(AA);
    expect(ratio(palette.ink, palette.card)).toBeGreaterThanOrEqual(AA);
    expect(ratio(palette.muted, palette.page)).toBeGreaterThanOrEqual(AA);
    expect(ratio(palette.muted, palette.card)).toBeGreaterThanOrEqual(AA);
  });
  it("marka düğmesi: beyaz yazı", () => {
    expect(ratio(palette.brandText, palette.brand)).toBeGreaterThanOrEqual(AA);
  });
  for (const tone of tones) {
    it(`${tone}: rozet (fg/bg), kartta renkli sayı (solid/kart), dolgu üstü beyaz yazı, hafif zemin üstü solid`, () => {
      const t = palette[tone];
      expect(ratio(t.fg, t.bg)).toBeGreaterThanOrEqual(AA);
      expect(ratio(t.solid, palette.card)).toBeGreaterThanOrEqual(AA);
      expect(ratio(palette.card, t.solid)).toBeGreaterThanOrEqual(AA);
      expect(ratio(t.solid, mix(t.solid, palette.card, 0.1))).toBeGreaterThanOrEqual(AA);
      expect(ratio(t.solid, mix(t.solid, palette.page, 0.1))).toBeGreaterThanOrEqual(AA);
    });
  }
  it("renkler birbirinden ayırt edilir (iyi/kötü/uyarı)", () => {
    const solids = tones.map((t) => palette[t].solid);
    expect(new Set(solids).size).toBe(tones.length);
  });
});
