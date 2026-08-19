# BB-MFI Geliştirme Adayları — Web ve Yerel Kanıt Notu

**Tarih:** 2026-08-19. Bu plan paper-only'dir; gerçek emir, anahtar veya
canlı para kapsam dışındadır.

## Problem tanımı

Son live-parity penceresinde aktif profil 53 kapanan işlemde `-267,04 TL`,
PF `0,440` ve `%3,011` azami düşüş üretti. Çıkışların 52'si BB-MFI v3 sinyal
çıkışıydı; 33'ü zararla kapandı. Sembol bazında en büyük net kayıplar SUI
(-45,96 TL), APT (-24,99 TL), ADA (-24,95 TL) ve AVAX (-20,88 TL) idi.
Bu, yalnız kazanma oranı değil, maliyet sonrası giriş/çıkış ve yeniden giriş
kalitesi problemidir.

## Dış araştırmadan çıkarımlar

1. Teknik kural sonucu eğitim döneminde olumlu görünse bile OOS'ta değişebilir;
   çok sayıda alternatif sınanıyorsa veri-taraması kontrolü gerekir. Hudson ve
   Urquhart bunu kripto teknik kurallarında doğrudan vurgular.
2. İşlem maliyeti ve uygulama sürtünmesi, tahmin edilebilir görünen sinyalin
   alınıp satılabilir bir sonuca dönüşmesini engelleyebilir. Kim ve Lim
   çalışması OOS ve sabit maliyet/uygulama zamanlaması ile değerlendirir;
   Rösch vd. efektif retail maliyetlerinin yaygın kıyaslardan yüksek
   olabileceğini bulur.
3. Kısa ufukta order-book dengesizliği bilgi taşıyabilir, ancak bu yalnız
   zaman damgalı ve doğru sıralı L2 akışında ölçülebilir. Bu nedenle geçmiş
   OHLCV replay'ine sonradan L2 filtresi eklemek look-ahead/proxy riski taşır.
4. Portföy devrini azaltan bir ceza/koruma OOS değerlendirmeye değerdir; bunu
   pozisyon boyutu veya keyfî optimizasyon yerine şeffaf cooldown/kayıp sınırı
   ile test etmek daha denetlenebilirdir.

Kaynaklar:

- Hudson & Urquhart, *Technical Analysis and Cryptocurrencies*:
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3387950
- Frömmel & Deprez, *Are Simple Technical Trading Rules Profitable in Bitcoin
  Markets?*: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4401552
- Kim & Lim, *From Predictability to Tradability*:
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7115197
- Rösch et al., *The Actual Retail Price of Crypto Trades*:
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6992598
- Binance WebSocket documentation (bookTicker, depth and kline semantics):
  https://developers.binance.com/en/docs/binance-spot-api-docs/web-socket-streams

## Önceliklendirilmiş adaylar

| Öncelik | Aday | Neden | Test türü | Terfi koşulu |
| --- | --- | --- | --- | --- |
| 1 | **Kayıp sonrası cooldown** | Aynı sembolde ardışık zayıf mean-reversion denemelerinin portföy devrini azaltabilir. | Mevcut replay'de `--symbol-loss-cooldown-hours 2`; baseline ile aynı üç OOS pencere ve maliyet stresi. | Toplam net PnL/PF iyileşmeli, işlem sayısı yeterli kalmalı, DD artmamalı. |
| 2 | **Aleyhe EMA/ATR çıkışı** | 52 sinyal çıkışının çoğu zarar; aleyhe trend devam ettiğinde sermayeyi daha erken serbest bırakmayı test eder. | `--adverse-ema-atr-exit-hours 1 --adverse-ema-atr-multiplier 1`; giriş mantığı değişmez. | En az iki bağımsız pencerede net/PF iyileşmesi ve daha iyi veya eşit DD. |
| 3 | **Daha erken düşüş-rejimi engeli** | BB-MFI long mean-reversion güçlü yönlü düşüşte ters yön riski taşır. | Önceden kaydedilmiş tek bir sıkılaştırılmış bear-pressure eşiği; filtre tek başına test edilir. | Kârlı işlemleri aşırı yok etmeden, en az iki pencerede kayıp/expectancy iyileşmesi. |
| 4 | **Order-book gölge skoru** | Canlı akışta mevcut spread, derinlik ve imbalance sinyal kalitesini açıklayabilir. | Davranış değiştirmez: her BUY_SIGNAL için tazelik, spread, depth, imbalance ve sonraki net PnL kaydı. | En az 100 kapanan paper sinyalinden sonra önceden sabitlenmiş eşik için OOS kanıtı. |
| 5 | **Üçlü mum/hacim/MFI teyidi** | Son 72 saatte DD'yi azalttı fakat sadece dört işlem üretti. | Yalnız gözlemde kalır; daha uzun, farklı rejimlerde replay/paper örneklemi. | Yeterli işlem sayısı ve birden fazla OOS penceresinde PF > 1, maliyet stresinde dayanıklılık. |

