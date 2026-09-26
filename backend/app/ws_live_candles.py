"""Canlı mum akışı (2026-09-16, grafik-canlı-düzeltmesi).

GRAFİK NEDEN CANLI GÜNCELLENMİYORDU (özet):
    Grafik sayfası mum verisini YALNIZCA doğrudan tarayıcı→Binance WS'ine
    (`wss://stream-cloud.binance.tr/...`) bağlıyordu. Bu adres browser'dan
    ERİŞİLEMEZ (backend aynı adrese sunucudan bağlanabiliyor ve "WS bağlı"
    görünüyor ama browser'dan TCP/TLS bağlantısı kurulamıyor → "WebSocket
    connection failed" console hatası). Bu yüzden mumlar backend'in kendi WS
    istemcisinden (`app/market_data.py`) alınıp bu kanal üzerinden yayınlanır.

İKİNCİ DÜZELTME — YALNIZCA KAPANMIŞ MUM YAYINLAMAK CANLI YAPMIYORDU
(2026-09-16, "grafik güncellenmiyor" tekrarı):
    İlk sürüm yalnızca KAPANMIŞ mumları yayınlıyordu (`candle["x"] == True`).
    Ama HTTP `/api/market-klines` son eleman olarak **oluşan** mumu verir ve
    kapanmış bir mumun açılış zamanı ondan her zaman KÜÇÜKTÜR. İstemcinin
    `setBars` kapısı (charts/page.tsx) yalnızca `bar.time === last.time`
    (güncelle) veya `bar.time > last.time` (ekle) durumunda resmi işler; küçük
    olanı "eski" sayıp DÜŞÜRÜR. Sonuç: canlı kanaldan gelen HER mum atılıyordu
    ve grafik yalnızca 10 sn'lik HTTP yoklamasıyla tazeleniyordu — yani "canlı"
    değil, 10 sn gecikmeliydi. Rozet yeşil yanıyordu (yanıltıcı).

    ÇÖZÜM: OLUŞAN mum da yayınlanır. Oluşan mumun açılış zamanı istemcinin son
    mumuyla AYNIDIR → `bar.time === last.time` → `series.update(...)` → mum
    gerçek zamanlı güncellenir. Bar kapandığında son hâli, yeni bar açıldığında
    `bar.time > last.time` ile EKLEME yolu işler. Frontend'de değişiklik gerekmez.

NEDEN YALNIZ "BAKILAN" ÇİFT YAYINLANIR:
    MarketData 70 sembol × 6 ufuk = ~420 kline stream'ine abone. Oluşan mumu
    hepsi için yayınlamak saniyede yüzlerce WS mesajı demekti ve bunların
    tamamı istemcide zaten süzülüp atılırdı. Bu yüzden yalnızca BİRİNİN
    görüntülediği `(sembol, ufuk)` çiftleri yayınlanır (`note_viewed`).
    Bu kayıt `/api/market-klines` uç noktasından beslenir — grafik zaten onu
    10 sn'de bir çağırdığı için TTL'li kayıt kendiliğinden tazelenir ve
    istemci tarafında HİÇBİR değişiklik gerekmez. Kimse bakmıyorsa (TTL
    dolduğunda) oluşan mum için TEK mesaj bile üretilmez → ek yük sıfır.

KULLANIMI (startup_market_warmup'tan otomatik):
    from app.ws_live_candles import start_live_candle_broadcast
    start_live_candle_broadcast(market_instance)
"""
from __future__ import annotations

import asyncio
import logging
import time

from app.state import market

logger = logging.getLogger("scalper.candles")

# BACKPRESSURE (Görev 11): `_publish` her kline olayında `create_task` ile
# ayrı bir yayın görevi doğuruyordu (25 olay/sn → görev patlaması). Yayın artık
# (a) eşzamanlı görev sayısı bir SEMAPHORE ile sınırlı, (b) `ws_runtime`
# tarafında istemci başına kuyrukta yığılıyor. Aşırı yükte en eski yayın
# düşürülür — ticker verisi zaten "en son" anlamında.
_PUBLISH_SEMAPHORE: asyncio.Semaphore | None = None
_PUBLISH_INFLIGHT = {"now": 0, "dropped": 0}


def _publish_semaphore() -> asyncio.Semaphore:
    """Semaphore event loop'a bağlı olduğu için ilk çağrıda üretilir."""
    global _PUBLISH_SEMAPHORE
    if _PUBLISH_SEMAPHORE is None:
        # Eşzamanlı yayın görevi tavanı: 25 olaviy saniyede işleyebilir,
        # ama olay anında 25 görev birden yaratılmaz.
        _PUBLISH_SEMAPHORE = asyncio.Semaphore(4)
    return _PUBLISH_SEMAPHORE


async def _broadcast_now(payload: dict) -> None:
    """Yayını semaphore sınırlarıyla gerçekleştirir (yavaş istemci izole)."""
    from app import ws_runtime
    async with _publish_semaphore():
        try:
            await ws_runtime.ws_manager.broadcast(payload)
        except Exception as exc:  # yayın asla dinleyiciyi düşürmemeli
            logger.debug("kline yayını başarısız: %s", exc)

# Kapanmış mum başına yayın (WS yeniden bağlanınca aynı mum tekrar gelebilir).
_last_closed_ms: dict[tuple[str, str], int] = {}
# Oluşan mumun geriye gitmemesi için son yayınlanan açılış zamanı.
_last_open_ms: dict[tuple[str, str], int] = {}
# Bakılan çiftlerde oluşan mumun yayın sıklığını sınırla (burst koruması).
_last_open_publish_at: dict[tuple[str, str], float] = {}

