"""Hız Avcısı (velocity) dedektörünün `historical_candles` üzerinde ÇEVRİMDIŞI yeniden taraması.

AMAÇ: Canlı journal (`velocity_candidates`, 2026-09-16'dan başlar) 30 günle sınırlı.
Bu betik, MEVCUT dedektör mantığını (app/routers/velocity.py `scan_one`) geçmiş
1m/5m/15m mumları üzerinde her `--step-min` dakikada bir çalıştırır ve geçen
adayları `velocity_candidates` şeklinde (candidate_id `rescan:{sym}:{tick_ms}:{h}`)
üretir; böylece mevcut replay'ler 60 günlük pencereyi ölçebilir.

İLERİYE BAKMAMA: her tick'te yalnız o anda KAPANMIŞ barlar (open+tf <= tick)
kullanılır (`app.rescan.scan.closed_before`). Sadakat ve sapma listesi:
docs/RESCAN_HARNESS.md.

KULLANIM (backend/ içinden):
  .venv/Scripts/python.exe scripts/rescan_velocity_history.py \
      --start 2026-08-17 --end 2026-10-16 --step-min 5 \
      --universe top-gainers-daily --write none --out work/rescan.jsonl --validate
  ... --symbols FILTRY,BTCTRY --max-symbols 5 (duman testi)
  ... --write db --replace   (DB'ye yazar; status='rescan', retention 30 gün -> belgeye bak)

Ortam: DATABASE_URL (yoksa --db-url). Ağa ÇIKMAZ.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCALPER_ENV", "development")
os.environ.setdefault("SCALPER_ADMIN_PASSWORD", "x")

from app.config import config  # noqa: E402
from app.routers import velocity as V  # noqa: E402
from app.rescan import scan as S  # noqa: E402
from app.rescan import series as SE  # noqa: E402
from app.rescan import validate as VAL  # noqa: E402

_TZ_FALLBACK = dt.timezone(dt.timedelta(hours=3))
HORIZONS = (5, 15)
WARMUP_MS = 2 * 86_400_000  # 24s ticker + 15m×129 (~32s) için


def _tz():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("Europe/Istanbul")
    except Exception:
        return _TZ_FALLBACK


def parse_when(s: str, *, end: bool = False) -> int:
    """'YYYY-MM-DD' (Istanbul gece yarısı; end=True -> ertesi gece yarısı, yani gün dâhil)
    veya ISO datetime -> epoch ms."""
    s = str(s).strip()
    tz = _tz()
    if len(s) == 10:
        d = dt.datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=tz)
        if end:
            d = d + dt.timedelta(days=1)
        return int(d.timestamp() * 1000)
    d = dt.datetime.fromisoformat(s)
    if d.tzinfo is None:
        d = d.replace(tzinfo=tz)
    return int(d.timestamp() * 1000)


def db_url(arg: str | None) -> str:
    url = arg or os.getenv("DATABASE_URL") or ""
    if not url:
        raise SystemExit("DATABASE_URL yok; --db-url ver.")
    return url


# ------------------------------------------------------------------ yükleme --

def load_symbols_with_tf(conn, tf: str, start_ms: int, end_ms: int) -> dict[str, int]:
    rows = conn.execute(
        "SELECT symbol, count(*) FROM historical_candles WHERE timeframe=%s "
        "AND open_time >= %s AND open_time < %s GROUP BY symbol ORDER BY symbol",
        (tf, start_ms, end_ms)).fetchall()
    return {str(r[0]).upper(): int(r[1]) for r in rows}


def load_series(conn, symbol: str, tf: str, start_ms: int, end_ms: int) -> SE.SymbolSeries | None:
    rows = conn.execute(
        "SELECT open_time, open, high, low, close, volume, close_time, "
        "COALESCE(quote_volume, 0), COALESCE(trade_count, 0), taker_buy_base_volume FROM historical_candles "
        "WHERE symbol=%s AND timeframe=%s AND open_time >= %s AND open_time < %s ORDER BY open_time",
        (symbol, tf, start_ms, end_ms)).fetchall()
    if not rows:
        return None
    arr = np.asarray(rows, dtype=np.float64)
    return SE.SymbolSeries(symbol, tf, arr)


def load_prof_atr(conn, spec: str) -> dict[str, float | None]:
    """'db' -> llm_settings (canlı `load_velocity_atr_profiles` ile aynı kelepçe);
    'default' -> hepsi None (VELOCITY_MIN_ATR_PCT); '5m=0.1,15m=0.1' -> açık değer."""
    out: dict[str, float | None] = {f"{h}m": None for h in HORIZONS}
    if spec == "default":
        return out
    if spec == "db":
        for h in HORIZONS:
            key = f"velocity_min_atr_pct_{h}m"
            row = conn.execute("SELECT value FROM llm_settings WHERE key=%s", (key,)).fetchone()
            if row and row[0]:
                max_allowed = V.VELOCITY_PROFILE_CALIB.get(f"{h}m", {}).get("max_atr", 0.50)
                out[f"{h}m"] = min(max_allowed, round(float(row[0]), 2))
        return out
    for part in spec.split(","):
        k, v = part.split("=")
        out[k.strip()] = float(v)
    return out


def load_min_atr(conn, spec: str) -> float:
    """Canlı global eşik: DB `velocity_min_atr_pct` > env/sabit (VELOCITY_MIN_ATR_PCT)."""
    if spec == "db":
        row = conn.execute("SELECT value FROM llm_settings WHERE key=%s", ("velocity_min_atr_pct",)).fetchone()
        if row and row[0]:
            return round(float(row[0]), 2)
    return float(V.VELOCITY_MIN_ATR_PCT)


def load_learned_targets(conn) -> dict[str, tuple[float, int]]:
    try:
        rows = conn.execute("SELECT symbol, target_pct, total_count FROM symbol_target_state").fetchall()
    except Exception:
        return {}
    out = {}
    for sym, tgt, cnt in rows:
        try:
            if tgt and float(tgt) > 0:
                out[str(sym).upper()] = (float(tgt), int(cnt or 0))
        except (TypeError, ValueError):
            continue
    return out


def load_live_candidates(conn, symbols: set[str], start_ms: int, end_ms: int) -> list[dict]:
    rows = conn.execute(
        "SELECT candidate_id, created_at, symbol, velocity_score, target_pct, price FROM velocity_candidates "
        "WHERE passes AND created_at >= %s AND created_at < %s AND candidate_id LIKE 'vel-%%' "
        "ORDER BY created_at", (start_ms / 1000.0, end_ms / 1000.0)).fetchall()
    out = []
    for cid, ts, sym, score, tgt, px in rows:
        sym = str(sym).upper()
        if sym not in symbols:
            continue
        h = V._velocity_horizon_from_candidate_id(str(cid))
        if h not in HORIZONS:
            continue
        out.append({"candidate_id": cid, "created_at": float(ts), "symbol": sym, "horizon_minutes": h,
                    "velocity_score": float(score or 0.0), "target_pct": float(tgt or 0.0), "price": float(px or 0.0)})
    return out


# ------------------------------------------------------------------- yazma --

def write_jsonl(path: str, rows: list[dict]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")


def write_db(conn, rows: list[dict], *, replace: bool, start_ms: int, end_ms: int) -> int:
    """`velocity_candidates`'a yazar. status='rescan' (canlı öğrenme döngüsü yalnız
    'pending' okur; kalibrasyon istatistiği 'evaluated' sayar -> kirlenme yok).
    Mevcut kolonlara dokunulmaz; ek alanlar outcome_details JSON'una gömülür."""
    cur = conn.cursor()
    if replace:
        cur.execute("DELETE FROM velocity_candidates WHERE candidate_id LIKE 'rescan:%%' "
                    "AND created_at >= %s AND created_at < %s", (start_ms / 1000.0, end_ms / 1000.0))
    sql = ("INSERT INTO velocity_candidates (candidate_id, created_at, symbol, price, target_pct, atr_pct, "
           "volume_ratio, ret3_pct, velocity_score, passes, rank, status, outcome_details) "
           "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'rescan',%s::jsonb) ON CONFLICT (candidate_id) DO NOTHING")
    n = 0
    batch = []
    for r in rows:
        details = {"source": "rescan", "horizon_minutes": r["horizon_minutes"], "mode": r.get("mode"),
                   "pool_source": r.get("pool_source"), "change_24h": r.get("change_24h"),
                   "m5_pattern": r.get("m5_pattern"), "m5_pattern_ok": r.get("m5_pattern_ok"),
                   "leading_ok": r.get("leading_ok"), "m1_atr_prev": r.get("m1_atr_prev"),
                   "m3_atr_prev": r.get("m3_atr_prev"), "radar": r.get("radar") or {}}
        batch.append((r["candidate_id"], r["created_at"], r["symbol"], r["price"], r["target_pct"], r["atr_pct"],
                      r["volume_ratio"], r["ret3_pct"], r["velocity_score"], r["passes"], r["rank"],
                      json.dumps(details, default=str)))
        if len(batch) >= 2000:
            cur.executemany(sql, batch); n += len(batch); batch = []
    if batch:
        cur.executemany(sql, batch); n += len(batch)
    conn.commit()
    return n


