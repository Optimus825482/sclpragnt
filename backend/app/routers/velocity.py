"""Velocity (fast-riser) candidate detection, tracking and autonomous paper entries."""
import asyncio
import json
import math
import os
import time
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request

from app.config import config
from app import database
from app.state import market, analyzer
from app.api_common import _start_background, _fresh_public_price, _background_tasks
from app.binance_tr_public import klines as fetch_klines, historical_klines, trading_symbols, orderbook, ticker_price
from app.technical_analysis import (calculate_snapshot, _atr, _aroon, _bollinger,
                                    _cci, _ema, _linreg_slope_pct, _mfi, _macd, _rsi, _sma,
                                    _wick_rejection_zscore)
from app.market_intelligence import microstructure_snapshot
from app.microflow import microflow
from app import calibration as calibration_service
from app.binance_tr_public import top_gainers, ticker_24h, active_movers_pool
from app.embedding_worker import worker as embedding_worker
from app.memory_service import build_document
from app import ml_forecast
from app.ws_runtime import ws_manager
from app.api_common import _llm_guard_block_reason

logger = logging.getLogger("scalper.velocity")
router = APIRouter()


# I-07 (2026-09-12): modül sabiti artık env ile GEÇERSİZ KILINABİLİR. Öncelik:
# DB (llm_settings["velocity_min_atr_pct"], `load_velocity_atr_profiles` ile
# açılışta/öğrenme döngüsünde okunur ve bu global'e yazar) > env
# (`VELOCITY_MIN_ATR_PCT`) > bu sabit. Global eşik için DB anahtarı KALICI
# YAZILMAZ (yalnızca profil anahtarları `velocity_min_atr_pct_5m/_15m` yazılır);
# bu yüzden restart'ta env/sabit değerine döner — bilinçli ve belgelenmiş.
VELOCITY_MIN_ATR_PCT = float(os.getenv("VELOCITY_MIN_ATR_PCT", "0.25"))  # 1m ATR% ≥ 0.25 → yüksek salınım rejimi (her iki mod)
VELOCITY_MIN_BB_WIDTH_PCT = 2.5    # Bollinger(20,2) genişliği ≥ %2.5 (d=+0.73, en güçlü)
VELOCITY_TREND_RSI_MIN = 60.0      # trend-içi mod: RSI ≥ 60 (momentum devam)
VELOCITY_REVERSAL_RSI_MAX = 35.0   # V-dönüşü mod: RSI ≤ 35 (aşırı satımdan sıçrama)
VELOCITY_STRUCT_SLOPE_PCT = 0.20   # LinReg(20) eğimi ≥ %0.2/10bar VEYA Aroon ≥ +50
# Aşırı uç elme: MFI/RSI tükenmişlikte +%2 olasılığı bazın altına düşüyor
# (14.475 gözlem: MFI≥95 → %0.71, RSI≥80 → %0.65, sağlıklı bant %1.56-2.48).
# Zaten fırlamış sembol "gidecek yeri yok" — geri çekilme riski en yüksek.
VELOCITY_MFI_UPPER = 90.0          # MFI ≥ 90 → ele (M1, 14 periyot)
VELOCITY_MFI_LOWER = 10.0          # MFI ≤ 10 → ele (aşırı satım da aynı risk)
VELOCITY_RSI_UPPER = 80.0          # RSI ≥ 80 → ele (trend-devam modunun üst sınırı)
VELOCITY_BASE_RATE_PCT = 1.97
VELOCITY_CALIBRATED_HIT_PCT = 19.3

# Binance TR rate limiter: token bucket, ~8 req/s max (conservative).
# Her scan_one / fetch_klines / top_gainers / ticker_24h cagrisi bu
# limiter uzerinden gecer. 2026-09-07.
_VELOCITY_RATE_LIMIT_RPS = 8.0
_VELOCITY_RATE_BURST = 12
_velocity_rate_tokens = _VELOCITY_RATE_BURST
_velocity_rate_last_refill = time.time()
_velocity_rate_lock = asyncio.Lock()

async def _velocity_rate_acquire():
    """Token bucket rate limiter: burst kadar token, saniyede RPS oranında yenilenir.

    D-13 (2026-09-12): eski sürüm asyncio.Lock ALTINDA uyuyordu
    (`await asyncio.sleep`) ve uyanınca token'ı DÜŞÜRMÜYOR, `_velocity_rate_tokens
    = 0` yapıp geçiyordu → eşzamanlı bekleyen N çağrı AYNI ANDA serbest kalıp
    8 rps sınırını aşıyordu (Binance TR 429 riski). Ayrıca bazı REST yolları
    limiter'ı hiç çağırmıyordu (bkz. `_fetch_one`, `_hydrate_market_cache_for`).

    Düzeltme: bekleme kilit DIŞINDA yapılır; döngü başında token yeniden
    kontrol edilir ve TAM BİR token düşülerek dönülür. Böylece her başarılı
    çağrı tam bir token tüketir; dönüş daima True'dur (bloklayıcı sözleşme).
    """
    global _velocity_rate_tokens, _velocity_rate_last_refill
    while True:
        async with _velocity_rate_lock:
            now = time.time()
            elapsed = now - _velocity_rate_last_refill
            _velocity_rate_tokens = min(_VELOCITY_RATE_BURST,
                                        _velocity_rate_tokens + elapsed * _VELOCITY_RATE_LIMIT_RPS)
            _velocity_rate_last_refill = now
            if _velocity_rate_tokens >= 1.0:
                _velocity_rate_tokens -= 1.0
                return True
            wait = (1.0 - _velocity_rate_tokens) / _VELOCITY_RATE_LIMIT_RPS
        # Kilit DIŞINDA bekle; uyanınca döngü başında token yeniden düşülür.
        await asyncio.sleep(wait + 0.01)

def _rate_limit_stats():
    """Anlik rate limit durumu (diagnostics icin)."""
    return {'tokens_remaining': round(_velocity_rate_tokens, 1),
            'burst': _VELOCITY_RATE_BURST,
            'rps': _VELOCITY_RATE_LIMIT_RPS}


def _velocity_rsi(closes, n=14):
    """Wilder RSI — kanonik ``technical_analysis._rsi``'e devreder (tek tanım)."""
    return _rsi(closes, n)


def _velocity_mfi(highs, lows, closes, vols, n=14):
    if len(closes) < n + 1:
        return None
    pos = neg = 0.0
    for i in range(len(closes) - n, len(closes)):
        tp = (highs[i] + lows[i] + closes[i]) / 3
        ptp = (highs[i - 1] + lows[i - 1] + closes[i - 1]) / 3
        flow = tp * vols[i]
        if tp > ptp: pos += flow
        elif tp < ptp: neg += flow
    # MFI düzeltmesi: hem pos hem neg sıfırsa (tüm hacimler 0 / düz tipik fiyat)
    # "aşırı alım 100" DÖNME — nötr 50.0. 100 yalnızca pos > 0 ve neg == 0
    # (tek yönlü alış akışı) iken anlamlıdır; kanonik `technical_analysis._mfi`
    # ile aynı kural.
    if neg:
        return 100 - 100 / (1 + pos / neg)
    return 100.0 if pos > 0 else 50.0


def _velocity_bollinger_width(closes, n=20, mult=2.0):
    """Bollinger genişliği — kanonik ``technical_analysis._bollinger``'e devreder.

    I-02 (2026-09-12): eski kopya `ddof=1` (n-1) kullanıyordu; kanonik `_bollinger`
    ddof=0 (n) kullanır ve ML eğitim tarafı (`ml_forecast`) da ddof=0 kullanıyor.
    Kesir→yüzde dönüşümü `_bollinger` genişliğinin ekran/panel beklediği ölçeğe
    uyar (x100). Eşikler (VELOCITY_MIN_BB_WIDTH_PCT=2.5) yeni ölçekle kalibre
    edilir; tek tüketici bu kopya olduğundan davranış tek kaynaktan gelir.
    """
    b = _bollinger(closes, n, mult)
    if b is None:
        return None
    return b.get("width_pct") * 100 if b.get("width_pct") is not None else None


def _velocity_struct_slope(closes, n=20):
    """Velocity yapısal eğim göstergesi — ``VELOCITY_STRUCT_SLOPE_PCT``'e KALİBRE.

    DİKKAT: Bu, ML özelliği ``linreg_slope10_pct`` DEĞİLDİR. Tarama eşiği
    (0.20) buradaki %/bar×10 ölçeğine göre kalibre edilmiştir; ölçeği veya
    pencereyi değiştirmek giriş davranışını bozar. ML yolu kanonik
    ``technical_analysis._linreg_slope_pct`` kullanır (periyot 10, yüzde/bar).
    """
    if len(closes) < n:
        return None
    xs = list(range(n))
    ys = closes[-n:]
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = sum((x - mx) ** 2 for x in xs)
    slope = num / den if den else 0
    return slope / my * 100 * 10 if my else None


def _velocity_aroon(highs, lows=None, n=25):
    """Aroon — kanonik ``technical_analysis._aroon``'e devreder (tek tanım).

    ``lows`` verilmezse yalnız yukarı bileşen hesaplanır (eski davranış korunur).
    """
    result = _aroon(highs, highs if lows is None else lows, n)
    if result is None:
        return None
    return {"up": result["up"],
            "down": result["down"] if lows is not None else None}


def _velocity_volume_z(vols, n=20):
    """Hacim z-skoru — eğitimdeki ``(v - mean20) / std20`` tanımıyla aynı.

    ML-08 (2026-09-12): `vol_z` çıkarımda sabit None yazılıyordu, eğitimde ise
    gerçek değer hesaplanıyordu (`build_symbol_dataset`). Aynı tanım burada.
    """
    if len(vols) < n:
        return None
    window = [float(value) for value in vols[-n:]]
    mean = sum(window) / n
    variance = sum((value - mean) ** 2 for value in window) / n
    if variance <= 0:
        return None
    return (float(vols[-1]) - mean) / math.sqrt(variance)


def _velocity_ml_feature_dict(closes, highs, lows, vols):
    """Kapanmış **5m** serisinden ML özellik sözlüğü (ML-01: eğitimle aynı dayanak).

    Geriye dönük ML backfill (maintenance) geçmiş mumlardan bu fonksiyonla
    özellik üretir; `scan_one`'daki ML bloğu değişirse burası da senkron kalmalı.
    Sözleşme: TÜM *_pct alanları YÜZDE girer (predict_target içeride kesire çevirir).

    ML-03/ML-04 (2026-09-12): ATR ve Bollinger genişliği KANONİK yardımcılardan
    (`ml_forecast.atr_ratio_from_bars` / `bb_width_ratio_from_bars`) gelir; eğitim
    tarafıyla aynı pencere (14 TR) ve aynı payda (kapanış) kullanılır.
    `scan_one`'daki tarama `atr_pct`'i KALİBRE eşik göstergesidir, ML özelliği
    DEĞİLDİR — bu yüzden ona dokunulmaz.

    ML-08 (2026-09-12): `ret1_pct`/`ret5_pct`/`vol_z` artık GERÇEKTEN hesaplanır.
    Önceden sabit None yazılıyordu; model bu üç kolonu eğitimde dolu görüp
    çıkarımda hep NaN aldığı için körleşebiliyordu.
    """
    closes = list(closes); highs = list(highs); lows = list(lows); vols = list(vols)
    atr_ratio = ml_forecast.atr_ratio_from_bars(highs, lows, closes)
    bb_ratio = ml_forecast.bb_width_ratio_from_bars(closes)
    ret1 = (closes[-1] / closes[-2] - 1) * 100 if len(closes) >= 2 and closes[-2] else None
    ret3 = (closes[-1] / closes[-4] - 1) * 100 if len(closes) >= 4 and closes[-4] else None
    ret5 = (closes[-1] / closes[-6] - 1) * 100 if len(closes) >= 6 and closes[-6] else None
    aroon = _velocity_aroon(highs, lows)
    return {
        "ret1_pct": ret1,
        "ret3_pct": ret3,
        "ret5_pct": ret5,
        "atr_pct": (atr_ratio * 100) if atr_ratio is not None else None,
        "bb_width_pct": (bb_ratio * 100) if bb_ratio is not None else None,
        "rsi": _velocity_rsi(closes),
        "mfi": _velocity_mfi(highs, lows, closes, vols),
        "vol_z": _velocity_volume_z(vols),
        "linreg_slope10_pct": _linreg_slope_pct(closes, 10),
        "aroon_up": aroon["up"] if aroon else None,
        "aroon_down": aroon["down"] if aroon else None,
    }


def _velocity_horizon_from_candidate_id(candidate_id: str) -> int:
    """'vel-5dk-%2-...' / 'vel-15dk-%3-...' adından ufuk dakikasını çıkarır."""
    return 15 if str(candidate_id or "").startswith("vel-15dk") else 5


VELOCITY_PROFILES = {
    # horizon_minutes: {target_pct, ölçüm penceresi, journal profile etiketi}
    5: {"target_pct": 2.0, "label": "5dk-%2"},
    15: {"target_pct": 3.0, "label": "15dk-%3"},
}


def _panel_score(raw_score: float) -> float:
    """Ham ``velocity_score`` (cap'siz, sınırlı değil) → panel 0-100 ölçeği.

    R2-01 / R3-03 (P0, 2026-09-12): ``MONITORING_TARGET_SCORE_TIERS``
    ('74.02:4.0,71.54:2.5,68.22:2.0') ve admin eşiği
    (``MONITORING_MIN_SCORE_DEFAULT``) **panel** ölçeğinde tanımlıdır. Eski kod
    ``dynamic_target_pct``'e HAM skoru geçiriyordu; kapıyı geçen her aday ham
    ≥ ~1400 ≫ 90 olduğundan daima üst bant (4.0%) seçiliyordu → hedef bantları
    fiilen ölüydü.

    A3 (2026-09-14): harita artık ``log`` modda ``100×log1p(raw)/log1p(REF)``.
    Formül, ``monitoring._panel_from_raw`` (KANONİK kaynak) ile BİREBİR aynıdır.
    ``monitoring.py`` bu modülü import ettiği için burada ters yönde import
    döngü (cycle) yaratırdı; bu yüzden formül TEK kaynaktan replike edilir ve
    ``tests/test_d08_skor_doygunluk.py`` parite testi eşitliği kilitler.
    """
    try:
        raw = float(raw_score or 0)
    except (TypeError, ValueError):
        return 0.0
    if raw <= 0:
        return 0.0
    if str(getattr(config, "MONITORING_SCORE_NORM_MODE", "log") or "log").lower() == "linear":
        cap = float(config.MONITORING_SCORE_NORM_CAP or 0)
        if cap <= 0:
            return 0.0
        return round(max(0.0, min(100.0, raw / cap * 100)), 1)
    ref = float(getattr(config, "MONITORING_SCORE_NORM_LOG_REF", 25000) or 0)
    denom = math.log1p(ref) if ref > 0 else 0.0
    if denom <= 0:
        return 0.0
    return round(max(0.0, min(100.0, 100.0 * math.log1p(raw) / denom)), 1)


def _panel_to_raw_score(panel_score: float) -> float:
    """Panel (0-100) → ham skor: ``_panel_score``'un TERSİ (A3).

    Admin/eşik değerleri panel ölçeğinde; kapı karşılaştırması ham skorda yapılır.
    """
    try:
        panel = max(0.0, min(100.0, float(panel_score or 0)))
    except (TypeError, ValueError):
        panel = 0.0
    if str(getattr(config, "MONITORING_SCORE_NORM_MODE", "log") or "log").lower() == "linear":
        return panel / 100.0 * float(config.MONITORING_SCORE_NORM_CAP or 0)
    ref = float(getattr(config, "MONITORING_SCORE_NORM_LOG_REF", 25000) or 0)
    denom = math.log1p(ref) if ref > 0 else 0.0
    if denom <= 0:
        return panel
    return math.expm1(panel / 100.0 * denom)


def _velocity_raw_score_gate() -> float:
    """``VELOCITY_AUTO_MIN_SCORE`` (PANEL 0-100) → ham velocity_score eşiği.

    Düzeltme (2026-09-12): eşik eski 0-100 skor ölçeğinde kalibre edilmişti
    (varsayılan 10), ama ham skor saturation kaldırıldıktan sonra tipik
    50-2000 bandında → `score < 10` kapısı hiçbir adayı elemiyordu. Panel→ham
    dönüşümü monitoring paneliyle aynı haritanın TERSİdir (A3: log modda expm1;
    öncesinde panel/100×cap).
    """
    return _panel_to_raw_score(float(config.VELOCITY_AUTO_MIN_SCORE or 0))


def _warm_gate(*, prof_atr: float, atr_pct: float, bb_width: float | None,
               slope: float | None, aroon_up: float | None,
               macd_bullish: bool, macd_rising: bool, ret3: float,
               volume_ratio: float, leading_ok: bool) -> tuple[bool, str | None, float]:
    """Isınıyor (warm) şeridi — eşiği kıl payı kaçıran adaylar için erken görünürlük.

    Kök neden (2026-09-26 kullanıcı şikâyeti: "bildirimler geç geliyor"): eşiği
    kıl payı kaçıran adaylar yalnızca ``block_reason`` ile watchlist'e düşüyor
    ve panelde görünmez. Bu yardımcı, geçilememiş kapıların eşik oranlarını
    hesaplar ve EN ZAYIF kapının eşiğe yakınlığını (0..1) döndürür.

    DÖNÜŞ: ``(warm, warm_reason, warm_proximity)`` — warm=True yolları:
      (a) ``leading_ok`` (M1/M3 öncü ATR kesişimi) → reason="m1_m3_oncu_atr",
          proximity=0.75 (sabit yüksek güven; araştırmada dokunuşu ~2.5× artırır).
      (b) Geçilememiş kapılar YALNIZ {atr, bb, struct} kümesinden VE en zayıf
          oran ≥ 0.6 VE destek sinyali (macd_bullish | macd_rising |
          ret3 ≥ 0.5 | volume_ratio ≥ 2.0) → reason="<kapı>_yaklas"
          ("atr_yaklas"/"bb_yaklas"/"struct_yaklas"), proximity=en zayıf oran.

    ÖNEMLİ — auto-entry BAĞLANTISI YOK: bu şerit ``passes``/skor/sıralama/hedef
    hesabını HİÇ etkilemez; yalnızca görünürlük (warm listesi + bildirim
    şeridi) içindir. ``exhausted``/``rejection_wick`` gibi tuzak elmelerini bu
    saf fonksiyon BİLMEZ — çağıran taraf (scan_one) guard eder.
    """
    # Kapı oranları: 1.0 = tam eşikte, <1.0 = eşiğin altında (geçilemedi).
    atr_oran = (atr_pct / prof_atr) if (prof_atr and prof_atr > 0) else 0.0
    bb_oran = (bb_width / VELOCITY_MIN_BB_WIDTH_PCT) \
        if (bb_width is not None and VELOCITY_MIN_BB_WIDTH_PCT > 0) else 0.0
    # Yapısal kapı: slope VEYA Aroon'dan GEÇENİ (skor formülündeki struct_ratio
    # ile aynı tanım; None → 0 yani kapı açılmamış sayılır).
    _slope_oran = ((slope or 0.0) / VELOCITY_STRUCT_SLOPE_PCT) if VELOCITY_STRUCT_SLOPE_PCT > 0 else 0.0
    _aroon_oran = (aroon_up or 0.0) / 50.0
    struct_oran = max(_slope_oran, _aroon_oran)

    # (a) M1/M3 öncü kesişim: bağımsız yüksek güven şeridi.
    if leading_ok:
        return True, "m1_m3_oncu_atr", 0.75

    # (b) Geçilememiş kapılar (yalnız oranla ifade edilebilen {atr, bb, struct});
    # negatif oranlar (ör. aşağı eğim) 0'a kırpılır — proximity negatif olmasın.
    failed: list[tuple[str, float]] = []
    if atr_oran < 1.0:
        failed.append(("atr", max(0.0, atr_oran)))
    if bb_oran < 1.0:
        failed.append(("bb", max(0.0, bb_oran)))
    if struct_oran < 1.0:
        failed.append(("struct", max(0.0, struct_oran)))
    if not failed:
        # Tüm kapılar oran olarak geçiyor → "yaklaşan" diye işaretlenmez;
        # (geçenler zaten normal aday akışına girer).
        return False, None, 0.0
    min_oran = min(r for _, r in failed)
    if min_oran < 0.6:
        # Eşiğin çok altında → ısınma değil, hareketsizlik.
        return False, None, 0.0
    if not (macd_bullish or macd_rising or ret3 >= 0.5 or volume_ratio >= 2.0):
        # Destek sinyali yok: eşeğin dibinde duran aday erken görünürlük kazanmaz.
        return False, None, 0.0
    en_zayif = min(failed, key=lambda item: item[1])[0]
    return True, f"{en_zayif}_yaklas", min_oran


