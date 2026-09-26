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
import json
import logging
import os
import time
from collections import deque

from app import database
from app.llm_analysis import _json_load_lenient

logger = logging.getLogger("scalper.llm_second_eye")

# --- Ayarlar (env ile aynen; testler modül niteliğini değiştirerek kelepçeler) ---
# HIZ İLKESİ + GERÇEKLİK (2026-09-26 revizyonu): lean prompt hızı sağlar; tavan
# yalnızca üst sınırdır. 20 sn tavan yavaş sağlayıcılarda HER kararı siliyordu
# (kullanıcı hiç bildirim görmüyordu) → dış bütçe 45 sn'e çekildi; aşılırsa
# karar YOK, kural kararı geçerli.
COOLDOWN_SEC = float(os.getenv("LLM_SECOND_EYE_COOLDOWN_SEC", "1800") or 1800)
MIN_INTERVAL_SEC = float(os.getenv("LLM_SECOND_EYE_MIN_INTERVAL_SEC", "15") or 15)
TIMEOUT_SEC = float(os.getenv("LLM_SECOND_EYE_TIMEOUT_SEC", "45") or 45)
MIN_SCORE = float(os.getenv("LLM_SECOND_EYE_MIN_SCORE", "0") or 0)
MAX_PER_HOUR = int(os.getenv("LLM_SECOND_EYE_MAX_PER_HOUR", "15") or 15)
PROVIDER_MISSING_BACKOFF_SEC = float(os.getenv("LLM_SECOND_EYE_PROVIDER_BACKOFF_SEC", "600") or 600)
# Hızlı yol: 2 mesaj + tavan 250 token — kısa JSON cevabı saniyeler içinde döner.
# NOT (2026-09-26): HTTP tavanı başta 15 sn idi; yavaş sağlayıcılarda HER çağrı
# sessizce düşüyor ve kullanıcı hiç karar görmüyordu. Lean prompt hızı zaten
# sağlar; tavan yalnızca üst sınırdır → 40 sn / dış bütçe 45 sn.
FAST_MAX_TOKENS = int(os.getenv("LLM_SECOND_EYE_MAX_TOKENS", "250") or 250)
HTTP_TIMEOUT_SEC = float(os.getenv("LLM_SECOND_EYE_HTTP_TIMEOUT", "40") or 40)

VERDICT_SCHEMA_HINT = (
    '{"verdict":"DEVAM|FAKE|BELIRSIZ","confidence":<0-100 tam sayı>,'
    '"reasons":["kısa kanıt etiketi",...],"trap_evidence":["varsa fake kanıtları",...],'
    '"summary":"tek cümle Türkçe özet"}'
)

SECOND_EYE_PROMPT = FAST_SYSTEM_PROMPT = (
    "TEK GÖREVİN: aşağıdaki şemada JSON döndürmek. Düşünme sürecini, ara cümleleri, "
    "İngilizce yorumları YAZMA — 'We need to evaluate...' gibi analiz cümleleri yasak. "
    "İlk karakterin '{' son karakterin '}' olsun. Örnek biçim: "
    '{"verdict":"DEVAM","confidence":78,"reasons":["cvd_pozitif","derinlik_guclu"],'
    '"trap_evidence":[],"summary":"Akis teyitli"}\n'
    "Görev: kural motoru bir yükseliş/kırılım sinyali ateşledi; bu kırılımın GERÇEK mi "
    "FAKE mi olduğunu ve yükselişin DEVAM edip etmeyeceğini yalnızca verilen kanıt "
    "paketiyle değerlendir. Yeni veri uydurma, aritmetik yapma. Kanıtlar ÇELİŞİYORSA "
    "(fiyat yükseliyor ama CVD/trade_imbalance negatif, whale satıyor, ladder_asymmetry "
    "negatif, funding EXTREME_LONG, BTC panik) FAKE ihtimali GÜÇLENİR; kanıtlar "
    "hemfikirse DEVAM'a eğil; yeterli kanıt yoksa BELIRSIZ. "
    "verdict değeri TAM OLARAK şu üç kelimeden biri: DEVAM, FAKE, BELIRSIZ. "
    "'GERÇEK', 'REAL' gibi eş anlamlı yazma. JSON dışında tek karakter yazma."
)


# --- Çalışma zamanı durumu (tek event loop; kapı bloğu await'siz → yarışsız) ---
_state = {
    "last_eval_at": 0.0,
    "hour_marks": deque(),
    "provider_missing_until": 0.0,
    "last_error": None,
    "last_error_kind": None,
    "error_counts": {},
    "evaluated": 0,
    "skipped": 0,
    "delivered": 0,
}
_last_eval_per_symbol: dict[str, float] = {}


