"""Sinyal İzleme API'si (2026-11-10).

LLM/otonom paper kararlarının ARKASINDAKİ ölçülmüş kanıtı ve canlı filtre
davranışını tek ekranda gösterir. Amaç: "bu parametreler canlıda ne yapıyor?"
sorusunu panelden cevaplanabilir kılmak.

Uçlar:
  GET /api/signal-insights/overview   → aktif parametreler + filtre sayaçları
  GET /api/signal-insights/evidence   → ölçülmüş hipotez tablosu (statik)
  GET /api/signal-insights/outcomes   → canlı işlem sonuçları (son N gün)

NOT: Ağır sorgular yok — sayaçlar zaman aralıklı GROUP BY, sonuçlar indeksli
auto_paper_trades üzerinden. Her uç fail-open: hata olursa boş/None döner,
panel çökmez.
"""
from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Request

from app import config, database

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/signal-insights", tags=["signal-insights"])


def _num(value, default=None):
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# 1) Aktif parametreler + filtre sayaçları
# ---------------------------------------------------------------------------

async def _active_params() -> dict:
    """Panelde geçerli (DB varsa DB, yoksa config) sinyal parametreleri."""
    from app.routers.auto_paper import get_auto_paper_settings
    try:
        s = await get_auto_paper_settings()
    except Exception as exc:  # noqa: BLE001 — panel çökmemeli
        logger.debug("signal_insights: ayarlar okunamadı: %s", exc)
        s = {}
    return {
        "min_atr_pct": _num(s.get("min_atr_pct"),
                            _num(getattr(config, "AUTO_PAPER_MIN_ATR_PCT", 0.0))),
        "min_oi_change_pct": _num(s.get("min_oi_change_pct"),
                                  _num(getattr(config, "AUTO_PAPER_MIN_OI_CHANGE_PCT", 0.0))),
        "oi_window_min": _num(s.get("oi_window_min"),
                              _num(getattr(config, "AUTO_PAPER_OI_WINDOW_MIN", 15.0))),
        "max_sl_tp_ratio": _num(s.get("max_sl_tp_ratio"),
                                _num(getattr(config, "AUTO_PAPER_MAX_SL_TP_RATIO", 0.0))),
        "trailing_enabled": bool(s.get("trailing_enabled",
                                       getattr(config, "AUTO_PAPER_TRAILING_ENABLED", True))),
        "trailing_trigger_pct": _num(s.get("trailing_trigger_pct"),
                                     _num(getattr(config, "AUTO_PAPER_TRAILING_TRIGGER_PCT", 2.0))),
        "trailing_gap_pct": _num(s.get("trailing_gap_pct"),
                                 _num(getattr(config, "AUTO_PAPER_TRAILING_GAP_PCT", 1.0))),
    }


async def _filter_counts(hours: int = 24) -> dict:
    """Son N saatte kaç aday geldi, kaçı hangi kapıda elendi.

    Aday üretimi: velocity_candidates.created_at (epoch SANİYE).
    Kayıplar: notifications tablosunda block_reason benzeri alanlar yerine
    en güvenilir kaynak velocity_candidates + auto_paper_trades. Filtre
    kapılarının kaç adayı elediğini göstermek için OI/ATR eşiklerini AYNI
    veri üzerinde YENİDEN uygularız (gerçek kararlar değil, "şu an kaçı
    elenirdi" göstergesi) — bu yüzden ayrıca 'applied' alanı işaretlenir.
    """
    since = time.time() - hours * 3600
    out = {
        "window_hours": hours,
        "candidates": None,
        "with_oi": None,
        "with_atr_pct": None,
        "atr_rejected": None,
        "oi_rejected": None,
        "passed": None,
        "mode": "estimate",
        "error": None,
    }
    try:
        p = await _active_params()

        def _op(conn):
            cur = conn.execute(
                """select count(*) c,
                          count(atr_pct) atr,
                          avg(atr_pct) avg_atr,
                          sum(case when coalesce(atr_pct,0) < ? then 1 else 0 end) atr_rej
                     from velocity_candidates
                    where created_at >= ?""",
                (p["min_atr_pct"], since),
            )
            row = cur.fetchone()
            return dict(row) if row else None

        r = await database._run_db(_op)
    except Exception as exc:  # noqa: BLE001
        logger.debug("signal_insights: filtre sayaçları alınamadı: %s", exc)
        out["error"] = type(exc).__name__
        return out
    if not r:
        return out
    total = int(r["c"] or 0)
    atr_rej = int(r["atr_rej"] or 0)
    out.update({
        "candidates": total,
        "with_atr_pct": int(r["atr"] or 0),
        "avg_atr_pct": round(_num(r["avg_atr"], 0.0), 3),
        "atr_rejected": atr_rej,
        "with_oi": None,
        "oi_rejected": None,
        "passed": max(0, total - atr_rej),
    })
    return out


