## 11:30 Tarama Raporunu WhatsApp Grubuna Gönderme (Baileys köprüsü)

### Mimari (iki parça)
Uygulama doğrudan WhatsApp'a bağlanmaz (mümkün ve güvenli değil). Bunun yerine:

```
[ScalperAgent backend]  --HTTP POST-->  [Baileys köprüsü (Node, kendi sunucunda)]
  11:30 taraması biter                    WhatsApp Web protokolü
  raporu biçimler                          → GRUBA mesaj atar
```

- **Baileys köprüsü:** Küçük Node servisi. Telefon bir kez QR ile bağlanır, oturum dosyada saklanır (tekrar QR gerekmez). `POST /send` alır, gruba gönderir. MIT lisanslı, ücretsiz.
- **Backend tarafı:** Yalnız bir HTTP POST atar. WhatsApp/Node bağımlılığı backend'e girmez → backend saf Python kalır.

### Teslim edilecekler

**1. `whatsapp-bridge/` (yeni klasör, Node servisi)**
- `index.js`: Baileys ile QR login + oturum kalıcılığı (`auth/` klasörü) + Express HTTP sunucusu:
  - `GET /status` → bağlı mı, grubun ID'si ne
  - `GET /groups` → katıldığı gruplar (grup ID'sini bulmak için)
  - `POST /send` `{message}` → yapılandırılmış gruba gönderir
  - Bir API anahtarı header'ı (`X-Bridge-Key`) ile basit koruma
- `package.json` + `README.md` (TR): `npm install && node index.js`, QR okutma, `.env` (`PORT`, `WHATSAPP_GROUP_ID`, `BRIDGE_KEY`)

**2. `backend/app/whatsapp_notify.py` (yeni modül)**
- `async def send_whatsapp(text) -> bool`: env `WHATSAPP_BRIDGE_URL` + `WHATSAPP_BRIDGE_KEY` + `WHATSAPP_GROUP_ID` okur; yapılandırılmamışsa **sessizce atlar** (fail-safe, mevcut davranış bozulmaz). `urllib` + `asyncio.to_thread` (mevcut `derivatives_service` deseni).
- `def format_scan_report(candidates, stats) -> str`: adayları **WhatsApp için okunur** metne çevirir (emoji + satır başı, ör. `📈 MINA/TRY  4,68 → hedef %3,8 | potansiyel %81`). Öncelik: momentum+sqeeze onaylılar (strategy=both) üstte, sonra potansiyel %'ye göre.

**3. `monitoring._daily_momentum_scan_once` kancası**
- Tarama + bildirim tesliminden SONRA: o turda bulunan adaylardan rapor metni üretilir, `send_whatsapp(...)` çağrılır. **Sadece 11:30 otomatik taraması** (sizin seçiminiz) — manuel "Tara" göndermez.
- Günlük tek mesaj (11:30). Hata olursa loglanır, tarama akışı **etkilenmez** (try/except).

**4. `config.py`** — env-kontrollü, varsayılan KAPALI:
```
WHATSAPP_NOTIFY_ENABLED=false          # ana anahtar
WHATSAPP_BRIDGE_URL=http://host:3001    # köprü adresi
WHATSAPP_BRIDGE_KEY=...                 # paylaşılan anahtar
WHATSAPP_GROUP_ID=...                   # grup ID (köprü /groups ile bulunur)
```

**5. Testler** — `send_whatsapp` fail-safe (yapılandırma yoksa False, hata fırlatmaz), rapor biçimlendirme (boş liste, sıralama), OFF'ta hiç çağrılmaması.

### Kurulum akışı (sizde)
1. Sunucuda `whatsapp-bridge/`'i çalıştır (`npm install && node index.js`), QR'ı telefondan okut.
2. `GET /groups` ile grup ID'sini al → `.env`'e yaz.
3. Backend `.env`: `WHATSAPP_NOTIFY_ENABLED=true` + köprü URL/key/grup.
4. 11:30'da rapor otomatik gruba düşer.

### Riskler (dürüstçe)
- **WhatsApp ToS:** Baileys resmi olmayan bir yöntemdir; otomasyon hesap banı riski taşır. Günde 1 mesaj düşük risklidir ama sıfır değildir.
- **Köprü çalışır durumda olmalı:** Uygulama sunucusundan farklı bir süreç; kapalıysa rapor gitmez (backend loglar, akış bozulmaz).
- **Telefon bağlantısı:** WhatsApp Web oturumu bazen yeniden QR ister (nadiren).
- Bu iş **backend'e WhatsApp bağımlılığı eklemez** (yalnız outbound POST), dolayısıyla mevcut testler/servis etkilenmez.