def _warm_list_build(candidates: list[dict], watchlist: list[dict]) -> list[dict]:
    """Warm (ısınıyor) şeridi listesi: aday + izleme listesi içinden ``warm=True`` satırlar.

    Sıralama ``warm_proximity`` azalan (eşiğe EN YAKIN en üstte); limit
    ``config.MONITORING_WARM_LIST_LIMIT`` (getattr, varsayılan 12). Öğeler
    mevcut aday sözlüklerinin KENDİSİDİR (kopya gerekmez). Bu liste auto-entry'ye
    BAĞLI DEĞİLDİR — yalnız erken görünürlük (panel/bildirim) içindir.
    """
    try:
        limit = max(1, int(getattr(config, "MONITORING_WARM_LIST_LIMIT", 12)))
    except (TypeError, ValueError):
        limit = 12
    warm_rows = [r for r in (list(candidates) + list(watchlist)) if r.get("warm") is True]
    warm_rows.sort(key=lambda r: (r.get("warm_proximity") or 0.0), reverse=True)
    return warm_rows[:limit]


async def detect_velocity_candidates(args: dict | None = None, *, horizon_minutes: int = 5,
                                      extra_symbols: list | None = None):
    """Belirli ufukta (5dk/15dk) en az hedef % (2/3) yükselme potansiyeli taşıyan en hızlı 3 aday.

    v2 — forensics kalibrasyonu: Bollinger genişliği + ATR + (RSI iki ucu) +
    yapısal teyit (LinReg/Aroon) + aşırı uç elme (MFI/RSI). Her aday
    'trend_devam' veya 'v_donusu' moduyla etiketlenir.
    Yalnızca kapanmış 1m mumlar; tahmin/garanti değildir, paper-only.
    extra_symbols: top-gainer havuzuna ek olarak zorunlu taranacak semboller
    (monitoring izleme listesi — daha sık analiz).
    """
    profile = VELOCITY_PROFILES.get(horizon_minutes) or VELOCITY_PROFILES[5]
    base_target_pct = float(profile["target_pct"])
    now_ms = int(time.time() * 1000)
    all_ticker_rows = []
    try:
        await _velocity_rate_acquire()
        all_ticker_rows = await ticker_24h()
    except Exception as exc:
        logger.warning("velocity scan: ticker_24h hatası: %s", exc)

    try:
        gainer_rows = await top_gainers(config.VELOCITY_POOL_SIZE, _ticker_rows=all_ticker_rows)
    except Exception as exc:
        logger.warning("velocity scan: top_gainers hatası: %s", exc)
        gainer_rows = []

    active_rows = []
    if getattr(config, "DYNAMIC_ACTIVE_POOL_ENABLED", True):
        try:
            active_rows = await active_movers_pool(
                getattr(config, "DYNAMIC_ACTIVE_POOL_LIMIT", 15),
                _ticker_rows=all_ticker_rows
            )
        except Exception as exc:
            logger.warning("velocity scan: active_movers_pool hatası: %s", exc)
            active_rows = []

    # Havuz: top_gainers + active_movers_pool (intraday akış) + config.SYMBOLS + extra_symbols.
    # 24h değişimi düşük olsa bile aktif/hacimli ve yükselen semboller taranır (H-01/T-01).
    # 2026-09-26 (denetim #6): havuza girme KAYNAĞI ve 24h değişimi aday kaydına
    # yazılır — "yükselen" tanımı havuz başına farklı olduğundan (24h değişim /
    # 24h range-position / sabit evren) kalibrasyon popülasyonu kaynağa göre
    # ayrıştırılabilsin (eski pump'lar 24h lookback yüzünden hâlâ gainer'dadır).
    pool: list[str] = []
    _pool_set: set[str] = set()
    pool_source: dict[str, str] = {}
    _change_24h: dict[str, float] = {}
    for _row in (all_ticker_rows or []):
        try:
            _sym = str(_row.get("symbol") or "").upper()
            _chg = float(_row.get("priceChangePercent"))
        except (TypeError, ValueError, AttributeError):
            continue
        if _sym and _sym not in _change_24h:
            _change_24h[_sym] = _chg

    def _add(sym: str, source: str) -> None:
        sym = str(sym).upper()
        if sym and sym not in _pool_set:
            pool.append(sym)
            _pool_set.add(sym)
            pool_source[sym] = source

    for item in gainer_rows:
        _add(item["symbol"], "gainer")
    for item in active_rows:
        _add(item["symbol"], "mover")
    # 2026-09-26 (keşif A): !miniTicker@arr akışından 1m momentum+hacim patlaması
    # yakalanan semboller havuza eklenir — 24h top-gainer listesi birkaç dakika
    # geriden geldiği için ŞU AN başlayan hareket burada yakalanır.
    try:
        from app.early_discovery import top_candidates as _discovery_top
        for _c in _discovery_top(int(getattr(config, "DISCOVERY_POOL_INJECT_LIMIT", 8))):
            # Sembolsüz/bozuk kayıt havuzu kirletmesin (_add "None"u "NONE"
            # sembolüne çevirirdi).
            if not isinstance(_c, dict) or not _c.get("symbol"):
                continue
            _add(_c.get("symbol"), "discovery")
    except Exception as exc:
        logger.warning("velocity discovery havuz birleşimi: %s", exc)
    for sym in (str(s).upper() for s in config.SYMBOLS):
        _add(sym, "symbol")
    if extra_symbols:
        for sym in extra_symbols[:10]:
            _add(sym, "extra")

    # ---- N+1 ELİMİNASYONU (KRİTİK PERFORMANS) ---------------------------
    # Sembol başına AYRI `get_symbol_target_state` çağrısı, tarama havuzu
    # (~100-125 sembol) kadar DB round-trip demekti. `_run_scan` bunu 5dk ve
    # 15dk profilleri için PARALEL çalıştırıyor → 60 sn'lik tur başına ~220
    # ayrı sorgu. Psycopg havuzu `max_size=8` olduğu için bu sorgular
    # `strategy_loop` (5 sn'de bir stop/TP) ve `auto_paper_management_loop`
    # (5 sn) ile AYNı havuzu paylaşıyor ve pozisyon yönetimini bloklıyor —
    # paper botun tek işi pozisyon yönetimi olduğu için doğrudan PnL riski.
    #
    # `get_all_symbol_target_states` TEK sorguda tüm tabloyu çeker; sonuç
    # seans içi sözlüğe konur ve `scan_one` oradan okur. 220 tur → 2 tur.
    # Kalibrasyon seansları boyunca tablo DEĞİŞMEZ (taramalar salt okur);
    # yine de okuma başarısız olursa boş sözlüğe düşeriz (learned_target None),
    # yani eski "sorgu patlarsa hedefsiz tara" davranışı korunur.
    target_states: dict[str, dict] = {}
    if config.MONITORING_TARGET_ADAPTIVE:
        try:
            rows_states = await database.get_all_symbol_target_states()
            target_states = {
                str(row.get("symbol") or "").strip().upper(): row
                for row in (rows_states or []) if row.get("symbol")
            }
        except Exception as exc:
            logger.warning("velocity scan: sembol hedef durumu ön yüklemesi: %s", exc)
            target_states = {}

    sem = asyncio.Semaphore(6)

    async def scan_one(symbol: str) -> dict | None:
        async with sem:
            try:
                await _velocity_rate_acquire()
                rows = await fetch_klines(symbol, "1m", 60)
            except Exception:
                return None
            # D-04 (2026-09-12): oluşmakta olan (forming) mumu düşür. Binance
            # /api/v3/klines son satırı içinde bulunulan mumu döndürür; eşikler
            # (VELOCITY_MIN_ATR_PCT, VELOCITY_PATTERN_*) kapanmış mum varsayımıyla
            # kalibre edildi. Yarım mumla ölçüm ATR/chg/roc'u sistematik eksik
            # gösterir ve kapıyı bar içinde kararsızlaştırır.
            if int(rows[-1][0]) + 60_000 > now_ms:
                rows = rows[:-1]
            if len(rows) < 30:
                return None
            # Ölü/borsa dışı semboller 24h ticker'da eski kapanış verisiyle
            # listelenmeye devam edebiliyor; güncel mum şart.
            last_age_sec = (now_ms - (int(rows[-1][0]) + 59_999)) / 1000
            if last_age_sec > 180:
                return None
            opens = [float(r[1]) for r in rows]
            closes = [float(r[4]) for r in rows]
            highs = [float(r[2]) for r in rows]
            lows = [float(r[3]) for r in rows]
            vols = [float(r[5]) for r in rows]
            # A1: Closed-M1 MACD histogram confirmation
            _macd_res = _macd(closes)
            _macd_prev = _macd(closes[:-1]) if len(closes) > 1 else None
            macd_hist = _macd_res.get("histogram") if _macd_res else None
            macd_hist_prev = _macd_prev.get("histogram") if _macd_prev else None
            macd_bullish = bool(macd_hist is not None and macd_hist > 0)
            macd_rising = bool(macd_hist is not None and macd_hist_prev is not None and macd_hist > macd_hist_prev)
            i = len(rows) - 1
            price = closes[-1]
            if price <= 0:
                return None
            # I-03 (2026-09-12): özel 15-bar ATR yerine KANONİK
            # `technical_analysis._atr` (14 bar). Eski kopya `range(i-14, i+1)`
            # ile 15 true-range alıp basit ortalamasını alıyordu; kanonik `_atr`
            # 14 bar kullanır (analyzer.calculate_atr ve eğitim tarafıyla AYNI
            # pencere). Yüzde anlamı korunur (atr / price * 100) ve
            # VELOCITY_MIN_ATR_PCT=0.30 bu yüzde ölçeğinde kalır.
            atr_value = _atr(highs, lows, closes, 14)
            atr_pct = (atr_value / price * 100) if (atr_value and price) else 0.0
            bb_width = _velocity_bollinger_width(closes)
            rsi = _velocity_rsi(closes)
            mfi = _velocity_mfi(highs, lows, closes, vols)
            # Yapısal eğim: VELOCITY_STRUCT_SLOPE_PCT eşiğine kalibre ayrı
            # gösterge (ML özelliği linreg_slope10_pct DEĞİL — aşağıda kanonik
            # değer ayrıca hesaplanır).
            slope = _velocity_struct_slope(closes)
            ml_slope = _linreg_slope_pct(closes, 10)
            aroon = _velocity_aroon(highs, lows)
            aroon_up = aroon["up"] if aroon else None
            aroon_down = aroon["down"] if aroon else None
            ret3 = (closes[-1] / closes[-4] - 1) * 100 if len(closes) >= 4 else 0.0
            ret5 = (closes[-1] / closes[-6] - 1) * 100 if len(closes) >= 6 else 0.0
            short_atr_val = _atr(highs, lows, closes, 3)
            short_atr_pct = (short_atr_val / price * 100) if (short_atr_val and price) else 0.0
            # Mod tespiti: RSI iki ucundan biri
            if rsi is None:
                return None
            mode = "trend_devam" if rsi >= VELOCITY_TREND_RSI_MIN else \
                   "v_donusu" if rsi <= VELOCITY_REVERSAL_RSI_MAX else "notr"
            struct_ok = (slope is not None and slope >= VELOCITY_STRUCT_SLOPE_PCT) or \
                        (aroon_up is not None and aroon_up >= 50)
            # Aşırı uç elme: zaten fırlamış/tükenmiş semboller geri çekilme
            # riski taşır; +%2 olasılığı bazın altına düşüyor (forensics 14.475 gözlem).
            exhausted = None
            if mfi is not None and mfi >= VELOCITY_MFI_UPPER:
                exhausted = f"mfi_asiri_alim:{mfi:.0f}"
            elif mfi is not None and mfi <= VELOCITY_MFI_LOWER:
                exhausted = f"mfi_asiri_satim:{mfi:.0f}"
            elif rsi >= VELOCITY_RSI_UPPER:
                exhausted = f"rsi_asiri_alim:{rsi:.0f}"
            # Profil bazlı ATR eşiği: kalibrasyon 5dk/15dk için ayrı kaydeder;
            # yoksa global varsayılan kullanılır.
            prof_key = "5m" if horizon_minutes == 5 else "15m"
            prof_atr = _velocity_profile_atr.get(prof_key) or VELOCITY_MIN_ATR_PCT
            # Üst fitil (Rejection Wick / Boğa Tuzağı) kontrolü (2026-09-19):
            # Satıcıların tepeye yığılıp sert bastığı (shooting star/pin bar) barlarda
            # pump tepesi tuzağına düşülmesini engeller.
            wick_info = _wick_rejection_zscore(opens, highs, lows, closes) if len(closes) >= 21 else {}
            upper_wick_ratio = float(wick_info.get("upper_wick_ratio", 0.0)) if isinstance(wick_info, dict) else 0.0
            upper_zscore = float(wick_info.get("upper_zscore", 0.0)) if isinstance(wick_info, dict) else 0.0
            rejection_wick = bool(wick_info.get("signal") == "bearish_rejection" or (closes[-1] <= opens[-1] and upper_wick_ratio >= 0.60 and upper_zscore >= 2.0))

            # Kırılma / Ani Volatilite Patlaması Tespiti (2026-09-22):
            # 14-bar ATR, ani başlayan rallilerde geçmiş durgun/yatay mumlar yüzünden
            # matematiksel olarak gecikmeli yükselir. Son 3-5 mumda ani patlama varsa
            # (ret3 >= 1.0% veya ret5 >= 1.8% veya 3-bar ATR >= 0.45%),
            # sistem bu kırılmayı "ATR yetersiz" diyerek kaçırmaz.
            is_breakout = bool(ret3 >= 1.0 or ret5 >= 1.8 or short_atr_pct >= 0.45)
            # 2026-09-26 (denetim #4): breakout gevşetmesi profili TAMAMEN eziyordu —
            # DB kalibrasyonu prof_atr'yi 0.45'e çıkardıysa bile tek bir spike'lı
            # 3-bar pencere her zaman 0.25 tabanından geçebiliyordu. Artık gevşetme
            # tabanı profilin %60'ının altına inmez (varsayılan profilde davranış
            # değişmez: prof=0.25 → taban 0.25).
            breakout_floor = min(prof_atr, max(VELOCITY_MIN_ATR_PCT, prof_atr * 0.6))
            atr_passes = bool(atr_pct >= prof_atr or (is_breakout and atr_pct >= breakout_floor))

            # notr modu (RSI 35-60) da aday olabilir: yalnızca yapısal teyit (struct_ok) aranir.
            passes = (exhausted is None and
                      not rejection_wick and
                      atr_passes and
                      bb_width is not None and bb_width >= VELOCITY_MIN_BB_WIDTH_PCT and
                      mode is not None and
                      # ret3 saf yüzde formuyla yukarıda hesaplandı; eski
                      # `/max(closes[-4], 1)` kopyası 1 TRY altı fiyatları
                      # sistematik eksik raporluyordu — tek tanım ret3.
                      (struct_ok or (mode == "v_donusu" and ret3 >= 0.30)))
            # Elme sebebi: izleme listesindeki sembol yüksek skorla görünsede
            # hangi kapıya takıldığını arayüz gösterebilsin (2026-09-04).
            block_reason = None
            if not passes:
                if exhausted:
                    block_reason = exhausted  # örn. mfi_asiri_alim:85
                elif rejection_wick:
                    block_reason = f"ust_fitil_tuzagi:wick_{upper_wick_ratio:.2f}_z{upper_zscore:.1f}"
                elif not atr_passes:
                    block_reason = f"atr_yetersiz:{atr_pct:.2f}%<{prof_atr:.2f}%"
                elif bb_width is None or bb_width < VELOCITY_MIN_BB_WIDTH_PCT:
                    block_reason = f"bb_genisligi_yetersiz:{bb_width:.2f}%" if bb_width else "bb_verisi_yok"
                elif not (struct_ok or (mode == "v_donusu" and ret3 >= 0.30)):
                    block_reason = "yapisal_teyit_yok"
                else:
                    block_reason = "diger"
            # velocity skoru: normalize edilmiş bileşen çarpımı. Her bileşen
            # oransal (ratio) haritalanır; saturation 2026-09-07'de bilinçli
            # kaldırıldığı için çarpım ÜST SINIRSIZDIR (atr_ratio × bb_ratio
            # 1.0'ın üstüne çıkabilir) — "0..100 bandında kalır" iddiası artık
            # geçerli DEĞİL. 0-100 panel karşılığı monitoring._panel_from_raw
            # (varsayılan log haritası, REF=25000) ile üretilir; `linear` moda
            # geçilirse CAP=2000 sert kırpar ve SIRALAMA değişir — mod geçişi
            # sıralama olayıdır, yalnızca görüntü değil (2026-09-26 denetim #5).
            bb_ratio = (bb_width / VELOCITY_MIN_BB_WIDTH_PCT) if bb_width else 0.0
            struct_ratio = max(0.0, (slope or 0) / VELOCITY_STRUCT_SLOPE_PCT,
                                         (aroon_up or 0) / 50.0)
            # Saturation kaldirildi (2026-09-07)
            atr_ratio = (atr_pct / prof_atr) if prof_atr else 0.0
            # Momentum hesabı: ret3 (3 mum) ve ret5 (5 mum) maksimumu — kısa
            # geri çekilme momentum skorunu öldürmesin diye maksimum alınır.
            # 2026-09-26 (denetim #1 düzeltmesi): eski kodda "V-dönüşü slope
            # tabanlı momentum" diye ikinci bir dal vardı; dal yalnız ret3 ≤ 0
            # VE ret5 ≤ 0 iken çalışır, ret3/3 (≤ 0) hesaplar ve max(0, ·)
            # ile zaten 0'a iner — yani iki dal MATEMATİKSEL ÖZDEŞTİ ve
            # "slope tabanlı" davranış hiçbir zaman fiilen var olmadı.
            # Ölü dal kaldırıldı; skor değişmedi (her iki mod için tek tanım).
            momentum = max(0.0, ret3, ret5)
            # Hacim teyidi: son 20 kapanmış bar ortalamasına oranı (O-03 düzeltmesi)
            if len(vols) >= 20:
                _avg_vol = sum(vols[-20:]) / 20.0
                _vol_ratio = vols[-1] / _avg_vol if _avg_vol > 0 else 0.0
            else:
                _vol_ratio = 0.0
            volume_ratio = _vol_ratio
            # Momentum normalizasyonu (NameError: momentum_ratio düzeltmesi 2026-09-19)
            _mom_ref = max(prof_atr, 0.4)
            momentum_ratio = min(2.5, max(0.0, momentum / _mom_ref))
            velocity_score = round(100.0 * atr_ratio * bb_ratio
                                   * (0.2 + 0.8 * struct_ratio)
                                   * (0.5 + 0.5 * momentum_ratio)
                                   * (0.5 + 0.5 * min(1.0, volume_ratio / 2.0)), 2)
            # A1: MACD histogram confirmation multiplier
            if config.VELOCITY_MACD_CONFIRMATION_ENABLED:
                if macd_bullish and macd_rising:
                    velocity_score = round(velocity_score * 1.15, 2)
                elif macd_bullish:
                    velocity_score = round(velocity_score * 1.05, 2)
                elif macd_hist is not None and macd_hist < -config.VELOCITY_MACD_DIP_GATE_ATR * atr_pct and not macd_rising:
                    velocity_score = round(velocity_score * 0.85, 2)
            # ---- M5 momentum+volatilite deseni (7g replay: %66.8 başarı) ----
            # g0: en son kapanan M5 mumu; g1: ondan önceki; g2: iki önceki aralık.
            # Eşikler config.VELOCITY_PATTERN_* (24s/72s/7g doğrulandı).
            m5_pattern = None
            m5_pattern_ok = None
            m5_macd_bullish = None
            # ML-01 (2026-09-12): eğitime özelliklerin üretildiği bar dayanağı
            # (5m kapanış) ile çıkarım AYNI olmalıdır. Model 5m kapanış barlarla
            # eğitildiği için ML özellikleri de kapanmış 5m serisinden üretilir;
            # 1m serisi yalnız tarama/desen eşikleri için kalır.
            m5_ml_features = None
            try:
                await _velocity_rate_acquire()
                m5_rows = await fetch_klines(symbol, "5m", 40)  # ~3.3 saat warmup
                # D-04: oluşmakta olan 5m mumunu düşür (kalibrasyon kapanmış mum).
                if int(m5_rows[-1][0]) + 300_000 > now_ms:
                    m5_rows = m5_rows[:-1]
                if len(m5_rows) >= 35:
                    m5_closes = [float(r[4]) for r in m5_rows]
                    m5_highs = [float(r[2]) for r in m5_rows]
                    m5_lows = [float(r[3]) for r in m5_rows]
                    m5_vols = [float(r[5]) for r in m5_rows]
                    m5_ml_features = _velocity_ml_feature_dict(
                        m5_closes, m5_highs, m5_lows, m5_vols)
                    k = len(m5_rows) - 1  # son kapanmiş M5
                    def _m5_groups():
                        # g1: k-1'e kadar tam seri; g2: son 2 çıkar; g0: k dahil tam seri
                        g1 = m5_rows[:k]
                        g2 = m5_rows[:k - 2] if k > 3 else m5_rows[:k]
                        g0 = m5_rows  # son kapanan dahil
                        return g0, g1, g2
                    def _grp_vals(grp):
                        cls = [float(r[4]) for r in grp]
                        hs = [float(r[2]) for r in grp]
                        ls = [float(r[3]) for r in grp]
                        vs = [float(r[5]) for r in grp]
                        atr_v = None
                        if len(cls) >= 15:
                            trs = [max(hs[j] - ls[j], abs(hs[j] - cls[j - 1]), abs(ls[j] - cls[j - 1]))
                                   for j in range(len(cls) - 14, len(cls))]
                            atr_v = sum(trs) / len(trs)
                        atr_pct = (atr_v / cls[-1] * 100) if atr_v and cls[-1] else None
                        chg5 = (cls[-1] / cls[-6] - 1) * 100 if len(cls) >= 6 else None
                        chg3 = (cls[-1] / cls[-4] - 1) * 100 if len(cls) >= 4 else None
                        roc10 = (cls[-1] / cls[-11] - 1) * 100 if len(cls) >= 11 else None
                        return {"atr_pct": atr_pct, "chg5": chg5, "chg3": chg3, "roc": roc10}
                    g0, g1, g2 = _m5_groups()
                    v0, v1, v2 = _grp_vals(g0), _grp_vals(g1), _grp_vals(g2)
                    conds = {
                        "g0_chg5": v0["chg5"] is not None and v0["chg5"] >= config.VELOCITY_PATTERN_G0_CHG5,
                        "g0_chg3": v0["chg3"] is not None and v0["chg3"] >= config.VELOCITY_PATTERN_G0_CHG3,
                        "g0_roc": v0["roc"] is not None and v0["roc"] >= config.VELOCITY_PATTERN_G0_ROC,
                        "g0_atr": v0["atr_pct"] is not None and v0["atr_pct"] >= config.VELOCITY_PATTERN_G0_ATR,
                        "g1_atr": v1["atr_pct"] is not None and v1["atr_pct"] >= config.VELOCITY_PATTERN_G1_ATR,
                        "g2_atr": v2["atr_pct"] is not None and v2["atr_pct"] >= config.VELOCITY_PATTERN_G2_ATR,
                    }
                    m5_pattern = {k: bool(v) for k, v in conds.items()}
                    m5_pattern_ok = all(conds.values())
                    # A2: M5 MACD alignment context
                    _m5_macd = _macd(m5_closes)
                    m5_macd_hist = _m5_macd.get("histogram") if _m5_macd else None
                    m5_macd_bullish = bool(m5_macd_hist is not None and m5_macd_hist > 0)
                    if m5_macd_bullish and macd_rising:
                        velocity_score = round(velocity_score * 1.10, 2)
            except Exception as exc:
                logger.warning("velocity m5 pattern hesabı: %s", exc)
            # ---- M1/M3 öncü ATR deseni (araştırma: v2×M1/M3 kesişimi dokunuşu 2.5× artırıyor) ----
            # M1 öncü ATR: son kapanmış 1m'den ÖNCEKİ barın ATR%'si; M3 öncü: 3 dk öncesi.
            # Yüksekse (M1>1.0 VE M3>1.0) aday "kesişim deseni" taşır — skorlamada önceliklendirilir.
            try:
                m1_atr_prev = m3_atr_prev = None
                if len(closes) >= 16:
                    def _atr_pct_at(idx):
                        # Pencere hizalaması: kanonik `technical_analysis._atr`
                        # (ve taramadaki `_atr(highs, lows, closes, 14)`) 14 true
                        # range kullanır; buradaki eski 15-TR penceresi (idx-14..idx)
                        # ile aynı ölçülmüyordu. Aynı 14-bar kuralına hizalandı.
                        if idx < 13:
                            return None
                        trs = [max(highs[j] - lows[j], abs(highs[j] - closes[j - 1]),
                                   abs(lows[j] - closes[j - 1]))
                               for j in range(idx - 13, idx + 1)]
                        return (sum(trs) / len(trs)) / closes[idx] * 100 if trs else None
                    m1_atr_prev = _atr_pct_at(i - 1)
                    m3_atr_prev = _atr_pct_at(i - 3)
                leading_ok = bool(m1_atr_prev is not None and m3_atr_prev is not None
                                  and m1_atr_prev > 1.0 and m3_atr_prev > 1.0)
                # Kesişim deseni dokunuşu ~2.5× artırıyor (araştırma run 14); skor
                # çarpanı aday sıralamasında önceliklendirir (O-01 dengelendi).
                if leading_ok:
                    _lead_mult = float(getattr(config, "VELOCITY_LEADING_MULTIPLIER", 1.15))
                    velocity_score = round(velocity_score * _lead_mult, 2)
            except Exception as exc:
                logger.warning("velocity m1/m3 leading hesabı: %s", exc)
                m1_atr_prev = m3_atr_prev = None
                leading_ok = False
            # ---- "Isınıyor" (warm) şeridi (2026-09-26) ------------------------
            # Eşiği kıl payı kaçıran adaylar için ERKEN GÖRÜNÜRLÜK. BU ŞERİT
            # auto-entry'ye HİÇ BAĞLI DEĞİLDİR — passes/skor/sıralama/hedef
            # değişmez; yalnız warm listesi/bildirim katmanı okur. Tuzak
            # elmeleri (exhausted / rejection_wick) burada guard edilir,
            # _warm_gate saf kalır; `passes` zaten True ise warm=False.
            warm = False
            warm_reason = None
            warm_proximity = 0.0
            if not passes and exhausted is None and not rejection_wick:
                warm, warm_reason, warm_proximity = _warm_gate(
                    prof_atr=prof_atr, atr_pct=atr_pct, bb_width=bb_width,
                    slope=slope, aroon_up=aroon_up,
                    macd_bullish=macd_bullish, macd_rising=macd_rising, ret3=ret3,
                    volume_ratio=volume_ratio, leading_ok=bool(leading_ok))
            # --- ML tahmin: sembol bazlı adaptif hedef/süre ---
            ml_target = None
            ml_hit_prob = None
            ml_pred = None
            try:
                # ML-01 (2026-09-12): çıkarım eğitimle aynı dayanağı (5m kapanış)
                # kullanır. 5m warmup yeterli değilse ML tahmini TAMAMEN atlanır
                # (ml_target/ml_hit_prob None kalır → dynamic_target_pct ml_pct
                # almaz, baz hedef kullanılır). 1m serisiyle tahmin etmek — eski
                # davranış — modelin eğitildiği dağılımın dışında bir noktaydı
                # (ML-01 kökü) ve bundan kaçınırız.
                if m5_ml_features is not None:
                    ml_pred = ml_forecast.predict_target(symbol, m5_ml_features,
                                                         horizon=horizon_minutes)
                if ml_pred:
                    ml_target = float(ml_pred.get("target_pct") or 0)
                    ml_hit_prob = float(ml_pred.get("hit_probability") or 0)
            except Exception as exc:
                logger.debug("velocity ML tahmin hatası %s: %s", symbol, exc)

            # --- Spread okuma + ek kapılar (2026-09-19) ---
            # 1) SPREAD KAPISI: spread hedefin oranını aşarsa işlem maliyeti
            #    kârı yutacağı için sinyal elenir (kullanıcı kuralı).
            # 2) ML OLASILIK KAPISI: model %config.ML_MIN_EXECUTION_PROB altında
            #    isabet öngörüyorsa tuzak sinyal bildirime gitmez.
            flow_snap = (market.orderflow.get(symbol) or {})
            spread_pct = None
            try:
                _sp = flow_snap.get("spread_pct")
                spread_pct = float(_sp) if _sp is not None and float(_sp) > 0 else None
            except (TypeError, ValueError):
                spread_pct = None

            # --- Hedef kuralı: EN AZ base hedef + net-kâr maliyet tabanı ---
            learned_target = None
            learned_count = 0
            if config.MONITORING_TARGET_ADAPTIVE:
                try:
                    # Sembol durumu seans başında TEK sorguda yüklendi
                    # (`target_states`); sembol başına DB turu YOK.
                    # Satır yoksa `None` → hedefsiz tara (eski `get_*` davranışı
                    # ile aynı sonuç, sadece bedava).
                    state = target_states.get(str(symbol or "").strip().upper())
                    if state:
                        val = float(state.get("target_pct") or 0)
                        learned_target = val if val > 0 else None
                        learned_count = int(state.get("total_count") or 0)
                except (TypeError, ValueError) as exc:
                    # Bozuk satır (NaN/string target_pct) TEK sembolü etkiler,
                    # taramayı düşürmez.
                    logger.debug("velocity hedef durumu bozuk (%s): %s", symbol, exc)
                    learned_target = None
                    learned_count = 0
            # R2-01/R3-03 (P0): hedef bantları PANEL (0-100) ölçeğinde tanımlı;
            # buraya HAM skor değil PANEL skoru geçilir.
            effective_target = dynamic_target_pct(
                _panel_score(velocity_score), float(base_target_pct),
                learned_pct=learned_target,
                learned_count=learned_count,
                ml_pct=ml_target if (ml_target is not None and ml_target > 0) else None,
                ml_prob=ml_hit_prob if (ml_hit_prob is not None and ml_hit_prob > 0) else None,
                spread_pct=spread_pct,
                atr_pct=atr_pct,
            )
            # KAPİ 1 — SpreadGate: spread, hedefin izinli oranını aşıyorsa elenir.
            # Kullanıcı kuralı: "%X hedefte spread+komisyon sonrası net hedef kalmalı";
            # spread hedefin %MAX_ALLOWABLE_SPREAD_RATIO'sundan fazlaysa maliyet
            # kârı yutar → sinyal geçersiz.
            if spread_pct is not None:
                _max_spread = float(effective_target) * float(getattr(config, "MAX_ALLOWABLE_SPREAD_RATIO", 0.35))
                if spread_pct > _max_spread:
                    return {"symbol": symbol, "price": price, "volume_ratio": round(volume_ratio, 2),
                            "atr_pct": round(atr_pct, 3),
                            "bb_width_pct": round(bb_width, 2) if bb_width else None,
                            "rsi": round(rsi, 1) if rsi else None, "mfi": round(mfi, 1) if mfi else None,
                            "mode": mode, "exhausted": exhausted,
                            "linreg_slope10_pct": round(ml_slope, 3) if ml_slope is not None else None,
                            "horizon_minutes": horizon_minutes,
                            "target_pct": round(effective_target, 3),
                            "spread_pct": round(spread_pct, 3),
                            "ret3_pct": round(ret3, 3),
                            "pool_source": pool_source.get(symbol, "unknown"),
                            "change_24h": _change_24h.get(symbol),
                            "velocity_score": velocity_score, "passes": False,
                            "block_reason": f"asiri_spread:{spread_pct:.2f}%>{_max_spread:.2f}%_siniri",
                            "macd_hist": round(macd_hist, 6) if macd_hist is not None else None,
                            "macd_bullish": macd_bullish,
                            "macd_rising": macd_rising,
                            "leading_ok": leading_ok,
                            "base_hit_pct": VELOCITY_BASE_RATE_PCT,
                            "last_closed_at": rows[-1][0]}
            # KAPİ 2 — ML düşük olasılık: model eğitimliyse ve yapılandırılmış pozitif bir
            # MIN eşiği varsa tuzak sinyal elenir (varsayılan 0.0 — teknik momentuma izin verilir).
            _min_exec_prob = float(getattr(config, "ML_MIN_EXECUTION_PROB", 0.0) or 0.0)
            if _min_exec_prob > 0 and ml_hit_prob is not None and ml_hit_prob > 0 and ml_hit_prob < _min_exec_prob:
                return {"symbol": symbol, "price": price, "volume_ratio": round(volume_ratio, 2),
                        "atr_pct": round(atr_pct, 3),
                        "bb_width_pct": round(bb_width, 2) if bb_width else None,
                        "rsi": round(rsi, 1) if rsi else None, "mfi": round(mfi, 1) if mfi else None,
                        "mode": mode, "exhausted": exhausted,
                        "linreg_slope10_pct": round(ml_slope, 3) if ml_slope is not None else None,
                        "horizon_minutes": horizon_minutes,
                        "target_pct": round(effective_target, 3),
                        "ml_hit_probability": round(ml_hit_prob, 3),
                        "ret3_pct": round(ret3, 3),
                        "pool_source": pool_source.get(symbol, "unknown"),
                        "change_24h": _change_24h.get(symbol),
                        "velocity_score": velocity_score, "passes": False,
                        "block_reason": f"ml_dusuk_olasilik:{ml_hit_prob:.2f}<{_min_exec_prob:.2f}",
                        "macd_hist": round(macd_hist, 6) if macd_hist is not None else None,
                        "macd_bullish": macd_bullish,
                        "macd_rising": macd_rising,
                        "warm": warm, "warm_reason": warm_reason,
                        "warm_proximity": round(warm_proximity, 3),
                        "leading_ok": leading_ok,
                        "base_hit_pct": VELOCITY_BASE_RATE_PCT,
                        "last_closed_at": rows[-1][0]}
            # Hedef gercekciligi (VELOCITY_TARGET_REALISM_*): guclu MACD teyidi veya
            # yuksek ML olasiligi yoksa agresif ust-bant (4%) hedefi MAX_PCT'e indir;
            # 5dk+ icinde dokunulmasi nadirdir ve basariyi dusurur.
            if config.VELOCITY_TARGET_REALISM_ENABLED:
                macd_strong = bool(macd_bullish or macd_rising)
                prob = ml_hit_prob if ml_hit_prob is not None else 0.0
                if not macd_strong and float(prob) < config.VELOCITY_TARGET_REALISM_MIN_ML_PROB:
                    effective_target = min(effective_target, config.VELOCITY_TARGET_REALISM_MAX_PCT)
            # ML siralama bonusu KALDIRILDI (2026-09-07): yapay skor şişirmesi
            # zayıf sinyalleri eşik üstüne taşıyıp agresif hedef (%4.0) verdiriyor,
            # gerçek MFE yetişemiyordu. ML tahmini hedef belirlemede (dynamic_target_pct
            # ml_pct parametresi) hâlâ kullanılır; skoru etkilemez.
            velocity_score = round(velocity_score, 2)  # cap kaldirildi (2026-09-07)
            return {"symbol": symbol, "price": price, "volume_ratio": round(volume_ratio, 2),
                    "atr_pct": round(atr_pct, 3),
                    "bb_width_pct": round(bb_width, 2) if bb_width else None,
                    "rsi": round(rsi, 1) if rsi else None, "mfi": round(mfi, 1) if mfi else None,
                    "mode": mode, "exhausted": exhausted,
                    "linreg_slope10_pct": round(ml_slope, 3) if ml_slope is not None else None,
                    "aroon_up": round(aroon_up, 0) if aroon_up is not None else None,
                    "aroon_down": round(aroon_down, 0) if aroon_down is not None else None,
                    "horizon_minutes": horizon_minutes,
                    "target_pct": round(effective_target, 3),
                    "ml_target_pct": round(ml_target, 3) if ml_target is not None and ml_target > 0 else None,
                    "ml_hit_probability": round(ml_hit_prob, 3) if ml_hit_prob is not None else None,
                    "ret3_pct": round(ret3, 3),
                    "pool_source": pool_source.get(symbol, "unknown"),
                    "change_24h": _change_24h.get(symbol),
                    "velocity_score": velocity_score, "passes": passes,
                    "block_reason": block_reason,
                    # Warm şeridi: `passes=True` iken yukarıdaki guard yüzünden
                    # zaten False'tur (geçen aday "ısınıyor" olarak işaretlenmez);
                    # `passes=False` adaylarda kıl payı kaçırma yakınlığı taşır.
                    "warm": warm, "warm_reason": warm_reason,
                    "warm_proximity": round(warm_proximity, 3),
                    "macd_hist": round(macd_hist, 6) if macd_hist is not None else None,
                    "macd_bullish": macd_bullish,
                    "macd_rising": macd_rising,
                    "m5_macd_bullish": m5_macd_bullish,
                    "m5_pattern": m5_pattern, "m5_pattern_ok": m5_pattern_ok,
                    # ML-01: gölge ML tahmininin girdisi. Bu sözlük KAPANMIŞ 5m
                    # seriden üretilir (eğitimle aynı dayanak). Aday satırındaki
                    # `atr_pct`/`ret3_pct`/`rsi`... ise 1m serisindendir (tarama
                    # eşikleri için kalibrasyonlu) — ML çıkarımında KULLANILMAZ.
                    # Tek doğruluk kaynağı burasıdır; tüketiciler (llm_chat)
                    # bunu doğrudan `predict_target`e geçirmelidir.
                    "ml_features_5m": m5_ml_features,
                    "m1_atr_prev": round(m1_atr_prev, 3) if m1_atr_prev is not None else None,
                    "m3_atr_prev": round(m3_atr_prev, 3) if m3_atr_prev is not None else None,
                    "leading_ok": leading_ok,
                    "base_hit_pct": VELOCITY_BASE_RATE_PCT,
                    "calibrated_hit_pct": VELOCITY_CALIBRATED_HIT_PCT if passes else None,
                    "last_closed_at": rows[-1][0]}

    results = await asyncio.gather(*(scan_one(s) for s in pool))
    limit = max(1, min(int((args or {}).get("limit", 3)), 10))
    # Mikro-yapı anlık görüntüsü: aday satırına eklenir (sıralama çarpanı +
    # journal kaydı aynı kaynaktan beslenir; başarısızlık sıralamayı düşürmez).
    def _micro_for(r: dict) -> dict | None:
        """Adayın KENDİ sembolüne ait mikro-yapıyı getir (yabancı sembol yok).

        D-14 (2026-09-26 denetimi, KRİTİK): `microflow.get_snapshot` sembol
        parametrik DEĞİLse GLOBAL aktif sembolü okur. Tarama sırasında taranan
        TÜM adaylara aynı sembolün mikro-yapısı yükleniyordu ve sıralama anahtarı
        `velocity_score × micro_mult` olduğu için YANLIŞ aday seçilebiliyordu
        (bir sembolün whale cezası diğerlerine de uygulanıyordu).

        Savunma (fail-safe, iki yönlü uyum):
          1. Sembol-parametrik API varsa (`get_snapshot(symbol=...)`) o kullanılır.
          2) Değilse mevcut imza denenir.
          3. Dönen snapshot'ın `symbol` alanı aday sembolüyle UYUŞMUYORSA
             veri YOK sayılır → `None` (fail-open 1.0 yerine "veri yok" işareti;
             `micro_structure_multiplier(None)` nötr 1.0 döner, yani sıralama
             etkilenmez ama yanlış veri de bulaşmaz).
        """
        target = str(r.get("symbol") or "").upper()
        micro = None
        try:
            try:
                # Parametrik API (microflow.py ayrı ajan tarafından
                # `symbol=` destekleyecek şekilde düzeltiliyor).
                micro = microflow.get_snapshot(symbol=target, price=r["price"])
            except TypeError:
                try:
                    micro = microflow.get_snapshot(symbol=target)
                except TypeError:
                    # Eski, global-sembol imzası: yalnızca aktif sembol
                    # adayınkiyle örtüşüyorsa anlamlıdır.
                    micro = microflow.get_snapshot(price=r["price"])
        except Exception:
            return None
        if not isinstance(micro, dict):
            return None
        got = str(micro.get("symbol") or "").upper()
        if got and target and got != target:
            # Yabancı sembolün verisi — kullanmak yanlış aday seçimine yol açar.
            return None
        flow = (micro.get("trade_flow") or {})
        activity = (flow.get("whale_activity") or {})
        if not flow and not activity and not micro.get("data_ready"):
            return None
        return {"symbol": target,
                "whale_verdict": activity.get("verdict"),
                "whale_count": activity.get("whale_count"),
                "cvd_try": flow.get("cvd_try"),
                "trade_rate_per_min": flow.get("trade_rate_per_min"),
                "data_ready": bool(micro.get("data_ready"))}
    for r in results:
        if r:
            r["microstructure"] = _micro_for(r)
            r["micro_mult"] = round(micro_structure_multiplier(r["microstructure"]), 3)
    candidates = [r for r in results if r and r["passes"]]
    # Sıralama: ham skor × mikro-yapı çarpanı (kalite çarpanı burada DEĞİL;
    # upside_rank_score içinde uygulanır — monitoring/ortak sıralama anahtarı).
    candidates.sort(key=lambda r: r["velocity_score"] * r["micro_mult"], reverse=True)
    for rank, candidate in enumerate(candidates[:limit], 1):
        candidate["rank"] = rank
    # Izleme listesi: geçmeyen ama kayda deger hareket sinyali olanlar.
    # Düzeltme (2026-09-12): eski `>= 0.6` eşiği 0-100 skor ölçeğinden kalma ve
    # ham ölçekte (tipik 50-2000) ölüydü — her elenen aday izlemeye düşüyordu.
    # Aynı panel→ham dönüşümü uygulanır (A3: aktif haritanın tersi; log modda
    # expm1). Panel 0.6 paneli çok düşük olduğu için ham eşik de çok küçüktür —
    # amaç "her elenen aday izlemeye düşmesin".
    _watchlist_min_raw = _panel_to_raw_score(0.6)
    watchlist = [r for r in results if r and not r["passes"] and r["velocity_score"] >= _watchlist_min_raw]
    watchlist.sort(key=lambda r: r["velocity_score"] * r["micro_mult"], reverse=True)
    # "Isınıyor" (warm) şeridi (2026-09-26): eşiği kıl payı kaçıran adaylar
    # block_reason'a gömülüp görünmez olmasın — erken görünürlük listesi.
    # Auto-entry BU listeye BAĞLI DEĞİLDİR (yalnız panel/bildirim okur).
    warm_list = _warm_list_build(candidates, watchlist)
    # Journal: geçenler + izleme listesi kaydedilir; ufuk süresi dolunca
    candidate_id_prefix = f"vel-{profile['label']}-{int(now_ms)}"
    for r in candidates + watchlist:
        r["candidate_id"] = f"{candidate_id_prefix}-{r['symbol']}"
    # Adaylar için tekil WS mikro yapı akışını başlat; 1s/5s bar ve agresif
    # akış, aday izleme sırasında LLM/panelin gerçek zamanlı görüntü almasını
    # sağlar. En fazla 3 aday, sembol sayısı sınırlı olduğu için bağlantı
    # maliyeti düşüktür. Başarısızlık taramayı düşürmez.
    try:
        for cand in candidates[:limit]:
            await microflow.start(cand["symbol"])
    except Exception as exc:
        logger.warning("velocity microflow aday başlatma: %s", exc)
    try:
        # Journal: geçenler (en az ilk 20) + izleme listesi kaydedilir; böylece
        # monitoring_notifications'a giren hiçbir aday journal kayıtsız kalmaz.
        journal_rows = [{
            "candidate_id": r["candidate_id"],
            "created_at": now_ms / 1000, "symbol": r["symbol"], "price": r["price"],
            "target_pct": r.get("target_pct") or base_target_pct, "atr_pct": r.get("atr_pct") or 0.0, "volume_ratio": 0.0,
            "ret3_pct": r.get("ret3_pct") or 0.0, "velocity_score": r.get("velocity_score") or 0.0,
            "passes": r.get("passes", False), "rank": r.get("rank"),
            "ml_target_pct": r.get("ml_target_pct"),
            "ml_hit_probability": r.get("ml_hit_probability"),
            "m5_pattern": r.get("m5_pattern"), "m5_pattern_ok": r.get("m5_pattern_ok"),
            "leading_ok": r.get("leading_ok"),
        } for r in (candidates[:max(limit, 20)] + watchlist[:5])]
        # Mikro yapı (whale dağıtım sinyali, CVD) aday satırından journal'a
        # taşınır; filtreler kapalıyken dahi ileride canlı istatistik üretmek
        # için kaydedilir.
        for row in journal_rows:
            src = next((r for r in candidates + watchlist if r["symbol"] == row["symbol"]), None)
            if src and src.get("microstructure"):
                row["microstructure"] = src["microstructure"]
        await database.save_velocity_candidates(journal_rows)
    except Exception as exc:
        logger.warning("velocity journal hatası: %s", exc)
    live_stats = await database.get_velocity_calibration_stats()
    live_hit_pct = (float(live_stats.get("passing_touched_count") or 0) /
                    float(live_stats.get("passing_count") or 0) * 100) if live_stats.get("passing_count") else None
    return {"generated_at": now_ms / 1000, "target": f"min %{base_target_pct:g} move in {horizon_minutes} minutes",
            "horizon_minutes": horizon_minutes, "target_pct": base_target_pct,
            "pool_source": "binance_tr_top_gaining_tab", "symbols_scanned": len(pool),
            "version": "v2-forensics-2026-08-29",
            "filter": {"min_atr_pct": VELOCITY_MIN_ATR_PCT,
                        "min_bb_width_pct": VELOCITY_MIN_BB_WIDTH_PCT,
                        "trend_rsi_min": VELOCITY_TREND_RSI_MIN,
                        "reversal_rsi_max": VELOCITY_REVERSAL_RSI_MAX,
                        "mfi_upper": VELOCITY_MFI_UPPER, "mfi_lower": VELOCITY_MFI_LOWER,
                        "rsi_upper": VELOCITY_RSI_UPPER,
                        "struct_slope_pct": VELOCITY_STRUCT_SLOPE_PCT},
            "calibration": {"base_rate_pct": VELOCITY_BASE_RATE_PCT,
                             "conditional_hit_pct": VELOCITY_CALIBRATED_HIT_PCT,
                             "live_hit_pct": live_hit_pct,
                             "live_evaluated": int(live_stats.get("evaluated_count") or 0),
                             "live_passing_touched": int(live_stats.get("passing_touched_count") or 0),
                             "live_passing_count": int(live_stats.get("passing_count") or 0),
                             "note": "v2: hacim şartı kaldırıldı; BB genişliği + RSI/MFI uç elmesi + LinReg/Aroon teyidi. live_hit_pct canlı journal'dan gelir."},
            "candidates": candidates[:limit], "watchlist": watchlist[:5],
            "warm": warm_list,
            "leading_summary": {
                "scanned": len(results),
                "leading_ok_count": sum(1 for r in results if r and r.get("leading_ok")),
                "note": "M1/M3 öncü ATR kesişimi (M1>1.0 VE M3>1.0) dokunuşu ~2.5x artırır; skorda 1.5x öncelik.",
            },
            "data_policy": "kapanmış 1m mumlar; tahmin/garanti değil, paper-only"}