async def _processing_lag() -> dict:
    """En son aday ne zaman üretildi (akış canlı mı, 'BAYAT' var mı)."""
    def _op(conn):
        cur = conn.execute("select max(created_at) m, count(*) c from velocity_candidates")
        row = cur.fetchone()
        return dict(row) if row else None

    try:
        row = await database._run_db(_op)
    except Exception as exc:  # noqa: BLE001
        logger.debug("signal_insights: tazelik okunamadı: %s", exc)
        return {"last_candidate_at": None, "age_sec": None, "total": None}
    if not row:
        return {"last_candidate_at": None, "age_sec": None, "total": None}
    last = _num(row["m"])
    return {
        "last_candidate_at": last,
        "age_sec": (time.time() - last) if last else None,
        "total": int(row["c"] or 0),
    }


@router.get("/overview")
async def overview(request: Request):
    """Aktif parametreler + son 24s filtre sayaçları + akış tazeliği."""
    params = await _active_params()
    return {
        "ok": True,
        "params": params,
        "filters_24h": await _filter_counts(24),
        "freshness": await _processing_lag(),
        "note": (
            "ATR sayacı gerçek veridir (velocity_candidates.atr_pct). OI sayaçları "
            "None: OI değişimi canlıda yalnız bildirim akışında hesaplanıyor ve "
            "DB'ye yazılmıyor — OI kabul/ret sayısı bu yüzden ölçülemiyor. "
            "'passed' = adaylar − ATR'de elenenler (OI etkisi hariç)."
        ),
    }


# ---------------------------------------------------------------------------
# 2) Ölçülmüş kanıt tablosu (statik — dokümanlardan derlendi)
# ---------------------------------------------------------------------------