def _record_error(kind: str, detail: str, sym: str = "") -> None:
    """Hata türünü ayırt edilebilir kaydet — teşhis state uçta görünür olmalı."""
    _state["last_error"] = f"{sym}: {detail}" if sym else detail
    _state["last_error_kind"] = kind
    _state["error_counts"][kind] = _state["error_counts"].get(kind, 0) + 1
    # Hata TÜRÜNE göre seviye: sağlayıcı yok/timeout sessiz arızadır — görünür olmalı.
    logger.warning("LLM ikinci göz [%s] %s: %s", kind, sym or "-", detail)


def stats() -> dict:
    """Gözlem sayaçları — /state ucu ve panel rozeti bu sözlüğü okur."""
    return {
        "evaluated": _state["evaluated"],
        "delivered": _state["delivered"],
        "skipped": _state["skipped"],
        "last_error": _state["last_error"],
        "last_error_kind": _state["last_error_kind"],
        "error_counts": dict(_state["error_counts"]),
        "provider_missing_active": time.time() < _state["provider_missing_until"],
        "cooldown_sec": COOLDOWN_SEC,
        "min_score": MIN_SCORE,
        "timeout_sec": TIMEOUT_SEC,
        "http_timeout_sec": HTTP_TIMEOUT_SEC,
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
    """Türev kanıtı (funding/OI) — YALNIZCA önbellekten (90 sn TTL'i aşmışsa da kabul).

    Ağ beklemeye girmez: cache soğuksa kanıtsız devam eder (hız > genişlik —
    `get_derivatives_intel` 4 sn'ye kadar bloklayabilir, fırsat kaçar).
    """
    try:
        from app.derivatives_service import get_cached_derivatives_intel
        intel = get_cached_derivatives_intel(symbol, max_age_sec=900)
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
    # MACD MTF konfluans (kullanıcının grafik metodu): kesişim durumu/yaşı +
    # eğimler + paralel yukarı — LLM artık "MTF MACD bakışını" görerek karar verir.
    try:
        from app.macd_mtf import compute as _macd_mtf_compute
        mtf = await _macd_mtf_compute(sym)
        if isinstance(mtf, dict) and mtf.get("coverage"):
            evidence["macd_mtf"] = mtf
    except Exception:
        pass
    signals = notif.get("signals")
    if isinstance(signals, dict) and signals:
        evidence["rising_signals"] = {
            k: signals.get(k) for k in list(signals)[:12] if signals.get(k) is not None
        }
    return evidence


def parse_verdict(text) -> dict | None:
    """LLM yanıtından şemalı kararı çıkarır; toleranslı ayrıştırma, şema dışına izin yok.

    Canlıda görülen arızalar için bağışıklık (2026-09-26, rozet SCHEMA gösteriyordu):
    - Eş anlamlı verdict kelimeleri (GERÇEK/REAL/YÜKSELİŞ → DEVAM vb.) eşlenir.
    - Sarmalanmış JSON ({"result": {...}}) içine inilir.
    - JSON'un cümle içine gömüldüğü yanıtlarda `"verdict":"..."` regex ile kurtarılır
      (serbest metin taraması YOK — "gerçek değil" tuzağına düşmemek için).
    """
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
        decoded = None  # JSON'suz yanıt → kurtarma yollarına düşer (lenient 'object' döndürebilir)
    if isinstance(decoded, dict) and not decoded.get("verdict"):
        # Tek dict-valued anahtar sarmalanmış olabilir → verdict taşıyan katmana in.
        for value in decoded.values():
            if isinstance(value, dict) and value.get("verdict"):
                decoded = value
                break
    verdict_raw = str((decoded or {}).get("verdict") or "").strip().upper() if isinstance(decoded, dict) else ""
    salvaged = False
    if not verdict_raw:
        # Kurtarma 1: JSON cümle içine gömülmüşse "verdict": "..." kalıbını ayıkla.
        import re as _re
        match = _re.search(r'"verdict"\s*:\s*"([^"]{2,24})"', raw, _re.IGNORECASE)
        if match:
            verdict_raw = match.group(1).strip().upper()
            salvaged = True
    if not verdict_raw:
        # Kurtarma 2: model düşünme sürecini sızdırdıysa (canlı örnek: "We should
        # perhaps DEVAM due strong confluence?") — ŞEMA TOKENLERINI (BÜYÜK HARF,
        # tam kelime) metinden kurtar; SON geçtiği yer nihai karar sayılır.
        # Küçük harf eşleşmez ("devam etmez" / "gerçek değil" tuzağına karşı).
        positions: list[tuple[int, str]] = []
        for token in ("DEVAM", "FAKE", "BELIRSIZ"):
            start = 0
            while True:
                idx = raw.find(token, start)
                if idx < 0:
                    break
                after = idx + len(token)
                before_ok = idx == 0 or not (raw[idx - 1].isalnum() or raw[idx - 1] == "_")
                after_ok = after >= len(raw) or not (raw[after].isalnum() or raw[after] == "_")
                if before_ok and after_ok:
                    positions.append((idx, token))
                start = after
        if positions:
            positions.sort()
            verdict_raw = positions[-1][1]
            salvaged = True
    aliases = {"DEVAM": "DEVAM", "CONTINUE": "DEVAM", "ONAY": "DEVAM",
               "GERÇEK": "DEVAM", "GERCEK": "DEVAM", "REAL": "DEVAM",
               "YÜKSELİŞ": "DEVAM", "YUKSELIS": "DEVAM", "BULLISH": "DEVAM",
               "FAKE": "FAKE", "TUZAK": "FAKE", "TRAP": "FAKE", "SAHTE": "FAKE",
               "BELIRSIZ": "BELIRSIZ", "BELİRSİZ": "BELIRSIZ", "UNCERTAIN": "BELIRSIZ",
               "NEUTRAL": "BELIRSIZ", "UNKNOWN": "BELIRSIZ", "BİLİNMİYOR": "BELIRSIZ"}
    verdict = aliases.get(verdict_raw)
    if not verdict:
        return None
    try:
        confidence = max(0.0, min(100.0, float((decoded or {}).get("confidence") or 0)))
    except (TypeError, ValueError):
        confidence = 0.0
    if salvaged and confidence == 0.0:
        # Kurtarılan yanıtta güven alanı yok: metindeki %N'e bak, yoksa nötr 50.
        import re as _re
        m_conf = (_re.search(r'(\d{1,3})\s*%', raw)
                  or _re.search(r'%\s*(\d{1,3})', raw)          # Türkçe: %65
                  or _re.search(r'"confidence"\s*:\s*(\d{1,3})', raw, _re.IGNORECASE))
        if m_conf:
            try:
                confidence = max(0.0, min(100.0, float(m_conf.group(1))))
            except ValueError:
                confidence = 50.0
        else:
            confidence = 50.0

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
        "reasons": _str_list((decoded or {}).get("reasons") if isinstance(decoded, dict) else None),
        "trap_evidence": _str_list((decoded or {}).get("trap_evidence") if isinstance(decoded, dict) else None),
        "summary": str((decoded or {}).get("summary") or "").strip()[:300] or None,
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


async def _fast_llm_call(evidence: dict) -> dict:
    """Küçük TEK-ATIMLIK completion — chat personalı/bellek/araç yükü YOK.

    `llm_analysis.chat` kişisel asistan personalı + bellek talimatlarını da
    taşıyan onlarca KB'lik system prompt ile çağrı yapıyordu; bu kanal yalnızca
    2 mesaj + ≤250 token ile saniyeler içinde döner. Sözleşme chat() ile aynı:
    sağlayıcı yoksa {"enabled": False}; taşıma hatası RuntimeError fırlatır.
    HTTP tavanı `HTTP_TIMEOUT_SEC` — dıştaki `TIMEOUT_SEC` (45 sn) her zaman
    baskındır.
    """
    from urllib.error import HTTPError
    from urllib.request import Request
    from app import database
    from app.llm_analysis import _compact_json_dumps, _decode_provider_response, decrypt_key
    from app.security import safe_provider_open, validate_provider_url

    cfg = await database.get_active_llm_config()
    if not cfg:
        return {"enabled": False, "status": "disabled", "text": None}
    base_url = await validate_provider_url(cfg["provider"]["base_url"])
    url = base_url if base_url.endswith("/chat/completions") else base_url + "/chat/completions"
    payload = {
        "model": cfg["model"]["name"],
        "temperature": 0.1,
        "max_tokens": FAST_MAX_TOKENS,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": FAST_SYSTEM_PROMPT},
            {"role": "user", "content": "Kanıt paketi (JSON):\n" + _compact_json_dumps(evidence)},
        ],
    }
    headers = {"Content-Type": "application/json",
               "Authorization": "Bearer " + decrypt_key(cfg["provider"]["api_key_encrypted"])}

    def _extract(body) -> str | None:
        """choices[0].message içinden metni çıkarır (sağlayıcı biçimlerine dayanıklı).

        - content parça listesi olabilir (OpenAI-compatible bazı gateway'ler).
        - reasoning modelleri nihai cevabı `reasoning_content`'e düşürebilir.
        """
        try:
            message = body["choices"][0]["message"]
            content = message.get("content")
            if isinstance(content, list):
                content = "".join(str(p.get("text") or "")
                                  for p in content if isinstance(p, dict))
            text = str(content or "").strip()
            if not text:
                text = str(message.get("reasoning_content") or "").strip()
            return text or None
        except (KeyError, IndexError, TypeError, AttributeError):
            return None

    def _send() -> Request:
        return Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")

    try:
        response = await safe_provider_open(_send(), timeout=HTTP_TIMEOUT_SEC)
        text = _extract(_decode_provider_response(response.read()))
        if text is None:
            raise RuntimeError("sağlayıcı yanıtı beklenen biçimde değil")
        return {"enabled": True, "text": text}
    except HTTPError as http_error:
        # json_object reddeden gateway'ler 4xx döner: response_format'sız TEK deneme.
        if http_error.code // 100 != 4:
            raise RuntimeError(f"LLM sağlayıcısı reddetti: {http_error}") from http_error
        payload.pop("response_format", None)
        try:
            response = await safe_provider_open(_send(), timeout=HTTP_TIMEOUT_SEC)
            text = _extract(_decode_provider_response(response.read()))
            if text is None:
                raise RuntimeError("sağlayıcı yanıtı beklenen biçimde değil")
            return {"enabled": True, "text": text}
        except Exception as exc:
            raise RuntimeError(f"LLM gateway yanıt vermedi: {exc}") from exc
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"LLM gateway yanıt vermedi: {exc}") from exc


