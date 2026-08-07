# Scalper Trade Manager Policy

Bu politika yalnızca paper-trading içindir. LLM aday seçebilir ve plan önerebilir; pozisyon açma yetkisi backend'in deterministik kapılarından geçer.

## Giriş sözleşmesi

Bir LLM paper long işlemi ancak aşağıdaki kontroller başarılıysa açılabilir:

1. Sembol ve teknik veri güncel olmalı; en az 55 kapanmış mum bulunmalı.
2. Trend bearish olmamalı.
3. RSI, Stoch, MFI veya CCI aşırı alım sınırlarını aşmamalı.
4. Fiyat Bollinger üst bandında/üzerinde yeni giriş olarak kabul edilmemeli.
5. Spread `%0.15` üzerinde olmamalı.
6. Orderflow imbalance `-0.10` altında olmamalı.
7. Aynı sembolün aktif re-entry guard'ı olmamalı.
8. Sembol/strateji geçmişinde en az iki ardışık kayıp olmamalı.
9. En az dört geçmiş işlemde komisyon sonrası expectancy negatif olmamalı.
10. Likidite, bakiye, komisyon, slippage ve minimum net getiri kontrolleri geçmeli.

`BUY_BLOCKED` işlem değildir. Yalnızca gerçek `BUY_SIGNAL` paper pozisyon açıldığını gösterir.

## Çıkış sonrası davranış

LLM pozisyonu kapattığında backend sembol için varsayılan 30 dakikalık cooldown guard oluşturur. LLM kapanışı artık otomatik replenishment/yeniden giriş tetiklemez; aynı sembol veya başka aday ancak sonraki bağımsız taramada değerlendirilir. Cooldown bitince de giriş teknik ve tarihsel giriş kapılarından yeniden geçmelidir; cooldown tek başına giriş izni değildir. Ayrıca kapanıştaki ATR volatilitesine göre dinamik re-arm hareketi hesaplanır: taban `%0.5`, yüksek volatilitede en fazla `%2`.

## Öğrenme sözleşmesi

Her kapanan işlem komisyon sonrası PnL, maksimum olumlu/olumsuz hareket, kapanış nedeni ve sembol/strateji profiline katkı sağlar. Öğrenme çıktısı doğrudan eşik değiştirmez; önce gözlemlenir, yeterli örnek oluşunca aday kural olarak değerlendirilir. Bu, tek bir işlemin modeli aşırı uyarlamasını önler.

## Araştırma ve doğrulama

Yeni setup'lar yalnızca kronolojik walk-forward ve zorunlu out-of-sample sonuçları pozitif, maliyet sonrası ve makul drawdown ile doğrulanırsa aday olabilir. Tek bir sembolün geçmiş başarısı genel kârlılık kanıtı değildir.

## Kanıt kayıtları

Giriş reddedildiğinde `BUY_BLOCKED` ve nedeni kaydedilir. Kapanış sonrası kilitte `LLM_REENTRY_BLOCKED` kaydı oluşturulur. Bu kayıtlar UI ve veritabanı incelemesinde “neden işlem açılmadı?” sorusunu cevaplamak için kullanılmalıdır.
