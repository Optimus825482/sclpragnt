"""Otonom Paper Trade Sistemi — monitoring bildirimlerinden tetiklenen pozisyonlar.

Mimari:
  monitoring.py _notify() → auto_paper.py try_open_from_notification()
  
Her bildirim oluştuğunda monitoring.py'deki _notify() fonksiyonunun sonunda bu
modül çağrılır. Açılan pozisyonlar yalnızca auto_paper_trades tablosunda
izlenir; SL/TP/breakeven yönetimi ayrı bir background loop'la yapılır.
positions/trades tablosuna DOKUNULMAZ (signals/decision_logs'a gözlem amaçlı
yazılır).

Muhasebe: açılışta wallet'tan order_value*(1+komisyon) düşülür; kapanışta
exit_notional*(1-komisyon) iade edilir. Kaydedilen pnl = round-trip net =
gross - (entry+exit) komisyon; pnl_pct aynı tabandan türetilir. Açılış ve
kapanış database.open_auto_paper_trade / close_auto_paper_trade içinde tek
transaction'dır (advisory lock ile yarış koruması).
"""
import asyncio
import json
import logging
import os
import time
import math

from fastapi import APIRouter, HTTPException, Request

from app.config import config
from app import database, ma_buy_profiles, notification_plan, paper_ledger, price_service, security
from app.api_common import log_user_action, _background_tasks, _start_background, _fresh_public_price
# R3-06: likidite + korelasyon küme kapıları (velocity-auto ile aynı kaynak)
# için analyzer örneği kullanılır (state'ten; market ile aynı yaşam döngüsü).
from app.state import market, analyzer, extend_stream_universe
from app.ws_runtime import ws_manager


def _session_username(request: Request) -> str | None:
    """Aktif oturumdaki kullanıcı adı (audit log için); None ise kayıt atlanır."""
    if request is None:
        return None
    try:
        user = security.request_user(request.headers, request.cookies)
    except Exception:
        return None
    return (user or {}).get("username")

logger = logging.getLogger("scalper.auto_paper")
router = APIRouter()

#: 2026-10-18: push kapısı / nabız istisnası engel nedenleri. Nabız nedeni Türkçe metin olarak kalır:
#: Radar → TARAMA LOGLARI satırı ("paper: engellendi (...)") eskisiyle birebir aynı görünsün.
_REASON_NO_PUSH = "push_bildirimi_yok"
_REASON_HEARTBEAT = "teyitsiz nabız bildirimi paper açmaz"
# Skorsuz kural sinyali kaynakları: skor/mod kapısı yerine kendi anahtarı (bkz. `_try_open_impl`).
_RULE_SIGNAL_SOURCES = frozenset({"ma_buy", "n7", "kdj_dip", "supertrend", "ema_bounce"})
#: Kural sinyali kaynağının kendi otonom paper anahtarı (2026-10-28: N7 eklendi, 2026-10-31: KDJ ve SuperTrend eklendi).
_RULE_SIGNAL_SWITCHES = {"ma_buy": "MA_BUY_AUTO_PAPER_ENABLED", "n7": "N7_AUTO_PAPER_ENABLED", "kdj_dip": "KDJ_AUTO_PAPER_ENABLED", "supertrend": "SUPERTREND_AUTO_PAPER_ENABLED", "ema_bounce": "EMA_BOUNCE_AUTO_PAPER_ENABLED"}
#: 2026-10-21: çıkış profilli işlem (MA BUY H4) iz süren stop kuralını profilden alır (`ma_buy_profiles.manage_params`):
#: 19:46 kararı — tetik %3 / mesafe %1,5, başabaş stop ve dinamik tetik/mesafe YOK (replay simülasyonuyla birebir).

# 2026-10-15 (denetim düzeltmesi, madde 14): eskiden fonksiyon gövdelerine
# gömülü sabitler (sl_cooldown 5.0, açılış bekleme 30 sn, breakeven gap
# fallback 0.3, reopen saat kovası 3600) tek yerde ve config/env'den okunur.
# Varsayılanlar ESKİ gömülü değerlerle aynı — davranış değişmedi.
_SL_COOLDOWN_MINUTES_DEFAULT = float(getattr(config, "AUTO_PAPER_SL_COOLDOWN_MINUTES", 5.0))
_LOOP_STARTUP_DELAY_SEC = float(getattr(config, "AUTO_PAPER_LOOP_STARTUP_DELAY_SEC", 30.0))
#: Yalnız config'de AUTO_PAPER_TRAILING_GAP_PCT yoksa kullanılan taban (canlı config 1.0).
_TRAILING_GAP_FALLBACK_PCT = 0.3


def _exit_defaults() -> dict:
    """2026-10-16 (maliyet/çıkış): SL / trailing / TP-primary VARSAYILANLARI (profil uygulanmış).

    `config.auto_paper_exit_defaults()` sarmalayıcısı — `AUTO_PAPER_EXIT_PROFILE`
    (`mevcut` | `kalibre`) yalnız varsayılanları değiştirir. Öncelik: DB'ye
    kaydedilmiş admin ayarı (`settings[...]`) > profil > config/env sabiti.
    Config eski ise (fonksiyon yok) sabitlere düşer; davranış değişmez.
    """
    fn = getattr(config, "auto_paper_exit_defaults", None)
    if callable(fn):
        try:
            return dict(fn())
        except Exception:  # noqa: BLE001 — profil çözümlenemezse eski sabitler
            logger.debug("auto_paper: çıkış profili çözümlenemedi, sabitlere düşüldü", exc_info=True)
    return {
        "stop_loss_pct": float(config.AUTO_PAPER_SL_PCT_DEFAULT),
        "trailing_trigger_pct": float(config.AUTO_PAPER_TRAILING_TRIGGER_PCT),
        "trailing_gap_pct": float(getattr(config, "AUTO_PAPER_TRAILING_GAP_PCT", _TRAILING_GAP_FALLBACK_PCT)),
        "tp_primary_exit_enabled": bool(getattr(config, "AUTO_PAPER_TP_PRIMARY_ENABLED", False)),
        "profile": "mevcut",
    }
#: Madde 1: REST de başarısızken zorla kapanış için max_hold çarpanı.
_STALE_FORCE_CLOSE_FACTOR = float(getattr(config, "AUTO_PAPER_STALE_FORCE_CLOSE_FACTOR", 1.5))

# 2026-11-10 (log gürültü kontrolü): likit olmayan sembollerde (HAEDAL/MITO/AVAX
# gibi) miniTicker akışı yalnız işlem olduğunda satır taşır; 15 sn tazelik
# kapısı (MAX_TICKER_AGE_SEC) her 5 sn'lik yönetim turunda uyarı üretir.
# BAYAT uyarısı + REST yedeği sonuç satırları sembol başına BU aralıkta bir
# düşer; REST yedeği HER TURDA AYNI ÇALIŞIR (yalnız log sıklığı — ticari
# davranış, eşik veya bayraK değişikliği yok; DENEY_KAYDI gerektirmez).
_STALE_TICKER_LOG_INTERVAL_SEC = 300.0
_STALE_TICKER_LOG_AT: dict[str, float] = {}


def _stale_ticker_log_gate(symbol: str, now: float) -> bool:
    """Bayat-ticker log satırlarını sembol başına aralıkta bir geçirir (True=logla).

    Ticari davranışa DOKUNMAZ: REST fiyat yedeği bu kapıdan bağımsız her turda
    denenmeye devam eder. Kapı YAPIŞKANDIR: tazelik 15 sn sınırında oynayıp
    kısa süreliğine "taze" olsa bile sayaç sıfırlanmaz (2026-11-10 flap
    düzeltmesi — AVAXTRY gibi sembollerde miniTicker ~15-20 sn kadansla
    geldiği için yaş 15 sn'nin hemen üstünde salınıyor ve sayaç sürekli
    temizlenip her turda log basılıyordu). Aralık dolduğunda bir sonraki
    bayat turda tekrar loglanır.
    """
    last = float(_STALE_TICKER_LOG_AT.get(symbol, 0.0) or 0.0)
    if now - last >= _STALE_TICKER_LOG_INTERVAL_SEC:
        _STALE_TICKER_LOG_AT[symbol] = now
        return True
    return False
# 2026-10-15 (radar iyileştirme): zaman-durdurma (time-stop) — VARSAYILAN KAPALI (0).
# AUTO_PAPER_TIME_STOP_MIN dk sonra kâr, AUTO_PAPER_TIME_STOP_MIN_PROFIT_PCT'in
# altındaysa pozisyon kapatılır (reason="time_stop"). Önce simülatörde ölçülür.
AUTO_PAPER_TIME_STOP_MIN = float(os.getenv("AUTO_PAPER_TIME_STOP_MIN", "0"))
AUTO_PAPER_TIME_STOP_MIN_PROFIT_PCT = float(os.getenv("AUTO_PAPER_TIME_STOP_MIN_PROFIT_PCT", "0.3"))


def _effective_sl_pct(sl_pct: float, atr_pct: float, cap_pct: float | None = None) -> float:
    """2026-10-15 (denetim düzeltmesi, madde 7): ATR'ye duyarlı stop (KESİR birimi).

    effective = max(sl_pct, min(TAVAN, 1.2 × atr_pct)). ATR stop'u yalnız
    GENİŞLETİR (asla daraltmaz); genişletme `AUTO_PAPER_ATR_SL_CAP_PCT`
    tavanıyla sınırlıdır. Eski kod tavan yerine `sl_pct` yazdığı için her
    zaman `sl_pct` dönüyordu (ATR ölü kod).
    """
    cap = (float(getattr(config, "AUTO_PAPER_ATR_SL_CAP_PCT", 2.8)) / 100.0) if cap_pct is None else float(cap_pct)
    return max(float(sl_pct), min(cap, 1.2 * float(atr_pct)))


# 2026-10-27 (işlem planı): bildirimin dondurulmuş `trade_plan`'ı. Yalnız plan sözlükse ve
# "veri_yetersiz" uyarısı yoksa uygulanır; aksi halde bugünkü davranış birebir korunur.
# İSTİSNA: `max_amount_try` tavanı defterden türer (istatistikten bağımsız) → "veri_yetersiz"
# planda da uygulanır (yalnız tavan; hedef/stop/süre uygulanmaz).
PLAN_EXIT_PROFILE = "plan"
PLAN_EXIT_REASON = "plan_sure_doldu"


def _any_trade_plan(notification: dict) -> dict | None:
    plan = (notification or {}).get("trade_plan") if isinstance(notification, dict) else None
    return plan if isinstance(plan, dict) else None


def _active_trade_plan(notification: dict) -> dict | None:
    plan = _any_trade_plan(notification)
    if plan is None:
        return None
    if "veri_yetersiz" in (plan.get("warnings") or []):
        return None
    return plan


def _plan_capped_order_value(order_value: float, notification: dict) -> float:
    """Plan tavanı (`max_amount_try`) mevcut tüm çarpanlardan SONRA uygulanır; yalnız düşürür.

    Tavan defter tabanlıdır → "veri_yetersiz" planda da uygulanır.
    """
    plan = _any_trade_plan(notification)
    if plan is None:
        return order_value
    try:
        cap = float(plan.get("max_amount_try"))
    except (TypeError, ValueError):
        return order_value
    if not math.isfinite(cap) or cap < 0:
        return order_value
    return min(float(order_value), cap)


def _plan_exit_params(notification: dict) -> dict | None:
    """profile_exit=False plan → hedef/stop/süre. Eksik/geçersiz alan varsa None (plan çıkışı uygulanmaz)."""
    plan = _active_trade_plan(notification)
    if plan is None or plan.get("profile_exit"):
        return None
    try:
        out = {
            "target_pct": float(plan["target_gross_pct"]),
            "stop_pct": float(plan["stop_pct"]),
            "exit_at": float(plan["exit_at"]),
            "grace_minutes": float(plan.get("grace_minutes") or 0.0),
        }
    except (KeyError, TypeError, ValueError):
        return None
    if out["target_pct"] <= 0 or out["stop_pct"] <= 0 or out["grace_minutes"] < 0:
        return None
    if not all(math.isfinite(v) for v in out.values()):
        return None
    out["plan_key"] = notification.get("plan_key")
    return out


def _trade_plan_context(trade: dict) -> dict | None:
    """`plan_context` kolonu (JSON metin) → sözlük; okunamazsa None."""
    raw = trade.get("plan_context")
    if isinstance(raw, dict):
        return raw
    if not raw:
        return None
    try:
        ctx = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return ctx if isinstance(ctx, dict) else None


def _blocked(symbol: str, reason: str, **extra) -> dict:
    """R3-06/R3-07: giriş engeli için görünür durum — sessiz düşme yok.

    `try_open_from_notification` artık engellerde None değil, neden tanımlı bir
    sözlük döndürür (operatör/rapor neden 'likidite'/'küme'/'max_open'/'sessiz'
    olduğunu görür). `_maybe_reopen_after_protect_close` bunu "açıldı" sanmasın
    diye yalnızca `status in ("opened","tp_updated","no_change")`ı doğrular.
    """
    block = {"status": "blocked", "reason": reason, "symbol": symbol}
    block.update(extra)
    # 2026-10-18: engel logu TEK yerde (eskiden her `return _blocked(...)` öncesinde ayrı logger.info vardı).
    logger.info("auto_paper %s: giriş engellendi — %s %s", symbol, reason, extra or "")
    try:
        price = float(extra.get("price") or extra.get("current_price") or 0.0)
        asyncio.create_task(_log_blocked_decision(symbol, reason, price, dict(extra)))
    except Exception:
        logger.debug("auto_paper %s: engel kararı loglanamadı", symbol, exc_info=True)
    return block


async def _log_blocked_decision(symbol: str, reason: str, price: float, extra: dict):
    """Otonom işlem engellerini decision_logs tablosuna kaydeder (OTONOM KARAR AKIŞI şeffaflığı)."""
    try:
        from app import database
        reason_tr_map = {
            "stale_ticker": "Taze fiyat alınamadı (REST ve bildirim fiyatı bayat)",
            "not_passing": "Aday panel kriterlerini karşılamadı (passes=False)",
            "quiet_hours": "Sessiz saatler devrede",
            "quiet_hours_query_error": "Sessiz saat kontrol hatası",
            "max_open": f"Maksimum açık pozisyon sınırına ulaşıldı ({extra.get('open_count')}/{extra.get('max_open')})",
            "liquidity": "Likidite yetersizliği (derinlik veya 24s hacim)",
            "cluster": f"Korelasyon küme riski aşıldı (%{extra.get('cluster', {}).get('exposure_pct', 0):.1f})",
            "order_below_min": f"Bakiye yetersiz ({extra.get('order_value', 0)} {config.QUOTE_ASSET} < {extra.get('min_order', 0)} {config.QUOTE_ASSET})",
            "score_below_min": f"Skor yetersiz ({extra.get('score')} < {extra.get('min_score')})",
            "weak_mtf_confluence": f"MACD MTF zayıf / sahte kırılım riski (skor: {extra.get('confluence')}, karar: {extra.get('verdict')})",
            "stop_loss_cooldown": f"Stop loss sonrası bekleme devrede (kalan: {extra.get('remaining_sec')} sn)",
            "post_win_cooldown": f"Kâr koruma beklemesi devrede (kalan: {extra.get('remaining_sec')} sn)",
            "llm_fake_blocked": f"LLM İkinci Göz sahte sinyal/tuzak engeli (güven: %{extra.get('confidence')})",
            "llm_low_confidence": f"LLM İkinci Göz düşük güven engeli (güven: %{extra.get('confidence')} < %60)",
            "mode_not_allowed": f"Mod izinli listede değil ('{extra.get('mode') or '?'}' — izinli: {extra.get('allowed')})",
            "symbol_dedup": f"Aynı sembolde kısa süre önce giriş yapıldı, tekrar açılmadı (kalan: {extra.get('remaining_sec')} sn)",
            # 2026-10-18: eskiden sessiz `return None` olan engeller artık karar günlüğünde görünür.
            "auto_paper_disabled": "Otonom paper trade kapalı (ayarlardan devre dışı)",
            "no_price": "Fiyat alınamadı (ticker ve bildirim fiyatı yok)",
            "notification_already_processed": "Bu bildirim anahtarıyla daha önce işlem açılmıştı (saatte en fazla bir)",
            "reopen_not_allowed": f"Aynı bildirimle yeniden açma koşulları sağlanmadı ({extra.get('detail')})",
            "zero_quantity": "Hesaplanan adet sıfır (bakiye/fiyat)",
            "plan_expired": "İşlem planının süresi geçmiş (çıkış zamanı + ek süre doldu), açılmadı",
            # 2026-10-18: push kapısı ve nabız istisnası artık try_open_from_notification içinde (tüm yollar).
            _REASON_NO_PUSH: "Bu sinyal için push bildirimi gönderilmedi (AUTO_PAPER_ONLY_ON_PUSH)",
            _REASON_HEARTBEAT: "Teyitsiz sessizlik nabzı bildirimi otonom paper açmaz",
        }
        human_reason = reason_tr_map.get(reason, f"Giriş engellendi: {reason}")
        if reason == "liquidity" and isinstance(extra.get("liquidity"), dict):
            liq_reason = extra["liquidity"].get("reason")
            if liq_reason:
                human_reason += f" ({liq_reason})"

        await database.save_decision_log({
            "timestamp": time.time(),
            "symbol": symbol,
            "strategy": "AUTO_PAPER",
            "decision": "ENTRY_BLOCKED",
            "reason": human_reason,
            "price": price,
            "metadata": {"blocked_reason": reason, **extra},
        })
    except Exception as exc:
        logger.debug("auto_paper %s log_blocked_decision hatası: %s", symbol, exc)


async def _liquidity_cluster_gate(symbol: str, order_value: float, balance: float) -> dict | None:
    """R3-06 (P1): bildirim→auto_paper yolunda likidite + korelasyon küme kapısı.

    velocity-auto yolu (`analyzer.open_position`) bu kapıları zaten uygular;
    auto_paper kendi DB yolunu (`database.open_auto_paper_trade`) kullandığı
    için burada AYNI KAPI vurgulanır. Engelin NEDENİ dönüş durumunda
    taşınır (sessiz düşme yok). Hata durumunda açık/geçirgen olunur (paper-only).
    """
    if not analyzer:
        return None
    sym_price = float((market.get_ticker(symbol) or {}).get("last_price") or 0.0)
    # (a) Likidite kapısı.
    liquid = True
    details = {}
    try:
        liquid, details = await analyzer.entry_liquidity_preflight(
            symbol, "AUTO_PAPER", order_value)
    except Exception as exc:
        logger.warning("auto_paper %s likidite ön-kapı değerlendirmesi atlandı: %s", symbol, exc)
    if not liquid:
        block = _blocked(symbol, "liquidity")
        block["price"] = sym_price
        block["liquidity"] = details
        return block
    # (b) Korelasyon küme aşımı.
    try:
        cluster = await analyzer.cluster_entry_blocked(symbol, order_value, balance)
    except Exception as exc:
        logger.debug("auto_paper %s küme kapısı atlandı: %s", symbol, exc)
        cluster = None
    if cluster:
        block = _blocked(symbol, "cluster")
        block["price"] = sym_price
        block["cluster"] = cluster
        return block
    return None

# ---------------------------------------------------------------------------
# Background loop state
# ---------------------------------------------------------------------------
_loop_task = None
_AUTO_PAPER_STATE = {
    "total_opened": 0,
    "total_closed": 0,
    "total_pnl": 0.0,
    "winning_trades": 0,
    "losing_trades": 0,
    "last_check_at": None,
    # D-16 (2026-09-12): yönetim döngüsü hata sayacı (üstel backoff için).
    "consecutive_errors": 0,
}

