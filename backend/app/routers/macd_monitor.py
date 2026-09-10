"""MACD MONITOR — aktif sembollerin çoklu zaman dilimi MACD histogram yönü.

"MACD MONITOR" sayfası + monitoring sayfasının "YÜKSELİŞ EĞİLİMİ ADAYLARI"
bölümü için arka plan döngüsü + snapshot API.

Tasarım:
  - Evren: activity taramasında ACTIVE olan semboller + açık pozisyonlar
    (bot + auto paper). Activity haritası henüz boşsa config.SYMBOLS yedeği.
  - Her ~1 sn'de fiyatı değişen semboller için M1/M3/M5/M15/M30/H1 MACD
    histogramı yeniden hesaplanır. Cache yalnızca KAPANMIŞ mum tuttuğundan,
    oluşan mumu temsil etmek için serinin sonuna canlı ticker fiyatı eklenir
    (bar kapanınca kapanış ≈ son canlı fiyat olduğu için seri süreklidir).
  - Yeşil/kırmızı kuralı: histogram > 0 → yeşil, < 0 → kırmızı.
  - Yalnızca gerçek değişiklik varsa ws_manager üzerinden
    {"type": "macd_monitor", "data": {...}} yayınlanır (en fazla ~1/sn);
    UI kendini onarsın diye her N. pass'ta koşulsuz tam yayın yapılır.
  - M3/M30 varsayılan WS abonelik setinde (PRIORITY_TIMEFRAMES) YOKTUR; bu
    seriler market.refresh_series() ile REST'ten periyodik tazelenir
    (3m ~75 sn, 30m ~31 dk — kendi aralıklarına göre).
"""
import asyncio
import json
import logging
import time

import numpy as np

from fastapi import APIRouter, Request

from app.config import config
from app import database
from app.api_common import _background_tasks
from app.state import market, analyzer
from app.technical_analysis import _macd
from app.ws_runtime import ws_manager

logger = logging.getLogger("scalper.macd_monitor")
router = APIRouter()

TF_LIST = ("1m", "3m", "5m", "15m", "30m", "1h")
# MACD için yeterli mum: slow(26) + signal(9)
_MACD_MIN_CANDLES = 26 + 9
LOOP_SEC = 1.0
_FIRST_WAIT_SEC = 2.0
# REST ile tazelenen (WS aboneliği olmayan) zaman dilimleri ve aralıkları
_REST_REFRESH_TFS = {"3m": 75.0, "30m": 31 * 60.0}
# Her pass'ta en fazla bu kadar REST tazeleme (Binance TR limit nazikliği)
_MAX_REST_PER_PASS = 8
# Kaç pass'ta bir koşulsuz tam yayın yapılır (UI kendini onarır)
_FULL_BROADCAST_EVERY = 5

# Trend gücü (lineer regresyon): 20 barlık pencere; eğim, bar-aralığına
# (h-l ort.) bölünerek HIZ, R² ile TUTARLILIK ölçülür. ADR (volatilite) ve
# ADX'ten (gecikmeli) farklı olarak M1..H1'de hem hassas hem karşılaştırılabilir.
_TREND_WINDOW = 20
_TREND_MIN_POINTS = 8

# Zaman dilimi ağırlıkları (kullanıcı isteği 2026-09-09): kullanıcı M5'te
# sıçrama/düzenli yükselişi izlemek istiyor → M5/M15 en yüksek; H1 önemli ama
# biraz daha kısa vade ağırlıklı → orta; M30 ortada; M1/M3 en düşük.
_TF_WEIGHTS = {"1m": 0.4, "3m": 0.6, "5m": 1.5, "15m": 1.4, "30m": 1.0, "1h": 1.1}

# SIRÇRAMA ADAYI skoru: 0-100; eşik ayarlardan (macd_monitor_settings)
# gelir; varsayılan config.MACD_JUMP_MIN_SCORE_DEFAULT (60).
# Aynı sembol için alarm tekrar aralığı (cooldown)
_JUMP_ALERT_COOLDOWN_SEC = 30 * 60
_SETTINGS_TTL_SEC = 5.0
# REST snapshot'ı bu yaşın altındaysa döngünün ürettiği önbellek döndürülür
# (her istekte tam evren hesabı yapılmasını engeller — A2).
_REST_CACHE_MAX_AGE_SEC = 5.0
# Eşik geçişinde alarm tekrarını engelleyen histerezis payı (B6): temizlenme
# eşiği = jump_min - bu değer. Sinyal davranışını etkilediği için kanıtla
# (replay) seçildi — bkz. outputs/macd_monitor_replay_kanit.md.
_JUMP_HYSTERESIS = 5
# C3: bekleyen alarmların 5m/15m/30m ileri getirilerini doldurma aralığı (sn)
_EVIDENCE_FILL_SEC = 120.0

_settings_cache: dict = {"value": None, "at": 0.0}

_loop_task = None
# C3 kanıt katmanı: bekleyen alarm sonuçlarını dolduran yardımcı döngü
_evidence_task = None
# _compute_pass'i tek seferde tek çağrıya indirir (döngü + REST yarışı — A2)
_pass_lock = asyncio.Lock()
# REST önbellek tazeliği için son başarılı pass zamanı
_last_pass_at = 0.0

# Son hesaplanan görünüm. symbols: {SYM: {"last": fiyat|None,
# "tfs": {tf: {"green": bool, "hist": float}|None}}}
_SNAPSHOT: dict = {"universe": [], "symbols": {}, "generated_at": 0.0}
# Sembol başına son işlenen canlı fiyat (değişmeyeni yeniden hesaplama)
_last_price_seen: dict[str, float] = {}
# (symbol, tf) → son görülen KAPANMIŞ bar timestamp'i. Yeni bar kapandığında
# fiyat değişmese de ilgili hücre yeniden hesaplanır (A9).
_last_bar_ts: dict[tuple[str, str], float] = {}
# (symbol, tf) → son REST tazeleme zamanı
_last_rest_refresh: dict[tuple[str, str], float] = {}
# C4/B8: sembol → (trend, ekstralar) önbelleği. Fiyat ve kapanmış barlar
# değişmediği sürece trend/sinyal hesabı (6 TF × OLS + ATR + kırılım + hacim)
# yeniden yapılmaz. MIN-MAX normalizasyonu yine her turda uygulanır, çünkü
# skor evrenin o anki min/max'ına bağlıdır.
_trend_cache: dict[str, tuple[dict, dict]] = {}
# C4/B9: son tam yayından bu yana satırı değişen semboller. Loop, tam snapshot
# yerine yalnızca bu sembolleri (delta) yayınlar; böylece 312 sembollük ~60 KB
# gövde saniyede bir değil, yalnızca değişenler kadar gönderilir. Her 5. pass'ta
# koşulsuz TAM yayın yapılır (istemci kendini onarır).
_pending_changed: set[str] = set()
# symbol → son sıçrama alarmı zamanı (cooldown için)
_jump_alerted_at: dict[str, float] = {}
# symbol → son ERKEN SİNYAL (yaklaşıyor) alarmı zamanı (ayrı cooldown)
_early_alerted_at: dict[str, float] = {}
_dirty = False


