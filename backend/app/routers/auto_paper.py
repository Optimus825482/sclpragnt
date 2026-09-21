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
from app.state import market, analyzer
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
    return block


async def _liquidity_cluster_gate(symbol: str, order_value: float, balance: float) -> dict | None:
    """R3-06 (P1): bildirim→auto_paper yolunda likidite + korelasyon küme kapısı.

    velocity-auto yolu (`analyzer.open_position`) bu kapıları zaten uygular;
    auto_paper kendi DB yolunu (`database.open_auto_paper_trade`) kullandığı
    için burada AYNI KAPI vurgulanır. Engelin NEDENİ dönüş durumunda
    taşınır (sessiz düşme yok). Hata durumunda açık/geçirgen olunur (paper-only).
    """
    if not analyzer:
        return None
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
            return None

        symbol = str(notification.get("symbol") or "").upper()
        if not symbol:
            return None

        score = float(notification.get("score") or 0)
        min_score = float(settings.get("min_score", config.AUTO_PAPER_MIN_SCORE_DEFAULT))
        if score < min_score:
            logger.info("auto_paper %s: skor %.1f < min_score %.1f — açılmadı",
                        symbol, score, min_score)
            return None

        # Sinyal teyit / gürültü filtresi (P1 - 2026-09-21 Erkan kararı):
        # Çoklu gösterge teyitlerinde 3'lü teyit ve altındaki sinyallere pozisyon AÇILMAZ.
        # Yalnızca 4 bağımsız algoritmanın (velocity + jump + early + rising)
        # tam mutabakat sağladığı 4'lü teyit sinyallerine otonom alım yapılır.
        sources = notification.get("sources")
        if sources is not None and isinstance(sources, list) and 1 < len(sources) < 4:
            logger.info("auto_paper %s: teyit sayısı %d < 4 — yalnızca 4'lü teyit işleme alınır, açılmadı",
                        symbol, len(sources))
            return _blocked(symbol, "low_confluence", sources_count=len(sources))

        # R3-08 (P1): aday PANEL EŞİĞİNİ geçmiş olmalı (passing-only). Monitoring
        # yalnızca passing adayları bildirir; burada `passes` bayrağı açıkça False
        # erse giriş engellenir. Guard (koruma) metriği kanıtlarsa engellenmez;
        # anahtar yoksa da geçirgen kalınır (geriye dönük uyum).
        passes = notification.get("passes")
        if passes is not None and not bool(passes):
            logger.warning("auto_paper %s: aday panel şartını geçmedi (passes=False) — "
                           "açılmadı (R3-08)", symbol)
            return _blocked(symbol, "not_passing")

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
        # NOT: `timestamp` ms cinsindendir — `ticker_freshness` dönüşümü ve
        # `MAX_TICKER_AGE_SEC` toleransını zaten uygular; elle ms/s karışımı
        # hesaplamak yerine hazır yardımcı kullanılır.
        try:
            # Otonom akış için 60 sn: global 15 sn toleransı (MAX_TICKER_AGE_SEC)
            # tarama kadansı + REST tazeleme aralığı içinde sık engel üretirdi;
            # 60 sn bayat-çapa riskini kabul edilebilir düzeyde tutar.
            freshness = market.ticker_freshness(symbol, max_age_sec=60)
        except Exception:
            freshness = {"fresh": False, "age_sec": None}
        if not bool(freshness.get("fresh")):
            logger.warning("auto_paper %s: taze ticker yok (age=%ss) — bayat fiyata "
                        "açılış engellendi", symbol, freshness.get("age_sec"))
            return _blocked(symbol, "stale_ticker")

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
                return _blocked(symbol, "max_open", open_count=open_count, max_open=max_open)

        # R3-06 (a/b): girişten önce LİKİDİTE + KORELASYON KÜME kapısı. order_value
        # burada hesaplanıp `_open_new_trade`'e iletilir (tek wallet okuması).
        balance = await database.get_wallet_balance("TRY")
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
            balance = await database.get_wallet_balance("TRY")
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
            logger.warning(
                "auto_paper %s: risk bütçesi yetersiz (bakiye %.2f TRY × %%%.1f = %.2f TRY "
                "< min emir %.2f TRY) — açılmadı; balance_pct/min_order_try ayarlayın",
                symbol, balance, balance_pct * 100, order_value, min_order)
            return _blocked(symbol, "order_below_min",
                            order_value=round(order_value, 2),
                            min_order=min_order,
                            balance=round(balance, 2),
                            balance_pct=round(balance_pct * 100, 2))

        sl_pct = float(settings.get("stop_loss_pct", config.AUTO_PAPER_SL_PCT_DEFAULT)) / 100.0
        target_pct = _effective_target_pct(notification)
        if target_pct <= 0:
            target_pct = float(settings.get("default_target_pct", config.AUTO_PAPER_DEFAULT_TARGET_PCT))

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
        stop_loss_price = fill_entry * (1 - sl_pct)
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
            logger.info("auto_paper %s: bildirim %s zaten işlendi — açılmadı", symbol, notification_id)
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

        await _broadcast_trade({
            "action": "OPENED", "symbol": symbol,
            "entry": fill_entry, "take_profit": take_profit_price,
            "stop_loss": stop_loss_price, "quantity": quantity,
            "order_value": net_order_value, "score": notification.get("score"),
            "target_pct": target_pct, "trade_id": trade_id,
        })

        logger.info("auto_paper %s: AÇILDI miktar=%.4f giriş=%.6f TP=%.6f SL=%.6f değer=%.2fTRY skor=%.1f",
                    symbol, quantity, fill_entry, take_profit_price, stop_loss_price,
                    net_order_value, notification.get("score"))

        return {"status": "opened", "trade_id": trade_id, "symbol": symbol}

    except Exception as exc:
        logger.exception("auto_paper %s açılış hatası: %s", symbol, exc)
        return None


