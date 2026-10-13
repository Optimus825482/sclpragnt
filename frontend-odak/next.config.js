/**
 * Odak UI — Scalper Agent V4 için alternatif, sadeleştirilmiş panel.
 *
 * ENTEGRASYON MODELİ (bilinçli seçim):
 * Tarayıcı `/api/...` isteklerini kendi origin'ine (odak-ui) yapar; Next.js
 * sunucusu bunları `BACKEND_ORIGIN`'e proxy'ler. Böylece:
 *   1) CORS yapılandırması GEREKMEZ — proxy sunucu-sunucu olduğu için
 *      tarayıcı çapraz köken isteği görmez.
 *   2) Oturum cookie'si (scalper_session) odak-ui origin'inde saklanır ve
 *      backend'in `Set-Cookie`'si aynı yoldan geri iletilir → giriş çalışır.
 * Ayrıntı: frontend-odak/README.md.
 */
const BACKEND_ORIGIN = process.env.BACKEND_ORIGIN || "http://127.0.0.1:8004";

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  async rewrites() {
    // `/api/*` → backend. `:path*` yakalama; sorgu dizesi korunur.
    return [{ source: "/api/:path*", destination: `${BACKEND_ORIGIN}/api/:path*` }];
  },
  headers: async () => [
    { source: "/sw.js", headers: [{ key: "Cache-Control", value: "no-store" }] },
  ],
};

module.exports = nextConfig;
