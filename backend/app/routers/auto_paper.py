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
import time
import math

from fastapi import APIRouter, HTTPException, Request

from app.config import config
from app import database, security
from app.api_common import log_user_action, _background_tasks, _start_background
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


def _blocked(symbol: str, reason: str, **extra) -> dict:
    """R3-06/R3-07: giriş engeli için görünür durum — sessiz düşme yok.

    `try_open_from_notification` artık engellerde None değil, neden tanımlı bir
    sözlük döndürür (operatör/rapor neden 'likidite'/'küme'/'max_open'/'sessiz'
    olduğunu görür). `_maybe_reopen_after_protect_close` bunu "açıldı" sanmasın
    diye yalnızca `status in ("opened","tp_updated","no_change")`ı doğrular.
    """
    block = {"status": "blocked", "reason": reason, "symbol": symbol}
    block.update(extra)
    try:
        price = float(extra.get("price") or extra.get("current_price") or 0.0)
        asyncio.create_task(_log_blocked_decision(symbol, reason, price, dict(extra)))
    except Exception:
        pass
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

#: Stop loss sonrası sembol bazında aşırı işlem (churn/peş peşe kayıp) koruma süreleri {symbol: expire_timestamp}
_stop_loss_cooldowns: dict[str, float] = {}
#: Kârlı kapanış (take_profit/trailing_stop) sonrası kârı geri vermeme (post-win churn) koruma süreleri {symbol: expire_timestamp}
_post_win_cooldowns: dict[str, float] = {}


