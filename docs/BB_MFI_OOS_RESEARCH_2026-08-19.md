# BB-MFI 72 Saatlik OOS Araştırması — 2026-08-19

Bu çalışma paper-only'dir; gerçek emir veya anahtar kullanılmadı. Veri kaynağı
Binance TR public REST 5m kapanmış mumlarıdır. Sinyal kapanmış mumda, dolum bir
sonraki mum açılışında; her iki yönde komisyon, varsayılan spread ve slippage
modellenmiştir. Tarihsel order-book/ticker olay sırası bulunmadığından sonuçlar
dolum garantisi değildir.

## Dondurulmuş baseline

Aktif BB-MFI v3 kuralları, 18 yapılandırılmış TRY sembolü, 10.000 TL ortak
cüzdan, %10 emir büyüklüğü, iki katman ve aktif bear-pressure/pyramid korumaları
ile çalıştırıldı. Her satır bağımsız, çakışmayan 72 saatlik cüzdandır.

| Pencere (UTC) | Net PnL | İşlem | PF | Maks. DD | Komisyon/maliyet |
| --- | ---: | ---: | ---: | ---: | ---: |
| 15 Ağustos 22:50 – 18 Ağustos 22:50 | -267,04 TL | 53 | 0,440 | %3,011 | 186,67 TL |
| 12 Ağustos 22:50 – 15 Ağustos 22:50 | -125,13 TL | 8 | 0,166 | %1,166 | 50,72 TL |
| 9 Ağustos 22:50 – 12 Ağustos 22:50 | 0,00 TL | 0 | — | %0,000 | 0,00 TL |

Her çalıştırmada cüzdan mutabakat farkı en çok 0,000005 TL idi.

## Aday: üçlü giriş teyidi

Araştırma override'ı: hacim oranı >= 0,80, mum kapanışı aralığının >= %55'i ve
MFI önceki kapalı muma göre >= 0,5 puan yükseliş. Portföy/maliyet kuralları
baseline ile aynıdır.

| Pencere (UTC) | Net PnL | İşlem | PF | Maks. DD |
| --- | ---: | ---: | ---: | ---: |
| 15 Ağustos 22:51 – 18 Ağustos 22:51 | +3,64 TL | 4 | 1,102 | %0,553 |
| 12 Ağustos 22:51 – 15 Ağustos 22:51 | 0,00 TL | 0 | — | %0,000 |
| 9 Ağustos 22:51 – 12 Ağustos 22:51 | 0,00 TL | 0 | — | %0,000 |

## Karar

**continue-testing**. Son pencere baseline'a göre belirgin iyileşmiş olsa da
yalnız dört kapanan işlem vardır ve önceki iki OOS penceresinde adayın işlem
sayısı sıfırdır. Bu nedenle varsayılan paper ayarları değiştirilmedi; canlıya
terfi yoktur. Kural dondurularak, farklı piyasa rejimlerinde yüzlerce yeni
paper işlemi ve maliyet stresi birikene kadar izlenmelidir.

Ham çıktılar: `backend/research-baseline-{0,72,144}h.json` ve
`backend/research-triple-confirm-{0,72,144}h.json`.
