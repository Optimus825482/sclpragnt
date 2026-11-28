"""CVD onay katmanı — canlı tape (Binance TR) + kesinleşmiş saatlik akış.

Neden var: `microflow` ve velocity katmanları CVD'yi **canlı aggTrade
akışından bir proxy olarak** üretir; anlık doğrudur ama tek tek işlemler
sıralama/gecikme yüzünden yanılabilir. CryptoHFTData her saat bittikten
~1-2 saat sonra o saatin **tam işlem kayıtlarını** yayınlar (gerçek taker
BUY/SELL, net CVD, VWAP). Bu modül ikisini birleştirir:

- KESİN  : son yayınlanmış saatlerin gerçek CVD'si (collector JSONL'ine yazar)
- CANLI  : 1m kline'lardan taker alıcı oranı, hacim temposu, fiyat/VWAP ilişkisi

Çıktı bir *yön hükmü* değil, bir **uyum/uyumsuzluk** okumasıdır:
fiyat yükselirken kesin CVD negatifse bu "boğa tuzağı" sınıfıdır.

Veri yolu: `CVD_CONFIRMED_PATH` (varsayılan `backend/work/cvd_confirmed.jsonl`).
Collector: `backend/scripts/cvd_confirm_collector.py` (research venv, pandas
+ cryptohftdata ister; çalışma zamanı bu dosyayı yalnızca okur).
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from app.binance_tr_public import klines

logger = logging.getLogger("scalper.confirmed_flow")

_DEFAULT_PATH = Path(__file__).resolve().parent.parent / "work" / "cvd_confirmed.jsonl"

# Eşikler tek yerde: hüküm metni bu sayılara göre yazılır.
CVD_STRONG_PCT = 3.0  # hacmin %3'ü ve üzeri net taker akışı = güçlü
CVD_WEAK_PCT = 1.0
LIVE_TAKER_BUY = 55.0
LIVE_TAKER_SELL = 45.0
LIVE_VOLUME_HOT = 1.5  # 15m hacim / 60m taban


def confirmed_path() -> Path:
    raw = os.environ.get("CVD_CONFIRMED_PATH")
    return Path(raw) if raw else _DEFAULT_PATH


def load_confirmed(path: Path | None = None) -> dict[str, list[dict]]:
    """Sembol -> saat kayıtları (eskiden yeniye). Aynı saat için son kayıt geçerli."""
    target = path or confirmed_path()
    out: dict[str, dict[str, dict]] = {}
    if not target.exists():
        return {}
    try:
        with target.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                sym, hour = row.get("symbol"), row.get("hour")
                if not sym or not hour:
                    continue
                out.setdefault(sym, {})[hour] = row
    except OSError as exc:  # dosya okunamazsa sessizce boş dönmek yerine logla
        logger.warning("confirmed_flow: %s okunamadı: %s", target, exc)
        return {}
    return {sym: [rows[h] for h in sorted(rows)] for sym, rows in out.items()}


def _cvd_pct(row: dict) -> float:
    try:
        return float(row.get("cvd_pct_of_volume") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _hour_change_pct(row: dict) -> float:
    open_, close = float(row.get("open") or 0.0), float(row.get("close") or 0.0)
    return (close / open_ - 1) * 100 if open_ else 0.0


def score_confirmed(hours: list[dict]) -> tuple[int, list[str]]:
    """Son 1-2 kesin saatten akış puanı (-4..+4) ve gerekçeler."""
    score, reasons = 0, []
    if not hours:
        return 0, ["kesinleşmiş saat verisi yok"]
    last = hours[-1]
    pct = _cvd_pct(last)
    chg = _hour_change_pct(last)
    if pct >= CVD_STRONG_PCT:
        score += 2
        reasons.append(f"son kesin saatte net taker akışı hacmin %{pct:+.1f}'i (güçlü alım)")
    elif pct >= CVD_WEAK_PCT:
        score += 1
        reasons.append(f"son kesin saatte hafif alıcı akışı (%{pct:+.1f})")
    elif pct <= -CVD_STRONG_PCT:
        score -= 2
        reasons.append(f"son kesin saatte net satış baskısı (%{pct:+.1f})")
    elif pct <= -CVD_WEAK_PCT:
        score -= 1
        reasons.append(f"son kesin saatte hafif satıcı akışı (%{pct:+.1f})")
    else:
        reasons.append(f"son kesin saatte akış dengeli (%{pct:+.1f})")

    # Fiyat yönü ile akış aynı tarafı gösteriyor mu?
    if chg > 1 and pct < 0:
        reasons.append(
            f"saat içinde fiyat {chg:+.1f}% artarken akış negatif — yükseliş alıcıyla değil, satıcının fiyatı yukarı bırakmasıyla"
        )
    if chg < -1 and pct > 0:
        reasons.append(f"fiyat {chg:+.1f}% düşerken akış pozitif — düşüşte alıcı var (birikim ihtimali)")

    if len(hours) >= 2:
        prev = hours[-2]
        if _cvd_pct(prev) > CVD_WEAK_PCT and pct < -CVD_WEAK_PCT:
            score -= 1
            reasons.append("iki saat arasında akış tam tersine döndü (alımdan satışa)")
        elif _cvd_pct(prev) < -CVD_WEAK_PCT and pct > CVD_WEAK_PCT:
            score += 1
            reasons.append("iki saat arasında akış satıştan alıma döndü")
    return max(-4, min(4, score)), reasons


def live_read(kline_rows: list) -> dict:
    """1m kline'lardan canlı okuma. Satır biçimi: Binance kline dizisi."""
    closed = list(kline_rows)[:-1] or list(kline_rows)
    if not closed:
        return {}
    qv = [float(c[7]) for c in closed]
    taker = [float(c[10]) for c in closed]
    close = [float(c[4]) for c in closed]
    v15 = sum(qv[-15:])
    base15 = sum(qv[-60:]) / 4.0 if len(qv) >= 60 else (sum(qv) / max(1, len(qv)) * 15)
    taker_ratio = (sum(taker[-15:]) / v15 * 100) if v15 else 0.0
    return {
        "price": close[-1],
        "change_15m_pct": (close[-1] / close[-15] - 1) * 100 if len(close) >= 15 else 0.0,
        "volume_15m_try": v15,
        "volume_ratio_15m": (v15 / base15) if base15 else 0.0,
        "taker_buy_pct_15m": taker_ratio,
        "at": time.time(),
    }


