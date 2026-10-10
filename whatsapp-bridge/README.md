# WhatsApp Köprüsü (ScalperAgent V4)

ScalperAgent V4'ün **11:30 tarama raporunu** ve **saat başı takip tablosunu** bir
WhatsApp grubuna ileten küçük Node servisi. WhatsApp'ın gruba gönderen ücretsiz
resmi API'si olmadığı için WhatsApp Web protokolünü kullanan **Baileys**
(MIT, ücretsiz) kütüphanesiyle çalışır.

```
[backend]  --HTTP POST (iç ağ)-->  [whatsapp-bridge]  --> WhatsApp GRUBU
```

## Kurulum (Docker Compose / Coolify — önerilen)

Köprü, ana projenin `docker-compose.yaml` dosyasında **ayrı bir servis** olarak
tanımlıdır. Backend'e iç ağdan `http://whatsapp-bridge:3001` ile ulaşır ve
**dışarıya port açmaz** (internete kapalı, `traefik.enable=false`).

### 1. Ortam değişkenleri (Coolify paneli / kök `.env`)

```
WHATSAPP_NOTIFY_ENABLED=true          # 11:30 raporu aktif
WHATSAPP_HOURLY_ENABLED=true          # saat başı takip tablosu aktif
WHATSAPP_BRIDGE_KEY=<uzun-rastgele-anahtar>
WHATSAPP_GROUP_ID=                    # QR sonrası /groups ile bul, sonra doldur
```

`WHATSAPP_BRIDGE_URL` varsayılanı `http://whatsapp-bridge:3001` — compose içinde
otomatik ayarlanır, elle vermeye gerek yok.

### 2. Deploy et

```bash
docker compose up -d --build whatsapp-bridge backend
```

### 3. QR'ı okut (bir kez)

QR terminalde/logda çıkar ama konteynerde okumak zor olabilir; kolay yol:

```bash
# Sunucuda (veya Coolify terminalinden):
curl http://localhost:3001/qr        # ← köprünün HOST portu yoksa:
docker exec -it <whatsapp-bridge-konteyner> sh -c 'cat /dev/stdin' # yerine log:
docker compose logs -f whatsapp-bridge
```

En pratik: `docker compose logs -f whatsapp-bridge` ile ASCII QR'ı terminalde
görüp telefondan **WhatsApp > Ayarlar > Bağlı Cihazlar > Cihaz Bağla** ile okut.

> QR'ı tarayıcıda görmek isterseniz, geçici olarak köprüye host portu verin
> (`ports: ["3001:3001"]`), `curl http://SUNUCU_IP:3001/qr` açın, okuttuktan
> sonra portu geri kaldırın. Coolify'da kalıcı port açmayın.

### 4. Grup ID'sini bul ve `.env`'e yaz

```bash
docker exec <whatsapp-bridge> node -e "console.log('bkz /groups')"   # veya
curl http://localhost:3001/groups -H "X-Bridge-Key: SENIN_ANAHTARIN"
```

Çıkan `id` (ör. `1203630xxxxxxxx@g.us`) → `WHATSAPP_GROUP_ID` olarak Coolify'da
ayarla ve backend'i yeniden başlat.

## Yerel geliştirme (Docker olmadan)

```bash
cd whatsapp-bridge
npm install
cp .env.example .env      # BRIDGE_KEY + WHATSAPP_GROUP_ID
npm start
```

## `.env` örneği (yerel)

```
PORT=3001
BRIDGE_KEY=degistir-uzun-rastgele-anahtar
WHATSAPP_GROUP_ID=1203630xxxxxxxx@g.us
LOG_LEVEL=warn
```

## Uçlar

| Uç | Metot | Açıklama |
|----|-------|----------|
| `/status` | GET | Bağlantı durumu (connected), grup yapılandırıldı mı |
| `/qr` | GET | Bağlanmadan önce ASCII QR (konteynerde kolay okutma) |
| `/groups` | GET | Katıldığın gruplar (ID bulmak için) — `X-Bridge-Key` gerekir |
| `/send` | POST | `{ "message": "..." }` → gruba gönderir — `X-Bridge-Key` gerekir |

## ⚠️ Uyarı

Baileys **resmi olmayan** bir yöntemdir; WhatsApp Kullanım Şartları'na aykırı
olabilir ve otomasyon nedeniyle **hesap banı riski** taşır. Bu köprü günde
1 rapor + saat başı takip (~14 mesaj/gün) atar — düşük risklidir ama sıfır
değildir. Riski kabul etmiyorsanız alternatif: **Telegram bot** (resmi,
ücretsiz, grup destekli).

## Sorun giderme

- **Build hatası: `npm error syscall spawn git` / `enoent` (exit 254):** Baileys'in
  bağımlılığı `@whiskeysockets/libsignal-node` bir **git bağımlılığıdır**.
  `node:20-slim` imajında **git YOKTUR** → Dockerfile artık git + ca-certificates
  kurar ve `git+ssh` URL'lerini https'e çevirir (`insteadOf`). Bu düzeltme
  olmadan deploy bu satırda patlar.
- **QR çıkmıyor / bağlanmıyor:** `whatsapp_auth` volume'unu sil (Coolify >
  Storages / `docker volume rm`), yeniden başlat → yeni QR.
- **`/send` 503:** WhatsApp bağlı değil — logda `✅ WhatsApp bağlandı.` görmelisin.
- **`/send` 401:** `X-Bridge-Key`, köprüdeki `BRIDGE_KEY` ile uyuşmuyor.
- **Backend raporu göndermiyor:** backend env'inde `WHATSAPP_NOTIFY_ENABLED=true`
  ve `WHATSAPP_BRIDGE_URL=http://whatsapp-bridge:3001` olmalı; backend loglarında
  "WhatsApp" satırına bak.
