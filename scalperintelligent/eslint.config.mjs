// ESLint flat config (denetim 2026-10-15, bölüm 6: iki frontend'de de lint yoktu).
// Next 16: `eslint-config-next` düz (flat) config dizisi dışa aktarır.
//
// TABAN (baseline) POLİTİKASI: İlk kurulumda mevcut kod ~400 ihlal verdi
// (çoğu `no-explicit-any` ve yeni React Compiler kuralları). Kapıyı ilk
// çalışmada kırmamak için bu kurallar `warn`'a indirildi — görünür kalır ama
// CI'ı kırmaz. Kalan kurallar (rules-of-hooks, core-web-vitals vb.) `error`.
// Taban temizlendikçe kurallar tek tek "error"a çevrilmeli.
import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

export default defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    rules: {
      "@typescript-eslint/no-explicit-any": "warn",
      "@typescript-eslint/no-require-imports": "warn",
      "@next/next/no-html-link-for-pages": "warn",
      "react/no-unescaped-entities": "warn",
      "react-hooks/set-state-in-effect": "warn",
      "react-hooks/refs": "warn",
      "react-hooks/static-components": "warn",
      "react-hooks/immutability": "warn",
      "react-hooks/purity": "warn",
      "react-hooks/preserve-manual-memoization": "warn",
      "prefer-const": "warn",
    },
  },
  globalIgnores([".next/**", "out/**", "build/**", "coverage/**", "next-env.d.ts", "node_modules/**", "*.config.js"]),
]);
