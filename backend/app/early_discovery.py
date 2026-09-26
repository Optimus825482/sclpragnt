"""Erken yükseliş keşfi (early discovery) — `!miniTicker@arr` beslemesi.

AMAÇ
----
24 saatlik top-gainer havuzu GERİDE KALIR: 24h penceresi çok uzun olduğu için
şu anda pump'a başlayan bir coin, yükselişinin ilk dakikalarında 24h sıralamasında
hâlâ görünmezdir (ör. günlük %24 yapan bir coin'in yanında ilk-dakika %0.8'lik
hareket sıralamada kaybolur). Tarama havuzu yalnız 24h sıralamasından beslenirse
pump'ın en kârlı ilk 1-3 dakikası kaçırılır.

Binance'ın `!miniTicker@arr` birleşik akışı bu boşluğu TEK bağlantıyla kapatır:
saniyede bir, borsadaki TÜM semboller için son fiyat ve kümülatif 24h quote
hacmini tek dizi hâlinde yayınlar. Bu modül diziyi yutar, sembol başına ~1 sn
örneklemeyle 1 dakikalık momentum (``return_1m_pct``) ve hacim patlaması
(``volume_burst``) hesaplar; velocity taraması ``top_candidates()`` çıktısını
aday havuza ekler (bu modülde havuza ekleme YOKTUR).

miniTicker ŞEMASI (tek satır)
-----------------------------
    {"e": "24hrMiniTicker", "E": 123456789, "s": "BTCTRY",
     "c": "950000.00",      # son fiyat (string)
     "o": "...", "h": "...", "l": "...", "v": "...",
     "q": "123456789.00"}   # 24h quoteVolume — KÜMÜLATİF

`q` 24 saatlik KÜMÜLATİF hacim olduğu için periyot hacmi q FARKI'dır (iki
ardışık örneğin q değeri arasındaki artış). UTC gün başında pencere sıfırlandığı
için q düşebilir; negatif fark 0 sayılır (hayali hacim üretilmez).

BELLEK
------
Sembol başına en fazla 120 fiyat örneği (2 dk × ~1 sn) ve 15 dakikalık hacim
geçmişi tutulur; yalnız `DISCOVERY_QUOTE_SUFFIX` (env, varsayılan "TRY") ekine
uyan semboller saklanır. 120 sn'den eski örnekler budanır, hiç örneği kalmayan
sembolün durumu tamamen düşürülür — sembol churn'ünde sızıntı oluşmaz.

ZAMAN
-----
Örnekleme zamanı `time.monotonic()` tabanlıdır (WS event ms'i DEĞİL, ALIM anı);
monotonik saat NTP sıçramalarından bağımsızdır. Testler yalnız modüldeki
``_now`` fonksiyonunu ikame ederek zamanı tam denetler.
"""
import os
import statistics
import time
from collections import deque

from app.config import config

# --- Eşikler ---------------------------------------------------------------
# config.py'YE DOKUNULMADI: kanonik tanımlar başka ajan tarafından config'e
# ekleniyor; burada getattr ile okunur, config'te yoksa bu varsayılanlar geçerli.
DEFAULT_MIN_RETURN_1M_PCT = 0.4
DEFAULT_MIN_VOLUME_BURST = 2.0
DEFAULT_QUOTE_SUFFIX = "TRY"

# --- Pencereler ------------------------------------------------------------
SAMPLE_WINDOW_SEC = 120.0   # sembol başına örnek ufku (2 dk × ~1 sn)
SAMPLES_MAXLEN = 120
RETURN_WINDOW_SEC = 60.0    # momentum + hacim penceresi
# 20 sn getiri penceresi (2026-09-26, "daha erken"): 1 dakikalık momentum'un
# daha kısa ufku — pump'ın ilk saniyelerindeki ivmeyi gösterir. Pulse (ham keşif
# yayını) ve fast-scan tetikleyicisi bu alanı okur; eşik monitoring/config'tedir.
RETURN_20S_WINDOW_SEC = 20.0
SAMPLE_AGE_MAX_SEC = 15.0   # son örnek bundan yaşlıysa aday gösterilmez
MINUTES_MAXLEN = 15         # dakikalık hacim geçmişi (dk)
MINUTE_MEDIAN_WINDOW = 10   # medyan taban son ~10 dk'dan alınır
# Medyan taban 0 ise (dakika geçmişi boş / önceki dakikalarda işlem yok) bölen
# bu tabana indirilir; sıfıra bölme olmaz ve yeni sembolde burst tanımlı kalır.
VOLUME_MEDIAN_FLOOR = 1.0