## Uygulama sırası

1. Önce aday 1 ve 2'yi **ayrı ayrı** aynı dondurulmuş live-parity profilde
   koştur; birlikte kombinasyon yapma.
2. Her aday için en az üç çakışmayan 72 saatlik pencere, komisyon/spread/
   slippage stres koşulu ve sembol/çıkış nedeni kırılımını raporla.
3. Sadece iki bağımsız pencerede pozitif iyileşen adayları kombinasyon testine
   al; başarısız adayları reddet.
4. Paralelde order-book gölge kaydını başlat. Geçmiş L2 bulunmadığından bu
   aday backtest sonucu diye etiketlenmez.

Bu sıra, mevcut replay'deki küçük örneklem nedeniyle eşik araması ve yanlış
pozitif üretme riskini azaltır.

## Aday 1 ve 2 sonuçları

Her aday aktif live-parity profilinden ayrı çalıştırıldı. 9--12 Ağustos
penceresinde hiçbir yaklaşım sinyal üretmediği için karşılaştırma yapılabilir
iki pencereye dayanır.

| Aday / pencere | Normal maliyet net PnL | PF | 2x spread+slippage net PnL | Karar |
| --- | ---: | ---: | ---: | --- |
| Baseline, son 72 saat | -267,04 TL | 0,440 | -342,84 TL | Referans |
| 2 saat kayıp cooldown, son 72 saat | -256,72 TL | 0,529 | -333,96 TL | Stres altında iyileşme yok |
| Baseline, önceki 72 saat | -125,13 TL | 0,166 | -165,33 TL | Referans |
| 2 saat kayıp cooldown, önceki 72 saat | -132,33 TL | 0,166 | -165,33 TL | Tutarsız / reddet |
| 1 saat aleyhe EMA/ATR, son 72 saat | -869,16 TL | 0,266 | çalıştırılmadı | Açık biçimde reddet |
| 1 saat aleyhe EMA/ATR, önceki 72 saat | -325,72 TL | 0,101 | çalıştırılmadı | Açık biçimde reddet |

EMA/ATR çıkışı son pencerede 160 ek erken çıkış ve 200 toplam işlem üretti;
maliyet 617,18 TL'ye yükseldi. Cooldown son pencerede 14, önceki pencerede
yalnız bir girişi engelledi. Bu sonuçlar kuralın genellenebilir bir iyileşme
olmadığını gösterir; iki aday da varsayılan paper yapılandırmasına alınmadı.

Maliyet stresi `--live-parity-cost-multiplier 2` ile yalnız spread ve
slippage iki katına çıkarılarak yapıldı; komisyon sabit kaldı. Her sonuçta
cüzdan mutabakat farkı 0,000002 TL'den küçüktür.

## Aday 3 sonucu: daha erken bear-pressure engeli

Önceden kaydedilmiş araştırma override'ı ADX eşiğini 50'den 30'a, `-DI - +DI`
farkını 25'ten 15'e ve 15 dakikalık düşüş eşiğini `%0,50`den `%0,25`e çekti.
Bu, güçlü kısa vadeli satışta daha çok BB-MFI long girişini engellemeyi amaçlar.

| Pencere | Baseline net PnL / PF | Bear-pressure v1 net PnL / PF | Karar |
| --- | --- | --- | --- |
| Son 72 saat | -267,04 TL / 0,440 | -244,70 TL / 0,492 | Tek pencere iyileşmesi yetersiz |
| Önceki 72 saat | -125,13 TL / 0,166 | -133,65 TL / 0,091 | Kötüleşti; reddet |
| Daha eski 72 saat | İşlem yok | İşlem yok | Bilgi sağlamaz |

Bu aday iki bağımsız pencerede tutarlı olmadığı için maliyet stresi veya aday
kombinasyonuna alınmadı. Aktif bear-pressure ayarları değişmedi.
