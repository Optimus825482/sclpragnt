# Güncel gösterge rehberi — dört kolun ortak özeti (2026-10-17)

Soru: Güncellenen TradingView rehberindeki 149 yeni (★) gösterge, tarama sistemlerini güçlendirir ya da ana tahmin motoruna yeni bir algoritma olarak girebilir mi?

**Karar: Hayır.** Dört bağımsız testin hiçbiri örneklem dışında, gerçekçi dolumla net pozitif bir sinyal, filtre ya da model vermedi. Canlıya bir şey alınmadı.

Ortak ölçü: seçim yalnız geçmiş blokta; değerlendirme üç 30 günlük blokta (B1 20 Tem–18 Ağu, B2 19 Ağu–17 Eyl, B3 18 Eyl–16 Eki); 60 sn gecikme, %0,15 kayma, bacak başına %0,1125 ücret; rastgele giriş tabanı.

| kol | ne test edildi | olay tahminine katkı (t0−10, AUC) | en iyi sinyal / filtre neti | karar |
|---|---|---|---|---|
| Sembol başı yeni göstergeler | ~100 gösterge: Squeeze, WaveTrend, QQE, UT Bot, Laguerre, Schaff, SMC/ICT (iFVG, Breaker, OTE, Turtle Soup), Wyckoff, formasyonlar, RVOL | 0,629 → 0,644 | −0,36 (rastgele −0,50) | hayır |
| Piyasa genişliği, göreli güç, zaman | EMA üstü yüzde, McClellan, A/D, BTC'ye/piyasaya göre güç, SMT, USDTTRY, saat/seans | +0,006'ya kadar | hiçbir kova pozitif değil | hayır |
| İşlem akışı + vadeli | balina/büyük işlem akışı, OI, L/S, fonlama, defter dengesizliği, vadeli primi | ≤ +0,004 | −0,30 (vadeli primi; rastgele −0,50) | hayır |
| Lorentzian sınıflandırıcı | jdehorty betiğinin nedensel kopyası + bizim hedefle eğitilen kNN, gradient boosting'e karşı | orijinal 0,50–0,53 | orijinal rastgeleden anlamlı kötü | hayır |

## Ortak bulgular

- **Bilgi hep aynı iki boyutta:** oynaklık genişlemesi ve yükselen rejim. İkisi de mevcut özelliklerde (ATR, EMA açıklığı) zaten var. Yeni göstergeler bunları başka biçimde yeniden ifade ediyor.
- **Hız Avcısı adayları için anlamlı tek eksen:** "fiyat zaten uzamışsa giriş daha kötü". Bu, isabeti değil neti iyileştirmeye çalışan filtrelerde tutarlı ama hiçbir blokta neti pozitife taşımıyor.
- **En tutarlı ham kenar vadeli primi** (perp fiyatı TRY spotun önünde): rastgeleye göre her blokta ~+0,2 puan, ama net ~−0,3. Canlıda küresel öncü-takipçi modülü olarak zaten var.
- **Lorentzian betiğinin etiketi** kaynakta geçmiş 4 barın tersi; "4 bar sonrası" niyeti uygulanmamış. İki yorum da test edildi, ikisi de sonuç vermedi. Bizim hedefle eğitilen sürüm gradient boosting'ten iyi değil.
- **Maliyet duvarı** gidiş-dönüş yaklaşık %0,53. En iyi brüt kenarlar %0,15–0,4 bandında kaldı.

## Raporlar

- `docs/GOSTERGE_REHBERI_V2_2026-10-17.md` — sembol başı yeni göstergeler
- `docs/GENISLIK_GORELI_GUC_ZAMAN_2026-10-17.md` — genişlik, göreli güç, zaman
- `docs/ISLEM_AKISI_VADELI_TAHMIN_2026-10-17.md` — işlem akışı ve vadeli
- `docs/LORENTZIAN_SINIFLANDIRMA_2026-10-17.md` — Lorentzian
- Veri: `docs/ISLEM_AKISI_GECMISI_2026-10-17.md`, `docs/VADELI_GECMIS_VERI_2026-10-17.md`
