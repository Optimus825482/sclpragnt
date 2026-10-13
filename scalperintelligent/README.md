# Scalper Intelligent Trade Systems — arayüz

Scalper Agent V4 için gerçek backend verilerine bağlı açık tema Next.js arayüzü. Ana ekran referans görselindeki üst menü, sol menü, yatay fırsat kartları, aktif hesap varlıkları, portföy özeti ve sağ Binance TR paneli düzenini izler.

## Sayfalar ve veri

- `/` — birleşik tarama adayları, kişisel favori fiyat bandı, Binance TR varlıkları/portföyü ve emir paneli (emir defteri + SL/TP koruması).
- `/firsatlar` — güncel birleşik adaylar, kaynak uzlaşısı, açıklanabilir skorlar, kullanıcıya özel kalıcı tarama geçmişi, motor başarı paneli ve tarama geçmişi CSV dışa aktarma.
- `/grafik` — 1/2/4 bağımsız grafik paneli, teknik göstergeler ve canlı mum güncellemeleri.
- `/emirler` — Binance TR açık (bekleyen) emirleri: liste, durum, OCO grup bilgisi ve tek tıkla onaylı iptal.
- `/gecmis-islemler` — tarih seçilebilir Binance TR dolumları + CSV dışa aktarma, portföy performans analitiği (equity eğrisi, win rate, profit factor, max drawdown, expectancy) ve işlem günlüğü (journal) notları.
- `/alarmlar` — fiyat/percent alarm kuralları ve tetiklenen olaylar; kural oluşturma/silme yönetici yetkisi gerektirir.
- `/ayarlar` — profil, uygulama/ses/WhatsApp bildirimleri ve kullanıcı bazlı Binance TR anahtar yönetimi.

Oturum açmış kullanıcılar ana ekran veya fırsatlar sayfasından yetkileri dahilinde manuel salt-veri taraması başlatabilir. Tarama sonuçları kullanıcıya özel geçmişte saklanır; tarama bildirim göndermez, paper pozisyonu açmaz ve gerçek emir iletmez. Ekran yenilemeleri tek başına manuel tarama başlatmaz. Adayı emir paneline taşımak yalnızca sembol/tutar ve aday bağlamını doldurur; emir gönderimi değildir.

Binance API key/secret ayar ekranından kaydedilir ve backend tarafından şifreli saklanır. Emir paneli Binance TR gerçek alış/satış endpoint'lerini çağırabilir. Emir gönderimi için kullanıcı hesabı bağlı olmalı, sunucu tarafındaki gerçek işlem kapısı açık olmalı ve panelde ayrı son onay verilmelidir. Portföy/aktif varlık verisi hesap bağlanmadan gösterilmez. Gerçek emir türleri backend'in desteklediği işlemlerle sınırlıdır.

### Pozisyon koruması (SL/TP/OCO) ve emir defteri

Emir paneli, eldeki varlık için borsada bekleyen satış koruması kurar: `OCO` (SL+TP), `Sadece SL` veya `Sadece TP` modları backend'deki mevcut `/api/binance/set-sl-tp` yolunu kullanır. Hızlı doldurma butonları fiyat yüzdesinden TP/SL önerir; "Başabaş çek" stopu ortalama maliyete çeker; "Önceki emirleri iptal et" seçeneği Binance TR'nin bakiye kilidi gereksinimi içindir. Koruma emri de iki aşamalı onayla gönderilir. Otomatik trailing stop yalnızca paper motorunda çalışır; gerçek pozisyonda kâr büyüdükçe SL seviyesi elle yukarı taşınır. Emir defteri (DOM), seçili sembolün public alış/satış derinliğini ve spread'ini gösterir.

### Performans analitiği, işlem günlüğü ve kısayollar

`/gecmis-islemler` sayfasındaki performans bölümü, kapanan paper işlemlerden salt-okunur equity eğrisi ve kâr kalitesi metrikleri üretir (`/api/portfolio/equity-curve`). İşlem günlüğü notları kullanıcıya özeldir (`/api/journal`; `012_trade_journal` migration'ı) ve emir/pozisyon tarafı etkisi yoktur. Ana sayfa klavye kısayolları: `j/k` aday gezinme, `Enter` adayı panele aktarma (emir göndermez), `f` favori, `m` salt-veri tarama, `?` yardım penceresi.

Bildirim tercihleri `/api/user/preferences` üzerinden saklanır; WhatsApp tercihi açık olduğunda telefon numarası istenir ve sunucudaki WhatsApp Bridge ayarına göre gönderim yapılır.

## Çalıştırma

```bash
cd scalperintelligent
npm install
# BACKEND_ORIGIN varsayılanı: http://127.0.0.1:8004
npm run dev      # http://localhost:3055
```

Üretim: `npm run build && npm start`. Next.js `/api/*` isteklerini sunucu tarafından `BACKEND_ORIGIN` adresine proxy'ler; tarayıcı ve oturum aynı origin'i kullanır.
