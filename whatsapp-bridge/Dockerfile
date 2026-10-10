# ScalperAgent WhatsApp köprüsü (Baileys) — üretim imajı.
# Node 20 slim: Baileys saf JS; native derleme gerekmez.
FROM node:20-slim

WORKDIR /app

# git GEREKLİ: Baileys'in bağımlılığı `@whiskeysockets/libsignal-node`
# bir git bağımlılığıdır (git+ssh://git@github.com/...). node:20-slim'de git
# YOKTUR → `npm install` "syscall spawn git / enoent" ile patlar (deploy hatası).
# ca-certificates: git+ssh/https çekimi için TLS kök sertifikaları.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates openssh-client \
    && rm -rf /var/lib/apt/lists/* \
    && git config --global --add url."https://github.com/".insteadOf "ssh://git@github.com/" \
    && git config --global --add url."https://github.com/".insteadOf "git+ssh://git@github.com/"

# Önce bağımlılıklar (katman önbelleği için). Lockfile varsa `npm ci` (reproducible);
# lockfile sürüm uyuşmazlığında güvenli fallback `npm install`.
COPY package.json package-lock.json* ./
RUN (npm ci --omit=dev --no-audit --no-fund \
     || npm install --omit=dev --no-audit --no-fund) \
    && npm cache clean --force

# Uygulama kodu.
COPY index.js ./

# Oturum dosyaları (QR sonrası) buraya yazılır; compose'da VOLUME ile kalıcıdır.
ENV AUTH_DIR=/app/auth
# Coolify/docker-compose ortamında env verilir; varsayılan port.
ENV PORT=3001
EXPOSE 3001

# Basit canlılık: /status ucu 200 döner (bağlantı durumunu JSON'da raporlar).
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD node -e "require('http').get('http://127.0.0.1:3001/status',r=>process.exit(r.statusCode===200?0:1)).on('error',()=>process.exit(1))"

CMD ["node", "index.js"]