def _status_value(info) -> str:
    """config.SYMBOL_ACTIVITY_STATUS girdisinden status metnini çıkar."""
    if isinstance(info, dict):
        return str(info.get("status") or "")
    return str(info or "")


def _to_bool(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "açık", "on")


def _aligned_ohlc(symbol: str, tf: str, min_len: int):
    """OHLC listeleri hizalı ve yeterliyse history döner, aksi halde None.

    Bazı akışlarda highs/lows/closes uzunlukları farklı olabiliyor; index
    tabanlı TR/ATR hesapları o durumda IndexError fırlatıp turun kalanını
    iptal ederdi (A15). Tek sembol hatası artık tüm pass'i düşürmüyor.
    """
    history = market.get_ut_kline(symbol, tf)
    closes = history.get("closes") or []
    highs = history.get("highs") or []
    lows = history.get("lows") or []
    if len(closes) < min_len or len(highs) != len(closes) or len(lows) != len(closes):
        return None
    return history


def _bar_marker(history) -> float:
    """Serideki son KAPANMIŞ barın zaman damgası (yeni bar tespiti — A9)."""
    try:
        marker = float(history.get("last_closed_at_ms") or 0)
    except Exception:
        marker = 0.0
    if marker > 0:
        return marker
    stamps = history.get("timestamps") or []
    try:
        return float(stamps[-1]) if stamps else 0.0
    except Exception:
        return 0.0


def _macd_settings_defaults() -> dict:
    return {
        "jump_min_score": int(config.MACD_JUMP_MIN_SCORE_DEFAULT),
        "alerts_enabled": bool(config.MACD_JUMP_ALERTS_ENABLED),
        "push_enabled": bool(config.MACD_JUMP_PUSH_ENABLED),
        "early_alerts_enabled": bool(config.MACD_EARLY_ALERTS_ENABLED),
    }


async def get_macd_settings(force: bool = False) -> dict:
    """MACD MONITOR ayarları (DB; 5 sn TTL'li önbellek)."""
    global _settings_cache
    now = time.time()
    if not force and _settings_cache["value"] and now - _settings_cache["at"] < _SETTINGS_TTL_SEC:
        return dict(_settings_cache["value"])
    defaults = _macd_settings_defaults()
    try:
        raw = await database.get_llm_setting("macd_monitor_settings", "{}")
        stored = json.loads(raw or "{}") if raw else {}
    except Exception:
        stored = {}
    merged = {
        "jump_min_score": int(max(0, min(100, int(stored.get("jump_min_score", defaults["jump_min_score"]))))),
        "alerts_enabled": _to_bool(stored.get("alerts_enabled"), defaults["alerts_enabled"]),
        "push_enabled": _to_bool(stored.get("push_enabled"), defaults["push_enabled"]),
        "early_alerts_enabled": _to_bool(stored.get("early_alerts_enabled"), defaults["early_alerts_enabled"]),
    }
    _settings_cache.update(value=merged, at=now)
    return dict(merged)


async def _active_symbols() -> list[str]:
    """Aktif evren: ACTIVE durumdakiler + açık pozisyonlar (bot + auto paper).

    Activity haritası boşsa (ilk tarama öncesi) tüm takip listesi döner.
    """
    statuses = getattr(config, "SYMBOL_ACTIVITY_STATUS", None) or {}
    active = {str(s).upper() for s, info in statuses.items() if _status_value(info).upper() == "ACTIVE"}
    open_syms = {str(s).upper() for s in (analyzer.positions or {})}
    try:
        auto_open = await database.list_auto_paper_trades(status="open")
        open_syms |= {str(t.get("symbol") or "").upper() for t in (auto_open or [])}
    except Exception as exc:
        logger.debug("macd_monitor açık auto-paper pozisyonları okunamadı: %s", exc)
    symbols = sorted(active | open_syms)
    if not symbols:
        tracked = [str(s).upper() for s in (getattr(config, "SYMBOLS", None) or [])]
        symbols = sorted(set(tracked))
    return symbols


def _compute_cell(symbol: str, tf: str):
    """Tek (sembol, zaman dilimi) için histogram yönü.

    Kapanmış mum serisine taze canlı fiyat eklenerek oluşan mum da işin içine
    girer; yetersiz mum (< MACD_MIN_CANDLES) veya veri yoksa None döner.
    """
    history = market.get_ut_kline(symbol, tf)
    closes = history.get("closes") or []
    if not closes:
        return None
    now = time.time()
    ticker = market.get_ticker(symbol)
    live_price = float((ticker or {}).get("last_price") or 0)
    tick_ts = float((ticker or {}).get("timestamp") or 0)
    series = list(closes)
    # Kapanmamış son mumu canlı fiyatla temsil et (tazelik kapısı MAX_TICKER_AGE)
    if live_price > 0 and tick_ts and now * 1000 - tick_ts <= config.MAX_TICKER_AGE_SEC * 1000:
        series.append(live_price)
    if len(series) < _MACD_MIN_CANDLES:
        return None
    macd = _macd(series)
    if macd is None:
        return None
    hist = float(macd["histogram"])
    return {"green": bool(hist > 0), "hist": round(hist, 12)}