_velocity_learning_state = {"last_run_at": None, "measured": 0, "last_error": None,
                             "last_calibrated_at": None, "active_filters": None}

# Kalibrasyon parametreleri — profil bazlı.
# 5dk-%2 ve 15dk-%3 farklı hedefler; ayrı ATR eşiği + ayrı hedef bant.
# Hedef bant backtest/forensics'ten: tüm-sembol 5dk-%2 ~%11-15, canlı (top-gainer
# + rank seçimi) ~%20-28. Bant histerezisli: eşik, isabet hedefin dışına
# çıkınca ±0.05 kayar; bant içinde kalırsa dokunulmaz (salınım önlenir).
VELOCITY_PROFILE_CALIB = {
    "5m": {"target_low": 0.12, "target_high": 0.30, "step": 0.05,
           "min_atr": 0.10, "max_atr": 0.50, "min_samples": 30},
    "15m": {"target_low": 0.15, "target_high": 0.38, "step": 0.05,
            "min_atr": 0.10, "max_atr": 0.55, "min_samples": 30},
}
_velocity_profile_atr = {"5m": None, "15m": None}  # lazy-loaded per-profile thresholds


async def velocity_calibrate():
    """Profil bazlı ATR eşiği kalibrasyonu; her döngüde değerlendirilir.

    Döndürür: (değişiklik_yapıldı_mı, durum_sözlüğü). Eşikler
    ``llm_settings``'e kalıcı yazılır (restart'ta geri yüklenir).

    I-07 (2026-09-12): eskiden burada vestigial bir ``global VELOCITY_MIN_ATR_PCT``
    bildirimi vardı ama fonksiyon global'i HİÇ atamıyordu (yalnızca okuyordu) →
    kaldırıldı. Global eşiğin env ile geçersiz kılınabilmesi modül tepesinde
    (``VELOCITY_MIN_ATR_PCT = float(os.getenv(...))``) sağlanır.
    """
    changed = False
    by_profile = {}
    hit_rates = []
    for profile, cal in VELOCITY_PROFILE_CALIB.items():
        stats = await database.get_velocity_calibration_stats(profile=profile)
        passing = int(stats.get("passing_count") or 0)
        touched = int(stats.get("passing_touched_count") or 0)
        hit = (touched / passing) if passing else None
        by_profile[profile] = {"passing_count": passing, "passing_touched": touched,
                               "hit_pct": round(hit * 100, 1) if hit is not None else None}
        if passing < cal["min_samples"] or hit is None:
            continue
        hit_rates.append(hit)
        # Profil eşiği: global VELOCITY_MIN_ATR_PCT'e çarpan olarak sakla.
        # (Modül global'i tek kalır; profil çarpanı ayrı kaydedilir.)
        key = f"velocity_min_atr_pct_{profile}"
        saved = await database.get_llm_setting(key, None)
        if saved:
            _velocity_profile_atr[profile] = round(float(saved), 2)
        else:
            _velocity_profile_atr[profile] = VELOCITY_MIN_ATR_PCT
        cur = _velocity_profile_atr[profile]
        if hit < cal["target_low"] and cur < cal["max_atr"]:
            new_v = round(min(cal["max_atr"], cur + cal["step"]), 2)
            _velocity_profile_atr[profile] = new_v
            await database.set_llm_setting(key, str(new_v))
            changed = True
            logger.info("velocity: %s isabet %s%% hedef altı (%s%%) → ATR %s→%s",
                        profile, round(hit * 100, 1), round(cal["target_low"] * 100),
                        cur, new_v)
        elif hit > cal["target_high"] and cur > cal["min_atr"]:
            new_v = round(max(cal["min_atr"], cur - cal["step"]), 2)
            _velocity_profile_atr[profile] = new_v
            await database.set_llm_setting(key, str(new_v))
            changed = True
            logger.info("velocity: %s isabet %s%% hedef üstü (%s%%) → ATR %s→%s",
                        profile, round(hit * 100, 1), round(cal["target_high"] * 100),
                        cur, new_v)
        by_profile[profile]["atr_threshold"] = _velocity_profile_atr[profile]
    if hit_rates:
        # Genel (global) eşik: profil ortalaması; UI'ın tek göstergesi için.
        mean_hit = sum(hit_rates) / len(hit_rates)
        by_profile["_meta"] = {"mean_hit_pct": round(mean_hit * 100, 1)}
    if changed:
        _velocity_learning_state["last_calibrated_at"] = time.time()
    return changed, by_profile


