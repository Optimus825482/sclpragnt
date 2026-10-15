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
 * Ayrıntı: scalperintelligent/README.md.
 */
/*
 * BACKEND_ORIGIN — BUILD-TIME değerdir (denetim P2, 2026-10-15, bilinçli olarak
 * bırakıldı): `output: "standalone"` ile Next.js `rewrites()` sonucunu derleme
 * sırasında `.next/routes-manifest.json` içine gömer; `async rewrites()` içinde
 * `process.env` okumak da yalnız derleme anında çalışır, `next start`/standalone
 * sunucu manifesti yeniden üretmez. Çalışma zamanında farklı backend adresi
 * gerekiyorsa seçenekler: (a) imajı hedef ortamın BACKEND_ORIGIN'i ile derlemek
 * (Dockerfile ARG), (b) rewrite yerine `app/api/[...path]/route.ts` ile
 * çalışma zamanı proxy yazmak (cookie/Set-Cookie ve streaming'i elle taşımak
 * gerekir). Bağımlılık eklemeden (b) bu denetim kapsamına alınmadı.
 */
const BACKEND_ORIGIN = process.env.BACKEND_ORIGIN || "http://127.0.0.1:8004";

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  // Üretimde aynı host altında oturum cookie'sini paylaşarak sunulur.
  // Değer build-time'da gömülür; yerel geliştirmede kök yol varsayılanı korunur.
  basePath: process.env.NEXT_BASE_PATH || "",
  async rewrites() {
    // `/api/*` → backend. `:path*` yakalama; sorgu dizesi korunur.
    return [{ source: "/api/:path*", destination: `${BACKEND_ORIGIN}/api/:path*` }];
  },
  headers: async () => [
    { source: "/sw.js", headers: [{ key: "Cache-Control", value: "no-store" }] },
  ],
};

module.exports = nextConfig;