def _ols_slope_r2(values: list[float]):
    """Son N kapanış üzerinde lineer regresyon: eğim ve R² (0-1)."""
    n = len(values)
    if n < _TREND_MIN_POINTS:
        return None, None
    xs = np.arange(n, dtype=float)
    ys = np.asarray(values, dtype=float)
    xm, ym = xs.mean(), ys.mean()
    sxx = float(np.sum((xs - xm) ** 2))
    sxy = float(np.sum((xs - xm) * (ys - ym)))
    syy = float(np.sum((ys - ym) ** 2))
    if sxx <= 0:
        return None, None
    slope = sxy / sxx
    if syy <= 0:
        r2 = 0.0 if abs(slope) <= 0 else 1.0
    else:
        corr = sxy / (np.sqrt(sxx * syy) + 1e-12)
        r2 = max(0.0, min(1.0, float(corr ** 2)))
    return float(slope), float(r2)


def _bar_range_mean(highs, lows) -> float | None:
    """Son pencere boyunca ortalama bar aralığı (h-l) — eğimi ölçekler."""
    highs = list(highs or [])
    lows = list(lows or [])
    n = min(_TREND_WINDOW, len(highs), len(lows))
    if n < 2:
        return None
    ranges = [highs[-i] - lows[-i] for i in range(1, n + 1) if highs[-i] > lows[-i]]
    if not ranges:
        return None
    return float(sum(ranges) / len(ranges))


def _trend_feature(symbol: str, tf: str):
    """Tek (sembol, zaman dilimi) için trend gücü bileşenleri.

    Kapanmış serinin son 20 barına canlı fiyat eklenir (MACD hücresiyle aynı
    canlılık politikası). Dönüş: {"r2": 0-1 tutarlılık, "speed": |eğim|/bar
    aralığı (hız), "slope": işaretli eğim} veya veri yetersizse None.
    """
    history = market.get_ut_kline(symbol, tf)
    closes = history.get("closes") or []
    if not closes:
        return None
    now = time.time()
    ticker = market.get_ticker(symbol)
    live_price = float((ticker or {}).get("last_price") or 0)
    tick_ts = float((ticker or {}).get("timestamp") or 0)
    series = list(closes[-(_TREND_WINDOW - 1):])
    if live_price > 0 and tick_ts and now * 1000 - tick_ts <= config.MAX_TICKER_AGE_SEC * 1000:
        series.append(live_price)
    if len(series) < _TREND_MIN_POINTS:
        return None
    slope, r2 = _ols_slope_r2(series)
    if slope is None or r2 is None:
        return None
    span = _bar_range_mean(history.get("highs") or [], history.get("lows") or [])
    speed = abs(slope) / span if span else None
    return {"r2": r2, "speed": speed, "slope": slope}


def _tf_breakout(symbol: str, tf: str):
    """Donchian kırılımı: canlı fiyat, son 20 kapanmış barın en yükseğini kırdı mı.

    M5/M15 sıçrama adayı için en erken yapısal sinyal. Veri yetersizse None.
    """
    history = _aligned_ohlc(symbol, tf, 21)
    if history is None:
        return None
    highs = history.get("highs") or []
    closes = history.get("closes") or []
    now = time.time()
    ticker = market.get_ticker(symbol)
    price = float((ticker or {}).get("last_price") or 0)
    tick_ts = float((ticker or {}).get("timestamp") or 0)
    if not (price > 0 and tick_ts and now * 1000 - tick_ts <= config.MAX_TICKER_AGE_SEC * 1000):
        price = float(closes[-1] or 0)
    if price <= 0:
        return None
    prior_high = max(highs[-21:-1])
    return bool(price > prior_high)


def _tf_vol_state(symbol: str, tf: str):
    """Volatilite durumu: squeeze (sıkışma) veya expand (genişleme).

    Kapanmış bar TR'leri üzerinden: son bar TR'si 14-ATR'nin ≥1.5 katıysa
    'expand' (sıçrama başlıyor), son 3 bar ortalaması ATR'nin ≤0.7 katıysa
    'squeeze' (yay hazırlığı). Veri yetersizse None.
    """
    history = _aligned_ohlc(symbol, tf, 22)
    if history is None:
        return None
    highs = history.get("highs") or []
    lows = history.get("lows") or []
    closes = history.get("closes") or []
    trs = []
    for index in range(len(closes) - 21, len(closes)):
        high, low = highs[index], lows[index]
        prev_close = closes[index - 1]
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    atr = float(sum(trs[-14:]) / 14.0)
    if atr <= 0:
        return None
    tr_last = trs[-1]
    recent3 = float(sum(trs[-3:]) / 3.0)
    if tr_last >= atr * 1.5:
        return "expand"
    if recent3 <= atr * 0.7:
        return "squeeze"
    return None


def _tf_volume_surge(symbol: str, tf: str) -> bool | None:
    """Son kapanmış mum hacmi, önceki 20 bar ortalamasının 1.5 katını aştı mı."""
    history = market.get_ut_kline(symbol, tf)
    volumes = history.get("volumes") or []
    closes = history.get("closes") or []
    if len(volumes) < 22 or len(volumes) != len(closes):
        return None
    current = float(volumes[-1] or 0)
    baseline = float(sum(volumes[-21:-1]) / 20.0)
    if baseline <= 0:
        return None
    return bool(current > baseline * 1.5)


def _live_close_series(symbol: str, tf: str, min_len: int) -> list[float] | None:
    """Kapanmış seri + taze canlı fiyat (MACD/öncü hesaplarının ortak girdisi)."""
    history = market.get_ut_kline(symbol, tf)
    closes = history.get("closes") or []
    if not closes:
        return None
    now = time.time()
    ticker = market.get_ticker(symbol)
    live_price = float((ticker or {}).get("last_price") or 0)
    tick_ts = float((ticker or {}).get("timestamp") or 0)
    series = list(closes[-(min_len - 1):])
    if live_price > 0 and tick_ts and now * 1000 - tick_ts <= config.MAX_TICKER_AGE_SEC * 1000:
        series.append(live_price)
    if len(series) < min_len:
        return None
    return series


def _atr_14_closed(symbol: str, tf: str) -> float | None:
    """Kapanmış bar TR'lerinin son 14'lük ortalaması (öncü mesafeyi ölçekler)."""
    history = _aligned_ohlc(symbol, tf, 15)
    if history is None:
        return None
    highs = history.get("highs") or []
    lows = history.get("lows") or []
    closes = history.get("closes") or []
    trs = []
    for index in range(len(closes) - 14, len(closes)):
        high, low = highs[index], lows[index]
        prev_close = closes[index - 1]
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    return float(sum(trs) / len(trs)) if trs else None


