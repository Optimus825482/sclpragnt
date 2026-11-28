"""Live Binance TR one-minute acceleration experiment with an isolated paper ledger."""

import asyncio
import logging
import math
import os
import time
from collections import deque
from dataclasses import dataclass
from datetime import date, datetime, time as day_time, timedelta, timezone
from statistics import median

from app import alerting, database
from app.binance_tr_public import depth, klines, trading_symbols
from app.trade_size import parse_levels, sweep
from app.ws_runtime import ws_manager

MINUTE = 60_000
WINDOW = 30 * MINUTE
STARTING_CASH = 10_000.0
NOTIONAL = 1_000.0
FEE = 0.002
HOLD_SECONDS = 600
DELAY = 0.5
STOP = -3.0
TRAIL_START = 2.0
TRAIL_INITIAL_GAP = 1.25
TRAIL_MIN_GAP = 0.50
TRAIL_TIGHTEN_PER_POINT = 0.15
# Kademeli yükseliş tohumu (2026-11-28): 30 dk dibine göre bu oranı gören
# sembol izlemeye alınır; medyan*GRADUAL_GUARD şartı dip-recovery gürültüsünü
# keser. Yükselişlerin medyan tabanı yakalayamadığı durumlar için eklendi.
GRADUAL_MULT = 1.05  # 3 saatlik dibe göre kademeli kırılım
GRADUAL_GUARD = 1.015  # aynı anda 30 dk medyanının üstünde olmalı
SLOW_BARS = 180  # yavaş taban penceresi (3 saat)
MAX_SIGNAL_AGE = 15
RADAR_SCAN_SECONDS = 60
RADAR_WS_GRACE_SECONDS = 8
RADAR_SIGNAL_AGE = 90
RADAR_MAX_ENTRY_DRIFT = 0.01
RADAR_HISTORY_BARS = 61
RADAR_CONCURRENCY = 6
FOLLOWUP_BARS = 30
MONITOR_HOURS = 24
MONITOR_LIMIT = 300
# Erken izleme (+%5) aşamasında da push gönderilsin mi? Amaç: kullanıcı +%10
# teyidini beklemeden, pump'ın ilk dakikalarında haberdar olsun. Spam koruması
# için sembol başına 60 dk'da tek push ve saatte en fazla EARLY_PUSH_HOURLY
# push vardır; kapatmak için LARGE_MOVE_EARLY_PUSH=0.
EARLY_PUSH_HOURLY = 8
EARLY_PUSH_COOLDOWN_SEC = 3600.0
_early_push_sent: dict[str, float] = {}
_early_push_log: deque[float] = deque(maxlen=64)
ISTANBUL = timezone(timedelta(hours=3))
STABLE = {"USDT", "USDC", "FDUSD", "TUSD", "DAI", "USD1", "USDP", "USDE", "EUR", "EURI", "TRY", "WBETH", "BNSOL"}
_WALLET_LOCK = 39401157
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Alert:
    seed: int
    base: float
    stamp: int
    price: float
    level: int


def signal_notification(symbol: str, seed_ms: int, signal_ms: int, price: float, base: float) -> dict:
    rise = f"{100 * (price / base - 1):.1f}".replace(".", ",")
    return {
        "id": f"large-move-{symbol}-{seed_ms}",
        "kind": "large_move",
        "symbol": symbol,
        "message": f"Bir dakikalık mum baz fiyatın +%{rise} üzerinde kapandı.",
        "price": price,
        "triggered_at": signal_ms / 1000,
    }


def watch_notification(symbol: str, seed_ms: int, watch_ms: int) -> dict:
    return {
        "id": f"large-move-watch-{symbol}-{seed_ms}",
        "kind": "large_move_watch",
        "symbol": symbol,
        "message": "Baz fiyata göre +%10 eşiği geçildi. Parite izlemeye alındı.",
        "triggered_at": watch_ms / 1000,
    }


def early_watch_notification(symbol: str, seed_ms: int, watch_ms: int, price: float, base: float) -> dict:
    """+%5 erken izleme uyarısı — teyit (+%10) beklenmeden gönderilir."""
    rise = f"{100 * (price / base - 1):.1f}".replace(".", ",") if base else "5,0"
    return {
        "id": f"large-move-early-{symbol}-{seed_ms}",
        "kind": "large_move_early",
        "symbol": symbol,
        "message": f"Baz fiyata göre +%{rise} — erken izlemeye alındı (teyit için +%10 bekleniyor).",
        "price": price,
        "base": base,
        "triggered_at": watch_ms / 1000,
    }


def early_push_enabled() -> bool:
    """`LARGE_MOVE_EARLY_PUSH` (varsayılan açık) — kapalıysa +%5'te yalnız kayıt yazılır."""
    raw = os.getenv("LARGE_MOVE_EARLY_PUSH")
    return True if raw is None else str(raw).strip().lower() not in {"0", "false", "no", "off", ""}