# ---------------------------------------------------------------------------
# 2026-10-16 (giriş gecikmesi): bildirim -> paper dolum gecikmesi ve giriş kayması
# ÖLÇÜMÜ. 30 günlük ölçüm: tek umut verici alt küme (trend_devam + skor>=95,
# brüt +0,26%) bildirimden 1 adet 5m mum sonra girilince kenarını yitiriyor
# (brüt -0,07%) → bildirim `detected_at` ile dolum arasındaki saniyeler kârlılığı
# belirliyor. Bu blok YALNIZ gözlemdir; giriş davranışı değişmez.
# NOT: `auto_paper_trades` tablosunda `entry_context` kolonu YOKTUR (şema
# doğrulandı; migration eklenmedi). Bu yüzden kayıt (a) süreç içi halka
# tamponda ve (b) logda tutulur; kalıcı ölçüm `monitoring_notifications`
# join'inden (`/api/auto-paper/stats` ve scripts/entry_latency_report.py) gelir.
# ---------------------------------------------------------------------------
from collections import deque  # noqa: E402

_ENTRY_LATENCY_LOG: "deque[dict]" = deque(maxlen=200)
_ENTRY_LATENCY_STATS_LIMIT = 200
#: "Yüksek gecikme" payı eşiği (sn) — stats bloğundaki `share_over_15s`.
_ENTRY_LATENCY_SHARE_SEC = 15.0


def compute_entry_latency_sec(entry_time, detected_at) -> float | None:
    """`entry_time - detected_at` (sn). ms epoch (>1e11) saniyeye çevrilir.

    Geçersiz/eksik girdi veya zaman makinesi (negatif fark) → None/0'a kırpılmaz:
    negatif fark saat kayması demektir, ölçüm dışı bırakılır (None).
    """
    try:
        et = float(entry_time or 0)
        dt = float(detected_at or 0)
    except (TypeError, ValueError):
        return None
    if et > 1e11:
        et /= 1000.0
    if dt > 1e11:
        dt /= 1000.0
    if et <= 0 or dt <= 0:
        return None
    lat = et - dt
    return lat if lat >= 0 else None


def compute_entry_slippage_pct(entry_price, notification_price) -> float | None:
    """`(entry_price / notification.price - 1) * 100` (yüzde; + = bildirimden pahalı giriş)."""
    try:
        ep = float(entry_price or 0)
        np_ = float(notification_price or 0)
    except (TypeError, ValueError):
        return None
    if ep <= 0 or np_ <= 0:
        return None
    return (ep / np_ - 1.0) * 100.0


def _pctile(sorted_vals: list, q: float) -> float | None:
    """Doğrusal enterpolasyonlu yüzdelik (q 0-100); boş liste → None."""
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    k = (len(sorted_vals) - 1) * (q / 100.0)
    lo = int(math.floor(k))
    hi = min(lo + 1, len(sorted_vals) - 1)
    return float(sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo))


def summarize_entry_latency(rows: list, share_sec: float = _ENTRY_LATENCY_SHARE_SEC) -> dict:
    """Satırlardan (``latency_sec``, ``slippage_pct``) `entry_latency` stats bloğu.

    Her satır dict; ``latency_sec``/``slippage_pct`` None olabilir (o ölçüm dışı).
    n = geçerli gecikme sayısı.
    """
    lats = sorted(float(r["latency_sec"]) for r in rows if r.get("latency_sec") is not None)
    slips = sorted(float(r["slippage_pct"]) for r in rows if r.get("slippage_pct") is not None)
    n = len(lats)
    over = sum(1 for v in lats if v > share_sec)
    return {
        "n": n,
        "median_latency_sec": (round(_pctile(lats, 50), 2) if lats else None),
        "p90_latency_sec": (round(_pctile(lats, 90), 2) if lats else None),
        "max_latency_sec": (round(lats[-1], 2) if lats else None),
        "median_slippage_pct": (round(_pctile(slips, 50), 4) if slips else None),
        "share_over_15s": (round(over / n, 4) if n else None),
        "share_threshold_sec": share_sec,
        "slippage_n": len(slips),
    }


def record_entry_latency(symbol: str, trade_id, entry_time, entry_price, notification: dict,
                         market_price=None) -> dict:
    """Açılışta gecikme/kayma ölç, halka tampona yaz, eşik aşılırsa WARNING bas.

    Hiçbir koşulda istisna fırlatmaz (gözlem, girişi bozmamalı).
    """
    try:
        latency = compute_entry_latency_sec(entry_time, notification.get("detected_at"))
        slippage = compute_entry_slippage_pct(entry_price, notification.get("price"))
        # Saf piyasa kayması (modelin giriş kayması hariç): ticker / bildirim fiyatı.
        drift = compute_entry_slippage_pct(market_price, notification.get("price")) if market_price else None
        rec = {
            "trade_id": trade_id,
            "symbol": symbol,
            "mode": notification.get("mode"),
            "entry_time": float(entry_time or 0),
            "entry_latency_sec": (round(latency, 2) if latency is not None else None),
            "entry_slippage_pct": (round(slippage, 4) if slippage is not None else None),
            "market_drift_pct": (round(drift, 4) if drift is not None else None),
            # summarize_entry_latency ortak anahtarları
            "latency_sec": latency,
            "slippage_pct": slippage,
        }
        _ENTRY_LATENCY_LOG.append(rec)
        warn_sec = float(getattr(config, "AUTO_PAPER_ENTRY_LATENCY_WARN_SEC", 15.0))
        if latency is not None and latency > warn_sec:
            logger.warning("auto_paper %s: GİRİŞ GECİKMESİ yüksek %.1fs > %.0fs (kayma %s%%, "
                           "bildirim=%s) — bildirim→dolum gecikmesi kenarı eritir",
                           symbol, latency, warn_sec,
                           (f"{slippage:+.3f}" if slippage is not None else "?"),
                           notification.get("id"))
        else:
            logger.info("auto_paper %s: giriş gecikmesi=%ss kayma=%s%%", symbol,
                        (f"{latency:.1f}" if latency is not None else "?"),
                        (f"{slippage:+.3f}" if slippage is not None else "?"))
        return rec
    except Exception as exc:  # pragma: no cover - savunma
        logger.debug("auto_paper %s: giriş gecikmesi ölçümü atlandı: %s", symbol, exc)
        return {}


async def _fetch_recent_entry_latency_rows(limit: int = _ENTRY_LATENCY_STATS_LIMIT) -> list[dict]:
    """Son `limit` trade'in dolum zamanı/fiyatı + bildirimin detected_at/fiyatı (DB join)."""
    def op(conn):
        cur = conn.execute(
            "SELECT t.id, t.symbol, t.entry_time, t.entry_price, n.detected_at, n.price AS notif_price "
            "FROM auto_paper_trades t JOIN monitoring_notifications n ON n.id = t.notification_id "
            "ORDER BY t.id DESC LIMIT ?", (int(limit),))
        out = []
        for r in cur.fetchall():
            out.append({
                "trade_id": r["id"], "symbol": r["symbol"],
                "latency_sec": compute_entry_latency_sec(r["entry_time"], r["detected_at"]),
                "slippage_pct": compute_entry_slippage_pct(r["entry_price"], r["notif_price"]),
            })
        return out
    return await database._run_db(op)


async def get_entry_latency_block(limit: int = _ENTRY_LATENCY_STATS_LIMIT) -> dict:
    """`/api/auto-paper/stats` `entry_latency` bloğu: DB join (kalıcı), olmazsa halka tampon."""
    source = "db_join"
    try:
        rows = await _fetch_recent_entry_latency_rows(limit)
    except Exception as exc:
        logger.debug("entry_latency DB join atlandı: %s", exc)
        rows = []
    if not rows:
        source = "memory_ring"
        rows = list(_ENTRY_LATENCY_LOG)[-limit:]
    block = summarize_entry_latency(rows)
    block["source"] = source
    block["warn_sec"] = float(getattr(config, "AUTO_PAPER_ENTRY_LATENCY_WARN_SEC", 15.0))
    return block


#: Stop loss sonrası sembol bazında aşırı işlem (churn/peş peşe kayıp) koruma süreleri {symbol: expire_timestamp}
_stop_loss_cooldowns: dict[str, float] = {}
#: Kârlı kapanış (take_profit/trailing_stop) sonrası kârı geri vermeme (post-win churn) koruma süreleri {symbol: expire_timestamp}
_post_win_cooldowns: dict[str, float] = {}

#: P2-4 (2026-10-07 denetimi): cooldown haritaları YALNIZ bellekte tutuluyordu →
#: her restart'ta kayboluyor ve aynı sembole hemen yeniden girilip churn/kâr
#: geri-verme serisi başlıyordu. `monitoring.py` kalıcılık deseniyle aynı
#: anahtar kullanılır (JSON blob, `default=str`). Expire edilmiş girdiler
#: yazılırken budanır (kalıcı büyüme olmaz).
_AUTO_PAPER_STATE_KEY = "auto_paper_runtime_state"


def _cooldowns_to_payload() -> dict:
    now = time.time()
    return {
        "stop_loss_cooldowns": {k: v for k, v in _stop_loss_cooldowns.items() if v > now},
        "post_win_cooldowns": {k: v for k, v in _post_win_cooldowns.items() if v > now},
    }


async def _persist_cooldowns() -> None:
    """Cooldown haritalarını DB'ye yaz (restart amnezisini gider)."""
    try:
        await database.set_llm_setting(
            _AUTO_PAPER_STATE_KEY, json.dumps(_cooldowns_to_payload(), default=str))
    except Exception as exc:
        # Sessiz DEBUG yerine WARNING: persist hatası restart'ta cooldown kaybı
        # demektir (monitoring.py _persist_runtime_state ile aynı desen).
        logger.warning("auto_paper cooldown durumu kalici hale getirilemedi: %s", exc)


async def restore_runtime_state() -> None:
    """Cooldown durumunu DB'den geri yükle (başlangıçta çağrılır)."""
    try:
        raw = await database.get_llm_setting(_AUTO_PAPER_STATE_KEY, "{}")
        payload = json.loads(raw or "{}")
        if not isinstance(payload, dict):
            return
        now = time.time()
        sl = payload.get("stop_loss_cooldowns") or {}
        pw = payload.get("post_win_cooldowns") or {}
        if isinstance(sl, dict):
            _stop_loss_cooldowns.update(
                {str(k): float(v) for k, v in sl.items() if v and float(v) > now})
        if isinstance(pw, dict):
            _post_win_cooldowns.update(
                {str(k): float(v) for k, v in pw.items() if v and float(v) > now})
    except Exception as exc:
        logger.warning("auto_paper cooldown durumu geri yuklenemedi: %s", exc)


# ---------------------------------------------------------------------------
# Core: bildirim → pozisyon açılışı
# ---------------------------------------------------------------------------
async def _push_gate(notification: dict) -> dict | None:
    """2026-10-18 (AUTO_PAPER_ONLY_ON_PUSH, kullanıcı kararı): otonom giriş yalnız push bildirimi GÖNDERİLMİŞ sinyalde.

    Eskiden yalnız velocity yolunda (çağıran tarafta) uygulanıyordu; radar teslimi, hızlı yol, yükseliş,
    LLM-sonrası ve koruma-sonrası yeniden açma yolları kapıyı atlıyordu. Artık TÜM yollar buradan geçer.
    - Sessizlik nabzı (teyitsiz katman) bayraktan bağımsız olarak paper AÇMAZ.
    - Zarf push'un başarıyla gittiğini kendisi taşıyorsa (`sent_via_push=True`) DB sorgusu yapılmaz;
      taşımıyorsa (velocity zarfı, yeniden açma) son ufuk+5 dk (en az 20 dk) içinde push'lanmış kayıt aranır.
    - Kontrol hatasında AÇILMAZ (fail-closed). Engel yoksa None."""
    from app import notification_policy
    symbol = str(notification.get("symbol") or "").upper()
    if notification.get("notify_tier") == notification_policy.TIER_HEARTBEAT:
        return _blocked(symbol or "?", _REASON_HEARTBEAT)
    if not getattr(config, "AUTO_PAPER_ONLY_ON_PUSH", False) or not symbol or notification.get("sent_via_push"):
        return None
    window_sec = max(int(notification.get("horizon_minutes") or 5) + 5, 20) * 60
    try:
        pushed = await database.has_recent_pushed_notification(symbol, window_sec)
    except Exception as exc:  # noqa: BLE001 — kontrol başarısızsa AÇMA (push şartı fail-closed)
        logger.warning("auto_paper %s push kontrolü hatası: %s", symbol, exc)
        pushed = False
    return None if pushed else _blocked(symbol, _REASON_NO_PUSH, window_sec=window_sec)


def _note_scan_log(notification: dict, result) -> None:
    """Giriş sonucunu (açıldı / engellendi:neden / denenmedi) son radar tarama kaydına işle — TEK nokta."""
    try:
        from app import radar_scan_log
        radar_scan_log.note_paper_result((notification or {}).get("symbol"), result)
    except Exception:  # noqa: BLE001 — teşhis kaydı giriş akışını bozmaz
        pass


async def try_open_from_notification(notification: dict) -> dict | None:
    """Bir bildirim/aday zarfından otonom paper pozisyonu aç — TÜM otonom giriş yollarının tek kapısı.

    Önce push kapısı (`_push_gate`), sonra giriş kuralları (`_try_open_impl`). Her sonuç (engel dahil)
    burada bir kez Radar tarama loguna işlenir; çağıranlar ayrıca kapı/log uygulamaz."""
    result = None
    try:
        result = await _push_gate(notification)
        if result is None:
            result = await _try_open_impl(notification)
        return result
    finally:
        _note_scan_log(notification, result)





# ---------------------------------------------------------------------------
# 2026-11-10 REFACTOR: `_try_open_impl` (472 satır) aşamalara bölündü.
# Aşamalar: context -> gates -> cooldown -> price -> reopen -> max_open ->
# sizing -> _open_new_trade. Davranış birebir korunmuştur (kapı sırası ve
# engel nedenleri aynı); yalnız okunabilirlik/bakım için bölündü.
# ---------------------------------------------------------------------------


async def _entry_context(notification: dict) -> tuple[dict | None, dict | None, str | None, bool]:
    """Aşama 1 — ayar/kimlik/skor/mod kapıları. Dönüş: (settings, block, symbol, rule_signal)."""
    settings = await get_auto_paper_settings()
    if not settings.get("enabled", True):
        return None, _blocked(str(notification.get("symbol") or "?").upper(), "auto_paper_disabled"), None, False

    symbol = str(notification.get("symbol") or "").upper()
    if not symbol:
        return settings, None, None, False

    _source = str(notification.get("source") or "")
    rule_signal = _source in _RULE_SIGNAL_SOURCES
    if rule_signal and not getattr(config, _RULE_SIGNAL_SWITCHES[_source], True):
        return settings, _blocked(symbol, f"{_source}_paper_kapali"), symbol, rule_signal

    score = float(notification.get("score") or 0)
    min_score = float(settings.get("min_score", config.AUTO_PAPER_MIN_SCORE_DEFAULT))
    if not rule_signal and score < min_score:
        return settings, _blocked(symbol, "score_below_min", price=0.0,
                                  score=round(score, 1), min_score=min_score), symbol, rule_signal

    allowed_modes = settings.get("allowed_modes") or []
    if allowed_modes and not rule_signal:
        notif_mode = str(notification.get("mode") or "").strip()
        if notif_mode not in allowed_modes:
            return settings, _blocked(symbol, "mode_not_allowed", mode=notif_mode,
                                      allowed=allowed_modes), symbol, rule_signal

    return settings, None, symbol, rule_signal


async def _entry_dedup_gate(symbol: str, settings: dict) -> dict | None:
    """Sembol dedup cooldown kapısı (yalnız açık pozisyon yokken anlamlı)."""
    dedup_min = float(settings.get("dedup_cooldown_minutes", 0.0) or 0.0)
    if dedup_min <= 0:
        return None
    try:
        _last_entry = await database.get_last_auto_paper_entry_time(symbol)
    except Exception as exc:
        logger.debug("auto_paper %s dedup kontrol hatasi: %s", symbol, exc)
        _last_entry = None
    if _last_entry and (time.time() - _last_entry) < (dedup_min * 60.0):
        rem = round(dedup_min * 60.0 - (time.time() - _last_entry), 0)
        return _blocked(symbol, "symbol_dedup", remaining_sec=rem,
                        dedup_cooldown_minutes=dedup_min)
    return None


def _entry_flag_gates(notification: dict, symbol: str) -> dict | None:
    """passes / block_reason / rejim rozeti / master_surge kapıları."""
    passes = notification.get("passes")
    if passes is not None and not bool(passes):
        logger.warning("auto_paper %s: aday panel sartini gecmedi (passes=False) - acilmadi (R3-08)", symbol)
        return _blocked(symbol, "not_passing")

    block_reason = notification.get("block_reason") or notification.get("surge_block_reason")
    if block_reason:
        logger.warning("auto_paper %s: risk engeli devrede (%s) - acilmadi", symbol, block_reason)
        return _blocked(symbol, f"risk_blocked:{block_reason}", block_reason=block_reason)

    _regime_badge = notification.get("regime_badge")
    if not _regime_badge and str(getattr(config, "RADAR_SHIELD_MODE", "badge")).lower() != "block":
        try:
            from app.routers.velocity import btc_shield_active
            if symbol not in ("BTCTRY", "BTCUSDT") and btc_shield_active():
                _regime_badge = "BTC_BEAR_REGIME_SHIELD"
        except Exception:
            _regime_badge = None
    if _regime_badge:
        if getattr(config, "AUTO_PAPER_BLOCK_ON_REGIME_BADGE", False):
            return _blocked(symbol, f"risk_blocked:{_regime_badge}", block_reason=_regime_badge)
        logger.info("auto_paper %s: BTC rejim rozeti var ama otonom girisi engellemiyor (kullanici karari)", symbol)
    if notification.get("master_surge_passed") is False:
        logger.warning("auto_paper %s: Master Surge kontrolunden gecmedi - acilmadi", symbol)
        return _blocked(symbol, "master_surge_failed")
    return None


def _entry_llm_gate(notification: dict, symbol: str, settings: dict) -> dict | None:
    """LLM ikinci göz kapısı (FAKE/TUZAK ya da düşük güven)."""
    if not settings.get("llm_gate_enabled", True):
        return None
    llm_v = str(notification.get("llm_verdict") or "").strip().upper()
    try:
        llm_c = float(notification.get("llm_confidence") or 0)
    except (ValueError, TypeError):
        llm_c = 0.0
    min_c = float(settings.get("llm_min_confidence", 60.0))
    if llm_v in ("FAKE", "TUZAK") and llm_c >= 50:
        logger.warning("auto_paper %s: LLM Ikinci Goz FAKE/TUZAK uyarisi verdi (Guven: %%%.0f) - islem acilmadi", symbol, llm_c)
        return _blocked(symbol, "llm_fake_blocked", block_reason=f"LLM_FAKE_%{round(llm_c)}", verdict=llm_v, confidence=round(llm_c))
    if llm_v == "DEVAM" and llm_c > 0 and llm_c < min_c:
        logger.warning("auto_paper %s: LLM DEVAM dedi ancak guven yetersiz (%%%s < %%%s) - acilmadi", symbol, llm_c, min_c)
        return _blocked(symbol, "llm_low_confidence", block_reason="LLM_LOW_CONFIDENCE", verdict=llm_v, confidence=round(llm_c))
    return None