def _m5_approach_gap_atr(symbol: str) -> float | None:
    """M5: canlı fiyatın 20-bar zirvesine ATR cinsinden uzaklığı.

    Pozitif = zirvenin altında (ne kadar yakın), 0 = zirvede. Zirve kırılmışsa
    (fiyat üstündeyse) negatif döner. Veri yetersizse None.
    """
    history = _aligned_ohlc(symbol, "5m", 21)
    if history is None:
        return None
    highs = history.get("highs") or []
    closes = history.get("closes") or []
    now = time.time()
    ticker = market.get_ticker(symbol)
    price = float((ticker or {}).get("last_price") or 0)
    tick_ts = float((ticker or {}).get("timestamp") or 0)
    if not (price > 0 and tick_ts and now * 1000 - tick_ts <= config.MAX_TICKER_AGE_SEC * 1000):
        price = float(closes[-1] or 0)
    if price <= 0:
        return None
    atr = _atr_14_closed(symbol, "5m")
    if not atr or atr <= 0:
        return None
    high20 = max(highs[-21:-1])
    return (high20 - price) / atr


def _macd_hist_turn_up(symbol: str, tf: str) -> bool:
    """MACD histogram 'dip dönüşü': hist hâlâ <0 ama son iki değerde yükseliyor.

    Yeşil ok çıkmadan ÖNCE yukarı ivmelenmenin en erken işareti.
    """
    series = _live_close_series(symbol, tf, _MACD_MIN_CANDLES)
    if not series:
        return False
    current = _macd(series)
    previous = _macd(series[:-1]) if len(series) > 1 else None
    if not current or not previous:
        return False
    hist_now = float(current["histogram"])
    hist_prev = float(previous["histogram"])
    return bool(hist_prev < hist_now < 0.0)


def _symbol_cvd(symbol: str) -> dict:
    """Son ~60 sn agresör akışı (CVD): alıcı/satıcı dengesi + balina neti."""
    flow = market.trade_flow.get(symbol) or {}
    updated = float(flow.get("updated_at") or 0)
    if not updated or time.time() - updated > 180:
        return {"fresh": False, "buy_ratio": None, "whale_net": None, "buy_dominant": False}
    buy = float(flow.get("buy_qty") or 0)
    sell = float(flow.get("sell_qty") or 0)
    total = buy + sell
    ratio = (buy / total) if total > 0 else None
    whale_net = int(flow.get("whale_buys") or 0) - int(flow.get("whale_sells") or 0)
    return {
        "fresh": True,
        "buy_ratio": round(ratio, 3) if ratio is not None else None,
        "whale_net": int(whale_net),
        "buy_dominant": bool(ratio is not None and total > 0 and ratio >= 0.58),
    }


def _jump_score(strength10, green: int, sigs: dict, cvd: dict) -> int | None:
    """SIRÇRAMA ADAYI skoru (0-100).

    Ağırlıklar (M5/M15 odaklı): trend gücü 30, MACD yeşil uyumu 20,
    M5 paketi (kırılım 14 + genişleme 7 + hacim 6) 27, M15 paketi
    (kırılım 11 + genişleme 5 + hacim 4) 20, alıcı-agresör teyidi 3.
    """
    if strength10 is None:
        return None
    score = 0.0
    score += max(0.0, min(30.0, strength10 * 3.0))
    score += round((min(green, len(TF_LIST)) / len(TF_LIST)) * 20.0)
    m5 = sigs.get("5m") or {}
    m15 = sigs.get("15m") or {}
    if m5.get("break"):
        score += 14
    if m5.get("state") == "expand":
        score += 7
    if m5.get("vol"):
        score += 6
    if m15.get("break"):
        score += 11
    if m15.get("state") == "expand":
        score += 5
    if m15.get("vol"):
        score += 4
    if cvd.get("buy_dominant"):
        score += 3
    return int(min(100.0, score))


def _update_jump_arm(row: dict, jump: int | None, jump_min: int, prev_jump: int | None) -> bool:
    """Histerezisli eşik bayrağını güncelle; alarm basılmalıysa True döner (B6).

    - Eşik geçişi (`jump >= jump_min`) bayrağı kurar ve alarm ister; ancak
      boot'ta (`prev_jump is None`) bayrak kurulur, alarm BASILMAZ — aksi halde
      sunucu her açılışta hazır adaylar için toplu alarm üretirdi.
    - Bayrak, skor temizleme eşiğinin (`jump_min - _JUMP_HYSTERESIS`) altına
      inene kadar kurulu kalır → eşik çevresinde titreyen skor tekrar tekrar
      alarm basmaz (histerezis).
    """
    if jump is None:
        return False
    armed = bool(row.get("jump_armed", False))
    clear = max(0, jump_min - _JUMP_HYSTERESIS)
    if not armed and jump >= jump_min:
        row["jump_armed"] = True
        return prev_jump is not None
    if armed and jump <= clear:
        row["jump_armed"] = False
    return False


async def _record_alert_evidence(symbol: str, kind: str, score: int | None = None,
                                 jump_min: int | None = None,
                                 extra_signals: dict | None = None) -> None:
    """Alarmı kanıt katmanına yaz (C3) — hata alarm akışını ASLA bozmaz.

    Fiyat/sinyal imzası `_SNAPSHOT`'tan okunur; çağrı imzası bilinçli olarak
    sabit tutuldu ki alarm fonksiyonlarının test çiftleri (fake) etkilenmesin.
    """
    row = (_SNAPSHOT.get("symbols") or {}).get(symbol) or {}
    signals = {
        "strength": row.get("strength"),
        "tier": row.get("tier"),
        "r2": row.get("r2"),
        "speed": row.get("speed"),
        "sigs": row.get("sigs"),
        "cvd": row.get("cvd"),
        "jump": row.get("jump"),
    }
    if extra_signals:
        signals.update(extra_signals)
    try:
        await database.record_macd_monitor_alert(
            created_at=time.time(), symbol=symbol, kind=kind, score=score,
            jump_min=jump_min, price=row.get("last"), signals=signals)
    except Exception as exc:  # pragma: no cover - kanıt katmanı kritik değil
        logger.debug("macd_monitor kanıt kaydı (%s/%s): %s", kind, symbol, exc)


