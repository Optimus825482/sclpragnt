"""GİRİŞ GECİKMESİ RAPORU (2026-10-16) — bildirim -> paper dolum süresi ve giriş kayması.

NEDEN: 30 günlük ölçümde tek umut verici alt küme (trend_devam + skor >= 95,
brüt +0,26%) girişi bildirimden 1 adet 5m mum sonraya kayınca kenarını yitiriyor
(brüt -0,07%). Yani `monitoring_notifications.detected_at` ile `auto_paper_trades.entry_time`
arasındaki saniyeler kârlılığı belirliyor. Bu script TÜM auto_paper_trades için:

  * gecikme (entry_time - detected_at) dağılımı (p50 / p90 / max),
  * giriş kayması ((entry_price / bildirim fiyatı - 1) * 100) dağılımı,
  * mod ve hafta kırılımı,
  * gecikme kovası -> ortalama gerçekleşen pnl_pct (<=5s / 5-15 / 15-60 / >60)

çıkarır. Bildirim eşleşmesi: önce `notification_id`; boşsa (reopen / string-id)
aynı sembolde `detected_at <= entry_time` olan EN YAKIN bildirim, en çok 10 dk içinde.

SALT OKUNUR — hiçbir şey yazmaz. KULLANIM:
    DATABASE_URL=postgresql://... python backend/scripts/entry_latency_report.py
"""
from __future__ import annotations

import datetime as _dt
import os
import sys
from bisect import bisect_right

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#: id'siz eşleşmede en yakın bildirim için azami geriye bakış (sn).
FALLBACK_WINDOW_SEC = 600.0
#: Gecikme kovaları: (etiket, alt sınır (hariç), üst sınır (dahil)).
LATENCY_BUCKETS = (
    ("<=5s", -1.0, 5.0),
    ("5-15s", 5.0, 15.0),
    ("15-60s", 15.0, 60.0),
    (">60s", 60.0, float("inf")),
)


# 2026-10-15 (denetim düzeltmesi) deseni: DATABASE_URL import anında değil,
# bağlantı anında okunur (testler modülü DB'siz import eder).
def _db_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        sys.exit("HATA: DATABASE_URL ortam değişkeni tanımlı değil "
                 "(örn. postgresql://kullanici:sifre@host:5432/scalper)")
    return url


# ---------------------------------------------------------------------------
# Saf yardımcılar (testlenebilir; DB'ye dokunmaz)
# ---------------------------------------------------------------------------
def _to_sec(ts) -> float:
    """Epoch -> saniye (ms ise çevirir); geçersiz -> 0."""
    try:
        v = float(ts or 0)
    except (TypeError, ValueError):
        return 0.0
    return v / 1000.0 if v > 1e11 else v


def percentile(sorted_vals: list, q: float):
    """Doğrusal enterpolasyonlu yüzdelik (q 0-100); boş -> None."""
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    k = (len(sorted_vals) - 1) * (q / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return float(sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo))


def latency_sec(entry_time, detected_at):
    """entry_time - detected_at (sn); eksik veya negatif -> None."""
    et, dt = _to_sec(entry_time), _to_sec(detected_at)
    if et <= 0 or dt <= 0:
        return None
    lat = et - dt
    return lat if lat >= 0 else None


def slippage_pct(entry_price, notif_price):
    """(entry_price / bildirim fiyatı - 1) * 100; eksik -> None."""
    try:
        ep, npx = float(entry_price or 0), float(notif_price or 0)
    except (TypeError, ValueError):
        return None
    if ep <= 0 or npx <= 0:
        return None
    return (ep / npx - 1.0) * 100.0


def build_notif_index(notifs: list) -> dict:
    """Sembol -> (detected_at sıralı liste, paralel bildirim listesi) + id -> bildirim."""
    by_id: dict = {}
    by_sym: dict = {}
    for n in notifs:
        by_id[n["id"]] = n
        by_sym.setdefault(str(n["symbol"]).upper(), []).append(n)
    sym_idx = {}
    for sym, lst in by_sym.items():
        lst.sort(key=lambda x: _to_sec(x.get("detected_at")))
        sym_idx[sym] = ([_to_sec(x.get("detected_at")) for x in lst], lst)
    return {"by_id": by_id, "by_sym": sym_idx}


def match_notification(trade: dict, index: dict, window_sec: float = FALLBACK_WINDOW_SEC):
    """(bildirim, eşleşme_türü) — 'id' | 'fallback' | (None, 'none')."""
    nid = trade.get("notification_id")
    if nid is not None and nid in index["by_id"]:
        return index["by_id"][nid], "id"
    sym = str(trade.get("symbol") or "").upper()
    entry = _to_sec(trade.get("entry_time"))
    if sym in index["by_sym"] and entry > 0:
        times, lst = index["by_sym"][sym]
        i = bisect_right(times, entry) - 1  # detected_at <= entry_time olan en yakın
        if i >= 0 and (entry - times[i]) <= window_sec:
            return lst[i], "fallback"
    return None, "none"