def live_score(live: dict, hours: list[dict]) -> int:
    """Canlı tape'in puan katkısı (-2..+2): taker oranı + fiyatın kesin VWAP'ına göre konumu."""
    taker = live.get("taker_buy_pct_15m") or 0.0
    price = live.get("price") or 0.0
    adj = 0
    if taker >= LIVE_TAKER_BUY:
        adj += 1
    elif taker <= LIVE_TAKER_SELL:
        adj -= 1
    if hours and price:
        vwap = float(hours[-1].get("vwap") or 0.0)
        if vwap:
            adj += 1 if price >= vwap else -1
    return adj


def _verdict(score_conf: int, reasons: list[str], live: dict, hours: list[dict]) -> str:
    """Uyum/uyumsuzluk hükmü.

    Tuzak tanımları **yön şartı** ister: fiyat yükselirken akış negatifse
    `BOGA_TUZAGI`; fiyat düşerken akış pozitifse `AYI_TUZAGI`. Aksi halde
    puan eşiklerine göre ONAYLI/ZAYIF/NÖTR döner.
    """
    price = live.get("price") or 0.0
    chg15 = live.get("change_15m_pct") or 0.0
    taker = live.get("taker_buy_pct_15m") or 0.0
    last = hours[-1] if hours else {}
    last_close = float(last.get("close") or 0.0)
    vwap = float(last.get("vwap") or 0.0)
    cvd_pct = _cvd_pct(last) if hours else 0.0
    vs_close = ((price / last_close - 1) * 100) if (price and last_close) else 0.0

    rising = chg15 > 1.0 or vs_close > 1.0
    falling = chg15 < -1.0 or vs_close < -1.0

    if rising and cvd_pct < -CVD_WEAK_PCT and taker < LIVE_TAKER_BUY:
        return "BOGA_TUZAGI"
    if falling and cvd_pct > CVD_WEAK_PCT and taker > LIVE_TAKER_SELL:
        return "AYI_TUZAGI"

    live_adj = live_score(live, hours)

    total = score_conf + live_adj
    if total >= 3:
        return "ONAYLI_ALIM"
    if total <= -3:
        return "ONAYLI_SATIS"
    if total > 0:
        return "ZAYIF_ALIM"
    if total < 0:
        return "ZAYIF_SATIS"
    return "NOTR"


