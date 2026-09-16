"""Monitoring page API: continuous scan for high-potential symbols with push notifications."""
import asyncio
import json
import logging
import math
import os
import time
from collections import deque

from fastapi import APIRouter, HTTPException, Request

from app.config import config
from app import database
from app.api_common import log_user_action, _background_tasks, _start_background, get_task
from app.state import market, analyzer
from app.routers.velocity import (detect_velocity_candidates, upside_rank_score,
                                  _journal_touch_rates)
from app.alerting import deliver_web_push
from app.ws_runtime import ws_manager
from contextlib import asynccontextmanager

logger = logging.getLogger("scalper.monitoring")
router = APIRouter()

# Monitoring state
_monitoring_state = {
    "last_scan_at": None,
    "last_candidates": [],
    "last_watchlist": [],
    "scan_count": 0,
    "notified_symbols": {},       # symbol -> son bildirim zamanı (epoch)
    "watchlist_seen_at": {},      # symbol -> izlemeye alınma zamanı
    "history": [],                # son bildirim geçmişi (yeni -> eski)
    "pending_targets": {},        # symbol -> {"expected": float, "horizon_minutes": int, "set_at": epoch}
    "candidate_streak": {},       # symbol -> ardışık aday tarama sayısı (debounce)
    # D-07 (2026-09-14): symbol -> son YENİ bildirimin taban fiyatı.
    # "Hiçbir şey değişmedi" durumunu yakalamak için (zaman kapıları görmez).
    "notified_prices": {},
    "refire_blocked": 0,          # D-07: fiyat değişmediği için bastırılan yeniden tetikleme
    "rr_blocked": 0,              # A4: R/R kapısı yüzünden bastırılan aday sayısı (ölçüm)
    "rising_notified": 0,         # R3: bu oturumda bildirilen yükseliş/erken sinyali
    "risk_off": False,            # piyasa rejimi RISK_OFF
    "risk_off_unknown": False,    # F-14: referans verisi yetersiz → rejim BİLİNMİYOR
    "_db_latencies": [],              # notify query gecikmeleri (diagnostics icin, 2026-09-07) (gözlem bayrağı, eşiği etkilemez — 2026-09-04)
}

# Sunucu tarafı döngü aralıkları: genel tarama 60 sn; izleme listesindeki
# semboller her turda zorunlu havuza eklenip yeniden analiz edilir. Böylece
# PWA kapalı olsa bile tarama ve bildirim sunucudan devam eder.
SCAN_INTERVAL_SEC = 60.0
HISTORY_LIMIT = 60
NOTIFY_COOLDOWN_SEC = 300.0  # aynı sembol için tekrar bildirim engeli (5 dk)
# D-07 (2026-09-14): yeniden tetikleme için ASGARİ fiyat hareketi (YÜZDE).
# Zaman kapıları (cooldown + ufuk) "değişen bir şey var mı" sorusunu SORMAZ;
# donmuş/likit olmayan sembolde aynı fiyattan tekrar tekrar bildirim üretir.
# Varsayılan = gidiş-dönüş maliyeti (%0.35): kâr ettirmeyecek bir hareket
# "yeni sinyal" sayılmaz. Kanıt: 88 ardışık çiftte 26 tekrarı bastırır,
# hiçbir TAMAMEN'i kaybettirmez (TAMAMEN oranı %8.0 -> %11.3).
MONITORING_REFIRE_MIN_MOVE_PCT = float(
    os.getenv("MONITORING_REFIRE_MIN_MOVE_PCT", str(config.round_trip_cost() * 100)))
_loop_task = None
# Manuel (/api/monitoring/scan) ile arka plan döngüsü aynı anda taramasın diye
# ortak kilit — çift tarama/çift journal/state yarışını önler (2026-09-04).
_scan_lock = asyncio.Lock()

# State lock: _monitoring_state ve _deferred_push concurrent okuma/yazma
# yarisini onler (2026-09-07).
_state_lock = asyncio.Lock()

@asynccontextmanager
async def _locked_state():
    """_monitoring_state ve _deferred_push guvenli erisim icin."""
    async with _state_lock:
        yield

# Runtime state DB kalıcılığı: restart sonrası pending_targets / debounce
# sayacı / bildirim cooldown kaybolmasın diye her tarama sonunda JSON olarak
# yazılır, loop başlarken geri yüklenir (2026-09-04, hibrit sistem).
_STATE_SETTING_KEY = "monitoring_runtime_state"


def _score_is_saturated(row: dict) -> bool:
    """Panel skoru tavan yüzünden KIRPILMIŞ mı? (D-08, güncellendi A3)

    `linear` modda `normalize_score` raw >= CAP'te tam 100.00'a kırpar → gösterilen
    skor SIRALAMA bilgisi taşımaz. `log` modda (A3 sonrası varsayılan) kırpma
    yalnız raw >= REF'te olur ve REF gözlenen max'ın üstünde seçildiği için
    pratikte hiç tetiklenmez.
    Bayrak yalnızca GÖRÜNÜRLÜK içindir; eşik/hedef davranışı değişmez.
    """
    raw = row.get("raw_score")
    if raw is None:
        return False
    try:
        raw_v = float(raw)
    except (TypeError, ValueError):
        return False
    mode = _score_norm_mode()
    if mode == "linear":
        return raw_v >= float(_row_norm_cap(row))
    ref = float(getattr(config, "MONITORING_SCORE_NORM_LOG_REF", 25000) or 0)
    return ref > 0 and raw_v >= ref


def _score_norm_mode() -> str:
    return str(getattr(config, "MONITORING_SCORE_NORM_MODE", "log") or "log").lower()


# A3 (2026-09-14): panel ölçek SÜRÜMÜ. Satır başına `norm_version` yazılır; okuma
# tarafı (`_stored_panel_score`) sürüme göre doğru haritayı uygular. Sürüm 1 =
# lineer (min(100, raw/cap×100)), sürüm 2 = log (100×log1p(raw)/log1p(REF)).
MONITORING_SCORE_NORM_VERSION = 2


def _panel_from_raw(raw_score: float) -> float:
    """Ham velocity_score → panel (0-100). Aktif ölçek moduna göre monoton harita.

    `linear`: eski `min(100, raw/CAP×100)` — CAP üstünde SERT kırpar (sıralama kaybı).
    `log`   : `100×log1p(raw)/log1p(REF)` — REF'e kadar kırpma YOK; bildirilen
              banttaki yığılma biter (A3). REF gözlenen max'ın üstünde seçilir.
    """
    try:
        raw = float(raw_score or 0)
    except (TypeError, ValueError):
        return 0.0
    if raw <= 0:
        return 0.0
    if _score_norm_mode() == "linear":
        cap = float(getattr(config, "MONITORING_SCORE_NORM_CAP", 2000))
        if not cap > 0:  # cap<=0/NaN → normalizasyon tanımsız; ham skoru kelepçele
            return round(max(0.0, min(100.0, raw)), 1)
        return round(max(0.0, min(100.0, raw / cap * 100)), 1)
    ref = float(getattr(config, "MONITORING_SCORE_NORM_LOG_REF", 25000) or 0)
    denom = math.log1p(ref) if ref > 0 else 0.0
    if denom <= 0:  # REF<=0/NaN → log haritası tanımsız; ham skoru kelepçele
        return round(max(0.0, min(100.0, raw)), 1)
    return round(max(0.0, min(100.0, 100.0 * math.log1p(raw) / denom)), 1)


def _raw_from_panel(panel_score: float) -> float:
    """Panel (0-100) → ham velocity_score: `_panel_from_raw`'un TERSİ.

    Admin eşikleri panel ölçeğinde girilir (`min_score`), aday kapısı ise ham
    skorla karşılaştırır. Ters harita yanlış olursa admin eşiği sessizce kayar
    (log modda doğrusal ters çevirme ~%15 hata verirdi: panel 70 → 1400 yerine
    1195).
    """
    try:
        panel = max(0.0, min(100.0, float(panel_score)))
    except (TypeError, ValueError):
        panel = 0.0
    if _score_norm_mode() == "linear":
        cap = float(getattr(config, "MONITORING_SCORE_NORM_CAP", 2000))
        return panel / 100.0 * max(1e-9, cap)
    ref = float(getattr(config, "MONITORING_SCORE_NORM_LOG_REF", 25000) or 0)
    denom = math.log1p(ref) if ref > 0 else 0.0
    if denom <= 0:
        return panel
    return math.expm1(panel / 100.0 * denom)


def normalize_score(raw_score: float) -> float:
    """Ham velocity_score → panel (0-100). Kanonik kaynak: `_panel_from_raw`.

    NOT: `velocity._panel_score` bu formülün BİREBİR kopyasıdır (modül döngüsel
    import nedeniyle monitoring import edilemez). İkisinin eşitliği
    `test_d08_skor_doygunluk.py` parite testiyle kilitlidir.
    """
    return _panel_from_raw(raw_score)



async def _persist_runtime_state() -> None:
    try:
        # Deferred push kuyruğunu da kaydet (restart sonrası ertelenen push kaybolmasın)
        deferred = []
        for n in list(_deferred_push):
            deferred.append({
                "symbol": n.get("symbol"), "message": n.get("message"),
                "title": n.get("title"), "url": n.get("url"), "tag": n.get("tag"),
                "score": n.get("score"), "target_pct": n.get("target_pct"),
                "price": n.get("price"), "expected_price": n.get("expected_price"),
                "detected_at": n.get("detected_at"), "horizon_minutes": n.get("horizon_minutes"),
                "mode": n.get("mode"), "id": n.get("id"),
                "ml_hit_probability": n.get("ml_hit_probability"),
                "ml_target_pct": n.get("ml_target_pct"),
            })
        payload = {
            "pending_targets": _monitoring_state["pending_targets"],
            # F-07: bellek monotonik → kalıcı katman duvar saati (tek noktada dönüşüm).
            "notified_symbols": _notified_wall_from_mono(_monitoring_state["notified_symbols"]),
            "watchlist_seen_at": _monitoring_state["watchlist_seen_at"],
            "candidate_streak": _monitoring_state["candidate_streak"],
            "notified_prices": _monitoring_state["notified_prices"],
            "refire_blocked": int(_monitoring_state.get("refire_blocked", 0)),
            "refire_min_move_pct": MONITORING_REFIRE_MIN_MOVE_PCT,
            "notified_prices": _monitoring_state["notified_prices"],
            "refire_blocked": int(_monitoring_state.get("refire_blocked", 0)),
            "rr_blocked": int(_monitoring_state.get("rr_blocked", 0)),
            "risk_off": bool(_monitoring_state["risk_off"]),
            # M1/P2 (R4-11): rejim "BİLİNMİYOR" bayrağı da kalıcılaştırılır.
            "risk_off_unknown": bool(_monitoring_state.get("risk_off_unknown", False)),
            # HISTORY_LIMIT ile aynı sınır (restore'da [:HISTORY_LIMIT] kesiliyor —
            # yazım 100, okuma 60 farklı limanlarıydı; tek limana indirildi).
            "history": _monitoring_state["history"][:HISTORY_LIMIT],
            "deferred_push": deferred,
        }
        await database.set_llm_setting(_STATE_SETTING_KEY, json.dumps(payload, default=str))
    except Exception as exc:
        # M1/P2 (R2-08): sessiz DEBUG yerine WARNING — persist hatası restart'ta
        # dedup/cooldown kaybı demektir, operatör bunu görmeli.
        logger.warning("monitoring state kalıcılaştırılamadı: %s", exc)


async def restore_runtime_state() -> None:
    """DBden runtime statei geri yukler."""
    try:
        raw = await database.get_llm_setting(_STATE_SETTING_KEY, "{}")
        async with _locked_state():
            payload = json.loads(raw or "{}")
            if isinstance(payload, dict):
                _monitoring_state["pending_targets"] = payload.get("pending_targets") or {}
                # F-07: kalıcı duvar saati → bellek monotonik (tek noktada dönüşüm).
                _monitoring_state["notified_symbols"] = _notified_mono_from_wall(
                    payload.get("notified_symbols"))
                _monitoring_state["watchlist_seen_at"] = payload.get("watchlist_seen_at") or {}
                _monitoring_state["candidate_streak"] = payload.get("candidate_streak") or {}
                _monitoring_state["notified_prices"] = payload.get("notified_prices") or {}
                _monitoring_state["refire_blocked"] = int(payload.get("refire_blocked", 0) or 0)
                _monitoring_state["rr_blocked"] = int(payload.get("rr_blocked", 0) or 0)
                _monitoring_state["risk_off"] = bool(payload.get("risk_off", False))
                # M1/P2 (R4-11): BİLİNMİYOR bayrağı geri yüklenir (restart sonrası
                # ilk taramaya kadar "rejim biliniyor" yanılsaması olmasın).
                _monitoring_state["risk_off_unknown"] = bool(payload.get("risk_off_unknown", False))
                _monitoring_state["history"] = (payload.get("history") or [])[:HISTORY_LIMIT]
                deferred = payload.get("deferred_push") or []
                _deferred_push.clear()
                for n in deferred:
                    _deferred_push.append(n)
                # NOT: `pending_targets` YUKARIDA bir kez atanır; burada ikinci kez
                # atanması ölü koddu (M1/P2 — R4-11).
    except Exception as exc:
        # M1/P2 (R2-08): bozuk payload TÜM runtime state'i sessizce sıfırlıyordu;
        # artık uyarı seviyesinde loglanır (operatör restart kaybını görür).
        logger.warning("monitoring state geri yuklenemedi (runtime state sifirlandi): %s", exc)


def _in_quiet_hours(settings) -> bool:
    """Sessiz saat aralığı kontrolü; gece yarısı üzerinden sarmalı aralık destekler."""
    start, end = settings.get("quiet_hours_start"), settings.get("quiet_hours_end")
    if not start or not end:
        return False
    try:
        h1, m1 = int(str(start).split(":")[0]), int(str(start).split(":")[1])
        h2, m2 = int(str(end).split(":")[0]), int(str(end).split(":")[1])
    except (ValueError, IndexError):
        return False
    now = time.localtime()
    cur = now.tm_hour * 60 + now.tm_min
    a = h1 * 60 + m1
    b = h2 * 60 + m2
    if a == b:
        return False
    return (cur >= a and cur < b) if a < b else (cur >= a or cur < b)


async def quiet_hours_active(settings: dict | None = None) -> bool:
    """Sessiz saatlerin ŞU AN etkin olup olmadığını döndür (dışa açık yardımcı — M1/P2).

    TEK KAYNAK: `_in_quiet_hours` mantığı. `auto_paper.py` bunu kullanarak sessiz
    saatlerde OTONOM işlemi de DURDURMALIDIR (yalnızca push erteleme değil — R3-07).
    `settings` verilmezse global bildirim ayarları DB'den okunur.
    """
    if settings is None:
        settings = await get_user_notification_settings()
    return _in_quiet_hours(settings)


