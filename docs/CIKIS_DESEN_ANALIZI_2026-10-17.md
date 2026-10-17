# LUNA Tipi Çıkışlar — Veri-Önce Desen Analizi (2026-10-17)

**Soru (kullanıcı önerisi):** Son 5 günün 5 dk mumlarında LUNA tipi (merdiven, sıçramasız) yükselişleri bul; çıkışın ilk
mumunda 5m / 3m / 1m gösterge anlık görüntülerini al; hangi göstergeler olaylarda birbirine yakın değer alıyor (desen);
bu desenleri daha önceki günlerde geriye dönük test et.

**Araçlar:** `backend/app/rescan/pattern_study.py` (olay dedektörü, 3m türetme, 127 özellik), `backend/scripts/breakout_pattern_study.py`
(olay madenciliği → anlık görüntüler → sıralama/desen → arka test), `backend/tests/test_pattern_study.py` (23 test).
Ham çıktılar `backend/work/pattern/` (gitignore); rapor tabloları bu klasöre kopyalandı: `docs/desen_2026-10-17/`.

## 0. Veri notları (önemli)
- Veritabanında **~21 gün** mum var (60 değil): 1m/5m/15m, 2026-09-26'dan. **3 dk mum yok**, 1 dk'dan türetildi (3 dk sınırına
  hizalı, yalnız eksiksiz kovalar). 1m verisi 16 Ekim 19:56'da bitiyor; LUNATRY'nin 17 Ekim 1m mumları Binance public kline ile yamalandı.
- Bazı sembollerde eksik 5m/1m satırları var (ör. LUNATRY 01:00–01:10); boşluklar düz mumla dolduruldu. Doldurmadan LUNATRY hiç olay çıkmıyordu.
- Eğitim penceresi: 12 Ekim → (4,8 gün). Doğrulama (OOS): 27 Eylül – 11 Ekim.

## 1. Olaylar (adım 1)
Tanım: 60 dk pencerede kapanış ≥ +%4, koşudaki 5m mumların ≥ %70'i yeşil, zirveden geri çekilme ≤ %1,5, tek mum ≤ %2,5,
24s quote ≥ 5M TRY; sembol başına 3 saatte bir olay; t0 = koşunun ilk mumu.

| pencere | olay | sembol | kazanç medyan | süre medyan |
|---|---|---|---|---|
| Eğitim (12 Ekim →) | 306 | 128 | %4,8 | 50 dk |
| OOS (27 Eylül – 11 Ekim) | 797 | — | — | — |

- 63 olay (%21) aynı dakikada, 15 Ekim 16:55'te başlıyor (piyasa geneli dalga); eğitim olaylarının %41'i 15 Ekim'de →
  **bağımsız örnek sayısı 306'dan çok daha küçük.** OOS'ta hiçbir 5 dk kovada 8'den fazla olay yok.
- LUNATRY bulundu: 17 Ekim 01:15, +%4,7, 35 dk (eksik satırlar yüzünden 01:05 yerine 01:15).
- Tam liste: `docs/desen_2026-10-17/events_full.md`.

## 2. Anlık görüntüler (adım 2)
t0'dan ÖNCE kapanmış mumlarla, 5m / 3m / 1m için ayrı ayrı 127 özellik: EMA7/20/50/99 oranları ve eğimleri, yelpaze skoru,
RSI14, MFI14, ATR%, Bollinger genişliği/%B, MACD hist ve eğimi, ADX/+DI/−DI, Aroon, linreg eğim 10/20, getiri 1/3/5/10,
hacim oranı, 24s quote, 24s aralık konumu, ardışık yeşil, yükselen dip sayısı, saat. Olay/taban medyan ve çeyrekleri,
AUC, standartlaştırılmış fark, IQR oranı ve FWER işaretiyle **üst üste** tablolar:
`docs/desen_2026-10-17/stack_5m.md`, `stack_3m.md`, `stack_1m.md`. (8 rastgele olayda RSI/MFI değerleri kanonik
`technical_analysis` fonksiyonlarıyla birebir doğrulandı.)

## 3. Desen analizi (adım 3) — eşleşmiş taban: aynı sembol, aynı gün, olay başına 40 rastgele an
- **t0'da "LUNA imzası" yok.** Olaylar küçük bir geri çekilmeden sonra başlıyor: 1m RSI medyanı olayda 38,7 / tabanda 48,7;
  1m MFI 27,9 / 47,1; fiyat 1m EMA7/EMA20'nin altında, %B düşük. Bunun bir kısmı tanım gereği (olay yerel dipten başlar).
- EMA yelpazesi ve RSI/MFI doygunluğu ancak **t0+15 dk**'da beliriyor (5m getiri(3) AUC 0,94) — bu süren hareketin tespiti, tahmin değil.
- Havuz tabanına karşı en güçlü ayırıcılar oynaklık özellikleri (ATR%, BB genişliği, 12 bar geri çekilme; AUC 0,79–0,85):
  olaylar zaten oynak sembollerde çıkıyor.
- **"Sıkı küme" yok:** 127 özelliğin yalnız 12'sinde olay/taban IQR oranı 0,8'in altında; çoğunda olay dağılımı tabandan daha geniş.
  FWER permütasyon eşiği 106/127 özelliği "anlamlı" buluyor; anlamlılık işlenebilirlik demek değil. 15 Ekim dışlanınca
  sıralama korunuyor (Spearman 0,96). Sıralamalar: `rank_t0_matched.md`, `rank_t0_pooled.md`, `rank_t15_*.md`, `tight_*.md`.

