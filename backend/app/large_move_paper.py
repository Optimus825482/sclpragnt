"""Live Binance TR one-minute acceleration experiment with an isolated paper ledger."""
import asyncio
import logging
import math
import time
from collections import deque
from dataclasses import dataclass
from datetime import date, datetime, time as day_time, timedelta, timezone
from statistics import median

from app import database
from app.binance_tr_public import depth, klines
from app.trade_size import parse_levels, sweep

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
MAX_SIGNAL_AGE = 15
FOLLOWUP_BARS = 30
ISTANBUL = timezone(timedelta(hours=3))
STABLE = {"USDT", "USDC", "FDUSD", "TUSD", "DAI", "USD1", "USDP", "USDE", "EUR",
          "EURI", "TRY", "WBETH", "BNSOL"}
_WALLET_LOCK = 39401157
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Alert:
    seed: int
    base: float
    stamp: int
    price: float
    level: int


class Tracker:
    """Advance on a contiguous sequence of closed candles, using only prior closes."""

    def __init__(self):
        self.closes = deque(maxlen=30)
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
        self.closes.append(price)
        if anchor is None:
            return None
        above = traded and self._reached(price, anchor, 1.03)
        if self.seed is not None and stamp >= self.seed + WINDOW:
            self.seed = None
        if self.seed is None and above and not self.was_above:
            self.seed, self.base, self.level = stamp, anchor, 0
        self.was_above = above
        if self.seed is None or not traded or stamp + MINUTE >= self.seed + WINDOW:
            return None
        level = (15 if self._reached(price, self.base, 1.15) else
                 10 if self._reached(price, self.base, 1.10) else 0)
        if level <= self.level:
            return None
        self.level = level
        return Alert(self.seed, self.base, stamp + MINUTE, price, level)

    @staticmethod
    def _reached(price: float, base: float, multiplier: float) -> bool:
        threshold = base * multiplier
        return price >= threshold or math.isclose(price, threshold, rel_tol=1e-12)


def read_book(raw):
    if not raw:
        return None
    try:
        bids, asks = (parse_levels(raw[k]) for k in ("bids", "asks"))
    except (TypeError, KeyError, ValueError, OverflowError):
        return None
    if not bids or not asks or bids[0][0] >= asks[0][0]:
        return None
    if any(not math.isfinite(p) or not math.isfinite(q) or min(p, q) <= 0
           for p, q in (*bids, *asks)):
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


async def save_watch(symbol: str, alert: Alert):
    await database._run_db(lambda conn: conn.execute(
        """INSERT INTO large_move_paper (symbol, seed_ms, base_price, watch_ms, status)
           VALUES (?, ?, ?, ?, 'watch')
           ON CONFLICT (symbol, seed_ms) DO UPDATE
           SET watch_ms = LEAST(large_move_paper.watch_ms, EXCLUDED.watch_ms)
           WHERE large_move_paper.watch_ms > EXCLUDED.watch_ms""",
        (symbol, alert.seed, alert.base, alert.stamp),
    ).rowcount)


async def save_entry(symbol, alert, book, now):
    fill = sweep(book[1], NOTIONAL) if book else None
    spread = None
    if book:
        bid, ask = book[0][0][0], book[1][0][0]
        spread = 200 * (ask - bid) / (ask + bid)
    cost = NOTIONAL * (1 + FEE)
    start_today = datetime.combine(datetime.fromtimestamp(now, ISTANBUL).date(),
                                   day_time.min, ISTANBUL).timestamp()

    def write(conn):
        conn.execute("SELECT pg_advisory_xact_lock(?)", (_WALLET_LOCK,))
        existing = conn.execute(
            "SELECT status FROM large_move_paper WHERE symbol = ? AND seed_ms = ?",
            (symbol, alert.seed),
        ).fetchone()
        if not existing or existing["status"] != "watch":
            return
        settings = {r["key"]: r["value"] for r in conn.execute(
            """SELECT key, value FROM llm_settings
               WHERE key IN ('global_trading_halt', 'daily_loss_limit_pct')"""
        ).fetchall()}
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
        elif now - alert.stamp / 1000 > MAX_SIGNAL_AGE:
            reason = "stale_signal"
        elif not fill:
            reason = "quote_unavailable"
        elif fill["filled_try"] < NOTIONAL - 1e-7:
            reason = "insufficient_depth"
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
                (alert.stamp, alert.price, spread, now, fill["avg_price"], fill["qty"],
                 cost, FEE, symbol, alert.seed),
            )

    await database._run_db(write)


async def open_trades():
    now = time.time()

    def read(conn):
        conn.execute(
            """UPDATE large_move_paper SET reason = 'time', exit_due_at = opened_at + ?
               WHERE status = 'open' AND exit_due_at IS NULL AND opened_at <= ?""",
            (HOLD_SECONDS + DELAY, now - HOLD_SECONDS),
        )
        return [dict(r) for r in conn.execute(
            "SELECT * FROM large_move_paper WHERE status = 'open' ORDER BY symbol, seed_ms"
        ).fetchall()]
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
        if (start_ms <= stamp and stamp + MINUTE <= end_ms
                and all(math.isfinite(p) for p in (low, high, close))
                and 0 < low <= close <= high):
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
        late_signal = next((
            start_ms + i * MINUTE for i, (_, _, close) in enumerate(path, 1)
            if Tracker._reached(close, base_price, 1.15)
        ), None)
    return len(path), min(bar[0] for bar in path), max(bar[1] for bar in path), path[-1][2], late_signal


