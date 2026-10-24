"""GÜNÜN İLK BİLDİRİMİ izleyicisi (2026-10-25; migration 029, tablo `daily_first_notification`).

Kural: her sembol için Europe/Istanbul takvim gününün İLK bildirimi (push denenmiş: `sent_via_push`
OR `push_attempted` — `daily_seq` ile aynı "hangi bildirim sayılır" kuralı) kaydedilir: an + bildirim
fiyatı. O andan gün sonuna (23:59:59 Europe/Istanbul) kadar 1 dk mumlarla izlenir:

* ``mfe_pct``: ilk fiyattan en yüksek ``high``'a yükseliş (%); **>= 0** (yükseliş hiç olmadıysa 0).
  ``mfe_ts``: o mumun açılış anı (epoch sn). Eşitlikte İLK görülen tepe korunur.
* ``mae_pct``: ilk fiyattan en düşük ``low``'a düşüş (%); **<= 0, NEGATİF SAKLANIR** (örn. -2.35 =
  "%2.35 maksimum düşüş"; düşüş hiç olmadıysa 0). ``mae_ts``: o mumun açılış anı.

Mum penceresi `routers.velocity._post_signal_window` ile AYNI sözleşmeyi izler: bildirim anını İÇEREN
yarım mum HARİÇ (açılışı bildirim anına eşit/büyük mumlar), gün sonundan sonra açılan mumlar HARİÇ.
Mumlar `binance_tr_public.klines` ("1m") ile çekilir; hız sınırı / soğuma o modülün içindedir
(semafor + ağırlık bütçesi + 429 penceresi), burada ek koruma yoktur. Sembol başına hata diğerlerini durdurmaz.

Artımlı izleme: her turda ``max(first_ts, last_tracked_ts)`` → ``min(now, gün sonu)`` aralığı çekilir ve
mevcut MFE/MAE ile birleştirilir (``fold_excursions``). ``last_tracked_ts`` işlenen SON mumun açılış anıdır;
o mum bir sonraki turda (yarım olabileceği için) yeniden çekilir — maksimum/minimum monoton olduğu için zararsız.
Gün sonu geçince (+ kısa tampon) son tur koşar ve ``finalized=true`` yazılır.
"""
import asyncio
import logging
import time
from datetime import datetime, timedelta

from app import database
from app.push_daily_counter import ISTANBUL_TZ, day_key, day_start, normalize_symbol

logger = logging.getLogger("scalper.daily_first_notification")

LOOP_INTERVAL_SEC = 300.0
CANDLE_INTERVAL = "1m"
CANDLE_MS = 60_000
KLINES_LIMIT = 1000
# Gün sonundan sonra son mumun (23:59) kapanması için beklenen tampon.
FINALIZE_GRACE_SEC = 120.0
# Açılışta ilk turu geciktir (startup patlaması bitsin; diğer döngülerle aynı desen).
STARTUP_DELAY_SEC = 60.0