def _effective_min_score(settings) -> float:
    """O an geçerli PANEL (0-100) eşiği — yalnızca gösterim/panel filtresi içindir.

    F-14: RISK_OFF'un eşiğe etkisi YOKTUR. Kod, üç ayrı yorum + UI metniyle
    çelişiyordu (`max(base+20, 50)` çarpanı hâlâ uygulanıyordu; ısınma
    sırasında referans verisi gelmezse `risk_off=True` oluyor ve radar eşiği
    SESSİZCE +20 yükseliyordu). Çarpan kaldırıldı — rejim bayrağı yalnızca
    gözlem amaçlıdır; veri yetersizken `risk_off_unknown` ile BİLİNMİYOR
    raporlanır.

    M1/P2 (R2-11/C2.3): alt sınır da kelepçelenir (negatif admin değeri tüm
    adayları geçirmesin). Aday KAPISI artık `_effective_min_raw_score`.
    B6: `min_score=None` (varsayılana dönüş) → panel varsayılanı kullanılır.
    """
    raw = settings.get("min_score")
    base = float(raw) if raw is not None else float(config.MONITORING_MIN_SCORE_DEFAULT)
    return round(max(0.0, min(100.0, base)), 1)


def _effective_min_raw_score(settings) -> float:
    """Aday KAPISI için HAM velocity_score eşiği (M1/P0 — R2-01/R2-02/R3-01).

    Öncelik sırası (dokümante):
      1. **Açık admin panel eşiği** (`min_score`, 0-100) verilmişse → ham eşik
         AKTİF ölçeğin TERS haritasıyla türetilir (`_raw_from_panel`; A3 sonrası
         log modda `expm1(panel/100 × log1p(REF))`). Admin panel ölçeğinde
         düşünür; ölçek/mode değişse de bu türetme tutarlıdır.
      2. Aksi halde → `config.MONITORING_MIN_RAW_SCORE` (varsayılan 1400). Bu mutlak
         ham eşik ölçekten BAĞIMSIZDIR; böylece ölçek haritası ileride değişse bile
         aday kapısı sessizce kaymaz.

    "Açık" belirleme: settings'te `min_score_explicit` işareti varsa o kullanılır
    (DB'den gelen ayarlar bu işareti taşır); yoksa `min_score` anahtarının
    VAR OLUP None OLMADIĞINA bakılır (B6: `min_score: null` → açık eşik YOK,
    varsayılan ham eşik devreye döner; testlerin/manuel sözlüklerin geriye
    dönük uyumu korunur).
    """
    explicit = settings.get("min_score_explicit")
    if explicit is None:
        explicit = settings.get("min_score") is not None
    if explicit:
        raw_panel = settings.get("min_score")
        panel = max(0.0, min(100.0, float(
            raw_panel if raw_panel is not None else config.MONITORING_MIN_SCORE_DEFAULT)))
        # A3: panel → ham dönüşümü AKTİF ölçeğin tersi olmalı (log modda expm1).
        return round(_raw_from_panel(panel), 4)
    return float(config.MONITORING_MIN_RAW_SCORE)


def _threshold_fields(settings) -> dict:
    """State/ayar yanıtlarına eklenecek eşik alanları (M1/P0 — R2-02).

    `monitoring_min_raw_score`: aday kapısının karşılaştırdığı HAM skor eşiği.
    `monitoring_min_score_panel`: aynı eşiğin panel (0-100) karşılığı — gösterim.
    `effective_min_score`: geriye dönük uyumluluk (== panel eşiği).
    A4 R/R kapısı alanları (`rr_*`) — panel/lejant bu kalibrasyonu gösterir.
    """
    return {
        "effective_min_score": _effective_min_score(settings),
        "monitoring_min_raw_score": _effective_min_raw_score(settings),
        "monitoring_min_score_panel": _effective_min_score(settings),
        "rr_enabled": bool(getattr(config, "MONITORING_RR_ENABLED", True)),
        "rr_min": float(getattr(config, "MONITORING_RR_MIN", 0.6)),
        "rr_sl_pct": float(getattr(config, "MONITORING_RR_SL_PCT", 3.0)),
        "rr_blocked": int(_monitoring_state.get("rr_blocked", 0)),
    }


def _notified_mono_from_wall(values) -> dict[str, float]:
    """F-07: kalıcı (duvar saati) bildirim damgalarını monotonik tabana çevir.

    `notified_symbols` BELLEKTE monotonik zaman tutar (cooldown GÖRELİ ölçüm);
    kalıcı katman duvar saati beklediği için restore'da yaş üzerinden tek seferde
    dönüştürülür — iki saat karıştırılmaz.
    """
    mono_now = time.monotonic()
    wall_now = time.time()
    out: dict[str, float] = {}
    for sym, ts in (values or {}).items():
        try:
            age = max(0.0, wall_now - float(ts))
        except (TypeError, ValueError):
            age = 0.0
        out[sym] = mono_now - age
    return out


def _notified_wall_from_mono(values) -> dict[str, float]:
    """F-07: bellekteki monotonik bildirim damgalarını kalıcı duvar saatine çevir."""
    mono_now = time.monotonic()
    wall_now = time.time()
    out: dict[str, float] = {}
    for sym, ts in (values or {}).items():
        try:
            age = max(0.0, mono_now - float(ts))
        except (TypeError, ValueError):
            age = 0.0
        out[sym] = wall_now - age
    return out


def get_cached_radar_candidate(symbol: str) -> dict | None:
    """Son taramanın 'uygun adaylar' listesinden sembolün aday kaydını döndür.

    auto_paper, trailing/breakeven kapanışı sonrası yeniden açma kararını bu
    listeye dayandırır: sembol panelde (son taramada) göründüğü sürece fırsat
    canlı kabul edilir; listeden düşmüşse None döner.
    """
    sym = str(symbol or "").upper()
    for c in _monitoring_state.get("last_candidates") or []:
        if str(c.get("symbol") or "").upper() == sym:
            return c
    return None


async def get_user_notification_settings() -> dict:
    """Global bildirim ayarlarını DB'den oku (admin ayarı — tüm kullanıcıları etkiler).

    min_score varsayılanı config.MONITORING_MIN_SCORE_DEFAULT (70): yalnızca
    yüksek güvenli adaylar bildirilir. Admin PUT ile düşürüp daha fazla
    bildirim alabilir — değişiklik tüm kullanıcıları anında etkiler.
    """
    try:
        settings_json = await database.get_llm_setting("monitoring_notification_settings", "{}")
        settings = json.loads(settings_json or "{}")
        # B6: min_score None olabilir (varsayılana dönüş) — float(None) patlamasın.
        raw_min = settings.get("min_score")
        min_score = float(raw_min) if raw_min is not None else float(config.MONITORING_MIN_SCORE_DEFAULT)
        return {
            "enabled": settings.get("enabled", True),
            "min_score": min_score,
            # M1/P0: admin `min_score` PANEL eşiğini AÇIKÇA set etti mi? Aday kapısı
            # önceliği buna bağlı (açık panel > varsayılan ham eşik).
            "min_score_explicit": settings.get("min_score") is not None,
            "min_target_pct": float(settings.get("min_target_pct", 2.0)),
            "quiet_hours_start": settings.get("quiet_hours_start", None),
            "quiet_hours_end": settings.get("quiet_hours_end", None),
            # A5: verilmezse config varsayılanı (AÇIK) — `_notify` ile aynı öncelik.
            "macd_refire_gate": _coerce_bool(settings.get(
                "macd_refire_gate", getattr(config, "MONITORING_MACD_REFIRE_GATE", True))),
            # BİRLEŞİK RADAR (2026-09-16): verilmezse config varsayılanı. Tek doğruluk
            # kaynağı bu fonksiyondur — motor, teslimat ve Radar ayar sekmesi buradan okur.
            "radar_combined_enabled": _coerce_bool(settings.get(
                "radar_combined_enabled", getattr(config, "RADAR_COMBINED_ENABLED", False))),
            "radar_unified_notify": _coerce_bool(settings.get(
                "radar_unified_notify", getattr(config, "RADAR_UNIFIED_NOTIFY", False))),
            "radar_route_velocity_auto_through_auto_paper": _coerce_bool(settings.get(
                "radar_route_velocity_auto_through_auto_paper",
                getattr(config, "RADAR_ROUTE_VELOCITY_AUTO_THROUGH_AUTO_PAPER", False))),
            "radar_confluence_window_sec": _radar_confluence_window(settings.get(
                "radar_confluence_window_sec",
                getattr(config, "RADAR_CONFLUENCE_WINDOW_SEC", 1800))),
        }
    except Exception:
        return {"enabled": True, "min_score": config.MONITORING_MIN_SCORE_DEFAULT,
                "min_score_explicit": False,
                "min_target_pct": 2.0, "quiet_hours_start": None, "quiet_hours_end": None,
                "macd_refire_gate": bool(getattr(config, "MONITORING_MACD_REFIRE_GATE", True)),
                # Hata durumunda da RADAR anahtarları VAR OLMALI — yoksa motor/teslimat
                # anahtarı bulamayıp sessizce yanlış dala gider.
                "radar_combined_enabled": bool(getattr(config, "RADAR_COMBINED_ENABLED", False)),
                "radar_unified_notify": bool(getattr(config, "RADAR_UNIFIED_NOTIFY", False)),
                "radar_route_velocity_auto_through_auto_paper": bool(
                    getattr(config, "RADAR_ROUTE_VELOCITY_AUTO_THROUGH_AUTO_PAPER", False)),
                "radar_confluence_window_sec": int(
                    getattr(config, "RADAR_CONFLUENCE_WINDOW_SEC", 1800))}


@router.get("/api/monitoring/settings")
async def get_monitoring_settings():
    """Global bildirim ayarlarını döndür (okuma tüm kullanıcıya açık)."""
    settings = await get_user_notification_settings()
    # M1/P2 (R2-18): okuma uçları state'i kilit altında okur.
    async with _locked_state():
        risk_off = bool(_monitoring_state["risk_off"])
        risk_off_unknown = bool(_monitoring_state.get("risk_off_unknown", False))
    return {"paper_only": True, "scope": "global_admin",
            "risk_off": risk_off,
            "risk_off_unknown": risk_off_unknown,
            **_threshold_fields(settings),
            **settings}


