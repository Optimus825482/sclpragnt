---
name: scalper-trade-manager
description: Paper-only, cost-aware scalping trade manager for Binance TR spot data.
---

# Scalper Trade Manager

Bu skill yalnızca paper-trading içindir; gerçek emir, anahtar veya canlı para kullanmaz.

## Karar sırası

1. Güncel public snapshot ve kapanmış mumları doğrula.
2. 5m setup'ı 15m ve 1h trendiyle teyit et.
3. Spread, orderflow, likidite, ATR kapasitesi ve round-trip maliyeti kontrol et.
4. Dirençte/aşırı alımda kovalamaca yapma; teyitli breakout veya pullback/retest bekle.
5. Sembol ve strateji geçmişinin net PnL, expectancy ve loss streak değerlerini kullan.
6. Son kapanıştan sonra guard/cooldown/re-arm hareketi tamamlanmadan tekrar giriş yapma.
7. Sadece backend'den gelen gerçek `BUY_SIGNAL` pozisyon açılışıdır; `BUY_BLOCKED` işlem değildir.

## Giriş setup'ları

- Trend pullback: bullish 15m/1h yapı, 5m geri çekilme, destek/retest, pozitif akış ve maliyet sonrası yeterli R:R.
- Breakout continuation: kapanmış mum breakout'u, hacim teyidi, spread/derinlik uygunluğu ve üst zaman dilimi uyumu.
- Mean reversion: yalnızca range rejiminde, destek yakınında, aşırı satıştan dönüş teyidiyle; trend ortasında kullanılmaz.

Tek bir indikatör sinyali giriş gerekçesi değildir. Açık mum, Bollinger üstü fiyat, negatif orderflow, geniş spread veya geçmişte tekrarlayan sembol kaybı varsa `watch/avoid` seç.

## Çıkış

Çıkış gerekçesi net olmalı: invalidation, stop, target, trailing veya model kararı. Maliyet sonrası PnL negatifken “küçük brüt kâr” başarılı trade sayılmaz. Kapanıştan sonra aynı sembolü otomatik yeniden alma; yeni hareket ve yeni setup bekle.

## Öğrenme

Her işlemden sonra komisyon sonrası sonuç, MAE/MFE, spread, volatilite, setup türü, rejim ve çıkış nedeni kaydedilir. Tek işlemle kural değiştirme. En az yeterli örnek, kronolojik walk-forward ve OOS kanıtı olmadan yeni kuralı aktif stratejiye terfi ettirme.

## Raporlama

Her karar için sembol, timeframe, setup, teyitler, invalidation, maliyet varsayımı, risk ve güven seviyesi yaz. Veri eksikse uydurma; `data_not_ready` veya `BUY_BLOCKED` raporla.
