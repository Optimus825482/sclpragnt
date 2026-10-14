"""Global→TR RESIDUAL LEAD-LAG sinyali (2026-10-12).

NE: Global (USDT) fiyatının, AYNI-bar TR (TRY) hareketiyle açıklanamayan kısmını
(residual) sinyal olarak kullanır. Düz Global momentum (`g_ret1`) DEĞİL — o
`NO_CHANNEL_EDGE` çıkmıştı. Residual, "USD, TRY'nin henüz yansıtmadığı bilgiyi
taşıyor mu" sorusunun ölçüsüdür.

YÖNTEM (araştırma `research_usd_leadlag.py` ile aynı):
    r_tr = son bar TRY getirisi (%), r_gl = son bar Global getirisi (%)
    β    = cov(r_gl, r_tr) / var(r_tr)   — son `window` bar üzerinden (rolling)
    residual = r_gl − β · r_tr
    residual > eşik  → Global, TR'nin henüz yansıtmadığı yukarı baskı taşıyor.

DÜRÜST UYARI (bağlayıcı — silme): 45 günlük ölçümde residual öncülüğü GERÇEK
(korelasyon +0.14…+0.16, 112 sembolde tutarlı) AMA net EV maliyet altında
(taker −0.05…−0.22; gerçek limit dolgusunda −0.45). Bu modül sinyali ÜRETİR;
kârlılık iddiası YOKTUR. Ürün kararı gereği canlıya alınmıştır; performans
`GLOBAL_LEAD_LAG` stratejisi altında ayrı izlenmeli ve gerekirse kapatılmalıdır.

LOOK-AHEAD: yalnız KAPANMIŞ barlar (bar open_time + 300 sn <= sinyal anı); β
yalnız geçmiş pencereden fit edilir.
"""
from __future__ import annotations

import logging
import statistics

logger = logging.getLogger("scalper.lead_lag_signal")

# Eşik: residual bu yüzdenin üzerindeyse aday. Araştırmadaki üst-kuyruk dilimiyle
# uyumlu (p85 civarı). Sembol evreni Global evrenle sınırlı olduğu için ağ yükü az.
DEFAULT_MIN_RESIDUAL_PCT = 0.35
DEFAULT_WINDOW = 120


def compute_residual(gl_rets: list[float], tr_rets: list[float],
                     window: int = DEFAULT_WINDOW) -> dict | None:
    """Son bar residual'ını hesapla (saf fonksiyon — DB/ağ YOK).

    `gl_rets`/`tr_rets`: zaman ARTAN yüzde getiri serileri (aynı uzunlukta,
    hizalı). Döner: {"beta","residual","gl_ret","tr_ret","n"} veya None.
    """
    n = min(len(gl_rets), len(tr_rets))
    if n < 30:
        return None
    a = gl_rets[-window:] if window > 0 else gl_rets
    b = tr_rets[-window:]
    m = min(len(a), len(b))
    a, b = a[-m:], b[-m:]
    var_b = statistics.pvariance(b)
    if var_b <= 0:
        return None
    mean_a = statistics.mean(a)
    mean_b = statistics.mean(b)
    cov = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b)) / len(a)
    beta = cov / var_b
    gl_last = gl_rets[-1]
    tr_last = tr_rets[-1]
    residual = gl_last - beta * tr_last
    return {"beta": round(beta, 4), "residual": round(residual, 4),
            "gl_ret": round(gl_last, 4), "tr_ret": round(tr_last, 4), "n": m}


def _pct_rets(closes: list[float]) -> list[float]:
    out = []
    for i in range(1, len(closes)):
        if closes[i - 1] > 0:
            out.append((closes[i] / closes[i - 1] - 1) * 100.0)
        else:
            out.append(0.0)
    return out


def _closed(bars: list, now_ms: int, bar_ms: int = 300_000) -> list[float]:
    """KAPANMIŞ barların kapanış fiyatları (open_time+bar_ms <= now_ms)."""
    out = []
    for row in bars:
        try:
            ot = int(row[0]); cl = float(row[4])
        except (IndexError, TypeError, ValueError):
            continue
        if ot + bar_ms <= now_ms and cl > 0:
            out.append(cl)
    return out


async def detect_leadlag_candidates(*, now_ms: int | None = None,
                                    min_residual_pct: float = DEFAULT_MIN_RESIDUAL_PCT,
                                    limit: int = 5,
                                    adapter=None, tr_adapter=None,
                                    symbols: list[str] | None = None) -> list[dict]:
    """Global evrendeki her sembol için residual hesapla; en yüksek `limit` adayı döndür.

    Global sembol → TR sembol eşlemesi `binance_tr_symbols` ile yapılır; TR'de
    listeli değilse atlanır. Ağ hataları sessizce atlanır (tek sembol turu bozmaz).
    """
    import time
    from app.binance_tr_symbols import is_binance_tr_symbol, map_to_tr_symbol
    from app.config import config

    if adapter is None:
        from app import binance_public as adapter
    if tr_adapter is None:
        from app import binance_tr_public as tr_adapter

    now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    evren = list(symbols if symbols is not None else getattr(config, "GLOBAL_SYMBOLS", []))
    out: list[dict] = []
    for gsym in evren:
        gsym = str(gsym or "").upper()
        if not gsym or not is_binance_tr_symbol(gsym):
            continue
        trsym = map_to_tr_symbol(gsym)
        try:
            gbars = await adapter.klines(gsym, "5m", 200)
            tb = await tr_adapter.klines(trsym, "5m", 200)
        except Exception as exc:
            logger.debug("lead_lag klines hatası %s/%s: %s", gsym, trsym, exc)
            continue
        gc = _closed(gbars, now_ms)
        tc = _closed(tb, now_ms)
        if len(gc) < 40 or len(tc) < 40:
            continue
        # Hizalama: iki seriyi ortak uzunluğa indir (sondan).
        m = min(len(gc), len(tc))
        res = compute_residual(_pct_rets(gc[-m:]), _pct_rets(tc[-m:]))
        if not res or res["residual"] < min_residual_pct:
            continue
        out.append({"symbol": gsym, "tr_symbol": trsym,
                    "residual": res["residual"], "beta": res["beta"],
                    "gl_ret": res["gl_ret"], "tr_ret": res["tr_ret"]})
    out.sort(key=lambda x: -x["residual"])
    return out[:max(1, int(limit))]