def _entry_suite_gates(notification: dict, symbol: str) -> dict | None:
    """FinCon tuzak kalkanı + OBV/CMF + Wyckoff VSA kapıları."""
    try:
        from app.ai_trading_suite import evaluate_trap_shield
        trap_verdict = evaluate_trap_shield(
            symbol=symbol,
            indicators={
                "rsi": float(notification.get("rsi") or 50.0),
                "volume_ratio": float(notification.get("volume_ratio") or 1.0),
                "adx": float(notification.get("adx") or 20.0),
            }
        )
        if trap_verdict.protective_veto:
            logger.warning("auto_paper %s: FinCon Tuzak Kalkani VETOSU verdi (Benzerlik: %%%.0f, Tip: %s) - islem engellendi",
                           symbol, trap_verdict.highest_similarity_pct, trap_verdict.matching_failure_type)
            return _blocked(symbol, f"fincon_trap_shield_veto:{trap_verdict.matching_failure_type}",
                            block_reason=f"FINCON_TRAP_%{int(trap_verdict.highest_similarity_pct)}",
                            verdict=trap_verdict.verdict)
    except Exception as trap_exc:
        logger.debug("auto_paper %s FinCon trap shield kontrolu atlandi: %s", symbol, trap_exc)

    try:
        from app.ai_trading_suite import evaluate_wyckoff_vsa, evaluate_obv_cmf_inflow
        obv_res = evaluate_obv_cmf_inflow(symbol=symbol)
        if obv_res.divergence_type == "BEARISH_DISTRIBUTION" and obv_res.cmf_value < -0.15:
            logger.warning("auto_paper %s: OBV/CMF Kurumsal Dagitim Uyarisi (CMF: %.2f) - islem engellendi",
                           symbol, obv_res.cmf_value)
            return _blocked(symbol, "obv_cmf_bearish_distribution_veto",
                            block_reason=f"OBV_CMF_DISTRIBUTION_{round(obv_res.cmf_value, 2)}",
                            verdict="BEARISH_DISTRIBUTION")
        wyckoff_res = evaluate_wyckoff_vsa(symbol=symbol)
        if wyckoff_res.vsa_pattern in ("DISTRIBUTION_UTAD", "BUYING_CLIMAX_EXHAUSTION") or wyckoff_res.trade_action == "TAKE_PROFIT":
            logger.warning("auto_paper %s: Wyckoff VSA Zirve Tukenis/Dagitim Uyarisi (%s) - islem engellendi",
                           symbol, wyckoff_res.vsa_pattern)
            return _blocked(symbol, f"wyckoff_distribution_veto:{wyckoff_res.vsa_pattern}",
                            block_reason=f"WYCKOFF_{wyckoff_res.vsa_pattern}",
                            verdict=wyckoff_res.vsa_pattern)
    except Exception as spot_suite_err:
        logger.debug("auto_paper %s Spot AI Suite kontrolu atlandi: %s", symbol, spot_suite_err)
    return None


async def _compute_entry_gates(notification: dict, symbol: str, settings: dict,
                               open_trade: dict | None) -> dict | None:
    """Aşama 2 — dedup + akıllı-para / rejim / LLM / trap kapıları.

    Açık pozisyon varsa TP-güncelleme yoluna gidileceği için kalite kapıları
    BİLİNÇLİ atlanır — mevcut pozisyonu iyileştirmek riskli değildir.
    """
    if open_trade is None:
        blocked = await _entry_dedup_gate(symbol, settings)
        if blocked is not None:
            return blocked
    else:
        return None

    blocked = _entry_flag_gates(notification, symbol)
    if blocked is not None:
        return blocked
    blocked = _entry_llm_gate(notification, symbol, settings)
    if blocked is not None:
        return blocked
    return _entry_suite_gates(notification, symbol)


async def _cooldown_gate(notification: dict, symbol: str, settings: dict) -> dict | None:
    """Aşama 3a — sessiz saatler + stop-loss ve post-win cooldown kapıları."""
    try:
        from app.routers import monitoring as _monitoring_mod
        if await _monitoring_mod.quiet_hours_active():
            logger.warning("auto_paper %s: sessiz saatler etkin - otonom islem acilmadi (R3-07)", symbol)
            return _blocked(symbol, "quiet_hours")
    except Exception as quiet_exc:
        logger.warning("auto_paper %s: sessiz saat sorgusu basarisiz - islem acilmadi (fail-closed): %s",
                       symbol, quiet_exc)
        return _blocked(symbol, "quiet_hours_query_error")

    now_ts = time.time()
    cooldown_min = float(settings.get("sl_cooldown_minutes", _SL_COOLDOWN_MINUTES_DEFAULT))
    sl_cooldown_until = _stop_loss_cooldowns.get(symbol, 0.0)
    if cooldown_min > 0 and now_ts >= sl_cooldown_until:
        try:
            last_sl = await database.get_last_auto_paper_stop_loss_time(symbol)
            if last_sl and (now_ts - last_sl) < (cooldown_min * 60.0):
                sl_cooldown_until = last_sl + (cooldown_min * 60.0)
                _stop_loss_cooldowns[symbol] = sl_cooldown_until
        except Exception as exc:
            logger.debug("auto_paper %s db sl cooldown kontrol hatasi: %s", symbol, exc)
    if now_ts < sl_cooldown_until:
        return _blocked(symbol, "stop_loss_cooldown", remaining_sec=round(sl_cooldown_until - now_ts, 0))

    win_cooldown_min = float(settings.get("post_win_cooldown_minutes", getattr(config, "AUTO_PAPER_POST_WIN_COOLDOWN_MINUTES", 15.0)))
    win_cooldown_until = _post_win_cooldowns.get(symbol, 0.0)
    if win_cooldown_min > 0 and now_ts >= win_cooldown_until:
        try:
            last_win = await database.get_last_auto_paper_winning_trade_time(symbol)
            if last_win and (now_ts - last_win) < (win_cooldown_min * 60.0):
                win_cooldown_until = last_win + (win_cooldown_min * 60.0)
                _post_win_cooldowns[symbol] = win_cooldown_until
        except Exception as exc:
            logger.debug("auto_paper %s db post win cooldown kontrol hatasi: %s", symbol, exc)
    if now_ts < win_cooldown_until:
        return _blocked(symbol, "post_win_cooldown", remaining_sec=round(win_cooldown_until - now_ts, 0))

    return None


async def _resolve_entry_price(notification: dict, symbol: str, settings: dict) -> tuple[float | None, dict | None]:
    """Aşama 3b — güncel fiyat + ticker tazelik kapısı + MTF konfluans kapısı."""
    if hasattr(config, "PASSIVE_SYMBOLS") and isinstance(config.PASSIVE_SYMBOLS, set):
        config.PASSIVE_SYMBOLS.discard(symbol)

    ticker = market.get_ticker(symbol)
    current_price = float(ticker.get("last_price") or 0) if ticker else 0
    if current_price <= 0:
        current_price = float(notification.get("price") or 0)
    if current_price <= 0:
        return current_price, _blocked(symbol, "no_price")

    try:
        freshness = market.ticker_freshness(symbol, max_age_sec=60)
    except Exception:
        freshness = {"fresh": False, "age_sec": None}

    if not bool(freshness.get("fresh")):
        try:
            rest_px = await price_service.rest_ticker_price(symbol)
            if rest_px:
                current_price = float(rest_px)
                freshness = {"fresh": True, "age_sec": 0.0, "source": "binance_tr_rest_auto_paper"}
        except Exception as exc:
            logger.warning("auto_paper %s: REST ticker fetch hatasi: %s", symbol, exc)

    if not bool(freshness.get("fresh")):
        notif_time = float(notification.get("detected_at") or notification.get("timestamp") or 0)
        if notif_time > 1e11:
            notif_time /= 1000.0
        if notif_time > 0 and (time.time() - notif_time) <= 60.0 and float(notification.get("price") or 0) > 0:
            current_price = float(notification["price"])
            freshness = {"fresh": True, "age_sec": round(time.time() - notif_time, 1),
                         "source": "notification_fallback"}

    if current_price <= 0:
        current_price = float(notification.get("price") or 0)

    if not bool(freshness.get("fresh")) or current_price <= 0:
        logger.warning("auto_paper %s: taze ticker yok (age=%ss) - bayat fiyata acilis engellendi",
                       symbol, freshness.get("age_sec"))
        return current_price, _blocked(symbol, "stale_ticker", price=current_price, age_sec=freshness.get("age_sec"))

    block_weak_mtf = bool(settings.get("block_weak_mtf", True))
    min_mtf_confluence = float(settings.get("min_mtf_confluence", 45.0))
    if block_weak_mtf:
        mtf_verdict = notification.get("macd_mtf_verdict")
        mtf_confluence = notification.get("macd_mtf_confluence")
        if mtf_verdict is None or mtf_confluence is None:
            try:
                from app import macd_mtf
                mtf_compact = macd_mtf.cached_compact(symbol)
                if mtf_compact:
                    mtf_verdict = mtf_compact.get("verdict")
                    mtf_confluence = mtf_compact.get("confluence")
            except Exception:
                logger.debug("auto_paper %s: MACD MTF kompakt verisi alinamadi", symbol, exc_info=True)
        if mtf_verdict == "ZAYIF" or (mtf_confluence is not None and float(mtf_confluence) < min_mtf_confluence):
            logger.warning("auto_paper %s: MACD MTF ZAYIF (skor=%s < %.1f, verdict=%s) - sahte kirilim riskiyle acilmadi",
                           symbol, mtf_confluence, min_mtf_confluence, mtf_verdict)
            return current_price, _blocked(symbol, "weak_mtf_confluence", price=current_price,
                                           confluence=mtf_confluence, verdict=mtf_verdict)

    return current_price, None


async def _reopen_gate(notification: dict, symbol: str, settings: dict, current_price: float) -> dict | None:
    """Aşama 4 — aynı bildirimin daha önce işlenip işlenmediğini ve yeniden-açma kurallarını denetler."""
    notification_id = notification.get("id")
    notification_key = notification.get("notification_key")
    now = time.time()

    prior_trade = None
    if notification_key is not None:
        try:
            prior_trade = await database.get_recent_auto_paper_trade_by_notification_key(str(notification_key))
        except Exception:
            prior_trade = None
        if prior_trade:
            return _blocked(symbol, "notification_already_processed", price=current_price, key=str(notification_key))
        return None

    if notification_id is None:
        return None

    nid_int = None
    if isinstance(notification_id, int):
        nid_int = notification_id
    elif isinstance(notification_id, str) and notification_id.lstrip("-").isdigit():
        nid_int = int(notification_id)
    if nid_int is not None:
        try:
            prior_trade = await database.get_recent_auto_paper_trade_by_notification(nid_int)
        except Exception:
            prior_trade = None
    if not prior_trade:
        return None

    if not bool(settings.get("reopen_after_protect_close", config.AUTO_PAPER_REOPEN_AFTER_PROTECT_CLOSE)):
        return _blocked(symbol, "reopen_not_allowed", price=current_price, detail="yeniden acma kapali")

    exit_reason = str(prior_trade.get("exit_reason") or "").lower()
    trailing_kapanis = exit_reason in {"trailing_stop", "breakeven_stop"}
    if not trailing_kapanis:
        return _blocked(symbol, "reopen_not_allowed", price=current_price, detail=f"onceki kapanis: {exit_reason or '?'}")

    notif_price = float(notification.get("price") or 0)
    if notif_price <= 0 or current_price <= notif_price:
        return _blocked(symbol, "reopen_not_allowed", price=current_price, detail="fiyat bildirim fiyatinin altinda")

    detected_at = float(notification.get("detected_at") or 0)
    horizon_min = float(notification.get("horizon_minutes") or 0)
    ufuk_bitti = bool(detected_at and horizon_min and (detected_at + horizon_min * 60) < now)
    if ufuk_bitti:
        return _blocked(symbol, "reopen_not_allowed", price=current_price, detail="ufuk suresi doldu")

    prior_tp = float(prior_trade.get("take_profit") or 0)
    if prior_tp > 0 and current_price >= prior_tp:
        return _blocked(symbol, "reopen_not_allowed", price=current_price, detail="hedefe ulasildi")

    logger.info("auto_paper %s: trailing/breakeven kapanisi sonrasi kosullar saglaniyor (%s) - "
                "ayni bildirimle yeniden islem aciliyor", symbol, exit_reason)
    return None


async def _max_open_gate(symbol: str, settings: dict, current_price: float) -> dict | None:
    """Aşama 5 — global maksimum açık pozisyon tavanı (0 = sınırsız)."""
    max_open = int(settings.get("max_open_positions",
                                getattr(config, "AUTO_PAPER_MAX_OPEN_POSITIONS", 0)))
    if max_open <= 0:
        return None
    open_count = len(await database.list_auto_paper_trades(status="open", apply_reports_baseline=False))
    if open_count >= max_open:
        logger.warning("auto_paper %s: max acik pozisyon (%d/%d) - acilmadi (R3-06)",
                       symbol, open_count, max_open)
        return _blocked(symbol, "max_open", price=current_price, open_count=open_count, max_open=max_open)
    return None


async def _sizing_gate(notification: dict, symbol: str, settings: dict) -> tuple[float | None, float | None, dict | None]:
    """Aşama 6 — sizing (bakiye x balance_pct, plan tavani) + likidite/korelasyon kume kapisi."""
    balance = await database.get_wallet_balance()
    balance_pct = float(settings.get("balance_pct", config.AUTO_PAPER_BALANCE_PCT_DEFAULT)) / 100.0
    order_value = balance * balance_pct
    order_value = _plan_capped_order_value(order_value, notification)
    gate = await _liquidity_cluster_gate(symbol, order_value, balance)
    if gate is not None:
        logger.warning("auto_paper %s giris engellendi: %s (R3-06)", symbol, gate.get("reason"))
        return balance, order_value, gate
    return balance, order_value, None
async def _try_open_impl(notification: dict) -> dict | None:
    """Bir monitoring bildirimi geldiğinde otonom paper pozisyonu aç — aşamalı orkestratör.

    Giriş kuralları (aşama sırası):
      1. `_entry_context`        — ayar/kimlik/skor/mod kapıları
      2. `_compute_entry_gates`  — dedup + akıllı-para/rejim/LLM/trap kapıları
      3. `_cooldown_gate`        — sessiz saat + SL/post-win cooldown
      4. `_resolve_entry_price`  — fiyat + tazelik + MTF konfluans
      5. `_reopen_gate`          — aynı bildirim / yeniden-açma kuralları
      6. `_max_open_gate`        — global açık pozisyon tavanı
      7. `_sizing_gate`          — bakiye × balance_pct + likidite/küme kapısı
      8. `_open_new_trade`       — atomik pozisyon açılışı

    Her kapı bir engel sözlüğü döndürüp kısa devre yapar (sessiz düşme yok).
    Açık pozisyon varsa TP güncellemesine (`_update_existing_trade`) yönlenir.
    """
    try:
        # 1) Ayar + kimlik + skor/mod kapıları
        settings, block, symbol, rule_signal = await _entry_context(notification)
        if block is not None:
            return block
        if not symbol:
            return None

        # Açık pozisyon tek okuma: dedup + TP-güncelleme kararı paylaşır
        open_trade = await database.get_open_auto_paper_trade(symbol)

        # 2) Dedup + akıllı-para/rejim/LLM/trap kapıları
        block = await _compute_entry_gates(notification, symbol, settings, open_trade)
        if block is not None:
            return block

        # 3) Sessiz saat + cooldown kapıları
        block = await _cooldown_gate(notification, symbol, settings)
        if block is not None:
            return block

        # 4) Fiyat + tazelik + MTF konfluans
        current_price, block = await _resolve_entry_price(notification, symbol, settings)
        if block is not None:
            return block

        # 5) Aynı bildirim / yeniden-açma kapısı
        block = await _reopen_gate(notification, symbol, settings, current_price)
        if block is not None:
            return block

        # Açık pozisyon varsa yeni giriş yok — yalnız TP'yi güncelle
        if open_trade:
            return await _update_existing_trade(open_trade, notification, current_price)

        # 6) Global maksimum açık pozisyon tavanı
        block = await _max_open_gate(symbol, settings, current_price)
        if block is not None:
            return block

        # 7) Sizing + likidite/korelasyon küme kapısı
        balance, order_value, block = await _sizing_gate(notification, symbol, settings)
        if block is not None:
            return block

        # 8) Yeni pozisyon aç (atomik; DB tarafında çift-açılış kontrolü de var)
        return await _open_new_trade(symbol, notification, current_price, settings,
                                     order_value=order_value, balance=balance)
    except Exception as exc:
        logger.exception("auto_paper try_open: %s", exc)
        return _blocked(str((notification or {}).get("symbol") or "?").upper(),
                        f"exception:{type(exc).__name__}", error=str(exc)[:160])




async def _resolve_order_size(symbol: str, notification: dict, settings: dict, current_price: float,
                              order_value: float | None, balance: float | None
                              ) -> tuple[float | None, float | None, float, dict | None]:
    """Aşama 1 — bakiye/sizing + min emir kapısı. Dönüş: (balance, order_value, min_order, block)."""
    balance_pct = float(settings.get("balance_pct", config.AUTO_PAPER_BALANCE_PCT_DEFAULT)) / 100.0
    min_order = float(settings.get("min_order_try", config.AUTO_PAPER_MIN_ORDER_TRY))
    if balance is None:
        balance = await database.get_wallet_balance()
    if order_value is None:
        order_value = balance * balance_pct
    # 2026-10-27 (işlem planı): tavan tüm çarpanlardan sonra; küçük tavan min emre takılır (bilinçli).
    order_value = _plan_capped_order_value(order_value, notification)
    # RİSK SİZİNG fail-closed: geçerli emir üretemiyorsa AÇMA (R3-06 deseni).
    if order_value < min_order:
        quote = config.QUOTE_ASSET
        logger.warning(
            "auto_paper %s: risk bütçesi yetersiz (bakiye %.2f %s × %%%.1f = %.2f %s "
            "< min emir %.2f %s) — açılmadı; balance_pct/min_order_try ayarlayın",
            symbol, balance, quote, balance_pct * 100, order_value, quote, min_order, quote)
        return balance, order_value, min_order, _blocked(
            symbol, "order_below_min", price=current_price,
            order_value=round(order_value, 2), min_order=min_order,
            balance=round(balance, 2), balance_pct=round(balance_pct * 100, 2))
    return balance, order_value, min_order, None


def _exit_apply_ppo(symbol: str, sl_pct: float, target_pct: float, order_value: float,
                    ppo_apply: bool) -> tuple[float, float | None, float]:
    """PPO/RL adaptasyonu — yalnız kullanıcı planı/profili YOKKEN.

    Döner: (target_pct, ppo_sl_pct | None, order_value). SL önerisi ATR'den
    sonra birleştirilir; volatilite girdisi güncel `sl_pct`.
    """
    ppo_sl_pct: float | None = None
    try:
        from app.ai_trading_suite import evaluate_ppo_adaptive_policy
        ppo_action = evaluate_ppo_adaptive_policy(
            symbol=symbol, volatility_atr_pct=sl_pct * 100.0, daily_drawdown_pct=0.5)
        if ppo_apply:
            if ppo_action.recommended_tp_pct > 0:
                target_pct = max(target_pct, ppo_action.recommended_tp_pct * 100.0)
            if ppo_action.recommended_sl_pct > 0:
                ppo_sl_pct = max(0.006, min(0.028, ppo_action.recommended_sl_pct))
            if ppo_action.position_size_multiplier != 1.0:
                order_value = order_value * ppo_action.position_size_multiplier
    except Exception as ppo_err:
        logger.debug("auto_paper %s PPO adaptasyonu atlandı: %s", symbol, ppo_err)
    return target_pct, ppo_sl_pct, order_value


def _exit_apply_volume_breakout(symbol: str, current_price: float, target_pct: float) -> float:
    """Wyckoff VSA & Volume Anomaly Breakout hedef adaptasyonu."""
    try:
        from app.ai_trading_suite import evaluate_volume_breakout
        vol_bo = evaluate_volume_breakout(symbol=symbol, price=current_price)
        if vol_bo.is_box_breakout and vol_bo.take_profit > current_price:
            bo_tp_pct = (vol_bo.take_profit - current_price) / current_price * 100.0
            if bo_tp_pct > target_pct:
                target_pct = min(12.0, max(target_pct, bo_tp_pct))
    except Exception as bo_err:
        logger.debug("auto_paper %s Volume breakout adaptasyonu atlandı: %s", symbol, bo_err)
    return target_pct