def should_push_early(symbol: str, now: float) -> bool:
    """Erken izleme push'u gönderilmeli mi? (spam koruması, saf fonksiyon)."""
    if not early_push_enabled():
        return False
    last = _early_push_sent.get(symbol)
    if last is not None and now - last < EARLY_PUSH_COOLDOWN_SEC:
        return False
    recent = sum(1 for stamp in _early_push_log if now - stamp < 3600.0)
    return recent < EARLY_PUSH_HOURLY


def note_early_push(symbol: str, now: float) -> None:
    _early_push_sent[symbol] = now
    _early_push_log.append(now)


async def recent_notifications(limit: int = 30) -> list[dict]:
    def read(conn):
        rows = conn.execute(
            """SELECT symbol, seed_ms, signal_ms AS event_ms, signal_price AS price, base_price, 2 AS level
               FROM large_move_paper WHERE signal_ms IS NOT NULL
               UNION ALL
               SELECT symbol, seed_ms, watch_ms AS event_ms, NULL AS price, base_price, 1 AS level
               FROM large_move_paper
               ORDER BY event_ms DESC, level DESC, symbol, seed_ms DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        events = []
        for r in rows:
            if r["level"] == 2:
                events.append(
                    signal_notification(r["symbol"], r["seed_ms"], r["event_ms"], r["price"], r["base_price"])
                )
            else:
                events.append(watch_notification(r["symbol"], r["seed_ms"], r["event_ms"]))
        # Erken izleme (+%5) olayları ayrı tablodan; tablo yoksa (eski şema /
        # pg yetkisi) bildirim listesi çalışmaya devam eder.
        try:
            early_rows = conn.execute(
                """SELECT symbol, seed_ms, watch_ms AS event_ms, watch_price AS price, base_price
                   FROM large_move_early_watch ORDER BY event_ms DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        except Exception:  # noqa: BLE001
            logger.debug("erken izleme bildirimleri okunamadı", exc_info=True)
            early_rows = []
        for r in early_rows:
            events.append(
                early_watch_notification(r["symbol"], r["seed_ms"], r["event_ms"], r["price"], r["base_price"] or 0.0)
            )
        events.sort(key=lambda e: e.get("triggered_at") or 0.0, reverse=True)
        return events[:limit]

    return await database._run_db(read)


class Tracker:
    """Advance on a contiguous sequence of closed candles, using only prior closes."""

    def __init__(self):
        self.closes = deque(maxlen=30)
        # Yavaş taban (2026-11-28): kademeli yükselişler 30 dk medyanıyla
        # yakalanamıyor (medyan fiyatla birlikte yükseliyor). 3 saatlik dip
        # ayrıca tutulur; "3 saatte +%5" kırılımı da izlemeye alınır.
        self.slow = deque(maxlen=SLOW_BARS)
        self.last = 0
        self.was_above = False
        self.seed = None
        self.base = 0.0
        self.level = 0

    def observe(self, stamp: int, price: float, traded: bool) -> Alert | None:
        if stamp <= self.last:
            return None
        if self.last and stamp != self.last + MINUTE:
            self.__init__()
        self.last = stamp
        anchor = median(self.closes) if len(self.closes) == 30 else None
        slow_low = min(self.slow) if len(self.slow) >= 30 else None
        self.closes.append(price)
        self.slow.append(price)
        if anchor is None:
            return None
        # İKİ TABAN (2026-11-28 düzeltmesi): eski ölçüt yalnız 30 dk MEDYANINA
        # göre +%3 arıyordu. Kademeli yükselişte medyan fiyatla birlikte
        # yükseldiği için fark hiç oluşmuyordu (NIGHTTRY 2 saatte +%7 yükseldi,
        # medyan oranı en fazla +%2,32 kaldı → Monitor onu izlemeye almadı).
        # Artık "3 saatlik dibe göre +%5" de tohumluyor; medyan*1.015 koruması
        # dip-recovery gürültüsünü ve 3 saatlik eski dibi kesiyor.
        sharp = self._reached(price, anchor, 1.03)
        gradual = bool(
            slow_low and self._reached(price, slow_low, GRADUAL_MULT) and self._reached(price, anchor, GRADUAL_GUARD)
        )
        above = bool(traded and (sharp or gradual))
        if self.seed is not None and stamp >= self.seed + WINDOW:
            self.seed = None
        if self.seed is None and above and not self.was_above:
            # Taban, hareketi tetikleyen seviyedir: ani sıçramada 30 dk medyanı,
            # yavaş yükselişte 3 saatlik dip (seviyeler o tabana göre ölçülür).
            self.seed, self.base, self.level = stamp, anchor if sharp else slow_low, 0
        self.was_above = above
        if self.seed is None or not traded or stamp + MINUTE >= self.seed + WINDOW:
            return None
        level = (
            15
            if self._reached(price, self.base, 1.15)
            else 10
            if self._reached(price, self.base, 1.10)
            else 5
            if self._reached(price, self.base, 1.05)
            else 0
        )
        if level <= self.level:
            return None
        self.level = level
        return Alert(self.seed, self.base, stamp + MINUTE, price, level)

    @staticmethod
    def _reached(price: float, base: float, multiplier: float) -> bool:
        threshold = base * multiplier
        return price >= threshold or math.isclose(price, threshold, rel_tol=1e-12)


def radar_bars(candles, close_ms):
    """Normalize REST candles up to the requested completed minute."""
    bars = {}
    for candle in candles if isinstance(candles, list) else []:
        try:
            stamp, price, volume, end = int(candle[0]), float(candle[4]), float(candle[5]), int(candle[6])
        except (IndexError, TypeError, ValueError, OverflowError):
            continue
        if (
            stamp > 0
            and stamp % MINUTE == 0
            and end == stamp + MINUTE - 1
            and end < close_ms
            and math.isfinite(price)
            and price > 0
            and math.isfinite(volume)
        ):
            bars[stamp] = (stamp, price, volume > 0)
    return [bars[stamp] for stamp in sorted(bars)]


def radar_symbol(symbol):
    return symbol.endswith("TRY") and symbol[:-3] not in STABLE


async def scan_missing_bars(symbols, trackers, accept, close_ms):
    """Fill missing closes and warm untracked pairs without polling healthy streams."""
    slots = asyncio.Semaphore(RADAR_CONCURRENCY)

    async def recover(symbol):
        async with slots:
            tracker = trackers.get(symbol)
            limit = RADAR_HISTORY_BARS
            if tracker and len(tracker.closes) == tracker.closes.maxlen:
                missing = (close_ms - MINUTE - tracker.last) // MINUTE
                if missing <= 0:
                    return
                limit = min(limit, missing)
            try:
                candles = await asyncio.wait_for(
                    klines(symbol, "1m", limit, end_time_ms=close_ms - 1),
                    timeout=6,
                )
            except (TimeoutError, OSError, RuntimeError, ValueError):
                logger.debug("Large-move radar candles unavailable for %s", symbol, exc_info=True)
                return
            bars = radar_bars(candles, close_ms)
            tracker = trackers.get(symbol)
            if not tracker or (len(tracker.closes) < tracker.closes.maxlen and len(bars) > len(tracker.closes)):
                trackers[symbol] = Tracker()
            for stamp, price, traded in bars:
                accept(symbol, stamp, price, traded, from_radar=True)

    await asyncio.gather(*(recover(symbol) for symbol in symbols if radar_symbol(symbol)))


def read_book(raw):
    if not raw:
        return None
    try:
        bids, asks = (parse_levels(raw[k]) for k in ("bids", "asks"))
    except (TypeError, KeyError, ValueError, OverflowError):
        return None
    if not bids or not asks or bids[0][0] >= asks[0][0]:
        return None
    if any(not math.isfinite(p) or not math.isfinite(q) or min(p, q) <= 0 for p, q in (*bids, *asks)):
        return None
    return bids, asks


def mark_exit(bids, quantity, cost, fee):
    remaining, proceeds = quantity, 0.0
    for price, size in bids:
        take = min(remaining, size)
        proceeds += take * price
        remaining -= take
        if remaining <= 1e-10:
            net = proceeds * (1 - fee) - cost
            return proceeds / quantity, net, 100 * net / cost
    return None


def trailing_level(pct: float, previous_peak: float | None, previous_stop: float | None):
    """Return the observed net peak and the one-way trailing floor in percentage points."""
    peak = pct if previous_peak is None else max(pct, previous_peak)
    if peak < TRAIL_START:
        return peak, previous_stop
    gap = max(TRAIL_MIN_GAP, TRAIL_INITIAL_GAP - (peak - TRAIL_START) * TRAIL_TIGHTEN_PER_POINT)
    floor = peak - gap
    return peak, floor if previous_stop is None else max(floor, previous_stop)


async def save_early_watch(symbol: str, alert: Alert):
    await database._run_db(
        lambda conn: conn.execute(
            """INSERT INTO large_move_early_watch (symbol, seed_ms, base_price, watch_ms, watch_price)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT (symbol, seed_ms) DO UPDATE SET
             base_price = EXCLUDED.base_price, watch_ms = EXCLUDED.watch_ms, watch_price = EXCLUDED.watch_price
           WHERE large_move_early_watch.watch_ms > EXCLUDED.watch_ms""",
            (symbol, alert.seed, alert.base, alert.stamp, alert.price),
        )
    )


async def save_watch(symbol: str, alert: Alert) -> bool:
    def write(conn):
        inserted = conn.execute(
            """INSERT INTO large_move_paper (symbol, seed_ms, base_price, watch_ms, status)
               VALUES (?, ?, ?, ?, 'watch')
               ON CONFLICT (symbol, seed_ms) DO NOTHING""",
            (symbol, alert.seed, alert.base, alert.stamp),
        ).rowcount
        if inserted:
            return True
        conn.execute(
            """UPDATE large_move_paper SET watch_ms = ?
               WHERE symbol = ? AND seed_ms = ? AND watch_ms > ?""",
            (alert.stamp, symbol, alert.seed, alert.stamp),
        )
        return False

    return await database._run_db(write)


async def deliver_watch_push(event: dict, alert: Alert):
    try:
        symbol = event["symbol"]
        await alerting.deliver_alert_push(
            event["message"],
            title=f"{symbol} izlemeye alındı",
            url=f"/charts?symbol={symbol}&timeframe=1m",
            tag=event["id"],
            extra={
                "symbol": symbol,
                "source": "large_move_watch",
                "detected_at": event["triggered_at"],
                "horizon_minutes": (alert.seed + WINDOW - alert.stamp) / MINUTE,
            },
        )
    except Exception:
        logger.exception("Large-move watch push failed for %s", event["symbol"])


async def deliver_early_push(event: dict, alert: Alert):
    """+%5 erken izleme push'u — teyit sinyalinden önce haber verir."""
    try:
        symbol = event["symbol"]
        note_early_push(symbol, time.time())
        await alerting.deliver_alert_push(
            event["message"],
            title=f"{symbol} erken izlemede",
            url=f"/monitor",
            tag=event["id"],
            extra={
                "symbol": symbol,
                "source": "large_move_early",
                "detected_at": event["triggered_at"],
                "base_price": event.get("base"),
                "horizon_minutes": (alert.seed + WINDOW - alert.stamp) / MINUTE,
            },
        )
    except Exception:
        logger.exception("Large-move early push failed for %s", event.get("symbol"))


async def save_entry(symbol, alert, book, now, *, from_radar=False):
    fill = sweep(book[1], NOTIONAL) if book else None
    spread = None
    if book:
        bid, ask = book[0][0][0], book[1][0][0]
        spread = 200 * (ask - bid) / (ask + bid)
    cost = NOTIONAL * (1 + FEE)
    age = now - alert.stamp / 1000
    max_age = RADAR_SIGNAL_AGE if from_radar else MAX_SIGNAL_AGE
    start_today = datetime.combine(datetime.fromtimestamp(now, ISTANBUL).date(), day_time.min, ISTANBUL).timestamp()

    def write(conn):
        conn.execute("SELECT pg_advisory_xact_lock(?)", (_WALLET_LOCK,))
        existing = conn.execute(
            "SELECT status FROM large_move_paper WHERE symbol = ? AND seed_ms = ?",
            (symbol, alert.seed),
        ).fetchone()
        if not existing or existing["status"] != "watch":
            return False
        settings = {
            r["key"]: r["value"]
            for r in conn.execute(
                """SELECT key, value FROM llm_settings
               WHERE key IN ('global_trading_halt', 'daily_loss_limit_pct')"""
            ).fetchall()
        }
        try:
            daily_limit = STARTING_CASH * float(settings.get("daily_loss_limit_pct", "0")) / 100
        except ValueError:
            daily_limit = 0
        wallet = conn.execute(
            """SELECT COALESCE(SUM(net_pnl_try), 0) AS realized,
                      COALESCE(SUM(net_pnl_try) FILTER (WHERE closed_at >= ?), 0) AS today_pnl,
                      COALESCE(SUM(entry_cost) FILTER (WHERE status = 'open'), 0) AS reserved,
                      COUNT(*) FILTER (WHERE status = 'open' AND symbol = ?) AS same_symbol
               FROM large_move_paper""",
            (start_today, symbol),
        ).fetchone()
        reason = None
        if settings.get("global_trading_halt", "").strip().lower() in {"1", "true", "yes", "on"}:
            reason = "global_kill_switch"
        elif daily_limit > 0 and wallet["today_pnl"] <= -daily_limit:
            reason = "daily_loss_limit"
        elif age > max_age:
            reason = "stale_signal"
        elif not fill:
            reason = "quote_unavailable"
        elif fill["filled_try"] < NOTIONAL - 1e-7:
            reason = "insufficient_depth"
        elif (
            from_radar
            and age > MAX_SIGNAL_AGE
            and (
                not Tracker._reached(fill["avg_price"], alert.base, 1.15)
                or fill["avg_price"] > alert.price * (1 + RADAR_MAX_ENTRY_DRIFT)
            )
        ):
            reason = "radar_price_moved"
        elif wallet["same_symbol"]:
            reason = "already_open"
        elif STARTING_CASH + wallet["realized"] - wallet["reserved"] < cost:
            reason = "insufficient_cash"
        if reason:
            conn.execute(
                """UPDATE large_move_paper SET signal_ms = ?, signal_price = ?, spread_pct = ?,
                       status = 'blocked', reason = ? WHERE symbol = ? AND seed_ms = ?""",
                (alert.stamp, alert.price, spread, reason, symbol, alert.seed),
            )
        else:
            conn.execute(
                """UPDATE large_move_paper SET signal_ms = ?, signal_price = ?, spread_pct = ?,
                       status = 'open', opened_at = ?, entry_price = ?, quantity = ?,
                       entry_cost = ?, fee_rate = ? WHERE symbol = ? AND seed_ms = ?""",
                (alert.stamp, alert.price, spread, now, fill["avg_price"], fill["qty"], cost, FEE, symbol, alert.seed),
            )
        return True

    return await database._run_db(write)


async def open_trades():
    now = time.time()

    def read(conn):
        conn.execute(
            """UPDATE large_move_paper SET reason = 'time', exit_due_at = opened_at + ?
               WHERE status = 'open' AND exit_due_at IS NULL AND opened_at <= ?""",
            (HOLD_SECONDS + DELAY, now - HOLD_SECONDS),
        )
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM large_move_paper WHERE status = 'open' ORDER BY symbol, seed_ms"
            ).fetchall()
        ]

    return await database._run_db(read)