async def load_velocity_atr_profiles():
    """Startup'ta kalibre edilmiş ATR eşiklerini DB'den yükler.
    
    velocity_learning_loop 120sn uyuduğu için ilk taramalar fabrika
    ayarı (0.30) ile çalışıyordu. Bu fonksiyon başlangıçta hemen
    yüklenir böylece ilk scan bile doğru eşikle çalışır.
    """
    global VELOCITY_MIN_ATR_PCT
    try:
        saved = await database.get_llm_setting("velocity_min_atr_pct", None)
        if saved:
            VELOCITY_MIN_ATR_PCT = round(float(saved), 2)
        for profile in ("5m", "15m"):
            key = f"velocity_min_atr_pct_{profile}"
            val = await database.get_llm_setting(key, None)
            if val:
                max_allowed = VELOCITY_PROFILE_CALIB.get(profile, {}).get("max_atr", 0.50)
                _velocity_profile_atr[profile] = min(max_allowed, round(float(val), 2))
        _velocity_learning_state["active_filters"] = {
            "min_atr_pct": VELOCITY_MIN_ATR_PCT,
            "profile_atr": {k: v for k, v in _velocity_profile_atr.items() if v is not None},
        }
    except Exception as exc:
        logger.warning("velocity ATR profilleri başlangıçta yüklenemedi: %s", exc)