def _exit_volatility_sl(symbol: str, current_price: float, sl_pct: float,
                        volatility_sl_enabled: bool) -> float:
    """Volatiliteye duyarlı SL (ATR koruması, ATR stop'u yalnız GENİŞLETİR)."""
    effective_sl_pct = sl_pct
    if not volatility_sl_enabled:
        return effective_sl_pct
    try:
        from app.technical_analysis import _atr
        kline = market.get_ut_kline(symbol, "5m") or market.get_ut_kline(symbol, "1m")
        if kline:
            highs = kline.get("highs") or []
            lows = kline.get("lows") or []
            closes = kline.get("closes") or []
            if len(closes) >= 15:
                atr_val = _atr(highs, lows, closes, 14)
                if atr_val and current_price > 0:
                    atr_pct = atr_val / current_price
                    effective_sl_pct = _effective_sl_pct(sl_pct, atr_pct)
    except Exception as atr_err:
        logger.debug("auto_paper %s: ATR stop hesaplama atlandı: %s", symbol, atr_err)
    return effective_sl_pct


def _exit_profile_context(plan_exit, exit_profile, now: float) -> tuple[str | None, float | None, str | None] | None:
    """Çıkış profili / tutma süresi / plan bağlamı.

    Döner: (trade_exit_profile, trade_max_hold, plan_context) ya da plan
    süresi dolduysa `None` (çağıran `plan_expired` bloğu üretir).
    """
    if plan_exit is not None:
        trade_exit_profile = PLAN_EXIT_PROFILE
        trade_max_hold = (plan_exit["exit_at"] - now + plan_exit["grace_minutes"] * 60) / 60.0
        if trade_max_hold <= 0:
            return None
        plan_context = json.dumps({"exit_at": plan_exit["exit_at"],
                                   "grace_minutes": plan_exit["grace_minutes"],
                                   "plan_key": plan_exit["plan_key"]})
    else:
        trade_exit_profile = exit_profile["name"] if exit_profile else None
        trade_max_hold = (float(exit_profile["max_hold_minutes"])
                          if exit_profile and exit_profile.get("max_hold_minutes") else None)
        plan_context = None
    return trade_exit_profile, trade_max_hold, plan_context


async def _calc_exit_plan(symbol: str, notification: dict, current_price: float, settings: dict,
                          order_value: float
                          ) -> tuple[dict | None, dict | None]:
    """Aşama 2 — çıkış planı: SL/TP yüzdeleri (profil/plan/PPO/volume-breakout),
    ATR koruması, hedef tavanı, komisyon+slippage ve fill/miktar.

    Dönüş: `(plan, block)`. `plan` = fill/quantity/tp/sl/exit_profile/max_hold/
    plan_context/target_pct/order_value/net_order_value. `block` doluysa iptal.
    """
    sl_pct = float(settings.get("stop_loss_pct", _exit_defaults()["stop_loss_pct"])) / 100.0
    _is_rule_signal = str(notification.get("source") or "") in _RULE_SIGNAL_SOURCES
    plan_exit = _plan_exit_params(notification)
    exit_profile = ma_buy_profiles.exit_overrides(notification) if (_is_rule_signal and plan_exit is None) else None
    if exit_profile and exit_profile.get("stop_loss_pct"):
        sl_pct = float(exit_profile["stop_loss_pct"]) / 100.0
    elif notification.get("sl_pct"):
        sl_pct = float(notification["sl_pct"]) / 100.0
    if plan_exit is not None:
        sl_pct = plan_exit["stop_pct"] / 100.0
    target_pct = _effective_target_pct(notification)

    # PPO/RL adaptasyonu: yalnız kullanıcı planı/profili YOKKEN.
    ppo_apply = exit_profile is None and plan_exit is None
    target_pct, ppo_sl_pct, order_value = _exit_apply_ppo(
        symbol, sl_pct, target_pct, order_value, ppo_apply)

    target_pct = _exit_apply_volume_breakout(symbol, current_price, target_pct)

    if target_pct <= 0:
        target_pct = float(settings.get("default_target_pct", config.AUTO_PAPER_DEFAULT_TARGET_PCT))

    # Master Surge TP2: nihai hedef TP2 ise — TP FİYATI hesaplanmadan ÖNCE uygulanır.
    tp1_scalp_val = notification.get("tp1_scalp_pct")
    tp2_runner_val = notification.get("tp2_runner_pct")
    if plan_exit is None and tp2_runner_val and float(tp2_runner_val) > target_pct:
        target_pct = float(tp2_runner_val)

    # Hedef tavanı (0 = sınırsız).
    max_target = float(settings.get("max_target_pct", 0.0) or 0.0)
    if plan_exit is None and max_target > 0 and target_pct > max_target:
        logger.info("auto_paper %s: bildirim hedefi +%.2f%% tavanı +%.2f%%'e çekildi",
                    symbol, target_pct, max_target)
        target_pct = max_target

    commission_pct = paper_ledger.commission_pct()
    max_cost = order_value / (1 + commission_pct)
    entry_slip = paper_ledger.slippage_pct()
    fill_entry = paper_ledger.entry_fill(current_price, entry_slip)
    quantity = max_cost / fill_entry if fill_entry > 0 else 0
    if quantity <= 0:
        return None, _blocked(symbol, "zero_quantity", price=current_price)

    net_order_value = fill_entry * quantity
    cost_markup = paper_ledger.round_trip_markup(commission_pct, entry_slip, exit_kind="take_profit")
    if plan_exit is not None:
        # Plan brüt hedefi ücret+kaymayı ZATEN içerir → mark-up ikinci kez eklenmez.
        target_pct = plan_exit["target_pct"]
        cost_markup = 0.0
    take_profit_price = fill_entry * (1 + target_pct / 100 + cost_markup)

    # Volatiliteye duyarlı SL (ATR koruması; yalnız GENİŞLETİR).
    volatility_sl_enabled = (bool(settings.get("volatility_sl_enabled", True)) and not exit_profile
                             and plan_exit is None)
    effective_sl_pct = _exit_volatility_sl(symbol, current_price, sl_pct, volatility_sl_enabled)
    # PPO SL: yalnız volatilite SL açıkken ve stopu GENİŞLETİYORSA (asla daraltmaz).
    if ppo_apply and volatility_sl_enabled and ppo_sl_pct is not None:
        effective_sl_pct = max(effective_sl_pct, ppo_sl_pct)

    stop_loss_price = fill_entry * (1 - effective_sl_pct)
    now = time.time()

    profile_ctx = _exit_profile_context(plan_exit, exit_profile, now)
    if profile_ctx is None:
        return None, _blocked(symbol, "plan_expired", price=current_price,
                              exit_at=plan_exit["exit_at"], grace_minutes=plan_exit["grace_minutes"])
    trade_exit_profile, trade_max_hold, plan_context = profile_ctx

    return {
        "fill_entry": fill_entry,
        "quantity": quantity,
        "net_order_value": net_order_value,
        "take_profit_price": take_profit_price,
        "stop_loss_price": stop_loss_price,
        "target_pct": target_pct,
        "order_value": order_value,
        "now": now,
        "tp1_scalp_val": tp1_scalp_val,
        "tp2_runner_val": tp2_runner_val,
        "trade_exit_profile": trade_exit_profile,
        "trade_max_hold": trade_max_hold,
        "plan_context": plan_context,
    }, None


def _build_trade_record(symbol: str, notification: dict, plan: dict, settings: dict
                        ) -> tuple[dict, dict]:
    """Aşama 3 — `trade_data` + `signal` sözlüklerini kurar (DB insert girdisi)."""
    now = plan["now"]
    # R3-09 (P0): notification_id bigint'e yalnız TAM SAYI; string id → key (TEXT).
    raw_nid = notification.get("id")
    notification_id_val = None
    if isinstance(raw_nid, int):
        notification_id_val = raw_nid
    elif isinstance(raw_nid, str) and raw_nid.lstrip("-").isdigit():
        notification_id_val = int(raw_nid)
    notification_key = notification.get("notification_key")

    fill_entry = plan["fill_entry"]
    trade_data = {
        "symbol": symbol,
        "side": "LONG",
        "status": "open",
        "notification_id": notification_id_val,
        "notification_key": notification_key,
        "entry_price": fill_entry,
        "quantity": plan["quantity"],
        "order_value_try": plan["net_order_value"],
        "stop_loss": plan["stop_loss_price"],
        "take_profit": plan["take_profit_price"],
        "peak_price": fill_entry,
        "entry_time": now,
        "notification_score": notification.get("score"),
        "notification_target_pct": plan["target_pct"],
        "notification_expected_price": notification.get("expected_price"),
        "tp1_scalp_pct": float(plan["tp1_scalp_val"]) if plan["tp1_scalp_val"] is not None else None,
        "tp2_runner_pct": float(plan["tp2_runner_val"]) if plan["tp2_runner_val"] is not None else None,
        "confluence_4way": bool(notification.get("confluence_4way")),
        "trailing_gap_pct": float(getattr(config, "MASTER_SURGE_BE_GAP_PCT", 0.40)) if notification.get("confluence_4way") else None,
        "exit_profile": plan["trade_exit_profile"],
        "max_hold_minutes": plan["trade_max_hold"],
        "plan_context": plan["plan_context"],
        "created_at": now,
        "updated_at": now,
    }
    signal = {
        "timestamp": now,
        "symbol": symbol,
        "action": "BUY_SIGNAL",
        "price": fill_entry,
        "reason": (f"AUTO_PAPER skor {notification.get('score', 0):.1f} hedef +%{plan['target_pct']:.1f} "
                   f"TP={plan['take_profit_price']:.6f} SL={plan['stop_loss_price']:.6f}"),
        "strategy": "AUTO_PAPER",
        "trade_id": None,
        "max_open_positions": int(settings.get("max_open_positions",
                                 getattr(config, "AUTO_PAPER_MAX_OPEN_POSITIONS", 0))),
    }
    return trade_data, signal


async def _apply_post_open_effects(symbol: str, notification: dict, plan: dict, current_price: float,
                                   trade_id: int) -> None:
    """Aşama 5 — açılış sonrası yan etkiler: state, giriş gecikmesi, akış evreni, WS, log."""
    fill_entry = plan["fill_entry"]
    now = plan["now"]
    _AUTO_PAPER_STATE["total_opened"] += 1
    # 2026-10-16 (giriş gecikmesi): yalnız gözlem; hata girişi bozmaz.
    record_entry_latency(symbol, trade_id, now, fill_entry, notification, market_price=current_price)

    # Açılan sembolü anında akış evrenine ekle (WS/tazelik verisi canlı aksın).
    try:
        extend_stream_universe([symbol], source="auto_paper_open")
        asyncio.create_task(market.ensure_history(config.PRIORITY_TIMEFRAMES, symbols=[symbol.lower()]))
    except Exception as exc:
        logger.warning("auto_paper %s akış evrenine ekleme hatası: %s", symbol, exc)

    await _broadcast_trade({
        "action": "OPENED", "symbol": symbol,
        "entry": fill_entry, "take_profit": plan["take_profit_price"],
        "stop_loss": plan["stop_loss_price"], "quantity": plan["quantity"],
        "order_value": plan["net_order_value"], "score": notification.get("score"),
        "target_pct": plan["target_pct"], "trade_id": trade_id,
    })

    logger.info("auto_paper %s: AÇILDI miktar=%.4f giriş=%.6f TP=%.6f SL=%.6f değer=%.2f %s skor=%.1f",
                symbol, plan["quantity"], fill_entry, plan["take_profit_price"], plan["stop_loss_price"],
                plan["net_order_value"], config.QUOTE_ASSET, notification.get("score"))


async def _handle_open_status(symbol: str, notification: dict, current_price: float,
                              trade: dict | None, status: str) -> dict | None:
    """Aşama 4 — DB açılış sonucu dallanması. Dönüş: açıldıysa trade_id içeren dict, yoksa None."""
    if status == "already_open":
        # Arada başka bir çağrı açmış — TP güncellemesini dene.
        open_trade = await database.get_open_auto_paper_trade(symbol)
        if open_trade:
            return await _update_existing_trade(open_trade, notification, current_price)
        return None
    if status == "already_traded":
        raw_nid = notification.get("id")
        notification_id_val = (raw_nid if isinstance(raw_nid, int)
                               else int(raw_nid) if isinstance(raw_nid, str) and raw_nid.lstrip("-").isdigit()
                               else None)
        logger.info("auto_paper %s: bildirim id=%s key=%s zaten işlendi — açılmadı",
                    symbol, notification_id_val, notification.get("notification_key"))
        return None
    if status == "max_open":
        logger.warning("auto_paper %s: transaction içinde max açık pozisyon dolu — açılmadı", symbol)
        return None
    if status == "insufficient_balance":
        logger.info("auto_paper %s: transaction'da bakiye yetersiz", symbol)
        return None
    if not trade or status != "opened":
        return None
    # Buradan itibaren `trade` bir açılış kaydıdır.
    return {"status": "opened"}


async def _open_new_trade(symbol: str, notification: dict, current_price: float, settings: dict,
                          order_value: float | None = None, balance: float | None = None) -> dict | None:
    """Yeni otonom paper pozisyonu aç — aşamalı orkestratör (atomik DB insert).

    Aşamalar:
      1. `_resolve_order_size`      — bakiye/sizing + min emir kapısı
      2. `_calc_exit_plan`          — SL/TP/ATR/PPO/volume-breakout/fill/miktar
      3. `_build_trade_record`      — trade_data + signal
      4. DB insert + `_handle_open_status` — sonuç dallanması
      5. `_apply_post_open_effects` — state/latency/akış evreni/WS/log

    R3-06: `order_value`/`balance` önceden verilmişse yeniden okunmaz (tutarlılık).
    """
    try:
        # 1) Sizing + min emir
        balance, order_value, _min_order, block = await _resolve_order_size(
            symbol, notification, settings, current_price, order_value, balance)
        if block is not None:
            return block

        # 2) Çıkış planı (SL/TP/fill/miktar)
        plan, block = await _calc_exit_plan(symbol, notification, current_price, settings, order_value)
        if block is not None:
            return block

        # 3) DB kayıt girdileri
        trade_data, signal = _build_trade_record(symbol, notification, plan, settings)

        # 4) Atomik insert + sonuç dallanması
        trade, status = await database.open_auto_paper_trade(trade_data, signal)
        handle = await _handle_open_status(symbol, notification, current_price, trade, status)
        if handle is None:
            return None
        if handle.get("status") != "opened":  # already_open → TP güncellemesi/no_change döndü
            return handle

        trade_id = trade["id"]

        # 5) Açılış sonrası yan etkiler
        await _apply_post_open_effects(symbol, notification, plan, current_price, trade_id)

        return {"status": "opened", "trade_id": trade_id, "symbol": symbol}

    except Exception as exc:
        logger.exception("auto_paper %s açılış hatası: %s", symbol, exc)
        return None


async def _update_existing_trade(open_trade: dict, notification: dict, current_price: float) -> dict | None:
    """Açık pozisyon için TP'yi bildirimdeki yeni hedefle güncelle."""
    # TP KORUMALI TRAILING (2026-09-28): trailing aktifken de yeni bildirim
    # TP'yi YUKARI güncelleyebilir — çıkış hedefini iyileştirir. Aşağı
    # çekmek engellenir (satır 726'daki `new_tp > old_tp` koruması yeterli).
    # Eski davranış (2026-09-18): trailing aktifken TP güncelleme tamamen
    # engelleniyordu çünkü TP siliniyordu. Artık TP korunduğu için
    # güncellemeye izin vermek mantıklı.
    # 2026-10-27 (işlem planı): plan işleminin hedefi DONDURULMUŞTUR — sonraki bildirim TP'ye dokunmaz.
    # `no_change` reopen akışında başarı sayılır (_blocked docstring'i).
    if open_trade.get("exit_profile") == PLAN_EXIT_PROFILE:
        return {"status": "no_change", "trade_id": open_trade["id"], "symbol": open_trade["symbol"]}
    try:
        target_pct = _effective_target_pct(notification)
        if target_pct <= 0:
            return None

        entry_price = float(open_trade["entry_price"])
        # ERKAN İSTEĞİ (2026-09-18): TP-güncelleme de NET hedefe göre — giriş
        # kapasıyla AYNI mark-up (`_open_new_trade` ile tutarlı); aksi halde
        # güncellenen pozisyonun hedefi mark-up'sız kalırdı.
        cost_markup = paper_ledger.round_trip_markup(exit_kind="take_profit")
        new_tp = entry_price * (1 + target_pct / 100 + cost_markup)
        old_tp = float(open_trade.get("take_profit") or 0)

        # TP-CANCEL-ON-TRAIL (2026-10-09, DIRILMEME GARANTISI): TP bir kez iptal
        # edildiyse (tp_cancelled) bildirim hedefi TP'yi YENIDEN YAZMAZ; aksi
        # halde sabit TP geri dirilir ve 2026-09-18 hatasi tekrarlanir. DB
        # `update_auto_paper_trade_tp` de ayni bayrakla korur (savunma derinligi).
        if bool(open_trade.get("tp_cancelled", False)):
            logger.info("auto_paper %s: TP iptal edilmiş (tp_cancel_on_trail) — bildirim hedefi TP'yi yeniden yazmıyor",
                        open_trade["symbol"])
            return {"status": "no_change", "trade_id": open_trade["id"], "symbol": open_trade["symbol"]}

        # TP sadece yükseliyorsa güncelle (hedefe ulaşıp düzeltmeden sonra
        # yeni çıkış sinyali TP'yi yukarı taşır; aşağı çekmek kârı sınırlandırır).
        if new_tp > old_tp:
            await database.update_auto_paper_trade_tp(
                open_trade["id"], new_tp, notification.get("score"), target_pct)

            logger.info("auto_paper %s: TP güncellendi %.6f → %.6f",
                        open_trade["symbol"], old_tp, new_tp)

            return {"status": "tp_updated", "trade_id": open_trade["id"], "symbol": open_trade["symbol"]}
        return {"status": "no_change", "trade_id": open_trade["id"], "symbol": open_trade["symbol"]}
    except Exception as exc:
        logger.exception("auto_paper %s TP güncelleme hatası: %s", open_trade.get("symbol"), exc)
        return None


def _effective_target_pct(notification: dict) -> float:
    """Bildirimden kullanılacak TP yüzdesi — TEK KAYNAK: ``target_pct``.

    ``target_pct`` üretim tarafında (``velocity.dynamic_target_pct``) zaten
    harmanlanmıştır: skor bandı + öğrenilmiş sembol hedefi + güvenli ML tahmini.
    Burada ``ml_target_pct``'i TEKRAR okumak ML'i iki kez uygulardı — harman onu
    bilinçli olarak seyreltirken ``max`` geri yükseltir (2026-09-17 denetimi).
    ML davranışını değiştirmek isteyen tek yer ``dynamic_target_pct``dir.
    """
    return float(notification.get("target_pct") or 0)


# ---------------------------------------------------------------------------
# Background loop: pozisyon yönetimi (SL/TP/breakeven)
# ---------------------------------------------------------------------------
async def auto_paper_management_loop():
    """Her ~5 saniyede bir açık auto_paper pozisyonlarını kontrol et.

    - TP'ye ulaşıldıysa kapat (kâr)
    - SL'ye ulaşıldıysa kapat (zarar)
    - +breakeven_trigger_pct kâra geçtiyse stop'u maliyet üstüne çek
    """
    logger.info("auto_paper yönetim döngüsü başladı")
    await asyncio.sleep(_LOOP_STARTUP_DELAY_SEC)
    # D-16 (2026-09-12): hata durumunda üstel backoff (5 → 60 sn) ve
    # `consecutive_errors` sayacı. Eskiden kalıcı DB/REST hatasında 5 sn'de bir
    # denenip log gürültüsü + boşa yük üretiliyordu. Başarılı turda taban
    # gecikmeye ve sayaç 0'a döner; liveness korunur (CancelledError re-raise).
    backoff_sec = 5.0
    while True:
        try:
            await _check_open_positions()
            backoff_sec = 5.0
            _AUTO_PAPER_STATE["consecutive_errors"] = 0
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            errors = int(_AUTO_PAPER_STATE.get("consecutive_errors", 0)) + 1
            _AUTO_PAPER_STATE["consecutive_errors"] = errors
            backoff_sec = min(60.0, 5.0 * (2 ** (errors - 1)))
            logger.warning("auto_paper yönetim turu hatası (ardışık=%d, %.0fs sonra tekrar): %s",
                           errors, backoff_sec, exc)
        await asyncio.sleep(backoff_sec)