async def save_marks(updates):
    def write(conn):
        for trade, price, net, pct, now in updates:
            key = (trade["symbol"], trade["seed_ms"])
            current = conn.execute(
                """SELECT marked_at, mark_net_pct, peak_net_pct, trailing_stop_pct, exit_due_at
                   FROM large_move_paper WHERE symbol = ? AND seed_ms = ? AND status = 'open'
                   FOR UPDATE""",
                key,
            ).fetchone()
            if current is None or (current["marked_at"] is not None and now <= current["marked_at"]):
                continue
            due = current["exit_due_at"]
            if due is not None and now >= due:
                conn.execute(
                    """UPDATE large_move_paper SET status = 'closed', closed_at = ?, exit_price = ?,
                       net_pnl_try = ?, net_pnl_pct = ?, mark_price = ?, mark_net_pct = ?, marked_at = ?
                       WHERE symbol = ? AND seed_ms = ? AND status = 'open' AND exit_due_at <= ?""",
                    (now, price, net, pct, price, pct, now, *key, now),
                )
                continue
            peak, floor = current["peak_net_pct"], current["trailing_stop_pct"]
            reason = None
            if due is None:
                # Existing positions can seed the peak from their last recorded executable mark.
                peak, floor = trailing_level(pct, current["mark_net_pct"] if peak is None else peak, floor)
                if floor is not None and pct <= floor:
                    reason = "trailing"
                elif pct <= STOP:
                    reason = "stop"
            conn.execute(
                """UPDATE large_move_paper SET mark_price = ?, mark_net_pct = ?, marked_at = ?,
                   peak_net_pct = ?, trailing_stop_pct = ?,
                   reason = COALESCE(reason, ?), exit_due_at = COALESCE(exit_due_at, ?)
                   WHERE symbol = ? AND seed_ms = ? AND status = 'open'""",
                (price, pct, now, peak, floor, reason, now + DELAY if reason else None, *key),
            )

    if updates:
        await database._run_db(write)


