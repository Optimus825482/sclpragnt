# Kombine Liste Kadansı — Kaçırma Ölçümü (15 gün veri) — 2026-10-12

**ARAŞTIRMA — kod değişikliği YOK, commit YOK.**

## Soru
Kullanıcı: "Radar taraması 30 sn'de bir ama yükseliş kombine listesi belirli aralıklarla
(~15 dk). Bu 15 dk'lık ızgara, arada yakalanan yükseliş adaylarını KAÇIRIYOR; kombine
taramayı da radar mantığıyla (daha sık / olay-güdümlü) çalıştırmak daha iyi olmaz mı?"

## Yöntem
`scripts/measure_list_lag.py` + genişletilmiş koşu. Gerçek radar adayları
(`velocity_candidates`, passes=true, **5.909 aday**, 2026-10-06 → 10-10) + 5m fiyatlar
(118 sembol). 15 dk'lık gönderim ızgarası simüle edildi: her aday o an açık slot'a girer;
**gecikme** (aday→slot) ve **gecikmede kaçan getiri** (aday fiyatı → slot fiyatı) ölçüldü.
5/10/15/20/30 dk ızgara taraması yapıldı.

## Bulgular

### Izgara boyutu taraması (5.909 aday)
| Grid | Ort. gecikme | ≥%2 kaçan | **Ort. kaçan getiri** | Hedefi çoktan görmüş |
|---|---|---|---|---|
| 5 dk | 2.8 dk | 7.8% | **−0.17%** | 5.6% |
| 10 dk | 5.3 dk | 8.5% | **−0.20%** | 6.3% |
| **15 dk** | **7.8 dk** | **8.8%** | **−0.23%** | 6.4% |
| 20 dk | 10.4 dk | 10.9% | **−0.29%** | 7.6% |
| 30 dk | 15.3 dk | 9.5% | **−0.34%** | 7.1% |

### KRİTİK BULGU: gecikmede "kaçan" getiri NEGATİF
15 dk ızgarada, aday→slot beklemesinde fiyat ortalama **−0.23%** (medyan −0.256%).
Yani liste beklerken fiyat ortalama olarak **düşüyor**, yükselmiyor. Kaçırma basitçe yok.

- Dağılım: p10 −2.43%, p90 +1.80% — iki yanlı, ortalaması hafif negatif.
- **Yükselip kaçan:** adayların %42'si (yarıdan AZ).
- Aday anında son 15 dk getirisi zaten +0.19% (med +0.31%) → **hareket aday yaratıldığında
  büyük ölçüde olmuş**; sonraki 15 dk ortalama geri çekilme.
- Gün-gün tutarlı: gün732 (n=4178) −0.314%, gün733 (n=1669) −0.065%. Negatif her gün.

### Neden ilk (küçük) örneklem yanıltıcıydı
İlk koşu 62 aday/19 sembolle +1.18% "kaçan" gösterdi — o **şanslı bir dilim**di. 5.909
adayla işaret negatife döndü. Ders: dar örneklemle kadans kararı verilemez.

## Değerlendirme (kullanıcının önerisi hakkında)
Kullanıcının **gözlemi kısmen doğru:** yükseliş adayları da radar gibi 30 sn'de bir
*taranıyor* (`_run_rising_scan`, monitoring loop), ama WhatsApp **kombine listesi** 15 dk'da
bir gidiyor; ikisi kopuk kadanslarda. Ancak **çıkarımı (kaçırıyoruz) veriyle desteklenmiyor:**

1. **Ortalama kaçan getiri negatif** → 15 dk beklemek fiyatı kaçırmıyor; aksine adaylar
   ortalamada geri çekiliyor (yükseliş adaylarının bilinen doğası: geç keşif → geri çekilme).
2. **≥%2 kaçan yalnız ~%9** ve ızgarayı 30 dk'ya çıkarmak bunu sadece %9.5'e taşıyor —
   yani kadansı değiştirmenin etkisi küçük.
3. Daha sık liste (5 dk) "kaçanı" −0.17%'ye indiriyor ama yine negatif; **kâr artışı yok**,
   yalnız WhatsApp trafiği ~3× artar.

## KARAR
**Kadansı sıklaştırmak gerekçesiz.** Veri, "15 dk ızgara yükselişleri kaçırıyor" iddiasını
desteklemiyor: gecikmede ortalama getiri negatif, kaçan adayların çoğu zaten geri çekiliyor,
ve ızgara boyutu sonucu marjinal etkiliyor. Kombine listeyi radar kadansına (30 sn) çekmek
**fayda sağlamaz**, sadece bildirim gürültüsü üretir.

**Öneri:** Kadans aynı kalsın (15 dk liste / 5 dk durum). Eğer "erken haber" isteniyorsa
doğru kaldıraç kadans değil, **aday kalitesi/erken keşif** (hareket olmadan önce yakalama) —
ki onu 8 turda ölçtük ve mevcut veriyle mümkün değil.

## Yeniden üretim
```
python backend/scripts/measure_list_lag.py --days 5 --list-min 15
```