async def _check_open_positions():
    """Tüm açık auto_paper pozisyonlarını tara ve yönet."""
    # P0-3 (2026-10-07, KRİTİK): `apply_reports_baseline=False`. Pozisyon
    # yönetimi (SL/TP/max_hold/trailing) bir RAPOR/TELEMETRİ filtresiyle
    # yönetilemez. `list_auto_paper_trades` varsayılanı RAPOR BAŞLANGICI
    # (`reports_baseline`) alt sınırını `entry_time` üzerinden uygular; bundan
    # eski açık pozisyonlar hiç taranmaz → SL/TP/trailing UYGULANMAZ ve
    # pozisyon sonsuza dek "açık" kalıp telemetriyi de kirletir. Reset cutoff
    # (ilk argüman) YİNE uygulanır; kaldırılan yalnızca rapor filtresidir.
    trades = await database.list_auto_paper_trades(
        status="open", apply_reports_baseline=False)
    if not trades:
        return

    now = time.time()
    # Breakeven eşiğini turlar arasında bir kez yükle (her trade için DB'ye gitme)
    settings = await get_auto_paper_settings()
    breakeven_trigger_pct = float(settings.get("breakeven_trigger_pct", config.AUTO_PAPER_BREAKEVEN_TRIGGER_PCT))

    for trade in trades:
        try:
            await _manage_single_trade(trade, now, breakeven_trigger_pct, settings)
        except Exception as exc:
            logger.warning("auto_paper %s yönetim: %s", trade.get("symbol"), exc)

    _AUTO_PAPER_STATE["last_check_at"] = now


async def _fresh_trade_price(trade: dict, symbol: str, now: float):
    """Tazelik kapısı: WS ticker + REST yedeği. Döner: (current_price, price_is_fresh, last_known_price)."""
    # Güncel fiyat
    ticker = market.get_ticker(symbol)
    current_price = float(ticker.get("last_price") or 0) if ticker else 0
    # D-02 (2026-09-26 denetimi): TAZELİK KAPISI TÜM ÇIKIŞ YOLLARININ
    # ÖNÜNE alınır. Bayat/eksik ticker fiyatıyla kapanmak (aşağıdaki
    # max_hold ve symbol_deactivated yolları) gerçekleşmeyen bir fill fiyatı
    # yazar. Aynı desen SL/TP yollarında zaten uygulanıyordu; bu iki erken
    # çıkışta eksikti.
    # NOT: `ticker` hiç yoksa veya timestamp boşsa fiyat KULLANILAMAZ; ancak
    # bu turda hiçbir kâr/zarar muhasebesi yapmadan "veri yok" diye bir
    # sonraki turda yeniden denemek yerine pozisyon dokunulmadan bırakılır
    # (süre/sembol çıkışı da aynı turda ertelenir — en kötü halde bir sonraki
    # turlarda taze fiyatla kapanır).
    ticker_ts = float((ticker or {}).get("timestamp") or 0)
    price_is_fresh = bool(current_price > 0 and paper_ledger.is_fresh(ticker_ts, now))
    # Son bilinen fiyat (bayat ticker, yoksa DB tepe/giriş) — yalnız zorla kapanışta kullanılır.
    last_known_price = current_price if current_price > 0 else float(trade.get("peak_price") or float(trade["entry_price"]))
    # Log gürültü kapısı (2026-11-10, flap düzeltmesi): likit olmayan/15-20 sn
    # kadanslı sembollerde her tur uyarı yerine sembol başına aralıkta bir.
    # Sayaç YAPIŞKANDIR — ara tazelik anları sıfırlamaz. REST yedeği her turda
    # çalışır.
    _stale_logged = False
    if current_price > 0 and not price_is_fresh:
        _stale_logged = _stale_ticker_log_gate(symbol, now)
        if _stale_logged:
            logger.warning("auto_paper %s: ticker BAYAT (yaş=%.1fs > %ss) — REST fiyat yedeği deneniyor (bu satır sembol başına %d sn'de bir)",
                           symbol, (now * 1000 - ticker_ts) / 1000.0, config.MAX_TICKER_AGE_SEC,
                           int(_STALE_TICKER_LOG_INTERVAL_SEC))
    # 2026-10-15 (denetim düzeltmesi, madde 1): ticker bayat/eksikse ESKİDEN bu
    # tur erken dönülüyor, SL/trailing/max_hold hiç çalışmıyordu (WS akışında
    # olmayan sembolde pozisyon süresiz "izleniyor"da kalırdı). Artık REST
    # (`api_common._fresh_public_price`) ile taze fiyat alınır ve yönetim
    # NORMAL sürer; REST de başarısızsa bu tur ertelenir (zorla kapanış hariç).
    if not price_is_fresh:
        rest_price = None
        try:
            rest_price, _rest_info = await _fresh_public_price(symbol)
        except Exception as rest_exc:
            if _stale_logged:
                logger.warning("auto_paper %s: REST fiyat yedeği hatası: %s", symbol, rest_exc)
            else:
                logger.debug("auto_paper %s: REST fiyat yedeği hatası (tekrar): %s", symbol, rest_exc)
        if rest_price and float(rest_price) > 0:
            current_price = float(rest_price)
            price_is_fresh = True
            if _stale_logged:
                logger.info("auto_paper %s: bayat/eksik ticker yerine REST fiyatı kullanıldı (%.6f)",
                            symbol, current_price)
    return current_price, price_is_fresh, last_known_price


def _hold_effective_stop(trade: dict) -> tuple[float | None, float | None, bool]:
    """Başabaş koruması dahil efektif stop. Döner: (stop_loss, effective_stop_loss, tp_cancelled)."""
    stop_loss = float(trade["stop_loss"]) if trade.get("stop_loss") else None
    _breakeven_stop_db = float(trade.get("breakeven_stop") or 0)
    _breakeven_activated_db = bool(trade.get("breakeven_activated", False))
    effective_stop_loss = stop_loss
    if _breakeven_activated_db and _breakeven_stop_db > 0:
        effective_stop_loss = max(stop_loss, _breakeven_stop_db) if stop_loss is not None else _breakeven_stop_db
    elif _breakeven_stop_db > 0:
        # Breakeven fiyatı yazılmış ama bayrak henüz set edilmemişse de
        # (DB yazma sırası/yarış durumu) kâr koruması geçerlidir.
        effective_stop_loss = max(stop_loss, _breakeven_stop_db) if stop_loss is not None else _breakeven_stop_db
    return stop_loss, effective_stop_loss, bool(trade.get("tp_cancelled", False))


def _hold_limit_minutes(trade: dict, settings: dict | None) -> float:
    """Tutma süresi tavanı (profilli işlem kendi süresini taşır)."""
    max_hold_minutes = float((settings or {}).get("max_hold_minutes", getattr(config, "AUTO_PAPER_MAX_HOLD_MINUTES", 120.0)))
    # 2026-10-21: çıkış profilli işlem (MA BUY H4) kendi tutma süresini taşır; iz süren stop kuralı
    # profilden gelir, başabaş stop profilli işlemde uygulanmaz.
    _trade_hold = trade.get("max_hold_minutes")
    if trade.get("exit_profile") and _trade_hold:
        max_hold_minutes = float(_trade_hold)
    return max_hold_minutes


async def _hold_stale_force_close(symbol: str, trade_id: int, now: float, hold_minutes: float,
                                  max_hold_minutes: float, price_is_fresh: bool,
                                  last_known_price: float) -> bool:
    """1. SÜRE KONTROLÜ: taze fiyat yoksa ve süre aşıldıysa son bilinen fiyatla ZORLA kapat.

    Varsayılan `config.AUTO_PAPER_MAX_HOLD_MINUTES` (120 dk; 2026-09-21 Erkan
    kararı 60 dk idi, 2026-10-07 optimizasyonuyla 120'ye çıkarıldı — gerekçe
    config.py'de). Taze (WS ya da REST) fiyatla kapanır; fiyat yoksa bir sonraki
    tura ertelenir. REST de başarısızsa ve süre max_hold ×
    AUTO_PAPER_STALE_FORCE_CLOSE_FACTOR'ü aştıysa son bilinen fiyatla ZORLA
    kapatılır (madde 1) — pozisyon sonsuza dek açık kalamaz.
    """
    if price_is_fresh or max_hold_minutes <= 0:
        return False
    if hold_minutes < max_hold_minutes * _STALE_FORCE_CLOSE_FACTOR:
        return False
    logger.warning("auto_paper %s: taze fiyat alınamıyor ve süre %.1f dk >= max_hold %.0f dk × %.1f — "
                   "son bilinen fiyatla ZORLA kapatılıyor (çıkış=%.6f)",
                   symbol, hold_minutes, max_hold_minutes, _STALE_FORCE_CLOSE_FACTOR, last_known_price)
    await _close_trade(trade_id, symbol, paper_ledger.exit_fill("stale_force_close", last_known_price),
                       now, "stale_force_close")
    return True


async def _hold_plan_exit(trade: dict, symbol: str, trade_id: int, now: float, hold_minutes: float,
                          current_price: float, price_is_fresh: bool, entry_price: float,
                          stop_loss: float | None, effective_stop_loss: float | None,
                          take_profit: float | None, tp_cancelled: bool) -> bool:
    """2026-10-27 (işlem planı): plan çıkış zamanı geldiyse piyasa çıkışı.

    max_hold (= exit_at + ek süre) bundan SONRA; taze fiyat yoksa bu tur ertelenir.
    """
    if not (trade.get("exit_profile") == PLAN_EXIT_PROFILE and price_is_fresh and current_price > 0):
        return False
    _plan_ctx = _trade_plan_context(trade)
    if _plan_ctx is None or _plan_ctx.get("exit_at") is None:
        return False
    commission_pct = paper_ledger.commission_pct()
    try:
        _advice = notification_plan.exit_advice(_plan_ctx, entry_price, current_price, now,
                                                commission_pct)
    except Exception as plan_exc:
        logger.warning("auto_paper %s: plan çıkış önerisi hatası: %s", symbol, plan_exc)
        _advice = None
    if _advice != "cik":
        return False
    # Hedef / stop aynı anda tetiklendiyse onlar kendi adı ve dolum modeliyle kapanır.
    if not tp_cancelled and take_profit is not None and current_price >= take_profit:
        await _close_trade(trade_id, symbol, paper_ledger.exit_fill("take_profit", current_price, take_profit),
                           now, "take_profit")
        return True
    if effective_stop_loss is not None and current_price <= effective_stop_loss:
        _sl_reason = "breakeven_stop" if (effective_stop_loss != stop_loss) else "stop_loss"
        await _close_trade(trade_id, symbol,
                           paper_ledger.exit_fill(_sl_reason, current_price, effective_stop_loss),
                           now, _sl_reason)
        return True
    logger.info("auto_paper %s: PLAN SÜRESİ DOLDU (%.1f dk) — pozisyon kapatılıyor (çıkış=%.6f)",
                symbol, hold_minutes, current_price)
    await _close_trade(trade_id, symbol, paper_ledger.exit_fill(PLAN_EXIT_REASON, current_price),
                       now, PLAN_EXIT_REASON)
    return True


async def _hold_time_stop(symbol: str, trade_id: int, now: float, hold_minutes: float,
                          current_price: float, price_is_fresh: bool, entry_price: float) -> bool:
    """2026-10-15 (radar iyileştirme): ZAMAN-DURDURMA — max_hold'dan ÖNCE.

    Süre `hold_minutes` ile, kâr canlı `gross_pnl_pct` ile AYNI formülle
    (brüt, komisyonsuz) ölçülür. Taze fiyat yoksa bu tur ertelenir (D-02).
    Flag 0 iken bu blok hiç çalışmaz (davranış değişmez).
    """
    if not (AUTO_PAPER_TIME_STOP_MIN > 0 and price_is_fresh and current_price > 0
            and hold_minutes >= AUTO_PAPER_TIME_STOP_MIN):
        return False
    _ts_gross_pct = ((current_price - entry_price) / entry_price * 100) if entry_price else 0
    if _ts_gross_pct >= AUTO_PAPER_TIME_STOP_MIN_PROFIT_PCT:
        return False
    logger.info("auto_paper %s: ZAMAN-DURDURMA (%.1f dk >= %.1f dk, kâr %+.2f%% < %.2f%%) — pozisyon kapatılıyor (çıkış=%.6f)",
                symbol, hold_minutes, AUTO_PAPER_TIME_STOP_MIN, _ts_gross_pct,
                AUTO_PAPER_TIME_STOP_MIN_PROFIT_PCT, current_price)
    # Piyasa çıkışı: anlık fiyattan dolar. `paper_ledger.exit_fill` burada
    # KULLANILMAZ — "time_stop" MARKET_EXITS'te tanımlı değil (ValueError).
    await _close_trade(trade_id, symbol, float(current_price), now, "time_stop")
    return True


async def _hold_max_duration(trade: dict, symbol: str, trade_id: int, now: float,
                             hold_minutes: float, max_hold_minutes: float,
                             price_is_fresh: bool, current_price: float, entry_price: float) -> bool:
    """MAKSİMUM SÜRE: süre dolduysa kapat (bayat fiyatla kapanış YOK, D-02)."""
    if max_hold_minutes <= 0 or hold_minutes < max_hold_minutes:
        return False
    # D-02: bayat/eksik fiyatla KAPANMA YAPILMAZ. Pozisyon bir sonraki
    # tazelik turunda kapatılır (gerekirse peak_price fallback'i ile
    # bilinçli olarak).
    if not price_is_fresh:
        logger.info("auto_paper %s: max_hold doldu ama fiyat bayat — kapanış ertelendi (%.1f dk)",
                    symbol, hold_minutes)
        return True
    exit_price = current_price if current_price > 0 else float(trade.get("peak_price") or entry_price)
    logger.info("auto_paper %s: MAKSİMUM SÜRE DOLDU (%.1f dk >= %.1f dk) — pozisyon kapatılıyor (çıkış=%.6f)",
                symbol, hold_minutes, max_hold_minutes, exit_price)
    await _close_trade(trade_id, symbol, paper_ledger.exit_fill("max_duration", exit_price), now, "max_duration")
    return True


async def _check_hold_exit(trade: dict, symbol: str, trade_id: int, now: float,
                           current_price: float, price_is_fresh: bool, last_known_price: float,
                           settings: dict | None):
    """Süre tabanlı çıkışlar: stale force close / plan süresi / zaman-durdurma / max_hold.

    Döner: True → pozisyon kapatıldı (çağıran dönmeli); False → devam.
    """
    entry_price = float(trade["entry_price"])
    stop_loss, effective_stop_loss, tp_cancelled = _hold_effective_stop(trade)
    take_profit = float(trade["take_profit"]) if trade.get("take_profit") else None
    entry_time = float(trade.get("entry_time") or trade.get("created_at") or 0)
    hold_minutes = (now - entry_time) / 60.0 if entry_time > 0 else 0.0
    max_hold_minutes = _hold_limit_minutes(trade, settings)

    if await _hold_stale_force_close(symbol, trade_id, now, hold_minutes, max_hold_minutes,
                                     price_is_fresh, last_known_price):
        return True
    if await _hold_plan_exit(trade, symbol, trade_id, now, hold_minutes, current_price,
                             price_is_fresh, entry_price, stop_loss, effective_stop_loss,
                             take_profit, tp_cancelled):
        return True
    if await _hold_time_stop(symbol, trade_id, now, hold_minutes, current_price,
                             price_is_fresh, entry_price):
        return True
    return await _hold_max_duration(trade, symbol, trade_id, now, hold_minutes,
                                    max_hold_minutes, price_is_fresh, current_price, entry_price)


async def _check_tp_sl_exit(trade: dict, symbol: str, trade_id: int, now: float, current_price: float,
                            settings: dict | None):
    """TP-primary + SL çıkışları; tepe güncellemesi. Döner: (kapandı: bool, peak_price)."""
    entry_price = float(trade["entry_price"])
    stop_loss = float(trade["stop_loss"]) if trade.get("stop_loss") else None
    take_profit = float(trade["take_profit"]) if trade.get("take_profit") else None
    tp_cancelled = bool(trade.get("tp_cancelled", False))
    _breakeven_stop_db = float(trade.get("breakeven_stop") or 0)
    _breakeven_activated_db = bool(trade.get("breakeven_activated", False))
    effective_stop_loss = stop_loss
    if _breakeven_activated_db and _breakeven_stop_db > 0:
        effective_stop_loss = max(stop_loss, _breakeven_stop_db) if stop_loss is not None else _breakeven_stop_db
    elif _breakeven_stop_db > 0:
        effective_stop_loss = max(stop_loss, _breakeven_stop_db) if stop_loss is not None else _breakeven_stop_db
    # TP-primary cikis (2026-10-09: VARSAYILAN KAPALI — bkz. get_default_settings
    # yorumu ve work/ab_tp_cancel.py). Acikken trailing/breakeven'DEN ONCE degerlendirilir.
    # 2026-10-16 (maliyet/çıkış): varsayılanlar çıkış profilinden (DB ayarı önce).
    _exit_def = _exit_defaults()
    tp_primary_exit_enabled = bool((settings or {}).get("tp_primary_exit_enabled", _exit_def["tp_primary_exit_enabled"]))
    # 2026-10-27 (işlem planı): plan işleminde hedefte satış genel ayardan bağımsız AÇIK.
    if trade.get("exit_profile") == PLAN_EXIT_PROFILE:
        tp_primary_exit_enabled = True
    if tp_primary_exit_enabled and not tp_cancelled and take_profit is not None and current_price >= take_profit:
        # D-08 (2026-09-12): TP dolumu TETİK fiyatından (gap-through: min(price, tp)).
        await _close_trade(trade_id, symbol, paper_ledger.exit_fill("take_profit", current_price, take_profit),
                           now, "take_profit")
        return True, None
    # Peak güncelle
    peak_price = max(float(trade.get("peak_price") or entry_price), current_price)
    if peak_price > float(trade.get("peak_price") or entry_price):
        await database.update_auto_paper_peak(trade_id, peak_price)
    # SL kontrolü — 2026-10-15 (denetim düzeltmesi, madde 2): stop dolumu
    # `min(price, stop)` = iki fiyatın KÖTÜSÜ. Eski D-08 `max(price, stop)`
    # gap'te stop'un altına düşen fiyatı yok sayıp stop fiyatından doluyor,
    # zararı sistematik küçük / PnL'i iyimser yazıyordu. TP dolumu değişmedi.
    # D-01 (2026-09-26): burada ARTIK `stop_loss` değil `effective_stop_loss`
    # kullanılır — kâr kilidi aktifken orijinal stop'tan daha yüksekte
    # kapanış olur (aşağıdaki breakeven korumasıyla aynı mantık).
    if effective_stop_loss is not None and current_price <= effective_stop_loss:
        sl_reason = "breakeven_stop" if (effective_stop_loss != stop_loss) else "stop_loss"
        await _close_trade(trade_id, symbol, paper_ledger.exit_fill(sl_reason, current_price, effective_stop_loss),
                           now, sl_reason)
        return True, peak_price
    return False, peak_price

