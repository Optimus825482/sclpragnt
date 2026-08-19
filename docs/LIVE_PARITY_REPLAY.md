# 72 Saatlik Live-Parity Paper Replay

Bu araç gerçek emir göndermez. Aktif `BB_MFI_MEAN_REVERSION` ayarlarını bir
çalışma başında dondurur ve aynı `ScalpAnalyzer` BB-MFI sinyal fonksiyonunu,
ortak cüzdanı, pozisyon sınırını, katmanlamayı, stop/TP'yi ve komisyonu 72 saat
öncesinden başlayan tamamlanmış 5 dakikalık mumlarda uygular.

## Çalıştırma

```powershell
Set-Location D:\scalperagent_v4\backend
$env:PYTHONUTF8 = '1'
.\venv\Scripts\python.exe .\scripts\run_portfolio_backtest.py --live-parity-72h --output live-parity-72h.json
```

Tamamlanmış, çakışmayan önceki 72 saatlik OOS penceresi için bitişi geriye
kaydırın. Örneğin 72--144 saat önceki pencere:

```powershell
.\venv\Scripts\python.exe .\scripts\run_portfolio_backtest.py --live-parity-72h --live-parity-end-hours-ago 72 --output live-parity-oos-72h.json
```

`--live-parity-end-hours-ago` yalnız pencere zamanını değiştirir; aktif sembol,
ortak cüzdan, katmanlama, stop/TP, BB-MFI koruma filtreleri ve maliyet
varsayımlarını yine çalıştırma başında dondurur.

Maliyet dayanıklılığı için, sinyal ve portföy kurallarını değiştirmeden yalnız
dolum maliyetlerini çarpabilirsiniz:

```powershell
.\venv\Scripts\python.exe .\scripts\run_portfolio_backtest.py --live-parity-72h --live-parity-cost-multiplier 2 --output live-parity-cost-stress.json
```

Bu örnek varsayılan spread ve slippage'ı iki katına çıkarır; komisyon oranını
değiştirmez. Çıktı araştırmadır, canlı ayar değildir.

Çıktı; zaman penceresini, sembol listesini, dondurulmuş ayarları, veri
kalitesini, maliyet varsayımlarını, işlem/çıkış dağılımını, net PnL, PF,
drawdown ve cüzdan mutabakatını kaydeder. `replay_mode=live_parity_72h` yoksa
çıktı bir araştırma override'ıdır ve canlıyla eşdeğer sayılmamalıdır.

## Dolum ve veri sınırı

Sinyal yalnız kapanmış mumda hesaplanır; giriş bir sonraki mum açılışında,
komisyon + varsayılan spread/slippage ile modellenir. Binance TR'nin public
REST mumları geçmiş order-book derinliği ve ticker olay sırasını sağlamadığından
bu, karar mantığı ve portföy kısıtları açısından parity'dir; gerçekleşmiş
intrabar dolumların birebir yeniden üretimi değildir.

## Aday değişiklik akışı

1. Önce `--live-parity-72h` ile baseline üret.
2. Bir değişikliği ayrı bir araştırma override'ında çalıştır; aynı veri, sembol,
   maliyet ve açık-pozisyon mark-to-market kuralını koru.
3. Ayrı tarih pencerelerinde walk-forward/OOS ve maliyet stresi uygula.
4. Yeterli örneklemde net PnL, PF, drawdown ve mutabakat iyileşirse Ayarlar
   ekranından yalnız paper stratejisine uygula. Gerçek emir kapsam dışıdır.
