# MA kesişimi kombinasyon araması — birleşik özet (2026-10-21)

**Soru:** MA kesişimleri, bekleme süresi kısaltılıp en az %2 hedefle, hangi kombinasyonda kârlı olur? İşlem başına ortalama +%2 net veren bir kombinasyon var mı?

**Cevap:** Hayır. 90 günlük arşivde, 60 gün eğitim / 30 gün test ayrımıyla **yaklaşık 10,9 milyon kombinasyon** denendi (7 koşu). Hem eğitimde hem testte artı kalan en iyi kombinasyonlar işlem başına **+%0,3 ile +%0,9** arasında. Tek bir satır testte +%1,78 gösteriyor ama eğitimi +%0,70 ve n test 39; seçim gürültüsü sınırında. Hiçbir sağlam küme +%2'ye yaklaşmıyor.

## Koşular

Ortak: evren canlı sistem mantığı (aksi yazılmadıysa), giriş sinyal mumunun kapanışı, 1 dk mumlarla kötümser çıkış (aynı mumda stop ve hedef → stop), iz süren stop önceki mum tepesinden, gidiş-dönüş maliyet %0,275, sembol başına tek pozisyon. Giriş setleri: 4 TF (M5, M15, M30, H1) × 6 MA üçlüsü (7/20/99, 5/13/50, 9/21/55, 10/30/100, 3/8/21, 8/34/89) × 3 kesişim kuralı (kurdele, hızlı×orta, orta×yavaş) = 72. Filtre: 16 tekli + 120 ikili maske. Geçerlilik: n eğitim ≥ 60, n test ≥ 25.

| Koşu | Değişen boyut | Deneme | Eğitim medyanı | Eğitim en iyi 100'ün test medyanı / testte artı | En iyi sağlam (eğitim → test) |
|---|---|---:|---:|---|---|
| 1 | hedef 2–3, stop 1–4, tutma 30–240, iz süren 4 | 2 807 220 | −0,27% | −0,46% / 17 | H1 3/8/21 orta×yavaş, hedef 3, stop 4, 90 dk, StochRSI≤80 + MACD hist↑: +0,42% → +0,67% (n 73/42) |
| 2 | hedef 4–5 | 1 871 480 | −0,23% | −0,46% / 23 | M15 8/34/89 orta×yavaş, hedef 5, stop 1,5, 90 dk, gövde≥1%: +0,62% → +0,67% (n 66/42) |
| 3 | limit giriş kapanışın %0,5 altı (15 dk) | 702 036 | −0,28% | −0,26% / 23 | H1 5/13/50 kurdele, hedef 5, stop 2, 240 dk, ADX>25 + hacim≥1,5×: +0,76% → +0,69% (n 60/36) |
| 4 | limit giriş kapanışın %1 altı (15 dk) | 531 072 | −0,23% | −0,37% / 20 | M15 9/21/55 kurdele, hedef 5, stop 3, 60 dk, RSI<70 + gövde≥1%: +0,61% → +0,78% (n 77/41) |
| 5 | tutma 480 dk'ya, hedef 8'e, stop 6'ya kadar | 1 493 856 | −0,21% | −0,52% / 9 | M5 7/20/99 orta×yavaş, hedef 8, stop 4, 480 dk, gövde≥0,3% + yavaşa uzaklık≤1%: +0,84% → +0,86% (n 60/25) |
| 6 | evren: likitler içinde en çok düşen 50 | 2 751 960 | −0,27% | −0,33% / 2 | H1 10/30/100 kurdele, hedef 2,5, stop 4, 240 dk, ATR≥0,6% + saat 09–23: +0,39% → +0,41% (n 120/50) |
| 7 | evren: 24 sa hacmi ≥ 1M TL olan tüm çiftler (daraltılmış ızgara) | (koşu sürüyor) | | | |

Ayrıntılı tablolar: `MA_KESISIM_KOMBINASYON_ARAMA_90g_*.md` (aynı klasör).

## Neden +%2 çıkmıyor

- **Beklenti maliyet düzeyinde.** Her koşuda denemelerin eğitim medyanı −%0,21 ile −%0,28 arasında, yani kesişim girişinin brüt beklentisi ≈ 0 ve net ≈ −maliyet. Filtre ve çıkış ayarı dağılımın kuyruğunu seçer; bu seçim etkisi, 10 milyon denemede en iyi 100'ün testte ortalama eksi kalmasıyla (medyan −%0,26…−%0,52) görülüyor. Testte artı kalanların çoğu şans eseri; sağlam kümeler bile +%0,3…+%0,9.
- **Kısa tutma ile %2 hedef uyuşmuyor.** Tutma ≤ 60 dk ve hedef %2 ile eğitimde en iyi görünen kombinasyonların hepsi testte eksi (−%0,02 … −%0,55; koşu 1). Kısa sürede %2 hareketi yakalayan sinyal azınlıkta, geri kalanı süre dolumunda küçük zararla kapanıyor.
- **Daha uzun tutma ve büyük hedef ortalamayı +%0,9'a kadar çıkarıyor, daha ileri değil.** 480 dk ve %8 hedefle kazanma oranı %48–54; ortalamayı az sayıda büyük kazanç taşıyor, medyan işlem eksi. Bu, kullanıcının "süreyi kısaltma" isteğinin de tersi.
- **Limit giriş yardımcı ama sınırlı.** Kapanışın %0,5–1 altından dolum, dolan işlemlerde ortalamayı +%0,2 kadar iyileştiriyor; ama sinyallerin bir kısmı dolmuyor (en iyi uçuş sinyalleri geri çekilmediği için) ve sağlam en iyi yine +%0,6…+%0,8.
- **Evren değiştirmek yardımcı değil.** Düşenler evreninde en iyi sağlam +%0,4; eğitimin en iyi 100'ünden yalnız 2'si testte artı.
- **Tutarlı sinyal:** sağlam kümelerin çoğu hızlı×orta değil, **orta×yavaş** (ya da kurdele) kesişimi ve H1/M15 dilimi; yani daha geç, daha seçici giriş. Kazanma oranı yüksek (%55–85) olan kümelerde bile ortalama net küçük, çünkü hedef nadiren tam görülüyor ve iz süren stop kârın büyük kısmını geri veriyor.

## Kullanılabilir tek aday

H1 7/20/99 orta×yavaş + RSI 45–65 + ADX > 25, hedef 2–3%, stop 3%, tutma 180–240 dk, iz süren 1/0,5 (koşu 1). 8 komşu varyantı da iki dönemde artı; eğitim +%0,29…+%0,47, test +%0,28…+%0,35, kazanma %74–85, n 81/39. İşlem başına beklenti ≈ +%0,3 (pozisyon tutarına göre); 90 günde ~120 sinyal, yani ayda ~40 işlem. Canlıya alınacaksa önce paper'da ileriye dönük 30 gün izlenmeli.

## Araç

`backend/scripts/ma_cross_combo_search.py` (`--targets --stops --holds --universe live|liquid|decliners --pullback X --pullback-wait N`), evren önbellekleri `backend/work/ma_cross_search_cache_90g*.pkl`. Birim testleri `backend/tests/test_ma_cross_combo_search.py` (7 test).
