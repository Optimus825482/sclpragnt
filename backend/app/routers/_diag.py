"""AUTH'suz SALT-OKUNUR teşhis ucu (2026-11-10).

NEDEN: canlı sunucudaki paper işlem sonuçları (özellikle stop_loss ortalaması
-5,5%) API oturumu olmadan incelenemiyordu. Kullanıcı auth bilgisi paylaşmak
zorunda kalıyordu.

GÜVENLİK TASARIMI (önemli — bu uç auth'suz olduğu için veri sızdırmamalı):
  1) TOKEN ZORUNLU: ?t=<SCALPER_DIAG_TOKEN>. Env tanımlı değilse uç 404 döner
     (varsayılan KAPALI). Token sabit-zamanlı karşılaştırılır.
  2) TOPLULAŞTIRMA ZORUNLU: yalnız sayım/ortalama/dağılım döner. Tekil işlem
     satırı, sembol adı, fiyat, kullanıcı adı, e-posta ASLA dönmez.
  3) SALT-OKUNUR: yalnız select; hiçbir yazma yok.
  4) Sayısal kovalama: sembolleri maskelemek yerine HISTOGRAM döner
     (sl_pct buckets). Böylece karar verilebilir ama tersine mühendislik
     yapılamaz.

ÖLÇTÜĞÜ SORU: canlıda stop_loss neden -5,5% ortalama veriyor?
  - sl_pct dağılımı: SL seviyesi kaç %'de duruyor (2,0 beklenir, 4,0 çıkarsa
    eski ayar / plan profili demektir)
  - exit_reason × ortalama pnl
  - entry_time günlük dağılım (hangi günlerde işlem açılmış)
  - plan/profile etkisi
"""
from __future__ import annotations

import hmac
import os
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app import database

router = APIRouter()


def _token() -> str:
    return os.getenv("SCALPER_DIAG_TOKEN", "").strip()


def _check(t: str | None) -> None:
    expected = _token()
    # Env yoksa uc KAPALI. 404 döner: varlığı bile sızdırılmaz.
    if not expected:
        raise HTTPException(status_code=404, detail="Not Found")
    if not t or not hmac.compare_digest(str(t), expected):
        raise HTTPException(status_code=404, detail="Not Found")


def _n(v: Any) -> float | None:
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _r(v: Any, d: int = 3) -> float | None:
    x = _n(v)
    return None if x is None else round(x, d)


@router.get("/_diag/paper")
async def paper_diag(request: Request, t: str | None = None, days: int = 90):
    """Paper işlem sonuçlarının TOPLULAŞTIRILMIŞ teşhisi (auth'suz, token'lı)."""
    _check(t)
    days = max(1, min(int(days), 365))
    since = time.time() - days * 86400
    out: dict[str, Any] = {
        "ok": True, "days": days, "generated_at": int(time.time()),
        "note": ("Yalnız toplulaştırılmış ölçüm. Tekil işlem/sembol/fiyat "
                 "dönmez."),
        "error": None,
    }

    def _head(conn):
        cur = conn.execute(
            """select count(*) c,
                      sum(case when status = 'open' then 1 else 0 end) open_c,
                      min(entry_time) mn, max(entry_time) mx
                 from auto_paper_trades""")
        return dict(cur.fetchone() or {})

    def _reasons(conn):
        cur = conn.execute(
            """select coalesce(exit_reason, '(yok)') reason, count(*) c,
                      avg(pnl_pct) m, min(pnl_pct) lo, max(pnl_pct) hi,
                      avg(case when pnl_pct > 0 then 1.0 else 0.0 end) winr
                 from auto_paper_trades
                where entry_time >= ? and status <> 'open'
                group by 1 order by 2 desc""", (since,))
        return [dict(r) for r in cur.fetchall()]

    def _sl_hist(conn):
        # SL yüzdesi kovaları: seviye kaçta duruyor?
        cur = conn.execute(
            """select round(((stop_loss / entry_price) * 100 - 100)::numeric, 1) b,
                      count(*) c
                 from auto_paper_trades
                where entry_time >= ? and exit_reason = 'stop_loss'
                  and entry_price > 0 and stop_loss > 0
                group by 1 order by 2 desc""", (since,))
        return [dict(r) for r in cur.fetchall()]

    def _daily(conn):
        cur = conn.execute(
            """select to_char(to_timestamp(entry_time), 'YYYY-MM-DD') d,
                      count(*) c, avg(pnl_pct) m
                 from auto_paper_trades
                where entry_time >= ? and status <> 'open'
                group by 1 order by 1 desc limit 30""", (since,))
        return [dict(r) for r in cur.fetchall()]

    def _profile(conn):
        # exit_profile -> SL yuzdesi ve pnl iliskisi (ATR kolonu YOK).
        cur = conn.execute(
            """select coalesce(exit_profile, '(yok)') p, count(*) c,
                      avg(pnl_pct) m,
                      avg(case when entry_price > 0 and stop_loss > 0
                               then ((stop_loss / entry_price) * 100 - 100) end) slp
                 from auto_paper_trades
                where entry_time >= ? and status <> 'open'
                group by 1 order by 2 desc""", (since,))
        return [dict(r) for r in cur.fetchall()]

    try:
        head = await database._run_db(_head) or {}
        out["total_trades_all_time"] = int(_n(head.get("c")) or 0)
        out["open_now"] = int(_n(head.get("open_c")) or 0)
        out["first_trade_at"] = _n(head.get("mn"))
        out["last_trade_at"] = _n(head.get("mx"))
        out["last_trade_age_days"] = (
            round((time.time() - out["last_trade_at"]) / 86400, 1)
            if out["last_trade_at"] else None)

        out["by_reason"] = [
            {"reason": r["reason"], "n": int(r["c"]),
             "avg_pnl_pct": _r(r["m"]), "min_pnl_pct": _r(r["lo"]),
             "max_pnl_pct": _r(r["hi"]), "win_rate": _r((_n(r["winr"]) or 0) * 100, 1)}
            for r in await database._run_db(_reasons)
        ]
        out["sl_pct_histogram"] = [
            {"sl_pct": _r(r["b"], 1), "n": int(r["c"])}
            for r in await database._run_db(_sl_hist)
        ]
        out["daily"] = [
            {"day": r["d"], "n": int(r["c"]), "avg_pnl_pct": _r(r["m"])}
            for r in await database._run_db(_daily)
        ]
        out["by_profile"] = [
            {"profile": r["p"], "n": int(r["c"]),
             "avg_pnl_pct": _r(r["m"]), "avg_sl_pct": _r(r["slp"], 2)}
            for r in await database._run_db(_profile)
        ]
        # Ozet: kazanan/kaybeden asimetrisi
        tot = sum(i["n"] for i in out["by_reason"])
        wins = sum(i["n"] for i in out["by_reason"]
                   if (i["avg_pnl_pct"] or 0) > 0)
        out["summary"] = {
            "closed_trades": tot,
            "win_rate_pct": _r(100.0 * wins / tot, 1) if tot else None,
        }
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out