# Her satır: hipotez, durum (applied/rejected/unmeasured), özet, kanıt, kaynak
EVIDENCE: list[dict] = [
    {"id": "atr", "name": "ATR (volatilite) tabanı", "status": "applied",
     "summary": "ATR≥1,0% → kazanan oranı %34→%50",
     "detail": "Gerçek 1m mum, trailing çıkış, 5 seed: +0,364% (sd 0,168).",
     "source": "§12", "param": "min_atr_pct"},
    {"id": "atr_threshold", "name": "ATR eşiği 1,0 vs 1,5", "status": "applied",
     "summary": "1,5 daha yüksek ortalama ama sd 2,4× → 1,0 seçildi",
     "detail": "1,5 → +0,647%/sd 0,406 (n 38); 1,0 → +0,364%/sd 0,168 (n 114). Aynı güven için 9× işlem gerekir.",
     "source": "§12", "param": "min_atr_pct"},
    {"id": "oi", "name": "Açık pozisyon (OI) değişimi", "status": "applied",
     "summary": "TEK gerçek öncü gösterge: +0,917% (ATR'nin 2,5 katı)",
     "detail": "Q1 (düşük OI) kazanan %18-30 → Q5 %40-51. 5/5 seed pozitif.",
     "source": "§19", "param": "min_oi_change_pct"},
    {"id": "oi_window", "name": "OI ölçüm penceresi", "status": "applied",
     "summary": "60 dk keyfiydi → 15 dk kazandı (+0,502 → +0,878)",
     "detail": "4/4 seed'de 15 dk en iyi, monoton (15>20>30>60>120>240). Alt sınır 15 (veri 5 dk aralıklı).",
     "source": "§23", "param": "oi_window_min"},
    {"id": "atr_oi", "name": "ATR × OI birlikte", "status": "applied",
     "summary": "Eski 'iptal' bulgusu YANLIŞTI — tamamlayıcılar",
     "detail": "OI, ATR sabitken de ayrıştırıyor (ATR<1 içinde +0,565, ATR≥1 içinde +0,819). Birlikte +0,495 vs tek başına +0,24 (sinerji 3/4 seed).",
     "source": "§24", "param": None},
    {"id": "oi_threshold", "name": "OI eşiği değeri", "status": "applied",
     "summary": "1,2% seçildi (ATR tabanının 2,5 katı)",
     "detail": "4 seed, ATR≥1 açıkken: 0,0→+0,794 | 0,8→+0,883 | 1,2→+0,939 | 3,0→+1,213. 3,0 reddedildi: sd 2,4×, örneklem %37 az.",
     "source": "§25", "param": "min_oi_change_pct"},
    {"id": "sl_tp", "name": "SL/TP oranı (max_sl_tp_ratio)", "status": "applied",
     "summary": "0,64 → SL kısalt (TP'ye dokunmaz)",
     "detail": "Asimetri: kazanç +1,595% / kayıp −2,915% (oran 0,547, gereken 0,764). 0,64 → ortalama −0,724% (önce −0,796%).",
     "source": "§§", "param": "max_sl_tp_ratio"},
    {"id": "trailing", "name": "Trailing çıkış (2,0 / 1,0)", "status": "kept",
     "summary": "4 kez tarandı — mevcut değer doğru",
     "detail": "Geniş evrende 1,5/0,5 iyi göründü; filtreli (canlı) evrende mevcut 2,0/1,0 açık ara en iyi (+1,124% vs +0,935%). Çıkış parametreleri EVRENE ÖZEL.",
     "source": "§§§", "param": "trailing_trigger_pct"},
    {"id": "velocity", "name": "velocity_score", "status": "rejected",
     "summary": "ÖLÜ sinyal — r=0,0002, sıralama TERS",
     "detail": "Yüksek skor daha kötü sonuç veriyor. Kullanılmamalı.",
     "source": "§1", "param": None},
    {"id": "relstrength", "name": "Göreli güç (ret15)", "status": "rejected",
     "summary": "Reddedildi (+0,096/+0,144, ATR ile ters dönüyor)",
     "detail": "ATR filtresiyle birlikte katkı yok.",
     "source": "§?", "param": None},
    {"id": "funding", "name": "Funding ters sinyal", "status": "rejected",
     "summary": "Marjinal: filtresiz −0,254 → funding≤0,005 −0,233 (kazanç +0,021)",
     "detail": "Yön doğru (aşırı pozitif funding = en kötü dilim) ama filtre değeri yetersiz.",
     "source": "§13", "param": None},
    {"id": "orderflow", "name": "Order flow / taker buy", "status": "rejected",
     "summary": "Ayrıştırmıyor; AŞIRI uç TERS çalışıyor",
     "detail": "taker_buy >%90 → TEST −0,504%/kazanan %27,6 (tükenme). ATR≥1 + taker>%70 = −1,550% (en kötü kombinasyon).",
     "source": "§15b", "param": None},
    {"id": "mlprob", "name": "ML hit probability", "status": "rejected",
     "summary": "Sabit TP/SL'de çalışıyor, trailing'de SIFIR",
     "detail": "4 seed: +0,111/+0,033/−0,015/+0,041 (eşik +0,20). Model 'hedefe ulaşacak mı' tahmin ediyor — trailing'de hedef yok.",
     "source": "§16", "param": None},
    {"id": "bookdepth", "name": "Emir defteri dengesizliği", "status": "rejected",
     "summary": "GÜRÜLTÜ — işaret seed'den seed'e değişiyor",
     "detail": "4 seed Q5−Q1: −0,559 / +0,043 / −0,009 / +0,110. Ortalama −0,104, sd 0,307 → |ort|/sd 0,34.",
     "source": "§21", "param": None},
    {"id": "hour", "name": "Saat filtresi", "status": "rejected",
     "summary": "Zayıf, tekrarlanmadı", "detail": "Saat bazlı desen seed'ler arası tutarsız.",
     "source": "§?", "param": None},
]


@router.get("/evidence")
async def evidence(request: Request):
    """Ölçülmüş hipotez tablosu + özet sayılar."""
    counts = {"applied": 0, "kept": 0, "rejected": 0}
    for item in EVIDENCE:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    return {
        "ok": True,
        "items": EVIDENCE,
        "counts": counts,
        "total": len(EVIDENCE),
        "docs": "docs/YUKSELIS_ARASTIRMASI_2026-11-10.md",
        "warning": (
            "Tüm eşikler 1m bar replay ile ölçüldü. Canlıda 5 sn ticker "
            "gürültüsü vardır (bkz. §18 trailing gap). Özellikle gap/eşik "
            "optimizasyonları bar replay'de iyimser görünebilir."
        ),
    }


# ---------------------------------------------------------------------------
# 3) Canlı işlem sonuçları
# ---------------------------------------------------------------------------

