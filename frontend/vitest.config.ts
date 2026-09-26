import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

/**
 * Frontend test altyapısı.
 *
 * Kapsam bilinçli olarak dar: `lib/` ve `charts/` altındaki SAF matematik
 * modülleri (pnl.ts, signals.ts, format.ts). React bileşenlerinin testi için
 * jsdom kurulmadı — para matematiği doğrulanmadan UI testi kıymetsiz; önce
 * hesabın kendisi kilitlenir.
 *
 * `next typegen` gerektirmeyen, `tsconfig` yollarına (`@/*`) bağımlı olmayan
 * bağımsız bir kurulum; `tsc --noEmit` typecheck ile ayrı çalışır.
 */
export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL(".", import.meta.url)),
    },
  },
  test: {
    environment: "node",
    include: [
      "app/**/*.{test,spec}.{ts,tsx}",
      "tests/**/*.{test,spec}.{ts,tsx}",
    ],
    reporters: ["default"],
    passWithNoTests: false,
  },
});