async def velocity_learning_loop():
    """Ufku dolan hız adaylarını (5dk-%2 ve 15dk-%3) kapanmış M1 mumlarıyla
    ölç; eşikleri canlı dokunuş oranına göre ayarla; LLM'e postmortem bağlamı
    kaydet."""
    await asyncio.sleep(120)
    global VELOCITY_MIN_ATR_PCT
    # Kalibre edilmiş eşikleri kalıcı depodan geri yükle; aksi halde her restart
    # öğrenilen değeri fabrika ayarına sıfırlıyordu. load_velocity_atr_profiles
    # startup'ta hemen yükler; buradaki yükleme yedek/güncelleme amaçlıdır.
    try:
        saved = await database.get_llm_setting("velocity_min_atr_pct", None)
        if saved:
            VELOCITY_MIN_ATR_PCT = round(float(saved), 2)
        for profile in ("5m", "15m"):
            key = f"velocity_min_atr_pct_{profile}"
            val = await database.get_llm_setting(key, None)
            if val:
                max_allowed = VELOCITY_PROFILE_CALIB.get(profile, {}).get("max_atr", 0.50)
                _velocity_profile_atr[profile] = min(max_allowed, round(float(val), 2))
        _velocity_learning_state["active_filters"] = {
            "min_atr_pct": VELOCITY_MIN_ATR_PCT,
            "profile_atr": {k: v for k, v in _velocity_profile_atr.items() if v is not None},
        }
    except Exception as exc:
        logger.warning("velocity eşikleri geri yüklenemedi: %s", exc)
    while True:
        try:
            pending = await database.get_pending_velocity_candidates(limit=200)
            measured = 0
            # N+1 önlemi: her pending aday için SIRAYLA fetch_klines çağırmak
            # (200 aday × 1 REST = tur başına 200 istek) yerine semaphore'lu
            # paralel çekim yapıyoruz. Rate limit + gecikme düşer. 2026-09-05.
            sem = asyncio.Semaphore(10)
            fetch_results: dict[str, list | None] = {}

            async def _fetch_one(candidate: dict):
                symbol = candidate["symbol"]
                created_ms = int(float(candidate["created_at"]) * 1000)
                max_horizon = int(getattr(config, "MONITORING_OUTCOME_WINDOW_MINUTES", 60))
                now_ms = int(time.time() * 1000)
                due_ms = created_ms + max_horizon * 60_000
                fetch_to_ms = min(now_ms, due_ms + 65_000)
                bars_needed = min(max_horizon + 15, max(5, int((fetch_to_ms - created_ms) / 60_000) + 5))
                try:
                    async with sem:
                        # D-13: bu REST yolu eskiden limiter'ı atlıyordu; artık
                        # tarama/ölçüm çağrılarıyla AYNI token bucket'tan geçer.
                        await _velocity_rate_acquire()
                        rows = await fetch_klines(symbol, "1m", bars_needed, created_ms, fetch_to_ms)
                    fetch_results[candidate["candidate_id"]] = rows
                except Exception:
                    fetch_results[candidate["candidate_id"]] = None

            if pending:
                await asyncio.gather(*(_fetch_one(c) for c in pending))

            for candidate in pending:
                candidate_id = str(candidate.get("candidate_id", ""))
                rows = fetch_results.get(candidate_id)
                if not rows:
                    continue
                symbol = candidate["symbol"]
                created_ms = int(float(candidate["created_at"]) * 1000)
                max_horizon = int(getattr(config, "MONITORING_OUTCOME_WINDOW_MINUTES", 60))
                due_ms = created_ms + max_horizon * 60_000
                now_ms = int(time.time() * 1000)

                # Tarama anı bir M1 mumun ortasına denk gelebilir; o PARSİYEL mum
                # "atak öncesi" sayılır ve HARİÇ tutulur (R5-C4.4): aksi halde
                # mumun tüm dakikaya yayılan high'ı sinyal-öncesi hareketi MFE'ye katar.
                window = _post_signal_window(rows, created_ms, min(now_ms, due_ms))
                if not window:
                    continue
                entry = float(candidate["price"])
                if entry <= 0:
                    continue

                target_pct = float(candidate["target_pct"])
                # D-15 (2026-09-26): config'te `AUTO_PAPER_SL_PCT` ADI YOK;
                # yalnızca `AUTO_PAPER_SL_PCT_DEFAULT` var. getattr sessizce
                # varsayılan 1.5'e düşüyordu, yani env ile ayarlanan SL
                # (örn. %3.0) journal ölçümünde HİÇ kullanılmıyordu ve
                # `velocity_calibrate` yanlış geometriye göre optimize ediyordu.
                sl_pct = float(getattr(config, "AUTO_PAPER_SL_PCT_DEFAULT", 1.5))
                cost_pct = round_trip_cost_pct()

                # Gerçekçi işlem yaşam döngüsü: Mum bazlı sıralı TP ve SL kontrolü
                # D-16 (2026-09-26): bar içi sıra bilinmediği için belirsiz
                # barda worst-case (SL) kabul edilir — `passing_hit_rate`
                # artık sistematik olarak şişmez.
                first_hit, hit_bar = _first_stop_or_target_bar(
                    window, entry, target_pct, sl_pct)
                hit_target = (first_hit == "take_profit")
                hit_stop = (first_hit == "stop_loss")
                touch_bar = hit_bar if hit_target else None
                stop_bar = hit_bar if hit_stop else None

                expired = (now_ms >= due_ms)

                # Ne hedefe ne stop'a dokundu ve henüz maksimum süre (60 dk) dolmadıysa beklemeye devam et
                if not hit_target and not hit_stop and not expired:
                    continue

                mfe_pct = _mfe_from_window(window, entry) or 0.0
                touched = hit_target
                # D-16: belirsiz barda (TP+SL aynı mum) SL kabul edildiği
                # için `touched=False`; kayıt nedenini saklar.
                ambiguous = bool(hit_stop and stop_bar is not None
                                 and (float(stop_bar[2]) / entry - 1) * 100 >= target_pct)

                if hit_target:
                    exit_pct = target_pct
                    net_pct = exit_pct - cost_pct
                    touch_sec = max(0, int((int(touch_bar[0]) + 59_999 - created_ms) / 1000)) if touch_bar else None
                    details = {
                        "window_bars": len(window),
                        "entry": entry,
                        "target_pct": target_pct,
                        "touch_sec": touch_sec,
                        "touched_at_minute": round((touch_sec or 0) / 60, 1),
                        "status_reason": "TARGET_HIT",
                        "intrabar_ambiguous": False
                    }
                elif hit_stop:
                    exit_pct = -sl_pct
                    net_pct = exit_pct - cost_pct
                    stop_sec = max(0, int((int(stop_bar[0]) + 59_999 - created_ms) / 1000)) if stop_bar else None
                    details = {
                        "window_bars": len(window),
                        "entry": entry,
                        "target_pct": target_pct,
                        "stop_sec": stop_sec,
                        "stopped_at_minute": round((stop_sec or 0) / 60, 1),
                        "status_reason": "STOPPED_OUT",
                        "intrabar_ambiguous": ambiguous
                    }
                else:  # expired
                    exit_pct = _exit_pct_from_window(window, entry)
                    net_pct = (exit_pct - cost_pct) if exit_pct is not None else None
                    details = {
                        "window_bars": len(window),
                        "entry": entry,
                        "target_pct": target_pct,
                        "status_reason": "MAX_HORIZON_EXPIRED"
                    }

                ok = await database.mark_velocity_candidate_evaluated(
                    candidate["candidate_id"], mfe_pct=round(mfe_pct, 4),
                    touched_target=touched,
                    exit_pct=(round(exit_pct, 4) if exit_pct is not None else None),
                    net_pct=(round(net_pct, 4) if net_pct is not None else None),
                    details=details)
                if ok:
                    measured += 1
                    # Sembol bazli adaptif hedef ogrenmesini gercek olcümle guncelle;
                    # hedefe dokunulduysa basari, dokunulmadiysa basarisiz kaydedilir
                    try:
                        await database.record_symbol_target_outcome(
                            symbol, success=touched, achieved_pct=round(mfe_pct, 3))
                    except Exception as exc:
                        logger.warning('velocity hedef durumu guncellenemedi %s: %s', symbol, exc)
                    # LLM hafıza katmanına kanıt olarak yaz (postmortem döngüsü okur)
                    await embedding_worker.enqueue_persistent(build_document(
                        layer="symbol", scope=f"velocity-outcome:{symbol}", symbol=symbol,
                        source_type="velocity_candidate_outcome", source_id=str(candidate["candidate_id"]),
                        content=json.dumps({
                            "candidate": {k: candidate.get(k) for k in ("atr_pct", "volume_ratio", "ret3_pct", "velocity_score", "passes")},
                            "outcome": {"mfe_pct": round(mfe_pct, 3), "touched_target": touched},
                        }, ensure_ascii=False, default=str),
                        metadata={"source_type": "velocity_candidate_outcome",
                                  "touched_target": touched, "passes": candidate.get("passes")},
                        observed_at=time.time()))
            if measured:
                _velocity_learning_state["measured"] = _velocity_learning_state.get("measured", 0) + measured
            # Kalibrasyon her döngüde değerlendirilir (yeni ölçüm olmasa bile
            # mevcut istatistikler zamanla değişebilir). Profil bazlıdır.
            try:
                cal_changed, by_profile = await velocity_calibrate()
            except Exception as exc:
                logger.warning("velocity kalibrasyon hatası: %s", exc)
                by_profile = {}
                cal_changed = False
            _velocity_learning_state["active_filters"] = {
                "min_atr_pct": VELOCITY_MIN_ATR_PCT,
                "profile_atr": {k: v for k, v in _velocity_profile_atr.items() if v is not None},
                "min_bb_width_pct": VELOCITY_MIN_BB_WIDTH_PCT,
                "trend_rsi_min": VELOCITY_TREND_RSI_MIN,
                "reversal_rsi_max": VELOCITY_REVERSAL_RSI_MAX,
                "by_profile": by_profile,
            }
            # Ölü/sessiz sembollerde mum hiç gelmediği için sonsuza dek pending
            # kalan kayıtları temizle — istatistikleri şişirmesini önler.
            expired = await database.cleanup_stale_velocity_candidates()
            if expired:
                logger.info("velocity: %s ölü pending kayıt expired işaretlendi", expired)
            _velocity_learning_state.update({"last_run_at": time.time(), "last_error": None})
            # Kalp atışı: ölçüm döngüsünün canlı olduğunu llm_settings'e yaz (rapor/izleme).
            try:
                await database.set_llm_setting('velocity_learner_last_heartbeat', str(time.time()))
            except Exception:
                pass
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _velocity_learning_state.update({"last_run_at": time.time(), "last_error": str(exc)})
            logger.exception("velocity learning loop: %s", exc)
        await asyncio.sleep(60)


@router.get("/api/market-snapshot/velocity-5m")
async def market_snapshot_velocity_5m(limit: int = 3):
    return await detect_velocity_candidates({"limit": limit}, horizon_minutes=5)


@router.get("/api/market-snapshot/velocity-15m")
async def market_snapshot_velocity_15m(limit: int = 3):
    """15 dakikada +%3 hedefli hız avcısı; aynı v2 filtre seti, ayrı journal profili."""
    return await detect_velocity_candidates({"limit": limit}, horizon_minutes=15)


@router.get("/api/reports/velocity")
async def get_velocity_report(limit: int = 60):
    """Hız avcısı journal'ı: koşullu dokunuş başarısı + öğrenme durumu."""
    stats = await database.get_velocity_calibration_stats()
    stats_5m = await database.get_velocity_calibration_stats(profile="5m")
    stats_15m = await database.get_velocity_calibration_stats(profile="15m")
    pattern_hit_rates = await database.get_velocity_pattern_hit_rates()
    recent = await database.get_velocity_candidates(limit=limit)
    evaluated = int(stats.get("evaluated_count") or 0)
    touched = int(stats.get("touched_count") or 0)
    passing = int(stats.get("passing_count") or 0)
    passing_touched = int(stats.get("passing_touched_count") or 0)

    def _profile_stats(raw):
        p = int(raw.get("passing_count") or 0)
        pt = int(raw.get("passing_touched_count") or 0)
        return {"passing_count": p, "passing_touched": pt,
                "passing_hit_rate": pt / p if p else None,
                "evaluated": int(raw.get("evaluated_count") or 0)}
    # Sembol bazında başarı
    symbol_rows = [row for row in recent if row.get("status") == "evaluated"]
    by_symbol: dict[str, dict] = {}
    for row in symbol_rows:
        bucket = by_symbol.setdefault(row["symbol"], {"evaluated": 0, "touched": 0, "sum_mfe": 0.0})
        bucket["evaluated"] += 1
        bucket["touched"] += 1 if row.get("touched_target") else 0
        bucket["sum_mfe"] += float(row.get("mfe_pct") or 0)
    symbols = [{"symbol": symbol, "evaluated": bucket["evaluated"],
                "touched": bucket["touched"],
                "touch_rate": bucket["touched"] / bucket["evaluated"] if bucket["evaluated"] else None,
                "average_mfe_pct": bucket["sum_mfe"] / bucket["evaluated"] if bucket["evaluated"] else None}
               for symbol, bucket in sorted(by_symbol.items(), key=lambda kv: -kv[1]["evaluated"])]
    return {"paper_only": True,
            "stats": {"total": int(stats.get("total") or 0), "pending": int(stats.get("pending_count") or 0),
                       "evaluated": evaluated, "touched": touched,
                       "touch_rate": touched / evaluated if evaluated else None,
                       "average_mfe_pct": stats.get("average_mfe_pct"),
                       "passing_count": passing, "passing_touched": passing_touched,
                       "passing_hit_rate": passing_touched / passing if passing else None,
                       "passing_average_mfe_pct": stats.get("passing_mfe_pct")},
            "stats_by_profile": {"5m": _profile_stats(stats_5m), "15m": _profile_stats(stats_15m)},
            "pattern_hit_rates": pattern_hit_rates,
            "filters": {"min_atr_pct": VELOCITY_MIN_ATR_PCT,
                         "profile_atr": {k: v for k, v in _velocity_profile_atr.items() if v is not None},
                         "min_bb_width_pct": VELOCITY_MIN_BB_WIDTH_PCT,
                         "trend_rsi_min": VELOCITY_TREND_RSI_MIN,
                         "reversal_rsi_max": VELOCITY_REVERSAL_RSI_MAX,
                         "struct_slope_pct": VELOCITY_STRUCT_SLOPE_PCT},
            "learning_state": dict(_velocity_learning_state),
            "auto_trade": {"enabled": bool(config.VELOCITY_AUTO_ENABLED and (await database.get_llm_setting("llm_paper_trade_enabled", "0")) == "1"),
                            "interval_sec": config.VELOCITY_AUTO_INTERVAL_SEC,
                            "balance_pct": config.VELOCITY_AUTO_BALANCE_PCT,
                            "sl_pct": config.VELOCITY_AUTO_SL_PCT,
                            "trail_trigger_pct": config.VELOCITY_TRAIL_TRIGGER_PCT,
                            "state": {k: v for k, v in _velocity_auto_state.items() if k != "opened"},
                            "microstructure_filters": {
                                "whale_distribution_enabled": bool(config.VELOCITY_WHALE_DISTRIBUTION_FILTER),
                                "flow_confirmation_enabled": bool(config.VELOCITY_FLOW_CONFIRMATION_FILTER),
                                "skip_counts": dict(_velocity_auto_state["filters"]),
                                "note": "Filtreler varsayılan kapalı; istatistik toplanırken giriş kalitesi değişmez. Canlı istatistik sonrası açılabilir.",
                            },
                            "recent_opens": list(_velocity_auto_state["opened"][-5:])},
            "symbols": symbols[:20], "recent": recent}



@router.delete("/api/reports/velocity/{candidate_id}")
async def delete_velocity_candidate(candidate_id: str, request: Request = None):
    """Journal temizliği: geçersiz/ölü sembol kaydını raporlardan kaldırır."""
    from app.api_common import require_admin as _require_admin
    _require_admin(request)
    deleted = await database.delete_velocity_candidates([candidate_id])
    if not deleted:
        raise HTTPException(status_code=404, detail="Kayıt bulunamadı")
    return {"ok": True, "deleted": deleted, "paper_only": True}


@router.post("/api/reports/velocity/{candidate_id}/remeasure")
async def remeasure_velocity_candidate(candidate_id: str, request: Request = None):
    """Journal satırını kapanmış M1 mumlarla yeniden ölçer.

    Eski/yanlış ölçülmüş kayıtlar için: pencere (created → created+5dk)
    yeniden hesaplanır, MFE ve dokunuş journal'a tekrar yazılır.
    """
    from app.api_common import require_admin as _require_admin
    _require_admin(request)
    rows = await database.get_velocity_candidates(limit=200)
    candidate = next((r for r in rows if r["candidate_id"] == candidate_id), None)
    if not candidate:
        raise HTTPException(status_code=404, detail="Kayıt bulunamadı")
    symbol = candidate["symbol"]
    max_horizon = int(getattr(config, "MONITORING_OUTCOME_WINDOW_MINUTES", 60))
    created_ms = int(float(candidate["created_at"]) * 1000)
    due_ms = created_ms + max_horizon * 60_000
    try:
        rows1m = await fetch_klines(symbol, "1m", max_horizon + 15, created_ms, due_ms + 65_000)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"mum verisi alınamadı: {exc}")
    # R5-C4.4: sinyal anını içeren parsiyel mum HARİÇ (aynı `_post_signal_window`).
    window = _post_signal_window(rows1m, created_ms, due_ms)
    if len(window) < 3:
        raise HTTPException(status_code=409, detail=f"pencere mumları yetersiz: {len(window)}")
    entry = float(candidate["price"])
    target_pct = float(candidate["target_pct"])
    # D-15 (2026-09-26): gerçek config alanı `AUTO_PAPER_SL_PCT_DEFAULT`
    # (yukarıdaki ölçüm döngüsüyle aynı düzeltme).
    sl_pct = float(getattr(config, "AUTO_PAPER_SL_PCT_DEFAULT", 1.5))
    cost_pct = round_trip_cost_pct()

    hit_target = False
    hit_stop = False
    touch_bar = None
    stop_bar = None

    # D-16 (2026-09-26): yeniden ölçüm de AYNI belirsizlik kuralını kullanır
    # (`_first_stop_or_target_bar`) — aksi halde "hepsini yeniden ölç" işlemi
    # ölçüm döngüsünün düzelttiği iyimserliği geri getirirdi.
    first_hit, hit_bar = _first_stop_or_target_bar(window, entry, target_pct, sl_pct)
    hit_target = (first_hit == "take_profit")
    hit_stop = (first_hit == "stop_loss")
    touch_bar = hit_bar if hit_target else None
    stop_bar = hit_bar if hit_stop else None

    mfe_pct = _mfe_from_window(window, entry) or 0.0
    touch_sec = int((int(touch_bar[0]) + 59_999 - created_ms) / 1000) if hit_target and touch_bar else None
    stop_sec = int((int(stop_bar[0]) + 59_999 - created_ms) / 1000) if hit_stop and stop_bar else None

    if hit_target:
        exit_pct = target_pct
        net_pct = exit_pct - cost_pct
        reason = "TARGET_HIT"
    elif hit_stop:
        exit_pct = -sl_pct
        net_pct = exit_pct - cost_pct
        reason = "STOPPED_OUT"
    else:
        exit_pct = _exit_pct_from_window(window, entry) or 0.0
        net_pct = exit_pct - cost_pct
        reason = "MAX_HORIZON_EXPIRED"

    # D-16: belirsiz barda hem TP hem SL eşiği aşılmıştı; kayıt bunu
    # açıkça taşır ki yeniden ölçüm/analiz "neden SL?" sorusunu cevaplayabilsin.
    ambiguous = bool(hit_bar is not None and hit_stop
                     and (float(hit_bar[2]) / entry - 1) * 100 >= target_pct)

    await database.mark_velocity_candidate_evaluated(
        candidate_id, mfe_pct=round(mfe_pct, 4), touched_target=hit_target,
        exit_pct=round(exit_pct, 4), net_pct=round(net_pct, 4),
        details={"remeasured": True, "window_bars": len(window),
                 "window_first": datetime.fromtimestamp(int(window[0][0]) / 1000, tz=timezone(timedelta(hours=3))).strftime("%H:%M"),
                 "window_last": datetime.fromtimestamp(int(window[-1][0]) / 1000, tz=timezone(timedelta(hours=3))).strftime("%H:%M"),
                 "entry": entry, "target_pct": candidate["target_pct"], "touch_sec": touch_sec,
                 "stop_sec": stop_sec, "status_reason": reason,
                 "intrabar_ambiguous": ambiguous},
        force=True)
    return {"ok": True, "paper_only": True, "mfe_pct": round(mfe_pct, 3),
            "touched_target": hit_target, "window_bars": len(window),
            "window_first": datetime.fromtimestamp(int(window[0][0]) / 1000, tz=timezone(timedelta(hours=3))).strftime("%H:%M"),
            "window_last": datetime.fromtimestamp(int(window[-1][0]) / 1000, tz=timezone(timedelta(hours=3))).strftime("%H:%M"),
            "intrabar_ambiguous": ambiguous,
            "touch_sec": touch_sec}


@router.post("/api/reports/velocity/remeasure-all")
async def remeasure_all_velocity(request: Request = None):
    """Journal'daki tüm ölçülmüş kayıtları yeniden ölçer (sunucu saati/veri
    tutarsızlıklarını topluca gidermek için)."""
    from app.api_common import require_admin as _require_admin
    _require_admin(request)
    rows = await database.get_velocity_candidates(limit=300)
    remeasured, failed = 0, []
    for candidate in rows:
        if candidate["status"] != "evaluated":
            continue
        try:
            await remeasure_velocity_candidate(candidate["candidate_id"])
            remeasured += 1
        except HTTPException as exc:
            failed.append({"candidate_id": candidate["candidate_id"], "detail": exc.detail})
    return {"ok": True, "paper_only": True, "remeasured": remeasured, "failed": failed[:10]}


