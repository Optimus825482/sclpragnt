import { readFileSync, writeFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("../app", import.meta.url));
const PALETTE = JSON.parse(readFileSync(new URL("./user-palette.json", import.meta.url), "utf8"));
const rgb = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
const MAP = {
  "bunker-950": rgb(PALETTE.page), "bunker-900": rgb(PALETTE.card), "bunker-800": rgb(PALETTE.line),
  "bunker-700": rgb(PALETTE.line2), "bunker-600": rgb(PALETTE.muted), "bunker-muted": rgb(PALETTE.muted),
  "neon-green": rgb(PALETTE.good.solid), "neon-greenHover": rgb(PALETTE.good.fg), "neon-red": rgb(PALETTE.bad.solid),
  "neon-yellow": rgb(PALETTE.warn.solid), white: rgb(PALETTE.ink), black: rgb(PALETTE.ink),
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

const files = walk(ROOT);
const found = new Set();
for (const file of files) {
  for (const m of readFileSync(file, "utf8").matchAll(re)) {
    // bg-white/border-white açık yüzeydir; light temada olduğu gibi kalır (koyuya çevrilmez).
    if (/^(bg|border|divide)-white/.test(m[0])) continue;
    found.add(m[0]);
  }
}
const rules = [...found].sort().map((cls) => {
  const [, kind, color, alpha] = cls.match(/^(bg|text|border|divide)-(.+?)(?:\/(\d{1,3}))?$/);
  const [r, g, b] = MAP[color];
  const value = alpha ? `rgb(${r} ${g} ${b} / ${Number(alpha) / 100})` : `rgb(${r} ${g} ${b})`;
  const sel = `.${cls.replace(/\//g, String.raw`\/`)}`;
  const target = kind === "divide" ? `${sel} > :not([hidden]) ~ :not([hidden])` : sel;
  return `[data-theme="light"] ${target}{${PROPS[kind]}:${value}}`;
});

// Tailwind varsayılan vurgu renkleri: açık tonlar koyu zeminde okunur, beyazda okunmaz → 700 tonu.
const ACCENT700 = {
  yellow: [161, 98, 7], amber: [180, 83, 9], cyan: [14, 116, 144], sky: [3, 105, 161], blue: [29, 78, 216],
  emerald: [4, 120, 87], green: [21, 128, 61], lime: [77, 124, 15], teal: [15, 118, 110], red: [185, 28, 28],
  rose: [190, 18, 60], orange: [194, 65, 12], purple: [126, 34, 206], violet: [109, 40, 217], pink: [190, 24, 93],
  fuchsia: [162, 28, 175], indigo: [67, 56, 202],
};
const reAccent = new RegExp(String.raw`\btext-(${Object.keys(ACCENT700).join("|")})-(200|300|400)(?![\w-])`, "g");
const reNeutral = /\btext-(slate|gray|zinc|neutral)-(100|200|300|400|500)(?![\w-])/g;
const extra = new Map();
for (const file of files) {
  const src = readFileSync(file, "utf8");
  for (const m of src.matchAll(reAccent)) extra.set(m[0], ACCENT700[m[1]].join(" "));
  for (const m of src.matchAll(reNeutral)) extra.set(m[0], Number(m[2]) >= 400 ? "91 100 120" : "51 65 85");
}
for (const [cls, rgb] of [...extra].sort()) {
  rules.push(`[data-theme="light"] .${cls}{color:rgb(${rgb})}`);
}

const header = "/* ÜRETİLDİ: node scripts/gen-light-theme.mjs — elle düzenleme yapma; elle kurallar user-theme.manual.css'te. */\n";
writeFileSync(join(ROOT, "user-theme.generated.css"), header + rules.join("\n") + "\n");
console.log(`${rules.length} kural üretildi`);

// ---- Anlamsal sınıflar (rozet, sayı, çubuk, düğme) + CSS değişkenleri: palet JSON'undan ----
const tones = ["good", "warn", "bad", "info", "wait"];
const vars = [`--u-page:${PALETTE.page}`, `--u-card:${PALETTE.card}`, `--u-ink:${PALETTE.ink}`, `--u-muted:${PALETTE.muted}`,
  `--u-line:${PALETTE.line}`, `--u-brand:${PALETTE.brand}`, `--u-brand-text:${PALETTE.brandText}`,
  ...tones.flatMap((t) => [`--u-${t}-fg:${PALETTE[t].fg}`, `--u-${t}-bg:${PALETTE[t].bg}`, `--u-${t}:${PALETTE[t].solid}`])];
const sem = [
  `[data-theme="light"]{${vars.join(";")}}`,
  `[data-theme="light"] .u-chip{display:inline-flex;align-items:center;gap:.3rem;padding:.2rem .65rem;border-radius:999px;font-size:.75rem;font-weight:700;line-height:1.2;white-space:nowrap}`,
  ...tones.flatMap((t) => [
    `[data-theme="light"] .u-chip-${t}{background:${PALETTE[t].bg};color:${PALETTE[t].fg}}`,
    `[data-theme="light"] .u-num-${t}{color:${PALETTE[t].solid}}`,
    `[data-theme="light"] .u-bar-${t}{background:${PALETTE[t].solid}}`,
    `[data-theme="light"] .card.u-card-${t}{border-top:4px solid ${PALETTE[t].solid};background:linear-gradient(180deg,${PALETTE[t].bg} 0,${PALETTE.card} 70%)}`,
  ]),
  `[data-theme="light"] .u-btn-brand{background:${PALETTE.brand};color:${PALETTE.brandText};font-weight:700}`,
  `[data-theme="light"] .u-chip-brand{background:${PALETTE.brand};color:${PALETTE.brandText}}`,
  `[data-theme="light"] .u-seg-on{background:${PALETTE.brand};color:${PALETTE.brandText}}`,
  `[data-theme="light"] .u-seg-off{background:${PALETTE.card};color:${PALETTE.ink};border:1px solid ${PALETTE.line}}`,
];
writeFileSync(join(ROOT, "user-palette.generated.css"),
  "/* ÜRETİLDİ: node scripts/gen-light-theme.mjs (kaynak: scripts/user-palette.json) */" + String.fromCharCode(10)
  + sem.join(String.fromCharCode(10)) + String.fromCharCode(10));
console.log(`palet CSS: ${sem.length} kural`);
