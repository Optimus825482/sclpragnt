import { readFileSync, writeFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("../app", import.meta.url));
const MAP = {
  "bunker-950": [245, 247, 251], "bunker-900": [255, 255, 255], "bunker-800": [227, 232, 242],
  "bunker-700": [203, 211, 227], "bunker-600": [139, 148, 173], "bunker-muted": [91, 100, 120],
  "neon-green": [15, 138, 78], "neon-greenHover": [11, 110, 62], "neon-red": [200, 40, 40],
  "neon-yellow": [166, 110, 8], white: [15, 23, 42], black: [15, 23, 42],
};
const PROPS = { bg: "background-color", text: "color", border: "border-color", divide: "border-color" };
const re = /\b(bg|text|border|divide)-(bunker-(?:950|900|800|700|600|muted)|neon-(?:greenHover|green|red|yellow)|white|black)(?:\/(\d{1,3}))?(?![\w-])/g;

function walk(dir, out = []) {
  for (const f of readdirSync(dir)) {
    const p = join(dir, f);
    if (statSync(p).isDirectory()) { if (!["node_modules", ".next"].includes(f)) walk(p, out); }
    else if (/\.(tsx|ts)$/.test(f)) out.push(p);
  }
  return out;
}

const found = new Set();
for (const file of walk(ROOT)) {
  for (const m of readFileSync(file, "utf8").matchAll(re)) found.add(m[0]);
}
const rules = [...found].sort().map((cls) => {
  const [, kind, color, alpha] = cls.match(/^(bg|text|border|divide)-(.+?)(?:\/(\d{1,3}))?$/);
  const [r, g, b] = MAP[color];
  const value = alpha ? `rgb(${r} ${g} ${b} / ${Number(alpha) / 100})` : `rgb(${r} ${g} ${b})`;
  const sel = `.${cls.replace(/\//g, String.raw`\/`)}`;
  const target = kind === "divide" ? `${sel} > :not([hidden]) ~ :not([hidden])` : sel;
  return `[data-theme="light"] ${target}{${PROPS[kind]}:${value}}`;
});
const header = "/* ÜRETİLDİ: node scripts/gen-light-theme.mjs — elle düzenleme yapma; elle kurallar user-theme.manual.css'te. */\n";
writeFileSync(join(ROOT, "user-theme.generated.css"), header + rules.join("\n") + "\n");
console.log(`${rules.length} kural üretildi`);