# ---------------------------------------------------------------------------
# Core: bildirim → pozisyon açılışı
# ---------------------------------------------------------------------------
async def try_open_from_notification(notification: dict) -> dict | None:
    """Bir monitoring bildirimi geldiğinde otonom paper pozisyonu aç.

    Giriş kuralları:
      - Sembolde açık pozisyon yoksa serbest TL bakiyesinin %balance_pct'i ile pozisyon aç.
      - SL: settings'teki stop_loss_pct (varsayılan %3)
      - TP: bildirimdeki hedef (notification_target_pct üzerinden)
      - Sembolde zaten açık auto_paper pozisyonu varsa TP güncelle (hedef takibi)
      - Aynı bildirim daha önce işlendiyse (kapanış sonrası yeniden açma) engelle.
      - R3-06 (P1): girişten önce likidite + korelasyon küme kapısı; engelin NEDENİ
        dönüş durumunda taşınır (sessiz düşme yok). R3-07 (P0): sessiz saatlerde
        otonom işlem engellenir.

IKI OTONOM YOLUN KAPI/OLCEK KARSILASTIRMASI (R3-08 — DOKUMANTASYON):

      * Bildirim -> auto_paper (BU yol):
          - Esik olcegi: PANEL (0-100). `score` panel; `min_score` varsayilani
            `AUTO_PAPER_MIN_SCORE_DEFAULT` (50). Monitoring yalnizca panel
            `monitoring.min_score`'u (varsayilan 70) gecen PASSING adaylari bildirir.
          - Havuz: yalnizca PASSING adaylar (watchlist dahil DEGIL).
          - Desen kapisi: `m5_pattern_ok` koşulu YOK.
          - Likidite/kume: R3-06 ile bu yola DAHIL EDILDI (asagida).

      * velocity-auto (velocity.py):
          - Esik olcegi: HAM `velocity_score` >= 10 (0-2000; panel yaklasik 0.5).
          - Havuz: WATCHLIST (`passes=False`) adaylarini DAHIL eder.
          - Desen kapisi: `m5_pattern_ok` ZORUNLU.
          - Likidite: R3-06 oncesi yalnizca bu yolda vardi.

      Bu yuzden ayni tarama iki farkli islem seti uretebilir. Bu fonksiyon
      kapi/olcek uyumsuzlugunu DOKUMANTE eder ve esikleri BILINCLI olarak
      DEGISTIRMEZ (her yol kendi sozlesmesiyle calismaya devam eder — R3-08).
      R3-08 kapsaminda yalnizca `passes` bayragi acikca FALSE ise giris engellenir.

      Kurallar:
      - Likidite (derinlik + 24h) ve korelasyon kume asimi kapilari (R3-06).
    """
    try:
        settings = await get_auto_paper_settings()
        if not settings.get("enabled", True):
            # 2026-09-27: sessiz None yerine görünür log — otonom kapalıyken
            # push gelip işlem açılmayınca operatör neden görebilsin.
            logger.info("auto_paper %s: otonom paper trade KAPALI (settings.enabled=false) — "
                        "bildirim işleme alınmadı", str(notification.get("symbol") or "?"))
            return None

        symbol = str(notification.get("symbol") or "").upper()
        if not symbol:
            return None

        score = float(notification.get("score") or 0)
        min_score = float(settings.get("min_score", config.AUTO_PAPER_MIN_SCORE_DEFAULT))
        if score < min_score:
            logger.info("auto_paper %s: skor %.1f < min_score %.1f — açılmadı",
                        symbol, score, min_score)
            # 2026-09-27: eskiden sessiz None dönüyordu → push gelip işlem
            # açılmayınca operatör NEDENİ göremiyordu. Engelin nedenini
            # decision_logs'a yaz (R3-06 deseni: sessiz düşme yok).
            return _blocked(symbol, "score_below_min", price=0.0,
                            score=round(score, 1), min_score=min_score)

        # Sinyal teyit kontrolü: Panel veya Push ile gelen tüm geçerli bildirimler
        # açık pozisyon yoksa otonom işleme alınır (2026-09-22 Erkan Kararı).

        # MOD FILTRESI (2026-10-07). Bos liste = filtre kapali (eski davranis).
        # Kanit: 3214 bildirim, 30 gun, gercek mum verisi -> trend_devam
        # +0.47%/islem (5/5 hafta pozitif, p~0.000) iken ayni donemde
        # global_lead_lag -0.13%, notr -0.70%, llm_ikinci_goz -0.27%.
        # Karisik havuz maliyet sonrasi negatif kaliyor; bu kapi yalnizca
        # otonom KATMANI moda gore suzer (push bildirimi engellenmez).
        allowed_modes = settings.get("allowed_modes") or []
        if allowed_modes:
            notif_mode = str(notification.get("mode") or "").strip()
            if notif_mode not in allowed_modes:
                logger.info("auto_paper %s: mod '%s' izinli listede degil %s — acilmadi",
                            symbol, notif_mode or "?", allowed_modes)
                return _blocked(symbol, "mode_not_allowed", mode=notif_mode,
                                allowed=allowed_modes)

        # BILDIRIM DEDUP (2026-10-07). Ayni sembolde kisa sure once giris
        # yapildiysa tekrar girme. Ayarlar > 0 ise devreye girer: ayni sinyal
        # 5 dakikada birden fazla kanaldan geliyordu ve her biri ayri pozisyon
        # aciyordu; 30 gunluk veride bu tekrarlar ortalamayi bozuyordu.
        dedup_min = float(settings.get("dedup_cooldown_minutes", 0.0) or 0.0)
        if dedup_min > 0:
            try:
                _last_entry = await database.get_last_auto_paper_entry_time(symbol)
            except Exception as exc:
                logger.debug("auto_paper %s dedup kontrol hatasi: %s", symbol, exc)
                _last_entry = None
            if _last_entry and (time.time() - _last_entry) < (dedup_min * 60.0):
                rem = round(dedup_min * 60.0 - (time.time() - _last_entry), 0)
                logger.info("auto_paper %s: ayni sembolde %.0f dk once giris yapildi — "
                            "tekrar acilmadi (kalan %.0f sn)", symbol, dedup_min, rem)
                return _blocked(symbol, "symbol_dedup", remaining_sec=rem,
                                dedup_cooldown_minutes=dedup_min)

        # R3-08 (P1): aday PANEL EŞİĞİNİ geçmiş olmalı (passing-only). Monitoring
        # yalnızca passing adayları bildirir; burada `passes` bayrağı açıkça False
        # erse giriş engellenir. Guard (koruma) metriği kanıtlarsa engellenmez;
        # anahtar yoksa da geçirgen kalınır (geriye dönük uyum).
        passes = notification.get("passes")
        if passes is not None and not bool(passes):
            logger.warning("auto_paper %s: aday panel şartını geçmedi (passes=False) — "
                           "açılmadı (R3-08)", symbol)
            return _blocked(symbol, "not_passing")

        # Savunma Derinliği: Master Surge veya Risk Kapısı engeli varsa açma (fail-closed)
        block_reason = notification.get("block_reason") or notification.get("surge_block_reason")
        if block_reason:
            logger.warning("auto_paper %s: risk engeli devrede (%s) — açılmadı", symbol, block_reason)
            return _blocked(symbol, f"risk_blocked:{block_reason}", block_reason=block_reason)
        if notification.get("master_surge_passed") is False:
            logger.warning("auto_paper %s: Master Surge kontrolünden geçmedi — açılmadı", symbol)
            return _blocked(symbol, "master_surge_failed")

        # LLM Sinyal Hakemi Kapısı: FAKE/Tuzak kararı varsa veya güven çok zayıfsa açma (2026-09-29 analiz kanıtı: +22.59 TRY koruma)
        if settings.get("llm_gate_enabled", True):
            llm_v = str(notification.get("llm_verdict") or "").strip().upper()
            try:
                llm_c = float(notification.get("llm_confidence") or 0)
            except (ValueError, TypeError):
                llm_c = 0.0
            min_c = float(settings.get("llm_min_confidence", 60.0))
            if llm_v in ("FAKE", "TUZAK") and llm_c >= 50:
                logger.warning("auto_paper %s: LLM İkinci Göz FAKE/TUZAK uyarısı verdi (Güven: %%%.0f) — işlem açılmadı", symbol, llm_c)
                return _blocked(symbol, "llm_fake_blocked", block_reason=f"LLM_FAKE_%{round(llm_c)}", verdict=llm_v, confidence=round(llm_c))
            if llm_v == "DEVAM" and llm_c > 0 and llm_c < min_c:
                logger.warning("auto_paper %s: LLM DEVAM dedi ancak güven yetersiz (%%%s < %%%s) — açılmadı", symbol, llm_c, min_c)
                return _blocked(symbol, "llm_low_confidence", block_reason="LLM_LOW_CONFIDENCE", verdict=llm_v, confidence=round(llm_c))

        # R3-07 (P0): SESSİZ SAATLERDE otonom işlem DURDURULUR. Web push'un sessiz
        # saatlerde ertelenmesi monitoring._notify içinde zaten korunur (onun
        # ALTERNATİFİ değil, POSITION açılışında ek kapı). Aday bir sonraki taramada
        # (sessiz saat bitince) yeniden değerlendirilir — doğal retry. Ertelemeyi
        # buraya uygulamıyoruz: sessiz aralık boyunca pozisyon açmak istemiyoruz.
        try:
            from app.routers import monitoring as _monitoring_mod
            if await _monitoring_mod.quiet_hours_active():
                logger.warning("auto_paper %s: sessiz saatler etkin — otonom işlem "
                            "açılmadı (R3-07)", symbol)
                return _blocked(symbol, "quiet_hours")
        except Exception as quiet_exc:
            # Sessizlik sorgusu BAŞARISIZ OLURSA KAPAT (fail-closed, R3-07 düzeltmesi):
            # eskiden sorgu hatasında AÇILIYORDU (fail-open) ve kullanıcı
            # sessiz saatlerde otonom pozisyon açıldığını görebiliyordu —
            # ayardaki R3-07 sözleşmesiyle çelişiyordu. Sessiz aralık
            # pozisyon açmaya izin vermez; aday bir sonraki taramada yeniden
            # değerlendirilir (doğal retry).
            logger.warning("auto_paper %s: sessiz saat sorgusu başarısız — işlem "
                        "açılmadı (fail-closed): %s", symbol, quiet_exc)
            return _blocked(symbol, "quiet_hours_query_error")

        # Stop-loss sonrası bekleme süresi (cooldown) kapısı (5 dk):
        # Stop olan sembole hemen peş peşe yeniden girip kayıp serisi (churn) yaratmayı engelle.
        now_ts = time.time()
        cooldown_min = float(settings.get("sl_cooldown_minutes", 5.0))
        sl_cooldown_until = _stop_loss_cooldowns.get(symbol, 0.0)
        if cooldown_min > 0 and now_ts >= sl_cooldown_until:
            try:
                last_sl = await database.get_last_auto_paper_stop_loss_time(symbol)
                if last_sl and (now_ts - last_sl) < (cooldown_min * 60.0):
                    sl_cooldown_until = last_sl + (cooldown_min * 60.0)
                    _stop_loss_cooldowns[symbol] = sl_cooldown_until
            except Exception as exc:
                logger.debug("auto_paper %s db sl cooldown kontrol hatası: %s", symbol, exc)

        if now_ts < sl_cooldown_until:
            rem = round(sl_cooldown_until - now_ts, 0)
            logger.info("auto_paper %s: stop_loss sonrası bekleme süresi devrede (kalan: %.0f sn) — açılmadı",
                        symbol, rem)
            return _blocked(symbol, "stop_loss_cooldown", remaining_sec=rem)

        # Kârlı işlem sonrası kâr koruma beklemesi (post-win cooldown) kapısı:
        # Kârla kapanan sembole hemen tekrar girip kârı geri verme tuzağını engeller (2026-09-29 analiz kanıtı: 9 işlemde -79.40 TRY kayıp).
        win_cooldown_min = float(settings.get("post_win_cooldown_minutes", getattr(config, "AUTO_PAPER_POST_WIN_COOLDOWN_MINUTES", 15.0)))
        win_cooldown_until = _post_win_cooldowns.get(symbol, 0.0)
        if win_cooldown_min > 0 and now_ts >= win_cooldown_until:
            try:
                last_win = await database.get_last_auto_paper_winning_trade_time(symbol)
                if last_win and (now_ts - last_win) < (win_cooldown_min * 60.0):
                    win_cooldown_until = last_win + (win_cooldown_min * 60.0)
                    _post_win_cooldowns[symbol] = win_cooldown_until
            except Exception as exc:
                logger.debug("auto_paper %s db post win cooldown kontrol hatası: %s", symbol, exc)

        if now_ts < win_cooldown_until:
            rem = round(win_cooldown_until - now_ts, 0)
            logger.info("auto_paper %s: karlı kapanış sonrası kâr koruma beklemesi devrede (kalan: %.0f sn) — açılmadı",
                        symbol, rem)
            return _blocked(symbol, "post_win_cooldown", remaining_sec=rem)

        # Aktif işleme giren sembol pasif listesinden temizlenir
        if hasattr(config, "PASSIVE_SYMBOLS") and isinstance(config.PASSIVE_SYMBOLS, set):
            config.PASSIVE_SYMBOLS.discard(symbol)

        # Mevcut fiyat
        ticker = market.get_ticker(symbol)
        current_price = float(ticker.get("last_price") or 0) if ticker else 0
        if current_price <= 0:
            current_price = float(notification.get("price") or 0)
        if current_price <= 0:
            return None

        # Ticker tazelik kapısı: REST ticker'ı getiremezse bildirim fiyatına
        # (detected_at anına ait, bayat) düşmek SL/TP çapasını yanlış sabitler.
        # Bildirim fiyatı yalnızca taze bir ticker ile doğrulanınca kullanılır.
        # (Denetim maddesi: otomatik açılışta bayat fiyata çapa riski.)
        try:
            freshness = market.ticker_freshness(symbol, max_age_sec=60)
        except Exception:
            freshness = {"fresh": False, "age_sec": None}

        # Eğer hafızada taze ticker yoksa (ör. sembol config.SYMBOLS dışındaki bir radar çiftiyse),
        # anlık REST ticker ile hafızayı güncelle:
        if not bool(freshness.get("fresh")):
            try:
                from app.binance_tr_public import ticker_price as _fetch_ticker_price
                price_rows = await _fetch_ticker_price([symbol])
                row = next((r for r in (price_rows or []) if str(r.get("symbol", "")).upper() == symbol), None)
                if row and float(row.get("price") or 0) > 0:
                    current_price = float(row["price"])
                    now_ms = int(time.time() * 1000)
                    market.tickers[symbol] = {
                        "symbol": symbol,
                        "last_price": current_price,
                        "timestamp": now_ms,
                        "source": "binance_tr_rest_auto_paper",
                    }
                    freshness = {"fresh": True, "age_sec": 0.0}
            except Exception as exc:
                logger.warning("auto_paper %s: REST ticker fetch hatası: %s", symbol, exc)

        # Eğer REST de erişilemediyse ama bildirim taze (son 60s) ve fiyatı varsa fallback kullan:
        if not bool(freshness.get("fresh")):
            notif_time = float(notification.get("detected_at") or notification.get("timestamp") or 0)
            if notif_time > 1e11:
                notif_time /= 1000.0
            if notif_time > 0 and (time.time() - notif_time) <= 60.0 and float(notification.get("price") or 0) > 0:
                current_price = float(notification["price"])
                now_ms = int(time.time() * 1000)
                market.tickers[symbol] = {
                    "symbol": symbol,
                    "last_price": current_price,
                    "timestamp": now_ms,
                    "source": "notification_fallback",
                }
                freshness = {"fresh": True, "age_sec": round(time.time() - notif_time, 1)}

        if current_price <= 0:
            current_price = float(notification.get("price") or 0)

        if not bool(freshness.get("fresh")) or current_price <= 0:
            logger.warning("auto_paper %s: taze ticker yok (age=%ss) — bayat fiyata "
                        "açılış engellendi", symbol, freshness.get("age_sec"))
            return _blocked(symbol, "stale_ticker", price=current_price, age_sec=freshness.get("age_sec"))

        # MACD MTF Konfluans Kapısı: ZAYIF MTF / Yüksek sahte kırılım (%75 fake) filtresi
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
                    pass
            if mtf_verdict == "ZAYIF" or (mtf_confluence is not None and float(mtf_confluence) < min_mtf_confluence):
                logger.warning("auto_paper %s: MACD MTF ZAYIF (skor=%s < %.1f, verdict=%s) — sahte kırılım riskiyle açılmadı",
                               symbol, mtf_confluence, min_mtf_confluence, mtf_verdict)
                return _blocked(symbol, "weak_mtf_confluence", price=current_price,
                                confluence=mtf_confluence, verdict=mtf_verdict)

        notification_id = notification.get("id")
        notification_key = notification.get("notification_key")
        # Aynı bildirim daha önce bir trade'e dönüşüyse: trailing/breakeven ile
        # kapandıysa ve fiyat hâlâ bildirim fiyatının üzerindeyse + ufuk süresi
        # dolmadıysa + hedefe ulaşılmadıysa YENİDEN açmaya izin ver. (Böylece kâr
        # kilidi/trailing çıkışı sonrası aynı fırsat devam ediyorsa kaçırılmaz;
        # diğer kapanış nedenleri tekrar açılışı engeller.)
        now = time.time()
        # R3-09 (P0): yeniden-açma (reopen) akışı, churn kontrolünü artık
        # `notification_key` (TEXT kolon) üzerinden yapar. Eski kod string'i
        # `notification_id` (bigint) içine yazıyordu → PostgreSQL tip hatası sessiz
        # yutuluyor ve yeniden açma HİÇ ÇALIŞMIYORDU. Normal (monitoring) bildirimler
        # integer id taşır ve `notification_id` bigint'i üzerinden geçerli kalır.
        prior_trade = None
        if notification_key is not None:
            # Reopen: kararlı anahtara göre churn koruması — saat başına en fazla bir.
            try:
                prior_trade = await database.get_recent_auto_paper_trade_by_notification_key(
                    str(notification_key))
            except Exception:
                prior_trade = None
            if prior_trade:
                logger.info("auto_paper %s: bildirim anahtarı %s daha önce işlendi — "
                            "yeniden açılmadı (R3-09)", symbol, notification_key)
                return None
        elif notification_id is not None:
            # Normal bildirim: id yalnızca tam sayı olabilir (bigint). String id
            # asla bigint'e yazılmaz/atanmaz → tip hatası riski yok.
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
            if prior_trade:
                # "Trailing/breakeven sonrası yeniden açma" kapalıysa eski davranış:
                # aynı bildirimle asla tekrar açma.
                if not bool(settings.get("reopen_after_protect_close", config.AUTO_PAPER_REOPEN_AFTER_PROTECT_CLOSE)):
                    return None

                # Kapanış biçimi nedir?
                exit_reason = str(prior_trade.get("exit_reason") or "").lower()
                trailing_kapanis = exit_reason in {"trailing_stop", "breakeven_stop"}
                if not trailing_kapanis:
                    # TP/SL/reset ile kapandıysa aynı bildirimle tekrar açma.
                    return None

                # Koşul 1: güncel fiyat bildirim fiyatının üzerinde olmalı.
                notif_price = float(notification.get("price") or 0)
                if notif_price <= 0 or current_price <= notif_price:
                    logger.info("auto_paper %s: trailing kapanış sonrası fiyat bildirim "
                                "fiyatının altında (%s <= %s) — yeniden açılmadı",
                                symbol, current_price, notif_price)
                    return None

                # Koşul 2: ufuk süresi henüz dolmamalı (bildirim detected_at + horizon).
                detected_at = float(notification.get("detected_at") or 0)
                horizon_min = float(notification.get("horizon_minutes") or 0)
                ufuk_bitti = bool(detected_at and horizon_min and (detected_at + horizon_min * 60) < now)
                if ufuk_bitti:
                    logger.info("auto_paper %s: trailing kapanış sonrası ufuk süresi doldu — yeniden açılmadı", symbol)
                    return None

                # Koşul 3: hedefe (take_profit) ulaşılmamış olmalı. Trailing/breakeven
                # zaten TP'ye ulaşmadan kapanış olduğu için bu genellikle otomatik
                # sağlar; yine de açık kontrol edilir. (Eski "fiyat yükselme
                # eğilimindedir" koşulu, trailing çıkışında fiyat zirveden
                # düştüğü için hep false dönüp yeniden açmayı engelliyordu.)
                prior_tp = float(prior_trade.get("take_profit") or 0)
                if prior_tp > 0 and current_price >= prior_tp:
                    logger.info("auto_paper %s: trailing kapanış sonrası hedefe ulaşıldı "
                                "(%s >= %s) — yeniden açılmadı",
                                symbol, current_price, prior_tp)
                    return None

                logger.info("auto_paper %s: trailing/breakeven kapanışı sonrası koşullar "
                            "sağlanıyor (%s) — aynı bildirimle yeniden işlem açılıyor",
                            symbol, exit_reason)

        # Mevcut açık auto_paper pozisyonunu kontrol et
        open_trade = await database.get_open_auto_paper_trade(symbol)

        if open_trade:
            # Açık pozisyon var → TP güncelle (bildirim hedefini takip et)
            return await _update_existing_trade(open_trade, notification, current_price)
        # Global maksimum açık pozisyon sınırı (varsayılan 8 — Erkan kararı,
        # 2026-09-18). ÖNCE çalışma-anı DB ayarı (Ayarlar > Otonom Paper Trade
        # > Max açık pozisyon); yoksa sınıf varsayılanı. 0 = sınırsız (yalnız
        # env ile verilir; UI 0'a izin vermez).
        # R3-06 (c): sembol-başı sınır yukarıda `open_trade` ile korunur; global
        # sınır ise burada. Engel NEDENÎ ile döndürülür (sessiz düşme yok).
        # Denetim notu (atomiklik): bu sayım ile `_open_new_trade` içindeki insert
        # arasında yarış penceresi VAR; kök neden düzeltmesi DB katmanında —
        # `insert_auto_paper_trade` advisory xact_lock'lu op içinde global limiti
        # yeniden sayar (aşağıdaki `_AUTO_PAPER_GLOBAL_LIMIT_NOTE`).
        max_open = int(settings.get("max_open_positions",
                     getattr(config, "AUTO_PAPER_MAX_OPEN_POSITIONS", 0)))
        if max_open > 0:
            open_count = len(await database.list_auto_paper_trades(status="open"))
            if open_count >= max_open:
                logger.warning("auto_paper %s: max açık pozisyon (%d/%d) — açılmadı "
                               "(R3-06)", symbol, open_count, max_open)
                return _blocked(symbol, "max_open", price=current_price, open_count=open_count, max_open=max_open)

        # R3-06 (a/b): girişten önce LİKİDİTE + KORELASYON KÜME kapısı. order_value
        # burada hesaplanıp `_open_new_trade`'e iletilir (tek wallet okuması).
        balance = await database.get_wallet_balance()
        balance_pct = float(settings.get("balance_pct", config.AUTO_PAPER_BALANCE_PCT_DEFAULT)) / 100.0
        order_value = balance * balance_pct
        gate = await _liquidity_cluster_gate(symbol, order_value, balance)
        if gate is not None:
            logger.warning("auto_paper %s giriş engellendi: %s (R3-06)", symbol, gate.get("reason"))
            return gate

        # Yeni pozisyon aç (atomik; DB tarafında çift-açılış kontrolü de var)
        return await _open_new_trade(symbol, notification, current_price, settings,
                                    order_value=order_value, balance=balance)
    except Exception as exc:
        logger.exception("auto_paper try_open: %s", exc)
        return None


