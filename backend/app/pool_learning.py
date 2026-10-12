"""BİRLEŞİK HAVUZ — ADAPTİF EŞİK ÖĞRENMESİ (2026-10-13).

NE: Havuzun "gerçekten yükselen" kapısının iki eşiğini (composite_index ve
confluence_count) GERÇEKLEŞEN sonuca göre otomatik ayarlar — sabit kural değil,
kendini geliştiren tarama.

DESEN: `velocity.velocity_calibrate` ile AYNI mantık — gerçekleşen dokunuş/isabet
oranı hedef bandın altına düşerse eşik SIKILAŞIR (daha seçici), üstüne çıkarsa
GEVŞER (daha çok aday). Bant histerezisli; her adım ±step; min/max kelepçeli.
Eşikler `llm_settings`'e kalıcı yazılır (restart'ta geri yüklenir).

VERİ KAYNAĞI: Havuz bildirimlerinin MFE sonuçları (monitoring_notifications ile
aynı tablo; `pool_genuinely_rising` işaretli satırlar) + yeni defterin kapanan
işlemleri. Aşama B replay'inde eşik öğrenmesi walk-forward doğrulanır.

DÜRÜST SINIR: Bu eşik öğrenmesidir; EDGE YARATMAZ (8 tur ölçümü). Yalnızca seçimi
gerçekleşen başarıya hizalar. Aşama C'ye kadar canlı döngüye BAĞLANMAZ.
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger("scalper.pool_learning")

# Adaptif eşik bantları (histerezisli). Hit oranı bu bandın altında → sıkılaştır,
# üstünde → gevşet. min/max kelepçe ADAY SAYISINI korur (aşırı daralma/genişleme yok).
POOL_CALIB = {
    "composite": {"target_low": 0.20, "target_high": 0.45, "step": 2.0,
                  "min": 55.0, "max": 75.0, "min_samples": 30},
    "confluence": {"target_low": 0.20, "target_high": 0.45, "step": 1,
                   "min": 1, "max": 3, "min_samples": 30},
}

_state: dict = {"last_calibrated_at": None, "history": []}


def get_state() -> dict:
    return dict(_state)


async def pool_calibrate() -> tuple[bool, dict]:
    """Havuz eşiklerini gerçekleşen isabete göre ayarla.

    Döndürür: (değişti_mi, durum_sözlüğü). Eşikler `llm_settings`'e yazılır.
    """
    from app import database
    from app.config import config

    changed = False
    report: dict = {}
    try:
        stats = await _pool_hit_stats()
    except Exception as exc:
        logger.debug("havuz kalibrasyon istatistiği alınamadı: %s", exc)
        return False, {"error": str(exc)}

    passing = int(stats.get("passing") or 0)
    touched = int(stats.get("touched") or 0)
    hit = (touched / passing) if passing else None
    report["passing"] = passing
    report["touched"] = touched
    report["hit_pct"] = round(hit * 100, 1) if hit is not None else None

    # Composite eşiği
    cal = POOL_CALIB["composite"]
    cur_comp = float(getattr(config, "POOL_MIN_COMPOSITE", 60.0))
    saved_comp = await database.get_llm_setting("pool_min_composite", None)
    if saved_comp:
        cur_comp = round(float(saved_comp), 2)
    if passing >= cal["min_samples"] and hit is not None:
        if hit < cal["target_low"] and cur_comp < cal["max"]:
            cur_comp = round(min(cal["max"], cur_comp + cal["step"]), 2)
            await database.set_llm_setting("pool_min_composite", str(cur_comp))
            changed = True
            logger.info("havuz: isabet %.1f%% alt bant → composite %.1f",
                        hit * 100, cur_comp)
        elif hit > cal["target_high"] and cur_comp > cal["min"]:
            cur_comp = round(max(cal["min"], cur_comp - cal["step"]), 2)
            await database.set_llm_setting("pool_min_composite", str(cur_comp))
            changed = True
            logger.info("havuz: isabet %.1f%% üst bant → composite %.1f",
                        hit * 100, cur_comp)
    report["min_composite"] = cur_comp

    # Confluence eşiği (aynı mantık, tamsayı adım)
    cal = POOL_CALIB["confluence"]
    cur_conf = int(getattr(config, "POOL_MIN_CONFLUENCE", 2))
    saved_conf = await database.get_llm_setting("pool_min_confluence", None)
    if saved_conf:
        cur_conf = int(float(saved_conf))
    if passing >= cal["min_samples"] and hit is not None:
        if hit < cal["target_low"] and cur_conf < cal["max"]:
            cur_conf = min(cal["max"], cur_conf + cal["step"])
            await database.set_llm_setting("pool_min_confluence", str(cur_conf))
            changed = True
            logger.info("havuz: isabet %.1f%% alt bant → confluence %d",
                        hit * 100, cur_conf)
        elif hit > cal["target_high"] and cur_conf > cal["min"]:
            cur_conf = max(cal["min"], cur_conf - cal["step"])
            await database.set_llm_setting("pool_min_confluence", str(cur_conf))
            changed = True
            logger.info("havuz: isabet %.1f%% üst bant → confluence %d",
                        hit * 100, cur_conf)
    report["min_confluence"] = cur_conf

    if changed:
        _state["last_calibrated_at"] = time.time()
    _state["history"] = (_state["history"] + [report])[-20:]
    return changed, report


async def load_pool_thresholds() -> dict:
    """Startup'ta kalibre edilmiş havuz eşiklerini DB'den yükle (varsa)."""
    from app import database
    out = {}
    try:
        c = await database.get_llm_setting("pool_min_composite", None)
        if c:
            out["min_composite"] = round(float(c), 2)
        k = await database.get_llm_setting("pool_min_confluence", None)
        if k:
            out["min_confluence"] = int(float(k))
    except Exception as exc:
        logger.debug("havuz eşikleri yüklenemedi: %s", exc)
    return out


async def _pool_hit_stats() -> dict:
    """Havuz bildirimlerinin gerçekleşen dokunuş oranı.

    NOT: Aşama C'ye kadar havuz bildirimleri DB'de ayrı işaretlenmez (bu yol henüz
    canlıya bağlanmadı). Bu yüzden şimdilik NÖTR (0/0) döner — kalibrasyon
    `min_samples` eşiğini geçemez ve eşikler DEĞİŞMEZ (güvenli). Aşama C'de
    bildirimlere `pool:true` işareti eklendiğinde bu sorgu onu sayar. Aşama B
    replay'i eşik öğrenmesini ayrıca walk-forward doğrular.
    """
    from app import database
    marker = getattr(__import__("app.config", fromlist=["config"]).config,
                     "POOL_NOTIFY_MARKER", None)
    if not marker:
        return {"passing": 0, "touched": 0}

    def op(conn):
        try:
            rows = conn.execute(
                "SELECT COUNT(*) AS passing, "
                "SUM(CASE WHEN mfe_pct IS NOT NULL AND mfe_pct >= 1.2 THEN 1 ELSE 0 END) AS touched "
                "FROM monitoring_notifications WHERE message LIKE ?", (f"%{marker}%",)).fetchone()
            d = dict(rows) if rows else {}
            return {"passing": int(d.get("passing") or 0), "touched": int(d.get("touched") or 0)}
        except Exception:
            return {"passing": 0, "touched": 0}
    try:
        return await database._run_db(op)
    except Exception:
        return {"passing": 0, "touched": 0}
