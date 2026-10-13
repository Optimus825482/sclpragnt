# Scalper Intelligent Trade Systems — arayüz

Scalper Agent V4 için gerçek backend verilerine bağlı açık tema Next.js arayüzü. Ana ekran referans görselindeki üst menü, sol menü, yatay fırsat kartları, aktif hesap varlıkları, portföy özeti ve sağ Binance TR paneli düzenini izler.

## Sayfalar ve veri

- `/` — birleşik radar fırsatları (`/api/monitoring/state`, boşsa `/api/daily-rising/state`), sinyal kaynak etiketleri, Binance TR varlık tablosu, portföy özeti ve gerçek market emir paneli.
- `/firsatlar` — anlık aday/ısınan/nabız kayıtları ve sayfalı tarama bildirimi geçmişi; her adayda üreten sistem etiketleri.
- `/gecmis-islemler` — tarih seçilebilir Binance TR gerçekleşen spot dolumları; komisyon ve günlük gerçekleşen net K/Z.
- `/ayarlar` — profil, uygulama/ses/WhatsApp bildirimleri ve kullanıcı bazlı Binance TR anahtar yönetimi.

Fırsat görünümü master monitoring/radar yanıtındaki konsolide adayları ve kaynaklarını kullanır; tarama POST ile tetiklenmez. Böylece ekran yenilemeleri strateji tarama veya paper otomasyon yan etkisi üretmez.

Binance API key/secret ayar ekranından kaydedilir ve backend tarafından şifreli saklanır. Emir paneli Binance TR gerçek market alış/satış endpoint'lerini çağırır. Emir gönderimi için kullanıcı hesabı bağlı olmalı ve sunucu tarafındaki gerçek işlem kapısı açık olmalıdır. Portföy/aktif varlık verisi hesap bağlanmadan gösterilmez. Bu panel yalnızca MARKET emirlerini etkinleştirir; Limit ve Stop-Limit görselde devre dışı bırakılmıştır.

Bildirim tercihleri `/api/user/preferences` üzerinden saklanır; WhatsApp tercihi açık olduğunda telefon numarası istenir ve sunucudaki WhatsApp Bridge ayarına göre gönderim yapılır.

## Çalıştırma

```bash
cd frontend-odak
npm install
# BACKEND_ORIGIN varsayılanı: http://127.0.0.1:8004
npm run dev      # http://localhost:3055
```

Üretim: `npm run build && npm start`. Next.js `/api/*` isteklerini sunucu tarafından `BACKEND_ORIGIN` adresine proxy'ler; tarayıcı ve oturum aynı origin'i kullanır.