async def _open_new_trade(symbol: str, notification: dict, current_price: float, settings: dict,
                          order_value: float | None = None, balance: float | None = None) -> dict | None:
    """Yeni otonom paper pozisyonu aç — atomik DB işlemi (open_auto_paper_trade).
    
    R3-06: `order_value`/`balance` önceden hesaplanıp iletilmişse yeniden okunmaz
    (likidite kapısı ile açılışta aynı değerler kullanılır — tutarlılık).
    """
    try:
        balance_pct = float(settings.get("balance_pct", config.AUTO_PAPER_BALANCE_PCT_DEFAULT)) / 100.0
        min_order = float(settings.get("min_order_try", config.AUTO_PAPER_MIN_ORDER_TRY))

        # Bakiye kontrolü — R3-06: çağıran (try_open) önceden hesapladıysa onu kullan.
        if balance is None:
            balance = await database.get_wallet_balance()
        if order_value is None:
            order_value = balance * balance_pct
        # RİSK SİZİNG (2026-09-16 denetimi): ESKİDEN `order_value < min_order` iken
        # `order_value = balance` yapılıyordu → tek pozisyona TÜM bakiye gidiyordu ve
        # `balance_pct` fiilen baypas ediliyordu. Ölçülebilir örnek: bakiye 100 TRY,
        # `balance_pct=%35`, `min_order_try=50` → 100 TRY açılış = riskin %100'ü.
        # Bu hem risk kontrolünü hem boyut kanıtını (sizing raporu) bozar.
        # Doğru davranış: risk bütçesi geçerli bir emir üretemiyorsa AÇMA (fail-closed)
        # ve nedeni görünür kıl — operatör `balance_pct`/`min_order_try` ayarlarını
        # kendisi hizalar. (R3-06 deseni: sessiz düşme yok.)
        if order_value < min_order:
            # 2026-09-27: metin `TRY` sabitiydi. deployment quote'u
            # (`config.QUOTE_ASSET`, TR→TRY) kullanılır — bakiye cinsi tanım
            # gereği quote cinsidir, sembol ekinden türetmeye gerek yok.
            quote = config.QUOTE_ASSET
            logger.warning(
                "auto_paper %s: risk bütçesi yetersiz (bakiye %.2f %s × %%%.1f = %.2f %s "
                "< min emir %.2f %s) — açılmadı; balance_pct/min_order_try ayarlayın",
                symbol, balance, quote, balance_pct * 100, order_value, quote,
                min_order, quote)
            return _blocked(symbol, "order_below_min",
                            price=current_price,
                            order_value=round(order_value, 2),
                            min_order=min_order,
                            balance=round(balance, 2),
                            balance_pct=round(balance_pct * 100, 2))

        sl_pct = float(settings.get("stop_loss_pct", config.AUTO_PAPER_SL_PCT_DEFAULT)) / 100.0
        target_pct = _effective_target_pct(notification)
        if target_pct <= 0:
            target_pct = float(settings.get("default_target_pct", config.AUTO_PAPER_DEFAULT_TARGET_PCT))

        # Master Surge iki kademeli hedefleme: bildirimde TP2 koşucu hedefi varsa
        # nihai hedef TP2'dir. DÜZELTME (2026-10-07): bu blok ESKİDEN TP fiyatı
        # hesaplandıktan SONRA çalışıyordu → `target_pct` yükseliyor ama
        # `take_profit_price` eski (düşük) değerde kalıyordu; DB'ye ise
        # yükseltilmiş `notification_target_pct` yazılıyordu. Sonuç: kayıtta
        # emrin asla ulaşamayacağı bir hedef görünüyordu (durum tutarsızlığı).
        # Artık TP2, TP fiyatı hesaplanmadan ÖNCE uygulanır.
        tp1_scalp_val = notification.get("tp1_scalp_pct")
        tp2_runner_val = notification.get("tp2_runner_pct")
        if tp2_runner_val and float(tp2_runner_val) > target_pct:
            target_pct = float(tp2_runner_val)

        # HEDEF TAVANI (2026-10-07 incelemesi). `default_target_pct` ayarı
        # buraya HİÇ etki etmiyordu: TP, bildirimin kendi `target_pct`'inden
        # gelir ve o ortalama +%3,90'dır. Ölçüm (1537 kapanan işlem + 9740
        # değerlendirilmiş aday): ulaşılan tepe medyanı +%1,62, yani hedef
        # ulaşılabilir tepenin ~2,4 katıydı; işlemlerin yalnızca %13'ü hedefe
        # değiyordu. Tavan, hedefi realize edilebilir bir aralığa çeker.
        # 0 = sınırsız (eski davranış); geriye dönük uyum için kapalı bırakılabilir.
        max_target = float(settings.get("max_target_pct", 0.0) or 0.0)
        if max_target > 0 and target_pct > max_target:
            logger.info("auto_paper %s: bildirim hedefi +%.2f%% tavanı +%.2f%%'e çekildi",
                        symbol, target_pct, max_target)
            target_pct = max_target

        commission_pct = config.COMMISSION_PCT
        max_cost = order_value / (1 + commission_pct)
        # D-08 (2026-09-12): fiilî ALIŞ dolumuna kayma (slippage) uygula. Maliyet
        # tabanı ve adet bu dolumdan türetilir; quantity*entry_price = max_cost
        # kimliği korunur (boyut raporu ile muhasebe tutarlı kalır). Tek kaynak:
        # config.ESTIMATED_SLIPPAGE_PCT.
        entry_slip = float(getattr(config, "ESTIMATED_SLIPPAGE_PCT", 0.0) or 0.0)
        fill_entry = current_price * (1.0 + entry_slip)
        quantity = max_cost / fill_entry if fill_entry > 0 else 0
        if quantity <= 0:
            return None

        net_order_value = fill_entry * quantity
        # ERKAN İSTEĞİ (2026-09-18): TP hedefi NET olacak — gidiş-dönüş komisyon
        # + SATIŞ kayması mark-up'a eklenir (giriş kayması zaten fill_entry
        # çapasında). Bildirimdeki +%2.0 hedefi artık net +%2.0 realize eder:
        # TP brüt = 2.0 + 2×0.15 + 0.025 ≈ +2.325%. Kapanış muhasebesi
        # (`_close_trade`) ZATEN komisyon+ kaymayı düşüyor; çapası da
        # mark-up'lı olmalı ki bildirimdeki hedef gerçekten realize edilsin.
        cost_markup = 2 * commission_pct + float(getattr(config, "ESTIMATED_SLIPPAGE_PCT", 0.0) or 0.0)
        take_profit_price = fill_entry * (1 + target_pct / 100 + cost_markup)

        # Volatiliteye duyarlı Stop Loss (ATR koruması):
        # 5m gürültüsü içinde normal -%1.6-1.8 geri çekilmelerde erken stop olmamak için
        # ATR'ye göre nefes alma payı (maksimum %2.8 ile sınırlı).
        volatility_sl_enabled = bool(settings.get("volatility_sl_enabled", True))
        effective_sl_pct = sl_pct
        if volatility_sl_enabled:
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
                            # 1.2 * ATR_pct nefes alma alanı, minimum sl_pct.
                            # DÜZELTME (2026-10-07): eski kod `max(sl_pct, min(TABAN, 1.2*atr))`
                            # idi. sl_pct TABANDAN genişse (canlıda %4 > %2,8 iken)
                            # max() her zaman sl_pct döndürüyordu → bu koruma
                            # SESSİZCE tamamen devre dışı kalıyordu. Artık tavan
                            # yalnızca ATR tarafını sınırlar; `max(sl_pct, ...)`
                            # değişmezi (koruma asla stop'u DARALTMAZ) korunur.
                            effective_sl_pct = max(sl_pct, min(sl_pct, 1.2 * atr_pct))
            except Exception as atr_err:
                logger.debug("auto_paper %s: ATR stop hesaplama atlandı: %s", symbol, atr_err)

        stop_loss_price = fill_entry * (1 - effective_sl_pct)
        now = time.time()
        # R3-09 (P0): `notification_id` bigint kolonuna yalnızca TAM SAYI yazılır.
        # Reopen akışının string anahtarı ayrı `notification_key` (TEXT kolon)
        # olarak taşınır. String `id` → notification_id NULL, key doldurulur.
        raw_nid = notification.get("id")
        notification_id_val = None
        if isinstance(raw_nid, int):
            notification_id_val = raw_nid
        elif isinstance(raw_nid, str) and raw_nid.lstrip("-").isdigit():
            notification_id_val = int(raw_nid)
        notification_key = notification.get("notification_key")

        # NOT (2026-10-07): Master Surge TP2 yükseltmesi buradan YUKARI taşındı
        # (TP fiyatı hesaplanmadan önce). Burada ikinci kez uygulanırsa
        # `take_profit_price` eski değerde kalırken `notification_target_pct`
        # yükselir → kayıtta tutarsız/ulaşılamaz hedef görünürdü.

        trade_data = {
            "symbol": symbol,
            "side": "LONG",
            "status": "open",
            "notification_id": notification_id_val,
            "notification_key": notification_key,
            "entry_price": fill_entry,
            "quantity": quantity,
            "order_value_try": net_order_value,
            "stop_loss": stop_loss_price,
            "take_profit": take_profit_price,
            "peak_price": fill_entry,
            "entry_time": now,
            "notification_score": notification.get("score"),
            "notification_target_pct": target_pct,
            "notification_expected_price": notification.get("expected_price"),
            "tp1_scalp_pct": float(tp1_scalp_val) if tp1_scalp_val is not None else None,
            "tp2_runner_pct": float(tp2_runner_val) if tp2_runner_val is not None else None,
            "confluence_4way": bool(notification.get("confluence_4way")),
            "trailing_gap_pct": float(getattr(config, "MASTER_SURGE_BE_GAP_PCT", 0.40)) if notification.get("confluence_4way") else None,
            "created_at": now,
            "updated_at": now,
        }
        signal = {
            "timestamp": now,
            "symbol": symbol,
            "action": "BUY_SIGNAL",
            "price": fill_entry,
            "reason": f"AUTO_PAPER skor {notification.get('score', 0):.1f} hedef +%{target_pct:.1f} TP={take_profit_price:.6f} SL={stop_loss_price:.6f}",
            "strategy": "AUTO_PAPER",
            "trade_id": None,  # insert sonrası id bilinir; DB'de dolduramayız, reason yeterli
            # D-11/Erkan (2026-09-18): çalışma-anı sınırını DB katmanının
            # advisory-lock'lu ikinci savunmasına taşı (yarış penceresi kapanır).
            "max_open_positions": int(settings.get("max_open_positions",
                                     getattr(config, "AUTO_PAPER_MAX_OPEN_POSITIONS", 0))),
        }
        trade, status = await database.open_auto_paper_trade(trade_data, signal)

        if status == "already_open":
            # Arada başka bir çağrı açmış — onu güncellemeyi dene
            open_trade = await database.get_open_auto_paper_trade(symbol)
            if open_trade:
                return await _update_existing_trade(open_trade, notification, current_price)
            return None
        if status == "already_traded":
            # R3-09 sonrası düzeltme: burada `notification_id` ADI KULLANILMAZDI —
            # R3-09 `notification_id_val` (bigint'e yazılabilir) ve
            # `notification_key` (TEXT, string id) olarak ikiye ayırdı, bu satır
            # eski adda kaldı → dal çalışınca NameError, sessizce yutuluyordu.
            # Log, DB'ye yazılan değeri (`notification_id_val`) ve string id'yi
            # (`notification_key`) birlikte gösterir: string id'de sadece key
            # doludur, tam sayı id'de sadece notification_id_val.
            logger.info("auto_paper %s: bildirim id=%s key=%s zaten işlendi — açılmadı",
                        symbol, notification_id_val, notification_key)
            return None
        if status == "max_open":
            # Advisory-lock'lu op içindeki ikinci savunma: arada başka tarama
            # tetiği limiti doldurdu — sessiz None yerine görünür log.
            logger.warning("auto_paper %s: transaction içinde max açık pozisyon dolu — açılmadı", symbol)
            return None
        if status == "insufficient_balance":
            logger.info("auto_paper %s: transaction'da bakiye yetersiz", symbol)
            return None
        if not trade or status != "opened":
            return None

        trade_id = trade["id"]
        # trade_id'yi sinyale geri yazamayız (transaction kapandı); id'yi state'te tut
        _AUTO_PAPER_STATE["total_opened"] += 1

        # Açılan sembolü anında akış evrenine ekle (market.symbols içinde kalsın ve WS/tazelik verisi canlı aksın)
        try:
            extend_stream_universe([symbol], source="auto_paper_open")
            asyncio.create_task(market.ensure_history(config.PRIORITY_TIMEFRAMES, symbols=[symbol.lower()]))
        except Exception as exc:
            logger.warning("auto_paper %s akış evrenine ekleme hatası: %s", symbol, exc)

        await _broadcast_trade({
            "action": "OPENED", "symbol": symbol,
            "entry": fill_entry, "take_profit": take_profit_price,
            "stop_loss": stop_loss_price, "quantity": quantity,
            "order_value": net_order_value, "score": notification.get("score"),
            "target_pct": target_pct, "trade_id": trade_id,
        })

        logger.info("auto_paper %s: AÇILDI miktar=%.4f giriş=%.6f TP=%.6f SL=%.6f değer=%.2f %s skor=%.1f",
                    symbol, quantity, fill_entry, take_profit_price, stop_loss_price,
                    net_order_value, config.QUOTE_ASSET, notification.get("score"))

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
    try:
        target_pct = _effective_target_pct(notification)
        if target_pct <= 0:
            return None

        entry_price = float(open_trade["entry_price"])
        # ERKAN İSTEĞİ (2026-09-18): TP-güncelleme de NET hedefe göre — giriş
        # kapasıyla AYNI mark-up (`_open_new_trade` ile tutarlı); aksi halde
        # güncellenen pozisyonun hedefi mark-up'sız kalırdı.
        cost_markup = 2 * config.COMMISSION_PCT + float(getattr(config, "ESTIMATED_SLIPPAGE_PCT", 0.0) or 0.0)
        new_tp = entry_price * (1 + target_pct / 100 + cost_markup)
        old_tp = float(open_trade.get("take_profit") or 0)

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
    await asyncio.sleep(30)
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
    trades = await database.list_auto_paper_trades(status="open")
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