async def _apply_breakeven(trade: dict, symbol: str, trade_id: int, now: float, current_price: float,
                           entry_price: float, peak_price: float, gross_pnl_pct: float, tp_gain_pct,
                           breakeven_trigger_pct: float, settings: dict | None,
                           profile_no_trail: bool, profile_no_breakeven: bool, is_plan_trade: bool):
    """Breakeven kâr kilidi. Döner: (kapandı: bool, breakeven_enabled: bool, trail_gap_pct: float)."""
    _exit_def = _exit_defaults()
    breakeven_enabled = bool((settings or {}).get("breakeven_enabled", getattr(config, "AUTO_PAPER_BREAKEVEN_ENABLED", False))) \
        and not profile_no_trail and not profile_no_breakeven and not is_plan_trade
    BREAKEVEN_TRAIL_GAP_PCT = float(_exit_def["trailing_gap_pct"])  # 2026-10-16 (maliyet/çıkış): profil
    if not breakeven_enabled:
        return False, breakeven_enabled, BREAKEVEN_TRAIL_GAP_PCT
    breakeven_activated = bool(trade.get("breakeven_activated", False))
    # B2: Dynamic profit-lock triggers tied to TP target (Tavan korumalı)
    dynamic_breakeven_enabled = bool((settings or {}).get("dynamic_breakeven_enabled", getattr(config, "AUTO_PAPER_DYNAMIC_BREAKEVEN_ENABLED", False)))
    # Master Surge Dinamik Uyarlanabilir Hedef Kilidi (2026-09-21):
    # 158 sinyallik testte gözlenen %71 kısmi kazancı (+%1.0-%3.7) korumak için
    # TP1 seviyesine (+%1.2-%1.8) ulaşıldığında kâr kilidi derhal devreye girer.
    # Standart (Master Surge olmayan) işlemler gerileme koruması gereği etkilenmez.
    raw_tp1 = trade.get("tp1_scalp_pct")
    is_master_surge = bool(trade.get("confluence_4way") or (raw_tp1 is not None and float(raw_tp1) > 0))
    if is_master_surge:
        tp1_scalp = float(raw_tp1 or getattr(config, "MASTER_SURGE_TP1_MIN_PCT", 1.2))
        if gross_pnl_pct >= tp1_scalp:
            breakeven_trigger_pct = min(breakeven_trigger_pct, tp1_scalp)
    elif tp_gain_pct is not None and dynamic_breakeven_enabled:
        breakeven_trigger_pct = min(breakeven_trigger_pct, max(0.8, tp_gain_pct * 0.5))
    # B4: Narrow breakeven buffer (admin-editable, default 0.02)
    breakeven_buffer_pct = float((settings or {}).get("breakeven_buffer_pct", getattr(config, "AUTO_PAPER_BREAKEVEN_BUFFER_PCT", 0.02)))
    # Standart taban açıklık: config.AUTO_PAPER_TRAILING_GAP_PCT (TR %0.6);
    # Master Surge veya özel tanımlı işlemde sıkı takip (%0.40)
    custom_gap = trade.get("trailing_gap_pct")
    if custom_gap is not None and float(custom_gap) > 0:
        BREAKEVEN_TRAIL_GAP_PCT = float(custom_gap)
    elif is_master_surge:
        BREAKEVEN_TRAIL_GAP_PCT = float(getattr(config, "MASTER_SURGE_BE_GAP_PCT", 0.40))
    else:
        BREAKEVEN_TRAIL_GAP_PCT = float(_exit_def["trailing_gap_pct"])  # 2026-10-16 (maliyet/çıkış): profil
    # In-memory breakeven stop: DB'ye yazılan değerle aynı turdaki koruma
    # kontrolü arasında gecikme olmasın.
    current_breakeven_stop = float(trade.get("breakeven_stop") or 0)
    commission_pct = paper_ledger.commission_pct()
    if gross_pnl_pct >= breakeven_trigger_pct:
        # NET taban (2026-09-18 hassasiyeti): gidiş-dönüş komisyon + SATIŞ dolum
        # kayması dahil (giriş kayması zaten çapa fill_entry'de). Bu fiyattan
        # satış, `_close_trade` muhasebesi sonrası daima pozitif net verir.
        exit_slip = paper_ledger.slippage_pct()
        net_floor = entry_price * (1 + paper_ledger.round_trip_markup(commission_pct, exit_slip) + breakeven_buffer_pct / 100)
        trail_stop = peak_price * (1 - BREAKEVEN_TRAIL_GAP_PCT / 100)
        new_breakeven = max(net_floor, trail_stop)
        applied_breakeven = max(new_breakeven, current_breakeven_stop)
        if applied_breakeven < current_price:
            if not breakeven_activated or applied_breakeven > current_breakeven_stop:
                await database.update_auto_paper_breakeven(trade_id, True, applied_breakeven)
                current_breakeven_stop = applied_breakeven
                breakeven_activated = True
                logger.info("auto_paper %s: breakeven stop=%.6f (gross=%+.2f%%)", symbol, applied_breakeven, gross_pnl_pct)
    # Breakeven stop koruması (in-memory değer kullanılır, DB okuması değil).
    # 2026-10-15 (madde 2): dolum iki fiyatın KÖTÜSÜ (min), gap iyimser yazılmaz.
    if breakeven_activated and current_breakeven_stop > 0 and current_price <= current_breakeven_stop:
        await _close_trade(trade_id, symbol,
                           paper_ledger.exit_fill("breakeven_stop", current_price, current_breakeven_stop),
                           now, "breakeven_stop")
        return True, breakeven_enabled, BREAKEVEN_TRAIL_GAP_PCT
    return False, breakeven_enabled, BREAKEVEN_TRAIL_GAP_PCT


def _trailing_params(_profile_manage, settings: dict | None, tp_gain_pct,
                     gross_pnl_pct: float, breakeven_enabled: bool,
                     breakeven_trail_gap_pct: float) -> tuple[float, float] | None:
    """Trailing tetik/mesafe yüzdelerini çözer. Döner: (trigger, gap) ya da `None` (kapalı).

    2026-10-21 19:46: profilli işlemde (MA BUY H4) iz süren stop ayarlardan BAĞIMSIZ — profil açık
    diyorsa açık, tetik/mesafe profilden, dinamik tetik/mesafe ve breakeven kısıtı uygulanmaz
    (replay simülasyonuyla birebir).
    """
    _exit_def = _exit_defaults()
    if _profile_manage is not None:
        trailing_trigger_pct = float(_profile_manage["trailing_trigger_pct"])
        trailing_gap_pct = float(_profile_manage["trailing_gap_pct"])
        return trailing_trigger_pct, trailing_gap_pct
    # 2026-10-16 (maliyet/çıkış): varsayılanlar çıkış profilinden (DB ayarı önce).
    trailing_trigger_pct = float((settings or {}).get("trailing_trigger_pct", _exit_def["trailing_trigger_pct"]))
    trailing_gap_pct = float((settings or {}).get("trailing_gap_pct", _exit_def["trailing_gap_pct"]))
    # B2: Dynamic trailing trigger tied to TP target (Tavan korumalı)
    dynamic_trailing_enabled = bool((settings or {}).get("dynamic_trailing_enabled", getattr(config, "AUTO_PAPER_DYNAMIC_TRAILING_ENABLED", False)))
    if tp_gain_pct is not None and dynamic_trailing_enabled:
        trailing_trigger_pct = min(trailing_trigger_pct, max(1.2, tp_gain_pct * 0.6))
    # B3: Dynamic trailing gap compatible with TP
    if tp_gain_pct is not None and gross_pnl_pct >= tp_gain_pct * 0.9:
        trailing_gap_pct = max(0.2, trailing_gap_pct * 0.5)
    # Breakeven açıksa trailing gap'i kısıtla; breakeven kapalıysa kullanıcının
    # belirlediği geniş trailing mesafesine izin ver.
    if breakeven_enabled:
        trailing_gap_pct = min(trailing_gap_pct, breakeven_trail_gap_pct)
    return trailing_trigger_pct, trailing_gap_pct


async def _trailing_ratchet(symbol: str, trade_id: int, trade: dict, peak_price: float,
                            current_price: float, current_trailing_stop: float,
                            trailing_gap_pct: float, gross_pnl_pct: float) -> float:
    """Trailing stop'u zirvenin %gap gerisinden yukarı kilitler (yalnız yukarı). Döner: güncel stop."""
    # Zirvenin %gap gerisinden stop; yalnızca yukarı güncellenir (fiyat
    # yükseldikçe takip eder, düşerken eski stopta kalır).
    new_trailing = peak_price * (1 - trailing_gap_pct / 100)
    # İlk aktivasyonda stop güncel fiyatın altında kalmalı (anında kapanma olmasın).
    if not bool(trade.get("trailing_activated", False)) and new_trailing >= current_price:
        new_trailing = current_price * (1 - trailing_gap_pct / 100)
    applied_trailing = max(new_trailing, current_trailing_stop)
    if applied_trailing > current_trailing_stop:
        await database.update_auto_paper_trailing(trade_id, True, applied_trailing)
        logger.info("auto_paper %s: trailing stop=%.6f (gross=%+.2f%%)", symbol, applied_trailing, gross_pnl_pct)
        return applied_trailing
    return current_trailing_stop


async def _trailing_tp_cancel(symbol: str, trade_id: int, settings: dict | None) -> None:
    """TP-CANCEL-ON-TRAIL (2026-10-09, opsiyonel; varsayilan KAPALI).

    Trailing devreye girdigi AN sabit TP emri IPTAL edilir. Boylece fiyat eski
    TP hedefine takilmadan trailing ile tasinir.
    KANIT (work/ab_tp_cancel.py, 30 gun gercek Binance TR mumu, 1231 islem,
    maliyet %0.325): B (cancel) A'ya (ratchet) karsi +0.138% islem basi,
    wilcoxon p=2e-14, 5/6 bagimsiz pencerede, 18/18 parametre kombinasyonunda
    kazandi; train VE test pozitif.
    CANLI MUHIM NOT: TRIG (1.0) < TP (>=1.5) oldugu icin trailing TP'ye
    UGRAMADAN once devreye girer; pratikte bu davranis
    `AUTO_PAPER_TP_PRIMARY_ENABLED=false` ile ORTUSUR.
    DIRILMEME GARANTISI (2026-09-18 basarisizliginin kok nedeni): iptal
    DB'de `tp_cancelled=TRUE` olarak KALICIDIR. Bu turdan sonra sirasi:
     - TP-primary dali `not tp_cancelled` ile ateslemez (yukarida),
     - `update_auto_paper_trade_tp` (bildirim hedefi + ratchet) bayrak
       set oldugu icin TP YAZMAZ (tek-yol bekci) → geri diriltilemez.
    """
    tp_cancel_on_trail = bool((settings or {}).get("tp_cancel_on_trail", getattr(config, "AUTO_PAPER_TP_CANCEL_ON_TRAIL", False)))
    if not tp_cancel_on_trail:
        return
    # Bayragi DB'de set et (kalici). In-memory `tp_cancelled` de set
    # edilir ki ayni turda asagidaki ratchet dali tekrar silmesin.
    try:
        await database.cancel_auto_paper_trade_tp(trade_id)
    except Exception as cancel_exc:
        logger.warning("auto_paper %s: TP iptal hatası: %s", symbol, cancel_exc)
        return
    logger.info("auto_paper %s: trailing devreye girdi — sabit TP İPTAL edildi (tp_cancel_on_trail)", symbol)


async def _trailing_tp_ratchet(symbol: str, trade_id: int, applied_trailing: float,
                               take_profit, gross_pnl_pct: float):
    """TP KORUMALI TRAILING (2026-09-28, kârlılık düzeltmesi). Döner: güncel TP.

    Trailing devreye girdiğinde TP artık SİLİNMEZ. Fiyat TP'ye ulaşırsa → TP ile
    kapanır (garanti kâr). Fiyat TP'ye ulaşmadan geri dönerse → trailing stop ile
    kapanır (korumalı kâr). Trailing stop TP'nin ÜZERİNE çıkarsa TP yukarı
    ratchet'lenir. Böylece:
     - Fiyat tahmin edilen artışın üzerinde yükselirse pozisyon taşınır ✓
     - Fiyat hedefine ulaştığında kâr GERÇEKTEN alınır ✓
     - Küçük geri çekilmelerde trailing kilitler ✓
    """
    if take_profit is None or applied_trailing <= take_profit:
        return take_profit
    try:
        await database.update_auto_paper_trade_tp(trade_id, applied_trailing)
        logger.info("auto_paper %s: trailing TP'nin üstüne çıktı — TP ratchet: %.6f (gross=%+.2f%%)",
                    symbol, applied_trailing, gross_pnl_pct)
        return applied_trailing
    except Exception as tp_exc:
        logger.warning("auto_paper %s: TP ratchet hatası: %s", symbol, tp_exc)
        return take_profit


async def _apply_trailing(trade: dict, symbol: str, trade_id: int, now: float, current_price: float,
                          peak_price: float, gross_pnl_pct: float, tp_gain_pct,
                          settings: dict | None, _profile_manage, is_plan_trade: bool,
                          breakeven_enabled: bool, breakeven_trail_gap_pct: float,
                          tp_cancelled: bool, take_profit):
    """Trailing stop ratchet + TP ratchet/iptal. Döner: True → pozisyon kapatıldı."""
    # Trailing stop modülü (kullanıcı isteği 2026-09-08): %trailing_trigger_pct
    # kara geçince fiyatı %trailing_gap_pct geriden takip eder. Varsayılan AÇIK;
    # ayarlardan kapatılabilir (trailing_enabled=false).
    if is_plan_trade:
        trailing_enabled = False
    elif _profile_manage is not None:
        trailing_enabled = bool(_profile_manage["trailing"])
    else:
        trailing_enabled = bool((settings or {}).get("trailing_enabled", config.AUTO_PAPER_TRAILING_ENABLED))
    if not trailing_enabled:
        return False
    trailing_trigger_pct, trailing_gap_pct = _trailing_params(
        _profile_manage, settings, tp_gain_pct, gross_pnl_pct,
        breakeven_enabled, breakeven_trail_gap_pct)
    trailing_activated = bool(trade.get("trailing_activated", False))
    current_trailing_stop = float(trade.get("trailing_stop") or 0)
    # Aktif değilse ve kâr trigger eşiğine ulaşıldıysa trailing'i devreye al.
    if not trailing_activated and gross_pnl_pct >= trailing_trigger_pct:
        trailing_activated = True
    if trailing_activated:
        current_trailing_stop = await _trailing_ratchet(
            symbol, trade_id, trade, peak_price, current_price,
            current_trailing_stop, trailing_gap_pct, gross_pnl_pct)
        applied_trailing = current_trailing_stop
        if not tp_cancelled:
            await _trailing_tp_cancel(symbol, trade_id, settings)
            # DB iptali başarılıysa in-memory bayrak da güncellenir.
            if bool((settings or {}).get("tp_cancel_on_trail", getattr(config, "AUTO_PAPER_TP_CANCEL_ON_TRAIL", False))):
                tp_cancelled = True
                take_profit = None
        if not tp_cancelled:
            take_profit = await _trailing_tp_ratchet(
                symbol, trade_id, applied_trailing, take_profit, gross_pnl_pct)
    # Trailing stop koruması: aktifse ve fiyat stopa düştüyse kapat.
    # 2026-10-15 (madde 2): dolum iki fiyatın KÖTÜSÜ (min), gap iyimser yazılmaz.
    if trailing_activated and current_trailing_stop > 0 and current_price <= current_trailing_stop:
        await _close_trade(trade_id, symbol,
                           paper_ledger.exit_fill("trailing_stop", current_price, current_trailing_stop),
                           now, "trailing_stop")
        return True
    return False


async def _manage_single_trade(trade: dict, now: float, breakeven_trigger_pct: float = 1.5, settings: dict | None = None):
    """Tek bir auto_paper pozisyonunu yönet — aşamalı orkestratör.

    Aşamalar: taze fiyat (WS+REST) -> süre çıkışları -> TP/SL + tepe ->
    breakeven kâr kilidi -> trailing ratchet. Profil/plan işlemlerinde
    trailing/breakeven kuralı profilden gelir.
    """
    symbol = str(trade.get("symbol") or "").upper()
    trade_id = int(trade["id"])
    entry_price = float(trade["entry_price"])
    # 2026-10-21: çıkış profilli işlem (MA BUY H4) kendi tutma süresini taşır; iz süren stop kuralı profilden gelir,
    # başabaş stop profilli işlemde uygulanmaz.
    _profile_manage = ma_buy_profiles.manage_params(trade.get("exit_profile"))
    profile_no_trail = _profile_manage is not None and not _profile_manage["trailing"]
    profile_no_breakeven = _profile_manage is not None and not _profile_manage.get("breakeven", False)
    # 2026-10-27 (işlem planı): plan işleminde iz süren / başabaş / TP iptali KAPALI — çıkış yalnız plan hedefi,
    # plan stopu, plan süre kuralı ve rejim/LLM/bayat fiyat güvenlik çıkışları (hedef min. %3 net).
    is_plan_trade = trade.get("exit_profile") == PLAN_EXIT_PROFILE
    take_profit = float(trade["take_profit"]) if trade.get("take_profit") else None
    tp_cancelled = bool(trade.get("tp_cancelled", False))

    # 1) Taze fiyat (WS ticker + REST yedeği)
    current_price, price_is_fresh, last_known_price = await _fresh_trade_price(trade, symbol, now)

    # 2) Süre tabanlı çıkışlar (stale force close / plan / time-stop / max_hold)
    if await _check_hold_exit(trade, symbol, trade_id, now, current_price, price_is_fresh,
                              last_known_price, settings):
        return

    # 3) SEMBOL STREAM GÜVENLİĞİ: açık pozisyonu olan sembol akışta tutulmalı
    # (asla bu yüzden kapatılmaz). 2026-10-28: sembolün pasife düşmesi açık
    # işlemi KAPATMAZ; işlem kendi SL/TP/süre kurallarıyla kapanır.
    market_symbols = getattr(market, "symbols", None)
    if isinstance(market_symbols, (list, set, tuple)):
        symbols_lower = {str(s).lower() for s in market_symbols if isinstance(s, str)}
        if symbols_lower and symbol.lower() not in symbols_lower:
            try:
                extend_stream_universe([symbol], source="auto_paper_stream_guard")
            except Exception as exc:
                logger.warning("auto_paper %s akış evrenine ekleme koruması: %s", symbol, exc)
    if not price_is_fresh:
        return

    # 4) TP-primary + SL + tepe güncellemesi
    closed, peak_price = await _check_tp_sl_exit(trade, symbol, trade_id, now, current_price, settings)
    if closed:
        return

    # Kâr ve TP oranları
    gross_pnl_pct = ((current_price - entry_price) / entry_price * 100) if entry_price else 0
    tp_gain_pct = None
    if take_profit is not None and entry_price > 0 and take_profit > entry_price:
        tp_gain_pct = (take_profit - entry_price) / entry_price * 100

    # 5) Breakeven kâr kilidi
    closed, breakeven_enabled, be_gap = await _apply_breakeven(
        trade, symbol, trade_id, now, current_price, entry_price, peak_price,
        gross_pnl_pct, tp_gain_pct, breakeven_trigger_pct, settings,
        profile_no_trail, profile_no_breakeven, is_plan_trade)
    if closed:
        return

    # 6) Trailing ratchet (+ TP ratchet/iptal)
    await _apply_trailing(trade, symbol, trade_id, now, current_price, peak_price,
                          gross_pnl_pct, tp_gain_pct, settings, _profile_manage, is_plan_trade,
                          breakeven_enabled, be_gap, tp_cancelled, take_profit)