# sembol -> {"samples": deque[(ts, price, q)], "minutes": deque[(bucket, volume)]}
_state: dict = {}


def _now() -> float:
    """Monotonik saniye. Testler yalnız bu fonksiyonu ikame ederek zamanı kurar."""
    return time.monotonic()


def _quote_suffix() -> str:
    """Saklanacak sembol ekini çöz: env önce, sonra config, sonra varsayılan."""
    value = os.getenv("DISCOVERY_QUOTE_SUFFIX") or getattr(
        config, "DISCOVERY_QUOTE_SUFFIX", DEFAULT_QUOTE_SUFFIX)
    return str(value).upper()


def _reference_sample(samples: deque, cutoff: float):
    """~60 sn önceki fiyat örneği: momentum ve hacim farkı için baz.

    Pencere sınırının SOLUNDAKİ (cutoff'tan eski/yakın) son örnek döner —
    seyrek örneklemede bile "60 sn önceye göre" hesabı savunur (ör. 0. ve 61.
    saniyede iki örnek varsa baz 61 sn önceki örnektir; aksi hâlde baz son
    örneğin kendisi olurdu ve getiri yanıltıcı biçimde 0 çıkardı). Hiç sol
    örnek yoksa (sembol henüz 60 sn'den yeni) mevcut EN ESKİ örnek esas
    alınır: getiri/hacim daha kısa ufuk üzerinden ölçülür.
    """
    reference = None
    for sample in samples:  # deque en eskiden en yeniye sıralı (monotonik ts)
        if sample[0] <= cutoff:
            reference = sample
        else:
            break
    return reference if reference is not None else (samples[0] if samples else None)