@router.get("/api/velocity/status")
async def velocity_status():
    """Hız Avcısı otonom tarama durumu: son tarama zamanı, M5 kapanış zamanı,
    aday havuzu boyutu, desen filtresi durumu."""
    return {
        "ok": True,
        "auto_enabled": bool(config.VELOCITY_AUTO_ENABLED and
                             (await database.get_llm_setting("llm_paper_trade_enabled", "0")) == "1"),
        # ``auto_enabled`` ayar kapısını yansıtır (env + DB). ``loop_running``
        # ise döngünün GERÇEKTEN ÇALIŞTIĞINI gösterir (G-16, 2026-09-12): görev
        # nesnesinin done() durumu + heartbeat tazeliği. Eskiden yapışkan
        # `_VELOCITY_AUTO_LOOP_STARTED` bayrağı okunuyordu ve döngü öldükten
        # sonra da True kalıyordu. `loop_started` ham bayrağı (gözlem) korur.
        "loop_running": velocity_loop_running(),
        "loop_started": _VELOCITY_AUTO_LOOP_STARTED,
        "pool_size": config.VELOCITY_POOL_SIZE,
        "pattern_filter_enabled": config.VELOCITY_PATTERN_FILTER_ENABLED,
        "sl_pct": config.VELOCITY_AUTO_SL_PCT,
        "reentry_hard_stop_block_sec": config.VELOCITY_HARD_STOP_REENTRY_BLOCK_SEC,
        "reentry_cooldown_bars": config.VELOCITY_REENTRY_COOLDOWN_BARS,
        "last_scan_at": _velocity_auto_state.get("last_scan_at"),
        "last_m5_close_ms": _velocity_auto_state.get("last_m5_close_ms"),
        "total_opened": _velocity_auto_state.get("total_opened", 0),
        "last_error": _velocity_auto_state.get("last_error"),
        "last_open": _velocity_auto_state.get("last_open"),
        "recent_opens": list(_velocity_auto_state.get("opened", [])[-5:]),
        "server_time": time.time(),
    }


@router.post("/api/velocity/manual-scan")
async def manual_velocity_scan():
    """Manuel hız avcısı taraması: 5dk-%2 + 15dk-%3 profillerini tarar,
    en yüksek skorlu adaya (GEÇTİ veya İZLEME) paper pozisyon açar.

    Otonom döngüyle AYNI kapılardan geçer; buton bunu anında tetikler.
    D-13 (2026-09-26): otonom döngünün iki filtresi burada EKSİKTİ:
      1) havuz filtresi — `analyzer.positions`'ta olan semboller havuzdan
         çıkarılır (otonom döngü `velocity.py:2219`), aksi halde manuel
         tarama açık pozisyonu olan bir adaya basar ve `_open_velocity_position`
         ancak en sonda `acik_pozisyon_var` diyerek boşa döner; kullanıcı
         aday görür ama hiçbir açılış olmaz.
      2) yönlendirme bayrağı — `RADAR_ROUTE_VELOCITY_AUTO_THROUGH_AUTO_PAPER`
         açıkken otonom döngü `_route_velocity_through_auto_paper` çağırır;
         manuel tarama bunu yok sayıp doğrudan analyzer'a gidiyordu, yani
         iki yol aynı anda iki farklı defter kullanabiliyordu (tek defter
         sözleşmesi ihlali).
    """
    scan5 = await detect_velocity_candidates({}, horizon_minutes=5)
    scan15 = await detect_velocity_candidates({}, horizon_minutes=15)
    raw_pool = (list(scan5.get("candidates") or []) + list(scan5.get("watchlist") or [])
                + list(scan15.get("candidates") or []) + list(scan15.get("watchlist") or []))
    # (1) Havuz filtresi — otonom döngüyle birebir aynı.
    pool = [c for c in raw_pool
            if str(c.get("symbol") or "").upper() not in analyzer.positions]
    filtered_out = [str(c.get("symbol") or "").upper() for c in raw_pool
                    if str(c.get("symbol") or "").upper() in analyzer.positions]
    # Sıralama: ham skor × sembol kalite çarpanı (otonom döngüyle aynı kapılar).
    touch_rates = await _journal_touch_rates()
    pool.sort(key=lambda c: -_rank_score(c, touch_rates))
    if not pool:
        return {"ok": True, "paper_only": True, "opened": False,
                "message": ("Şu an koşulları geçen aday yok; yüksek salınım rejimi bekleniyor."
                            if not filtered_out else
                            "Adaylar tarandı ama tümü zaten açık pozisyon taşıyor."),
                "filtered_open_positions": filtered_out,
                "scan5": {"candidates": scan5.get("candidates", []), "watchlist": scan5.get("watchlist", [])},
                "scan15": {"candidates": scan15.get("candidates", []), "watchlist": scan15.get("watchlist", [])}}
    best = pool[0]
    # (2) Yönlendirme bayrağı — otonom döngüyle aynı karar.
    if getattr(config, "RADAR_ROUTE_VELOCITY_AUTO_THROUGH_AUTO_PAPER", False):
        outcome = await _route_velocity_through_auto_paper(best)
    else:
        outcome = await _open_velocity_position(best)
    _velocity_auto_state["last_open"] = outcome
    if outcome.get("status") == "PAPER_OPENED":
        _velocity_auto_state["total_opened"] += 1
        _velocity_auto_state["opened"].append({**outcome, "at": time.time(),
                                                "score": best.get("velocity_score"),
                                                "horizon": best.get("horizon_minutes"),
                                                "manual": True})
        del _velocity_auto_state["opened"][:-20]
    return {"ok": True, "paper_only": True,
            "opened": outcome.get("status") == "PAPER_OPENED",
            "best_candidate": best, "outcome": outcome,
            "filtered_open_positions": filtered_out,
            "routed_via": "auto_paper" if getattr(config, "RADAR_ROUTE_VELOCITY_AUTO_THROUGH_AUTO_PAPER", False) else "analyzer",
            "scan5": {"candidates": scan5.get("candidates", []), "watchlist": scan5.get("watchlist", [])},
            "scan15": {"candidates": scan15.get("candidates", []), "watchlist": scan15.get("watchlist", [])}}


@router.get("/api/reports/velocity/live")
async def get_velocity_live_tracking():
    """Canlı izleme: son taramaların adaylarını güncel fiyatla takip eder.

    Her aday için: analiz anındaki giriş fiyatı, güncel fiyat, +%2'ye ulaşıp
    ulaşılmadığı, ulaşıldıysa kaç saniyede ulaşıldığı. Adayın kendi ufku (5dk/15dk) ve hedefi dolunca
    durum kesinleşir; öğrenme döngüsü nihai sonucu journal'a yazar.
    """
    import datetime as _dt
    tz_tr = _dt.timezone(_dt.timedelta(hours=3))  # GMT+3 sabit
    now_ms = int(time.time() * 1000)
    rows = await database.get_velocity_candidates(limit=25)
    # Canlı takip: penceresi hâlâ açık olanlar + kapanmış ama journal'a henüz
    # yazılmamışlar. Süresi dolup değerlendirilenler rapordan düşer (Son
    # Adaylar sekmesinde kalıcı olarak yaşar).
    # Düzeltme (2026-09-12): pencere sabit 5dk DEĞİL — her satırın ufku
    # candidate_id'den okunur (15dk adaylar eskiden 5dk'da "süresi doldu"
    # sayılıyordu). Ufuk okunamazsa 5dk fallback korunur.
    max_horizon_min = int(getattr(config, "MONITORING_OUTCOME_WINDOW_MINUTES", 60))
    max_horizon_sec = max_horizon_min * 60
    rows = [r for r in rows
            if r["status"] == "pending"
            or now_ms / 1000 - float(r["created_at"]) <= max_horizon_sec]
    sem = asyncio.Semaphore(6)
    tracked = []

    async def track(row):
        symbol = row["symbol"]
        entry = float(row["price"])
        created_ms = int(float(row["created_at"]) * 1000)
        due_ms = created_ms + max_horizon_min * 60_000
        try:
            row_target_pct = float(row.get("target_pct"))
        except (TypeError, ValueError):
            row_target_pct = None
        touch_ratio = (1 + row_target_pct / 100.0) if (row_target_pct and row_target_pct > 0) else 1.02
        # Kapanmış M1 mumlardan pencere içi tepe + dokunuş anı (5 sn çözünürlük için mum üstü)
        best_high, touch_sec = None, None
        try:
            bars_needed = min(max_horizon_min + 15, max(5, int((now_ms - created_ms) / 60_000) + 5))
            window_rows = await fetch_klines(symbol, "1m", bars_needed, created_ms, min(now_ms, due_ms + 65_000))
            # R5-C4.4: sinyal anını içeren parsiyel mum HARİÇ (aynı `_post_signal_window`).
            window = _post_signal_window(window_rows, created_ms, min(now_ms, due_ms))
            if entry > 0:
                touched_high = max((float(r[2]) for r in window if float(r[2]) / entry >= touch_ratio), default=None)
                best_high = max((float(r[2]) for r in window), default=None)
                if touched_high is not None:
                    touch_bar = next(r for r in window if float(r[2]) == touched_high)
                    touch_sec = max(0, int((int(touch_bar[0]) + 59_999 - created_ms) / 1000))
        except Exception:
            window = []
        # güncel fiyat: pencere içindeyse en son kapanmış mum, pencere bittiyse son fiyat
        try:
            fresh = await ticker_price([symbol])
            row = next((r for r in fresh if str(r.get("symbol", "")).upper() == symbol), None)
            current_price = float((row or {}).get("price") or 0) or None
        except Exception:
            current_price = None
        elapsed_sec = int((now_ms - created_ms) / 1000)
        window_closed = now_ms >= due_ms
        touched = touch_sec is not None
        if row["status"] == "evaluated":
            journal_touched = bool(row.get("touched_target"))
            journal_mfe = row.get("mfe_pct")
        else:
            journal_touched = None  # henüz öğrenme döngüsü yazmadı
            journal_mfe = None
        # Pencere içi en iyi hareket: kapanmış mumlardan (canlı) ve journal'dan
        # (ölçülmüşse) ikisinin büyüğü.
        live_mfe = ((best_high / entry - 1) * 100) if (best_high and entry) else None
        mfe_values = [v for v in (live_mfe, journal_mfe) if v is not None]
        effective_mfe = max(mfe_values) if mfe_values else None
        # Üçlü sınıflandırma (pencere kapandığında kesinleşir):
        #   success → +%2 hedefini geçti
        #   ok      → giriş fiyatının üzerine çıktı ama +%2'ye ulaşmadı
        #   failed  → pencere boyunca giriş fiyatının üzerine hiç çıkamadı
        if touched or journal_touched is True:
            outcome = "success"
        elif window_closed and journal_touched is False:
            outcome = "ok" if (effective_mfe is not None and effective_mfe > 0) else "failed"
        else:
            outcome = "pending"
        tracked.append({
            "candidate_id": row["candidate_id"], "symbol": symbol,
            "entry_price": entry, "current_price": current_price,
            "change_pct": round((current_price / entry - 1) * 100, 3) if current_price and entry else None,
            "target_pct": float(row["target_pct"]),
            "passes": bool(row.get("passes")),
            "velocity_score": row.get("velocity_score"),
            "status": row["status"],
            "touched": touched or (journal_touched is True),
            "journal_touched": journal_touched,
            "outcome": outcome,
            "touch_sec": touch_sec,
            "best_mfe_pct": round(effective_mfe, 3) if effective_mfe is not None else None,
            "elapsed_sec": elapsed_sec, "remaining_sec": max(0, int((due_ms - now_ms) / 1000)),
            "window_closed": window_closed,
            "window_time": _dt.datetime.fromtimestamp(created_ms / 1000, tz=tz_tr).strftime("%H:%M:%S"),
        })

    await asyncio.gather(*(track(r) for r in rows))
    rank_order = {"success": 0, "ok": 1, "pending": 2, "failed": 3}
    tracked.sort(key=lambda r: (rank_order.get(r["outcome"], 2), -r["elapsed_sec"]))
    counts = {"success": 0, "ok": 0, "failed": 0, "pending": 0}
    for r in tracked:
        counts[r["outcome"]] += 1
    return {"paper_only": True, "server_time": now_ms / 1000, "counts": counts, "tracking": tracked}


_velocity_auto_state = {"last_scan_at": None, "last_error": None, "opened": [],
                          "last_open": None, "total_opened": 0,
                          # G-16 (2026-09-12): her turda güncellenen kalp atışı.
                          "last_heartbeat_at": None,
                          "filters": {"whale_dagilim_reddet": 0, "akis_aykiri_reddet": 0,
                                      "microflow_yok": 0}}

#: ``autonomous_velocity_loop`` gerçekten başlatıldı mı? Bu bayrak yalnızca
#: döngünün kendisi tarafından True yapılır; startup'a eklenmediği sürece
#: False kalır ve ``velocity_status`` bunu dürüstçe raporlar (Madde 21).
#: G-16 (2026-09-12): yapışkan bayrak TEK BAŞINA yeterli değil — döngü ölse de
#: True kalıyordu. ``velocity_loop_running()`` görev nesnesinin ``done()``
#: durumunu ve heartbeat tazeliğini birlikte raporlar.
_VELOCITY_AUTO_LOOP_STARTED = False
#: main.py startup'ta bu adla başlatır (`_start_background(autonomous_velocity_loop, "velocity-autonomous")`).
_VELOCITY_AUTO_TASK_NAME = "velocity-autonomous"
#: Döngü ~5 sn'de bir tur atar; 120 sn'den uzun sessizlik = ölü.
_VELOCITY_LOOP_HEARTBEAT_TIMEOUT_SEC = 120.0

#: D-13 (2026-09-26 denetimi, KRİTİK) — TOCTOU. Pozisyon limiti kontrolü
#: bellek içi `analyzer.positions` sayımı yapıyordu ve KİLIT DIŞINDAydı:
#: `open_position` birçok await noktası içerdiği (guard, bakiye, likidite,
#: DB commit) iki eşzamanlı görev aynı sayımı yapıp İKİSİ DE limitin
#: altında görünce ikisini de açabiliyordu. `VELOCITY_AUTO_MAX_OPEN_POSITIONS`
#: default 0 (sınırsız) olduğunda bu görünmez, cap>0 iken limit gerçekte
#: iki katına çıkabiliyordu.
#: Çözüm: sayım + "rezervasyon" TEK kilit altında. Uyarı: `analyzer.positions`
#: yalnızca `open_position` SONUNDA güncellenir; bu yüzden kilit altında
#: sayılan pozisyonlara ek olarak uçuşta (in-flight) rezervasyonlar da
#: sayılır. Rezervasyon `try/finally` ile HER ZAMAN serbest bırakılır.
_velocity_open_lock = asyncio.Lock()
#: Şu an açılış sürecinde olan işlem sayısı (kilit altında artırılır/azaltılır).
_velocity_open_inflight = 0


def _velocity_open_count() -> int:
    """Şu an açık velocity_auto pozisyonu + uçuşta açılış sayısı."""
    opened = sum(
        1 for pos in analyzer.positions.values()
        if ((pos.get("entry_context") or {}).get("signal_context") or {}).get("source") == "velocity_auto")
    return opened + _velocity_open_inflight


def velocity_open_position_slots() -> int:
    """Kalan açılış yuvası (çoklu çağıranlar için TEK doğruluk kaynağı)."""
    vel_max = int(getattr(config, "VELOCITY_AUTO_MAX_OPEN_POSITIONS", 0) or 0)
    if vel_max <= 0:
        return -1  # sınırsız
    return max(0, vel_max - _velocity_open_count())


class _VelocitySlotReservation:
    """Async context manager: açılış yuvasını rezerve eder (TOCTOU koruması).

    Kullanım::

        async with _VelocitySlotReservation(symbol) as res:
            if not res.ok:
                return res.result
            ... await-heavy açılış işi ...

    Rezervasyon yalnızca ``VELOCITY_AUTO_MAX_OPEN_POSITIONS > 0`` iken
    anlamlıdır; sınırsız ayarda (0) kilitleme yapılmaz.
    """

    def __init__(self, symbol: str):
        self.symbol = symbol
        self.ok = True
        self.result = None

    async def __aenter__(self):
        global _velocity_open_inflight
        if int(getattr(config, "VELOCITY_AUTO_MAX_OPEN_POSITIONS", 0) or 0) <= 0:
            return self
        async with _velocity_open_lock:
            if _velocity_open_count() >= int(config.VELOCITY_AUTO_MAX_OPEN_POSITIONS):
                self.ok = False
                self.result = {"symbol": self.symbol, "status": "SKIPPED",
                               "reason": "pozisyon_limiti_dolu"}
            else:
                _velocity_open_inflight += 1
        return self

    async def __aexit__(self, exc_type, exc, tb):
        global _velocity_open_inflight
        if int(getattr(config, "VELOCITY_AUTO_MAX_OPEN_POSITIONS", 0) or 0) <= 0:
            return False
        async with _velocity_open_lock:
            _velocity_open_inflight = max(0, _velocity_open_inflight - 1)
        return False


def velocity_loop_running() -> bool:
    """Döngünün GERÇEKTEN çalıştığını raporla (yapışkan boolean DEĞİL — G-16).

    - ``_background_tasks`` içinde ``velocity-autonomous`` görevi aranır; görev
      ``done()`` ise False döner (çökmüş/durmuş döngü artık "çalışıyor" demez).
    - Heartbeat (``last_heartbeat_at``) 120 sn'den eskiyse False döner.
    """
    now = time.time()
    heartbeat = _velocity_auto_state.get("last_heartbeat_at")
    fresh = heartbeat is not None and (now - float(heartbeat)) <= _VELOCITY_LOOP_HEARTBEAT_TIMEOUT_SEC
    try:
        task = next((t for t in _background_tasks
                     if getattr(t, "get_name", lambda: "")() == _VELOCITY_AUTO_TASK_NAME), None)
    except Exception:
        task = None
    if task is not None:
        return (not task.done()) and fresh
    # Görev nesnesi bulunamadı (doğrudan çağrı / test / yeniden kablolama):
    # heartbeat tazeliğine güven; hiç başlamadıysa False.
    return bool(_VELOCITY_AUTO_LOOP_STARTED and fresh)


async def _velocity_24h_quote_volume(symbol: str) -> float | None:
    """Sembolün 24s quoteVolume'unu döndürür (cache öncelikli, tek istek)."""
    cached = float((market.ticker_24h or {}).get(str(symbol).upper(), 0) or 0)
    if cached > 0:
        return cached
    try:
        rows24 = await ticker_24h([symbol])
        return next((float(r.get("quoteVolume", 0) or 0) for r in rows24
                     if str(r.get("symbol", "")).upper() == symbol), None)
    except Exception as exc:
        logger.warning("24h quoteVolume %s: %s", symbol, exc)
        return None