async def _close_trade(trade_id: int, symbol: str, exit_price: float, now: float, reason: str):
    """Auto paper pozisyonunu kapat ve wallet'a iade et (atomik DB işlemi)."""
    try:
        trade = await database.get_auto_paper_trade(trade_id)
        if not trade or trade.get("status") != "open":
            return

        entry_price = float(trade["entry_price"])
        quantity = float(trade["quantity"])
        # D-08 (2026-09-12): fiilî SATIŞ dolumuna kayma (slippage) uygulanır.
        # `exit_price` kayma ÖNCESİ tetik/piyasa fiyatıdır (bkz.
        # paper_ledger.exit_fill); satış kayması + iki bacak komisyonu + net PnL
        # tek kaynak `paper_ledger.settle_close` içinde.
        settled = paper_ledger.settle_close(entry_price, exit_price, quantity, exit_kind=reason)
        fill_price = settled["fill_price"]
        total_commission = settled["commission"]
        pnl = settled["pnl"]
        pnl_pct = settled["pnl_pct"]
        hold_seconds = now - float(trade["entry_time"])

        # DB güncelle + wallet iadesi + sinyal tek transaction'da
        # 2026-10-17: cüzdan iadesi PnL'in çıkış bacağıyla AYNI oranı kullanır.
        closed = await database.close_auto_paper_trade(
            trade_id, fill_price, now, pnl, pnl_pct, total_commission, reason,
            exit_commission_pct=settled["exit_commission_pct"])
        if not closed:
            logger.warning("auto_paper %s: kapanış başarısız (zaten kapalı?)", symbol)
            return

        _AUTO_PAPER_STATE["total_closed"] += 1
        _AUTO_PAPER_STATE["total_pnl"] += pnl
        if pnl >= 0:
            _AUTO_PAPER_STATE["winning_trades"] += 1
        else:
            _AUTO_PAPER_STATE["losing_trades"] += 1

        await _broadcast_trade({
            "action": "CLOSED", "symbol": symbol,
            "exit": fill_price, "pnl": round(pnl, 2),
            "reason": reason, "trade_id": trade_id,
        })

        logger.info("auto_paper %s: KAPANDI (%s) çıkış=%.6f PnL=%.2f %s (%+.2f%%) süre=%.0fs",
                    symbol, reason, fill_price, pnl, config.QUOTE_ASSET, pnl_pct, hold_seconds)

        settings = await get_auto_paper_settings()

        # Kâr koruma (trailing/breakeven) kapanışı: yalnızca ayar AÇIKSA yeniden açma dene (varsayılan: False)
        # 2026-09-29 analizi: koruma kapanışı sonrası hemen yeniden açma 9 işlemde +79.40 TRY kârı geri vermişti.
        reopen_enabled = bool(settings.get("reopen_after_protect_close", getattr(config, "AUTO_PAPER_REOPEN_AFTER_PROTECT_CLOSE", False)))
        if reason in ("trailing_stop", "breakeven_stop") and reopen_enabled:
            orig_notification_id = trade.get("notification_id")
            _start_background(
                lambda: _maybe_reopen_after_protect_close(symbol, orig_notification_id),
                f"auto-paper-reopen-{symbol}", single_pass=True)

        # Kârlı işlem sonrası kâr koruma beklemesi (post-win cooldown):
        # Kâr realizasyonu sonrası aynı sembole 15 dk yeni pozisyon açılmasını engelleyerek kârı koru.
        if pnl > 0 or reason in ("take_profit", "trailing_stop", "breakeven_stop"):
            win_cooldown_min = float(settings.get("post_win_cooldown_minutes", getattr(config, "AUTO_PAPER_POST_WIN_COOLDOWN_MINUTES", 15.0)))
            if win_cooldown_min > 0:
                _post_win_cooldowns[symbol] = now + (win_cooldown_min * 60.0)
                logger.info("auto_paper %s: karlı kapanış (PnL=%.2f) sonrası %.0f dakika kâr koruma bekleme süresi (post_win_cooldown) başlatıldı",
                            symbol, pnl, win_cooldown_min)

        # P2-4: `breakeven_stop` de bir STOP ailesidir — breakeven'a takılan
        # (çoğunlukla başa-baş/komisyon-altı kapanan) sembole hemen yeniden
        # girmek aynı churn'ü üretir; SL cooldown ailesine dahil edilir.
        if reason in ("stop_loss", "breakeven_stop"):
            cooldown_min = float(settings.get("sl_cooldown_minutes", _SL_COOLDOWN_MINUTES_DEFAULT))
            if cooldown_min > 0:
                _stop_loss_cooldowns[symbol] = now + (cooldown_min * 60.0)
                logger.info("auto_paper %s: %s sonrası %.0f dakika yeni giriş bekleme süresi (cooldown) başlatıldı",
                            symbol, reason, cooldown_min)

        # P2-4: cooldown haritaları restart'a dayanıklı olsun diye DB'ye yazılır.
        await _persist_cooldowns()

    except Exception as exc:
        logger.exception("auto_paper %s kapatma: %s", symbol, exc)


#: D-06 (2026-09-12): koruma kapanışı sonrası yeniden açma denemeleri için saat
#: kovası. Aynı kova içinde üretilen bildirim id'si KARARLI olduğundan, DB'deki
#: `notification_id` churn kontrolü (auto_paper_trades.notification_id) saat
#: başına en fazla bir yeniden açmayı zorlar — eski kod `notification_id=None`
#: ile bu korumayı tamamen baypas ediyordu.
_REOPEN_HOUR_BUCKET_SEC = int(getattr(config, "AUTO_PAPER_REOPEN_HOUR_BUCKET_SEC", 3600))
#: Tur/deneme sınırı: sembol başına son deneme zamanı (in-memory, tek süreç).
_reopen_last_attempt: dict[str, float] = {}


def _reopen_notification_id(symbol: str, now: float | None = None) -> str:
    """Yeniden açma için KARARLI bildirim kimliği (D-06).

    Format: ``reopen:{SYMBOL}:{hour_bucket}``. Saat kovası hem kararlıdır hem de
    saat başına en fazla bir yeniden açmayı DB churn kontrolü üzerinden zorlar.
    """
    bucket = int((now if now is not None else time.time()) // _REOPEN_HOUR_BUCKET_SEC)
    return f"reopen:{str(symbol).upper()}:{bucket}"


async def _reopen_rate_gate(symbol: str, now: float) -> str | None:
    """D-06: saat başına en fazla bir DENEME (başarısız deneme de sayılır).

    Döner: reopen bildirim id'si ya da `None` (limit/zaten yapıldı → atla).
    """
    last_attempt = float(_reopen_last_attempt.get(symbol, 0) or 0)
    if now - last_attempt < _REOPEN_HOUR_BUCKET_SEC:
        logger.info("auto_paper %s: yeniden açma denemesi saatlik sınırda (%ds) — atlandı",
                    symbol, int(now - last_attempt))
        return None
    _reopen_last_attempt[symbol] = now
    # D-06: kararlı bildirim id'si + mevcut dedup kontrolünü ZORLA. Bu saat
    # kovasında zaten bir yeniden açma yapıldıysa tekrar açma.
    reopen_id = _reopen_notification_id(symbol, now)
    # R3-09 (2026-10-12): erken ön-kontrol `notification_key` (TEXT) üzerinden
    # yapılır. Eskiden string `reopen_id` bigint kolonlu
    # `...by_notification`'a veriliyordu → PostgreSQL "invalid input syntax
    # for type bigint" fırlatıyor, `except` yutuyordu: hem her saat sessiz tip
    # hatası loglanıyor hem bu ön-kontrol HİÇ çalışmıyordu. `reopen` akışının
    # yazma yolu (auto_paper.py:789) da string id'yi `notification_key`e
    # koyduğundan churn kontrolü aynı kolondan okunmalıdır.
    try:
        prior_reopen = await database.get_recent_auto_paper_trade_by_notification_key(reopen_id)
    except Exception:
        prior_reopen = None
    if prior_reopen:
        logger.info("auto_paper %s: %s saat kovasında yeniden açma zaten yapıldı — atlandı",
                    symbol, reopen_id)
        return None
    return reopen_id


def _reopen_candidate(symbol: str, reopen_id: str) -> dict | None:
    """Radar 'uygun adaylar' önbelleğinden yeniden açma bildirimi kurar.

    Döner: bildirim sözlüğü ya da `None` (aday yok / panel skoru 0).
    """
    # monitoring'i tembel içe aktar (çevrimsel import riski olmasın).
    from app.routers import monitoring as monitoring_mod
    cand = monitoring_mod.get_cached_radar_candidate(symbol)
    if not cand:
        logger.info("auto_paper %s: koruma kapanışı sonrası radar 'uygun adaylar' "
                    "listesinde değil — yeniden açılmadı", symbol)
        return None
    panel = float(cand.get("panel_score") or 0)
    if panel <= 0:
        try:
            panel = float(monitoring_mod.normalize_score(cand.get("velocity_score") or 0))
        except Exception:
            panel = 0.0
    if panel <= 0:
        return None
    price = float(cand.get("price") or 0)
    target_pct = float(cand.get("target_pct") or 0)
    return {
        # D-06: KARARLI, saat-kovalı bildirim id'si — `notification_id=None`
        # DEĞİL. Böylece try_open_from_notification + open_auto_paper_trade
        # içindeki already_traded churn kontrolü yeniden açmayı da kapsar.
        "id": reopen_id,
        # R3-09 düzeltmesi: `notification_key` AYNI reopen_id olmalı —
        # eskiden bu anahtar hiç set edilmiyordu ve try_open_from_notification
        # içindeki `get_recent_auto_paper_trade_by_notification_key` dedup
        # kontrolleri (database.py) HİÇ TETİKLENMİYORDU: trailing stop ->
        # reopen -> trailing stop döngüsü her saat her turda ~%0.35 sessiz
        # eriti ve restart'ta _reopen_last_attempt sıfırlanınca limit de
        # sıfırlanıyordu. Tek satırlık kök neden düzeltmesi.
        "notification_key": reopen_id,
        "symbol": symbol,
        "score": panel,
        "price": price,
        "target_pct": target_pct,
        "expected_price": (float(cand.get("expected_price") or 0)
                           or (price * (1 + target_pct / 100) if price > 0 else 0)),
        "detected_at": time.time(),
        "horizon_minutes": int(cand.get("horizon_minutes") or 5),
        "mode": cand.get("mode"),
        "ml_hit_probability": cand.get("ml_hit_probability"),
        "ml_target_pct": cand.get("ml_target_pct"),
    }


async def _maybe_reopen_after_protect_close(symbol: str, orig_notification_id=None) -> None:
    """Trailing/breakeven kapanışı sonrası yeniden açma denemesi.

    Kural (kullanıcı isteği 2026-09-08): sembol monitoring sayfasının "uygun
    adaylar" listesinde (son tarama sonucunda) kaldığı sürece kâr koruma
    çıkışının ardından aynı sembole yeniden pozisyon açılır. Sembol listeden
    düşmüşse veya reopen_after_protect_close ayarı kapalıysa açılmaz.

    D-06 (2026-09-12): yeniden açma bildirimine KARARLI bir ``id`` verilir
    (``reopen:{symbol}:{saat_kovası}``) ve hem uygulama içi hem DB tarafındaki
    ``already_traded`` kontrolü uygulanır. Ayrıca sembol başına saatte en fazla
    BİR deneme (in-memory + DB) yapılır. Eski kod ``id`` alanı olmadan
    ``notification_id=None`` gönderiyordu → churn koruması tamamen atlanıyor,
    sembol radar listesinde kaldığı sürece sınırsız yeniden giriş (her turda
    round-trip komisyon) oluşuyordu.
    """
    try:
        settings = await get_auto_paper_settings()
        if not bool(settings.get("reopen_after_protect_close", config.AUTO_PAPER_REOPEN_AFTER_PROTECT_CLOSE)):
            return
        reopen_id = await _reopen_rate_gate(symbol, time.time())
        if reopen_id is None:
            return
        notif = _reopen_candidate(symbol, reopen_id)
        if notif is None:
            return
        result = await try_open_from_notification(notif)
        if result:
            logger.info("auto_paper %s: koruma kapanışı sonrası radar adayı olarak "
                        "yeniden işlem açıldı/güncellendi (%s)", symbol, result.get("status"))
    except Exception as exc:
        logger.debug("auto_paper %s koruma kapanışı sonrası yeniden açma: %s", symbol, exc)


async def _broadcast_trade(data: dict):
    """WS üzerinden auto_paper trade olayını yayınla."""
    try:
        await ws_manager.broadcast({"type": "auto_paper_trade", "data": data})
    except Exception:
        logger.debug("auto_paper: trade WS yayını başarısız", exc_info=True)


# ---------------------------------------------------------------------------
# Settings API
# ---------------------------------------------------------------------------
def _allowed_modes_from_config() -> list[str]:
    """2026-10-16 (tarama güncellemesi): `AUTO_PAPER_ALLOWED_MODES` → liste.

    Çağrı anında okunur (test/çalışma anı override'ı). Virgüllü metin ya da
    yinelenebilir; boş girdiler atılır, sıra ve tekillik korunur. Boş sonuç =
    TÜM modlar (mod kapısı `allowed_modes` boşken herkesi geçirir).
    """
    raw = getattr(config, "AUTO_PAPER_ALLOWED_MODES", "trend_devam")
    parts = raw.split(",") if isinstance(raw, str) else list(raw or [])
    return list(dict.fromkeys(str(p).strip() for p in parts if str(p).strip()))[:20]


async def get_default_settings() -> dict:
    # 2026-10-16 (maliyet/çıkış): SL / trailing varsayılanları çıkış profilinden
    # (`AUTO_PAPER_EXIT_PROFILE`: mevcut | kalibre). DB'deki kayıtlı ayar
    # `get_auto_paper_settings` birleştirmesinde bu varsayılanları EZER.
    _exit_def = _exit_defaults()
    return {
        "enabled": True,
        "min_score": config.AUTO_PAPER_MIN_SCORE_DEFAULT,
        "balance_pct": config.AUTO_PAPER_BALANCE_PCT_DEFAULT,
        "stop_loss_pct": _exit_def["stop_loss_pct"],
        "exit_profile": _exit_def.get("profile", "mevcut"),
        "default_target_pct": config.AUTO_PAPER_DEFAULT_TARGET_PCT,
        # Hedef tavanı (2026-10-07): bildirimin kendi target_pct'i bunu aşarsa
        # TP bu değere çekilir. Env: AUTO_PAPER_MAX_TARGET_PCT. 0 = sınırsız.
        "max_target_pct": getattr(config, "AUTO_PAPER_MAX_TARGET_PCT", 0.0),
        "min_order_try": config.AUTO_PAPER_MIN_ORDER_TRY,
        "breakeven_enabled": getattr(config, "AUTO_PAPER_BREAKEVEN_ENABLED", False),
        "breakeven_trigger_pct": config.AUTO_PAPER_BREAKEVEN_TRIGGER_PCT,
        "trailing_enabled": config.AUTO_PAPER_TRAILING_ENABLED,
        "trailing_trigger_pct": _exit_def["trailing_trigger_pct"],
        "trailing_gap_pct": _exit_def["trailing_gap_pct"],
        "reopen_after_protect_close": config.AUTO_PAPER_REOPEN_AFTER_PROTECT_CLOSE,
        # TP-CANCEL-ON-TRAIL (2026-10-09): trailing devreye girdiginde sabit TP
        # IPTAL edilir. A/B kaniti B lehine (work/ab_tp_cancel.py) ama muhafazakar
        # varsayilan KAPALI (opt-in). Env: AUTO_PAPER_TP_CANCEL_ON_TRAIL.
        "tp_cancel_on_trail": getattr(config, "AUTO_PAPER_TP_CANCEL_ON_TRAIL", False),
        # P2-2 DUZELTMESI (2026-10-07) GERI ALINDI (2026-10-09). Eskiden burada
        # TP birincil cikis varsayilan ACIK yapilmisti (TP = en iyi cikis, §1).
        # Ama ayni repo'nun kendi kaniti (config.py:883 + commit 928feaf) ve
        # TP-CANCEL-ON-TRAIL A/B (work/ab_tp_cancel.py; 30 gun, 1231 islem,
        # mum-ici VE muhafazakar close-only) TP-primary'i KAPATMANIN en karli
        # oldugunu gosteriyor:
        #   mum-ici: TP-off +1.087% / ratchet +0.299% / cancel +0.436% (TP-off 6/6 pencere)
        #   close  : TP-off +0.690% / cancel +0.186% / ratchet -0.110% (TP-off 6/6 pencere)
        # Yalniz TP-off train VE test'te POZITIF kalir (close-only test +0.367%).
        # Sabit TP = bildirim hedefi (canlida ort +%4,30) sert bir tavan gibi
        # calisiyordu; tepe medyani +%1,62 oldugu icin cogu islem hedefe hic
        # degmiyor, degince de kazanan erken kesiliyordu. Bu yuzden varsayilan
        # KAPALI (kanitla hizali). NOT: `tp_cancel_on_trail` ACIKken trailing TP'yi
        # iptal ettiginden, TP emri zaten yoksa bu ayar ETKISIZdir — TP'yi kapatmak
        # icin yalniz `tp_primary_exit_enabled=false` yeterli ve erken-iptal
        # marjini kaybetmediginden daha karli. DB satiri env'i ezer.
        "tp_primary_exit_enabled": False,
        "dynamic_breakeven_enabled": getattr(config, "AUTO_PAPER_DYNAMIC_BREAKEVEN_ENABLED", False),
        "dynamic_trailing_enabled": getattr(config, "AUTO_PAPER_DYNAMIC_TRAILING_ENABLED", False),
        "breakeven_buffer_pct": getattr(config, "AUTO_PAPER_BREAKEVEN_BUFFER_PCT", 0.02),
        "max_open_positions": config.AUTO_PAPER_MAX_OPEN_POSITIONS,
        "max_hold_minutes": getattr(config, "AUTO_PAPER_MAX_HOLD_MINUTES", 120.0),
        "block_weak_mtf": True,
        "min_mtf_confluence": 45.0,
        "sl_cooldown_minutes": _SL_COOLDOWN_MINUTES_DEFAULT,
        "post_win_cooldown_minutes": getattr(config, "AUTO_PAPER_POST_WIN_COOLDOWN_MINUTES", 15.0),
        "llm_gate_enabled": True,
        "llm_min_confidence": 60.0,
        "volatility_sl_enabled": True,
        # MOD FILTRESI (2026-10-07 incelemesi). Bos liste = TUM modlar (eski
        # davranis). Kanit: 3214 bildirim uzerinde 30 gunluk gercek mum
        # verisiyle (work/analiz_2026-10-07) mod ayrimi belirleyici cikti:
        # trend_devam +0.47%/islem, unified +0.02%, global_lead_lag -0.13%,
        # notr -0.70%. Karisik havuz maliyet sonrasi negatif kaliyor.
        #
        # 2026-10-07 OPTIMIZASYON: yalnizca edge tasiyan mod islenir.
        # trend_devam+dedup+cikis kurallari: +1.375%/islem, train +1.746 /
        # test +0.508, 5/5 hafta pozitif, p~0.000 (null testi 400 orneklem).
        # TUM havuz ayni kurallarla +0.550% — yani diger modlar getiriyi
        # yariya indiriyor. Bos liste verilerek eski davranisa donulur.
        #
        # P0-2 DUZELTMESI (2026-10-07 denetimi): onceki varsayilan
        # `["trend_devam"]` idi ve radar giris yolunu SESSIZCE kapatuyordu —
        # `trend_devam` yalniz velocity yolunda uretilir; radar/birlesik
        # bildirimleri `mode="unified"`. `unified` de ayni cikis kurallariyla
        # islem basi +0.02% (≈ notr noktasi) verir; onu listelemek edge
        # KATMAZ ama hacmi (ve radar yolunu) oldurur. Bu yuzden `unified` de
        # eklenir. Negatif/kanitsiz modlar (`notr`, `llm_ikinci_goz`,
        # `global_lead_lag`) DISARIDA kalir.
        # DIKKAT (migration): mevcut DB `auto_paper_settings` satiri bu
        # varsayilani EZER (get_auto_paper_settings DB-over-defaults birlestirir).
        # Kayitli bir liste tek seferlik duzeltilmezse eski davranis surer.
        #
        # 2026-10-16 (tarama güncellemesi): sabit `["trend_devam", "unified"]`
        # yerine env `AUTO_PAPER_ALLOWED_MODES` (varsayılan "trend_devam").
        # Kanıt (7 günlük bildirim ölçümü, 279 ölçülebilir, 5m mum): trend_devam
        # n=150 hit60 %52.7 net 0.00; unified n=41 hit60 %19.5 (kayıtlı hedef
        # isabeti %3.7); notr net −1.09; v_donusu 0/10 → `unified` listeden
        # çıkar. Boş env = TÜM modlar (eski davranış). Kayıt: docs/DENEY_KAYDI.md.
        "allowed_modes": _allowed_modes_from_config(),
        # BILDIRIM DEDUP (2026-10-07). Ayni sembolde kisa sure once giris
        # yapildiysa tekrar girmez (0 = kapali). Ayni sinyal 5 dakikada birden
        # fazla kanaldan geliyor; her biri ayri pozisyon aciyordu.
        # OPTIMIZASYON: 60 dk. Canlida islem hacmi 107/gun -> 17/gun; ort.
        # bozulmadan (-%0.20 -> +0.55% @30dk dedup) tekrarli islemler atilir.
        "dedup_cooldown_minutes": 60.0,
    }


async def get_auto_paper_settings() -> dict:
    """DB'den auto_paper ayarlarını oku."""
    try:
        raw = await database.get_llm_setting("auto_paper_settings", "{}")
        settings = json.loads(raw or "{}")
        defaults = await get_default_settings()
        return {**defaults, **settings}
    except Exception:
        return await get_default_settings()


@router.get("/api/auto-paper/settings")
async def get_settings_endpoint():
    """Otonom paper trade ayarlarını döndür."""
    settings = await get_auto_paper_settings()
    state = dict(_AUTO_PAPER_STATE)
    return {"paper_only": True, "settings": settings, "state": state}


@router.put("/api/auto-paper/settings")
async def update_settings_endpoint(payload: dict, request: Request):
    """Otonom paper trade ayarlarını güncelle (admin)."""
    from app.api_common import require_admin as _require_admin
    _require_admin(request)

    editable = ("enabled", "min_score", "balance_pct", "stop_loss_pct",
                "default_target_pct", "max_target_pct", "min_order_try", "breakeven_enabled",
                "breakeven_trigger_pct", "trailing_enabled", "trailing_trigger_pct",
                "trailing_gap_pct", "reopen_after_protect_close",
                "tp_primary_exit_enabled", "tp_cancel_on_trail", "dynamic_breakeven_enabled",
                "dynamic_trailing_enabled", "breakeven_buffer_pct",
                "max_open_positions", "max_hold_minutes",
                "block_weak_mtf", "min_mtf_confluence",
                "sl_cooldown_minutes", "post_win_cooldown_minutes",
                "llm_gate_enabled", "llm_min_confidence",
                "volatility_sl_enabled",
                "allowed_modes", "dedup_cooldown_minutes")
    existing = await get_auto_paper_settings()
    merged = {**existing, **{k: payload[k] for k in editable if k in payload}}
    _exit_def = _exit_defaults()  # 2026-10-16 (maliyet/çıkış): profil varsayılanları (payload/DB önce)

    settings = {
        "enabled": bool(merged.get("enabled", True)),
        "min_score": max(0.0, min(100.0, float(merged.get("min_score", config.AUTO_PAPER_MIN_SCORE_DEFAULT)))),
        "balance_pct": max(1.0, min(100.0, float(merged.get("balance_pct", config.AUTO_PAPER_BALANCE_PCT_DEFAULT)))),
        "stop_loss_pct": max(0.1, min(20.0, float(merged.get("stop_loss_pct", _exit_def["stop_loss_pct"])))),
        "default_target_pct": max(0.5, min(20.0, float(merged.get("default_target_pct", config.AUTO_PAPER_DEFAULT_TARGET_PCT)))),
        # 0 = sınırsız (eski davranış, geriye dönük uyum). Üst sınır 20.
        "max_target_pct": max(0.0, min(20.0, float(merged.get("max_target_pct", getattr(config, "AUTO_PAPER_MAX_TARGET_PCT", 0.0))))),
        # 2026-09-27: taban `10.0` TRY cinsinden sabitlenmişti; deployment
        # quote'ünden gelir: TRY'de 10 (değişmeyen davranış). Üst sınır
        # koymadık — operatör bilerek küçük eşik seçebilir.
        "min_order_try": max(10.0 if config.QUOTE_ASSET == "TRY" else 0.5,
                              float(merged.get("min_order_try",
                                               config.AUTO_PAPER_MIN_ORDER_TRY))),
        "breakeven_enabled": bool(merged.get("breakeven_enabled", getattr(config, "AUTO_PAPER_BREAKEVEN_ENABLED", False))),
        "breakeven_trigger_pct": max(0.5, min(10.0, float(merged.get("breakeven_trigger_pct", config.AUTO_PAPER_BREAKEVEN_TRIGGER_PCT)))),
        "trailing_enabled": bool(merged.get("trailing_enabled", config.AUTO_PAPER_TRAILING_ENABLED)),
        "trailing_trigger_pct": max(0.5, min(20.0, float(merged.get("trailing_trigger_pct", _exit_def["trailing_trigger_pct"])))),
        # Breakeven ratchet'i artık config.AUTO_PAPER_TRAILING_GAP_PCT'ten okunuyor,
        # dolayısıyla trailing gap'i ondan daha gevşek ayarlamak fiilen etki eder;
        # üst sınır 2026-09-27'de 0.6 → 2.0'ye çıkarıldı (Erkan kararı).
        "trailing_gap_pct": max(0.1, min(2.0, float(merged.get("trailing_gap_pct", _exit_def["trailing_gap_pct"])))),
        "reopen_after_protect_close": bool(merged.get("reopen_after_protect_close", config.AUTO_PAPER_REOPEN_AFTER_PROTECT_CLOSE)),
        "tp_primary_exit_enabled": bool(merged.get("tp_primary_exit_enabled", _exit_def["tp_primary_exit_enabled"])),
        "tp_cancel_on_trail": bool(merged.get("tp_cancel_on_trail", getattr(config, "AUTO_PAPER_TP_CANCEL_ON_TRAIL", False))),
        "dynamic_breakeven_enabled": bool(merged.get("dynamic_breakeven_enabled", getattr(config, "AUTO_PAPER_DYNAMIC_BREAKEVEN_ENABLED", False))),
        "dynamic_trailing_enabled": bool(merged.get("dynamic_trailing_enabled", getattr(config, "AUTO_PAPER_DYNAMIC_TRAILING_ENABLED", False))),
        "breakeven_buffer_pct": max(0.01, min(0.5, float(merged.get("breakeven_buffer_pct", getattr(config, "AUTO_PAPER_BREAKEVEN_BUFFER_PCT", 0.02))))),
        # D-11/Erkan (2026-09-18): UI'dan değiştirilebilir global maksimum açık
        # pozisyon. 1..30 aralığı; 0'a izin verilmez (yanlışlıkla sınırsız
        # bırakma koruması — sınırsız gerekirse env ile verilir).
        "max_open_positions": max(1, min(30, int(merged.get("max_open_positions", config.AUTO_PAPER_MAX_OPEN_POSITIONS)))),
        "max_hold_minutes": max(5.0, min(1440.0, float(merged.get("max_hold_minutes", getattr(config, "AUTO_PAPER_MAX_HOLD_MINUTES", 120.0))))),
        "post_win_cooldown_minutes": max(0.0, min(120.0, float(merged.get("post_win_cooldown_minutes", getattr(config, "AUTO_PAPER_POST_WIN_COOLDOWN_MINUTES", 15.0))))),
        "llm_gate_enabled": bool(merged.get("llm_gate_enabled", True)),
        "llm_min_confidence": max(50.0, min(100.0, float(merged.get("llm_min_confidence", 60.0)))),
        "block_weak_mtf": bool(merged.get("block_weak_mtf", True)),
        "min_mtf_confluence": max(0.0, min(100.0, float(merged.get("min_mtf_confluence", 45.0)))),
        "sl_cooldown_minutes": max(0.0, min(120.0, float(merged.get("sl_cooldown_minutes", _SL_COOLDOWN_MINUTES_DEFAULT)))),
        "volatility_sl_enabled": bool(merged.get("volatility_sl_enabled", True)),
        # Mod filtresi: yalnizca tanimli mod adlari; ayni degeri korur, bilinmeyen
        # adlar sessizce dusurulur (fail-closed degil — eski davranisa donmesin diye
        # liste bosaltilirsa TUM modlar gecer). Bilinmeyen ad girisi KILITLEMEZ.
        "allowed_modes": [str(m).strip() for m in (
            merged.get("allowed_modes") or []
            if isinstance(merged.get("allowed_modes") or [], list) else [])
            if str(m).strip()][:20],
        "dedup_cooldown_minutes": max(0.0, min(1440.0, float(merged.get("dedup_cooldown_minutes", 0.0) or 0.0))),
    }

    await database.set_llm_setting("auto_paper_settings", json.dumps(settings))
    await log_user_action(None, None, "auto_paper", "AUTO_PAPER_SETTINGS_UPDATE",
                          details={"settings": settings}, request=request)
    return {"paper_only": True, "ok": True, "settings": settings}


# ---------------------------------------------------------------------------
# Trades API
# ---------------------------------------------------------------------------
@router.get("/api/auto-paper/trades")
async def list_trades_endpoint(
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    day: str | None = None,
    include_archived: bool = False,
):
    """Otonom paper trade kayıtlarını listele. Açık pozisyonlara güncel fiyat eklenir."""
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))
    # P0-3 (2026-10-07): AÇIK pozisyon sorgusu rapor görünüm sınırını YOK SAYAR
    # (açık pozisyon her zaman görünür/yönetilebilir olmalı). KAPALI/tümü
    # sorguları bir rapor görünümüdür → varsayılan sınır UYGULANIR.
    _only_open = str(status or "").strip().lower() == "open"
    trades = await database.list_auto_paper_trades(
        status=status or None, limit=limit, offset=offset, day=day,
        include_archived=include_archived, apply_reports_baseline=not _only_open
    )
    # Açık pozisyonlar için güncel ticker fiyatını ekle (frontend PnL hesabı için)
    for t in trades:
        if t.get("status") == "open":
            ticker = market.get_ticker(str(t.get("symbol") or "").upper())
            t["current_price"] = float(ticker.get("last_price") or 0) if ticker else None
            nid = t.get("notification_id")
            notif = None
            if nid:
                try:
                    notif = await database.get_monitoring_notification_by_id(nid)
                except Exception:
                    notif = None
            if notif:
                t["notification_price"] = float(notif.get("price") or 0)
                if not t.get("notification_expected_price"):
                    t["notification_expected_price"] = float(notif.get("expected_price") or 0)
                if not t.get("notification_target_pct"):
                    t["notification_target_pct"] = float(notif.get("target_pct") or 0)
                if not t.get("notification_score"):
                    t["notification_score"] = float(notif.get("score") or 0)
            else:
                t["notification_price"] = float(t.get("entry_price") or 0)
    reset_at = await database.get_reset_cutoff()
    return {
        "paper_only": True,
        "trades": trades,
        "total": len(trades),
        "day": day or "today",
        "reset_at": reset_at,
        "include_archived": include_archived,
    }