@router.get("/outcomes")
async def outcomes(request: Request, days: int = 7):
    """Son N günün paper işlem sonuçları + çıkış nedeni dağılımı."""
    days = max(1, min(int(days), 90))
    since = time.time() - days * 86400
    out = {"ok": True, "days": days, "summary": None, "by_reason": [],
           "error": None}
    def _summary_op(conn):
        cur = conn.execute(
            """select count(*) c,
                      sum(case when pnl_pct > 0 then 1 else 0 end) wins,
                      avg(pnl_pct) m,
                      avg(case when pnl_pct > 0 then pnl_pct end) avg_win,
                      avg(case when pnl_pct <= 0 then pnl_pct end) avg_loss
                 from auto_paper_trades
                where entry_time >= ? and status <> 'open'""",
            (since,),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def _reasons_op(conn):
        cur = conn.execute(
            """select coalesce(exit_reason,'(yok)') reason, count(*) c, avg(pnl_pct) m
                 from auto_paper_trades
                where entry_time >= ? and status <> 'open'
                group by 1 order by 2 desc limit 12""",
            (since,),
        )
        return [dict(r) for r in cur.fetchall()]

    try:
        r = await database._run_db(_summary_op)
        if r:
            total = int(r["c"] or 0)
            wins = int(r["wins"] or 0)
            out["summary"] = {
                "trades": total,
                "wins": wins,
                "win_rate": round(100.0 * wins / total, 1) if total else None,
                "avg_pnl_pct": round(_num(r["m"], 0.0), 3) if total else None,
                "avg_win_pct": round(_num(r["avg_win"], 0.0), 3) if wins else None,
                "avg_loss_pct": round(_num(r["avg_loss"], 0.0), 3)
                if (total - wins) else None,
            }
        reasons = await database._run_db(_reasons_op) or []
        out["by_reason"] = [
            {"reason": x["reason"], "count": int(x["c"] or 0),
             "avg_pnl_pct": round(_num(x["m"], 0.0), 3)}
            for x in reasons
        ]
    except Exception as exc:  # noqa: BLE001
        logger.debug("signal_insights: sonuçlar okunamadı: %s", exc)
        out["error"] = type(exc).__name__
    return out


# ---------------------------------------------------------------------------
# 4) Tek tıkla ayar düzeltme (panelden)
# ---------------------------------------------------------------------------

# Ölçülmüş önerilen değerler. `current` verilmezse mevcut değerle karşılaştırılır.
RECOMMENDED: dict[str, dict] = {
    "min_atr_pct": {
        "value": 1.0, "min": 0.0, "max": 20.0,
        "why": "ATR>='1,0%' kazanan oranı %34->%50 (5 seed, +0,364%). "
               "1,5 daha yüksek ortalama ama sd 2,4x -> aynı güven için 9x işlem.",
    },
    "min_oi_change_pct": {
        "value": 1.2, "min": 0.0, "max": 20.0,
        "why": "ATR>=1 açıkken 4 seed: 1,2% -> +0,939% (taban +0,379%, 2,5x). "
               "3,0% daha yüksek ama sd 2,4x, örneklem %37 az.",
    },
    "oi_window_min": {
        "value": 15.0, "min": 15.0, "max": 240.0,
        "why": "4/4 seed'de 15 dk en iyi (+0,878% vs 60 dk +0,502%), monoton. "
               "Alt sınır 15 (veri 5 dk aralıklı, 3 bar gerekli).",
    },
    "max_sl_tp_ratio": {
        "value": 0.64, "min": 0.0, "max": 5.0,
        "why": "Asimetri düzeltmesi: kazanç +1,595% / kayıp -2,915%. "
               "SL kısaltır, TP'ye dokunmaz.",
    },
}


@router.get("/recommended")
async def recommended(request: Request):
    """Ölçülmüş önerilen değerler + mevcut değerle farkı.

    Panel bunu kullanarak 'düzelt' düğmesi gösterir. Değişiklik YAPMAZ —
    yalnız karşılaştırma döner. Gerçek yazma PUT /api/auto-paper/settings.
    """
    params = await _active_params()
    items = []
    for key, rec in RECOMMENDED.items():
        cur = _num(params.get(key))
        items.append({
            "key": key,
            "current": cur,
            "recommended": rec["value"],
            "matches": cur is not None and abs(cur - rec["value"]) < 1e-9,
            "min": rec["min"],
            "max": rec["max"],
            "why": rec["why"],
        })
    mismatch = [i for i in items if not i["matches"]]
    return {
        "ok": True,
        "items": items,
        "mismatch_count": len(mismatch),
        "note": ("Değişiklik yapmak için panel PUT /api/auto-paper/settings "
                 "çağırır (admin yetkisi gerekir). Bu uç salt-okunurdur."),
    }
