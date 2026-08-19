# BB-MFI Sinyal Kalitesi Araştırma ve Replay Notu

**Tarih:** 19 Ağustos 2026  
**Kapsam:** Paper-only; gerçek emir veya yatırım tavsiyesi değildir.

## Gözlem

- Yerel işlem geçmişi: 206 zenginleştirilmiş işlemde son kronolojik %20 test bölümü `-100.83 TL`, PF `0.885` üretti. Dolayısıyla geçmişte eğitimde iyi görünen basit MTF/ATR kuralları tek başına genellenmedi.
- Güncel, tamamlanmış 5 dakikalık Binance TR kamu mumları (18 sembol, 15 Ağustos 22:27 UTC–18 Ağustos 21:27 UTC, 1.151 mum/sembol): mevcut sinyal `-238.49 TL`, 37 kapalı işlem, PF `0.666`, azami düşüş `%2.736`.
- Aynı mumlar, aynı maliyet modeli ve sonraki mum açılışı dolumu ile hacim `>=0.8`, dip mumunda kapanış konumu `>=0.55` ve MFI artışı `>=0.5` birlikte kullanıldığında `+3.64 TL`, 4 kapalı işlem, PF `1.102`, azami düşüş `%0.553` üretti. 763 sinyal bu kurallardan biriyle engellendi.

Bu kısa örnek yalnızca adayın giriş kalitesini arttırabileceğini gösterir; dört işlem istatistiksel kanıt değildir. Ayrıca önceki bağımsız 7 günlük OOS denemesi aynı birleşik adayda `-76.62 TL`, PF `0.311` verdi. Bu nedenle varsayılanlar değiştirilmedi; parametreler Ayarlar ekranında paper-candidate olarak erişilebilir yapıldı.

## Araştırmaya dayalı öneriler

1. Yalnızca maliyet sonrası beklenen hareket round-trip maliyet eşiğini geçiyorsa giriş yap; küçük brüt kazançlar ücretlerle net zarara dönebilir.
2. Girişleri kapatılmış mum, hacim, dipten dönüş ve MFI dönüşüyle teyit et; bunu kesin kural değil paper adayı olarak izle.
3. Her aday için kronolojik walk-forward pencereleri, maliyet/spread stres testi, sembol ve çıkış nedeni ayrımı uygula. Eğitim dönemi sonuçları aktivasyon kanıtı değildir.
4. Tarihsel L2 derinlik mevcut olmadığı için likidite/spread sonuçlarını muhafazakâr varsayımla modelle; canlı paper sonuçlarında gerçek spread ve dolum sapmasını ayrıca kaydet.

## Dış kaynaklar

- Hudson ve Urquhart, teknik kurallarda veri-taraması ve işlem maliyeti kontrolünün gerekli olduğunu gösterir: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3387950
- Bysik ve Slepaczuk, maliyet eşiğiyle işlem seçiminin turnover'ı azaltıp bazı walk-forward kurulumlarında sonucu iyileştirdiğini raporlar: https://arxiv.org/abs/2606.00060
- Mroziewicz ve Slepaczuk, bağımsız OOS ve maliyet duyarlılığı kontrolünü vurgular: https://arxiv.org/abs/2602.10785