async def _manage_single_trade(trade: dict, now: float, breakeven_trigger_pct: float = 1.5, settings: dict | None = None):
    """Tek bir auto_paper pozisyonunu yönet: TP/SL/breakeven/trailing."""
    symbol = str(trade.get("symbol") or "").upper()
    trade_id = int(trade["id"])
    entry_price = float(trade["entry_price"])
    stop_loss = float(trade["stop_loss"]) if trade.get("stop_loss") else None
    take_profit = float(trade["take_profit"]) if trade.get("take_profit") else None
    quantity = float(trade["quantity"])
    commission_pct = config.COMMISSION_PCT
    # D-01 (2026-09-26 denetimi): kâr kilidi stop'u HER ZAMAN orijinal
    # stop_loss'tan daha yukarıdadır; bu yüzden `stop_loss` kontrolü kâr
    # kilidi kontrolünden ÖNCE çalışırsa, kâr kilidi aktifken daha düşük
    # fiyattan kapanılır ve kâr kilidi fiilen devre dışı kalır. Etkin stop
    # = max(stop_loss, breakeven_stop) olmalı; bu değer aşağıdaki SL
    # kontrolünde VE (breakeven/trailing bloklarındaki) kâr koruma
    # kontrolünde tek kaynak olarak kullanılır.
    _breakeven_stop_db = float(trade.get("breakeven_stop") or 0)
    _breakeven_activated_db = bool(trade.get("breakeven_activated", False))
    effective_stop_loss = stop_loss
    if _breakeven_activated_db and _breakeven_stop_db > 0:
        effective_stop_loss = max(stop_loss, _breakeven_stop_db) if stop_loss is not None else _breakeven_stop_db
    elif _breakeven_stop_db > 0:
        # Breakeven fiyatı yazılmış ama bayrak henüz set edilmemişse de
        # (DB yazma sırası/yarış durumu) kâr koruması geçerlidir.
        effective_stop_loss = max(stop_loss, _breakeven_stop_db) if stop_loss is not None else _breakeven_stop_db

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
    price_is_fresh = bool(current_price > 0 and ticker_ts
                          and (now * 1000 - ticker_ts) <= config.MAX_TICKER_AGE_SEC * 1000)
    if current_price > 0 and not price_is_fresh:
        logger.warning("auto_paper %s: ticker BAYAT (yaş=%.1fs > %ss) — bu tur kâr/zarar muhasebesi yapılmıyor",
                       symbol, (now * 1000 - ticker_ts) / 1000.0, config.MAX_TICKER_AGE_SEC)

    # 1. SÜRE KONTROLÜ (2026-09-21 Erkan kararı: Maksimum 60 dk):
    # Fiyat bayat veya ticker boş olsa bile 60 dk dolmuşsa pozisyon kâr/zarara bakılmaksızın kapatılır.
    entry_time = float(trade.get("entry_time") or trade.get("created_at") or 0)
    hold_minutes = (now - entry_time) / 60.0 if entry_time > 0 else 0.0
    max_hold_minutes = float((settings or {}).get("max_hold_minutes", getattr(config, "AUTO_PAPER_MAX_HOLD_MINUTES", 60.0)))
    if max_hold_minutes > 0 and hold_minutes >= max_hold_minutes:
        # D-02: bayat/eksik fiyatla KAPANMA YAPILMAZ. Pozisyon bir sonraki
        # tazelik turunda kapatılır (gerekirse peak_price fallback'i ile
        # bilinçli olarak).
        if not price_is_fresh:
            logger.info("auto_paper %s: max_hold doldu ama fiyat bayat — kapanış ertelendi (%.1f dk)",
                        symbol, hold_minutes)
            return
        exit_price = current_price if current_price > 0 else float(trade.get("peak_price") or entry_price)
        logger.info("auto_paper %s: MAKSİMUM SÜRE DOLDU (%.1f dk >= %.1f dk) — pozisyon kapatılıyor (çıkış=%.6f)",
                    symbol, hold_minutes, max_hold_minutes, exit_price)
        await _close_trade(trade_id, symbol, exit_price, now, "max_duration")
        return

    # 2. SEMBOL STREAM GÜVENLİĞİ VE PASİF KONTROLÜ:
    # Açık pozisyonu olan sembol her zaman WebSocket akışında tutulmalı (asla bu yüzden kapatılmaz)
    market_symbols = getattr(market, "symbols", None)
    if isinstance(market_symbols, (list, set, tuple)):
        symbols_lower = {str(s).lower() for s in market_symbols if isinstance(s, str)}
        if symbols_lower and symbol.lower() not in symbols_lower:
            try:
                extend_stream_universe([symbol], source="auto_paper_stream_guard")
            except Exception as exc:
                logger.warning("auto_paper %s akış evrenine ekleme koruması: %s", symbol, exc)

    # Yalnızca açıkça doğrulanmış durağan/ölü semboller (gerçekten ölü tahta / hacimsiz)
    passive_symbols = getattr(config, "PASSIVE_SYMBOLS", None)
    is_passive = bool(passive_symbols and symbol in passive_symbols)

    if is_passive:
        # D-02: aynı tazelik kuralı — bayat fiyatla kapatma yapılmaz.
        if not price_is_fresh:
            logger.info("auto_paper %s: sembol pasif ama fiyat bayat — kapanış ertelendi", symbol)
            return
        exit_price = current_price if current_price > 0 else float(trade.get("peak_price") or entry_price)
        logger.info("auto_paper %s: SEMBOL PASİFE ALINMIŞ (doğrulanmış durağan) — açık pozisyon kapatılıyor (çıkış=%.6f)",
                    symbol, exit_price)
        await _close_trade(trade_id, symbol, exit_price, now, "symbol_deactivated")
        return

    if not price_is_fresh:
        return

    # B1: TP is PRIMARY exit — evaluated before any trailing/breakeven logic.
    tp_primary_exit_enabled = bool((settings or {}).get("tp_primary_exit_enabled", getattr(config, "AUTO_PAPER_TP_PRIMARY_ENABLED", True)))
    if tp_primary_exit_enabled and take_profit is not None and current_price >= take_profit:
        # D-08 (2026-09-12): TP dolumu TETİK fiyatından (gap-through: min(price, tp)).
        await _close_trade(trade_id, symbol, min(current_price, take_profit), now, "take_profit")
        return

    # Peak güncelle
    peak_price = max(float(trade.get("peak_price") or entry_price), current_price)
    if peak_price > float(trade.get("peak_price") or entry_price):
        await database.update_auto_paper_peak(trade_id, peak_price)

    # SL kontrolü — D-08: dolum tetik fiyatından (gap-through: max(price, sl)).
    # D-01 (2026-09-26): burada ARTık `stop_loss` değil `effective_stop_loss`
    # kullanılır — kâr kilidi aktifken orijinal stop'tan daha yüksekte
    # kapanış olur (aşağıdaki breakeven korumasıyla aynı mantık).
    if effective_stop_loss is not None and current_price <= effective_stop_loss:
        await _close_trade(trade_id, symbol, max(current_price, effective_stop_loss), now,
                           "breakeven_stop" if (effective_stop_loss != stop_loss) else "stop_loss")
        return

    # Kâr ve TP oranları
    gross_pnl_pct = ((current_price - entry_price) / entry_price * 100) if entry_price else 0
    tp_gain_pct = None
    if take_profit is not None and entry_price > 0 and take_profit > entry_price:
        tp_gain_pct = (take_profit - entry_price) / entry_price * 100

    # Breakeven kontrolü (isteğe bağlı — erken minik kârla çıkıp ralliyi kaçırmamak için
    # varsayılan KAPALI, 2026-09-22 Erkan kararı).
    breakeven_enabled = bool((settings or {}).get("breakeven_enabled", getattr(config, "AUTO_PAPER_BREAKEVEN_ENABLED", True)))
    BREAKEVEN_TRAIL_GAP_PCT = float(getattr(config, "AUTO_PAPER_TRAILING_GAP_PCT", 0.60))
    if breakeven_enabled:
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
            BREAKEVEN_TRAIL_GAP_PCT = float(getattr(config, "AUTO_PAPER_TRAILING_GAP_PCT", 0.60))
        # In-memory breakeven stop: DB'ye yazılan değerle aynı turdaki koruma
        # kontrolü arasında gecikme olmasın.
        current_breakeven_stop = float(trade.get("breakeven_stop") or 0)

        if gross_pnl_pct >= breakeven_trigger_pct:
            # NET taban (2026-09-18 hassasiyeti): gidiş-dönüş komisyon + SATIŞ dolum
            # kayması dahil (giriş kayması zaten çapa fill_entry'de). Bu fiyattan
            # satış, `_close_trade` muhasebesi sonrası daima pozitif net verir.
            exit_slip = float(getattr(config, "ESTIMATED_SLIPPAGE_PCT", 0.0) or 0.0)
            net_floor = entry_price * (1 + 2 * commission_pct + exit_slip + breakeven_buffer_pct / 100)
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
        # D-08: stop dolumu tetik fiyatından (gap-through: max(price, stop)).
        if breakeven_activated and current_breakeven_stop > 0 and current_price <= current_breakeven_stop:
            await _close_trade(trade_id, symbol, max(current_price, current_breakeven_stop), now, "breakeven_stop")
            return

    # Trailing stop modülü (kullanıcı isteği 2026-09-08): %trailing_trigger_pct
    # kara geçince fiyatı %trailing_gap_pct geriden takip eder. Varsayılan AÇIK;
    # ayarlardan kapatılabilir (trailing_enabled=false).
    trailing_enabled = bool((settings or {}).get("trailing_enabled", config.AUTO_PAPER_TRAILING_ENABLED))
    if trailing_enabled:
        trailing_trigger_pct = float((settings or {}).get("trailing_trigger_pct", config.AUTO_PAPER_TRAILING_TRIGGER_PCT))
        trailing_gap_pct = float((settings or {}).get("trailing_gap_pct", config.AUTO_PAPER_TRAILING_GAP_PCT))

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
            trailing_gap_pct = min(trailing_gap_pct, BREAKEVEN_TRAIL_GAP_PCT)

        trailing_activated = bool(trade.get("trailing_activated", False))
        current_trailing_stop = float(trade.get("trailing_stop") or 0)

        # Aktif değilse ve kâr trigger eşiğine ulaşıldıysa trailing'i devreye al.
        if not trailing_activated and gross_pnl_pct >= trailing_trigger_pct:
            trailing_activated = True

        if trailing_activated:
            # Zirvenin %gap gerisinden stop; yalnızca yukarı güncellenir (fiyat
            # yükseldikçe takip eder, düşerken eski stopta kalır).
            new_trailing = peak_price * (1 - trailing_gap_pct / 100)
            # İlk aktivasyonda stop güncel fiyatın altında kalmalı (anında kapanma olmasın).
            if not bool(trade.get("trailing_activated", False)) and new_trailing >= current_price:
                new_trailing = current_price * (1 - trailing_gap_pct / 100)
            applied_trailing = max(new_trailing, current_trailing_stop)
            if applied_trailing > current_trailing_stop:
                await database.update_auto_paper_trailing(trade_id, True, applied_trailing)
                current_trailing_stop = applied_trailing
                logger.info("auto_paper %s: trailing stop=%.6f (gross=%+.2f%%)", symbol, applied_trailing, gross_pnl_pct)

            # TP KORUMALI TRAILING (2026-09-28, kârlılık düzeltmesi):
            # Trailing devreye girdiğinde TP artık SİLİNMEZ. Fiyat TP'ye
            # ulaşırsa → TP ile kapanır (garanti kâr). Fiyat TP'ye ulaşmadan
            # geri dönerse → trailing stop ile kapanır (korumalı kâr).
            #
            # Eski davranış (2026-09-18): trailing aktivasyonunda TP=NULL yapılıyordu
            # ve çıkış tamamen trailing'e devrediliyordu. MFE verisi gösterdi ki
            # işlemlerin %93'ü kâra geçiyor ama TP silindiği için yalnızca %33'ü
            # kârla kapanıyordu — tepe ile çıkış arasında %1.73 sistematik kayıp.
            #
            # Yeni davranış: TP korunur; trailing stop TP'nin ÜZERİNE çıkarsa
            # TP yukarı ratchet'lenir (trailing stop seviyesine). Böylece:
            #  - Fiyat tahmin edilen artışın üzerinde yükselirse pozisyon taşınır ✓
            #  - Fiyat hedefe ulaştığında kâr GERÇEKTEN alınır ✓
            #  - Küçük geri çekilmelerde trailing kilitler ✓
            if take_profit is not None and applied_trailing > take_profit:
                # Trailing stop TP'nin üzerine çıktı → TP'yi yukarı ratchet'le
                # (trailing en az TP kadar koruyor, TP yükselince hedefe ulaşım garanti)
                try:
                    await database.update_auto_paper_trade_tp(trade_id, applied_trailing)
                    take_profit = applied_trailing
                    logger.info("auto_paper %s: trailing TP'nin üstüne çıktı — TP ratchet: %.6f (gross=%+.2f%%)",
                                symbol, applied_trailing, gross_pnl_pct)
                except Exception as tp_exc:
                    logger.warning("auto_paper %s: TP ratchet hatası: %s", symbol, tp_exc)

        # Trailing stop koruması: aktifse ve fiyat stopa düştüyse kapat.
        # D-08: stop dolumu tetik fiyatından (gap-through: max(price, stop)).
        if trailing_activated and current_trailing_stop > 0 and current_price <= current_trailing_stop:
            await _close_trade(trade_id, symbol, max(current_price, current_trailing_stop), now, "trailing_stop")