async def _update_existing_trade(open_trade: dict, notification: dict, current_price: float) -> dict | None:
    """Açık pozisyon için TP'yi bildirimdeki yeni hedefle güncelle."""
    # ERKAN İSTEĞİ (2026-09-18): trailing devreye girdiği pozisyonda TP kaldırılır;
    # yeni bildirim TP'yi geri YAZMAZ — geri yazmak kaldırma kararını bozar ve
    # fiyat tahmin edilen artışın üzerinde yükselirken çıkışı keser. Pozisyonun
    # çıkışı artık tamamen trailing stop'a aittir.
    if open_trade.get("trailing_activated"):
        return {"status": "no_change", "trade_id": open_trade["id"],
                "symbol": open_trade["symbol"], "reason": "trailing_active"}
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

    # Güncel fiyat
    ticker = market.get_ticker(symbol)
    current_price = float(ticker.get("last_price") or 0) if ticker else 0
    if current_price <= 0:
        return
    # Bayat fiyatla TP/SL değerlendirmesi yanlış fill fiyatı üretir; analyzer
    # yolundaki MAX_TICKER_AGE_SEC tazelik kapısı burada da uygulanır.
    ticker_ts = float((ticker or {}).get("timestamp") or 0)
    if not ticker_ts or now * 1000 - ticker_ts > config.MAX_TICKER_AGE_SEC * 1000:
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
    if stop_loss is not None and current_price <= stop_loss:
        await _close_trade(trade_id, symbol, max(current_price, stop_loss), now, "stop_loss")
        return

    # Breakeven kontrolü (trailing + dinamik komisyon + buffer).
    # Kullanıcı isteği: "breakeven stop'a dinamik komisyon ekle + fiyat yükseldikten
    # sonra devreye gir". Tasarım:
    #   - Net taban (floor): entry*(1 + 2*komisyon + buffer) → bu fiyattan satış,
    #     komisyonlar sonrası daima POZİTİF net verir (sıfırda değil).
    #   - Trailing: fiyat yükselirken stop, zirvenin BREAKEVEN_TRAIL_GAP_PCT
    #     gerisinden takip eder; zirveden sonra düşüşte kâr kilitlenir.
    #   - Stop, güncel fiyatın üstüne çıkarsa (trigger komisyondan küçükse)
    #     hemen kapanmasın: aktivasyon ertelenir, fiyat biraz daha yükselir.
    breakeven_activated = bool(trade.get("breakeven_activated", False))
    gross_pnl_pct = ((current_price - entry_price) / entry_price * 100) if entry_price else 0

    # B2: Dynamic profit-lock triggers tied to TP target (Tavan korumalı)
    dynamic_breakeven_enabled = bool((settings or {}).get("dynamic_breakeven_enabled", getattr(config, "AUTO_PAPER_DYNAMIC_BREAKEVEN_ENABLED", False)))
    dynamic_trailing_enabled = bool((settings or {}).get("dynamic_trailing_enabled", getattr(config, "AUTO_PAPER_DYNAMIC_TRAILING_ENABLED", False)))
    tp_gain_pct = None
    if take_profit is not None and entry_price > 0 and take_profit > entry_price:
        tp_gain_pct = (take_profit - entry_price) / entry_price * 100
    if tp_gain_pct is not None and dynamic_breakeven_enabled:
        # Dinamik breakeven TP'ye göre erken tetiklenebilir ancak kâr koruma eşiği
        # ASLA baz breakeven_trigger_pct'nin üstüne çıkarılamaz (kârın geri verilmesini engeller).
        breakeven_trigger_pct = min(breakeven_trigger_pct, max(0.8, tp_gain_pct * 0.5))

    # B4: Narrow breakeven buffer (admin-editable, default 0.02)
    breakeven_buffer_pct = float((settings or {}).get("breakeven_buffer_pct", getattr(config, "AUTO_PAPER_BREAKEVEN_BUFFER_PCT", 0.02)))
    BREAKEVEN_TRAIL_GAP_PCT = 0.60
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
                # D-14 (2026-09-12): bayrak YALNIZCA DB yazımı gerçekleştiğinde
                # set edilir. Eskiden koşulsuz atanıyordu (blok DIŞINDA), DB'de
                # breakeven_stop 0 kalırken bellek True oluyordu → bellek↔DB
                # tutarsızlığı ve yanıltıcı log. Artık ikisi aynı anda yazılır.
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
        if tp_gain_pct is not None and dynamic_trailing_enabled:
            trailing_trigger_pct = min(trailing_trigger_pct, max(1.2, tp_gain_pct * 0.6))

        # B3: Dynamic trailing gap compatible with TP
        if tp_gain_pct is not None and gross_pnl_pct >= tp_gain_pct * 0.9:
            trailing_gap_pct = max(0.2, trailing_gap_pct * 0.5)

        # SHADOW KİLİDİ (2026-09-16): breakeven ratchet açıklığı
        # (BREAKEVEN_TRAIL_GAP_PCT = %0.60) hem trailing'den (%0.80) DAHA SIKI hem
        # bu bloktan ÖNCE değerlendiriliyor. Sonuç: trailing'in ayarlanan açıklığı
        # pratikte hiç uygulanmıyordu — kullanıcının 471 işlemlik gerçek replay
        # CSV'sinde `trailing_stop` 0 kez tetiklendi (yalnız ~%0.2'lik bir bantta
        # erişilebilirdi). KURAL: sıkı olan taraf kazanır. Trailing, breakeven'den
        # daha GEVŞEK olamaz (gevşetmek net-zemin kilidini delip MFE'yi geri verir);
        # daha SIKI olabilir (ör. 0.3) ve artık gerçekten etki eder. Ayar böylece
        # sessizce yok sayılmak yerine dürüstçe kırpılır.
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

            # ERKAN İSTEĞİ (2026-09-18): trailing devreye girdiği AN TP kaldırılır —
            # çıkış tamamen trailing stop'a devredilir. Böylece fiyat tahmin edilen
            # artışın üzerinde yükselirse pozisyon taşınmaya devam eder (maksimum
            # kar); küçük geri çekilmelerde zirvenin %gap gerisindeki stop kilitler.
            # Kapanıştan EN ÜSTTEKI TP-birincil çıkışı (TP-primary) aktivasyon
            # turundan İTİBAREN devre dışı kalır (DB'de take_profit=NULL).
            if take_profit is not None:
                try:
                    await database.update_auto_paper_trade_tp(trade_id, None)
                    take_profit = None
                    logger.info("auto_paper %s: trailing aktivasyonu — TP kaldırıldı, çıkış trailing stop'a devredildi", symbol)
                except Exception as tp_exc:
                    logger.warning("auto_paper %s: TP kaldırılamadı (trailing yine de aktif): %s", symbol, tp_exc)

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

        logger.info("auto_paper %s: KAPANDI (%s) çıkış=%.6f PnL=%.2fTRY (%+.2f%%) süre=%.0fs",
                    symbol, reason, fill_price, pnl, pnl_pct, hold_seconds)

        # Kâr koruma (trailing/breakeven) kapanışı: sembol monitoring sayfasının
        # "uygun adaylar" listesinde kaldığı sürece aynı sembole yeniden aç.
        # D-15 (2026-09-12): yeniden açma artık bu zincirin DIŞINDA, tek
        # seferlik arka plan görevi olarak çalışır. Eskiden `await
        # _maybe_reopen_after_protect_close(...)` kapanışın içinde senkron
        # çağrılıyordu (REST + DB transaction); döngü tek task olduğundan bu
        # süre boyunca DİĞER sembollerin TP/SL yönetimi bekliyordu.
        if reason in ("trailing_stop", "breakeven_stop"):
            orig_notification_id = trade.get("notification_id")
            _start_background(
                lambda: _maybe_reopen_after_protect_close(symbol, orig_notification_id),
                f"auto-paper-reopen-{symbol}", single_pass=True)

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
        "min_order_try": config.AUTO_PAPER_MIN_ORDER_TRY,
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
                "default_target_pct", "min_order_try", "breakeven_trigger_pct",
                "trailing_enabled", "trailing_trigger_pct", "trailing_gap_pct",
                "reopen_after_protect_close",
                "tp_primary_exit_enabled", "dynamic_breakeven_enabled",
                "dynamic_trailing_enabled", "breakeven_buffer_pct",
                "max_open_positions")
    existing = await get_auto_paper_settings()
    merged = {**existing, **{k: payload[k] for k in editable if k in payload}}

    settings = {
        "enabled": bool(merged.get("enabled", True)),
        "min_score": max(0.0, min(100.0, float(merged.get("min_score", config.AUTO_PAPER_MIN_SCORE_DEFAULT)))),
        "balance_pct": max(1.0, min(100.0, float(merged.get("balance_pct", config.AUTO_PAPER_BALANCE_PCT_DEFAULT)))),
        "stop_loss_pct": max(0.1, min(20.0, float(merged.get("stop_loss_pct", config.AUTO_PAPER_SL_PCT_DEFAULT)))),
        "default_target_pct": max(0.5, min(20.0, float(merged.get("default_target_pct", config.AUTO_PAPER_DEFAULT_TARGET_PCT)))),
        "min_order_try": max(10.0, float(merged.get("min_order_try", config.AUTO_PAPER_MIN_ORDER_TRY))),
        "breakeven_trigger_pct": max(0.5, min(10.0, float(merged.get("breakeven_trigger_pct", config.AUTO_PAPER_BREAKEVEN_TRIGGER_PCT)))),
        "trailing_enabled": bool(merged.get("trailing_enabled", config.AUTO_PAPER_TRAILING_ENABLED)),
        "trailing_trigger_pct": max(0.5, min(20.0, float(merged.get("trailing_trigger_pct", config.AUTO_PAPER_TRAILING_TRIGGER_PCT)))),
        # Üst sınır 0.60: breakeven ratchet'i (BREAKEVEN_TRAIL_GAP_PCT) daha sıkı ve
        # önce değerlendiriliyor, dolayısıyla daha gevşek bir trailing fiilen etkisiz
        # olurdu. Ayarı kırpıyoruz ki ekrandaki değer gerçekten uygulanan değer olsun.
        "trailing_gap_pct": max(0.1, min(0.6, float(merged.get("trailing_gap_pct", config.AUTO_PAPER_TRAILING_GAP_PCT)))),
        "reopen_after_protect_close": bool(merged.get("reopen_after_protect_close", config.AUTO_PAPER_REOPEN_AFTER_PROTECT_CLOSE)),
        "tp_primary_exit_enabled": bool(merged.get("tp_primary_exit_enabled", getattr(config, "AUTO_PAPER_TP_PRIMARY_ENABLED", True))),
        "dynamic_breakeven_enabled": bool(merged.get("dynamic_breakeven_enabled", getattr(config, "AUTO_PAPER_DYNAMIC_BREAKEVEN_ENABLED", False))),
        "dynamic_trailing_enabled": bool(merged.get("dynamic_trailing_enabled", getattr(config, "AUTO_PAPER_DYNAMIC_TRAILING_ENABLED", False))),
        "breakeven_buffer_pct": max(0.01, min(0.5, float(merged.get("breakeven_buffer_pct", getattr(config, "AUTO_PAPER_BREAKEVEN_BUFFER_PCT", 0.02))))),
        # D-11/Erkan (2026-09-18): UI'dan değiştirilebilir global maksimum açık
        # pozisyon. 1..30 aralığı; 0'a izin verilmez (yanlışlıkla sınırsız
        # bırakma koruması — sınırsız gerekirse env ile verilir).
        "max_open_positions": max(1, min(30, int(merged.get("max_open_positions", config.AUTO_PAPER_MAX_OPEN_POSITIONS)))),
    }

    await database.set_llm_setting("auto_paper_settings", json.dumps(settings))
    await log_user_action(None, None, "auto_paper", "AUTO_PAPER_SETTINGS_UPDATE",
                          details={"settings": settings}, request=request)
    return {"paper_only": True, "ok": True, "settings": settings}


# ---------------------------------------------------------------------------
# Trades API
# ---------------------------------------------------------------------------
@router.get("/api/auto-paper/trades")
async def list_trades_endpoint(status: str | None = None, limit: int = 100, offset: int = 0):
    """Otonom paper trade kayıtlarını listele. Açık pozisyonlara güncel fiyat eklenir."""
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))
    trades = await database.list_auto_paper_trades(status=status or None, limit=limit, offset=offset)
    # Açık pozisyonlar için güncel ticker fiyatını ekle (frontend PnL hesabı için)
    for t in trades:
        if t.get("status") == "open":
            ticker = market.get_ticker(str(t.get("symbol") or "").upper())
            t["current_price"] = float(ticker.get("last_price") or 0) if ticker else None
    return {"paper_only": True, "trades": trades, "total": len(trades)}


@router.get("/api/auto-paper/stats")
async def get_stats_endpoint():
    """Otonom paper trade istatistikleri (reset_at sonrasi; reset kapanışları hariç)."""
    stats = await database.get_auto_paper_stats()
    return {
        "paper_only": True,
        "stats": stats,
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
