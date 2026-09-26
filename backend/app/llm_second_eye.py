"""LLM İKİNCİ GÖZ (2026-09-26): warm/master-surge ateşlendiğinde şemalı onay katmanı.

Tasarım ilkesi (kullanıcı kararı, 2026-09-26): LLM TARAMA motoru DEĞİLDİR.
Akış tabanlı ucuz dedektörler (pulse → warm → teyit) zaten saniyeler içinde
adayı bulur; bu modül yalnızca ATEŞLENMİŞ bildirim zarfını alıp hazır kanıt
paketini (master_surge katmanları + türev verisi + mikro-yapı) LLM'e verir ve
"devam mı, tuzak mu" kararını şemalı JSON olarak geri getirir. Sonuç ayrı bir
bildirim zarfı olarak ekrana/panele/push'a yansır.

Sınırlar:
- Ham mum verisi GÖNDERİLMEZ — LLM aritmetikte kötü, kanıt tartmada iyidir.
- Zaman bütçesi: tek çağrı TIMEOUT_SEC ile sınırlıdır; aşılırsa karar YOK
  (kural motorunun kararı geçerli kalır) — asla bildirim akışını bloklamaz.
- Sağlayıcı yapılandırılmamışsa (`enabled: False`) 10 dk boyunca sessizdir
  (tekrarlanan başarısız çağrı maliyeti/kirliliği yok).
"""
import asyncio
import logging
import os
import time
from collections import deque

from app import database
from app.llm_analysis import _json_load_lenient

logger = logging.getLogger("scalper.llm_second_eye")

# --- Ayarlar (env ile aynen; testler modül niteliğini değiştirerek kelepçeler) ---
COOLDOWN_SEC = float(os.getenv("LLM_SECOND_EYE_COOLDOWN_SEC", "1800") or 1800)
MIN_INTERVAL_SEC = float(os.getenv("LLM_SECOND_EYE_MIN_INTERVAL_SEC", "45") or 45)
TIMEOUT_SEC = float(os.getenv("LLM_SECOND_EYE_TIMEOUT_SEC", "75") or 75)
MIN_SCORE = float(os.getenv("LLM_SECOND_EYE_MIN_SCORE", "0") or 0)
MAX_PER_HOUR = int(os.getenv("LLM_SECOND_EYE_MAX_PER_HOUR", "15") or 15)
PROVIDER_MISSING_BACKOFF_SEC = float(os.getenv("LLM_SECOND_EYE_PROVIDER_BACKOFF_SEC", "600") or 600)

VERDICT_SCHEMA_HINT = (
    '{"verdict":"DEVAM|FAKE|BELIRSIZ","confidence":<0-100 tam sayı>,'
    '"reasons":["kısa kanıt etiketi",...],"trap_evidence":["varsa fake kanıtları",...],'
    '"summary":"tek cümle Türkçe özet"}'
)

SECOND_EYE_PROMPT = (
    "Sen kripto skolp sisteminde İKİNCİ GÖZ onay katmanısın. Kural motoru bir yükseliş/kırılım "
    "sinyali ateşledi; sen bu kırılımın GERÇEK mi FAKE mi olduğunu ve yükselişin DEVAM edip "
    "etmeyeceğini verilen kanıt paketiyle değerlendir. Yalnızca verilen kanıtları kullan; yeni "
    "veri uydurma; kendi aritmetiğinle skor hesaplama. Kanıtlar ÇELİŞİYORSA (fiyat yükseliyor "
    "ama CVD/trade_imbalance negatif, whale satıyor, ladder_asymmetry negatif, funding "
    "EXTREME_LONG, BTC panik) FAKE ihtimali GÜÇLENİR. Kanıtlar hemfikirse DEVAM'a eğil; "
    "yeterli kanıt yoksa BELIRSIZ ver. JSON dışında hiçbir şey yazma. Şema TAM OLARAK: "
    + VERDICT_SCHEMA_HINT
)


# --- Çalışma zamanı durumu (tek event loop; korumalı bölüm asyncio.Lock ile) ---
_state = {
    "last_eval_at": 0.0,
    "hour_marks": deque(),
    "provider_missing_until": 0.0,
    "last_error": None,
    "evaluated": 0,
    "skipped": 0,
}
_last_eval_per_symbol: dict[str, float] = {}
_guard_lock = asyncio.Lock()