async def _close_trade(trade_id: int, symbol: str, exit_price: float, now: float, reason: str):
    """Auto paper pozisyonunu kapat ve wallet'a iade et (atomik DB işlemi)."""
    try:
        trade = await database.get_auto_paper_trade(trade_id)
        if not trade or trade.get("status") != "open":
            return

        entry_price = float(trade["entry_price"])
        quantity = float(trade["quantity"])
        commission_pct = config.COMMISSION_PCT
        # D-08 (2026-09-12): fiilî SATIŞ dolumuna kayma (slippage) uygula.
        # TP/SL tetik dolumu `_manage_single_trade` içinde tetik fiyatına
        # çekilir (min/max); kayma bunun ÜZERİNE uygulanır. Tek kaynak:
        # config.ESTIMATED_SLIPPAGE_PCT.
        exit_slip = float(getattr(config, "ESTIMATED_SLIPPAGE_PCT", 0.0) or 0.0)
        fill_price = exit_price * (1.0 - exit_slip)
        entry_commission = entry_price * quantity * commission_pct
        exit_commission = fill_price * quantity * commission_pct
        total_commission = entry_commission + exit_commission
        gross_pnl = (fill_price - entry_price) * quantity
        pnl = gross_pnl - total_commission
        invested = entry_price * quantity
        pnl_pct = (pnl / invested * 100) if invested else 0.0
        hold_seconds = now - float(trade["entry_time"])

        # DB güncelle + wallet iadesi + sinyal tek transaction'da
        closed = await database.close_auto_paper_trade(
            trade_id, fill_price, now, pnl, pnl_pct, total_commission, reason)
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

        if reason == "stop_loss":
            cooldown_min = float(settings.get("sl_cooldown_minutes", 5.0))
            if cooldown_min > 0:
                _stop_loss_cooldowns[symbol] = now + (cooldown_min * 60.0)
                logger.info("auto_paper %s: stop_loss sonrası %.0f dakika yeni giriş bekleme süresi (cooldown) başlatıldı",
                            symbol, cooldown_min)

    except Exception as exc:
        logger.exception("auto_paper %s kapatma: %s", symbol, exc)