### Aday desenler
| desen | koşullar (VE) | recall (eğitim) | yanlış alarm (havuz) | 5-kat CV recall / YA |
|---|---|---|---|---|
| A ağaç d=2 @t0 | 1m px_ema20 ≤ −0,342 ∧ 1m ret3 ≤ −0,334 | %48,0 | %5,57 | %44,8 / %10,3 |
| B elle @t0 | 1m px_ema20 ≤ −0,016 ∧ 5m ret1 ≤ 0 ∧ 1m %B ≤ 0,466 | %71,6 | %38,65 | %68,3 / %36,5 |
| C ağaç d=3 @t0 | A ∧ 1m ret10 ≤ −0,82 | %36,9 | %2,54 | %38,2 / %8,3 |
| D ağaç d=3 @t0+15 | 5m ret3 > 1,414 ∧ 1m px_ema20 ≤ 2,634 | %69,6 | %1,43 | %68,0 / %4,9 |
| E seçici d=4 @t0 | 1m drawdown12 > 1,289 ∧ 5m ret1 ≤ −0,312 ∧ 5m ATR > 0,406 ∧ 5m BB ≤ 2,709 | %13,7 | %0,27 | %5,9 / %0,21 |
| F seçici d=4 @t0+15 | 5m ret3 > 1,907 ∧ 1m ret10 ≤ 4,398 ∧ 1m MACD hist > 0,120 | %45,1 | %0,37 | %33,5 / %0,26 |

CV katları 15 Ekim dalgasını paylaştığı için iyimser. Toplam 6 karşılaştırma.

## 4. Arka test (adım 4) — aynı ölçü: TP 1,5 / SL −3 / maliyet 0,225 / 60 dk / null3 şans tabanı
| | sinyal/gün | hit60@1,5 | hit−şans OOS | hit−şans eğitim | net60 OOS | trailing OOS | ≥+%4/60 dk: pay / şans |
|---|---|---|---|---|---|---|---|
| **Hız Avcısı (referans)** | 233 | %46,3 | **+3,7 pp** | +5,9 | −0,45 | −0,11 | %18,3 / %13,9 |
| A | 1519 | %21,5 | +2,9 | +1,7 | −0,19 | −0,10 | %3,7 / %3,2 |
| B | 4217 | %14,0 | +1,0 | +1,6 | −0,21 | −0,16 | %2,1 / %2,1 |
| C | 744 | %28,7 | **+3,7** | +5,4 | −0,20 | −0,09 | %5,7 / %5,1 |
| D | 479 | %33,5 | −0,7 | +2,9 | −0,44 | −0,22 | %10,5 / %9,1 |
| E | 132 | %29,7 | +2,5 | +4,5 | −0,19 | −0,08 | %4,4 / %4,5 |
| F | 201 | %42,9 | +1,5 | +5,4 | −0,47 | −0,10 | %17,2 / %14,0 |

- Tohum gürültüsü ≈ ±0,5–0,7 pp. net60 her hücrede negatif (t ≤ −6); trailing eğitimde C/E/F'de +0,01…+0,04 (t < 1), OOS'ta −0,08…−0,10.
- **Aşırı uyum:** eğitim → OOS hit−şans: C 5,4 → 3,7, E 4,5 → 2,5, F 5,4 → 1,5, D 2,9 → −0,7.
- **Seçicilik:** A–D günde 479–4217 sinyal; E/F Hız Avcısı hacminde (132–201/gün) ama farkları küçük.
- **Erkenlik:** Hız Avcısı olayların %82'sinde (OOS) t0'dan sonra 90 dk içinde aday üretiyor, medyan gecikme 25 dk. D ve F ondan medyan ~5 dk
  önce; F'de gerçek öncülük yok (%49 önce / %49 sonra). A/C/E "dip"te ateşliyor, koşu içinde şans düzeyinin altında yakalıyor.
- **LUNATRY:** D 01:20, F 02:00, A 02:05'te ateşledi; C ve E hiç. (Eğitim kümesinde; bağımsız kanıt değil.)

## 5. Sonuç
Veri-önce yolla da OOS'ta +4 pp şans farkını geçen ya da net pozitif olan desen çıkmadı. En iyi aday C (+3,7 pp) Hız Avcısı ile
aynı bantta; net −0,20, trailing −0,09. Bulunan "fark" çoğunlukla tanımın kendisi (dipten başlama) ve sembol oynaklığı.
**Hiçbirini canlıya almamak gerekiyor.** Önceki iki çalışmayla (merdiven, 4 dedektör) birlikte artık üç bağımsız yoldan aynı
sonuç: bu 21 günde fiyat+hacimden türeyen hiçbir erken-giriş kuralı Hız Avcısı'nın üstüne çıkmıyor ve hiçbiri maliyet sonrası kârlı değil.

Sıradaki makul deneyler (sırayla): (1) taker-alış hacmi / emir defteri gibi mumda olmayan veriyi journal'a almak;
(2) 60+ gün mum geçmişi (tek dönem sorunu); (3) C/F koşullarını Hız Avcısı adayı içinde bayrak olarak sınamak (önceki bayrak
denemesi olumsuzdu, bkz. docs/HA_OZELLIK_VE_ATR_HEDEF_2026-10-17.md).

## Sınırlar
Tek 21 günlük dönem; eğitim 4,8 gün, test zamanda geriye; etkin olay sayısı 306'dan küçük (15 Ekim dalgası); 127 özellik × 2 taban × 2 ofset
sıralandı, 6 desen denendi (çoklu karşılaştırma); t0 geriye bakışlı tanım; 1m/3m analizinde 299/306 olay tam; giriş gecikmesiz, aynı barda SL önce (kötümser).
