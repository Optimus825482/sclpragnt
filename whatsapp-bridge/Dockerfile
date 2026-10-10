# ScalperAgent WhatsApp köprüsü (Baileys) — üretim imajı.
# Node 20 slim: Baileys saf JS; native derleme gerekmez.
FROM node:20-slim

WORKDIR /app

# Önce bağımlılıklar (katman önbelleği için).
COPY package.json ./
RUN npm install --omit=dev && npm cache clean --force

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