async def confirm_flow_snapshot(symbol: str, store: dict[str, list[dict]] | None = None) -> dict:
    """Tek sembol için canlı + kesin birleşik okuma."""
    symbol = symbol.upper()
    data = store if store is not None else load_confirmed()
    hours = data.get(symbol, [])
    try:
        rows = await klines(symbol, "1m", limit=60)
        live = live_read(rows)
    except Exception as exc:  # noqa: BLE001 — canlı taraf düşerse kesin taraf yine dönsün
        logger.warning("confirmed_flow: %s canlı kline hatası: %s", symbol, exc)
        live = {}
    score_conf, reasons = score_confirmed(hours)
    verdict = _verdict(score_conf, reasons, live, hours)
    if hours and live.get("price"):
        last_close = float(hours[-1].get("close") or 0.0)
        if last_close:
            live["vs_last_confirmed_close_pct"] = (live["price"] / last_close - 1) * 100
        vwap = float(hours[-1].get("vwap") or 0.0)
        if vwap:
            live["vs_confirmed_vwap_pct"] = (live["price"] / vwap - 1) * 100
    warnings = []
    if not hours:
        warnings.append("kesinleşmiş saat verisi yok — collector çalışmıyor veya bu sembol izlenmiyor")
    if not live:
        warnings.append("canlı kline alınamadı")
    if hours:
        newest = hours[-1]["hour"]
        age_h = (
            (time.time() - float(hours[-1].get("fetched_at_epoch") or 0)) / 3600
            if hours[-1].get("fetched_at_epoch")
            else None
        )
        if age_h is not None and age_h > 4:
            warnings.append(f"en yeni kesin saat {age_h:.1f} saattir güncellenmedi")
        del newest
    return {
        "symbol": symbol,
        "verdict": verdict,
        "score": score_conf,
        "score_live": live_score(live, hours),
        "score_total": score_conf + live_score(live, hours),
        "reasons": reasons,
        "warnings": warnings,
        "live": live,
        "confirmed_hours": hours[-3:],
        "confirmed_count": len(hours),
        "as_of": time.time(),
    }


async def scan_confirmed_flow(store: dict[str, list[dict]] | None = None) -> dict:
    """İzlenen tüm semboller için özet liste (verdict'e göre sıralı)."""
    data = store if store is not None else load_confirmed()
    rows = []
    for sym in sorted(data):
        snap = await confirm_flow_snapshot(sym, store=data)
        rows.append(
            {
                "symbol": sym,
                "verdict": snap["verdict"],
                "score": snap["score"],
                "price": snap["live"].get("price"),
                "taker_buy_pct_15m": snap["live"].get("taker_buy_pct_15m"),
                "last_confirmed_hour": (snap["confirmed_hours"][-1]["hour"] if snap["confirmed_hours"] else None),
                "last_cvd_pct": (snap["confirmed_hours"][-1]["cvd_pct_of_volume"] if snap["confirmed_hours"] else None),
            }
        )
    order = {
        "ONAYLI_ALIM": 0,
        "ZAYIF_ALIM": 1,
        "NOTR": 2,
        "ZAYIF_SATIS": 3,
        "ONAYLI_SATIS": 4,
        "BOGA_TUZAGI": 5,
        "AYI_TUZAGI": 6,
    }
    rows.sort(key=lambda r: (order.get(r["verdict"], 9), -(r["score"] or 0), r["symbol"]))
    return {"count": len(rows), "path": str(confirmed_path()), "items": rows, "as_of": time.time()}