def stats() -> dict:
    """Gözlem sayaçları — /health veya ayar sayfası kartı için."""
    return {
        "evaluated": _state["evaluated"],
        "skipped": _state["skipped"],
        "last_error": _state["last_error"],
        "cooldown_sec": COOLDOWN_SEC,
        "min_score": MIN_SCORE,
    }


def enabled_by_env() -> bool:
    return os.getenv("LLM_SECOND_EYE_ENABLED", "1").strip().lower() not in ("0", "false", "off")


def eligible(notif: dict | None) -> bool:
    """Bildirim zarfı LLM değerlendirmesine uygun mu? (ucuz, senkron filtre)

    Varsayılan: uygulamadan giden HER push değerlendirilir (MIN_SCORE=0);
    maliyeti saatlik çağrı kotası + aralık kapısı sınırlar. Skor kapısı
    istenirse `LLM_SECOND_EYE_MIN_SCORE` ile yeniden sıkılaştırılır.
    """
    if not enabled_by_env():
        return False
    if not isinstance(notif, dict):
        return False
    if notif.get("updated"):
        return False
    if notif.get("suppressed_by_unified"):
        return False
    if str(notif.get("source") or "") == "llm_second_eye":
        return False  # kendi çıktımızı tekrar değerlendirme (sonsuz döngü koruması)
    sym = str(notif.get("symbol") or "").strip().upper()
    if not sym:
        return False
    try:
        if float(notif.get("score") or 0) < MIN_SCORE:
            return False
    except (TypeError, ValueError):
        return False
    return True


def _compact_layer(layer: dict) -> dict:
    keys = ("passed", "score", "reason", "direction", "state", "verdict")
    return {k: layer.get(k) for k in keys if layer.get(k) is not None}


def compact_master_surge(surge: dict | None) -> dict | None:
    """master_surge sonucunu LLM'e giden kompakt kanıta indirger."""
    if not isinstance(surge, dict):
        return None
    out: dict = {
        "passed": surge.get("passed"),
        "composite_index": surge.get("composite_index"),
        "confluence_4way": surge.get("confluence_4way"),
        "confluence_count": surge.get("confluence_count"),
        "block_reason": surge.get("block_reason"),
    }
    layers = surge.get("layers")
    if isinstance(layers, dict) and layers:
        out["layers"] = {name: _compact_layer(layer) for name, layer in layers.items() if isinstance(layer, dict)}
    deriv = surge.get("derivatives")
    if isinstance(deriv, dict) and deriv:
        out["derivatives"] = {
            k: deriv.get(k) for k in (
                "funding_rate_pct", "funding_state", "open_interest_usd",
                "crowded_long_danger", "short_squeeze_potential", "derivatives_bias",
            ) if deriv.get(k) is not None
        }
    if isinstance(surge.get("macro_sentiment"), dict):
        out["macro_sentiment"] = surge["macro_sentiment"]
    if surge.get("learning_bias"):
        out["learning_bias"] = surge.get("learning_bias")
    at = surge.get("adaptive_targets")
    if isinstance(at, dict) and at:
        out["adaptive_targets"] = {k: at[k] for k in list(at)[:6]}
    return out if len(out) > 1 else None


def microstructure_evidence(symbol: str) -> dict | None:
    """Mikro-yapı kanıtı — yalnızca aday, aktif microflow sembolüyse (tek sembol akışı)."""
    try:
        from app.microflow import microflow
        snap = microflow.get_snapshot()
    except Exception:
        return None
    if not isinstance(snap, dict) or not snap.get("data_ready"):
        return None
    if str(snap.get("symbol") or "").upper() != str(symbol or "").upper():
        return None
    return {
        "bars": snap.get("bars"),
        "trade_flow": snap.get("trade_flow"),
        "depth": snap.get("depth"),
        "slippage": snap.get("slippage"),
    }


