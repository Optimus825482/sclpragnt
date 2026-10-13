import type { Config } from "tailwindcss";

/**
 * Odak UI — AÇIK TEMA tasarım jetonları.
 *
 * Mevcut `frontend/` koyu (bunker + neon yeşil) temalıdır. Bu arayüz bilinçli
 * olarak AYRI bir görsel dil kullanır:
 *   - Açık/nötr zemin, beyaz kartlar, tek MAVİ vurgu (#0066ff).
 *   - Yeşil YALNIZCA kâr/pozitif veri için; kırmızı YALNIZCA zarar/negatif.
 *     (Tasarım incelemesinde "her blokta doygun yeşil" en büyük hiyerarşi
 *      sorunu olarak işaretlendi — burada vurgu rengi maviye ayrıldı.)
 */
export default {
  content: ["./app/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          900: "#0f172a", // ana metin
          700: "#334155",
          500: "#64748b", // ikincil metin
          400: "#94a3b8",
        },
        canvas: "#eef2f7", // sayfa zemini
        card: "#ffffff",
        line: "#e2e8f0", // kenarlıklar
        accent: {
          DEFAULT: "#0066ff",
          soft: "#e8f0ff",
          hover: "#0052cc",
        },
        gain: { DEFAULT: "#16a34a", soft: "#e7f6ec" },
        loss: { DEFAULT: "#dc2626", soft: "#fdeceb" },
        warn: { DEFAULT: "#d97706", soft: "#fef3e2" },
      },
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      borderRadius: {
        xl: "0.75rem",
        "2xl": "1rem",
      },
      boxShadow: {
        card: "0 1px 2px rgba(15,23,42,.06), 0 8px 24px rgba(15,23,42,.05)",
        pop: "0 12px 40px rgba(15,23,42,.14)",
      },
    },
  },
  plugins: [],
} satisfies Config;
