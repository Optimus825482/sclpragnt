"""Sembol başına GÜNLÜK push sayacı: "bu coin için bugün N. bildirim" (2026-10-24).

Kural: bir coin hakkında giden HER web push (zaman dilimi, tarama türü, mod, kaynak
fark etmez) o coinin günlük sayacını bir artırır; bildirim başlığına ve payload'a
(`daily_count`) yazılır. Gün sınırı Europe/Istanbul 00:00'dır. Sayaç veritabanında
tutulur (`push_daily_counter`, migration 028) — süreç yeniden başlasa da sıfırlanmaz.

Sayım GERÇEK gönderim anında yapılır (`alerting.deliver_web_push`), tespit anında değil;
sessiz saatte ertelenen push kuyruktan çıkınca sayılır. Sembolsüz push'lar ("ALERT",
test, yönetici işlem bildirimi) sayılmaz.
"""
import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from app import database

logger = logging.getLogger("scalper.push_daily_counter")

ISTANBUL_TZ = ZoneInfo("Europe/Istanbul")

# Sayaç tutulmayan "sembol" değerleri: ertelenen alarm zarfı `symbol="ALERT"` taşır.
_NON_COIN_SYMBOLS = frozenset({"ALERT"})


def day_key(now: float | None = None) -> str:
    """Epoch → Europe/Istanbul takvim günü (YYYY-MM-DD); `monitoring._notify_day_key` ile aynı anahtar."""
    ts = time.time() if now is None else float(now)
    return datetime.fromtimestamp(ts, ISTANBUL_TZ).strftime("%Y-%m-%d")


def normalize_symbol(symbol) -> str | None:
    """Sayaç anahtarı: büyük harf, boşluk/alt çizgi yok (`BTC_TRY` → `BTCTRY`).

    TRY soneki KORUNUR: `monitoring._notify_daily_count` ve service worker da tam sembolle
    çalışır. Boş ya da coin olmayan değer (ör. "ALERT") → None (sayaç yok).
    """
    sym = str(symbol or "").strip().upper().replace("_", "").replace(" ", "")
    if not sym or sym in _NON_COIN_SYMBOLS:
        return None
    return sym


async def next_count(symbol, now: float | None = None) -> int | None:
    """Sembolün bugünkü sayacını artırıp yeni değeri döndürür; sembol sayılmıyorsa None.

    Veritabanı hatası ÇAĞIRANA fırlatılır: `deliver_web_push` yakalar ve sayaçsız gönderir
    (sayaç arızası push'u asla durdurmamalı).
    """
    sym = normalize_symbol(symbol)
    if sym is None:
        return None
    return await database.bump_push_daily_count(sym, day_key(now), now)


def counter_label(count: int) -> str:
    """Bildirim başlığına eklenen kısa Türkçe metin: `bugün 3. bildirim`."""
    return f"bugün {int(count)}. bildirim"