async def _maybe_fire_jump_alert(symbol: str, score: int, jump_min: int, settings: dict):
    """Sıçrama eşiği geçilince WS olayı + web push (ayarlar + cooldown).

    alarms_enabled=false → hiçbir alarm üretilmez; push_enabled=false →
    yalnızca WS olayı (sayfa içi) yayınlanır, web push gönderilmez.
    """
    if not bool(settings.get("alerts_enabled", True)):
        return
    now = time.time()
    last = _jump_alerted_at.get(symbol, 0.0)
    if now - last < _JUMP_ALERT_COOLDOWN_SEC:
        return
    _jump_alerted_at[symbol] = now
    # C3 kanıt katmanı: alarmı, o anki sinyal imzası ve fiyatla birlikte kalıcı
    # kaydet. Böylece `jump_min_score` / ağırlıklar sezgiyle değil, gerçekleşen
    # 5m/15m/30m sonuçlarıyla ayarlanabilir. Kayıt kritik yol değildir.
    await _record_alert_evidence(symbol, "jump", score=int(score), jump_min=int(jump_min))
    try:
        await ws_manager.broadcast({
            "type": "macd_monitor_alert",
            "data": {"symbol": symbol, "score": int(score), "jump_min": int(jump_min),
                     "generated_at": now},
        })
    except Exception as exc:
        logger.debug("macd_monitor alarm WS: %s", exc)
    if not bool(settings.get("push_enabled", True)):
        return
    try:
        from app.alerting import deliver_web_push
        await deliver_web_push(
            f"🚀 {symbol} SIRÇRAMA ADAYI — skor {int(score)}/100 (M5/M15 kırılım/volatilite teyidi)",
            title=f"🚀 {symbol} sıçrama adayı",
            url=f"/charts?symbol={symbol}",
            tag=f"macd-jump-{symbol}",
            extra={"symbol": symbol, "score": int(score),
                   "reason": "jump_threshold", "source": "macd_monitor"},
        )
    except Exception as exc:
        logger.debug("macd_monitor push alarm: %s", exc)


async def _maybe_fire_early_alert(symbol: str, pre: dict, settings: dict):
    """YAKLAŞIYOR aşaması: kırılımdan ÖNCE erken öncü alarm (WS + web push).

    Tetikleyen öncüler pre içinde: approach (M5 zirveye yakın + aktivite),
    m1 (M1 kırılımı + M5 yeşil), dip (MACD hist dip dönüşü).
    """
    if not bool(settings.get("alerts_enabled", True)) or not bool(settings.get("early_alerts_enabled", True)):
        return
    now = time.time()
    last = _early_alerted_at.get(symbol, 0.0)
    if now - last < _JUMP_ALERT_COOLDOWN_SEC:
        return
    _early_alerted_at[symbol] = now
    signals = []
    if pre.get("approach"):
        signals.append("approach")
    if pre.get("m1"):
        signals.append("m1_breakout")
    if pre.get("dip"):
        signals.append("macd_dip_turn")
    if not signals:
        return
    # C3: erken sinyali de aynı kanıt katmanına yaz (kind="early").
    await _record_alert_evidence(symbol, "early", score=None, jump_min=None,
                                 extra_signals={"early_signals": signals})
    try:
        await ws_manager.broadcast({
            "type": "macd_early_alert",
            "data": {"symbol": symbol, "signals": signals, "generated_at": now},
        })
    except Exception as exc:
        logger.debug("macd_monitor erken alarm WS: %s", exc)
    if not bool(settings.get("push_enabled", True)):
        return
    try:
        from app.alerting import deliver_web_push
        await deliver_web_push(
            f"🌱 {symbol} YAKLAŞIYOR — kırılım öncesi erken sinyal ({'/'.join(signals)})",
            title=f"🌱 {symbol} erken sıçrama sinyali",
            url=f"/charts?symbol={symbol}",
            tag=f"macd-early-{symbol}",
            extra={"symbol": symbol, "signals": signals,
                   "reason": "early_approach", "source": "macd_monitor"},
        )
    except Exception as exc:
        logger.debug("macd_monitor erken push: %s", exc)


def _strength_meta(raw: float | None, lo: float | None, hi: float | None):
    """Evren içi min-max ile 0-10 güç skoru + GÜÇLÜ/NORMAL/ZAYIF dilimi."""
    if raw is None or lo is None or hi is None:
        return None, None
    if hi > lo:
        score = (raw - lo) / (hi - lo) * 10.0
    else:
        score = 0.0 if raw <= 0 else 5.0
    score = round(max(0.0, min(10.0, score)), 1)
    if score >= 7.0:
        tier = "strong"
    elif score < 4.0:
        tier = "weak"
    else:
        tier = "normal"
    return score, tier


def _symbol_trend_and_signals(sym: str, snapshot_symbols: dict) -> tuple[dict, dict]:
    """Tek sembolün trend gücü bileşenleri + sıçrama/erken sinyalleri.

    `_compute_pass` içinden çağrılır; her sembol kendi try/except'inde koştuğu
    için tek sembol hatası (ör. hizasız OHLC) turun kalanını düşürmez (A15).
    """
    raw_wsum = 0.0
    weight_sum = 0.0
    r2_wsum = 0.0
    speed_wsum = 0.0
    speed_weight_sum = 0.0
    # Yön: TANIMLAYICI alandır, skora GİRMEZ. Replay kanıtı (312 sembol,
    # 571.980 gözlem) yönlü momentumun bu evrende ters-yönlü (contrarian)
    # olduğunu gösterdi (IC ≈ −0.05, t ≈ −29 @30m); bu yüzden yön skoru
    # beslemez, yalnızca gözlem/kanıt katmanı için taşınır.
    dir_wsum = 0.0
    dir_weight_sum = 0.0
    for tf in TF_LIST:
        feat = _trend_feature(sym, tf)
        if feat is None or feat["r2"] is None:
            continue
        weight = _TF_WEIGHTS.get(tf, 1.0)
        speed = feat.get("speed")
        raw_wsum += weight * (feat["r2"] * (speed if speed is not None else 0.0))
        r2_wsum += weight * feat["r2"]
        weight_sum += weight
        if speed is not None:
            speed_wsum += weight * speed
            speed_weight_sum += weight
            slope = feat.get("slope") or 0.0
            signed = speed if slope >= 0 else -speed
            dir_wsum += weight * signed
            dir_weight_sum += weight
    if weight_sum <= 0:
        raise ValueError("trend verisi yok")
    trend = {
        "raw": raw_wsum / weight_sum,
        "r2": r2_wsum / weight_sum,
        "speed": (speed_wsum / speed_weight_sum) if speed_weight_sum else None,
        "dir": (dir_wsum / dir_weight_sum) if dir_weight_sum else None,
    }
    # Sıçrama sinyalleri (M5/M15 odaklı) + agresör akışı + yeşil sayısı
    sigs = {
        "5m": {"break": _tf_breakout(sym, "5m"), "state": _tf_vol_state(sym, "5m"),
               "vol": _tf_volume_surge(sym, "5m")},
        "15m": {"break": _tf_breakout(sym, "15m"), "state": _tf_vol_state(sym, "15m"),
                "vol": _tf_volume_surge(sym, "15m")},
    }
    row_tfs = (snapshot_symbols.get(sym) or {}).get("tfs") or {}
    green = sum(1 for tf in TF_LIST if (row_tfs.get(tf) or {}).get("green"))
    # Erken sinyal öncüleri (YAKLAŞIYOR → KIRILIM): M5 zirveye yaklaşma +
    # aktivite teyidi, M1 öncü kırılım (M5 yeşilken), MACD dip dönüşü.
    m5_sig = sigs["5m"]
    green5 = bool((row_tfs.get("5m") or {}).get("green"))
    approach = False
    gap = _m5_approach_gap_atr(sym)
    if gap is not None and gap >= 0 and not m5_sig.get("break"):
        approach = bool(gap <= 0.5 and (m5_sig.get("vol") or m5_sig.get("state") == "expand"))
    m1_pre = bool(_tf_breakout(sym, "1m")) and green5
    dip = _macd_hist_turn_up(sym, "5m")
    pre = {"approach": approach, "m1": m1_pre, "dip": dip}
    extra = {"sigs": sigs, "cvd": _symbol_cvd(sym), "green": green,
             "pre": pre, "pre_any": bool(approach or m1_pre or dip)}
    return trend, extra