async def _velocity_rest_liquidity_ok(symbol: str, order_value: float) -> tuple[bool, str | None]:
    """Hız avcısı için REST tabanlı likidite kapısı.

    Geleneksel preflight, WebSocket orderbook/ticker tazeliğini şart koşar;
    Top-Gainer'dan yeni gelen sembollerin WS akışı dolana kadar 'stale' sayılıp
    her adayı ENTRY_INELIGIBLE yapabiliyordu. Burada yalnız taze REST verisiyle
    gerçek likidite koşullarını kontrol eder: emir defteri derinliği ve 24s
    quoteVolume. Spread koruması otonom ve manuel taramada tamamen kaldırıldı;
    düşük fiyatlı coinlerde geniş spread işlem açılışını engelliyordu. Tarama
    zaten kapanmış 1m mumlar üzerinden geçtiği için fiyat kalitesi bu kapıyı
    geçen adayda güvence altındadır.
    """
    try:
        book = await orderbook(symbol, 5)
        bids = book.get("bids") or []
        asks = book.get("asks") or []
        if not bids or not asks:
            return False, "emir_defteri_bos"
        bid, ask = float(bids[0][0]), float(asks[0][0])
        if bid <= 0:
            return False, "gecersiz_fiyat"
        depth_try = (sum(float(q) for _, q in bids[:5]) + sum(float(q) for _, q in asks[:5])) * ((bid + ask) / 2)
        if depth_try < order_value * config.MIN_ORDERBOOK_DEPTH_MULTIPLIER:
            return False, f"derinlik_yetersiz:{depth_try:.0f}TRY"
    except Exception as exc:
        return False, f"orderbook_hata:{type(exc).__name__}"
    try:
        rows24 = await ticker_24h([symbol])
        qv = next((float(r.get("quoteVolume", 0) or 0) for r in rows24
                   if str(r.get("symbol", "")).upper() == symbol), None)
        if qv is None:
            qv = await _velocity_24h_quote_volume(symbol)
        if qv is not None and qv < config.MIN_24H_QUOTE_VOLUME_TRY:
            return False, f"24s_hacim_dusuk:{qv:.0f}TRY"
    except Exception:
        pass  # ticker erişilemezse spread+derinlik yeterli güvence
    return True, None


async def _hydrate_market_cache_for(symbol: str):
    """Top-Gainer adayının market önbelleğini REST'ten doldurur.

    market.ticker_24h / market.klines yalnız başlangıç sembol listesi için
    dolar; Top-Gainer'dan gelen yeni sembollerin recheck'i 0 hacim/derinlik
    üzerinden reddediliyordu. Bu fonksiyon tek sembolün 24s ticker'ını,
    1m kline geçmişini ve orderbook akışını önbelleğe işler.
    """
    try:
        # D-13: bu REST yolu eskiden limiter'ı atlıyordu (ticker+klines+orderbook
        # = 4 istek/sembol). Artık token bucket üzerinden geçer.
        await _velocity_rate_acquire()
        rows = await ticker_24h([symbol])
        row = next((r for r in rows if str(r.get("symbol", "")).upper() == symbol), None)
        if row:
            qv = float(row.get("quoteVolume", 0) or 0)
            last_price = float(row.get("lastPrice", 0) or 0)
            market.ticker_24h[symbol] = qv
            if last_price > 0:
                now_ms = int(time.time() * 1000)
                market.tickers[symbol] = {**(market.tickers.get(symbol) or {}),
                                            "symbol": symbol, "last_price": last_price,
                                            "timestamp": now_ms, "source": "binance_tr_public_rest"}
    except Exception as exc:
        logger.warning("hydrate ticker %s: %s", symbol, exc)
    try:
        # 1m (ATR kapasite + hız hesapları) ve 5m (preflight/recheck)
        # ikisini de doldur; aksi halde recheck 0 bar üzerinden yanlış
        # reddediyor. MOMENTUM_TIMEFRAME kaldırıldı; sabit "5m" kullanılır.
        for tf in ("1m", "5m"):
            await _velocity_rate_acquire()
            kline_rows = await fetch_klines(symbol, tf, 120)
            if kline_rows:
                market.klines.setdefault(tf, {})[symbol] = {
                    "timestamps": [int(r[0]) for r in kline_rows],
                    "opens": [float(r[1]) for r in kline_rows],
                    "highs": [float(r[2]) for r in kline_rows],
                    "lows": [float(r[3]) for r in kline_rows],
                    "closes": [float(r[4]) for r in kline_rows],
                    "volumes": [float(r[5]) for r in kline_rows],
                }
    except Exception as exc:
        logger.warning("hydrate klines %s: %s", symbol, exc)
    try:
        # D-13: orderbook da limiter'dan geçsin.
        await _velocity_rate_acquire()
        book = await orderbook(symbol, 5)
        bids, asks = book.get("bids") or [], book.get("asks") or []
        if bids and asks:
            bid_price, bid_qty = float(bids[0][0]), float(bids[0][1])
            ask_price, ask_qty = float(asks[0][0]), float(asks[0][1])
            mid = (bid_price + ask_price) / 2
            market.orderflow[symbol] = {**(market.orderflow.get(symbol) or {}),
                                          "bid_price": bid_price, "ask_price": ask_price,
                                          "bid_qty": bid_qty, "ask_qty": ask_qty,
                                          "spread_pct": ((ask_price - bid_price) / bid_price * 100) if bid_price else None,
                                          "source": "binance_tr_public_rest", "updated_at": time.time()}
    except Exception as exc:
        logger.warning("hydrate orderbook %s: %s", symbol, exc)


async def _velocity_journal_quality(symbol: str) -> dict | None:
    """Sembolün velocity journal geçmişi: ölçülen aday, dokunuş, ort. MFE.

    Kapanmış işlem geçmişi olmayan sembollerde bile (örn. yeni listelenen
    pump sembolleri) kalite sinyali verir; ölçüm yoksa None döner.
    """
    try:
        rows = await database.get_velocity_symbol_quality_stats()
    except Exception:
        return None
    row = next((r for r in rows if str(r.get("symbol", "")).upper() == symbol), None)
    if not row:
        return None
    evaluated = int(row.get("evaluated") or 0)
    if evaluated <= 0:
        return None
    touched = int(row.get("touched") or 0)
    avg_mfe = float(row.get("average_mfe_pct") or 0.0)
    return {"evaluated": evaluated, "touched": touched, "avg_mfe_pct": round(avg_mfe, 3)}


async def _journal_touch_rates() -> dict[str, float]:
    """Sembol başına journal dokunuş oranı; yeterli örneklemi olanlar dahil.

    Aday sıralamasında kalite çarpanı için kullanılır; veri yoksa boş döner
    (tüm adaylar çarpan 1.0 ile sıralanır — fail-open).
    """
    try:
        rows = await database.get_velocity_symbol_quality_stats()
    except Exception:
        return {}
    rates: dict[str, float] = {}
    for row in rows:
        evaluated = int(row.get("evaluated") or 0)
        if evaluated < config.VELOCITY_SYMBOL_QUALITY_JOURNAL_MIN_EVALUATED:
            continue
        rates[str(row.get("symbol", "")).upper()] = int(row.get("touched") or 0) / evaluated
    return rates


def _quality_multiplier(touch_rate: float | None) -> float:
    """Journal dokunuş oranına göre aday sıralama çarpanı.

    İyi sembollerde geçen adayların dokunuşu %46.3 (journal analizi);
    binary engel yerine sıralamada önceliklendirme yapılır.
    """
    if touch_rate is None:
        return 1.0
    if touch_rate >= 0.20:
        return 1.3
    if touch_rate >= 0.10:
        return 1.1
    if touch_rate < 0.05:
        return 0.4
    return 0.7


# ---- Hibrit sıralama yardımcıları (2026-09-04; chat upside-scout + monitoring ortak) ----

def upside_rank_score(candidate: dict, touch_rates: dict[str, float] | None = None) -> float:
    """Dakika başına beklenen yükseliş × hız skoru × kalite × mikro-yapı çarpanı.

    Chat upside-scout ile monitoring bildirim sıralamasının ortak anahtarı:
    'en kısa sürede en fazla yükselme' amacını sayısallaştırır. Hedef olarak
    aday satırındaki gerçek target_pct kullanılır (skor-bantlı dinamik hedef
    scan_one içinde uygulanır); satırda yoksa profil baz hedefine döner.
    Mikro-yapı çarpanı (whale aktivitesi) yalnız aday nesnesinde microstructure
    varsa uygulanır — yoksa nötr 1.0.
    """
    horizon = int(candidate.get("horizon_minutes") or 15)
    target = float(candidate.get("target_pct") or 0) or (2.0 if horizon <= 5 else 3.0)
    sym = str(candidate.get("symbol") or "").upper()
    rates = touch_rates or {}
    micro = candidate.get("microstructure") if isinstance(candidate.get("microstructure"), dict) else None
    # ML-target tutarliligi (2026-09-07): zayif skor + iddiali ML yanlis pozitif
    # riski olusturmasin diye target velocity_score ile sinirli.
    vel_score = float(candidate.get("velocity_score") or 0)
    if vel_score < 10 and target > 4.0:
        target = min(target, vel_score * 0.3)
    elif vel_score < 20 and target > 5.0:
        target = min(target, vel_score * 0.25)
    # Düzeltme: upside_rate KELEPLENMİŞ target'tan hesaplanmalı. Eski sürüm
    # kelempeden ÖNCE hesaplayıp kelempsiz değeri kullanıyordu → clamp ölü koddu
    # ve şişirilmiş ML hedefi zayıf adayı sıralamada haksız öne taşıyordu.
    upside_rate = target / max(1, horizon)
    return (upside_rate * vel_score
            * _quality_multiplier(rates.get(sym))
            * micro_structure_multiplier(micro))


def micro_structure_multiplier(micro: dict | None) -> float:
    """Mikro-yapı sinyaline göre sıralama çarpanı (kapı değil, önceliklendirme).

    2026-09-05 journal analizi (n≈52k evaluated): whale aktivitesi OLAN
    sembollerin dokunuş oranı daha yüksek (no_whale %14.8 vs whale'li %15-16;
    GEÇEN adaylarda no_whale %14.8 vs whale'li %19-22). Bu yüzden whale
    varlığı hafif bonus, hiç whale olmayan hafif ceza alır; whale 'verdict'i
    (accumulation/distribution/mixed) ayrım yapmaz. CVD işareti anlamlı
    ayırmadığından nötr. Veri yoksa nötr 1.0 (fail-open).
    """
    if not micro:
        return 1.0
    verdict = str(micro.get("whale_verdict") or "").lower()
    if verdict == "no_whale":
        return float(config.MONITORING_MICRO_NO_WHALE_MULT)
    if verdict in {"accumulation", "distribution", "mixed", "neutral"}:
        return float(config.MONITORING_MICRO_WHALE_MULT)
    return 1.0


def _parse_target_tiers(tiers_value) -> list[tuple[float, float]]:
    """``MONITORING_TARGET_SCORE_TIERS`` ('skor:hedef' çiftleri) → TÜM bantlar.

    R5-C3.4 / R2-12 (2026-09-12): Bant seçimi artık "ilk eşleşmede dur" DEĞİL;
    bu yardımcı bantların HEPSİNİ döndürür (bozuk/eksik parçalar sessizce
    atlanır). ``dynamic_target_pct`` eşiği karşılayan EN YÜKSEK skor bandını
    seçer, böylece sonuç girdi sırasından bağımsız ve deterministiktir.

    Beklenen konvansiyon yüksekten düşüğe yazmaktır ('90:4.0,70:2.5,50:2.0');
    ancak parser artan sıralı bir liste verilse bile monoton bir hedef üretir
    (eski `break`'li sürüm bu durumda yanlış/azalan hedef veriyordu).
    """
    bands: list[tuple[float, float]] = []
    for pair in str(tiers_value or "").split(","):
        pair = pair.strip()
        if not pair or ":" not in pair:
            continue
        try:
            min_score_s, pct_s = pair.split(":", 1)
            bands.append((float(min_score_s), float(pct_s)))
        except ValueError:
            continue
    return bands


def _post_signal_window(rows, created_ms: int, due_ms: int,
                        bar_ms: int = 60_000) -> list:
    """Sinyal ANINDAN SONRA TAMAMEN oluşan kapanmış M1 barları.

    R5-C4.4 (P0, 2026-09-12): Sinyal anını İÇEREN parsiyel (yarım) mum "atak
    öncesi" sayılıp HARİÇ tutulur. Eski filtre ``int(r[0]) + 59_999 > created_ms``
    bu mumu DAHİL ediyordu; mumun tüm dakikaya yayılan ``high``'ı sinyal öncesi
    hareketi MFE'ye katarak sahte "hedefe dokundu" üretiyordu (ör. sinyal öncesi
    105 spike'ı, dürüst sinyal-sonrası tepe 100.5 → yanlış MFE %5 ≫ %0.5).

    Yeni koşul: barın AÇILIŞI sinyal anına eşit/büyük (``int(r[0]) >= created_ms``)
    ve bar due_ms'ten önce kapanmış (``int(r[0]) + bar_ms - 1 <= due_ms``).
    """
    return [r for r in (rows or [])
            if int(r[0]) >= created_ms and int(r[0]) + bar_ms - 1 <= due_ms]


def _mfe_from_window(window, entry: float) -> float | None:
    """Pencere içi en yüksek ``high``'tan MFE (%) — tek tanım (R5-C4.4 kilitli)."""
    if not window or entry is None or float(entry) <= 0:
        return None
    return (max(float(r[2]) for r in window) / float(entry) - 1) * 100


def _exit_pct_from_window(window, entry: float) -> float | None:
    """Penceredeki SON kapanmış mumun ``close``'undan gerçekleşen çıkış (%).

    D-06 (2026-09-14): MFE ulaşılamaz bir TEPE'dir — "hedefe dokundu" demek için
    doğru olsa da "kazandık" demek için yanıltıcıdır. Bu ölçüm "sinyali al, ufuk
    sonunda kapanıştan çık" kuralının getirisidir: gerçekleştirilebilir ve
    ileriye dönük bilgi içermez. Aynı pencere (`_post_signal_window`) kullanılır.
    """
    if not window or entry is None or float(entry) <= 0:
        return None
    return (float(window[-1][4]) / float(entry) - 1) * 100


def round_trip_cost_pct() -> float:
    """Gidiş-dönüş maliyet (iki bacak komisyon + iki bacak slippage), YÜZDE.

    Tek kaynak `config.round_trip_cost()` (kesir) -> yüzde.
    -> (0.0015 + 0.00025) * 2 * 100 = %0.35
    """
    return float(config.round_trip_cost()) * 100


def _first_stop_or_target_bar(window, entry: float, target_pct: float,
                              sl_pct: float) -> tuple[str | None, object | None]:
    """Pencere içinde İLK TP/SL temasını bulur — bar içi sıra BİLİNMEZ.

    D-16 (2026-09-26 denetimi): 1 dakikalık mumda high VE low eşiği aynı anda
    aşabiliyor (ör. hedef +%2, stop -%1.5, mum 100→102→98.5 gerçekleşti).
    Gerçek bar içi sıra 1m verisinden bilinemez. Eski kod `if high ... elif
    low` yazdığı için belirsiz barda DAIMA TP sayıyordu → sistematik İYİMSER
    yanlılık (look-ahead bias): `passing_hit_rate` şişer, `velocity_calibrate`
    bu şişik oranı optimize eder, sembol bazlı hedef öğrenmesi yanlış yönde
    öğrenir.

    Sözleşme (worst-case, iyimserlik yok):
      - Yalnız TP eşiği aşıldı  → "take_profit"
      - Yalnız SL eşiği aşıldı  → "stop_loss"
      - İKİSİ DE aşıldı        → "stop_loss" (belirsizlik lehine EN KÖTÜ
        senaryo kabul edilir; TP ihtimali ölçüme YANSITILMAZ)
      - Hiçbiri                 → (None, None)

    Bu TEK tanımdır; hem `velocity_learning_loop` (öğrenme döngüsü) hem
    `remeasure_velocity_candidate` (yeniden ölçüm) ve `calibration.py` bu
    sözleşmeyi paylaşır. `touched`/`hit_target` yalnızca "stop_loss" DEĞİLse
    True olur → belirsiz barda dokunuş SAYILMAZ.
    """
    if entry is None or float(entry) <= 0:
        return None, None
    for r in (window or []):
        bar_high = float(r[2])
        bar_low = float(r[3])
        high_gain = (bar_high / float(entry) - 1) * 100
        low_dd = (bar_low / float(entry) - 1) * 100
        hit_tp = high_gain >= target_pct
        hit_sl = low_dd <= -abs(sl_pct)
        if hit_tp and hit_sl:
            return "stop_loss", r     # belirsiz → worst-case
        if hit_tp:
            return "take_profit", r
        if hit_sl:
            return "stop_loss", r
    return None, None


def dynamic_target_pct(score: float, base_target_pct: float,
                       learned_pct: float | None = None,
                       learned_count: int = 0,
                       ml_pct: float | None = None,
                       ml_prob: float | None = None,
                       panel_score: bool = True,
                       spread_pct: float | None = None,
                       atr_pct: float | None = None) -> float:
    """Skor ve sembol potansiyeline (ATR) dayalı dinamik hedef.

    Komisyon ve Maliyet Garantisi (Kullanıcı Kuralı 2026-09-21):
    Al-sat komisyonları (iki yönlü ~%0.35) ve alış-satış spread maliyeti (~%0.35)
    hedefin içine DAHİL EDİLİR; böylece hedefe ulaşıldığında kullanıcıya kalan kâr
    net olur (Net Kâr Tabanı = Net Hedef + Komisyon + Spread).

    Sembolün Oynaklık Potansiyeli (ATR):
    Sembolün ATR oranı yüksekse hedef dinamik olarak yukarı esnetilir;
    düşük volatilitede ise net kâr maliyet tabanında korunur.
    """
    target = float(base_target_pct)

    # PANEL ölçeği varsayımı 1/2 — bant seçimi.
    if panel_score:
        matched_threshold: float | None = None
        for min_score, pct in _parse_target_tiers(config.MONITORING_TARGET_SCORE_TIERS):
            if float(score) >= min_score and (matched_threshold is None or min_score > matched_threshold):
                matched_threshold = min_score
                target = max(target, pct)

    # Net Kâr Tabanı: komisyon (%0.35) + spread maliyeti hedefe eklenir
    spr = float(spread_pct) if (spread_pct is not None and float(spread_pct) > 0) else getattr(config, "DEFAULT_ESTIMATED_SPREAD_PCT", 0.65)
    total_cost = round_trip_cost_pct() + spr
    net_target = getattr(config, "SCALPING_NET_TARGET_PCT", 2.0)
    net_profit_floor = net_target + total_cost  # örn: 2.0 + 0.35 + 0.65 = %3.00
    target = max(target, net_profit_floor)

    # Sembol Oynaklık Potansiyeli (ATR): Yüksek volatilitede hedef genişler
    if atr_pct is not None and float(atr_pct) > 0:
        atr_potential = float(atr_pct) * 1.35
        target = max(target, atr_potential)

    # Öğrenilmiş sembol hedefi: yeterli örnek varsa (>=LEARNED_TARGET_MIN_SAMPLES)
    # iki yönlü harmanlanır; gerçek MFE'si banttan düşük sembollerde hedefi dengeler.
    if learned_pct and float(learned_pct) > 0 and learned_count >= config.LEARNED_TARGET_MIN_SAMPLES:
        weight = min(0.6, learned_count / 20.0)  # 3 örnekte 0.15, 12 örnekte 0.6
        target = target * (1 - weight) + float(learned_pct) * weight

    # ML tahmini: güven yeterliyse hedefi ML öngörüsüne çek; yukarı veya aşağı.
    if ml_pct and float(ml_pct) > 0 and ml_prob is not None and float(ml_prob) >= config.ML_TARGET_MIN_PROB:
        ml_weight = 0.5 if float(ml_prob) >= config.ML_TARGET_HIGH_PROB else 0.25
        target = target * (1 - ml_weight) + float(ml_pct) * ml_weight

    # PANEL ölçeği varsayımı 2/2 — zayıf skor kelepçesi:
    # Çok düşük skorlarda aşırı hedefleri sınırlar (en az floor * 0.75).
    if panel_score:
        target = min(target, max(float(score) * 0.3, net_profit_floor * 0.75))
    else:
        target = max(target, net_profit_floor)

    return round(max(config.MONITORING_TARGET_PCT_MIN,
                     min(config.MONITORING_TARGET_PCT_MAX, target)), 3)


