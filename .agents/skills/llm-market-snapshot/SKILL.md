---
name: llm-market-snapshot
description: Scan all configured symbols with fresh public market snapshots, rank bullish candidates, deeply analyze trend direction, phase and persistence, and produce Turkish paper-position suggestions. Use when Erkan asks for live market scanning, best upward symbols, trend duration, entry candidates, or a multi-symbol technical review.
---

# LLM Market Snapshot

## Amaç

Scalper, önce `scan_market_snapshots` ile bütün etkin sembolleri tarar; sonra yalnızca ilk adayları `deep_analyze_symbol` ile çoklu zaman diliminde inceler. Sonuç karar değil, veri destekli paper-trading adaylığıdır; canlı emir açılmaz.

## Zorunlu iş akışı

1. Taze tarama yap: Kullanıcı tek sembol istemediyse `scan_market_snapshots` çağrısını kullan. Varsayılan zaman dilimleri `1m,5m,15m,1h,4h,1d` olur.
2. Yukarı adayları filtrele: EMA hizası, ADX/DI, VWAP, momentum, rejim, hacim ve likiditeyi birlikte değerlendir. Tek göstergeyle aday seçme.
3. Derinleştir: En fazla 5 adayı `deep_analyze_symbol` ile incele. Trend yönü, rejim, trend fazı ve süre için eldeki mum zaman damgalarını kullan; zaman damgası yoksa süre uydurma.
4. Maliyet kontrolü: spread, derinlik, hacim, ATR ve komisyon etkisini ayrı raporla. Null/0/stale verileri bilinmiyor kabul et.
5. Sonucu Türkçe ve yapılandırılmış ver: sıralama, kanıtlar, karşı kanıtlar, trend yaşı, riskler, güven ve `paper_candidate`.

## Çıktı kuralları

Her adayda `symbol`, `selected_timeframe`, `trend_direction`, `regime`, `trend_phase`, `trend_age_or_unknown`, `bullish_evidence`, `bearish_evidence`, `liquidity_quality`, `volatility`, `data_gaps`, `confidence`, `paper_candidate` alanları bulunur. Fiyat hedefi, garanti, kesin kârlılık veya gerçek emir iddiası üretme. Araç sonucunda bulunmayan değeri tahmin etme.

`paper_candidate` yalnızca `watch`, `candidate`, `avoid` olabilir. `candidate` için en az iki bağımsız trend kanıtı, yeterli veri ve engelleyici olmayan likidite gerekir. `watch` karışık/eksik kanıttır; `avoid` zayıf trend, geç faz, kötü likidite veya stale veridir.

## Araç güvenliği

`scan_market_snapshots`, `deep_analyze_symbol`, `get_symbol_analysis`, `get_historical_klines`, `query_database` ve `read_only_sql` salt-okunurdur. Backtest araçları da canlı portföyü değiştirmez. SQL gerekiyorsa yalnızca SELECT/WITH SELECT ve dönen satırlara dayan. Araç hatasını kullanıcıdan saklama; bozuk JSON argümanını uydurmak yerine hata olarak raporla.
