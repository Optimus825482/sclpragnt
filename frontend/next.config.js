/** @type {import('next').NextConfig} */
const { execSync } = require("child_process");

// Derleme kimliği TEK değerde sabitlenir. `next build` işçi süreçleri bu dosyayı ayrıca yükler;
// her biri kendi `Date.now()`'unu üretirse `NEXT_PUBLIC_BUILD_ID` (istemci paketi, /sw.js,
// /build-id.json) ile `generateBuildId` birbirinden farklı çıkabilir ve "Yeni sürüm var"
// şeridi sürekli yanlış alarm verirdi. Ortam değişkeni alt süreçlere miras kalır.
// Dışarıdan verilebilir: BUILD_ID, Coolify'ın SOURCE_COMMIT değeri.
const getBuildId = () => {
  if (process.env.SCALPER_BUILD_ID) return process.env.SCALPER_BUILD_ID;
  const external = process.env.BUILD_ID || process.env.SOURCE_COMMIT;
  if (external) return `${Date.now().toString(36)}-${String(external).slice(0, 8)}`;
  try {
    const commit = execSync("git rev-parse --short HEAD").toString().trim();
    return `${Date.now().toString(36)}-${commit}`;
  } catch {
    return Date.now().toString(36);
  }
};

const BUILD_ID = getBuildId();
process.env.SCALPER_BUILD_ID = BUILD_ID;

const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  generateBuildId: () => BUILD_ID,
  env: {
    NEXT_PUBLIC_BUILD_ID: BUILD_ID,
  },
  // ÖNBELLEK KONTROLÜ (2026-09-16): her deploy'da sw.js ve uygulama JS'leri
  // otomatik yenilensin. sw.js yalnızca "no-cache" (her seferinde sunucuya
  // doğrula); /_next/static hash'li asset'leri zaten content-hash'li olduğu
  // için immutable kalır; HTML dokümanları no-cache. Böylece ?v=<BUILD_ID>
  // değiştiğinde tarayıcı yeni SW + yeni JS alır, bayat shell kalmaz.
  headers: async () => [
    {
      source: "/sw.js",
      headers: [
        { key: "Cache-Control", value: "no-cache, no-store, must-revalidate" },
        { key: "Pragma", value: "no-cache" },
      ],
    },
  ],
};

module.exports = nextConfig;
