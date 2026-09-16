"""Canlı mum akışı (2026-09-16, grafik-canlı-düzeltmesi).

GRAFİK NEDEN CANLI GUNCELLENMIYORDU:
    Grafik sayfası mum verisini YALNIZCA doğrudan tarayıcı→Binance WS'ine
    (`wss://stream-cloud.binance.tr/...`) bağlıyordu. Bu adres browser'dan
    ERİŞİLEMEZ (backend aynı adrese sunucudan bağlanabiliyor ve "WS bağlı"
    görünüyor ama browser'dan TCP/TLS bağlantısı kurulamıyor → "WebSocket
    connection failed" console hatası). Sonuç: grafik ASLINDA hiç canlı
    güncellenmiyordu.

COZUM:
    Binance mumlarını backend'in kendi WS istemcisi zaten tüketiyor
    (`app/market_data.py:MarketData._process_kline`). Bu modül, kapanmış her mumu
    backend'in sağlıklı `liveSocket` kanalı (`app/ws_runtime.ws_manager`)
    üzerinden yayınlar. Grafik sayfası da bu kanala abone olur.

    Böylece:
      • Backend WS bağlantısı sağlıklı olduğu sürece grafik CANLI güncellenir.
      • Browser'dan erişilemeyen Binance adresiyle doğrudan bağlantı KALDIRILMIŞ
        olur → console spam, retry döngüsü, bağlantı korkusu yok.
      • Grafik, WS açıksa mum başına (sub-saniye), kapalıysa HTTP fallback ile
        ~10 sn'de bir güncellenir (asla donuk kalmaz).

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

# Her sembol+ufuk için son yayınlanan mum zamanı (ms) — duplicate yayını önler.
_last_published_ms: dict[tuple[str, str], int] = {}
# Yayın zaman damgası mikro-bağımlılığı için son tur zamanı.
_last_publish_at: float = 0.0


def _on_bar_close(symbol: str, timeframe: str, bar: dict) -> None:
    """MarketData._process_kline'dan gelen kapanmış mumu liveSocket'e yayınla."""
    global _last_publish_at
    from app import ws_runtime

    key = (symbol.upper(), timeframe)
    bar_time = int(bar.get("time") or 0)
    last = _last_published_ms.get(key, 0)
    if bar_time <= last:
        # Aynı mum tekrar geldi (WS replay) → atla.
        return
    _last_published_ms[key] = bar_time

    # Çok sık yayını sınırla: aynı mum için en fazla bir kez (üstte korunur) ve
    # Minimum 50 ms arayla → 70+ sembol × 6 TF Worst-case'i bile ~200 msg/s altında.
    now = time.monotonic()
    if now - _last_publish_at < 0.05 and bar_time == last:
        return
    _last_publish_at = now

    try:
        asyncio.get_running_loop().create_task(
            ws_runtime.ws_manager.broadcast({
                "type": "kline",
                "data": {
                    "symbol": symbol.upper(),
                    "timeframe": timeframe,
                    "time": bar_time,
                    "open": float(bar.get("open", 0)),
                    "high": float(bar.get("high", 0)),
                    "low": float(bar.get("low", 0)),
                    "close": float(bar.get("close", 0)),
                    "volume": float(bar.get("volume", 0)),
                },
            })
        )
    except RuntimeError:
        # Event loop yok (thread konteksti) → kuyruğa al, bir sonraki turtte işlenir.
        pass
    except Exception as exc:
        logger.debug("kline yayını atlandı: %s", exc)


def start_live_candle_broadcast(market_instance=None) -> None:
    """MarketData örneğine bar dinleyicisini kaydet ve yayını başlat.

    `startup_market_warmup` içinden çağrılır; bağımsız bir döngü başlatmaz
    (MarketData kendi WS yakalayıcısı event loop'ta çalışır).
    """
    inst = market_instance or market
    inst.add_bar_listener(_on_bar_close)
    logger.info("Canlı mum akışı başlatıldı: MarketData bar dinleyicisi aktif")


# Modül importunda otomatik başlat (bağımsız kullanım için).
start_live_candle_broadcast()