# -------------------------------------------------------------------- ana --

def run(args) -> int:
    import psycopg
    url = db_url(args.db_url)
    start_ms = parse_when(args.start)
    end_ms = min(parse_when(args.end, end=True), int(time.time() * 1000))
    step_ms = int(args.step_min) * 60_000
    first_tick = ((start_ms + step_ms - 1) // step_ms) * step_ms  # ızgaraya yukarı yuvarla
    ticks = np.arange(first_tick, end_ms, step_ms, dtype=np.int64)
    if len(ticks) == 0:
        raise SystemExit("tick yok (start/end?)")
    load_from = start_ms - WARMUP_MS
    t0 = time.time()
    with psycopg.connect(url, connect_timeout=10) as conn:
        syms_1m = load_symbols_with_tf(conn, "1m", load_from, end_ms)
        syms_5m = load_symbols_with_tf(conn, "5m", load_from, end_ms)
        if args.symbols:
            want = {s.strip().upper() for s in args.symbols.split(",") if s.strip()}
            syms_1m = {k: v for k, v in syms_1m.items() if k in want}
        scan_syms = sorted(syms_1m)
        if args.max_symbols:
            scan_syms = scan_syms[:int(args.max_symbols)]
        all_syms = sorted(set(syms_5m) | set(scan_syms))
        prof_atr = load_prof_atr(conn, args.prof_atr)
        min_atr = load_min_atr(conn, args.prof_atr if args.prof_atr in ("db", "default") else "db")
        learned = load_learned_targets(conn) if args.learned_target == "db" else {}
        print(f"[rescan] pencere {args.start}..{args.end} tick={len(ticks)} (adım {args.step_min} dk) | "
              f"1m sembol={len(syms_1m)} taranacak={len(scan_syms)} | 5m evren={len(syms_5m)} | "
              f"prof_atr={prof_atr} min_atr={min_atr} | evren={args.universe} spread={args.spread_mode}")
        if not scan_syms:
            print("[rescan] 1m verisi olan sembol yok — geri doldurma bekleniyor.")
            return 2
        # ---- Faz 1: havuz (24s ticker aynası + discovery) ----
        tick24: dict[str, dict] = {}
        disc: dict[str, dict] = {}
        if args.universe == "top-gainers-daily":
            for n, sym in enumerate(all_syms, 1):
                s5 = load_series(conn, sym, "5m", load_from, end_ms)
                if s5 is not None:
                    tick24[sym] = SE.ticker_24h_at_ticks(s5, ticks)
                if not args.no_discovery and sym in syms_1m:
                    s1 = load_series(conn, sym, "1m", load_from, end_ms)
                    if s1 is not None:
                        disc[sym] = SE.discovery_at_ticks(s1, ticks)
                if n % 25 == 0 or n == len(all_syms):
                    print(f"[faz1] {n}/{len(all_syms)} sembol | {time.time() - t0:.0f} sn", flush=True)
        in_pool, src = SE.build_pool_matrix(all_syms, tick24, disc or None, len(ticks), universe=args.universe)
        sym_index = {s: i for i, s in enumerate(all_syms)}
        pool_sizes = in_pool.sum(axis=0)
        print(f"[faz1] havuz boyutu/tick: ort={pool_sizes.mean():.1f} min={pool_sizes.min()} max={pool_sizes.max()} "
              f"| {time.time() - t0:.0f} sn", flush=True)
        # ---- Faz 2: sembol başına tam tarama ----
        per_tick: dict[tuple[int, int], list[dict]] = {}
        stats = {"evaluated": 0, "passes": 0, "prefilter_ticks": 0, "pool_ticks": 0, "skipped_no_5m": 0}
        t_scan = time.time()
        for n, sym in enumerate(scan_syms, 1):
            si = sym_index[sym]
            s1 = load_series(conn, sym, "1m", load_from, end_ms)
            if s1 is None or len(s1) < 30:
                continue
            s5 = load_series(conn, sym, "5m", load_from, end_ms)
            s15 = load_series(conn, sym, "15m", load_from, end_ms)
            if s5 is None:
                stats["skipped_no_5m"] += 1
            feats = SE.bar_features(s1.arr)
            masks = {h: SE.prefilter_mask(feats, prof_atr=S.profile_atr_threshold(prof_atr[f"{h}m"], min_atr),
                                          min_atr_pct=min_atr) for h in HORIZONS}
            any_mask = np.zeros(len(s1), dtype=bool)
            for m in masks.values():
                any_mask |= m
            # tick -> kapanmış bar indeksi
            jidx = np.searchsorted(s1.open_time, ticks - s1.tf_ms, side="right") - 1
            valid = (jidx >= 29) & in_pool[si]
            stats["pool_ticks"] += int(in_pool[si].sum())
            # bayatlık: son bar tick'ten > 180 sn eski ise canlı eler
            jsafe = np.clip(jidx, 0, len(s1) - 1)
            fresh = (ticks - (s1.open_time[jsafe] + 59_999)) <= 180_000
            cand_ticks = np.nonzero(valid & fresh & any_mask[jsafe])[0]
            stats["prefilter_ticks"] += len(cand_ticks)
            t24 = tick24.get(sym)
            lt = learned.get(sym)
            for ti in cand_ticks:
                tick = int(ticks[ti])
                j = int(jidx[ti])
                rows1 = s1.arr[max(0, j - S.M1_BARS + 1):j + 1].tolist()
                rows5 = s5.window_rows(tick, S.M5_BARS) if s5 is not None else []
                rows15 = s15.window_rows(tick, S.M15_BARS) if s15 is not None else []
                chg = float(t24["change"][ti]) if (t24 is not None and np.isfinite(t24["change"][ti])) else None
                qv = float(t24["qvol"][ti]) if (t24 is not None and np.isfinite(t24["qvol"][ti])) else None
                for h in HORIZONS:
                    if not masks[h][j]:
                        continue
                    stats["evaluated"] += 1
                    cand = S.scan_symbol_at_tick(
                        sym, rows1, rows5, rows15, horizon_minutes=h, tick_ms=tick,
                        prof_atr=prof_atr[f"{h}m"], min_atr_pct=min_atr, change_24h=chg, quote_vol_24h=qv,
                        spread_mode=args.spread_mode,
                        learned_target=lt[0] if lt else None, learned_count=lt[1] if lt else 0,
                        pool_source=SE.pool_source_name(src[si, ti]))
                    if cand and cand["passes"]:
                        stats["passes"] += 1
                        cand.pop("ml_features_5m", None)
                        per_tick.setdefault((tick, h), []).append(cand)
            if n % 5 == 0 or n == len(scan_syms):
                el = time.time() - t_scan
                eta = el / n * (len(scan_syms) - n)
                print(f"[faz2] {n}/{len(scan_syms)} {sym:<12} geçen={stats['passes']} değerlendirilen={stats['evaluated']} "
                      f"| {el:.0f} sn, kalan ~{eta:.0f} sn", flush=True)
        # ---- Sıralama + journal kuralı ----
        out_rows: list[dict] = []
        for (tick, h), cands in sorted(per_tick.items()):
            out_rows.extend(S.rank_tick(cands, rank_limit=args.rank_limit, journal_cap=args.journal_cap))
        print(f"[rescan] bitti: tick={len(ticks)} havuz-tick={stats['pool_ticks']} ön-filtre={stats['prefilter_ticks']} "
              f"tam-değerlendirme={stats['evaluated']} geçen={stats['passes']} journal-satırı={len(out_rows)} "
              f"| toplam {time.time() - t0:.0f} sn", flush=True)
        if args.out:
            write_jsonl(args.out, out_rows)
            print(f"[rescan] JSONL -> {args.out} ({len(out_rows)} satır)")
        if args.write == "db":
            n = write_db(conn, out_rows, replace=args.replace, start_ms=start_ms, end_ms=end_ms)
            print(f"[rescan] velocity_candidates <- {n} satır (status='rescan', candidate_id 'rescan:%')")
        if args.validate:
            live = load_live_candidates(conn, set(scan_syms), start_ms, end_ms)

            def _in_pool(symbol: str, created_at: float):
                si = sym_index.get(symbol)
                if si is None:
                    return None
                ti = int(np.searchsorted(ticks, int(created_at * 1000), side="right")) - 1
                if ti < 0:
                    return None
                return bool(in_pool[si, ti])

            report = VAL.validate(live, out_rows, tol_s=args.tol_min * 60.0, in_pool_fn=_in_pool)
            print("\n[doğrulama] canlı velocity_candidates (passes=true, vel-5dk/15dk, taranan semboller) ↔ rescan")
            print(VAL.format_table(report))
            if args.validate_json:
                with open(args.validate_json, "w", encoding="utf-8") as fh:
                    json.dump(report, fh, ensure_ascii=False, indent=2, default=str)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", required=True, help="YYYY-MM-DD (Istanbul) veya ISO datetime")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD (gün dâhil) veya ISO datetime")
    ap.add_argument("--step-min", type=int, default=5, help="tarama adımı dk (varsayılan 5)")
    ap.add_argument("--symbols", default="", help="virgüllü sembol listesi (yalnız bunlar taranır)")
    ap.add_argument("--max-symbols", type=int, default=0, help="duman testi: ilk N sembol")
    ap.add_argument("--universe", choices=("all", "top-gainers-daily"), default="top-gainers-daily")
    ap.add_argument("--no-discovery", action="store_true", help="discovery (1m patlama) havuzunu atla")
    ap.add_argument("--write", choices=("none", "db"), default="none")
    ap.add_argument("--replace", action="store_true", help="--write db: penceredeki eski rescan satırlarını sil")
    ap.add_argument("--out", default="", help="JSONL çıktı yolu")
    ap.add_argument("--validate", action="store_true", help="canlı journal ile karşılaştır")
    ap.add_argument("--validate-json", default="", help="doğrulama raporunu JSON'a yaz")
    ap.add_argument("--tol-min", type=float, default=5.0, help="eşleşme toleransı dk (varsayılan 5)")
    ap.add_argument("--prof-atr", default="db", help="'db' | 'default' | '5m=0.1,15m=0.1'")
    ap.add_argument("--spread-mode", choices=("unknown", "known"), default="known",
                    help="'known' (varsayılan): canlıda orderflow WS anlık görüntüsü var -> x0.85 cezası YOK "
                         "(62 canlı adayda skor oranı medyanı tam 0.85 ölçüldü); 'unknown': fail-closed cezası uygula")
    ap.add_argument("--learned-target", choices=("off", "db"), default="off",
                    help="symbol_target_state (BUGÜNKÜ anlık görüntü; geçmişe sızar) — varsayılan kapalı")
    ap.add_argument("--rank-limit", type=int, default=10, help="canlı monitoring limit (rank verilen ilk N)")
    ap.add_argument("--journal-cap", type=int, default=20, help="tick+ufuk başına yazılan geçen aday (0=hepsi)")
    ap.add_argument("--db-url", default="")
    ap.add_argument("--no-exhaustion-gate", action="store_true",
                    help="ANALİZ: MFI/RSI aşırı alım kapısını kapat (VELOCITY_MFI_UPPER/RSI_UPPER=inf); "
                         "satırlardaki `exhausted` alanı canlıda elenecek adayı etiketler")
    args = ap.parse_args(argv)
    if args.no_exhaustion_gate:
        # Yalnız bu süreçte; `scan_symbol_at_tick` eşikleri `V.` üzerinden çağrı anında okur.
        V.VELOCITY_MFI_UPPER = float("inf")
        V.VELOCITY_RSI_UPPER = float("inf")
        print("[rescan] ANALİZ MODU: aşırı alım kapısı (MFI/RSI üst eşik) KAPALI")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