async def _compute_pass(pass_no: int) -> dict:
    """Bir hesaplama turu: evreni tazele, değişen sembolleri yeniden hesapla.

    Yayın yapmaz; güncel snapshot'ı döndürür (loop yayını yönetir).
    `_pass_lock` ile serileştirilir: döngü ve REST ucu aynı anda çağırırsa
    ikinci çağrı birincinin bitmesini bekler (A2) — çift hesap ve çift alarm yok.
    """
    global _SNAPSHOT, _dirty, _last_price_seen, _last_pass_at
    async with _pass_lock:
        _last_pass_at = time.time()
        return await _compute_pass_locked(pass_no)


async def _compute_pass_locked(pass_no: int) -> dict:
    global _SNAPSHOT, _dirty, _last_price_seen
    now = time.time()
    pass_changed: set[str] = set()
    settings = await get_macd_settings()
    jump_min = int(settings.get("jump_min_score", config.MACD_JUMP_MIN_SCORE_DEFAULT))
    alerts_enabled = bool(settings.get("alerts_enabled", True))
    early_alerts_enabled = bool(settings.get("early_alerts_enabled", True))
    universe = await _active_symbols()
    snapshot_symbols = _SNAPSHOT.setdefault("symbols", {})
    universe_changed = universe != list(_SNAPSHOT.get("universe") or [])

    # Evrenden düşen sembolleri temizle
    keep = set(universe)
    for sym in [s for s in list(snapshot_symbols) if s not in keep]:
        snapshot_symbols.pop(sym, None)
        _last_price_seen.pop(sym, None)
        for tf in TF_LIST:
            _last_bar_ts.pop((sym, tf), None)

    # M3/M30 REST tazeleme (yalnızca süresi gelenler; pass başına sınırlı).
    # Tazelenen (sym, tf) anahtarları toplanır: fiyat değişmese de o hücreler
    # yeniden hesaplanmalıdır, aksi halde refresh'in hiçbir etkisi olmaz (A1).
    due = []
    for sym in universe:
        for tf, interval in _REST_REFRESH_TFS.items():
            key = (sym, tf)
            last = _last_rest_refresh.get(key, 0.0)
            if not last or now - last > interval:
                due.append(key)
    refreshed: set[tuple[str, str]] = set()
    if due:
        async def _refresh(key):
            sym, tf = key
            try:
                if await market.refresh_series(sym, tf, limit=150):
                    _last_rest_refresh[key] = time.time()
                    refreshed.add(key)
            except Exception as exc:
                logger.debug("macd_monitor refresh_series %s/%s: %s", sym, tf, exc)
        await asyncio.gather(*(_refresh(k) for k in due[:_MAX_REST_PER_PASS]),
                             return_exceptions=True)

    recomputed = 0
    # C4/B8: trend/sinyal hesabı yalnızca gerçekten değişen semboller için
    # yeniden yapılır (6 TF × OLS + ATR + kırılım + hacim pahalıdır).
    trend_stale: set[str] = set()
    for sym in universe:
        try:
            ticker = market.get_ticker(sym)
            price = float((ticker or {}).get("last_price") or 0) if ticker else 0
            is_new = sym not in snapshot_symbols
            row = snapshot_symbols.get(sym) or {}
            tfs = row.get("tfs") or {}
            # Hücre bazında bayatlama gerekçesi: (a) yeni sembol, (b) evren
            # değişti, (c) canlı fiyat değişti, (d) ilgili TF REST'ten tazelendi,
            # (e) o TF'te yeni bir bar kapandı. Fiyat yoksa (ticker gelmedi)
            # asla atlanmaz — aksi halde satır ilk değerde donar (A1/A8/A9).
            price_changed = price != float(_last_price_seen.get(sym) or 0)
            touched = False
            for tf in TF_LIST:
                key = (sym, tf)
                history = market.get_ut_kline(sym, tf)
                marker = _bar_marker(history)
                prev_marker = _last_bar_ts.get(key, 0.0)
                new_bar = bool(marker and marker != prev_marker)
                stale_tf = key in refreshed
                if not (is_new or universe_changed or price_changed or new_bar or stale_tf):
                    continue
                tfs[tf] = _compute_cell(sym, tf)
                if marker:
                    _last_bar_ts[key] = marker
                touched = True
            row["tfs"] = tfs
            if price > 0:
                row["last"] = price
            snapshot_symbols[sym] = row
            # Fiyat, hücreler BAŞARIYLA hesaplandıktan sonra kaydedilir; erken
            # yazılırsa bir istisna satırın kalıcı olarak donmasına yol açardı.
            _last_price_seen[sym] = price
            if is_new or price_changed or universe_changed or touched:
                trend_stale.add(sym)
            if is_new or price_changed or universe_changed:
                recomputed += 1
            if touched or is_new:
                pass_changed.add(sym)
        except Exception as exc:
            logger.warning("macd_monitor sembol hatası %s: %s", sym, exc)
            continue

    # Evren değiştiyse delta yetmez (sembol DÜŞMÜŞ olabilir) → tam yayın şart.
    if universe_changed:
        _dirty = True

    # Trend gücü: her TF için 20 barlık lineer regresyon — R² (düzenlilik) ×
    # |eğim|/bar-aralığı (hız). Sembol skoru = TF'lerin _TF_WEIGHTS ile AĞIRLIKLI
    # ortalaması (M5/M15 önde, M1/M3 düşük); evren içinde 0-10'a normalize.
    raw_map: dict[str, dict] = {}
    extras: dict[str, dict] = {}
    for sym in snapshot_symbols:
        if sym not in trend_stale:
            cached = _trend_cache.get(sym)
            if cached is not None:
                raw_map[sym], extras[sym] = cached
                continue
        try:
            raw_map[sym], extras[sym] = _symbol_trend_and_signals(sym, snapshot_symbols)
        except Exception as exc:
            logger.warning("macd_monitor trend hatası %s: %s", sym, exc)
            continue
        _trend_cache[sym] = (raw_map[sym], extras[sym])
    # Önbellekten düşen sembolleri (evrenden çıkanlar) temizle
    for sym in [s for s in list(_trend_cache) if s not in snapshot_symbols]:
        _trend_cache.pop(sym, None)
    raws = [entry["raw"] for entry in raw_map.values()]
    lo, hi = (min(raws), max(raws)) if raws else (None, None)
    for sym, row in snapshot_symbols.items():
        entry = raw_map.get(sym)
        if not entry:
            continue
        extra = extras.get(sym) or {}
        prev_jump = row.get("jump")
        pre_prev = bool(row.get("pre_any"))
        score, tier = _strength_meta(entry["raw"], lo, hi)
        jump = _jump_score(score, extra.get("green", 0), extra.get("sigs", {}), extra.get("cvd", {}))
        sigs = extra.get("sigs")
        cvd = extra.get("cvd")
        pre = extra.get("pre") or {}
        pre_any = bool(extra.get("pre_any"))
        updated = {
            "strength": score,
            "tier": tier,
            "r2": round(entry["r2"], 3),
            "speed": round(entry["speed"], 4) if entry["speed"] is not None else None,
            "dir": round(entry["dir"], 4) if entry.get("dir") is not None else None,
            "sigs": sigs,
            "cvd": cvd,
            "jump": jump,
            "pre": pre,
            "pre_any": pre_any,
        }
        if (row.get("strength"), row.get("tier"), row.get("r2"), row.get("speed"),
                row.get("dir"), row.get("jump"), row.get("sigs"), row.get("cvd"),
                row.get("pre"), row.get("pre_any")) != (
            updated["strength"], updated["tier"], updated["r2"], updated["speed"],
            updated["dir"], updated["jump"], updated["sigs"], updated["cvd"],
            updated["pre"], updated["pre_any"]
        ):
            pass_changed.add(sym)
        row.update(updated)
        # KIRILIM aşaması: skor eşik GEÇİŞİ + histerezis (başlangıçta sessiz)
        if alerts_enabled and _update_jump_arm(row, jump, jump_min, prev_jump):
            await _maybe_fire_jump_alert(sym, jump, jump_min, settings)
        # YAKLAŞIYOR aşaması: erken öncü sinyal (0 → 1 geçişi, boot'ta sessiz)
        if (alerts_enabled and early_alerts_enabled and pre_any and not pre_prev):
            await _maybe_fire_early_alert(sym, pre, settings)

    # Ayarlar değişirse UI eşiği de tazelensin (delta yetmez → tam yayın)
    if _SNAPSHOT.get("jump_min") != jump_min:
        _dirty = True
    # C4/B9: bu turda değişen sembolleri biriktir (loop delta yayınlar).
    if pass_changed:
        _pending_changed.update(pass_changed)
    _SNAPSHOT.update({
        "universe": universe,
        "symbols": snapshot_symbols,
        "generated_at": now,
        "timeframes": list(TF_LIST),
        "jump_min": jump_min,
    })
    return _SNAPSHOT