async def derivatives_evidence(symbol: str) -> dict | None:
    """Türev kanıtı (funding/OI) — master_surge içinde yoksa cache-first çeker."""
    try:
        from app.derivatives_service import get_cached_derivatives_intel, get_derivatives_intel
        intel = get_cached_derivatives_intel(symbol)
        if not isinstance(intel, dict) or not intel:
            intel = await get_derivatives_intel(symbol)
    except Exception:
        return None
    if not isinstance(intel, dict) or not intel:
        return None
    compact = {
        k: intel.get(k) for k in (
            "funding_rate_pct", "funding_state", "open_interest_usd",
            "crowded_long_danger", "short_squeeze_potential", "derivatives_bias",
        ) if intel.get(k) is not None
    }
    return compact or None


async def build_evidence(notif: dict) -> dict:
    """Bildirim zarfından LLM kanıt paketi kurar (küçük JSON — ~1-2 KB)."""
    sym = str(notif.get("symbol") or "").upper()
    surge = compact_master_surge(notif.get("master_surge"))
    evidence: dict = {
        "symbol": sym,
        "signal": {
            "score": notif.get("score"),
            "target_pct": notif.get("target_pct"),
            "price": notif.get("price"),
            "horizon_minutes": notif.get("horizon_minutes"),
            "sources": notif.get("sources"),
            "mode": notif.get("mode"),
        },
    }
    if surge:
        evidence["master_surge"] = surge
        # master_surge içindeki türev verisi kanıt olarak yeterli; ayrı çekmeye gerek yok.
        if not surge.get("derivatives"):
            deriv = await derivatives_evidence(sym)
            if deriv:
                evidence["derivatives"] = deriv
    else:
        deriv = await derivatives_evidence(sym)
        if deriv:
            evidence["derivatives"] = deriv
    micro = microstructure_evidence(sym)
    if micro:
        evidence["microstructure"] = micro
    signals = notif.get("signals")
    if isinstance(signals, dict) and signals:
        evidence["rising_signals"] = {
            k: signals.get(k) for k in list(signals)[:12] if signals.get(k) is not None
        }
    return evidence


def parse_verdict(text) -> dict | None:
    """LLM yanıtından şemalı kararı çıkarır; toleranslı ayrıştırma, şema dışına izin yok."""
    if not text:
        return None
    raw = str(text).strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    decoded = _json_load_lenient(raw)
    if not isinstance(decoded, dict):
        return None
    verdict_raw = str(decoded.get("verdict") or "").strip().upper()
    aliases = {"DEVAM": "DEVAM", "CONTINUE": "DEVAM", "ONAY": "DEVAM",
               "FAKE": "FAKE", "TUZAK": "FAKE", "TRAP": "FAKE", "SAHTE": "FAKE",
               "BELIRSIZ": "BELIRSIZ", "UNCERTAIN": "BELIRSIZ", "NEUTRAL": "BELIRSIZ"}
    verdict = aliases.get(verdict_raw)
    if not verdict:
        return None
    try:
        confidence = max(0.0, min(100.0, float(decoded.get("confidence") or 0)))
    except (TypeError, ValueError):
        confidence = 0.0

    def _str_list(value) -> list[str]:
        if not isinstance(value, list):
            return []
        out = []
        for item in value[:5]:
            if isinstance(item, (int, float)):
                item = str(item)
            if isinstance(item, str) and item.strip():
                out.append(item.strip()[:120])
        return out

    return {
        "verdict": verdict,
        "confidence": round(confidence),
        "reasons": _str_list(decoded.get("reasons")),
        "trap_evidence": _str_list(decoded.get("trap_evidence")),
        "summary": str(decoded.get("summary") or "").strip()[:300] or None,
    }