def make_rows(trades: list, notifs: list, window_sec: float = FALLBACK_WINDOW_SEC) -> list:
    """Her trade için {gecikme, kayma, mod, hafta, pnl_pct, eşleşme} satırı."""
    index = build_notif_index(notifs)
    rows = []
    for t in trades:
        n, how = match_notification(t, index, window_sec)
        et = _to_sec(t.get("entry_time"))
        week = ""
        if et > 0:
            iso = _dt.datetime.fromtimestamp(et, _dt.timezone.utc).isocalendar()
            week = f"{iso[0]}-W{iso[1]:02d}"
        rows.append({
            "trade_id": t.get("id"),
            "symbol": t.get("symbol"),
            "mode": (n or {}).get("mode") or "?",
            "week": week,
            "match": how,
            "latency_sec": latency_sec(t.get("entry_time"), (n or {}).get("detected_at")) if n else None,
            "slippage_pct": slippage_pct(t.get("entry_price"), (n or {}).get("price")) if n else None,
            "pnl_pct": (float(t["pnl_pct"]) if t.get("pnl_pct") is not None
                        and str(t.get("status")) == "closed" else None),
        })
    return rows


def dist_stats(vals: list) -> dict:
    """n / p50 / p90 / max / ortalama (boşsa hepsi None, n=0)."""
    s = sorted(float(v) for v in vals if v is not None)
    if not s:
        return {"n": 0, "p50": None, "p90": None, "max": None, "mean": None}
    return {"n": len(s), "p50": percentile(s, 50), "p90": percentile(s, 90),
            "max": s[-1], "mean": sum(s) / len(s)}


def bucket_pnl(rows: list) -> list:
    """Gecikme kovası -> {n, mean_pnl_pct, win_rate}. Yalnız kapanmış + gecikmesi bilinen."""
    out = []
    for label, lo, hi in LATENCY_BUCKETS:
        pnls = [r["pnl_pct"] for r in rows
                if r.get("latency_sec") is not None and r.get("pnl_pct") is not None
                and lo < r["latency_sec"] <= hi]
        out.append({
            "bucket": label, "n": len(pnls),
            "mean_pnl_pct": (sum(pnls) / len(pnls)) if pnls else None,
            "win_rate": (sum(1 for p in pnls if p > 0) / len(pnls)) if pnls else None,
        })
    return out


def group_stats(rows: list, key: str) -> dict:
    """key (mode/week) -> {latency: dist, slippage: dist}."""
    groups: dict = {}
    for r in rows:
        groups.setdefault(r.get(key) or "?", []).append(r)
    return {g: {"latency": dist_stats([x["latency_sec"] for x in lst]),
                "slippage": dist_stats([x["slippage_pct"] for x in lst])}
            for g, lst in sorted(groups.items())}


# ---------------------------------------------------------------------------
# DB + çıktı
# ---------------------------------------------------------------------------
def _load(url: str):
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(url, connect_timeout=8, row_factory=dict_row) as conn:
        trades = conn.execute(
            "SELECT id, symbol, notification_id, entry_time, entry_price, pnl_pct, status "
            "FROM auto_paper_trades ORDER BY id").fetchall()
        notifs = conn.execute(
            "SELECT id, symbol, detected_at, price, mode FROM monitoring_notifications").fetchall()
    return trades, notifs


def _f(v, nd=2, suf=""):
    return "-" if v is None else f"{v:.{nd}f}{suf}"


def _dist_line(d: dict, nd=2, suf="") -> str:
    return (f"n={d['n']:<5} p50={_f(d['p50'], nd, suf):>9} p90={_f(d['p90'], nd, suf):>9} "
            f"max={_f(d['max'], nd, suf):>10} ort={_f(d['mean'], nd, suf):>9}")


def render(rows: list) -> str:
    L = []
    n_all = len(rows)
    by_match = {k: sum(1 for r in rows if r["match"] == k) for k in ("id", "fallback", "none")}
    L.append(f"Toplam trade: {n_all} | eşleşme: id={by_match['id']} fallback={by_match['fallback']} "
             f"eşleşmedi={by_match['none']}")
    L.append("")
    L.append("== Gecikme (sn) ==")
    L.append("  " + _dist_line(dist_stats([r["latency_sec"] for r in rows]), 1, "s"))
    lat_n = [r["latency_sec"] for r in rows if r["latency_sec"] is not None]
    if lat_n:
        for thr in (5, 15, 60):
            L.append(f"  > {thr:>2}s payı: {sum(1 for v in lat_n if v > thr) / len(lat_n) * 100:.1f}%")
    L.append("== Giriş kayması (% , + = bildirimden pahalı) ==")
    L.append("  " + _dist_line(dist_stats([r["slippage_pct"] for r in rows]), 3, "%"))
    L.append("")
    L.append("== Moda göre ==")
    for g, v in group_stats(rows, "mode").items():
        L.append(f"  {g:<12} gecikme: {_dist_line(v['latency'], 1, 's')}")
        L.append(f"  {'':<12} kayma  : {_dist_line(v['slippage'], 3, '%')}")
    L.append("")
    L.append("== Haftaya göre ==")
    for g, v in group_stats(rows, "week").items():
        L.append(f"  {g:<9} gecikme: {_dist_line(v['latency'], 1, 's')}")
        L.append(f"  {'':<9} kayma  : {_dist_line(v['slippage'], 3, '%')}")
    L.append("")
    L.append("== Gecikme kovası -> gerçekleşen pnl_pct (kapanmış) ==")
    for b in bucket_pnl(rows):
        wr = "-" if b["win_rate"] is None else f"{b['win_rate'] * 100:.1f}%"
        L.append(f"  {b['bucket']:<8} n={b['n']:<5} ort pnl_pct={_f(b['mean_pnl_pct'], 3, '%'):>9}  kazanma={wr}")
    return "\n".join(L)


def main() -> int:
    url = _db_url()
    trades, notifs = _load(url)
    print(render(make_rows(trades, notifs)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