def day_bounds(key: str) -> tuple[float, float]:
    """`YYYY-MM-DD` → (gün başı 00:00:00, gün sonu 23:59:59) epoch saniye, Europe/Istanbul."""
    start_local = datetime.strptime(key, "%Y-%m-%d").replace(tzinfo=ISTANBUL_TZ)
    next_local = (start_local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return start_local.timestamp(), next_local.timestamp() - 1.0


def previous_day_key(now: float | None = None) -> str:
    """Şu anki Istanbul gününden bir önceki günün anahtarı."""
    return day_key(day_start(now) - 3600.0)


def fold_excursions(candles, first_price: float, first_ts: float, day_end_ts: float,
                    state: dict | None = None) -> dict | None:
    """Mumları mevcut MFE/MAE durumuyla birleştir (SAF fonksiyon).

    `candles`: Binance kline satırları [açılış_ms, açılış, yüksek, düşük, kapanış, ...].
    Sayılan mumlar: açılışı >= first_ts VE açılışı <= day_end_ts. `state` (önceki tur) verilirse
    önceki tepe/dip ve zamanları korunur; yeni mum yalnız KESİN olarak daha iyiyse yazar.
    Hiç sayılacak mum yoksa ve state de yoksa None döner. Dönen sözlük:
    {mfe_pct (>=0), mfe_ts, mae_pct (<=0), mae_ts, last_open_ts}.
    """
    base = float(first_price or 0)
    if base <= 0:
        return None
    state = dict(state or {})
    best_high_pct = state.get("mfe_pct")
    best_high_ts = state.get("mfe_ts")
    worst_low_pct = state.get("mae_pct")
    worst_low_ts = state.get("mae_ts")
    last_open_ts = state.get("last_open_ts")
    seen = False
    first_ms = int(float(first_ts) * 1000)
    end_ms = int(float(day_end_ts) * 1000)
    for c in candles or []:
        try:
            open_ms = int(c[0])
            high = float(c[2])
            low = float(c[3])
        except (TypeError, ValueError, IndexError):
            continue
        if open_ms < first_ms or open_ms > end_ms:
            continue
        seen = True
        open_ts = open_ms / 1000.0
        high_pct = (high - base) / base * 100.0
        low_pct = (low - base) / base * 100.0
        if best_high_pct is None or high_pct > best_high_pct:
            best_high_pct, best_high_ts = high_pct, open_ts
        if worst_low_pct is None or low_pct < worst_low_pct:
            worst_low_pct, worst_low_ts = low_pct, open_ts
        if last_open_ts is None or open_ts > last_open_ts:
            last_open_ts = open_ts
    if not seen and best_high_pct is None:
        return None
    return {
        # Saklama sözleşmesi: MFE >= 0, MAE <= 0 (negatif). Zamanlar ham tepe/dip mumuna aittir.
        "mfe_pct": round(max(0.0, best_high_pct), 4) if best_high_pct is not None else None,
        "mfe_ts": best_high_ts,
        "mae_pct": round(min(0.0, worst_low_pct), 4) if worst_low_pct is not None else None,
        "mae_ts": worst_low_ts,
        "last_open_ts": last_open_ts,
    }


async def _fetch_candles(symbol: str, start_ms: int, end_ms: int) -> list:
    """[start_ms, end_ms] aralığındaki 1 dk mumlar; 1000'lik sayfalarla (historical_klines deseni)."""
    from app.binance_tr_public import klines as fetch_klines
    rows: list = []
    cursor = int(start_ms)
    end_ms = int(end_ms)
    while cursor <= end_ms:
        batch = await fetch_klines(symbol, CANDLE_INTERVAL, KLINES_LIMIT, cursor, end_ms)
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < KLINES_LIMIT:
            break
        cursor = int(batch[-1][0]) + 1
    return rows


async def register_day(key: str, now: float | None = None) -> int:
    """`key` gününün sembol başına ilk bildirimlerini tabloya ekler (var olanlar korunur). Eklenen sayı."""
    start_ts, end_ts = day_bounds(key)
    firsts = await database.get_first_notifications_between(start_ts, end_ts + 1.0, push_only=True)
    rows = []
    for item in firsts:
        sym = normalize_symbol(item.get("symbol"))
        if sym is None:
            continue
        price = item.get("price")
        rows.append({
            "symbol": sym, "day_key": key, "first_notification_id": item.get("id"),
            "first_ts": float(item["detected_at"]),
            "first_price": float(price) if price is not None and float(price) > 0 else None,
        })
    return await database.insert_daily_first_notifications(rows, now=now)


async def register_today(now: float | None = None, include_previous: bool = False) -> int:
    """Bugünün (ve istenirse dünün) eksik satırlarını ekler; deploy öncesi bildirimler de yakalanır.

    `include_previous=True` açılışta kullanılır: yeniden başlatma günün kaydını kaybetmesin.
    """
    ts = time.time() if now is None else float(now)
    inserted = 0
    if include_previous:
        inserted += await register_day(previous_day_key(ts), now=ts)
    inserted += await register_day(day_key(ts), now=ts)
    return inserted


async def track(now: float | None = None) -> dict:
    """Açık satırları mumlarla günceller; günü geçenleri kapatır. {"updated": n, "finalized": n, "errors": n}."""
    ts = time.time() if now is None else float(now)
    rows = await database.list_open_daily_first_notifications()
    stats = {"updated": 0, "finalized": 0, "errors": 0}
    for row in rows:
        try:
            changed = await _track_row(row, ts)
            if changed == "finalized":
                stats["finalized"] += 1
            elif changed == "updated":
                stats["updated"] += 1
        except Exception as exc:  # noqa: BLE001 — tek sembol hatası diğerlerini durdurmasın
            stats["errors"] += 1
            logger.warning("günün ilk bildirimi izlenemedi (%s %s): %s", row.get("symbol"), row.get("day_key"), exc)
        await asyncio.sleep(0.05)
    return stats


async def _track_row(row: dict, now: float) -> str | None:
    _, day_end_ts = day_bounds(str(row["day_key"]))
    first_ts = float(row["first_ts"])
    window_start = max(first_ts, float(row.get("last_tracked_ts") or 0.0))
    window_end = min(now, day_end_ts)
    finalize = now > day_end_ts + FINALIZE_GRACE_SEC
    if window_start > window_end and not finalize:
        return None
    start_ms = int(window_start * 1000) // CANDLE_MS * CANDLE_MS
    end_ms = int(max(window_end, window_start) * 1000)
    candles = await _fetch_candles(str(row["symbol"]), start_ms, end_ms)

    first_price = row.get("first_price")
    fill_price = None
    if not first_price or float(first_price) <= 0:
        # Bildirimde fiyat yoktu: bildirim sonrası ilk mumun açılışı referans alınır.
        first_ms = int(first_ts * 1000)
        opens = [float(c[1]) for c in candles if int(c[0]) >= first_ms and len(c) > 3]
        if not opens:
            if finalize:
                await database.update_daily_first_notification_tracking(
                    row["id"], mfe_pct=None, mfe_ts=None, mae_pct=None, mae_ts=None,
                    last_tracked_ts=row.get("last_tracked_ts"), finalized=True, now=now)
                return "finalized"
            return None
        first_price = fill_price = opens[0]

    state = {k: row.get(k) for k in ("mfe_pct", "mfe_ts", "mae_pct", "mae_ts")}
    state["last_open_ts"] = row.get("last_tracked_ts")
    folded = fold_excursions(candles, float(first_price), first_ts, day_end_ts, state=state)
    if folded is None:
        if not finalize:
            return None
        folded = {**state, "last_open_ts": row.get("last_tracked_ts")}
    await database.update_daily_first_notification_tracking(
        row["id"], mfe_pct=folded.get("mfe_pct"), mfe_ts=folded.get("mfe_ts"),
        mae_pct=folded.get("mae_pct"), mae_ts=folded.get("mae_ts"),
        last_tracked_ts=folded.get("last_open_ts") or row.get("last_tracked_ts"),
        finalized=finalize, first_price=fill_price, now=now)
    return "finalized" if finalize else "updated"


async def daily_first_notification_loop() -> None:
    """Her 5 dakikada bir: bugünün (açılışta dünün de) ilk bildirimlerini kaydet, sonra mumlarla izle."""
    await asyncio.sleep(STARTUP_DELAY_SEC)
    first_round = True
    while True:
        try:
            inserted = await register_today(include_previous=first_round)
            if inserted:
                logger.info("günün ilk bildirimi: %d yeni sembol kaydedildi", inserted)
        except Exception as exc:  # noqa: BLE001
            logger.warning("günün ilk bildirimi kaydı atlandı: %s", exc)
        try:
            stats = await track()
            if stats["updated"] or stats["finalized"] or stats["errors"]:
                logger.info("günün ilk bildirimi izleme: %s", stats)
        except Exception as exc:  # noqa: BLE001
            logger.warning("günün ilk bildirimi izleme turu atlandı: %s", exc)
        first_round = False
        await asyncio.sleep(LOOP_INTERVAL_SEC)


__all__ = [
    "LOOP_INTERVAL_SEC", "day_bounds", "previous_day_key", "fold_excursions",
    "register_day", "register_today", "track", "daily_first_notification_loop",
]