def _rank_score(candidate: dict, touch_rates: dict[str, float]) -> float:
    """Ham skor × sembol kalite çarpanı; açılış havuzunun sıralama anahtarı."""
    base = float(candidate.get("velocity_score") or 0)
    rate = touch_rates.get(str(candidate.get("symbol") or "").upper())
    return base * _quality_multiplier(rate)


def _velocity_to_auto_paper_envelope(candidate: dict) -> dict:
    """Velocity adayını auto_paper'ın beklediği bildirim zarfına çevirir.

    auto_paper `score`u PANEL ölçeğinde karşılaştırır; velocity `velocity_score`
    HAM taşır. Bu yüzden `_panel_score` ile ham→panel dönüşümü yapılır (radar
    teslimatının kullandığı aynı eşleme). `notification_key` saat kovasıdır →
    aynı sembol/saat için auto_paper churn koruması tek girişi garanti eder.
    """
    symbol = str(candidate.get("symbol") or "").upper()
    raw = float(candidate.get("velocity_score") or 0)
    panel = _panel_score(raw)
    target_pct = float(candidate.get("target_pct") or 2.0)
    horizon_minutes = int(candidate.get("horizon_minutes") or 5)
    return {
        "symbol": symbol,
        "score": panel,
        "target_pct": target_pct,
        "price": candidate.get("price"),
        "horizon_minutes": horizon_minutes,
        "mode": "velocity",
        "source": "velocity_auto",
        "notification_key": f"velocity-auto-{symbol}-{int(time.time() // 3600)}",
        "title": f"🎯 HIZ AVCISI · {symbol}",
        "message": f"{symbol} hız avcısı otonom girişi · skor {panel:.1f} · hedef %{target_pct:.2f}",
        "url": f"/charts?symbol={symbol}",
        "paper_only": True,
    }


async def _route_velocity_through_auto_paper(candidate: dict) -> dict:
    """BİRLEŞİK RADAR (D3): velocity otonom girişini auto_paper'a yönlendirir.

    Böylece tüm paper pozisyonlar tek defterde (`auto_paper_trades`) tutulur:
    tek sembol-tek pozisyon, `AUTO_PAPER_MAX_OPEN_POSITIONS` (3) kapısı, fail-closed
    emir boyutu ve B1-B4 merdiveniyle kapanır. Bayrak kapalıyken (`RADAR_ROUTE_…`
    default false) eski `analyzer.open_position` yolu AYNEN çalışır.
    """
    from app.routers.auto_paper import try_open_from_notification

    envelope = _velocity_to_auto_paper_envelope(candidate)
    try:
        result = await try_open_from_notification(envelope)
    except Exception as exc:
        logger.warning("velocity→auto_paper yönlendirme hatası: %s", exc)
        return {"symbol": envelope["symbol"], "status": "SKIPPED",
                "reason": f"auto_paper_hata:{type(exc).__name__}"}
    if isinstance(result, dict) and result.get("status") == "opened":
        return {"symbol": envelope["symbol"], "status": "PAPER_OPENED",
                "order_value_try": None, "entry": envelope.get("price"),
                "stop_loss_pct": None, "take_profit_pct": envelope.get("target_pct"),
                "horizon_minutes": envelope.get("horizon_minutes"), "via": "auto_paper",
                "trade_id": result.get("trade_id")}
    reason = (result or {}).get("reason") if isinstance(result, dict) else "kapı"
    return {"symbol": envelope["symbol"], "status": "SKIPPED",
            "reason": f"auto_paper:{reason}"}


async def _open_velocity_position(candidate: dict) -> dict:
    """En iyi hız adayına serbest TL'nin %50'si ile paper pozisyon açar.

    D-13 (2026-09-26): pozisyon limiti TOCTOU koruması. Sınır kontrolü +
    "rezervasyon" `_velocity_open_lock` altında TEK atomik adımda yapılır;
    gövvenin tamamı (guard/bakiye/likidite/DB commit) rezervasyon altında
    çalışır. Eşzamanlı iki görev limiti aynı anda geçemez.
    """
    symbol = str(candidate["symbol"] or "").upper()
    async with _VelocitySlotReservation(symbol) as reservation:
        if not reservation.ok:
            return reservation.result
        return await _open_velocity_position_reserved(candidate, symbol)


async def _open_velocity_position_reserved(candidate: dict, symbol: str) -> dict:
    """Rezervasyon ALINMIŞ halde açılış gövdesi (limit kontrolü burada TEKRAR
    edilmez — `_VelocitySlotReservation` zaten uçuşta sayımı yaptı)."""
    # Minimum skor eşiği: düşük skorlu adaylarda dokunuş oranının üçte biri
    # (journal analizi: <10 → %16.7, ≥10 → ~%50). Eşik altında tur pas geçilir.
    # Düzeltme (2026-09-12): eşik PANEL (0-100) ölçeğinde tanımlıdır ve ham
    # velocity_score ile karşılaştırılmadan ÖNCE `_velocity_raw_score_gate`
    # üzerinden ham ölçeğe çevrilir (varsayılan panel 10 → ham 200); aksi halde
    # `score < 10` kapısı 50-2000 bandındaki ham skorları hiç elemiyordu.
    min_score = _velocity_raw_score_gate()
    score = float(candidate.get("velocity_score") or 0)
    if min_score > 0 and score < min_score:
        return {"symbol": symbol, "status": "SKIPPED",
                "reason": f"skor_esigi_alti:{score:.2f}<{min_score:g}"}
    # M5 momentum+volatilite deseni (7g replay: %66.8 başarı). Filtre açıkken
    # desen karşılanmayan adaylar açılmaz — yalnız journal'da kalır.
    if config.VELOCITY_PATTERN_FILTER_ENABLED:
        if not candidate.get("m5_pattern_ok"):
            return {"symbol": symbol, "status": "SKIPPED",
                    "reason": "m5_pattern_reddet", "m5_pattern": candidate.get("m5_pattern")}
    if symbol in analyzer.positions:
        return {"symbol": symbol, "status": "SKIPPED", "reason": "acik_pozisyon_var"}
    guard = await database.get_llm_symbol_guard(symbol)
    guard_reason = _llm_guard_block_reason(guard)
    if guard_reason:
        return {"symbol": symbol, "status": "SKIPPED", "reason": guard_reason}
    try:
        price, _ = await _fresh_public_price(symbol)
    except Exception:
        price = None
    if not price:
        return {"symbol": symbol, "status": "SKIPPED", "reason": "fiyat_alinamadi"}
    # Açılış öncesi sub-minute mikro yapı akışını başlat: 1s/5s bar, agresif
    # alış/satış akışı ve whale sayısı, pozisyon yönetiminin giriş anını
    # gerçek zamanlı görmesini sağlar. Başarısızlık açılışı engellemez.
    try:
        await microflow.start(symbol)
    except Exception as exc:
        logger.warning("velocity microflow başlatma: %s", exc)
    # Mikro-yapı giriş filtreleri (deterministik, LLM çağrısız): whale dağıtım
    # sinyali ve aykırı agresif satış akışı "sahte kırılım" riskini işaretler.
    # Yalnız gerçek veri varsa uygulanır; veri yoksa kapı açık kalır (fail-open:
    # mikro yapı akışı daha yeni başladığı için ilk turda veri eksik olabilir).
    try:
        micro_snapshot = microflow.get_snapshot(price=price)
        micro_activity = (micro_snapshot.get("trade_flow") or {}).get("whale_activity") or {}
        micro_flow = micro_snapshot.get("trade_flow") or {}
        if config.VELOCITY_WHALE_DISTRIBUTION_FILTER:
            if micro_activity.get("whale_count") and micro_activity.get("verdict") in {"distribution", "mixed"}:
                _velocity_auto_state["filters"]["whale_dagilim_reddet"] += 1
                return {"symbol": symbol, "status": "SKIPPED",
                        "reason": f"whale_dagilim:{micro_activity.get('verdict')}",
                        "whale_activity": {k: micro_activity.get(k) for k in
                                           ("verdict", "accumulation", "distribution", "whale_count")}}
        if config.VELOCITY_FLOW_CONFIRMATION_FILTER:
            cvd = micro_flow.get("cvd_try")
            if cvd is not None and cvd < 0:
                _velocity_auto_state["filters"]["akis_aykiri_reddet"] += 1
                return {"symbol": symbol, "status": "SKIPPED",
                        "reason": f"akis_aykiri:cvd={cvd:.0f}TRY",
                        "cvd_try": cvd}
        if not micro_snapshot.get("data_ready"):
            _velocity_auto_state["filters"]["microflow_yok"] += 1
    except Exception as exc:
        logger.warning("velocity mikro yapı filtresi: %s", exc, exc_info=True)
    # Serbest TL'nin %50'si
    balance = await database.get_wallet_balance("TRY")
    order_value = round(balance * config.VELOCITY_AUTO_BALANCE_PCT / 100.0, 2)
    order_value = min(order_value, balance)
    if order_value < config.MIN_PARTIAL_ORDER_TRY:
        return {"symbol": symbol, "status": "SKIPPED", "reason": f"bakiye_yetersiz:{order_value}TRY"}
    # Likidite ön kontrolü: REST tabanlı (WS tazeliği beklemeyen) kapı.
    # Top-Gainer'dan yeni gelen sembollerin WS orderbook akışı dolmadan
    # geleneksel preflight 'stale' diyordu ve hiç işlem açılmıyordu.
    ok, reason = await _velocity_rest_liquidity_ok(symbol, order_value)
    if not ok:
        return {"symbol": symbol, "status": "ENTRY_INELIGIBLE", "reason": reason}
    # open_position içindeki son recheck market önbelleğini kullanır;
    # Top-Gainer adayının önbelleğini REST'ten doldur ki 0 hacim/derinlik
    # üzerinden reddedilmesin.
    await _hydrate_market_cache_for(symbol)
    # Kullanıcı kontratı: sinyal sonrası fiyat önce geri çekiliyor; açılışta sert
    # stop koymak geri çekilmede kapatıp yükselişi kaçırıyor. No-initial-stop
    # modunda stop'suz açılır; kâr koruması +%0.5'te yine devreye girer.
    # Kapanış modeli: trailing DEĞİL — açılışta tahmin edilen hedef (target_pct:
    # 5dk-%2 / 15dk-%3) TP olarak konur; fiyat oraya ulaşınca take_profit ile
    # kapanır. TP'ye ulaşmazsa +%0.5 kâr kilidi stop'u maliyet üstüne çeker,
    # 30dk max-hold ve -%3 acil stop zararı sınırlar.
    no_initial_stop = bool(config.VELOCITY_NO_INITIAL_STOP)
    stop_loss_pct = None if no_initial_stop else config.VELOCITY_AUTO_SL_PCT / 100.0
    target_pct = float(candidate.get("target_pct") or
                       (VELOCITY_PROFILES.get(int(candidate.get("horizon_minutes") or 5)) or VELOCITY_PROFILES[5])["target_pct"])
    horizon_minutes = int(candidate.get("horizon_minutes") or 5)
    context = {"signal_name": "Otonom Hız Avcısı · en iyi aday",
                "velocity_score": candidate.get("velocity_score"),
                "mode": candidate.get("mode"), "pattern_matches": candidate.get("m5_pattern"),
                "paper_only": True, "source": "velocity_auto",
                "atr_pct": candidate.get("atr_pct"),
                "velocity_relaxed_reentry": True,
                "no_initial_stop": no_initial_stop,
                "horizon_minutes": horizon_minutes,
                "target_pct": target_pct,
                "exit_model": "plan_tp"}
    # Strategy stays CHAT_PREDICTION: the analyzer's position-management ladder
    # (no-initial-stop, profit lock, emergency stop, plan TP, max hold) is keyed
    # to it, so renaming would silently drop velocity exit handling. Velocity
    # trades remain distinguishable via signal_context.source == "velocity_auto".
    result = await analyzer.open_position(symbol, price, "LONG", "CHAT_PREDICTION", order_value,
                                           stop_loss_pct=stop_loss_pct,
                                           take_profit_pct=target_pct / 100.0,
                                           entry_context_extra=context)
    if result and str(result.get("action", "")).upper() == "BUY_SIGNAL":
        await ws_manager.broadcast({"type": "signal", "data": result})
        return {"symbol": symbol, "status": "PAPER_OPENED", "order_value_try": order_value,
                 "entry": price,
                 "stop_loss_pct": (stop_loss_pct * 100) if stop_loss_pct is not None else None,
                 "no_initial_stop": no_initial_stop,
                 "take_profit_pct": target_pct, "horizon_minutes": horizon_minutes,
                 "exit_model": "plan_tp"}
    return {"symbol": symbol, "status": "ENTRY_BLOCKED", "reason": str((result or {}).get("reason") or "kapı")}


async def autonomous_velocity_loop():
    """Her M5 kapanışında hız taraması; en iyi adaya (GEÇTİ veya İZLEME) pozisyon.

    Her turda önce 5dk-%2, sonra 15dk-%3 profili taranır; iki profilin
    adayları birleşik skorla sıralanır ve en iyi tek adaya pozisyon açılır.
    Açılış VELOCITY_AUTO_ENABLED + LLM paper anahtarıyla çift kilitli.
    Pozisyon yönetimi analyzer'ın genel döngüsünde: açılışta tahmin edilen
    hedef (target_pct) TP olarak konur → fiyat oraya ulaşınca take_profit ile
    kapanır; +%0.5 kâr kilidi stop'u maliyet üstüne çeker (trailing yok),
    30dk max-hold + -%3 acil stop zararı sınırlar.

    AKTİF (2026-09-10, kullanıcı kararı): ``main.py::startup_services()`` içinde
    ``_start_background(autonomous_velocity_loop, "velocity-autonomous")`` ile
    başlatılır. Kablolama, tanımlı ama başlatılmamış döngüleri yakalayan
    ``tests/test_loop_wiring.py`` ile korunur.

    Çift kilit: ``VELOCITY_AUTO_ENABLED`` (env) **ve**
    ``llm_paper_trade_enabled`` (DB ayarı) birlikte açık olmalı. Kapı her turda
    yeniden okunur → ayar kapatılınca tarama durur, açılınca restart gerekmez.
    Başlatma sırasında ikisi de açıktı (env=true, DB=1).
    """
    global _VELOCITY_AUTO_LOOP_STARTED
    # Döngü gövdesi çalışmaya başladığı anda "başlatıldı" sayılır; ilk 60 sn'lik
    # uyku boyunca da durum ucu doğru (True) raporlar.
    _VELOCITY_AUTO_LOOP_STARTED = True
    # G-16: heartbeat'i hemen yaz ki ilk 60 sn'lik uykuda da canlı sayılsın.
    _velocity_auto_state["last_heartbeat_at"] = time.time()
    await asyncio.sleep(60)
    # Restart sonrası mevcut M5 kapanışıyla senkron başla: ilk turda hazır
    # kapanışa bağlı kalıp yeni mum gelmeden taramayalım (0 ile başlarsak
    # açılışta anında, mum ortasından bir tarama yapılırdı).
    _last_m5_close_ms = 0
    try:
        m5_tick = await fetch_klines("BTCTRY", "5m", 2)
        if m5_tick:
            _last_m5_close_ms = int(m5_tick[-1][0])
    except Exception:
        pass
    while True:
        try:
            # G-16: tur başına canlılık işareti.
            _velocity_auto_state["last_heartbeat_at"] = time.time()
            enabled = config.VELOCITY_AUTO_ENABLED and \
                (await database.get_llm_setting("llm_paper_trade_enabled", "0")) == "1"
            if enabled:
                # M5 kapanış tetiklemesi: yeni kapanmış M5 mumu gelmeden tarama
                # yapma (replay'deki ile aynı senkron; her kapanışta 1 kez tara).
                try:
                    # D-13: `_velocity_rate_acquire` bloklayıcıdır ve her çağrıda
                    # TAM BİR token tüketir; dönüş daima True'dur (dolayısıyla
                    # "ignored" değil, sözleşmesi gereği kontrol gerektirmez).
                    await _velocity_rate_acquire()
                    m5_rows = await fetch_klines("BTCTRY", "5m", 2)
                    if m5_rows:
                        latest_close_ms = int(m5_rows[-1][0])
                    else:
                        latest_close_ms = _last_m5_close_ms
                except Exception:
                    latest_close_ms = _last_m5_close_ms
                if latest_close_ms == _last_m5_close_ms:
                    # Yeni M5 kapanışı yok; kapanışa kadar bekle.
                    await asyncio.sleep(3)
                    continue
                _last_m5_close_ms = latest_close_ms
                scan5 = await detect_velocity_candidates({}, horizon_minutes=5)
                scan15 = await detect_velocity_candidates({}, horizon_minutes=15)
                _velocity_auto_state["last_scan_at"] = time.time()
                _velocity_auto_state["last_m5_close_ms"] = latest_close_ms
                # İki profilin adayları birleşik; kalite çarpanlı skor ile sıralama.
                # Zaten açık pozisyonu olan semboller atlanır (çoklu açılışı önler).
                pool = [c for c in (list(scan5.get("candidates") or []) + list(scan5.get("watchlist") or [])
                        + list(scan15.get("candidates") or []) + list(scan15.get("watchlist") or []))
                        if str(c.get("symbol") or "").upper() not in analyzer.positions]
                # Sıralama: ham skor × sembol kalite çarpanı (journal dokunuş oranı).
                touch_rates = await _journal_touch_rates()
                pool.sort(key=lambda c: -_rank_score(c, touch_rates))
                if pool:
                    best = pool[0]
                    # BİRLEŞİK RADAR (D3): bayrak açıkken otonom giriş auto_paper'a
                    # yönlendirilir (tek defter, max-open kapısı, B1-B4 kapanışı).
                    # Kapalıyken eski analyzer yolu AYNEN çalışır.
                    if getattr(config, "RADAR_ROUTE_VELOCITY_AUTO_THROUGH_AUTO_PAPER", False):
                        outcome = await _route_velocity_through_auto_paper(best)
                    else:
                        outcome = await _open_velocity_position(best)
                    _velocity_auto_state["last_open"] = outcome
                    if outcome.get("status") == "PAPER_OPENED":
                        _velocity_auto_state["total_opened"] += 1
                        _velocity_auto_state["opened"].append({**outcome, "at": time.time(),
                                                                "score": best.get("velocity_score"),
                                                                "horizon": best.get("horizon_minutes")})
                        del _velocity_auto_state["opened"][:-20]
            _velocity_auto_state["last_error"] = None
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _velocity_auto_state["last_error"] = str(exc)
            logger.exception("autonomous velocity loop: %s", exc)
        # Kapanış senkronlu: bir sonraki kontrolü 5sn'de bir yap (interval'e bağlı değil)
        await asyncio.sleep(5)
