FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --no-audit --no-fund

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
EXPOSE 3055
CMD ["node", "server.js"]
