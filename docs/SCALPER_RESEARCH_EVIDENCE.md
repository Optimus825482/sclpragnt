# Scalper Trade Manager Research Evidence

Bu belge yatırım tavsiyesi değildir; sistem paper-trading içindir. Amaç, LLM'nin işlem açma kararlarını kaynaklı ve denetlenebilir prensiplere bağlamaktır.

## Uygulamaya çevrilen sonuçlar

### 1. Net edge maliyetlerden sonra ölçülür

Komisyon, spread ve slippage hesaba katılmadan küçük brüt kârlar anlamlı değildir. Bu nedenle giriş kapısı `expected_net` ve sembol geçmişinin komisyon sonrası expectancy değerini kullanır. Küçük hedeflerde maliyetin risk bütçesini tüketebileceğine dair kripto intraday örnekleri vardır:

- [Volume Profile Mean Reversion Strategy with Tape Speed Confirmation](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6932998)

### 2. Spread ve orderbook işlem kalitesinin parçasıdır

Binance resmi dokümantasyonu piyasa verisi, endpoint ağırlıkları, rate limitleri ve orderbook akışının ayrı operasyonel kısıtlar olduğunu belirtir. Uygulama bu yüzden stale veri, spread, depth ve orderflow olmadan işlem açmaz:

- [Binance Spot REST API](https://developers.binance.com/en/docs/products/spot/rest-api)
- [Binance Developer Documentation](https://developers.binance.com/en/docs/introduction)

### 3. Tek timeframe sinyali yeterli değildir

Kısa vadeli momentum ve reversal davranışı piyasa ve zaman aralığına göre değişebilir; bu nedenle 5m sinyalin 15m/1h yönüyle teyit edilmesi, tek göstergeye dayalı girişten daha güvenli bir uygulama sözleşmesidir. Bu, kârlılık garantisi değil, yanlış rejimde giriş riskini azaltan bir filtredir:

- [Intraday Return Predictability in the Cryptocurrency Markets](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4080253)

### 4. Backtest seçimi overfitting'e açıktır

Çok sayıda parametreyi geçmiş veride seçmek, gerçek dışı performans ve zayıf geleceğe yol açabilir. Yeni setup'lar bu nedenle kronolojik walk-forward, zorunlu OOS, maliyet/stress ve yeterli örnek olmadan canlı paper giriş evrenine alınmamalıdır:

- [Determining Optimal Trading Rules without Backtesting](https://arxiv.org/abs/1408.1159)
- [Avoiding Backtesting Overfitting by Covariance-Penalties](https://arxiv.org/abs/1905.05023)
- [Interpretable Hypothesis-Driven Trading](https://arxiv.org/abs/2512.12924)

## Sistem sözleşmesi

Araştırma kaynakları tek başına “bu strateji kârlıdır” kanıtı sayılmaz. Runtime'da nihai karar sırası:

1. Public veri tazeliği ve kapanmış mum kontrolü
2. 5m setup + 15m/1h trend teyidi
3. Aşırı alım/direnç ve price-action kontrolü
4. Spread/orderflow/likidite/ATR kontrolü
5. Sembol/strateji loss streak ve net expectancy
6. Cooldown + dinamik ATR re-arm
7. Komisyon/slippage sonrası minimum net getiri
8. Sadece `BUY_SIGNAL` ile paper pozisyon açılması

Bu kuralların kanıtı `BUY_BLOCKED`, `LLM_REENTRY_BLOCKED`, `decision_logs.metadata`, trade geçmişi ve backtest OOS sonuçlarında tutulur.