def followup_path(rows, start_ms, end_ms, base_price=None):
    """Summarize consecutive complete minutes and a late threshold crossing if applicable."""
    candles = {}
    for row in rows:
        try:
            stamp = int(row[0])
            high, low, close = map(float, row[2:5])
        except (ValueError, TypeError, IndexError, KeyError, OverflowError):
            continue
        if (
            start_ms <= stamp
            and stamp + MINUTE <= end_ms
            and all(math.isfinite(p) for p in (low, high, close))
            and 0 < low <= close <= high
        ):
            candles[stamp] = (low, high, close)
    path = []
    for stamp in range(start_ms, end_ms, MINUTE):
        if stamp not in candles:
            break
        path.append(candles[stamp])
    if not path:
        return None
    late_signal = None
    if base_price is not None:
        late_signal = next(
            (
                start_ms + i * MINUTE
                for i, (_, _, close) in enumerate(path, 1)
                if Tracker._reached(close, base_price, 1.15)
            ),
            None,
        )
    return len(path), min(bar[0] for bar in path), max(bar[1] for bar in path), path[-1][2], late_signal


async def refresh_followup_paths():
    now = time.time()
    rows = await database._run_db(
        lambda conn: conn.execute(
            """SELECT symbol, seed_ms, closed_at, watch_ms, base_price, status FROM large_move_paper
           WHERE followup_bars < ? AND (followup_check_at IS NULL OR followup_check_at <= ?)
                 AND ((status = 'closed' AND reason IN ('stop', 'trailing') AND closed_at <= ?)
                      OR (status = 'watch' AND seed_ms + ? <= ?))
           ORDER BY followup_check_at NULLS FIRST, watch_ms DESC LIMIT 4""",
            (FOLLOWUP_BARS, now, now - 120, WINDOW, int((now - 60) * 1000)),
        ).fetchall()
    )

    async def fetch(row):
        expired_watch = row["status"] == "watch"
        start = row["seed_ms"] + WINDOW if expired_watch else math.ceil(row["closed_at"] / 60) * MINUTE
        query_start = row["watch_ms"] - MINUTE if expired_watch else start
        end = min(start + FOLLOWUP_BARS * MINUTE, int(now // 60) * MINUTE)
        watch_high = None
        try:
            candles = await asyncio.wait_for(
                klines(
                    row["symbol"], "1m", (end - query_start) // MINUTE, start_time_ms=query_start, end_time_ms=end - 1
                ),
                timeout=8,
            )
            candles = candles if isinstance(candles, list) else []
            result = followup_path(candles, start, end, row["base_price"] if expired_watch else None)
            if expired_watch:
                during_watch = followup_path(candles, query_start, start)
                if during_watch and during_watch[0] == (start - query_start) // MINUTE:
                    watch_high = during_watch[2]
        except (OSError, RuntimeError, ValueError):
            logger.debug("Follow-up candles unavailable for %s", row["symbol"], exc_info=True)
            result = None
        return row, result, watch_high

    observed = await asyncio.gather(*(fetch(row) for row in rows))

    def write(conn):
        for row, result, watch_high in observed:
            key = (row["symbol"], row["seed_ms"], row["status"])
            if result:
                bars, low, high, close, late_signal = result
                conn.execute(
                    """UPDATE large_move_paper SET followup_bars = ?, followup_low = ?,
                       followup_high = ?, followup_close = ?, late_signal_ms = ?,
                       watch_high = COALESCE(?, watch_high), followup_check_at = ?
                       WHERE symbol = ? AND seed_ms = ? AND status = ? AND followup_bars <= ?""",
                    (bars, low, high, close, late_signal, watch_high, now + 60, *key, bars),
                )
            else:
                conn.execute(
                    """UPDATE large_move_paper SET followup_check_at = ?,
                       watch_high = COALESCE(?, watch_high)
                       WHERE symbol = ? AND seed_ms = ? AND status = ? AND followup_bars < ?""",
                    (now + 300, watch_high, *key, FOLLOWUP_BARS),
                )

    if observed:
        await database._run_db(write)


def derive_monitor_metrics(row: dict, now_ms: int) -> dict:
    """İzleme satırına okunabilir ilerleme metrikleri ekler (saf fonksiyon).

    - `rise_from_base_pct`: baz fiyattan bu yana gerçekleşen yükseliş
    - `to_watch_pct` / `to_signal_pct`: +%10 teyit ve +%15 sinyal eşiğine kalan
    - `age_min` / `remaining_min`: erken izleme yaşı ve pencerenin kalanı
    """
    base = row.get("base_price") or 0.0
    price = row.get("current_price")
    seed = row.get("seed_ms") or 0
    out = {
        "rise_from_base_pct": None,
        "to_watch_pct": None,
        "to_signal_pct": None,
        "age_min": None,
        "remaining_min": None,
    }
    if base and isinstance(price, (int, float)) and price > 0:
        rise = (price / base - 1) * 100
        out["rise_from_base_pct"] = round(rise, 2)
        out["to_watch_pct"] = round(10.0 - rise, 2)
        out["to_signal_pct"] = round(15.0 - rise, 2)
    if seed:
        start = row.get("early_watch_ms") or seed
        out["age_min"] = round(max(0.0, (now_ms - start) / MINUTE), 1)
        out["remaining_min"] = round(max(0.0, (seed + WINDOW - now_ms) / MINUTE), 1)
    return out


def flow_tag_for(cvd_pct: float | None) -> str:
    """Kesinleşmiş saat akışını etikete çevir (CVD yoksa `BILINMIYOR`)."""
    if cvd_pct is None:
        return "BILINMIYOR"
    if cvd_pct >= 1.0:
        return "AKIS_ALICI"
    if cvd_pct <= -1.0:
        return "AKIS_SATICI"
    return "DENGELI"


async def monitor_rows(market):
    now_ms = int(time.time() * 1000)
    cutoff = now_ms - MONITOR_HOURS * 60 * MINUTE

    def read(conn):
        return [
            dict(row)
            for row in conn.execute(
                """WITH recent AS (
                 SELECT symbol, seed_ms FROM large_move_early_watch WHERE watch_ms >= ?
                 UNION
                 SELECT symbol, seed_ms FROM large_move_paper WHERE watch_ms >= ? OR status = 'open'
               )
               SELECT recent.symbol, recent.seed_ms, COALESCE(p.base_price, e.base_price) AS base_price,
                      e.watch_ms AS early_watch_ms, e.watch_price AS early_watch_price,
                      p.watch_ms, p.signal_ms, p.signal_price, p.entry_price, p.exit_price,
                      p.closed_at, p.net_pnl_pct, p.mark_net_pct,
                      recent.seed_ms + ? AS expires_at_ms,
                      CASE WHEN p.status IN ('open', 'closed', 'blocked') THEN p.status
                           WHEN recent.seed_ms + ? <= ? THEN 'expired'
                           WHEN p.watch_ms IS NOT NULL THEN 'watch'
                           ELSE 'early' END AS display_status
               FROM recent
               LEFT JOIN large_move_early_watch e USING (symbol, seed_ms)
               LEFT JOIN large_move_paper p USING (symbol, seed_ms)
               ORDER BY CASE WHEN p.status = 'open' THEN 0
                             WHEN recent.seed_ms + ? > ? AND p.signal_ms IS NULL THEN 1
                             ELSE 2 END,
                        COALESCE(p.signal_ms, p.watch_ms, e.watch_ms) DESC, recent.symbol, recent.seed_ms DESC
               LIMIT ?""",
                (cutoff, cutoff, WINDOW, WINDOW, now_ms, WINDOW, now_ms, MONITOR_LIMIT),
            ).fetchall()
        ]

    rows = await database._run_db(read)
    prices = {}
    for row in rows:
        symbol = row["symbol"]
        if symbol not in prices:
            price = (market.get_ticker(symbol) or {}).get("last_price")
            if (
                isinstance(price, (float, int))
                and math.isfinite(price)
                and price > 0
                and market.ticker_freshness(symbol, max_age_sec=60)["fresh"]
            ):
                prices[symbol] = price
            else:
                prices[symbol] = None
        row["current_price"] = prices[symbol]

    # CVD onay katmanı: yalnız kesinleşmiş saati olan semboller için dolar.
    # (Collector: backend/scripts/cvd_confirm_collector.py, ~1-2 saat gecikmeli.)
    try:
        from app.confirmed_flow import load_confirmed

        confirmed = load_confirmed()
    except Exception:  # noqa: BLE001
        logger.debug("confirmed flow store okunamadı", exc_info=True)
        confirmed = {}
    for row in rows:
        row.update(derive_monitor_metrics(row, now_ms))
        hours = confirmed.get(row["symbol"]) or []
        if hours:
            oldest = hours[-1]
            cvd_pct = float(oldest.get("cvd_pct_of_volume") or 0.0)
            row["confirmed_hour"] = oldest.get("hour")
            row["confirmed_cvd_pct"] = cvd_pct
            row["flow_tag"] = flow_tag_for(cvd_pct)
            rise = row.get("rise_from_base_pct") or 0.0
            row["trap_risk"] = bool(rise >= 8.0 and cvd_pct <= -1.0)
        else:
            row["confirmed_hour"] = None
            row["confirmed_cvd_pct"] = None
            row["flow_tag"] = flow_tag_for(None)
            row["trap_risk"] = False
    return {"rows": rows, "as_of_ms": now_ms, "hours": MONITOR_HOURS, "limit": MONITOR_LIMIT}


async def report(day: date | None, include_archived: bool):
    def read(conn):
        lower = 0 if include_archived else database._get_reports_baseline_sync(conn) * 1000
        upper = 2**63 - 1
        if day:
            start = datetime.combine(day, day_time.min, ISTANBUL).timestamp() * 1000
            lower = max(lower, start)
            upper = int(start + 86_400_000)
        params = (int(lower), upper)
        where = "watch_ms >= ? AND watch_ms < ?"
        now_ms = int(time.time() * 1000)
        stats = conn.execute(
            f"""SELECT COUNT(*) AS watched,
               COUNT(*) FILTER (WHERE signal_ms IS NOT NULL) AS signals,
               COUNT(*) FILTER (WHERE status = 'open') AS opened,
               COUNT(*) FILTER (WHERE status = 'closed') AS closed,
               COUNT(*) FILTER (WHERE status = 'blocked') AS blocked,
               COUNT(*) FILTER (WHERE status = 'closed' AND net_pnl_try > 0) AS wins,
               COALESCE(SUM(net_pnl_try), 0) AS net_try
               FROM large_move_paper WHERE {where}""",
            params,
        ).fetchone()
        rows = conn.execute(
            f"""SELECT *, CASE WHEN status = 'watch' AND seed_ms + ? <= ? THEN 'expired'
                                  ELSE status END AS display_status
                FROM large_move_paper WHERE {where}
                ORDER BY (status = 'open') DESC, watch_ms DESC, symbol LIMIT 300""",
            (WINDOW, now_ms, *params),
        ).fetchall()
        return {
            "paper_only": True,
            "day": day.isoformat() if day else None,
            "initial_cash": STARTING_CASH,
            "notional": NOTIONAL,
            "fee_pct": FEE * 100,
            "trailing": {
                "activation_pct": TRAIL_START,
                "initial_gap": TRAIL_INITIAL_GAP,
                "min_gap": TRAIL_MIN_GAP,
                "tighten_per_point": TRAIL_TIGHTEN_PER_POINT,
            },
            "stop_pct": STOP,
            "hold_minutes": HOLD_SECONDS // 60,
            "followup_minutes": FOLLOWUP_BARS,
            "limit": 300,
            "summary": dict(stats),
            "rows": [dict(r) for r in rows],
        }

    return await database._run_db(read)


async def run(market):
    trackers: dict[str, Tracker] = {}
    queue: asyncio.Queue = asyncio.Queue(maxsize=512)
    retry_until: dict[str, float] = {}

    def accept(symbol, stamp, price, traded, *, from_radar=False):
        alert = trackers[symbol].observe(stamp, price, traded)
        max_age = RADAR_SIGNAL_AGE if from_radar else MAX_SIGNAL_AGE
        if alert and abs(time.time() - alert.stamp / 1000) <= max_age:
            try:
                queue.put_nowait((symbol, alert, from_radar))
            except asyncio.QueueFull:
                logger.error("Large-move paper queue full for %s", symbol)

    def on_bar(symbol, timeframe, bar):
        if timeframe != "1m" or not bar["closed"] or not radar_symbol(symbol):
            return
        stamp, price = int(bar["time"]), float(bar["close"])
        if not math.isfinite(price) or price <= 0:
            return
        tracker = trackers.get(symbol)
        if tracker is None:
            tracker = trackers[symbol] = Tracker()
            history = market.klines.get("1m", {}).get(symbol, {})
            for t, p, volume in zip(
                *(history.get(key, [])[-RADAR_HISTORY_BARS:] for key in ("timestamps", "closes", "volumes"))
            ):
                if t < stamp and p > 0 and math.isfinite(p):
                    tracker.observe(int(t), p, volume > 0)
        # Preserve the active episode until REST can fill a missing close.
        if tracker.last and stamp > tracker.last + MINUTE:
            return
        accept(symbol, stamp, price, bar["volume"] > 0)

    async def quote(symbol, enough):
        live = market.get_depth_snapshot(symbol, max_age=2)
        book = read_book(live)
        if (book and enough(book)) or time.monotonic() < retry_until.get(symbol, 0):
            return book
        retry_until[symbol] = time.monotonic() + 10
        try:
            return read_book(await asyncio.wait_for(depth(symbol, 20), timeout=4)) or book
        except (TimeoutError, OSError, RuntimeError, ValueError):
            logger.debug("Large-move paper quote unavailable for %s", symbol, exc_info=True)
            return book

    async def record_early(symbol, alert):
        try:
            await save_early_watch(symbol, alert)
        except Exception:
            logger.exception("Large-move early watch persistence failed for %s", symbol)

    async def entry(symbol, alert, from_radar, tasks):
        try:
            if alert.level == 5:
                await record_early(symbol, alert)
                if should_push_early(symbol, time.time()):
                    event = early_watch_notification(symbol, alert.seed, alert.stamp, alert.price, alert.base)
                    await deliver_early_push(event, alert)
                    await ws_manager.broadcast({"type": "large_move_alert", "data": event})
                return
            if await save_watch(symbol, alert):
                # A single candle can cross both watch thresholds.
                tasks.create_task(record_early(symbol, alert))
                event = watch_notification(symbol, alert.seed, alert.stamp)
                tasks.create_task(deliver_watch_push(event, alert))
                await ws_manager.broadcast({"type": "large_move_alert", "data": event})
            if alert.level == 15:
                book = None
                max_age = RADAR_SIGNAL_AGE if from_radar else MAX_SIGNAL_AGE
                if time.time() - alert.stamp / 1000 <= max_age:
                    await asyncio.sleep(DELAY)
                    book = await quote(symbol, lambda b: sum(p * q for p, q in b[1]) >= NOTIONAL)
                if await save_entry(symbol, alert, book, time.time(), from_radar=from_radar):
                    await ws_manager.broadcast(
                        {
                            "type": "large_move_alert",
                            "data": signal_notification(symbol, alert.seed, alert.stamp, alert.price, alert.base),
                        }
                    )
        except Exception:
            logger.exception("Large-move paper alert persistence failed for %s", symbol)

    market.add_bar_listener(on_bar)
    try:
        async with asyncio.TaskGroup() as tasks:

            async def process_entries():
                while True:
                    symbol, alert, from_radar = await queue.get()
                    await entry(symbol, alert, from_radar, tasks)

            async def update_trade(trade):
                book = await quote(trade["symbol"], lambda b: sum(q for _, q in b[0]) >= trade["quantity"])
                if book is None:
                    return None
                mark = mark_exit(book[0], trade["quantity"], trade["entry_cost"], trade["fee_rate"])
                if mark is None:
                    return None
                now = time.time()
                price, net, pct = mark
                return trade, price, net, pct, now

            async def manage():
                while True:
                    try:
                        trades = await open_trades()
                        marks = await asyncio.gather(*(update_trade(t) for t in trades))
                        await save_marks([m for m in marks if m is not None])
                    except Exception:
                        logger.exception("Large-move paper position management failed")
                    await asyncio.sleep(DELAY)

            async def track_followups():
                while True:
                    try:
                        await refresh_followup_paths()
                    except Exception:
                        logger.exception("Large-move paper follow-up tracking failed")
                    await asyncio.sleep(30)

            async def scan_radar():
                while True:
                    now = time.time()
                    await asyncio.sleep((RADAR_WS_GRACE_SECONDS - now % RADAR_SCAN_SECONDS) % RADAR_SCAN_SECONDS)
                    close_ms = int(time.time() // 60) * MINUTE
                    try:
                        symbols = await asyncio.wait_for(trading_symbols(), timeout=6)
                        await scan_missing_bars(symbols, trackers, accept, close_ms)
                    except Exception:
                        logger.exception("Large-move radar scan failed")
                    await asyncio.sleep(1)

            for _ in range(8):
                tasks.create_task(process_entries())
            tasks.create_task(manage())
            tasks.create_task(track_followups())
            tasks.create_task(scan_radar())
    finally:
        market.remove_bar_listener(on_bar)
