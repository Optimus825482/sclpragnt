# WhatsApp Köprüsü (ScalperAgent V4)

Bu küçük Node servisi, ScalperAgent V4'ün **11:30 günlük tarama raporunu** bir
WhatsApp grubuna iletir. WhatsApp'ın gruba gönderen ücretsiz resmi API'si
olmadığı için WhatsApp Web protokolünü kullanan **Baileys** (MIT, ücretsiz)
kütüphanesiyle çalışır.

```
[ScalperAgent backend]  --HTTP POST-->  [bu köprü]  --> WhatsApp GRUBU
```

## Kurulum

```bash
cd whatsapp-bridge
npm install
cp .env.example .env      # sonra .env'i düzenle
npm start
```

İlk çalıştırmada terminalde **QR kod** çıkar. Telefondan:
**WhatsApp > Ayarlar > Bağlı Cihazlar > Cihaz Bağla** → QR'ı okut.
Oturum `auth/` klasörüne kaydedilir; bir daha QR gerekmez (nadiren yeniler).

## Grup ID'sini bulma

Köprü çalışırken (bağlandıktan sonra):

```bash
curl http://localhost:3001/groups -H "X-Bridge-Key: SENIN_ANAHTARIN"
```

Çıktıdaki `id` alanı (ör. `1203630xxxxxxxx@g.us`) senin grup ID'nidir. Bunu
`.env` içindeki `WHATSAPP_GROUP_ID`'ye yaz ve köprüyü yeniden başlat.

## `.env` örneği

```
PORT=3001
BRIDGE_KEY=uzun-rastgele-bir-anahtar
WHATSAPP_GROUP_ID=1203630xxxxxxxx@g.us
LOG_LEVEL=warn
```

## Backend tarafı

Backend `.env`'ine ekle:

```
WHATSAPP_NOTIFY_ENABLED=true
WHATSAPP_BRIDGE_URL=http://127.0.0.1:3001
WHATSAPP_BRIDGE_KEY=uzun-rastgele-bir-anahtar     # köprüdeki BRIDGE_KEY ile AYNI
```

Backend sadece 11:30 otomatik taramasından sonra tek bir POST atar:
`POST {WHATSAPP_BRIDGE_URL}/send` → `{ "message": "<rapor>" }`.

## Uçlar

| Uç | Metot | Açıklama |
|----|-------|----------|
| `/status` | GET | Bağlantı durumu + yapılandırılmış grup |
| `/groups` | GET | Katıldığın gruplar (ID bulmak için) — `X-Bridge-Key` gerekir |
| `/send` | POST | `{ "message": "..." }` → gruba gönderir — `X-Bridge-Key` gerekir |

## ⚠️ Uyarı

Baileys **resmi olmayan** bir yöntemdir; WhatsApp Kullanım Şartları'na aykırı
olabilir ve otomasyon nedeniyle **hesap banı riski** taşır. Bu köprü günde
**1 kez** (11:30 raporu) mesaj atar — bu düşük risklidir ama sıfır değildir.
Riski kabul etmiyorsan alternatif: Telegram bot (resmi, ücretsiz, grup destekli).

## Sorun giderme

- **QR çıkmıyor / bağlanmıyor:** `auth/` klasörünü sil, yeniden başlat.
- **`/send` 503:** WhatsApp bağlı değil — terminalde `✅ WhatsApp bağlandı.` görmelisin.
- **`/send` 401:** `X-Bridge-Key` köprüdeki `BRIDGE_KEY` ile uyuşmuyor.
- **Mesaj gitmiyor ama 200 dönüyor:** Grup ID yanlış olabilir; `/groups` ile teyit et.