def _coerce_bool(value) -> bool:
    """Bool alanları esnek ama GÜVENLİ çevir; tanınmazsa HTTPException(422) (R4-06)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        low = value.strip().lower()
        if low in ("true", "1", "yes", "on", "acik", "açık"):
            return True
        if low in ("false", "0", "no", "off", "kapali", "kapalı"):
            return False
    raise HTTPException(status_code=422, detail=f"Geçersiz boolean değeri: {value!r}")


def _validate_hhmm(value, field: str) -> str:
    """'HH:MM' doğrula; geçersizse HTTPException(422) (R4-06)."""
    try:
        parts = str(value).strip().split(":")
        if len(parts) != 2:
            raise ValueError("format")
        hh, mm = int(parts[0]), int(parts[1])
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            raise ValueError("range")
    except (TypeError, ValueError, IndexError):
        raise HTTPException(status_code=422, detail=f"{field} 'HH:MM' biçiminde olmalı (0-23:0-59)")
    return f"{hh:02d}:{mm:02d}"


def _radar_confluence_window(value) -> int:
    """Birleşik radar çakışma penceresi (sn): 60 sn - 6 saat aralığına zorlanır.

    Bu pencere "iki kaynağın aynı olay sayılması" için maksimum aralıktır; aşırı
    büyük bir değer alakasız sinyalleri çakışma sanıp raporu şişirir, bu yüzden
    üst sınır konur (6 saat = en uzun radar ufkundan geniş).
    """
    try:
        window = int(float(value))
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="radar_confluence_window_sec sayısal olmalı (sn)")
    if not (60 <= window <= 21600):
        raise HTTPException(status_code=422, detail="radar_confluence_window_sec 60-21600 sn (6 saat) aralığında olmalı")
    return window


@router.put("/api/monitoring/settings")
async def update_monitoring_settings(payload: dict, request: Request):
    """Global bildirim ayarlarını güncelle — YALNIZ admin.

    Admin tarafından yapılan değişiklik tüm kullanıcıları ve arka plan
    döngüsünü anında etkiler (kullanıcı-başı ayar kaldırıldı, 2026-09-04).
    Merge semantiği: yalnızca gönderilen alanlar güncellenir; diğer alanlar
    (min_target_pct, quiet_hours, enabled) korunur — aksi halde eşiği kaydeden
    her istek diğer ayarları varsayılana sıfırlıyordu (2026-09-04 teşhis).

    M1/P1 (R4-06): tip/aralık doğrulaması eklendi — `"abc"` → 500 DEĞİL 422;
    bozuk sessiz saatler deferral'ı sessizce kapatamaz; `min_target_pct`
    [MONITORING_TARGET_PCT_MIN, MAX] aralığına zorlanır.

    B6: `"min_score": null` gönderilerek AÇIK panel eşiği kaldırılabilir —
    aday kapısı varsayılan ham eşiğe (`MONITORING_MIN_RAW_SCORE`) döner.
    """
    from app.api_common import require_admin as _require_admin
    _require_admin(request)
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Gövde bir JSON nesnesi olmalı")
    existing = await get_user_notification_settings()
    editable = ("enabled", "min_score", "min_target_pct",
                "quiet_hours_start", "quiet_hours_end", "macd_refire_gate",
                # BİRLEŞİK RADAR (2026-09-16): aynı ayar deposu, aynı merge semantiği.
                "radar_combined_enabled", "radar_confluence_window_sec",
                "radar_unified_notify", "radar_route_velocity_auto_through_auto_paper")
    merged = {**existing, **{k: payload[k] for k in editable if k in payload}}

    # --- Doğrulama (geçersiz girdi → 422, state BOZULMAZ) ---
    enabled = _coerce_bool(merged.get("enabled", True))
    # B6: min_score=None (veya açıkça null gönderilmiş) → eşik sıfırlanır.
    min_score_reset = "min_score" in payload and payload["min_score"] is None
    if min_score_reset:
        min_score = None
    else:
        try:
            min_score = float(merged.get("min_score", config.MONITORING_MIN_SCORE_DEFAULT))
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="min_score sayısal olmalı (0-100 panel); varsayılana dönmek için null gönderin")
        if not (0.0 <= min_score <= 100.0):
            raise HTTPException(status_code=422, detail="min_score 0-100 aralığında olmalı")
    try:
        min_target = float(merged.get("min_target_pct", 2.0))
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="min_target_pct sayısal olmalı")
    if not (config.MONITORING_TARGET_PCT_MIN <= min_target <= config.MONITORING_TARGET_PCT_MAX):
        raise HTTPException(
            status_code=422,
            detail=f"min_target_pct {config.MONITORING_TARGET_PCT_MIN}-{config.MONITORING_TARGET_PCT_MAX} aralığında olmalı")
    quiet_start = merged.get("quiet_hours_start", None)
    quiet_end = merged.get("quiet_hours_end", None)
    if quiet_start not in (None, ""):
        quiet_start = _validate_hhmm(quiet_start, "quiet_hours_start")
    else:
        quiet_start = None
    if quiet_end not in (None, ""):
        quiet_end = _validate_hhmm(quiet_end, "quiet_hours_end")
    else:
        quiet_end = None

    settings = {
        "enabled": enabled,
        # B6: None saklanabilir → ham eşik varsayılanına dönüş (tek yönlü
        # kilit kaldırıldı; getter None'ı panel varsayılanı olarak çözer).
        "min_score": round(min_score, 4) if min_score is not None else None,
        "min_score_explicit": min_score is not None,
        "min_target_pct": min_target,
        "quiet_hours_start": quiet_start,
        "quiet_hours_end": quiet_end,
        # A5: MACD-teyitli yeniden bildirim kapısı (admin aç/kapa). Verilmezse
        # config varsayılanı korunur — `_notify` aynı önceliği uygular.
        "macd_refire_gate": _coerce_bool(merged.get(
            "macd_refire_gate", getattr(config, "MONITORING_MACD_REFIRE_GATE", True))),
        # BİRLEŞİK RADAR (2026-09-16): varsayılanlar config.RADAR_*'dan, admin
        # üzerine yazabilir. Kapalıyken hiçbir üretim yolu değişmez.
        "radar_combined_enabled": _coerce_bool(merged.get(
            "radar_combined_enabled", getattr(config, "RADAR_COMBINED_ENABLED", False))),
        "radar_unified_notify": _coerce_bool(merged.get(
            "radar_unified_notify", getattr(config, "RADAR_UNIFIED_NOTIFY", False))),
        "radar_route_velocity_auto_through_auto_paper": _coerce_bool(merged.get(
            "radar_route_velocity_auto_through_auto_paper",
            getattr(config, "RADAR_ROUTE_VELOCITY_AUTO_THROUGH_AUTO_PAPER", False))),
        "radar_confluence_window_sec": _radar_confluence_window(
            merged.get("radar_confluence_window_sec",
                       getattr(config, "RADAR_CONFLUENCE_WINDOW_SEC", 1800))),
    }
    await database.set_llm_setting("monitoring_notification_settings", json.dumps(settings))
    await log_user_action(None, None, "monitoring", "MONITORING_SETTINGS_UPDATE",
                          details={"settings": {k: v for k, v in settings.items() if k != "enabled"},
                                   "scope": "global_admin"},
                          request=request)
    async with _locked_state():
        risk_off = bool(_monitoring_state["risk_off"])
        risk_off_unknown = bool(_monitoring_state.get("risk_off_unknown", False))
    return {"paper_only": True, "ok": True, "scope": "global_admin",
            "risk_off": risk_off,
            "risk_off_unknown": risk_off_unknown,
            **_threshold_fields(settings),
            **settings}


# Otonom paper trade (monitoring bildiriminden tetiklenen, 2026-09-04)
# NOT: Sessiz saatte ertelenen push'lar bu kuyrukta tutulur; sessiz saat
# bitince monitoring_background_loop tarafından boşaltılıp gerçek push gönderilir.
# (Öncesinde "ertelenen" bildirim asla push edilmiyordu ve DB'ye yanlışlıkla
# sent_via_push=True yazılıyordu — 2026-09-05 düzeltmesi.)
_deferred_push = deque(maxlen=100)

# BİRLEŞİK RADAR (2026-09-16, Aşama 2): tek tip bildirim bastırıcısı.
# `radar_unified_notify=true` iken aynı turda aynı sembol için YALNIZCA BİR push
# gider. Bu set, radar teslimatının bu turda push ettiği sembolleri tutar;
# yükseliş teslimatı onları görüp İKİNCİ push'u atlar (çift bildirim ölür).
_unified_pushed_symbols: set[str] = set()


async def _radar_unified_enabled() -> bool:
    """Tek tip bildirim modu açık mı (radar+yükseliş tek tag/tek push)."""
    settings = await get_user_notification_settings()
    return bool(settings.get("radar_unified_notify")
                or getattr(config, "RADAR_UNIFIED_NOTIFY", False))


async def _send_push(notif: dict) -> bool:
    """Tek bildirimi web push ile gönder; gerçek başarı durumunu döndür.

    NOT: ek alanlar `.get()` ile okunur — bu yardımcı artık İKİ zarf şeklini
    taşır: radar bildirimi (skor/hedef/ufuk dolu) ve ertelenmiş ALARM push'u
    (`alerting.deliver_alert_push`; yalnız mesaj+başlık+url+tag taşır).
    Abonelik okuması `notif["..."]` ile yapılsaydı alarm zarfı KeyError verip
    sessizce gönderilemezdi.
    """
    try:
        result = await deliver_web_push(
            notif["message"],
            title=notif["title"],
            url=notif["url"],
            tag=notif["tag"],
            extra={
                "symbol": notif.get("symbol"),
                "score": notif.get("score"),
                "target_pct": notif.get("target_pct"),
                "price": notif.get("price"),
                "expected_price": notif.get("expected_price"),
                "detected_at": notif.get("detected_at"),
                "horizon_minutes": notif.get("horizon_minutes"),
                "source": notif.get("source", "monitoring"),
            },
        )
        ok = bool(result.get("ok", False))
        if not ok:
            reason = result.get("reason", result.get("error", "unknown"))
            logger.warning("Monitoring push failed for %s: %s", notif["symbol"], reason)
        return ok
    except Exception as exc:
        logger.warning("Monitoring push exception for %s: %s", notif["symbol"], exc)
        return False


async def _flush_deferred_push():
    """Sessiz saat bittiyse ertelenen push kuyruğunu boşalt (M1/P1 — R2-07/R4-12).

    Düzeltmeler:
      * Bayatlık (TTL): ufku (+2 dk tolerans) dolmuş bildirim GÖNDERİLMEZ (atılır).
      * Ayarlara saygı: `enabled=false` ise kuyruk TAMAMEN düşürülür.
      * VAPID yokken KİLİTLENME yok: gönderilemeyen öğeler kuyrukta tutulur ama
        TTL dolunca atılır (eskiden `break` ile sonsuza dek yeniden kuyruğa
        ekleniyordu — kalıcı latch).
      * `break` yok: tüm kuyruk her turda işlenir.
    """
    if not _deferred_push:
        return
    settings = await get_user_notification_settings()
    if _in_quiet_hours(settings):
        return  # hâlâ sessiz saatteyiz
    now = time.time()
    # Bildirimler kapatılmışsa ertelenenler bekletilmez (kullanıcı niyeti).
    if not settings.get("enabled", True):
        n = len(_deferred_push)
        _deferred_push.clear()
        logger.info("Monitoring: bildirimler kapalı — %d ertelenen push düşürüldü", n)
        return
    vapid_configured = bool(os.getenv("VAPID_PRIVATE_KEY", "").strip())
    if not vapid_configured:
        logger.warning("Monitoring: VAPID yapılandırılmamış — ertelenen push'lar teslim "
                       "edilemez; TTL dolunca düşürülecek (%d kuyrukta)", len(_deferred_push))
    sent = 0
    dropped = 0
    survivors = deque(maxlen=_deferred_push.maxlen)
    while _deferred_push:
        notif = _deferred_push.popleft()
        try:
            detected = float(notif.get("detected_at") or 0)
            horizon = int(notif.get("horizon_minutes") or 0)
        except (TypeError, ValueError):
            detected, horizon = 0.0, 0
        # TTL: hedef ufku (+ tolerans) geçtiyse bayat push gönderilmez.
        if detected and horizon and (now - detected) > (horizon + 2) * 60:
            dropped += 1
            continue
        if not vapid_configured:
            # Gönderilemez ama TTL dolmadan atmayız; sonraki turda yeniden denenir
            # ve TTL dolunca yukarıdaki dalda düşürülür (kalıcı latch YOK).
            survivors.append(notif)
            continue
        ok = await _send_push(notif)
        if ok:
            sent += 1
            notif["sent_via_push"] = True
            # Ertelenen push gerçekten gönderildi → DB etiketini düzelt
            nid = notif.get("id")
            if nid:
                try:
                    await database.mark_monitoring_push_sent(nid)
                except Exception as exc:
                    logger.warning("push etiketi güncellenemedi %s: %s", nid, exc)
            # R3: yükseliş bildiriminin kanıt satırı ayrı tabloda (`rising_alerts`);
            # `id` yerine `alert_id` taşır → dürüstlük kuralı orada da uygulanır.
            alert_id = notif.get("alert_id")
            if alert_id:
                try:
                    await database.mark_rising_alert_notified(int(alert_id), True)
                except Exception as exc:
                    logger.debug("rising push etiketi güncellenemedi %s: %s", alert_id, exc)
        else:
            # Gönderilemedi; TTL'e kadar bir sonraki fırsatta yeniden dene.
            survivors.append(notif)
    _deferred_push.extend(survivors)
    if sent:
        logger.info("Monitoring: sessiz saat bitti, %d ertelenen push gönderildi", sent)
    if dropped:
        logger.info("Monitoring: %d bayat (TTL dolmuş) ertelenen push düşürüldü", dropped)


# --- D-05 (2026-09-14): ticker fiyati tazelik dogrulamasi OLMADAN kullanilmaz ---
# `market.get_ticker()` onbellekten BAYAT fiyat dondurebiliyor; bildirime bayat
# fiyat + taze zaman damgasi yaziliyordu (olcum: 13.09 ARKTRY tabloda 10,26,
# ayni anda gercek mum ~7,0; gun araligi 5,95–9,94). MFE/touched ise adayin kendi
# fiyatiyla hesaplaniyor (velocity.py:873) -> ekrandaki fiyat ile olcum tabani
# ayrisiyordu. Tazelik kapisi precedent'i: auto_paper.py:219.
TICKER_MAX_AGE_SEC = float(getattr(config, "MONITORING_TICKER_MAX_AGE_SEC", 60))
# Yalnizca log: taze ama aday fiyattan cok sapmis ticker'i gormek icin.
TICKER_DIVERGENCE_WARN_PCT = 25.0


def _ticker_price(symbol: str) -> float | None:
    """Tazeligi DOGRULANMIS ticker fiyati; degilse None (bayat fiyat dondurmez)."""
    if not market:
        return None
    try:
        ticker = market.get_ticker(symbol)
    except Exception:
        return None
    if not ticker:
        return None
    try:
        if not market.ticker_freshness(symbol, max_age_sec=TICKER_MAX_AGE_SEC).get("fresh"):
            return None
    except Exception:
        return None
    try:
        price = float(ticker.get("last_price") or 0)
    except (TypeError, ValueError):
        return None
    return price if price > 0 else None


def _rr_ratio(target_pct: float) -> float | None:
    """Adayın ödül/risk oranı: TP mesafesi / SL mesafesi (ikisi de YÜZDE).

    SL dayanağı GERÇEK çıkış stop'udur (`MONITORING_RR_SL_PCT`, varsayılan %3 →
    `AUTO_PAPER_SL_PCT_DEFAULT` ile hizalı; pozisyonlar `stop_loss =
    fill_entry*(1-sl_pct)` ile açılır). Ölçülemeyen durumlarda None.
    """
    if not target_pct or target_pct <= 0:
        return None
    sl_pct = float(getattr(config, "MONITORING_RR_SL_PCT", 3.0) or 0.0)
    if sl_pct <= 0:
        return None
    return float(target_pct) / sl_pct


def _rr_gate_blocks(price: float, target_pct: float) -> bool:
    """A4: düşük ödül/risk adayını bildirme (True → `_notify` continue eder).

    Kalibrasyon (2026-09-14, gerçek DB): hedef bandı → dokunma oranı
    %2.00 → %8.8 (n=13137), %3.00 → %11.5 (n=15889), %4.00 → %1.3 (n=204).
    Yani yüksek hedef DAHA KÖTÜ vuruyor; "RR'yi yükselt" yönlü sıkı bir kapı
    isabeti en düşük bandı seçer. Bu yüzden eşik (`MONITORING_RR_MIN`, 0.6)
    yalnızca ödülü riskine göre anlamsız olan adayı eler (hedef < %1.8);
    tipik %2.0/%3.0 hedefleri geçer. Detay: `config.py` A4 bloğu.
    """
    if not getattr(config, "MONITORING_RR_ENABLED", True):
        return False
    if not price or price <= 0:
        return False
    rr = _rr_ratio(target_pct)
    if rr is None:
        return False
    return rr < float(getattr(config, "MONITORING_RR_MIN", 0.6))


def _build_notification(sym, c, settings, first_price: float | None = None) -> dict:
    """Zengin bildirim içeriği: sembol, tespit zamanı, %potansiyel, anlık ve beklenen fiyat.

    first_price: mevcut BEKLİYOR bildirimin ilk tespit fiyatı (güncelleme yolunda).
    Yoksa güncel fiyat kullanılır (yeni bildirim) — böylece API yanıtı ile DB'deki
    expected_price her zaman tutarlı olur (2026-09-06).
    """
    score = normalize_score(c.get("velocity_score", 0))
    target = float(c.get("target_pct", 2.0) or 0)
    price = float(c.get("price", 0) or 0)
    if first_price is not None:
        base_price = first_price
    else:
        # D-05: tazeligi dogrulanmis ticker YOKSA adayin kendi fiyati.
        # MFE/touched de `candidate.price` uzerinden olculuyor -> tek taban.
        ticker_price = _ticker_price(sym)
        base_price = ticker_price if ticker_price else price
        if ticker_price and price > 0:
            divergence = abs(ticker_price - price) / price * 100
            if divergence > TICKER_DIVERGENCE_WARN_PCT:
                logger.warning(
                    "[monitoring] ticker/aday fiyat ayrisimi %.1f%%: %s ticker=%s aday=%s",
                    divergence, sym, ticker_price, price)
    if base_price <= 0:
        base_price = price
    expected_price = base_price * (1 + target / 100) if base_price > 0 else 0.0
    detected_at = time.time()
    horizon = int(c.get("horizon_minutes", 5) or 5)
    ml_prob = c.get("ml_hit_probability")
    ml_pct_str = f" | ML %{ml_prob * 100:.0f}" if ml_prob is not None else ""
    message = (
        f"🎯 {sym} | Skor: {score:.1f} | Potansiyel: +%{target:g} ({horizon}dk){ml_pct_str} | "
        f"Anlık: {base_price:.6f} TRY | Beklenen: {expected_price:.6f} TRY"
    )
    return {
        "symbol": sym,
        "message": message,
        "title": f"🎯 {sym} +%{target:g} potansiyel{ml_pct_str}",
        "url": f"/charts?symbol={sym}",
        "tag": f"monitoring-{sym}",
        "detected_at": detected_at,
        "score": score,
        "target_pct": target,
        "price": base_price,
        "expected_price": expected_price,
        "horizon_minutes": horizon,
        "mode": c.get("mode"),
        "horizon": horizon,
        "ml_hit_probability": ml_prob,
        "ml_target_pct": c.get("ml_target_pct"),
        # A4: ödül/risk oranı ve dayanağı backend'den yayınlanır. Frontend
        # kendi SL sabitini varsaymasın (kalibrasyon tek kaynaktan gelsin).
        "rr": round(_rr_ratio(target), 3) if _rr_ratio(target) is not None else None,
        "sl_pct": float(getattr(config, "MONITORING_RR_SL_PCT", 3.0) or 0.0),
        # A3: satırın yazıldığı ölçek sürümü + cap. Okuma tarafı bu etiketle
        # doğru haritayı uygular (etiket yoksa kayıt lineer kabul edilir).
        "norm_version": MONITORING_SCORE_NORM_VERSION,
        "norm_cap": float(getattr(config, "MONITORING_SCORE_NORM_CAP", 2000) or 0),
        "settings_applied": {
            "min_score": settings.get("min_score"),
            "min_target_pct": settings.get("min_target_pct"),
        },
    }


def _row_norm_cap(row: dict) -> float:
    """Satırın normalize edildiği cap'i çöz (M1/P1 — R2-03).

    Opsiyonel `norm_cap` alanı (başka bir ajan `database.py`'ye ekliyor) varsa
    o kullanılır; yoksa/geçersizse güncel `MONITORING_SCORE_NORM_CAP`. Kolonun
    VAR OLMASI gerekmez — alan yoksa geriye dönük davranış aynen sürer.
    """
    raw_cap = row.get("norm_cap")
    if raw_cap not in (None, ""):
        try:
            cap = float(raw_cap)
            if cap > 0:
                return cap
        except (TypeError, ValueError):
            pass
    return float(config.MONITORING_SCORE_NORM_CAP)


def _row_norm_version(row: dict) -> int | None:
    """Satırın yazıldığı panel ölçek sürümü (A3). Yoksa None → A3 öncesi (lineer)."""
    raw_version = row.get("norm_version")
    if raw_version in (None, ""):
        return None
    try:
        return int(float(raw_version))
    except (TypeError, ValueError):
        return None


def _stored_panel_score(row: dict) -> float:
    """DB'deki score değerini panel (0-100) ölçeğine getirir.

    MONITORING_SCORE_NORM_SINCE sonrası kayıtlar zaten panel skorudur ve
    aynen kullanılır; öncesindeki kayıtlar ham velocity_score olduğundan tek
    kez normalize edilir. Kayda kaydı geçen skora tekrar normalize uygulamak
    (çift dönüşüm) eşiği fiilen 0.4×min_score'a indirdiği için düzeltildi
    (2026-09-04 teşhis).

    M1/P1 (R2-03): satırda opsiyonel `norm_cap` varsa (yazım anındaki cap)
    normalize bu cap ile yapılır; yoksa güncel cap'e düşülür. Böylece eski
    kayıtlar bugünkü cap ile yanlış yeniden ölçeklenmez.

    A3 (2026-09-14): SINCE sonrası kayıtlar PANEL değeri taşır ama HANGİ ölçekte
    yazıldıkları `norm_version` ile ayrılır. Satırın sürümü aktif sürümden farklıysa
    (veya etiket yoksa = A3 öncesi lineer) ve `raw_score` mevcutsa değer AKTİF
    haritayla yeniden hesaplanır — böylece rapor/eşik karşılaştırması tek ölçekte
    yapılır. Ham skor yoksa (kırpılmış lineer değer geri alınamaz) eski değer
    olduğu ölçekte bırakılır; bu bilinçli bir "en iyi çaba" sınırıdır.
    """
    try:
        detected = float(row.get("detected_at") or 0)
    except (TypeError, ValueError):
        detected = 0.0
    if detected and detected < float(config.MONITORING_SCORE_NORM_SINCE):
        # Eski (yeni 0-100 formülü öncesi) ham skorları cap'e göre bir kez
        # panel ölçeğine çevir. Yeni kayıtlarda skor zaten 0-100'dür.
        # NOT: bu kayıtlar yazıldıkları LİNEER ölçekte yorumlanır (satırın kendi
        # norm_cap'i ile); A3 haritası bunlara uygulanmaz.
        try:
            raw = float(row.get("score") or 0)
        except (TypeError, ValueError):
            raw = 0.0
        cap = _row_norm_cap(row)
        return round(max(0.0, min(100.0, 100.0 * raw / cap)), 1) if cap > 0 else round(max(0.0, min(100.0, raw)), 1)
    # A3: farklı ölçek sürümüyle yazılmış panel değeri → ham varsa aktif haritayla yeniden hesapla.
    if _row_norm_version(row) != MONITORING_SCORE_NORM_VERSION:
        raw_score = row.get("raw_score")
        if raw_score is not None:
            return _panel_from_raw(raw_score)
    try:
        return float(row.get("score") or 0)
    except (TypeError, ValueError):
        return 0.0


async def _record_history(entries):
    """Bildirim geçmişini DB'ye kaydet (uygulama kapalıyken gönderilenler dahil)."""
    try:
        await database.save_monitoring_notifications(entries)
    except Exception as exc:
        logger.warning("monitoring bildirim geçmişi kaydedilemedi: %s", exc)


async def _notify(candidates_list, settings) -> list:
    """Eşikleri geçen adaylar için bildirim üret ve web push gönder.

    Aynı sembol için sonuçlanmamış (BEKLİYOR) bildirim varsa yeni bildirim
    oluşturulmaz; mevcut bildirim güncellenir (hedef, skor, fiyat).
    Sadece önceki bildirim sonuçlanmışsa (TAMAMEN/BASARISIZ) veya ufuk süresi
    dolmuşsa yeni bildirim oluşturulur.
    """
    if not settings.get("enabled", True):
        return []
    # Tek eşik: aday kapısı HAM velocity_score üzerinden (M1/P0 — R2-01/R2-02/R3-01).
    # Panel (0-100) yalnızca gösterim ölçeğidir; cap değişince kapı kaymaz.
    min_raw = _effective_min_raw_score(settings)
    quiet = _in_quiet_hours(settings)
    # F-07: `now` duvar saati — KALICI/yayınlanan alanlar (detected_at,
    # pending_targets.set_at, DB horizon karşılaştırması) buna bağlı.
    now = time.time()
    # F-07: cooldown GÖRELİ ölçüm — monotonik saat. `notified_symbols` BELLEKTE
    # monotonik tutulur (kalıcılık sınırında duvar saatine çevrilir). Duvar saati
    # NTP adımıyla sıçrayınca tüm sembollerin cooldown'u aynı anda doluyordu.
    now_mono = time.monotonic()
    notified = []
    new_entries = []     # Yeni bildirimler
    # N+1 önlemi: aday sembollerinin BEKLİYOR kayıtlarını tek toplu sorguyla çek
    # (2026-09-05). Eşik altı adaylar pending kontrolüne girmez; yine de tüm
    # aday setini sorgulamak tek DB round-trip'idir. (Kopyalanmış ikinci yorum
    # bloğu kaldırıldı — küçük temizlik.)
    try:
        _t0 = time.time()
        pending_by_symbol = await database.get_pending_monitoring_notifications(
            [str(c.get("symbol", "") or "").upper() for c in candidates_list])
        _t1 = time.time()
        _db_lat = (_t1 - _t0) * 1000
        _monitoring_state.setdefault("_db_latencies", []).append(_db_lat)
        _monitoring_state["_db_latencies"] = _monitoring_state["_db_latencies"][-20:]
    except Exception as exc:
        logger.warning("monitoring pending toplu sorgu hatasi: %s", exc)
        pending_by_symbol = {}
    for c in candidates_list:
        sym = str(c.get("symbol", "") or "").upper()
        # normalize_score'a geçilir (2026-09-04 teşhis). upside_rank yalnızca
        # SIRALAMA anahtarıdır (dk-başı yükseliş × kalite × mikro-yapı).
        raw = float(c.get("velocity_score", 0) or 0)
        score = normalize_score(raw)
        target = float(c.get("target_pct") or 2.0)
        min_target = float(settings.get("min_target_pct") or 0)
        # M1/P0: kapı HAM skoru karşılaştırır (panel değil).
        if not sym or raw < min_raw or (min_target > 0 and target < min_target):
            continue
        # Bu sembol icin ufku dolmamis (sonucu bekleyen) bildirim var mi kontrol et.
        # Ufuk + 2 dk tolerans dolmussa bildirim sonuclanmis sayilir; aksi halde
        # ayni kayit guncellenir. (monitoring_notifications'ta status kolonu yok;
        # bekliyor tanimi okuma tarafindaki window_closed ile ayni olmalidir.)
        horizon_min = int(c.get("horizon_minutes", 5) or 5)
        existing_pending = pending_by_symbol.get(sym)
        if existing_pending and (
            now - float(existing_pending.get("detected_at") or 0)
            < (int(existing_pending.get("horizon_minutes") or horizon_min) + 2) * 60
        ):
            # Mevcut BEKLIYOR bildirimi guncelle (detected_at korunur); ML alanlari
            # da guncellenir (aksi halde guncelleme yolunda kaybolurdu, 2026-09-04).
            # Giris fiyati ILK bildirim anindaki fiyat olarak SABIT kalir (2026-09-04
            # kullanici karari): hedef fiyati son taramanin hedef yuzdesiyle ILK
            # giris fiyatindan yeniden hesaplanir — kullanici ilk giris + guncel
            # hedefi aynen takip edebilir (grafik cizgileri de bu iki seviyeyi
            # gosterir).
            first_price = float(existing_pending.get("price") or 0) or float(c.get("price", 0) or 0)
            # Ufuk daralmasın: bildirim SON ufuk süresi dolana kadar takipte kalır;
            # 5dk taraması 15dk bildirimin penceresini kısaltamaz (2026-09-04).
            horizon_keep = max(int(existing_pending.get("horizon_minutes") or 0), horizon_min)
            await database.update_monitoring_notification(
                existing_pending["id"],
                score=score,
                target_pct=target,
                price=first_price,
                expected_price=first_price * (1 + target / 100),
                horizon_minutes=horizon_keep,
                mode=c.get("mode"),
                ml_target_pct=c.get("ml_target_pct"),
                ml_hit_probability=c.get("ml_hit_probability"),
            )
            # Eski kayitlar kalir - sinyal tarihcesi icin
            # Bildirim olarak da ekle (push için)
            notif = _build_notification(sym, c, settings, first_price=first_price)
            # B2: `detected_at` DB kaydındaki İLK tespit zamanıyla eşitlenir;
            # `_build_notification` taze zaman üretiyordu — sessiz saat kuyruğuna
            # düşerse TTL hesabı gerçek yaşından uzun ömür verecekti.
            orig_detected = float(existing_pending.get("detected_at") or 0)
            if orig_detected > 0:
                notif["detected_at"] = orig_detected
            notif["id"] = existing_pending["id"]
            notif["updated"] = True
            notified.append(notif)
            # Güncellenen bildirimin streak'i temizlenir (bildirim zaten aktif)
            _monitoring_state["candidate_streak"].pop(sym, None)
            continue
        # Debounce: fast-lane altındaki adaylar N ardışık taramada aday kalmalı
        # (tek-tarama gürültüsünü keser). Yüksek skor hızlı pump'ta gelir —
        # fast-lane (>= MONITORING_FAST_LANE_SCORE) beklemeden geçer.
        streak = int(_monitoring_state["candidate_streak"].get(sym, 0)) + 1
        fast_lane = score >= float(config.MONITORING_FAST_LANE_SCORE)
        if not fast_lane and streak < config.MONITORING_DEBOUNCE_SCANS:
            _monitoring_state["candidate_streak"][sym] = streak
            continue
        _monitoring_state["candidate_streak"][sym] = streak
        # Kısa vadeli soğama (F-07: monotonik ölçüm → duvar saati adımına dayanıklı)
        last_sent = _monitoring_state["notified_symbols"].get(sym)
        if last_sent is not None and now_mono - last_sent < NOTIFY_COOLDOWN_SEC:
            continue
        # Beklenen fiyata ulaşana kadar aynı sembolü tekrar bildirme
        pending = _monitoring_state["pending_targets"].get(sym)
        if pending:
            horizon_sec = int(pending.get("horizon_minutes", 5) + 2) * 60
            if now - float(pending.get("set_at", 0)) < horizon_sec:
                continue
            _monitoring_state["pending_targets"].pop(sym, None)
        # D-07: fiyat DEGISTI mi? Zaman kapıları doldu ama fiyat aynıysa
        # bu "yeni sinyal" değil, aynı sinyalin tekrarıdır (donmuş fiyat /
        # likit olmayan sembol). Taban fiyat aynı kuraldan: taze ticker,
        # yoksa adayın kendi fiyatı (D-05 ile aynı tek taban).
        cand_px = float(c.get("price") or 0)
        tick_px = _ticker_price(sym)
        base_px = tick_px if tick_px else cand_px
        last_px = float(_monitoring_state["notified_prices"].get(sym) or 0)
        if last_px > 0 and base_px > 0 and (
                abs(base_px - last_px) / last_px * 100 < MONITORING_REFIRE_MIN_MOVE_PCT):
            _monitoring_state["refire_blocked"] = int(_monitoring_state.get("refire_blocked", 0)) + 1
            continue
        # A4: R/R kapisi — dusuk risk/odul adayi yalnizca YENI bildirimde
        # engellenir (mevcut BEKLIYOR bildirim guncellenmesi etkilenmez).
        # Sayaç kaliibrasyon icin tutulur: "kac aday bastirildi" gorunur olmali.
        if _rr_gate_blocks(base_px, float(c.get("target_pct") or 0) or 0.0):
            _monitoring_state["rr_blocked"] = int(_monitoring_state.get("rr_blocked", 0)) + 1
            continue
        # A5: MACD-teyitli histerezis — skor yukselmedigi ve MACD teyidi zayif
        # oldugunda yeniden bildirim basma. Anahtar SETTINGS'ten okunur (admin
        # panelinden kapatilabilir); settings'te yoksa config varsayilanina duser.
        if bool((settings or {}).get("macd_refire_gate",
                                     getattr(config, "MONITORING_MACD_REFIRE_GATE", True))):
            _ns = _monitoring_state.setdefault("notified_scores", {})
            prev_score = _ns.get(sym)
            macd_strong = bool(c.get("macd_bullish") or c.get("macd_rising"))
            if prev_score is not None and not macd_strong and score <= float(prev_score):
                continue
        notif = _build_notification(sym, c, settings)
        notif["updated"] = False
        new_entries.append(notif)
        notified.append(notif)
        _monitoring_state["notified_symbols"][sym] = now_mono
        _monitoring_state.setdefault("notified_scores", {})[sym] = score
        if base_px > 0:
            _monitoring_state["notified_prices"][sym] = base_px
        _monitoring_state["candidate_streak"].pop(sym, None)
        expected_price = float(notif.get("expected_price") or 0)
        horizon_minutes = int(c.get("horizon_minutes") or 5)
        if expected_price > 0:
            _monitoring_state["pending_targets"][sym] = {
                "expected": expected_price,
                "horizon_minutes": horizon_minutes,
                "set_at": now,
            }
        if len(_monitoring_state["notified_symbols"]) > 500:
            for k in sorted(_monitoring_state["notified_symbols"], key=_monitoring_state["notified_symbols"].get)[:-250]:
                _monitoring_state["notified_symbols"].pop(k, None)
        # D-07: fiyat geçmişi de sınırlı (sonsuz büyüme yok).
        if len(_monitoring_state["notified_prices"]) > 500:
            for k in list(_monitoring_state["notified_prices"])[:-250]:
                _monitoring_state["notified_prices"].pop(k, None)
    # Yeni bildirimleri DB'ye kaydet — M1/P1 (R2-06/R2-19): `sent_via_push` artık
    # GERÇEK teslimi yansıtır. Varsayılan False (henüz push denenmedi/teslim
    # edilmedi); yalnızca push gerçekten ulaşırsa mark_monitoring_push_sent ile
    # True'ya çevrilir. "sessiz saat değil" artık "gönderildi" DEMEK DEĞİL.
    if new_entries:
        for n in new_entries:
            n["sent_via_push"] = False
        _s_t0 = time.time()
        # M1/P2 (R2-15): ölü `_record_history` artık burada KULLANILIYOR (tek yol).
        await _record_history(new_entries)
        _s_t1 = time.time()
        _db_lat = (_s_t1 - _s_t0) * 1000
        _monitoring_state.setdefault("_db_latencies", []).append(_db_lat)
        _monitoring_state["_db_latencies"] = _monitoring_state["_db_latencies"][-20:]
    # Sessiz saat bilgisi bildirim nesnesine işaretlenir (UI geçmişte görür).
    for n in notified:
        n["quiet_hours"] = bool(quiet)
    # B3: oturum geçmişi TÜM bildirimleri içersin (önceden yalnız yeniler
    # alınıyordu; "güncellendi" bildirimleri geçmişte görünmüyordu).
    if notified:
        _monitoring_state["history"] = (notified + _monitoring_state["history"])[:HISTORY_LIMIT]
    # B5: Push gönderimi, WS yayını ve otonom paper denemeleri STATE KİLİDİ
    # DIŞINA taşındı (`_deliver_scan_notifications`) — ağırlıklı ağ I/O'su kilit
    # altında GET /state ve GET /scan isteklerini saniyelerce blokluyordu.
    return notified


async def _deliver_scan_notifications(notified: list) -> None:
    """Bildirim teslimi: push gönderimi, erteleme, WS yayını, otonom paper.

    MUTLAKA `_locked_state()` DIŞINDA çağrılmalı (B5): web push ağ I/O'su ve
    auto_paper DB/plan işlemleri state kilidini uzun süre tutmamalıdır.

    Push yalnızca YENI bildirimlere gönderilir (güncellemeler her turda
    tetiklenmesin diye spam koruması); WS yayını ise B3 ile TÜM bildirimleri
    (yeni + güncelleme) kapsar.
    """
    if not notified:
        return
    new_notifs = [n for n in notified if not n.get("updated")]
    quiet = bool(notified[0].get("quiet_hours"))
    vapid_configured = bool(os.getenv("VAPID_PRIVATE_KEY", "").strip())
    # BİRLEŞİK RADAR (Aşama 2): tek tip bildirim. Radar push'u `radar-{sym}` tag'i
    # ile gider ve bu turda push edilen semboller kaydedilir — yükseliş teslimatı
    # aynı sembol için İKİNCİ push atmaz.
    unified = await _radar_unified_enabled()
    if unified:
        for notif in new_notifs:
            sym = str(notif.get("symbol") or "").upper()
            notif["tag"] = f"radar-{sym}"
            notif["sources"] = ["velocity"]
            notif["unified"] = True
            if sym:
                _unified_pushed_symbols.add(sym)
    if new_notifs and not quiet and vapid_configured:
        for notif in new_notifs:
            ok = await _send_push(notif)
            notif["push_success"] = ok
            if ok:
                # M1/P1 (R2-06): gerçek teslim → DB etiketi True.
                notif["sent_via_push"] = True
                nid = notif.get("id")
                if nid:
                    try:
                        await database.mark_monitoring_push_sent(nid)
                    except Exception as exc:
                        logger.warning("push etiketi güncellenemedi %s: %s", nid, exc)
            else:
                logger.warning("Monitoring push gönderilemedi: %s", notif.get("symbol"))
    elif new_notifs and not quiet:
        # VAPID yok: push atlanır, bildirim kaydına işlenir
        logger.info("Monitoring push atlandı: VAPID_PRIVATE_KEY yapılandırılmamış (%d bildirim)", len(new_notifs))
        for notif in new_notifs:
            notif["push_success"] = False
    elif new_notifs and quiet:
        # Sessiz saat: push'u ertele — saat bitince _flush_deferred_push gönderir.
        logger.info("Monitoring: sessiz saatlerde %d bildirim push kuyruğuna alındı", len(new_notifs))
        for notif in new_notifs:
            _deferred_push.append(notif)
    # Otonom Paper Trade: sadece YENI bildirimlerde (güncellemelerde pozisyon
    # zaten açık veya hiç açılmamış; güncelleme her turda tetiklenir — gereksiz
    # sorgu + hesaplamayı önlemek için yok sayılır, 2026-09-06).
    try:
        from app.routers.auto_paper import try_open_from_notification
        for notif in new_notifs:
            try:
                await try_open_from_notification(notif)
            except Exception as exc:
                logger.debug("auto_paper %s denemesi: %s", notif.get("symbol"), exc)
    except ImportError:
        pass
    except Exception as exc:
        logger.warning("auto_paper toplu deneme hatası: %s", exc)
    try:
        await ws_manager.broadcast({"type": "monitoring_alert", "data": notified})
    except Exception as exc:
        logger.warning("Monitoring WS broadcast hatasi: %s", exc)


# ---------------------------------------------------------------------------
# YÜKSELİŞ SİNYALLERİ (R3, 2026-09-14)
#
# MACD MONITOR'ün kanıtlanmış erken-öncüleri (`app/rising_signals.py`) radara
# bağlanır. Tespit sunucu tarafındadır (eskiden istemci `/api/macd-monitor`
# yanıtını yeniden yorumluyordu → bildirim/kanıt yoktu).
#
# Teslim zinciri radarın kardeşidir: push → WS `rising_alert` (global dialog) →
# otonom paper. Sessiz saat/erteleme ve `sent_via_push` dürüstlüğü AYNEN korunur.
# ---------------------------------------------------------------------------
RISING_LABEL = {
    "erken": "ERKEN SİNYAL (YAKLAŞIYOR)",
    "yukselis": "YÜKSELİŞ EĞİLİMİ",
}


async def _push_health_safe() -> dict:
    """Push sağlığı — panelde GÖRÜNÜR olsun (2026-09-16 denetimi).

    `subscribers == 0` iken backend `VAPID_PRIVATE_KEY` yapılandırılmış olsa bile
    tek bir push gitmez; bu sessiz arıza panelde "push yok" olarak görünür.
    Sayaç okunamazsa state yanıtı BOZULMAZ (0 döner).

    2026-09-16 (yanlış alarm düzeltmesi): `vapid_public_key` eklendi. Tarayıcının
    abone olurken kullandığı anahtarın backend'in private anahtarıyla eşleşip
    eşleşmediği YALNIZCA iki değeri birden görebilen tarafta anlaşılır; frontend
    kendi `NEXT_PUBLIC_VAPID_PUBLIC_KEY` değerini bununla karşılaştırır. Böylece
    "push sessizce 401 alıyor" durumu panelde ayırt edilebilir hale gelir.
    """
    try:
        subscribers = int(await database.count_push_subscriptions() or 0)
    except Exception as exc:
        logger.debug("push sağlığı okunamadı: %s", exc)
        subscribers = 0
    try:
        from app.vapid import diagnose_vapid
        diag = diagnose_vapid()
        vapid_configured = bool(diag["configured"])
        vapid_public_key = diag["effective_public_key"]
    except Exception as exc:
        logger.debug("vapid teşhisi okunamadı: %s", exc)
        vapid_configured = bool(os.getenv("VAPID_PRIVATE_KEY", "").strip())
        vapid_public_key = None
    return {
        "backend_vapid_configured": vapid_configured,
        "subscribers": subscribers,
        # Tarayıcının abone olurken kullanması GEREKEN public anahtar
        # (private'dan türetilir; frontend kendi anahtarıyla karşılaştırır).
        "vapid_public_key": vapid_public_key,
    }


def _rising_summary_safe() -> dict | None:
    """Yükseliş özeti + panelin gösterdiği fiyat/TP/SL bilgisi.

    Fiyat burada eklenir çünkü `rising_signals` (tek doğruluk kaynağı) `monitoring`i
    import EDEMEZ (döngü olurdu); fiyat zaten bu modülün taze-ticker kuralıyla
    (`_ticker_price`) alınır. Hata durumunda state yanıtı BOZULMAZ (None döner).
    """
    try:
        from app import rising_signals
        payload = rising_signals.rising_summary_payload()
    except Exception as exc:
        logger.debug("rising özeti alınamadı: %s", exc)
        return None
    try:
        sl_pct = float(getattr(config, "MONITORING_RR_SL_PCT", 3.0) or 0.0)
        for cand in payload.get("candidates") or []:
            price = _ticker_price(str(cand.get("symbol") or ""))
            target = float(cand.get("target_pct") or 0)
            cand["price"] = float(price) if price else None
            cand["sl_pct"] = sl_pct
            cand["rr"] = round(target / sl_pct, 3) if (sl_pct > 0 and target > 0) else None
    except Exception as exc:
        logger.debug("rising fiyat zenginleştirme: %s", exc)
    return payload


def _build_rising_notification(candidate: dict, price: float) -> dict:
    """Yükseliş adayını `_send_push` + `try_open_from_notification` zarfına çevir.

    Zarf alanları bilinçli olarak monitoring bildirimiyle AYNI tutulur
    (`auto_paper.try_open_from_notification` değiştirilmeden kullanılabilsin).
    """
    symbol = str(candidate.get("symbol") or "").upper()
    kind = str(candidate.get("kind") or "erken")
    label = RISING_LABEL.get(kind, "YÜKSELİŞ SİNYALİ")
    signals = candidate.get("signals") or {}
    target = float(candidate.get("target_pct") or 2.0)
    score = float(candidate.get("score") or 0.0)
    proximity = signals.get("proximity")
    prox_txt = ""
    if isinstance(proximity, (int, float)):
        prox_txt = f" · zirveye yakınlık %{round(float(proximity) * 100)}"
    expected_price = price * (1 + target / 100) if price > 0 else 0.0
    now = time.time()
    message = (
        f"📈 {symbol} | {label} | Skor {score:.0f}{prox_txt} | "
        f"Anlık: {price:.6f} TRY | Beklenen: {expected_price:.6f} TRY"
    )
    return {
        "symbol": symbol,
        "message": message,
        "title": f"📈 {symbol} · {label}",
        "url": f"/charts?symbol={symbol}",
        "tag": f"rising-{symbol}",
        "detected_at": now,
        "score": score,
        "target_pct": target,
        "price": price,
        "expected_price": expected_price,
        "horizon_minutes": 5,
        "mode": "yukselis",
        "kind": kind,
        "signals": signals,
        "early_score": candidate.get("early_score"),
        "proximity": proximity,
        "green": candidate.get("green"),
        "strength": candidate.get("strength"),
        # Aynı saat kovasında aynı sembol için TEK otonom giriş (churn koruması
        # `auto_paper` tarafında `notification_key` ile uygulanır).
        "notification_key": f"rising-{kind}-{symbol}-{int(now // 3600)}",
        "updated": False,
        "source": "rising",
    }


async def _rising_deliver(notified: list) -> None:
    """Yükseliş teslimi: push + WS `rising_alert` + otonom paper.

    MUTLAKA state kilidi DIŞINDA çağrılır (push ağ I/O'su + auto_paper DB işi).
    """
    if not notified:
        return
    quiet = bool((notified[0] or {}).get("quiet_hours"))
    vapid_configured = bool(os.getenv("VAPID_PRIVATE_KEY", "").strip())
    unified = await _radar_unified_enabled()

    if unified:
        # TEK TİP BİLDİRİM: radar bu turda aynı sembolü ZATEN push ettiyse ikinci
        # push YOK. Yükseliş ya "birincil" push olur (radar tetiklenmediyse) ya da
        # bastırılır (radar push'u zaten aynı sembolü kapsadı). Her iki durumda da
        # tag tek şemaya iner: `radar-{sym}`.
        primary: list = []
        suppressed: list = []
        for notif in notified:
            sym = str(notif.get("symbol") or "").upper()
            notif["tag"] = f"radar-{sym}"
            notif["sources"] = ["rising"]
            notif["unified"] = True
            if sym in _unified_pushed_symbols:
                notif["push_success"] = False
                notif["suppressed_by_unified"] = True
                suppressed.append(notif)
            else:
                primary.append(notif)
        if vapid_configured and not quiet:
            for notif in primary:
                ok = await _send_push(notif)
                notif["push_success"] = ok
                if ok:
                    notif["sent_via_push"] = True
                alert_id = notif.get("alert_id")
                if alert_id:
                    try:
                        await database.mark_rising_alert_notified(alert_id, bool(ok))
                    except Exception as exc:
                        logger.debug("rising bildirim etiketi %s: %s", alert_id, exc)
        elif quiet:
            for notif in primary:
                _deferred_push.append(notif)
        # Bastırılanlar: push denenmedi → `sent_via_push=False` dürüstçe yazılır.
        for notif in suppressed:
            alert_id = notif.get("alert_id")
            if alert_id:
                try:
                    await database.mark_rising_alert_notified(alert_id, False)
                except Exception as exc:
                    logger.debug("rising bastırma etiketi %s: %s", alert_id, exc)
    else:
        # ESKİ DAVRANIŞ (bayrak kapalı): ayrı push + ayrı `rising_alert` WS tipi.
        if vapid_configured and not quiet:
            for notif in notified:
                ok = await _send_push(notif)
                notif["push_success"] = ok
                if ok:
                    notif["sent_via_push"] = True
                alert_id = notif.get("alert_id")
                if alert_id:
                    try:
                        await database.mark_rising_alert_notified(alert_id, bool(ok))
                    except Exception as exc:
                        logger.debug("rising bildirim etiketi %s: %s", alert_id, exc)
        elif quiet:
            for notif in notified:
                _deferred_push.append(notif)
        else:
            logger.info("Yükseliş push atlandı: VAPID_PRIVATE_KEY yapılandırılmamış (%d sinyal)", len(notified))
            for notif in notified:
                notif["push_success"] = False
                alert_id = notif.get("alert_id")
                if alert_id:
                    try:
                        await database.mark_rising_alert_notified(alert_id, False)
                    except Exception as exc:
                        logger.debug("rising bildirim etiketi %s: %s", alert_id, exc)
    # Otonom paper: yalnız yeni sinyaller; skor eşiği GEÇİLMELİ ve anahtar AÇIK.
    # BİLDİRİM bastırılsa bile OTONOM İŞLEM AÇILMAYA DEVAM EDER (ikisi ayrı).
    if bool(getattr(config, "RISING_AUTONOMOUS_ENABLED", True)):
        min_score = float(getattr(config, "RISING_AUTO_MIN_SCORE", 70) or 0)
        try:
            from app.routers.auto_paper import try_open_from_notification
            for notif in notified:
                if float(notif.get("score") or 0) < min_score:
                    continue
                try:
                    opened = await try_open_from_notification(notif)
                except Exception as exc:
                    logger.debug("rising auto_paper %s: %s", notif.get("symbol"), exc)
                    continue
                if isinstance(opened, dict) and opened.get("trade_id") and notif.get("alert_id"):
                    try:
                        await database.mark_rising_alert_trade(int(notif["alert_id"]),
                                                               int(opened["trade_id"]))
                    except Exception as exc:
                        logger.debug("rising işlem bağı: %s", exc)
        except ImportError:
            pass
        except Exception as exc:
            logger.warning("rising auto_paper toplu deneme hatası: %s", exc)
    if unified:
        # Tek tip: yalnızca birincil yükseliş bildirimleri `monitoring_alert`
        # kanalından gider (radar modalı zaten bunu dinler). Bastırılanlar radar'ın
        # kendi `monitoring_alert` yayınında mevcut → ayrı `rising_alert` YOK.
        if primary:
            try:
                await ws_manager.broadcast({"type": "monitoring_alert", "data": primary})
            except Exception as exc:
                logger.warning("Yükseliş birleşik WS broadcast hatası: %s", exc)
    else:
        try:
            await ws_manager.broadcast({"type": "rising_alert", "data": notified})
        except Exception as exc:
            logger.warning("Yükseliş WS broadcast hatası: %s", exc)


async def _run_rising_scan() -> dict:
    """Yükseliş taraması: tespit → fiyat → histerezis → kanıt → bildirim.

    Dönüş: {"detected": n, "notified": n, "skipped_price": n, "stale": bool}
    """
    from app import rising_signals

    summary = {"detected": 0, "notified": 0, "skipped_price": 0, "stale": False}
    if not bool(getattr(config, "RISING_SIGNALS_ENABLED", True)):
        return summary
    settings = await get_user_notification_settings()
    if not bool(settings.get("enabled", True)):
        return summary
    candidates = rising_signals.detect_rising_candidates()
    summary["detected"] = len(candidates)
    if not candidates:
        summary["stale"] = rising_signals.rising_is_stale()
        return summary
    quiet = _in_quiet_hours(settings)
    now = time.monotonic()
    max_per_scan = max(1, int(getattr(config, "RISING_MAX_PER_SCAN", 3) or 3))
    notify_enabled = bool(getattr(config, "RISING_NOTIFY_ENABLED", True))
    notified: list = []
    for candidate in candidates:
        symbol = str(candidate.get("symbol") or "").upper()
        if not symbol:
            continue
        # Histerezis: AYNI öncü kümesi sürüyorsa yeni bilgi yoktur → ne kayıt ne
        # bildirim (aksi halde kanıt tablosu her turda şişerdi).
        prev_key = rising_signals.last_key(symbol)
        cur_key = rising_signals.signal_key(candidate)
        if prev_key is not None and not rising_signals.rising_edge_trigger(prev_key, cur_key):
            continue
        is_first_observation = prev_key is None
        # Fiyat: bayat ticker ile bildirim/beklenti üretme (radar ile AYNI kural).
        price = _ticker_price(symbol) if notify_enabled else None
        if notify_enabled and (not price or price <= 0):
            summary["skipped_price"] += 1
            continue
        # Sessiz arm (ilk gözlem): restart fırtınasını engelle ama sinyali KAYDET —
        # panel ve rapor bundan beslenir, yalnız push/dialog yapılmaz.
        fire = notify_enabled and not is_first_observation and rising_signals.should_fire(candidate, now)
        if fire and len(notified) >= max_per_scan:
            continue
        notif = _build_rising_notification(candidate, float(price)) if notify_enabled else None
        if notif is not None:
            notif["quiet_hours"] = bool(quiet)
        # Kanıt katmanı: bildirimden ÖNCE yazılır ki her sinyal ölçülebilir olsun.
        alert_id = await database.record_rising_alert({
            **candidate,
            "price": float(price) if notify_enabled else None,
            "expected_price": notif["expected_price"] if notif else None,
            "created_at": time.time(),
            "notified": bool(fire),
        })
        if not fire:
            # Sessiz arm: durumu ilerlet (cooldown BAŞLATMA) ki cooldown'sız
            # ilk turda birikme olmasın.
            if is_first_observation:
                rising_signals.observe(candidate)
            continue
        rising_signals.mark_fired(candidate, now)
        if notif is None:
            continue
        if alert_id:
            notif["alert_id"] = alert_id
        notified.append(notif)
    if notified:
        _monitoring_state["rising_notified"] = int(_monitoring_state.get("rising_notified", 0)) + len(notified)
        try:
            await _rising_deliver(notified)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Yükseliş teslimi: %s", exc)
    summary["notified"] = len(notified)
    return summary


def _check_pending_targets():
    """Beklenen fiyata ulaşan sembolleri tespit et ve pending listesinden çıkar.

    Her tarama turunda çağrılır: aday listesindeki sembollerin anlık fiyatı,
    kayıtlı expected_price'a eşit veya üstüyse hedefe ulaşılmış sayılır.
    Ufuk süresi + 2 mk tolerans dolduysa da temizlenir (timeout).
    """
    pending = _monitoring_state.get("pending_targets")
    if not pending:
        return
    now = time.time()
    resolved = []
    for sym, info in list(pending.items()):
        horizon_sec = int(info.get("horizon_minutes", 5) + 2) * 60
        set_at = float(info.get("set_at", 0))
        expired = now - set_at >= horizon_sec
        price = None
        # D-05: bayat ticker ile yanlis "hedefe ulasildi" uretme.
        try:
            price = _ticker_price(sym)
        except Exception:
            price = None
        expected = float(info.get("expected") or 0)
        hit = price is not None and price > 0 and expected > 0 and price >= expected
        if expired or hit:
            resolved.append(sym)
    for sym in resolved:
        _monitoring_state["pending_targets"].pop(sym, None)


def _risk_state_from_references() -> tuple[bool, bool]:
    """Piyasa rejimi: (risk_off, risk_off_unknown) — hafif yerel ölçüm.

    Referans semboller (BTC/ETH 1h) EMA25 üstündeyse yapıcı, değilse zayıf
    rejim katkısı sayılır. (B4: önceki kod `sum/25` hesaplayıp adına EMA
    diyordu — gerçekte SMA idi; aşağıda standart EMA hesabı uygulanır.)

    F-14: referanslardan hiçbirinde yeterli veri YOKSA rejim HESAPLANAMAZ →
    `risk_off` BİLİNMİYOR kabul edilir (fail-open, eşik DEĞİŞTİRİLMEZ). Eskiden
    boş veri `risk_score == 0` yapıp `risk_off=True` döndürüyordu; bu da eşiği
    sessizce +20 yükselterek ısınma sırasında radar listesini boşaltıyordu.
    """
    try:
        risk_score = 0
        refs = 0
        for ref in ("BTC_TRY", "ETH_TRY"):
            bars = market.get_ut_kline(ref.lower().replace("_", ""), "1h")
            closes = (bars or {}).get("closes") or []
            if len(closes) >= 25:
                refs += 1
                # B4: gerçek EMA25 — SMA (sum/25) ile karıştırılmıştı. Standart
                # alpha=2/(span+1); hesap, mevcut serinin son 100 barına
                # ısınmalı uygulanır (daha uzun geçmiş EMA'yı stabilize eder).
                span = 25
                alpha = 2.0 / (span + 1)
                ema25 = float(closes[-100]) if len(closes) >= 100 else float(closes[0])
                for close_val in closes[-99:] if len(closes) >= 100 else closes[1:]:
                    ema25 = float(close_val) * alpha + ema25 * (1 - alpha)
                # Fiyat EMA25 üstündeyse yapıcı/pozitif rejim katkısı.
                if float(closes[-1]) >= ema25:
                    risk_score += 1
        if refs == 0:
            return False, True
        return risk_score == 0, False
    except Exception:
        return False, True  # rejim hesaplanamazsa fail-open + BİLİNMİYOR


async def _run_scan() -> dict:
    """Tek tarama turu: 5dk + 15dk velocity taramalarını hibrit sıralamayla birleştirir.

    İzleme listesindeki semboller her turda top-gainer havuzuna zorunlu olarak
    eklenir (extra_symbols) — böylece izleme listesi "daha sık analiz edilen"
    listede kalır ve terfi/düşme kararı her turda tazelenir.

    Hibrit (2026-09-04): sembol başına chat upside-scout ile AYNI sıralama
    anahtarı (upside_rank = dk-başı hedef × hız skoru × kalite × mikro-yapı)
    kullanılır; açık pozisyonlu semboller aday listesinden elenir; her adayın
    5dk+15dk çift profili saklanır. RISK_OFF rejimde etkin eşik yükseltilir.
    """
    watch_symbols = sorted({w.get("symbol") for w in (_monitoring_state["last_watchlist"] or []) if w.get("symbol")})
    # F-16: 5dk ve 15dk taramaları AYNI havuzu bağımsız olarak tarar; seri
    # beklemek gecikmeyi ikiye katlıyordu. Eşzamanlı çalıştırılır (asyncio tek
    # thread olduğu için paylaşılan durumda yarış yok).
    scan5, scan15 = await asyncio.gather(
        detect_velocity_candidates({"limit": 10}, horizon_minutes=5, extra_symbols=watch_symbols),
        detect_velocity_candidates({"limit": 10}, horizon_minutes=15, extra_symbols=watch_symbols),
    )

    candidates5 = scan5.get("candidates", [])
    candidates15 = scan15.get("candidates", [])
    watchlist5 = scan5.get("watchlist", [])
    watchlist15 = scan15.get("watchlist", [])

    # Sıralama anahtarı: chat upside-scout ile ortak (journal touch oranları +
    # mikro-yapı çarpanı satırların içinde hazır: upside_rank_score hesaplar).
    touch_rates = await _journal_touch_rates()

    # Çift profil: sembol -> {"5": satır, "15": satır} (aday + izleme havuzundan)
    profiles_by_symbol: dict[str, dict[int, dict]] = {}
    for row in candidates5 + watchlist5:
        profiles_by_symbol.setdefault(str(row.get("symbol") or "").upper(), {})[5] = row
    for row in candidates15 + watchlist15:
        profiles_by_symbol.setdefault(str(row.get("symbol") or "").upper(), {})[15] = row

    def _with_profiles(row: dict) -> dict:
        sym = str(row.get("symbol") or "").upper()
        profs = profiles_by_symbol.get(sym) or {}
        row["profiles"] = {
            str(h): {"horizon_minutes": h,
                     "target_pct": r.get("target_pct"),
                     "velocity_score": r.get("velocity_score"),
                     "upside_rank": round(upside_rank_score(r, touch_rates), 2),
                     "passes": bool(r.get("passes")),
                     "block_reason": r.get("block_reason"),
                     "rsi": r.get("rsi"), "mfi": r.get("mfi"), "atr_pct": r.get("atr_pct"),
                     "m5_pattern_ok": r.get("m5_pattern_ok"), "leading_ok": r.get("leading_ok"), "volume_ratio": r.get("volume_ratio")}
            for h, r in profs.items()
        }
        row["upside_rank"] = round(upside_rank_score(row, touch_rates), 2)
        # Panel (0-100) skoru: arayüz ve liste filtresi ham velocity_score yerine
        # bunu gösterir; admin eşiği bu ölçekte kurgulanmış (2026-09-04).
        row["panel_score"] = normalize_score(row.get("velocity_score", 0))
        return row

    # Birleştir: sembol başına en yüksek upside_rank'li kayıt kalır
    all_candidates = {}
    for c in candidates5 + candidates15:
        sym = str(c.get("symbol") or "").upper()
        if not sym:
            continue
        _with_profiles(c)
        if sym not in all_candidates or c.get("upside_rank", 0) > all_candidates[sym].get("upside_rank", 0):
            all_candidates[sym] = c

    all_watchlist = {}
    for w in watchlist5 + watchlist15:
        sym = str(w.get("symbol") or "").upper()
        if not sym:
            continue
        _with_profiles(w)
        if sym in all_candidates:  # aday olan izleme listesinde kalmasın
            continue
        if sym not in all_watchlist or w.get("upside_rank", 0) > all_watchlist[sym].get("upside_rank", 0):
            all_watchlist[sym] = w

    # Açık pozisyonlu semboller bildirim adayı olmaz (bot zaten yönetiyor;
    # izleme listesinde görüntülenmeye devam edebilir).
    open_symbols = {str(s or "").upper() for s in (analyzer.positions or {})}
    filtered_candidates = {sym: c for sym, c in all_candidates.items() if sym not in open_symbols}

    # Aday olanlar izleme listesinden çıkar (zaten geçti)
    for sym in all_candidates:
        all_watchlist.pop(sym, None)
        _monitoring_state["watchlist_seen_at"].pop(sym, None)

    # İzlemeye alınanları işaretle
    now = time.time()
    for sym in all_watchlist:
        _monitoring_state["watchlist_seen_at"].setdefault(sym, now)

    # B1: izleme listesinden TAMAMEN düşen sembollerin seen_at kaydı budanır —
    # aksi halde sözlük (ve her taramada yazılan kalıcı JSON) sınırsız büyür.
    for sym in list(_monitoring_state["watchlist_seen_at"]):
        if sym not in all_watchlist:
            _monitoring_state["watchlist_seen_at"].pop(sym, None)

    # Rejim: RISK_OFF bayrağı — hafif yerel ölçüm (BTC/ETH 1h trend).
    # 2026-09-04: bayrağın eşikle ilişkisi kaldırıldı (çarpan yok); yalnızca
    # gözlem amaçlı API'de raporlanır. F-14: referans verisi yoksa BİLİNMİYOR.
    risk_off, risk_off_unknown = _risk_state_from_references()
    _monitoring_state["risk_off"] = risk_off
    _monitoring_state["risk_off_unknown"] = risk_off_unknown

    settings = await get_user_notification_settings()
    # M1/P0 (R2-01/R2-02/R3-01): aday kapısı HAM velocity_score ile karşılaştırılır —
    # panel skoru yalnızca GÖSTERİM ölçeğidir. Cap değişse bile kapı sessizce kaymaz.
    effective_min_raw_score = _effective_min_raw_score(settings)
    # Admin eşiği altındaki adaylar listede GÖSTERILMEZ (2026-09-04 kullanıcı
    # kararı; RISK_OFF çarpanı kaldırıldı — _effective_min_raw_score aynen uygulanır).
    # _notify aynı eşiği zaten uyguladığından bildirim davranışı değişmez; yalnız
    # radar listesi temiz kalır.
    candidates_list = sorted(
        (c for c in filtered_candidates.values()
         if float(c.get("velocity_score", 0) or 0) >= effective_min_raw_score),
        key=lambda x: x.get("upside_rank", 0), reverse=True)
    watchlist_list = sorted(all_watchlist.values(), key=lambda x: x.get("upside_rank", 0), reverse=True)

    # Bu turdaki aday kümesi: eşik altında kalan sembollerin debounce sayacı sıfırlanır
    current_candidate_syms = set(filtered_candidates)
    for sym in list(_monitoring_state["candidate_streak"]):
        if sym not in current_candidate_syms:
            _monitoring_state["candidate_streak"].pop(sym, None)

    # Beklenen fiyata ulaşan veya süresi dolan sembolleri serbest bırak
    _check_pending_targets()

    new_notifications = await _notify(candidates_list, settings)

    _monitoring_state["last_scan_at"] = now
    _monitoring_state["last_candidates"] = candidates_list
    _monitoring_state["last_watchlist"] = watchlist_list
    _monitoring_state["scan_count"] += 1
    await _persist_runtime_state()
    return {
        "settings": settings,
        "candidates": candidates_list,
        "watchlist": watchlist_list,
        "new_notifications": new_notifications,
    }


def _loop_is_active() -> bool:
    """Tarama döngüsü GERÇEKTEN canlı mı? (M1/P1 — R4-02)

    `_loop_task` yalnızca ilk başlatmada set edilir; süpervizör respawn ettikten
    sonra BAYAT (ölü) görevi göstermeye devam eder. Süpervizörün İSİM→canlı görev
    kaydı (`api_common.get_task`) respawn'da güncellendiği için asıl kaynak odur;
    geriye dönük olarak `_loop_task`'a düşülür.
    """
    task = get_task("monitoring-scan-loop")
    if task is None:
        task = _loop_task
    return task is not None and not task.done()


def _cached_scan_snapshot(settings: dict, *, cached: bool = True) -> dict:
    """Son tarama durumunun önbellek anlık görüntüsü (YAN ETKİSİZ)."""
    data_ready = bool(_monitoring_state.get("last_scan_at"))
    return {
        "paper_only": True,
        "cached": cached,
        "data_ready": data_ready,
        "system_startup": not data_ready,
        "scan_at": _monitoring_state["last_scan_at"],
        "scan_count": _monitoring_state["scan_count"],
        "candidates": _monitoring_state["last_candidates"],
        "watchlist": _monitoring_state["last_watchlist"],
        "history": _monitoring_state["history"][:20],
        "settings": settings,
        "risk_off": bool(_monitoring_state["risk_off"]),
        "risk_off_unknown": bool(_monitoring_state.get("risk_off_unknown", False)),
        **_threshold_fields(settings),
        "loop_active": _loop_is_active(),
    }


@router.get("/api/monitoring/scan")
async def monitoring_scan(request: Request = None):
    """SON TARAMA önbelleğini döndür — SALT OKUNUR (M1/P1 — R4-03/R4-13).

    Eski davranış: GET tam tarama + DB yazımı + web push + otonom paper pozisyon
    açıyordu (yan etkili, hız sınırsız GET). Artık GET HİÇBİR yan etki üretmez;
    taramayı tetiklemek için `POST /api/monitoring/scan` (admin) kullanılır.
    """
    # M1/P2 (R2-18): okuma state kilidi altında (F-15 uyumlu; scan kilidi ALINMAZ).
    async with _locked_state():
        settings = await get_user_notification_settings()
        return _cached_scan_snapshot(settings, cached=True)


@router.post("/api/monitoring/scan")
async def monitoring_scan_trigger(request: Request):
    """Taramayı ZORLA tetikle — YALNIZ admin, basit hız sınırı ile (R4-03).

    Kanonik tetikleyici budur; GET artık salt-okunur. `rate_limit` token-bucket
    aşımında 429 döner.
    """
    from app.api_common import require_admin as _require_admin, rate_limit
    _require_admin(request)
    if not rate_limit("monitoring_scan", rate_per_sec=1 / 20.0, burst=2):
        raise HTTPException(status_code=429, detail="Çok sık tarama — lütfen bekleyin")
    try:
        # F-15: REST tarama yolu `_locked_state()` de almalı — kilit SIRASI
        # döngüyle aynı (scan → state) ⇒ deadlock yok.
        async with _scan_lock:
            async with _locked_state():
                result = await _run_scan()
        # B5: push/WS/otonom paper teslimi state kilidi DIŞINDA — yavaş push
        # ağ I/O'su artık okuma uçlarını bloklamaz.
        try:
            await _deliver_scan_notifications(result["new_notifications"])
        except Exception as exc:
            logger.warning("monitoring bildirim teslimi (manuel tarama): %s", exc)
        async with _locked_state():
            last_scan = _monitoring_state.get("last_scan_at")
            next_in = max(0, int(SCAN_INTERVAL_SEC - (time.time() - float(last_scan)))) if last_scan else None
            return {
                "paper_only": True,
                "cached": False,
                "data_ready": True,
                "system_startup": False,
                "scan_at": _monitoring_state["last_scan_at"],
                "scan_count": _monitoring_state["scan_count"],
                "candidates": result["candidates"],
                "watchlist": result["watchlist"],
                "new_notifications": len(result["new_notifications"]),
                "notifications": result["new_notifications"],
                "history": _monitoring_state["history"][:20],
                "settings": result["settings"],
                "risk_off": bool(_monitoring_state["risk_off"]),
                "risk_off_unknown": bool(_monitoring_state.get("risk_off_unknown", False)),
                **_threshold_fields(result["settings"]),
                "loop_active": _loop_is_active(),
                # Frontend poll hizalaması bu alanı okur; POST yanıtı eksikti.
                "next_scan_in_sec": next_in,
            }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Monitoring scan failed: %s", exc)
        return {"paper_only": True, "cached": False,
                "data_ready": bool(_monitoring_state.get("last_scan_at")),
                "system_startup": _monitoring_state.get("last_scan_at") is None,
                "loop_active": _loop_is_active(),
                "error": str(exc), "candidates": [], "watchlist": []}


@router.get("/api/monitoring/state")
async def monitoring_state():
    """Get current monitoring state (last scan results + notification history)."""
    settings = await get_user_notification_settings()
    # R3/denetim (2026-09-16): push sağlığı bir DB sorgusudur (COUNT) → state
    # kilidinin DIŞINDA hesaplanır. Dosyanın kendi kuralı: I/O kilit dışında
    # (`_deliver_scan_notifications` gerekçesi), böylece GET /state kilidi
    # gereksiz tutmaz.
    push_health = await _push_health_safe()
    # M1/P2 (R2-18): okuma state kilidi altında; tutarlı snapshot.
    async with _locked_state():
        last_scan = _monitoring_state.get("last_scan_at")
        next_in = None
        if last_scan:
            next_in = max(0, int(SCAN_INTERVAL_SEC - (time.time() - float(last_scan))))
        return {
            "paper_only": True,
            "data_ready": bool(last_scan),
            "system_startup": last_scan is None,
            "last_scan_at": _monitoring_state["last_scan_at"],
            "scan_count": _monitoring_state["scan_count"],
            "candidates": _monitoring_state["last_candidates"],
            "watchlist": _monitoring_state["last_watchlist"],
            "history": _monitoring_state["history"][:20],
            "settings": settings,
            "scope": "global_admin",
            "risk_off": _monitoring_state["risk_off"],
            "risk_off_unknown": bool(_monitoring_state.get("risk_off_unknown", False)),
            # R3 (2026-09-14): yükseliş/erken adayları SUNUCUDAN gelir. Eskiden
            # istemci `/api/macd-monitor` yanıtını yeniden yorumluyordu (bildirim
            # ve kanıt yoktu). Snapshot'tan türetilir → ağ isteği YOK, hızlı.
            "rising": _rising_summary_safe(),
            "rising_notified": int(_monitoring_state.get("rising_notified", 0)),
            # PUSH SAĞLIĞI (2026-09-16): 0 abone = tarayıcı push'u HİÇ çalışmıyor.
            # Backend `VAPID_PRIVATE_KEY` yapılandırılmış olsa bile abonelik yoksa
            # hiçbir push gitmez; bu blok o sessiz arızanın panelde görünmesini sağlar.
            "push": push_health,
            # M1/P0: hem ham kapı hem panel gösterim eşiği açıkça raporlanır.
            **_threshold_fields(settings),
            # M1/P1 (R4-02): canlı görev kaydından gerçek liveness.
            "loop_active": _loop_is_active(),
            "next_scan_in_sec": next_in,
        }


@router.get("/api/monitoring/active-notification/{symbol}")
async def monitoring_active_notification(symbol: str):
    """Sembol için ufku dolmamış (BEKLIYOR) son radar bildirimi — grafik sayfası paneli.

    Bildirim anındaki fiyat, hedef fiyat, hedef artış, skor ve ufuk bilgisini
    geri sayım için expires_at ile birlikte döndürür. Panel SON ufuk süresi
    dolana kadar görünür kalır (sembol adaylıktan düşse bile); canlı fiyat ve
    target_hit ile "HEDEFE ULAŞILDI" durumu da döner.
    """
    sym = str(symbol or "").upper().strip()
    if not sym:
        return {"symbol": sym, "active": False}
    try:
        row = await database.get_pending_monitoring_notification(sym)
    except Exception as exc:
        logger.warning("aktif bildirim okunamadı %s: %s", sym, exc)
        row = None
    if not row:
        return {"symbol": sym, "active": False}
    detected_at = float(row.get("detected_at") or 0)
    horizon = int(row.get("horizon_minutes") or 0)
    expires_at = detected_at + (horizon + 2) * 60
    now = time.time()
    if not detected_at or now >= expires_at:
        return {"symbol": sym, "active": False}
    price = float(row.get("price") or 0)
    expected = float(row.get("expected_price") or 0)
    target_pct = float(row.get("target_pct") or 0)
    # Canlı fiyat (ticker): hedef kontrolü _check_pending_targets ile aynı
    # ölçütle — panel ufuk dolana kadar kalır, hedefe ulaşıldıysa durum döner.
    current_price = None
    # D-05: tazeligi dogrulanmamis ticker None sayilir.
    try:
        current_price = _ticker_price(sym)
    except Exception:
        current_price = None
    target_hit = bool(current_price and expected > 0 and current_price >= expected)
    return {
        "symbol": sym,
        "active": True,
        # M1/P1 (R4-05): diğer TÜM monitoring skorları gibi panel (0-100) ölçeğine
        # normalize edilir; eski/ham kayıtlar `_stored_panel_score` ile çevrilir.
        "score": _stored_panel_score(row),
        "target_pct": target_pct,
        "price": price,
        "expected_price": expected,
        "target_gain_pct": round((expected / price - 1) * 100, 3) if price > 0 and expected > 0 else target_pct,
        "detected_at": detected_at,
        "horizon_minutes": horizon,
        "expires_at": expires_at,
        "remaining_sec": max(0, int(expires_at - now)),
        "mode": row.get("mode"),
        "current_price": current_price,
        "target_hit": target_hit,
    }


@router.get("/api/reports/notifications")
async def report_notifications(limit: int = 200, day: str = None):
    """Radar bildirim raporu - gercek kapannis M1 olcmueye dayali basari.
    day: YYYY-MM-DD formatinda gun filtresi (opsiyonel).

    Global admin eşiği altındaki bildirimler NE gösterilir NE başarı hesabına
    katılır (2026-09-04 kullanıcı kararı; RISK_OFF çarpanı kaldırıldı) — düşük
    skorlu gürültü başarı oranını yanıltmasın.
    """
    limit = max(1, min(int(limit), 1000))
    # R4-01: bozuk `day` parametresi veritabanına ulaşmadan 400 döner (500 üretmez).
    if day:
        try:
            time.strptime(str(day), "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="Geçersiz tarih: YYYY-MM-DD bekleniyor")
    settings = await get_user_notification_settings()
    # Tek eşik ilkesi (2026-09-04 kullanıcı kararı): raporlar da radar/bildirim/
    # otonom taramayla AYNI etkin eşiği kullanır (admin min_score — RISK_OFF
    # çarpanı kaldırıldı) — ekranda gösterilen sayı fiilen uygulananla aynıdır.
    min_score = _effective_min_score(settings)
    rows = await database.get_monitoring_velocity_matches(limit=limit, day=day)
    # Eşik filtresi panel (0-100) skoru üzerinden; eski ham kayıtlar tek kez
    # normalize edilir (bkz. _stored_panel_score).
    rows = [r for r in rows
            if _stored_panel_score(r) >= min_score]
    now = time.time()
    result = []
    for row in rows:
        symbol = row.get("symbol")
        price = float(row.get("price") or 0)
        target_pct = float(row.get("target_pct") or 0)
        detected_at = float(row.get("detected_at") or 0)
        mfe = row.get("mfe_pct")
        mfe_pct = float(mfe) if mfe is not None else None
        touched = row.get("touched_target")
        candidate_status = str(row.get("candidate_status") or "")
        horizon = int(row.get("horizon_minutes") or 0)
        window_closed = bool(detected_at and horizon and (now - detected_at) >= (horizon + 2) * 60)
        # M1/P0 (R3-04): TAMAMEN BAŞARILI YALNIZCA hedefe GERÇEKTEN dokunulduysa.
        # Yarım-hedef hareketi (mfe >= hedef×0.5) artık "BAŞARILI" DEĞİL → "KISMİ";
        # eski tanım başarı oranını ~2× şişiriyordu (hedefe değmeden "başarılı").
        if candidate_status == "evaluated" and mfe_pct is not None:
            if touched:
                status = "TAMAMEN BAŞARILI"
            elif mfe_pct > 0:
                status = "KISMİ"
            else:
                status = "BAŞARISIZ"
        elif candidate_status == "pending" and not window_closed:
            status = "BEKLİYOR"
        else:
            status = "ÖLÇÜLEMEDİ" if window_closed else "BEKLİYOR"
        result.append({
            "id": row.get("id"),
            "symbol": symbol,
            "message": row.get("message"),
            "title": row.get("title"),
            # Panel (0-100) skoru: eski ham kayıtlar da aynı ölçeğe çevrilerek
            # tabloda tek ölçek gösterilir (2026-09-04).
            "score": _stored_panel_score(row),
            "target_pct": target_pct,
            "price": price,
            "expected_price": row.get("expected_price"),
            "mfe_pct": mfe_pct,
            # D-06: MFE tepe; exit/net gerçekleşen çıkış ve maliyet sonrası net.
            "exit_pct": (float(row["exit_pct"]) if row.get("exit_pct") is not None else None),
            "net_pct": (float(row["net_pct"]) if row.get("net_pct") is not None else None),
            "touched_target": touched,
            "status": status,
            "mode": row.get("mode"),
            "horizon_minutes": horizon,
            "detected_at": detected_at,
            "sent_via_push": row.get("sent_via_push"),
            "candidate_id": row.get("candidate_id"),
            "ml_hit_probability": row.get("ml_hit_probability"),
            # D-08: doygunlukta siralama bilgisi panel skordan KAYBOLUR
            # (100'a kirpilir). Ham skor + kirpilma bayragi tasinir.
            "raw_score": (float(row["raw_score"]) if row.get("raw_score") is not None else None),
            "saturated": _score_is_saturated(row),
        })
    counts = {"TAMAMEN BAŞARILI": 0, "BAŞARILI": 0, "KISMİ": 0,
              "BAŞARISIZ": 0, "BEKLİYOR": 0, "ÖLÇÜLEMEDİ": 0}
    for item in result:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    evaluated = sum(counts[k] for k in ("TAMAMEN BAŞARILI", "BAŞARILI", "KISMİ", "BAŞARISIZ"))
    # M1/P0 (R3-04): başarı = YALNIZCA gerçek dokunuş (TAMAMEN BAŞARILI).
    # Yarım-hedef KISMİ sayılır ve başarıya eklenmez ("BAŞARILI" kovası korunur
    # ama boştur — FE uyumluluğu için anahtar silinmedi).
    success = counts["TAMAMEN BAŞARILI"]
    day_breakdown = {"counts": counts, "evaluated": evaluated,
                    "success_count": success,
                    "success_rate": (success / evaluated * 100) if evaluated else None}
    # R4-04: "genel (tüm zamanlar)" artık cap'siz (limit=None) — 1000 satırda sessizce kırpılmaz.
    all_rows = await database.get_monitoring_velocity_matches(limit=None, day=None)
    # Genel başarı da aynı global eşiğe tabi (gürültü oranları dışarıda kalır);
    # eski kayıtlar için tek kez normalize uygulanır (bkz. _stored_panel_score).
    all_rows = [r for r in all_rows if _stored_panel_score(r) >= min_score]
    all_evaluated = 0
    all_success = 0
    for r in all_rows:
        mfe_val = r.get("mfe_pct")
        mfe_f = float(mfe_val) if mfe_val is not None else None
        tch = r.get("touched_target")
        cand_st = str(r.get("candidate_status") or "")
        tgt = float(r.get("target_pct") or 0)
        if cand_st == "evaluated" and mfe_f is not None:
            all_evaluated += 1
            # M1/P0 (R3-04): yarım-hedef (mfe >= hedef×0.5) artık başarı SAYILMAZ;
            # genel başarı da yalnızca GERÇEK dokunuşla hesaplanır.
            if tch:
                all_success += 1
    overall_breakdown = {
        "evaluated": all_evaluated,
        "success_count": all_success,
        "success_rate": (all_success / all_evaluated * 100) if all_evaluated else None,
    }
    return {"paper_only": True, "notifications": result, "total": len(result),
            "breakdown": day_breakdown, "overall": overall_breakdown}

@router.get("/api/monitoring/diagnostics")
async def monitoring_diagnostics(request: Request):
    """Diagnostic deep-dive: compare target_pct vs actual MFE across all records.
    
    Returns per-symbol breakout so user can spot where the success rate is lost.

    B7: WS/bellek/rate-limit metrikleri ALTYAPI İÇ bilgileridir — uç artık
    YALNIZ admin erişimlidir (önceden kimlik doğrulamasız açıktı).
    """
    from app.api_common import require_admin as _require_admin
    _require_admin(request)
    settings = await get_user_notification_settings()
    min_score = _effective_min_score(settings)
    # R4-04: genel tablo da cap'siz okunur (limit=None).
    rows = await database.get_monitoring_velocity_matches(limit=None, day=None)
    rows = [r for r in rows if _stored_panel_score(r) >= min_score]
    profile_buckets: dict[str, list] = {"all": []}
    for r in rows:
        mfe_val = r.get("mfe_pct")
        mfe_f = float(mfe_val) if mfe_val is not None else None
        tgt = float(r.get("target_pct") or 0)
        cand_st = str(r.get("candidate_status") or "")
        if cand_st != "evaluated" or mfe_f is None:
            continue
        score = _stored_panel_score(r)
        bucket = "all"
        # Score buckets
        if score >= 90:
            bucket = "90-100"
        elif score >= 80:
            bucket = "80-90"
        elif score >= 70:
            bucket = "70-80"
        elif score >= 60:
            bucket = "60-70"
        elif score >= 50:
            bucket = "50-60"
        else:
            bucket = "0-50"
        tch = bool(r.get("touched_target"))
        # M1/P0 (R3-04): yarım-hedef artık "BASARILI" değil "KISMİ"; başarı yalnız
        # gerçek dokunuş (TAMAMEN). Teşhis kovaları raporla aynı tanımı kullanır.
        label = "TAMAMEN" if tch else ("KISMİ" if mfe_f > 0 else "BASARISIZ")
        entry = {"symbol": r.get("symbol"), "score": score, "target_pct": tgt,
                 "mfe_pct": round(mfe_f, 3), "status": label, "horizon": r.get("horizon_minutes")}
        profile_buckets.setdefault(bucket, []).append(entry)
        profile_buckets["all"].append(entry)
    summary = {}
    for bk, items in profile_buckets.items():
        n = len(items)
        # M1/P0 (R3-04): başarı yalnız gerçek dokunuş (TAMAMEN).
        s = sum(1 for i in items if i["status"] == "TAMAMEN")
        avg_target = sum(i["target_pct"] for i in items) / n if n else 0
        avg_mfe = sum(i["mfe_pct"] for i in items) / n if n else 0
        summary[bk] = {"count": n, "success": s, "success_rate": round(s/n*100,1) if n else 0,
                       "avg_target_pct": round(avg_target,2), "avg_mfe_pct": round(avg_mfe,2)}
    # Per-symbol top losers
    by_symbol = {}
    for r in rows:
        sym = str(r.get("symbol") or "").upper()
        mfe_val = r.get("mfe_pct")
        mfe_f = float(mfe_val) if mfe_val is not None else None
        tgt = float(r.get("target_pct") or 0)
        cand_st = str(r.get("candidate_status") or "")
        if cand_st != "evaluated" or mfe_f is None:
            continue
        tch = bool(r.get("touched_target"))
        by_symbol.setdefault(sym, {"count": 0, "success": 0, "total_mfe": 0.0, "total_target": 0.0})
        by_symbol[sym]["count"] += 1
        # M1/P0 (R3-04): yarım-hedef başarı sayılmaz (yalnız gerçek dokunuş).
        if tch:
            by_symbol[sym]["success"] += 1
        by_symbol[sym]["total_mfe"] += mfe_f
        by_symbol[sym]["total_target"] += tgt
    sym_summary = {}
    for sym, d in sorted(by_symbol.items(), key=lambda x: x[1]["success"]/max(x[1]["count"],1)):
        sym_summary[sym] = {"count": d["count"], "success": d["success"],
                            "rate": round(d["success"]/d["count"]*100, 1) if d["count"] else 0,
                            "avg_mfe": round(d["total_mfe"]/d["count"], 3) if d["count"] else 0,
                            "avg_target": round(d["total_target"]/d["count"], 2) if d["count"] else 0}
    # WS and rate limit metrics (2026-09-07)
    ws_metrics = {}
    try:
        from app.ws_runtime import ws_manager
        ws_metrics["active_connections"] = len(ws_manager.active_connections)
    except Exception:
        ws_metrics["active_connections"] = None
    try:
        md = market
        ws_metrics["ws_last_event_at"] = getattr(md, "ws_last_event_at", None)
        ws_metrics["rest_last_event_at"] = getattr(md, "rest_last_event_at", None)
        ws_metrics["ws_last_error"] = str(getattr(md, "ws_last_error", None))[:200] if getattr(md, "ws_last_error", None) else None
        ws_metrics["rest_last_error"] = str(getattr(md, "rest_last_error", None))[:200] if getattr(md, "rest_last_error", None) else None
        ws_metrics["ws_connected_at"] = getattr(md, "ws_connected_at", None)
        ws_metrics["connection_generation"] = getattr(md, "connection_generation", 0)
        ws_metrics["reconnect_requested"] = getattr(md, "reconnect_requested", False)
        ws_metrics["subscribed_symbols"] = len(getattr(md, "symbols", []))
    except Exception as exc:
        ws_metrics["error"] = str(exc)
    rate_stats = {}
    try:
        from app.routers import velocity
        rate_stats = velocity._rate_limit_stats()
    except Exception as exc:
        rate_stats["error"] = str(exc)
    freshness_sample = {}
    try:
        for sym_item in list(_monitoring_state.get("last_candidates") or [])[:3]:
            sym_name = str(sym_item.get("symbol", "") or "")
            if sym_name:
                fd = market.data_freshness(sym_name, "5m") if hasattr(market, "data_freshness") else {}
                freshness_sample[sym_name] = fd
    except Exception as exc:
        # M1/P2: sessiz `pass` yerine görünür kayıt (teşhis boş kalmasın).
        logger.warning("freshness_sample olusturulamadi: %s", exc)
        freshness_sample = {"error": str(exc)}
    # Memory usage: obezite tespiti (2026-09-07)
    memory_metrics = {}
    try:
        import sys as _sys
        # Klines cache boyutu: tum timeframelerdeki tum semboller icin toplam deger
        total_klines = 0
        total_volumes = 0
        md = market
        if hasattr(md, "klines"):
            for tf_kv in md.klines.values():
                for sym_kv in tf_kv.values():
                    if isinstance(sym_kv, dict):
                        klines_len = len(sym_kv.get("timestamps") or [])
                        total_klines += klines_len
                        total_volumes += len(sym_kv.get("volumes") or [])
        memory_metrics["total_cached_klines"] = total_klines
        memory_metrics["total_cached_volumes"] = total_volumes
        if hasattr(md, "tickers"):
            memory_metrics["ticker_count"] = len(md.tickers)
        if hasattr(md, "ticker_24h"):
            memory_metrics["ticker_24h_count"] = len(md.ticker_24h)
        if hasattr(md, "orderflow"):
            memory_metrics["orderflow_count"] = len(md.orderflow)
        if hasattr(md, "trade_flow"):
            memory_metrics["trade_flow_count"] = len(md.trade_flow)
        if hasattr(md, "symbols"):
            memory_metrics["subscribed_symbols"] = len(md.symbols)
    except Exception as exc:
        memory_metrics["error"] = str(exc)
    # DB query latency: son 3 notify sorgusunun gecikmesi (2026-09-07)
    db_latency = {}
    try:
        _db_latencies = _monitoring_state.get("_db_latencies", [])
        # Her notify turu sonunda _notify latency kaydeder; burada son 3'un ortalamasi
        recent = list(_db_latencies)[-3:] if _db_latencies else []
        if recent:
            db_latency["avg_notify_ms"] = round(sum(recent) / len(recent), 1)
            db_latency["max_notify_ms"] = round(max(recent), 1)
            db_latency["sample_count"] = len(recent)
        else:
            db_latency["avg_notify_ms"] = None
            db_latency["max_notify_ms"] = None
            db_latency["sample_count"] = 0
    except Exception as exc:
        # M1/P2: sessiz `pass` yerine loglanır.
        logger.warning("db_latency metrigi olusturulamadi: %s", exc)
        db_latency["error"] = str(exc)
    return {
        "paper_only": True,
        "system_startup": _monitoring_state.get("last_scan_at") is None,
        "data_ready": bool(_monitoring_state.get("last_scan_at")),
        "scan_count": _monitoring_state["scan_count"],
        "last_scan_at": _monitoring_state["last_scan_at"],
        "effective_min_score": min_score,
        "overall": summary,
        "per_symbol_worst": dict(list(sym_summary.items())[:30]),
        "settings": settings,
        "ws_health": ws_metrics,
        "rate_limiter": rate_stats,
        "freshness_sample": freshness_sample,
        "memory_metrics": memory_metrics,
        "db_latency": db_latency,
    }


@router.post("/api/monitoring/reset-notifications")
async def reset_monitoring_notifications(request: Request):
    """Clear notified symbols list (allows re-notification) — YALNIZ admin.

    Reset sonrasi ayni semboller yeniden bildirilebilir; spam korumasini
    atlatabilmek isteyen her kimlik yetkili olmamalidir (2026-09-04).

    Kapsam genişletildi: yalnız `notified_symbols` değil, cooldown'a bağlı TÜM
    geçici durumlar temizlenir (pending_targets, debounce sayacı, sessiz saat
    push kuyruğu) — aksi halde reset sonrası eski bekleyen hedefler/kuyruk
    yeni bildirimleri yine engelliyordu.
    """
    from app.api_common import require_admin as _require_admin
    _require_admin(request)
    async with _locked_state():
        _monitoring_state["notified_symbols"].clear()
        _monitoring_state["pending_targets"].clear()
        _monitoring_state["candidate_streak"].clear()
        _deferred_push.clear()
        await _persist_runtime_state()
    await log_user_action(None, None, "monitoring", "MONITORING_NOTIFICATIONS_RESET",
                          details={}, request=request)
    return {"ok": True, "message": "Bildirim sıfırlandı"}


@router.get("/api/monitoring/notifications")
async def monitoring_notification_history():
    """Son bildirim geçmişi: kalıcı DB kaydı + oturum içi liste."""
    try:
        persisted = await database.list_monitoring_notifications(limit=50)
    except Exception as exc:
        logger.warning("monitoring bildirim geçmişi okunamadı: %s", exc)
        persisted = []
    # M1/P2 (R2-18): oturum geçmişi state kilidi altında okunur.
    async with _locked_state():
        session = _monitoring_state["history"][:20]
    return {"paper_only": True, "history": persisted, "session": session}


async def monitoring_background_loop():
    """Sunucu tarafı sürekli tarama: PWA kapalıyken bile taramayı ve push
    bildirimlerini sürdürür. Hemen başlar (B8: ayrı bir başlangıç taraması
    YOK — döngünün ilk turu zaten hemen koşar; eskiden açılışta çift tarama
    yapılıyordu). Veri hazır değilse scan_one boş döner ama API her zaman
    yanıt verir (2026-09-07)."""
    logger.info("Monitoring arka plan taraması başladı (tur=%ss)", SCAN_INTERVAL_SEC)
    # Altyapı uyarısı: VAPID anahtarları yapılandırılmamışsa push bildirimleri
    # SESSİZCE hiç çalışmaz (uygulama sağlıklı görünür) — denetim maddesi.
    # Startup'ta bir kez görünür uyarı verilir; flush davranışı değişmez.
    # 2026-09-16: Teşhis artık yalnızca "eksik" demiyor; doğru anahtarın gerekli
    # olduğu TEK değişkeni belirtiyor ve private↔public uyuşmazlığını (sessiz 401)
    # yakalıyor. Eski uyarı VAPID_PUBLIC_KEY'i de zorunlu sanıyordu — backend için
    # zorunlu değildir (pywebpush public'i private'dan türetir).
    # 2026-09-16 (yanlış alarm düzeltmesi): "VAPID_PUBLIC_KEY ayarlı değil" notu
    # artık `info` içindedir; sağlıklı sistemde WARNING basmaz. Yalnızca gerçek
    # arızalar (private yok/geçersiz, private↔public uyuşmazlığı) uyarı olur.
    from app.vapid import diagnose_vapid
    _vapid = diagnose_vapid()
    for _problem in _vapid["problems"]:
        logger.warning("Monitoring push: %s", _problem)
    for _note in _vapid["info"]:
        logger.info("Monitoring push: %s", _note)
    if not _vapid["configured"]:
        logger.warning(
            "Monitoring push: tarayıcı push bildirimleri GÖNDERİLMEYECEK "
            "(panel geçmişi ve uygulama içi iletişim çalışmaya devam eder).")
    await restore_runtime_state()
    while True:
        result = None
        try:
            async with _scan_lock:
                async with _locked_state():
                    result = await _run_scan()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("monitoring loop turu başarısız: %s", exc)
            await asyncio.sleep(SCAN_INTERVAL_SEC)
            continue
        # B5: bildirim teslimi (push/WS/otonom paper) state kilidi DIŞINDA —
        # yavaş push ağ I/O'su GET /state ve GET /scan isteklerini bloklamaz.
        if result:
            # BİRLEŞİK RADAR: bu turda push edilen sembol kaydını sıfırla; aynı tur
            # içinde radar + yükseliş çapraz bastırma bu sete göre çalışır.
            _unified_pushed_symbols.clear()
            try:
                await _deliver_scan_notifications(result["new_notifications"])
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("monitoring bildirim teslimi: %s", exc)
        # Sessiz saat bittiyse ertelenen push'ları gönder (scan kilidinden bağımsız)
        try:
            await _flush_deferred_push()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("monitoring ertelenen push gönderimi: %s", exc)
        # R3 (2026-09-14): yükseliş/erken sinyalleri — MACD snapshot'ından türetilir
        # (ağ isteği yok). Her iki kilidin DIŞINDA: push ağ I/O'su + otonom paper
        # DB işi GET /state ve /scan isteklerini bloklamamalı.
        try:
            await _run_rising_scan()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Yükseliş taraması hatası: %s", exc)
        await asyncio.sleep(SCAN_INTERVAL_SEC)


def start_monitoring_loop() -> bool:
    """Arka plan döngüsünü bir kez başlat (idempotent)."""
    global _loop_task
    # M1/P1 (R4-02): canlılık süpervizörün görev kaydından okunur; respawn sonrası
    # bayat `_loop_task` yüzünden İKİNCİ bir döngü açılması engellenir.
    if _loop_is_active():
        return False
    # G-10: ham `create_task` yerine SÜPERVİZÖRLÜ başlatma — döngü beklenmeyen
    # bir hatayla ölürse sınırlı backoff ile yeniden başlatılır (sessiz ölü kanca yok).
    _loop_task = _start_background(monitoring_background_loop, "monitoring-scan-loop")
    return True


def stop_monitoring_loop():
    global _loop_task
    # M1/P1 (R4-02): respawn edilmiş CANLI görevi iptal et (bayat `_loop_task` değil).
    task = get_task("monitoring-scan-loop") or _loop_task
    if task is not None:
        task.cancel()
        _background_tasks.discard(task)
    _loop_task = None