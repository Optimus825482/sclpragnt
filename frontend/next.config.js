/** @type {import('next').NextConfig} */
const { execSync } = require("child_process");

const getBuildId = () => {
  try {
    const commit = execSync("git rev-parse --short HEAD").toString().trim();
    return `${Date.now().toString(36)}-${commit}`;
  } catch {
    return Date.now().toString(36);
  }
};

const BUILD_ID = getBuildId();

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