def build_verdict_notification(notif: dict, verdict: dict) -> dict:
    """Kararı ekrana/push'a gidecek KISA VE NET bildirim zarfına çevirir.

    Başlık = karar + güven; mesaj = tek satır (yönlendirme + en güçlü tek kanıt).
    """
    import json as _json

    sym = str(notif.get("symbol") or "").upper()
    v = verdict["verdict"]
    conf = verdict["confidence"]
    if v == "DEVAM":
        title = f"🧠 {sym}: DEVAM ✓ %{conf}"
        lead = "Kırılım gerçek görünüyor"
        reasons = verdict.get("reasons") or []
    elif v == "FAKE":
        title = f"🧠 {sym}: FAKE ⚠ %{conf}"
        lead = "Fake kırılım riski"
        reasons = verdict.get("trap_evidence") or verdict.get("reasons") or []
    else:
        title = f"🧠 {sym}: BELİRSİZ %{conf}"
        lead = "Yeterli kanıt yok"
        reasons = []
    reason_txt = reasons[0].strip() if reasons and isinstance(reasons[0], str) else ""
    if not reason_txt and verdict.get("summary"):
        reason_txt = str(verdict["summary"]).strip()[:80]
    message = f"🧠 {sym} | {lead}"
    if reason_txt:
        message += f" · {reason_txt}"
    message += f" | Güven %{conf}"
    now = time.time()
    return {
        "symbol": sym,
        "message": message,
        "title": title,
        "url": f"/charts?symbol={sym}",
        "tag": f"llm2eye-{sym}",
        "detected_at": now,
        "score": conf,                       # bu satırda skor = LLM güveni
        "target_pct": notif.get("target_pct"),
        "price": notif.get("price"),
        "horizon_minutes": notif.get("horizon_minutes"),
        "mode": "llm_ikinci_goz",
        "source": "llm_second_eye",
        "sent_via_push": False,
        "llm_verdict": v,
        "llm_confidence": conf,
        "llm_reasons": _json.dumps(
            {"reasons": verdict.get("reasons") or [],
             "trap_evidence": verdict.get("trap_evidence") or [],
             "summary": verdict.get("summary")}, ensure_ascii=False),
    }


async def evaluate(notif: dict) -> dict | None:
    """Uygun bildirim için LLM kararını alıp bildirim zarfı döndürür; atlanırsa None."""
    from app import llm_analysis

    if not eligible(notif):
        return None
    sym = str(notif.get("symbol") or "").upper()
    now = time.time()
    if now < _state["provider_missing_until"]:
        return None
    async with _guard_lock:
        try:
            setting = await database.get_llm_setting("llm_second_eye_enabled", "1")
        except Exception:
            setting = "1"
        if str(setting) != "1":
            return None
        if now - _last_eval_per_symbol.get(sym, 0.0) < COOLDOWN_SEC:
            _state["skipped"] += 1
            return None
        if now - _state["last_eval_at"] < MIN_INTERVAL_SEC:
            _state["skipped"] += 1
            return None
        marks = _state["hour_marks"]
        while marks and now - marks[0] > 3600:
            marks.popleft()
        if len(marks) >= MAX_PER_HOUR:
            _state["skipped"] += 1
            return None
        # Kapılar geçildi: kota/kapanı çağrıdan ÖNCE işaretle (burst koruması).
        _last_eval_per_symbol[sym] = now
        _state["last_eval_at"] = now
        marks.append(now)

    evidence = await build_evidence(notif)
    snapshot = {"type": "llm_second_eye", "paper_only": True, "evidence": evidence}
    try:
        result = await asyncio.wait_for(
            llm_analysis.chat(
                snapshot,
                [{"role": "user", "content": SECOND_EYE_PROMPT}],
                json_mode=True,
                max_tokens=600,
            ),
            timeout=TIMEOUT_SEC,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        _state["last_error"] = f"{sym}: {exc}"
        logger.info("LLM ikinci göz çağrısı başarısız %s: %s", sym, exc)
        return None
    if not isinstance(result, dict):
        _state["last_error"] = f"{sym}: beklenmeyen yanıt"
        return None
    if result.get("enabled") is False:
        # Sağlayıcı yapılandırılmamış: tekrar denemek maliyetsiz ama gereksiz.
        _state["provider_missing_until"] = time.time() + PROVIDER_MISSING_BACKOFF_SEC
        logger.info("LLM ikinci göz: sağlayıcı yapılandırılmamış — %s sn sessiz",
                    PROVIDER_MISSING_BACKOFF_SEC)
        return None
    text = result.get("text") or result.get("content")
    verdict = parse_verdict(text)
    if not verdict:
        _state["last_error"] = f"{sym}: karar şemasına uymadı"
        logger.info("LLM ikinci göz: yanıt şemaya uymadı (%s)", sym)
        return None
    _state["last_error"] = None
    _state["evaluated"] += 1
    return build_verdict_notification(notif, verdict)


def reset_state_for_tests() -> None:
    _state.update({"last_eval_at": 0.0, "provider_missing_until": 0.0,
                   "last_error": None, "evaluated": 0, "skipped": 0})
    _state["hour_marks"].clear()
    _last_eval_per_symbol.clear()