def _baseline_minutes(entry: dict, now: float) -> list:
    """Şu anki (henüz dolmamış) dakika kovası hariç, son ~10 dk'nın hacimleri."""
    current_bucket = int(now // 60)
    values = [volume for bucket, volume in entry["minutes"] if bucket < current_bucket]
    return values[-MINUTE_MEDIAN_WINDOW:]


def _ingest_row(row, suffix: str) -> None:
    if not isinstance(row, dict):
        raise TypeError("miniTicker satırı dict değil")
    symbol = str(row.get("s") or "").upper()
    if not symbol or not symbol.endswith(suffix):
        return
    price = float(row.get("c") or 0)
    quote_volume = float(row.get("q") or 0)
    if price <= 0:
        return
    now = _now()
    entry = _state.get(symbol)
    if entry is None:
        entry = {
            "samples": deque(maxlen=SAMPLES_MAXLEN),
            "minutes": deque(maxlen=MINUTES_MAXLEN),
        }
        _state[symbol] = entry
    samples = entry["samples"]
    previous = samples[-1] if samples else None
    samples.append((now, price, quote_volume))
    # Pencere budama: 120 sn'den eski örnekler düşer. maxlen da sınırlar; age
    # budaması yayının seyreklediği/stall ettiği durumlarda ufku gerçekten
    # 2 dk'da tutar.
    while samples and (now - samples[0][0]) > SAMPLE_WINDOW_SEC:
        samples.popleft()
    # Kümülatif q → dakika hacmi fark. q düşüşü (UTC gün başı sıfırlaması) 0 sayılır.
    delta_q = 0.0
    if previous is not None and quote_volume > previous[2]:
        delta_q = quote_volume - previous[2]
    bucket = int(now // 60)
    minutes = entry["minutes"]
    if minutes and minutes[-1][0] == bucket:
        last_bucket, last_volume = minutes[-1]
        minutes[-1] = (last_bucket, last_volume + delta_q)
    elif not minutes or bucket > minutes[-1][0]:
        minutes.append((bucket, delta_q))


def ingest_mini_ticker(rows: list[dict]) -> None:
    """Bir `!miniTicker@arr` dizisini yut. HİÇBİR KOŞULDA exception fırlatmaz.

    Tek bozuk satır (eksik alan, sayıya çevrilemeyen fiyat/hacim, dict olmayan
    öğe) yalnız o satırın atlanmasına yol açar; diğer satırlar işlenir. Sembol
    filtresi (TRY eki) ve eşik mantığı bu modülde uygulanır; market_data ham
    diziyi olduğu gibi buraya geçirir.
    """
    try:
        batch = list(rows or [])
    except TypeError:
        return
    if not batch:
        return
    suffix = _quote_suffix()
    for row in batch:
        try:
            _ingest_row(row, suffix)
        except Exception:
            continue


def top_candidates(limit: int = 10) -> list[dict]:
    """Erken pump adayları: eşikleri geçen semboller, |getiri| büyükten küçüğe.

    Sembol başına:
      * return_1m_pct = son fiyat / ~60 sn önceki fiyat - 1 (yüzde)
      * volume_1m     = son ~60 sn'deki kümülatif q artışı
      * volume_burst  = volume_1m / max(medyan(son ~10 dk dakikalık hacimleri),
                                        VOLUME_MEDIAN_FLOOR)
    Filtreler: return_1m_pct >= DISCOVERY_MIN_RETURN_1M_PCT (0.4),
    volume_burst >= DISCOVERY_MIN_VOLUME_BURST (2.0) ve son örnek yaşı
    <= 15 sn. 2 dk'dır örnek gelmeyen sembolün durumu tamamen düşürülür.

    return_20s_pct (2026-09-26, "daha erken"): son fiyatın 20 sn önceki fiyata
    göre yüzdesi — pump'ın İLK saniyelerindeki ivme. `RETURN_20S_WINDOW_SEC`
    penceresinin solundaki örnek yoksa (sembol 20 sn'den genç / örnek aralığı
    seyrek) None döner; mevcut alanlar (return_1m_pct, volume_burst, ...)
    değişmeden kalır.

    DÖNÜŞ: [{"symbol", "return_1m_pct", "return_20s_pct", "volume_burst",
             "price", "sample_age_sec"}, ...] — en fazla `limit` adet.
    """
    min_return = float(getattr(config, "DISCOVERY_MIN_RETURN_1M_PCT", DEFAULT_MIN_RETURN_1M_PCT))
    min_burst = float(getattr(config, "DISCOVERY_MIN_VOLUME_BURST", DEFAULT_MIN_VOLUME_BURST))
    now = _now()
    cutoff = now - RETURN_WINDOW_SEC
    results = []
    for symbol in list(_state.keys()):
        entry = _state.get(symbol)
        if entry is None:
            continue
        samples = entry["samples"]
        while samples and (now - samples[0][0]) > SAMPLE_WINDOW_SEC:
            samples.popleft()
        if not samples:
            # 2 dk'dır örnek gelmemiş sembolün durumu tamamen düşer (sızıntı yok).
            _state.pop(symbol, None)
            continue
        last_ts, last_price, last_q = samples[-1]
        age = now - last_ts
        if age > SAMPLE_AGE_MAX_SEC:
            continue
        reference = _reference_sample(samples, cutoff)
        if reference is None:
            continue
        ref_price = reference[1]
        if ref_price <= 0 or last_price <= 0:
            continue
        return_pct = (last_price / ref_price - 1.0) * 100.0
        # 20 sn getiri penceresi: aynı `_reference_sample` mantığıyla, pencere
        # SOLUNDAKİ örnek baz, son örnek pay. `_reference_sample` seyrek
        # örneklemede EN ESKİ örneğe düşer; bu ufukta fallback istenmez —
        # 20 sn'lik sol örnek gerçekten yoksa (sembol pencereden genç /
        # örnekleme seyrek) alan None yayınlanır, eski örnekten yapay getiri
        # üretilmez.
        cutoff20 = now - RETURN_20S_WINDOW_SEC
        ref20 = _reference_sample(samples, cutoff20)
        if ref20 is not None and ref20[0] > cutoff20:
            ref20 = None
        return_20s = None
        if ref20 is not None and ref20[1] > 0:
            return_20s = round((last_price / ref20[1] - 1.0) * 100.0, 4)
        volume_1m = max(0.0, last_q - reference[2])
        baseline = _baseline_minutes(entry, now)
        median = statistics.median(baseline) if baseline else 0.0
        denominator = max(median, VOLUME_MEDIAN_FLOOR)
        burst = volume_1m / denominator if denominator > 0 else 0.0
        if return_pct < min_return or burst < min_burst:
            continue
        results.append({
            "symbol": symbol,
            "return_1m_pct": round(return_pct, 4),
            "return_20s_pct": return_20s,
            "volume_burst": round(burst, 4),
            "price": last_price,
            "sample_age_sec": round(age, 3),
        })
    results.sort(key=lambda row: abs(row["return_1m_pct"]), reverse=True)
    return results[:max(0, int(limit))]


def reset() -> None:
    """Tüm keşif durumunu temizler (testler için)."""
    _state.clear()