async def macd_evidence_loop():
    """Bekleyen MACD alarmlarının 5m/15m/30m sonuçlarını periyodik doldur (C3).

    Sinyal DAVRANIŞINI değiştirmez; yalnızca `macd_monitor_alerts` tablosunu
    gerçekleşen getirilerle zenginleştirir. Böylece `jump_min_score` ve
    `_TF_WEIGHTS` gibi sezgisel sabitler, sezgi yerine ampirik isabet oranı ve
    ortalama getiriyle ayarlanabilir.
    """
    logger.info("macd_monitor kanıt doldurma döngüsü başladı")
    await asyncio.sleep(_FIRST_WAIT_SEC + 5.0)
    while True:
        try:
            filled = await database.fill_macd_monitor_alert_outcomes()
            if filled:
                logger.debug("macd_monitor kanıt: %d alarm sonucu dolduruldu", filled)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("macd_monitor kanıt doldurma: %s", exc)
        await asyncio.sleep(_EVIDENCE_FILL_SEC)


async def macd_monitor_loop():
    """~1 sn'de bir: değişen sembolleri hesapla, değişiklik varsa yayınla.

    Yayın iki modludur (B9): değişen semboller için `macd_monitor_delta` (küçük
    gövde), evren/ayar değişimi veya her 5. pass'ta koşulsuz `macd_monitor`
    (tam snapshot — istemci kendini onarır).
    """
    logger.info("macd_monitor döngüsü başladı")
    await asyncio.sleep(_FIRST_WAIT_SEC)
    global _dirty
    pass_no = 0
    while True:
        try:
            pass_no += 1
            await _compute_pass(pass_no)
            force_full = (pass_no % _FULL_BROADCAST_EVERY) == 0
            if _dirty or force_full:
                # Tam yayın: evren/ayar değişti ya da kendini onarma turu.
                await ws_manager.broadcast({"type": "macd_monitor", "data": _snapshot_payload()})
                _dirty = False
                _pending_changed.clear()
            elif _pending_changed:
                # Delta yayın: yalnızca değişen sembol satırları (B9).
                data = _delta_payload(_pending_changed)
                _pending_changed.clear()
                if data:
                    await ws_manager.broadcast({"type": "macd_monitor_delta", "data": data})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("macd_monitor turu: %s", exc)
        await asyncio.sleep(LOOP_SEC)