async def refresh_followup_paths():
    now = time.time()
    rows = await database._run_db(lambda conn: conn.execute(
        """SELECT symbol, seed_ms, closed_at, watch_ms, base_price, status FROM large_move_paper
           WHERE followup_bars < ? AND (followup_check_at IS NULL OR followup_check_at <= ?)
                 AND ((status = 'closed' AND reason IN ('stop', 'trailing') AND closed_at <= ?)
                      OR (status = 'watch' AND seed_ms + ? <= ?))
           ORDER BY followup_check_at NULLS FIRST, watch_ms DESC LIMIT 4""",
        (FOLLOWUP_BARS, now, now - 120, WINDOW, int((now - 60) * 1000)),
    ).fetchall())

    async def fetch(row):
        expired_watch = row["status"] == "watch"
        start = row["seed_ms"] + WINDOW if expired_watch else math.ceil(row["closed_at"] / 60) * MINUTE
        query_start = row["watch_ms"] - MINUTE if expired_watch else start
        end = min(start + FOLLOWUP_BARS * MINUTE, int(now // 60) * MINUTE)
        watch_high = None
        try:
            candles = await asyncio.wait_for(
                klines(row["symbol"], "1m", (end - query_start) // MINUTE,
                       start_time_ms=query_start, end_time_ms=end - 1),
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
               FROM large_move_paper WHERE {where}""", params,
        ).fetchone()
        rows = conn.execute(
            f"""SELECT *, CASE WHEN status = 'watch' AND seed_ms + ? <= ? THEN 'expired'
                                  ELSE status END AS display_status
                FROM large_move_paper WHERE {where}
                ORDER BY (status = 'open') DESC, watch_ms DESC, symbol LIMIT 300""",
            (WINDOW, now_ms, *params),
        ).fetchall()
        return {"paper_only": True, "day": day.isoformat() if day else None,
                "initial_cash": STARTING_CASH,
                "notional": NOTIONAL, "fee_pct": FEE * 100, "trailing": {
                    "activation_pct": TRAIL_START, "initial_gap": TRAIL_INITIAL_GAP,
                    "min_gap": TRAIL_MIN_GAP, "tighten_per_point": TRAIL_TIGHTEN_PER_POINT,
                },
                "stop_pct": STOP, "hold_minutes": HOLD_SECONDS // 60,
                "followup_minutes": FOLLOWUP_BARS, "limit": 300,
                "summary": dict(stats), "rows": [dict(r) for r in rows]}
    return await database._run_db(read)


async def run(market):
    trackers: dict[str, Tracker] = {}
    queue: asyncio.Queue = asyncio.Queue(maxsize=512)
    retry_until: dict[str, float] = {}

    def on_bar(symbol, timeframe, bar):
        if (timeframe != "1m" or not bar["closed"] or not symbol.endswith("TRY")
                or symbol[:-3] in STABLE):
            return
        stamp, price = int(bar["time"]), float(bar["close"])
        if not math.isfinite(price) or price <= 0:
            return
        tracker = trackers.get(symbol)
        if tracker is None or stamp > tracker.last + MINUTE:
            tracker = trackers[symbol] = Tracker()
            history = market.klines.get("1m", {}).get(symbol, {})
            for t, p, volume in zip(*(history.get(key, [])[-61:]
                                      for key in ("timestamps", "closes", "volumes"))):
                if t < stamp and p > 0 and math.isfinite(p):
                    tracker.observe(int(t), p, volume > 0)
        alert = tracker.observe(stamp, price, bar["volume"] > 0)
        if alert and abs(time.time() - alert.stamp / 1000) <= MAX_SIGNAL_AGE:
            try:
                queue.put_nowait((symbol, alert))
            except asyncio.QueueFull:
                logger.error("Large-move paper queue full for %s", symbol)

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

    async def entry(symbol, alert):
        try:
            await save_watch(symbol, alert)
            if alert.level == 15:
                await asyncio.sleep(DELAY)
                book = await quote(symbol, lambda b: sum(p * q for p, q in b[1]) >= NOTIONAL)
                await save_entry(symbol, alert, book, time.time())
        except Exception:
            logger.exception("Large-move paper alert persistence failed for %s", symbol)

    market.add_bar_listener(on_bar)
    try:
        async with asyncio.TaskGroup() as tasks:
            async def process_entries():
                while True:
                    symbol, alert = await queue.get()
                    await entry(symbol, alert)

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

            for _ in range(8):
                tasks.create_task(process_entries())
            tasks.create_task(manage())
            tasks.create_task(track_followups())
    finally:
        market.remove_bar_listener(on_bar)
