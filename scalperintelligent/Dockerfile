# 2026-10-15 (denetim düzeltmesi, §5 P2): `npm install` → `npm ci` (lockfile
# var; `install` lock'u sessizce yeniden yazıp sürüm kaydırabiliyordu),
# runner aşaması ROOT çalışıyordu → `USER node`. frontend/Dockerfile ile
# aynı desen. sha256 digest sabitlemesi ağ erişimi olmadan yapılamadı.
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ARG NEXT_BASE_PATH=/yeni-arayuz
ENV NEXT_BASE_PATH=${NEXT_BASE_PATH}
ARG BACKEND_ORIGIN=http://127.0.0.1:8004
ENV BACKEND_ORIGIN=${BACKEND_ORIGIN}
ARG NEXT_PUBLIC_API_URL=/yeni-arayuz
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV HOSTNAME=0.0.0.0 PORT=3055
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
# Next standalone sunucusu build çıktısını yalnızca OKUR; imaja gömülü `node`
# kullanıcısı (uid 1000) en az ayrıcalıklı seçenektir (bkz. frontend/Dockerfile).
RUN chown -R node:node /app
USER node
EXPOSE 3055
CMD ["node", "server.js"]