async def evaluate(notif: dict) -> dict | None:
    """Uygun bildirim için LLM kararını alıp bildirim zarfı döndürür; atlanırsa None."""

    if not eligible(notif):
        return None
    sym = str(notif.get("symbol") or "").upper()
    now = time.time()
    if now < _state["provider_missing_until"]:
        return None
    try:
        setting = await database.get_llm_setting("llm_second_eye_enabled", "1")
    except Exception:
        setting = "1"
    if str(setting) != "1":
        return None
    # Kapılar: await'siz senkron blok — tek event loop'ta yarışsız, kilitsiz.
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
    try:
        result = await asyncio.wait_for(_fast_llm_call(evidence), timeout=TIMEOUT_SEC)
    except asyncio.CancelledError:
        raise
    except asyncio.TimeoutError:
        _record_error("timeout", f"çağrı {TIMEOUT_SEC:.0f} sn içinde dönmedi — sağlayıcı yavaş", sym)
        return None
    except Exception as exc:
        _record_error("http", str(exc), sym)
        return None
    if not isinstance(result, dict):
        _record_error("bad_response", "beklenmeyen yanıt biçimi", sym)
        return None
    if result.get("enabled") is False:
        # Sağlayıcı yapılandırılmamış (llm_enabled=0 veya aktif chat modeli yok):
        # tekrar denemek maliyetsiz ama gereksiz — 10 dk sessiz, hata TÜRÜ görünür.
        _record_error("provider_missing",
                      "sağlayıcı yapılandırılmamış (llm_enabled / aktif chat modeli eksik olabilir)")
        _state["provider_missing_until"] = time.time() + PROVIDER_MISSING_BACKOFF_SEC
        return None
    text = result.get("text") or result.get("content")
    verdict = parse_verdict(text)
    if not verdict:
        _record_error("schema", f"yanıt karar şemasına uymadı: {str(text)[:200]}", sym)
        return None
    _state["last_error"] = None
    _state["last_error_kind"] = None
    _state["evaluated"] += 1
    _state["delivered"] += 1
    logger.info("LLM ikinci göz kararı: %s → %s %%%s", sym, verdict["verdict"], verdict["confidence"])
    return build_verdict_notification(notif, verdict)


def reset_state_for_tests() -> None:
    _state.update({"last_eval_at": 0.0, "provider_missing_until": 0.0,
                   "last_error": None, "last_error_kind": None, "error_counts": {},
                   "evaluated": 0, "skipped": 0, "delivered": 0})
    _state["hour_marks"].clear()
    _last_eval_per_symbol.clear()