@router.get("/api/auto-paper/stats")
async def get_stats_endpoint(day: str | None = None, include_archived: bool = False):
    """Otonom paper trade istatistikleri (seçilen gün / reset_at sonrasi; reset kapanışları hariç).

    `include_archived=True` → "arşivi göster": RAPOR BAŞLANGICI öncesi işlemler
    de KPI'lara sayılır. Varsayılan False → yalnız deploy sonrası işlemler.
    """
    stats = await database.get_auto_paper_stats(
        day=day, ignore_reports_baseline=include_archived)
    reset_at = await database.get_reset_cutoff()
    # 2026-10-16 (giriş gecikmesi): son 200 trade için bildirim→dolum gecikmesi/kayma.
    try:
        entry_latency = await get_entry_latency_block()
    except Exception as exc:
        logger.debug("entry_latency bloğu atlandı: %s", exc)
        entry_latency = {"n": 0, "error": str(exc)}
    return {
        "paper_only": True,
        "day": day or "today",
        "stats": stats,
        "reset_at": reset_at,
        "include_archived": include_archived,
        "state": dict(_AUTO_PAPER_STATE),
        "entry_latency": entry_latency,
    }


@router.post("/api/auto-paper/trades/{trade_id}/close")
async def close_auto_paper_endpoint(trade_id: int, request: Request):
    """Açık otonom paper pozisyonunu manuel kapat (admin-only, paper-only).

    Piyasa fiyatından kapanır; muhasebe close_auto_paper_trade içinde
    (komisyon + wallet iadesi + CLOSE sinyali) atomiktir.
    """
    from app.api_common import require_admin as _require_admin
    _require_admin(request)
    trade = await database.get_auto_paper_trade(trade_id)
    if not trade or trade.get("status") != "open":
        raise HTTPException(404, "Açık otonom pozisyon bulunamadı")
    symbol = str(trade.get("symbol") or "").upper()
    ticker = market.get_ticker(symbol) or {}
    price = float(ticker.get("last_price") or 0)
    if price <= 0:
        raise HTTPException(502, f"{symbol} için güncel fiyat bulunamadı")
    await _close_trade(trade_id, symbol, price, time.time(), "manual_close")
    await log_user_action(_session_username(request), None, "trade", "AUTO_PAPER_CLOSE_MANUAL",
                          target=symbol, details={"trade_id": trade_id, "exit_price": price}, request=request)
    return {"ok": True, "message": f"{symbol} kapatıldı @ {price:.6f}", "trade_id": trade_id}


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
def reset_state():
    """In-memory sayaçları sıfırla (admin reset sonrası restart beklemeden).

    P2-4: cooldown haritaları artık DB'ye kalıcılaştırıldığı için in-memory
    temizlik yetmez; kalıcı kopya da arka planda temizlenir — aksi halde reset
    sonrası restart cooldown'ları geri getirirdi.
    """
    _AUTO_PAPER_STATE.update({
        "total_opened": 0,
        "total_closed": 0,
        "total_pnl": 0.0,
        "winning_trades": 0,
        "losing_trades": 0,
        "last_check_at": None,
        "consecutive_errors": 0,
    })
    _stop_loss_cooldowns.clear()
    _post_win_cooldowns.clear()
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        # Yalnız çalışan bir event loop varsa kalıcı kopyayı temizle; senkron
        # bağlamda (ör. birim testi) atlanır — bir sonraki kapanış zaten güncel
        # (boş) haritayı yazar.
        loop.create_task(_persist_cooldowns())


async def _migrate_bad_settings_once() -> None:
    """TEK-SEFERLİK ayar onarımı (2026-10-11).

    NEDEN: canlı `auto_paper_settings` DB satırı config varsayılanlarını EZER ve
    içine kötü bir kombinasyon kaydedilmişti (ölçüldü, 70 kapanan işlem):
      * stop_loss_pct = 1.5        → çok sıkı stop, gürültüde tetikleniyor
      * trailing_trigger_pct = 1.8 → kâr kilidi çok GEÇ devreye giriyor
      * trailing_gap_pct = 0.6     → tepeden geri çekilmede kârı veriyor
    Ayrıca trailing gap 0.3 gibi ÇOK DAR değerler canlıda "anında yakalanma"
    (kâr büyüyemeden kapanma) üretiyor — canlı ticker gürültüsüne karşı yeterli
    mesafe şart. Bu yüzden onarım gap'i GEVŞEK değere (config varsayılanı 1.0)
    çeker; hem eski 0.6 hem de dar 0.3 kayıtlı değerler hedeflenir.

    Yalnız KÖTÜ kayıtlı değerleri düzeltir (operatörün bilinçli iyi seçimine
    dokunmaz): SL 1.5→5.0, trigger 1.8→0.8, gap 0.6/0.3→1.0.
    İdempotent: bir kez çalışır, sonraki restart'ta atlar.
    """
    try:
        raw = await database.get_llm_setting("auto_paper_settings", "{}")
        settings = json.loads(raw or "{}")
        if not isinstance(settings, dict) or not settings:
            return
        changed = {}
        gap_default = config.AUTO_PAPER_TRAILING_GAP_PCT  # 1.0
        trig_default = config.AUTO_PAPER_TRAILING_TRIGGER_PCT  # 2.0
        # Yalnız ESKİ/KÖTÜ değerleri hedefle (operatörün yeni seçimine dokunmaz).
        if abs(float(settings.get("stop_loss_pct", 0) or 0) - 1.5) < 1e-6:
            settings["stop_loss_pct"] = config.AUTO_PAPER_SL_PCT_DEFAULT  # 5.0
            changed["stop_loss_pct"] = settings["stop_loss_pct"]
        # Trailing tetik: eski 1.8 / 1.0 / 0.8 → config (2.0). Kural: trigger, gap'ten
        # BÜYÜK olmalı — aksi halde stop girişin altına düşüp kârı zarara çevirir.
        _trig = float(settings.get("trailing_trigger_pct", 0) or 0)
        if _trig and abs(_trig - trig_default) > 1e-6:
            settings["trailing_trigger_pct"] = trig_default
            changed["trailing_trigger_pct"] = trig_default
        # Dar gap (0.3 / 0.6) → gevşek (1.0): canlıda anında yakalanmayı bitirir.
        _gap = float(settings.get("trailing_gap_pct", 0) or 0)
        if _gap and _gap < 0.8 and abs(_gap - gap_default) > 1e-6:
            settings["trailing_gap_pct"] = gap_default
            changed["trailing_gap_pct"] = gap_default
        # GÜVENLİK KURALI (her durumda): trigger > gap. Operatör gap'i trigger'dan
        # büyük kaydettiyse bile burada düzeltilir → kâr kilidi asla zarara dönmez.
        _t = float(settings.get("trailing_trigger_pct") or trig_default)
        _g = float(settings.get("trailing_gap_pct") or gap_default)
        if _g >= _t:
            settings["trailing_trigger_pct"] = round(_g + 1.0, 2)
            changed["trailing_trigger_pct"] = settings["trailing_trigger_pct"]
        if changed:
            await database.set_llm_setting("auto_paper_settings", json.dumps(settings))
            logger.warning("auto_paper AYAR ONARIMI (tek seferlik): %s "
                           "(kötü/dar kayıtlı değerler canlıya uygun değere çekildi)", changed)
        else:
            logger.info("auto_paper ayar onarımı: kötü kayıtlı değer yok, atlandı")
    except Exception as exc:
        logger.warning("auto_paper ayar onarımı yapılamadı: %s", exc)


def start_auto_paper_loop() -> bool:
    """Arka plan döngüsünü bir kez başlat."""
    global _loop_task
    if _loop_task is not None and not _loop_task.done():
        return False
    # P2-4: kalıcı cooldown durumunu döngü başlamadan önce geri yükle
    # (süpervizör görevi gibi arka planda; döngü ilk turunu 30 sn geciktirir,
    # bu arada restore tamamlanır).
    _start_background(restore_runtime_state, "auto-paper-state-restore")
    # TEK-SEFERLİK ayar onarımı (2026-10-11): DB'deki kötü kayıtlı değerleri
    # (SL 1.5 / trig 1.8 / gap 0.6) veriye göre düzelt. İdempotent.
    _start_background(_migrate_bad_settings_once, "auto-paper-settings-repair")
    # G-10: süpervizörlü başlatma (hata sonrası sınırlı backoff ile yeniden başlar).
    _loop_task = _start_background(auto_paper_management_loop, "auto-paper-management")
    return True


def stop_auto_paper_loop():
    """Döngüyü durdur (arka plan task havuzundan çıkar)."""
    global _loop_task
    if _loop_task is not None:
        _loop_task.cancel()
        _background_tasks.discard(_loop_task)
        _loop_task = None