def _snapshot_payload() -> dict:
    """Yayın/cevap için `_SNAPSHOT`'ın sığ kopyası (global ASLA dışarı verilmez).

    `running` alanını cevaba eklemek global snapshot'ı kirletmesin diye ayrı
    sözlük kurulur (A10).
    """
    payload = dict(_SNAPSHOT)
    payload["symbols"] = dict(_SNAPSHOT.get("symbols") or {})
    return payload


def _delta_payload(changed: set[str]) -> dict:
    """Yalnızca değişen sembollerin satırlarını taşıyan kısmi güncelleme (B9).

    İstemci bu satırları mevcut snapshot'ının üzerine yazar. `universe`/`jump_min`
    de gönderilir çünkü ikisi de UI'ın türetilmiş sayaçlarını besler. Sembol
    DÜŞMESİ delta ile ifade edilemez — o durumda `_dirty` ile tam yayın yapılır.
    """
    symbols = _SNAPSHOT.get("symbols") or {}
    rows = {sym: symbols[sym] for sym in changed if sym in symbols}
    if not rows:
        return {}
    return {
        "delta": True,
        "symbols": rows,
        "universe": list(_SNAPSHOT.get("universe") or []),
        "timeframes": list(TF_LIST),
        "jump_min": _SNAPSHOT.get("jump_min"),
        "generated_at": _SNAPSHOT.get("generated_at"),
    }


@router.get("/api/macd-monitor")
async def get_macd_monitor():
    """MACD MONITOR snapshot'ı (REST ilk yükleme/yedek).

    Veri yalnızca public market verisinden türetilir (kapanış fiyatları +
    MACD/trend gücü); monitoring sayfasındaki "YÜKSELİŞ EĞİLİMİ ADAYLARI"
    bölümü de bu ucu kullandığından admin kısıtı YOKTUR.

    Döngü çalışıyorsa ve önbellek taze ise hesap YENİDEN yapılmaz — aksi halde
    her sayfa yüklemesi tam evren hesabını tetikler ve alarm üretebilirdi (A2).
    """
    running = _loop_task is not None and not _loop_task.done()
    age = time.time() - float(_SNAPSHOT.get("generated_at") or 0)
    if running and _SNAPSHOT.get("symbols") and age <= _REST_CACHE_MAX_AGE_SEC:
        payload = _snapshot_payload()
    else:
        try:
            await _compute_pass(0)
        except Exception as exc:
            logger.warning("macd_monitor snapshot hesaplanamadı: %s", exc)
        payload = _snapshot_payload()
    payload["running"] = running
    return {"paper_only": True, **payload}


@router.get("/api/macd-monitor/alerts")
async def get_macd_monitor_alerts(limit: int = 100, symbol: str | None = None,
                                  days: int = 30):
    """Son MACD alarmları + isabet özeti (C3 kanıt katmanı).

    Sinyaller yalnızca public market verisinden türetilir (sembol + skor +
    gerçekleşen ileri getiri); monitoring sayfası bunu doğrudan kullanır.
    """
    alerts = await database.list_macd_monitor_alerts(limit=limit, symbol=symbol)
    stats = await database.macd_monitor_alert_stats(days=days)
    return {"paper_only": True, "alerts": alerts, "stats": stats}


@router.get("/api/macd-monitor/settings")
async def get_macd_settings_endpoint():
    """MACD MONITOR / SIRÇRAMA ADAYI ayarları (okuma herkese açık)."""
    settings = await get_macd_settings(force=True)
    return {"paper_only": True, "settings": settings}


@router.put("/api/macd-monitor/settings")
async def update_macd_settings_endpoint(payload: dict, request: Request):
    """MACD MONITOR / SIRÇRAMA ADAYI ayarlarını güncelle (admin-only).

    jump_min_score: SIRÇRAMA ADAYI eşiği (0-100).
    alerts_enabled: eşik geçiş alarmları (WS olayı + banner).
    push_enabled: web push bildirimleri (açıksa alarmla birlikte gider).
    """
    global _dirty
    from app.main import _require_admin
    _require_admin(request)
    existing = await get_macd_settings(force=True)
    editable = ("jump_min_score", "alerts_enabled", "push_enabled", "early_alerts_enabled")
    merged = {**existing, **{k: payload[k] for k in editable if k in payload}}
    settings = {
        "jump_min_score": int(max(0, min(100, int(merged.get("jump_min_score", existing["jump_min_score"]))))),
        "alerts_enabled": _to_bool(merged.get("alerts_enabled"), existing["alerts_enabled"]),
        "push_enabled": _to_bool(merged.get("push_enabled"), existing["push_enabled"]),
        "early_alerts_enabled": _to_bool(merged.get("early_alerts_enabled"), existing["early_alerts_enabled"]),
    }
    await database.set_llm_setting("macd_monitor_settings", json.dumps(settings))
    _settings_cache.update(value=settings, at=time.time())
    _dirty = True  # yeni eşik değeri bir sonraki yayında UI'a gitsin
    return {"paper_only": True, "ok": True, "settings": settings}


def start_macd_monitor_loop() -> bool:
    """Arka plan döngülerini bir kez başlat (idempotent)."""
    global _loop_task, _evidence_task
    if _loop_task is not None and not _loop_task.done():
        return False
    _loop_task = asyncio.create_task(macd_monitor_loop(), name="macd-monitor-loop")
    _background_tasks.add(_loop_task)
    # C3 kanıt doldurma yardımcı döngüsü (sinyal davranışını değiştirmez)
    if _evidence_task is None or _evidence_task.done():
        _evidence_task = asyncio.create_task(macd_evidence_loop(),
                                              name="macd-evidence-loop")
        _background_tasks.add(_evidence_task)
    return True


def stop_macd_monitor_loop():
    """Döngüleri durdur (arka plan task havuzundan çıkar)."""
    global _loop_task, _evidence_task
    for task in (_loop_task, _evidence_task):
        if task is not None:
            task.cancel()
            _background_tasks.discard(task)
    _loop_task = None
    _evidence_task = None