# Grafiğin görüntülediği çiftler: { (SEMBOL, ufuk): son görülme (monotonic) }.
# `/api/market-klines` her çağrıldığında tazelenir; TTL dolunca çift düşer.
_viewed_pairs: dict[tuple[str, str], float] = {}
VIEWED_TTL_SEC = 90.0
# Oluşan mum için çift başına en kısa yayın aralığı (sn).
MIN_OPEN_PUBLISH_GAP_SEC = 0.2
# Görev patlaması tavanı: aynı anda bu kadar çok yayın görevi yaşar (Görev 11).
_MAX_PUBLISH_INFLIGHT = 8


def _key(symbol, timeframe) -> tuple[str, str]:
    return (str(symbol or "").replace("_", "").upper(), str(timeframe or ""))


def note_viewed(symbol, timeframe) -> None:
    """Grafik bu (sembol, ufuk) çiftini istedi → canlı yayına al (TTL'li).

    `/api/market-klines/{symbol}?interval=...` uç noktasından çağrılır. Yan
    etkisi kasıtlı ve dar: YALNIZCA bu çiftin oluşan mumu yayınlanır. Ölü
    çiftler TTL dolunca sessizce düşer, temizlik gerekmez.
    """
    symbol_key, tf_key = _key(symbol, timeframe)
    if not symbol_key or not tf_key:
        return
    _viewed_pairs[(symbol_key, tf_key)] = time.monotonic()


def _is_viewed(key: tuple[str, str]) -> bool:
    seen = _viewed_pairs.get(key)
    if seen is None:
        return False
    if time.monotonic() - seen > VIEWED_TTL_SEC:
        _viewed_pairs.pop(key, None)
        return False
    return True


def _publish(key: tuple[str, str], bar: dict, closed: bool) -> None:
    """liveSocket'e tek mum mesajı yayınla (event loop yoksa sessizce atla).

    Görev patlaması (Görev 11): her kline için `create_task` çağrılıyordu.
    Artık eşzamanlı yayın görevleri bir semaphore ile SINIRLANIR; kuyruk
    dolduğunda en eski yayın düşürülür (`_PUBLISH_INFLIGHT` sayacıyla izlenir).
    Ticker verisi "en son" anlamında olduğu için düşen kare kaybı zararsızdır.
    """
    payload = {
        "type": "kline",
        "data": {
            "symbol": key[0],
            "timeframe": key[1],
            "time": int(bar.get("time") or 0),
            "open": float(bar.get("open", 0)),
            "high": float(bar.get("high", 0)),
            "low": float(bar.get("low", 0)),
            "close": float(bar.get("close", 0)),
            "volume": float(bar.get("volume", 0)),
            "closed": closed,
        },
    }
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # Event loop yok (thread konteksti) → yayın yapılamaz, sessiz geç.
        return
    if _PUBLISH_INFLIGHT["now"] >= _MAX_PUBLISH_INFLIGHT:
        _PUBLISH_INFLIGHT["dropped"] += 1
        return
    _PUBLISH_INFLIGHT["now"] += 1

    async def _runner():
        try:
            await _broadcast_now(payload)
        finally:
            _PUBLISH_INFLIGHT["now"] -= 1

    try:
        loop.create_task(_runner())
    except RuntimeError:
        _PUBLISH_INFLIGHT["now"] -= 1
        return
    except Exception as exc:
        _PUBLISH_INFLIGHT["now"] -= 1
        logger.debug("kline yayını atlandı: %s", exc)


def publish_stats() -> dict:
    """Yayın backpressure gözlemlenebilirliği."""
    return {"in_flight": _PUBLISH_INFLIGHT["now"],
            "dropped": _PUBLISH_INFLIGHT["dropped"],
            "max_in_flight": _MAX_PUBLISH_INFLIGHT}


def _on_bar(symbol: str, timeframe: str, bar: dict) -> None:
    """MarketData'dan gelen mumu (OLUŞAN veya KAPANMIŞ) liveSocket'e yayınla.

    Kapanmış mum: her mum için BİR kez (WS replay'inde tekrar yayınlanmasın),
    bakılıp bakılmadığından bağımsız — bar geçişini istemci hemen görsün.
    Oluşan mum: YALNIZCA bakılan çift için ve saniyede birkaç kez.
    """
    if not isinstance(bar, dict):
        return
    key = _key(symbol, timeframe)
    bar_time = int(bar.get("time") or 0)
    if not key[0] or not key[1] or bar_time <= 0:
        return

    if bar.get("closed"):
        if bar_time <= _last_closed_ms.get(key, 0):
            return          # aynı kapanmış mum tekrar geldi
        _last_closed_ms[key] = bar_time
        _publish(key, bar, closed=True)
        return

    if not _is_viewed(key):
        return              # kimse bu çifti görüntülemiyor → yayın üretme
    if bar_time < _last_open_ms.get(key, 0):
        return              # geriye giden mum (eski seriden) → yayınlama
    now = time.monotonic()
    if now - _last_open_publish_at.get(key, 0.0) < MIN_OPEN_PUBLISH_GAP_SEC:
        return              # burst koruması
    _last_open_publish_at[key] = now
    _last_open_ms[key] = max(bar_time, _last_open_ms.get(key, 0))
    _publish(key, bar, closed=False)


def start_live_candle_broadcast(market_instance=None) -> None:
    """MarketData örneğine bar dinleyicisini kaydet ve yayını başlat.

    `startup_market_warmup` içinden çağrılır; bağımsız bir döngü başlatmaz
    (MarketData kendi WS yakalayıcısı event loop'ta çalışır).
    """
    inst = market_instance or market
    inst.add_bar_listener(_on_bar)
    logger.info("Canlı mum akışı başlatıldı: MarketData bar dinleyicisi aktif")


# Modül importunda otomatik başlat (bağımsız kullanım için).
start_live_candle_broadcast()