#: D-06 (2026-09-12): koruma kapanışı sonrası yeniden açma denemeleri için saat
#: kovası. Aynı kova içinde üretilen bildirim id'si KARARLI olduğundan, DB'deki
#: `notification_id` churn kontrolü (auto_paper_trades.notification_id) saat
#: başına en fazla bir yeniden açmayı zorlar — eski kod `notification_id=None`
#: ile bu korumayı tamamen baypas ediyordu.
_REOPEN_HOUR_BUCKET_SEC = 3600
#: Tur/deneme sınırı: sembol başına son deneme zamanı (in-memory, tek süreç).
_reopen_last_attempt: dict[str, float] = {}


def _reopen_notification_id(symbol: str, now: float | None = None) -> str:
    """Yeniden açma için KARARLI bildirim kimliği (D-06).

    Format: ``reopen:{SYMBOL}:{hour_bucket}``. Saat kovası hem kararlıdır hem de
    saat başına en fazla bir yeniden açmayı DB churn kontrolü üzerinden zorlar.
    """
    bucket = int((now if now is not None else time.time()) // _REOPEN_HOUR_BUCKET_SEC)
    return f"reopen:{str(symbol).upper()}:{bucket}"


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

        # D-06: saat başına en fazla bir DENEME (başarısız deneme de sayılır).
        now = time.time()
        last_attempt = float(_reopen_last_attempt.get(symbol, 0) or 0)
        if now - last_attempt < _REOPEN_HOUR_BUCKET_SEC:
            logger.info("auto_paper %s: yeniden açma denemesi saatlik sınırda (%ds) — atlandı",
                        symbol, int(now - last_attempt))
            return
        _reopen_last_attempt[symbol] = now

        # D-06: kararlı bildirim id'si + mevcut dedup kontrolünü ZORLA. Bu saat
        # kovasında zaten bir yeniden açma yapıldıysa (DB'de notification_id var)
        # tekrar açma.
        reopen_id = _reopen_notification_id(symbol, now)
        try:
            prior_reopen = await database.get_recent_auto_paper_trade_by_notification(reopen_id)
        except Exception:
            prior_reopen = None
        if prior_reopen:
            logger.info("auto_paper %s: %s saat kovasında yeniden açma zaten yapıldı — atlandı",
                        symbol, reopen_id)
            return

        # monitoring'i tembel içe aktar (çevrimsel import riski olmasın).
        from app.routers import monitoring as monitoring_mod
        cand = monitoring_mod.get_cached_radar_candidate(symbol)
        if not cand:
            logger.info("auto_paper %s: koruma kapanışı sonrası radar 'uygun adaylar' "
                        "listesinde değil — yeniden açılmadı", symbol)
            return

        panel = float(cand.get("panel_score") or 0)
        if panel <= 0:
            try:
                panel = float(monitoring_mod.normalize_score(cand.get("velocity_score") or 0))
            except Exception:
                panel = 0.0
        if panel <= 0:
            return

        price = float(cand.get("price") or 0)
        target_pct = float(cand.get("target_pct") or 0)
        notif = {
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
        pass


# ---------------------------------------------------------------------------
# Settings API
# ---------------------------------------------------------------------------
async def get_default_settings() -> dict:
    return {
        "enabled": True,
        "min_score": config.AUTO_PAPER_MIN_SCORE_DEFAULT,
        "balance_pct": config.AUTO_PAPER_BALANCE_PCT_DEFAULT,
        "stop_loss_pct": config.AUTO_PAPER_SL_PCT_DEFAULT,
        "default_target_pct": config.AUTO_PAPER_DEFAULT_TARGET_PCT,
        # Hedef tavanı (2026-10-07): bildirimin kendi target_pct'i bunu aşarsa
        # TP bu değere çekilir. Env: AUTO_PAPER_MAX_TARGET_PCT. 0 = sınırsız.
        "max_target_pct": getattr(config, "AUTO_PAPER_MAX_TARGET_PCT", 0.0),
        "min_order_try": config.AUTO_PAPER_MIN_ORDER_TRY,
        "breakeven_enabled": getattr(config, "AUTO_PAPER_BREAKEVEN_ENABLED", False),
        "breakeven_trigger_pct": config.AUTO_PAPER_BREAKEVEN_TRIGGER_PCT,
        "trailing_enabled": config.AUTO_PAPER_TRAILING_ENABLED,
        "trailing_trigger_pct": config.AUTO_PAPER_TRAILING_TRIGGER_PCT,
        "trailing_gap_pct": config.AUTO_PAPER_TRAILING_GAP_PCT,
        "reopen_after_protect_close": config.AUTO_PAPER_REOPEN_AFTER_PROTECT_CLOSE,
        "tp_primary_exit_enabled": getattr(config, "AUTO_PAPER_TP_PRIMARY_ENABLED", True),
        "dynamic_breakeven_enabled": getattr(config, "AUTO_PAPER_DYNAMIC_BREAKEVEN_ENABLED", False),
        "dynamic_trailing_enabled": getattr(config, "AUTO_PAPER_DYNAMIC_TRAILING_ENABLED", False),
        "breakeven_buffer_pct": getattr(config, "AUTO_PAPER_BREAKEVEN_BUFFER_PCT", 0.02),
        "max_open_positions": config.AUTO_PAPER_MAX_OPEN_POSITIONS,
        "max_hold_minutes": getattr(config, "AUTO_PAPER_MAX_HOLD_MINUTES", 60.0),
        "block_weak_mtf": True,
        "min_mtf_confluence": 45.0,
        "sl_cooldown_minutes": 5.0,
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
        "allowed_modes": ["trend_devam"],
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
                "tp_primary_exit_enabled", "dynamic_breakeven_enabled",
                "dynamic_trailing_enabled", "breakeven_buffer_pct",
                "max_open_positions", "max_hold_minutes",
                "block_weak_mtf", "min_mtf_confluence",
                "sl_cooldown_minutes", "post_win_cooldown_minutes",
                "llm_gate_enabled", "llm_min_confidence",
                "volatility_sl_enabled",
                "allowed_modes", "dedup_cooldown_minutes")
    existing = await get_auto_paper_settings()
    merged = {**existing, **{k: payload[k] for k in editable if k in payload}}

    settings = {
        "enabled": bool(merged.get("enabled", True)),
        "min_score": max(0.0, min(100.0, float(merged.get("min_score", config.AUTO_PAPER_MIN_SCORE_DEFAULT)))),
        "balance_pct": max(1.0, min(100.0, float(merged.get("balance_pct", config.AUTO_PAPER_BALANCE_PCT_DEFAULT)))),
        "stop_loss_pct": max(0.1, min(20.0, float(merged.get("stop_loss_pct", config.AUTO_PAPER_SL_PCT_DEFAULT)))),
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
        "trailing_trigger_pct": max(0.5, min(20.0, float(merged.get("trailing_trigger_pct", config.AUTO_PAPER_TRAILING_TRIGGER_PCT)))),
        # Breakeven ratchet'i artık config.AUTO_PAPER_TRAILING_GAP_PCT'ten okunuyor,
        # dolayısıyla trailing gap'i ondan daha gevşek ayarlamak fiilen etki eder;
        # üst sınır 2026-09-27'de 0.6 → 2.0'ye çıkarıldı (Erkan kararı).
        "trailing_gap_pct": max(0.1, min(2.0, float(merged.get("trailing_gap_pct", config.AUTO_PAPER_TRAILING_GAP_PCT)))),
        "reopen_after_protect_close": bool(merged.get("reopen_after_protect_close", config.AUTO_PAPER_REOPEN_AFTER_PROTECT_CLOSE)),
        "tp_primary_exit_enabled": bool(merged.get("tp_primary_exit_enabled", getattr(config, "AUTO_PAPER_TP_PRIMARY_ENABLED", True))),
        "dynamic_breakeven_enabled": bool(merged.get("dynamic_breakeven_enabled", getattr(config, "AUTO_PAPER_DYNAMIC_BREAKEVEN_ENABLED", False))),
        "dynamic_trailing_enabled": bool(merged.get("dynamic_trailing_enabled", getattr(config, "AUTO_PAPER_DYNAMIC_TRAILING_ENABLED", False))),
        "breakeven_buffer_pct": max(0.01, min(0.5, float(merged.get("breakeven_buffer_pct", getattr(config, "AUTO_PAPER_BREAKEVEN_BUFFER_PCT", 0.02))))),
        # D-11/Erkan (2026-09-18): UI'dan değiştirilebilir global maksimum açık
        # pozisyon. 1..30 aralığı; 0'a izin verilmez (yanlışlıkla sınırsız
        # bırakma koruması — sınırsız gerekirse env ile verilir).
        "max_open_positions": max(1, min(30, int(merged.get("max_open_positions", config.AUTO_PAPER_MAX_OPEN_POSITIONS)))),
        "max_hold_minutes": max(5.0, min(1440.0, float(merged.get("max_hold_minutes", getattr(config, "AUTO_PAPER_MAX_HOLD_MINUTES", 60.0))))),
        "post_win_cooldown_minutes": max(0.0, min(120.0, float(merged.get("post_win_cooldown_minutes", getattr(config, "AUTO_PAPER_POST_WIN_COOLDOWN_MINUTES", 15.0))))),
        "llm_gate_enabled": bool(merged.get("llm_gate_enabled", True)),
        "llm_min_confidence": max(50.0, min(100.0, float(merged.get("llm_min_confidence", 60.0)))),
        "block_weak_mtf": bool(merged.get("block_weak_mtf", True)),
        "min_mtf_confluence": max(0.0, min(100.0, float(merged.get("min_mtf_confluence", 45.0)))),
        "sl_cooldown_minutes": max(0.0, min(120.0, float(merged.get("sl_cooldown_minutes", 5.0)))),
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
    trades = await database.list_auto_paper_trades(
        status=status or None, limit=limit, offset=offset, day=day, include_archived=include_archived
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
    return {
        "paper_only": True,
        "day": day or "today",
        "stats": stats,
        "reset_at": reset_at,
        "include_archived": include_archived,
        "state": dict(_AUTO_PAPER_STATE),
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
    """In-memory sayaçları sıfırla (admin reset sonrası restart beklemeden)."""
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


def start_auto_paper_loop() -> bool:
    """Arka plan döngüsünü bir kez başlat."""
    global _loop_task
    if _loop_task is not None and not _loop_task.done():
        return False
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
