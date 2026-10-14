# SCALPERNEW — bağımsız izole deployment

Eski stack'in (kök `docker-compose.yaml` → scalper.erkanerdem.online) **tamamen
ayrı** bir kopyası: kendi Postgres'i (DB adı: `scalpernew`), kendi volume'ları,
kendi ağı ve kendi domain'i (`scalpernew.erkanerdem.online`) var. Eski stack ile
hiçbir kaynak paylaşmaz; aynı sunucuda yan yana çalışabilir.

## Dizin yapısı

| Dizin | İçerik |
|---|---|
| `backend/` | Backend'in temiz kopyası (yalnız Dockerfile'ın kullandığı: `app/`, `migrations/`, `scripts/`, `.well-known/`, testler). Araştırma JSON'ları, `.env`, venv DAHİL DEĞİL. |
| `frontend/` | `scalperintelligent` arayüzünün kopyası (node_modules/.next hariç). **basePath YOK** — kökte servis edilir. |
| `nginx/` | Bu stack'e özel hardened gateway config (`scalpernew.erkanerdem.online`). |
| `whatsapp-bridge/` | Baileys köprüsü (varsayılan kapalı). |
| `docker-compose.yaml` | Bağımsız stack tanımı. |
| `.env.example` | Secret şablonu → `.env` olarak doldurun. |

## Kritik farklar (eski stack'e göre)

1. **Temiz veritabanı**: `scalpernew` DB'si boş başlar; migration'lar (013 dahil)
   ilk açılışta otomatik kurulur. Eski veri eski stack'te kalır.
2. **basePath yok**: `NEXT_BASE_PATH=""` → arayüz `https://scalpernew.erkanerdem.online/`
   kökünde; WS zaten kök `/ws`'e bağlanır (basePath WS sorunu burada doğmaz).
3. **İzolasyon**: servis adları (`backend`, `frontend`) compose proje adı
   `scalpernew` altında kendi ağındadır; konteyner adları `scalpernew-*` öneklidir.
   Eski stack'in `backend` servisiyle DNS çakışması IMKANSIZDIR.
4. **CORS** `https://scalpernew.erkanerdem.online`'a ayarlı.

## Coolify ile deploy (önerilen)

1. Coolify → New Resource → **Docker Compose** → repo: bu repo, **Compose file path:**
   `./scalpernew/docker-compose.yaml`
2. Environment Variables'a `.env.example` içindeki ZORUNLU alanları gir:
   `POSTGRES_PASSWORD`, `SCALPER_ADMIN_PASSWORD`, `SCALPER_SESSION_SECRET`,
   `LLM_ENCRYPTION_KEY` (örnek üretim komutları `.env.example` içinde).
3. Domain alanına `scalpernew.erkanerdem.online` yaz (TLS'i Coolify/Traefik sağlar;
   DNS'te bu alt alan adı sunucu IP'sine A kaydı olarak ekli olmalı).
4. Deploy. Backend sağlıklı olduktan sonra arayüz kökte açılır.

## Manuel deploy (VPS'te)

```bash
git clone <repo> && cd <repo>
cp scalpernew/.env.example scalpernew/.env   # doldur
docker compose -f scalpernew/docker-compose.yaml -p scalpernew up -d --build
```

(DNS: `scalpernew.erkanerdem.online` → sunucu IP; TLS için ayrıca Traefik/Caddy
yapılandırması gerekir — Coolify bunu otomatik yapar.)

## Doğrulama

```bash
docker compose -f scalpernew/docker-compose.yaml -p scalpernew ps
docker logs scalpernew-backend --tail 100      # migration + startup logları
docker logs scalpernew-gateway --tail 50
curl -s https://scalpernew.erkanerdem.online/health
```

## ECONNRESET teşhisi (eski stack'ten bağımsız)

Eski stack'teki `Failed to proxy http://backend:8004 → ECONNRESET` sorununun
kaynağı büyük olasılıkla eski backend konteynerinin çökme/donma döngüsüdür; bu
stack'e KOPYAYLA GEÇMEZse (temiz DB + fresh başlangıçla geçmesi muhtemel),
yeni stack'te `docker logs scalpernew-backend` çıktısı kök nedeni temiz gösterir.
Aşağıdaki komutlar her iki durumda da tanı için altın değerindedir:

```bash
docker inspect --format '{{.State.Health.Status}} OOM={{.State.OOMKilled}} restarts={{.RestartCount}}' scalpernew-backend
docker stats --no-stream
```
