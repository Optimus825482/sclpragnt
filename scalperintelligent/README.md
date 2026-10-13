# Scalper Intelligent Trade Systems — arayüz

Scalper Agent V4 için gerçek backend verilerine bağlı açık tema Next.js arayüzü. Ana ekran referans görselindeki üst menü, sol menü, yatay fırsat kartları, aktif hesap varlıkları, portföy özeti ve sağ Binance TR paneli düzenini izler.

## Sayfalar ve veri

- `/` — birleşik tarama adayları, kişisel favori fiyat bandı, Binance TR varlıkları/portföyü ve emir paneli.
- `/firsatlar` — güncel birleşik adaylar, kaynak uzlaşısı, açıklanabilir skorlar ve kullanıcıya özel kalıcı tarama geçmişi.
- `/grafik` — 1/2/4 bağımsız grafik paneli, teknik göstergeler ve canlı mum güncellemeleri.
- `/gecmis-islemler` — tarih seçilebilir Binance TR gerçekleşen spot dolumları; komisyon ve günlük gerçekleşen net K/Z.
- `/ayarlar` — profil, uygulama/ses/WhatsApp bildirimleri ve kullanıcı bazlı Binance TR anahtar yönetimi.

Oturum açmış kullanıcılar ana ekran veya fırsatlar sayfasından yetkileri dahilinde manuel salt-veri taraması başlatabilir. Tarama sonuçları kullanıcıya özel geçmişte saklanır; tarama bildirim göndermez, paper pozisyonu açmaz ve gerçek emir iletmez. Ekran yenilemeleri tek başına manuel tarama başlatmaz. Adayı emir paneline taşımak yalnızca sembol/tutar ve aday bağlamını doldurur; emir gönderimi değildir.

Binance API key/secret ayar ekranından kaydedilir ve backend tarafından şifreli saklanır. Emir paneli Binance TR gerçek alış/satış endpoint'lerini çağırabilir. Emir gönderimi için kullanıcı hesabı bağlı olmalı, sunucu tarafındaki gerçek işlem kapısı açık olmalı ve panelde ayrı son onay verilmelidir. Portföy/aktif varlık verisi hesap bağlanmadan gösterilmez. Gerçek emir türleri backend'in desteklediği işlemlerle sınırlıdır.

Bildirim tercihleri `/api/user/preferences` üzerinden saklanır; WhatsApp tercihi açık olduğunda telefon numarası istenir ve sunucudaki WhatsApp Bridge ayarına göre gönderim yapılır.

## Çalıştırma

```bash
cd scalperintelligent
npm install
# BACKEND_ORIGIN varsayılanı: http://127.0.0.1:8004
npm run dev      # http://localhost:3055
```

Üretim: `npm run build && npm start`. Next.js `/api/*` isteklerini sunucu tarafından `BACKEND_ORIGIN` adresine proxy'ler; tarayıcı ve oturum aynı origin'i kullanır.
