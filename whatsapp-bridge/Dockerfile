# ScalperAgent WhatsApp köprüsü (Baileys) — üretim imajı.
#
# 2026-10-15 (denetim düzeltmesi, §5 P2): tek aşamalı node:20-slim + root +
# imajda git/openssh → çok aşamalı node:22-alpine + `USER node`. git YALNIZ
# bağımlılık kurulumunda gerekir (`@whiskeysockets/baileys` → `libsignal`
# git+https bağımlılığı; package-lock'ta commit'e sabitlenmiş); çalışma
# imajına git/ssh KOPYALANMAZ. Baileys saf JS (WhatsApp Web protokolü);
# whatsapp-web.js gibi Chromium/Puppeteer GEREKMEZ, sistem paketi yok.
# Tek isteğe bağlı native bağımlılık `sharp` (Baileys medya önizlemesi):
# lockfile'da `@img/sharp-linuxmusl-x64` önceden derlenmiş paketi var →
# Alpine'da derleyici gerekmez. sha256 digest sabitlemesi ağ olmadan yapılamadı.

# --- Aşama 1: bağımlılıklar (git burada kalır) --------------------------
FROM node:22-alpine AS deps
WORKDIR /app
# git: libsignal git bağımlılığı için (clone). ssh anahtarı YOK → git+ssh
# URL'leri https'e yönlendirilir (lock zaten git+https; npm bazı sürümlerde
# package.json'daki ssh biçimine düşebiliyor, insteadOf iki biçimi de kapsar).
RUN apk add --no-cache git ca-certificates \
    && git config --global --add url."https://github.com/".insteadOf "ssh://git@github.com/" \
    && git config --global --add url."https://github.com/".insteadOf "git+ssh://git@github.com/"
COPY package.json package-lock.json ./
# Lockfile var → `npm ci` (reproducible). Eski `|| npm install` geri düşüşü
# kaldırıldı: lock uyuşmazlığı build'i KIRMALI, sessizce sürüm kaydırmamalı.
RUN npm ci --omit=dev --no-audit --no-fund \
    && npm cache clean --force

# --- Aşama 2: çalışma imajı (git/ssh yok, non-root) ---------------------
FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=deps /app/node_modules ./node_modules
COPY package.json index.js ./

# Oturum dosyaları (QR sonrası) buraya yazılır; compose'da VOLUME ile kalıcıdır.
# Dizin node (uid 1000) sahipliğinde oluşturulur: YENİ bir named volume ilk
# mount'ta bu sahipliği devralır.
# ⚠️ MEVCUT KURULUM YÜKSELTMESİ: `whatsapp_auth` volume'u eski ROOT konteyner
# tarafından doldurulduysa dosyalar root sahipliğindedir ve uid 1000 yazamaz
# (oturum yenilenemez → QR tekrar istenir / kayıt hatası). Tek seferlik düzeltme:
#   docker run --rm -v whatsapp_auth:/app/auth alpine chown -R 1000:1000 /app/auth
ENV AUTH_DIR=/app/auth
RUN mkdir -p /app/auth && chown -R node:node /app
USER node

# Coolify/docker-compose ortamında env verilir; varsayılan port.
ENV PORT=3001
EXPOSE 3001

# Basit canlılık: /status ucu 200 döner (bağlantı durumunu JSON'da raporlar).
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD node -e "require('http').get('http://127.0.0.1:3001/status',r=>process.exit(r.statusCode===200?0:1)).on('error',()=>process.exit(1))"

CMD ["node", "index.js"]
