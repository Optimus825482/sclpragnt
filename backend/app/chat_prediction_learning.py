"""LLM postmortem and bounded insight derivation for Chat M5/M15 predictions.

Predictions are journaled in ``chat_predictions``; outcomes come only from
closed M1 candles (never from the LLM).  The LLM's role is limited to
explaining an already-measured outcome: which inputs misled it on failures and
which metrics supported the call on successes.  Insights are aggregated
deterministically from those factor tags, so a model response can never
promote itself into an active lesson without a measured outcome underneath.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict

ANALYSIS_OUTPUT_SCHEMA = {
    "summary": "en fazla 240 karakter; ne tahmin edilmişti, ne oldu, ana neden",
    "misleading_factors": ["yanıltıcı olan 0-4 kanıt/metrik adı"],
    "success_factors": ["başarıyı destekleyen 0-4 kanıt/metrik adı"],
    "lesson": "sonraki tahmin için tek cümlelik uygulanabilir ders, en fazla 200 karakter",
    "confidence_note": "güven skoru doğru mu yanlış mı kalibre olmuştu, tek cümle",
}

SNAPSHOT_KEYS = ("evidence", "risks", "label_policy", "candidate", "horizon_minutes", "source")


def build_analysis_snapshot(prediction: dict) -> dict:
    """Compact, causal payload for the postmortem call: prediction + measured outcome."""
    snapshot = prediction.get("snapshot") or {}
    candidate = snapshot.get("candidate") or {}
    indicator_context = {}
    for key in ("returns_pct", "trend", "volume", "liquidity", "volatility"):
        value = candidate.get(key)
        if value:
            indicator_context[key] = value
    return {
        "type": "chat_prediction_postmortem", "paper_only": True,
        "prediction": {
            "symbol": prediction.get("symbol"), "horizon_minutes": prediction.get("horizon_minutes"),
            "direction": prediction.get("direction"), "confidence": prediction.get("confidence"),
            "entry_price": prediction.get("entry_price"), "min_move_pct": prediction.get("min_move_pct"),
            "regime": prediction.get("regime"), "score": prediction.get("score"),
            "created_at": prediction.get("created_at"),
        },
        "measured_outcome": {
            "status": prediction.get("status"), "outcome_price": prediction.get("outcome_price"),
            "outcome_return_pct": prediction.get("outcome_return_pct"),
            "outcome_direction": prediction.get("outcome_direction"),
            "direction_correct": prediction.get("direction_correct"),
            "max_favorable_pct": prediction.get("max_favorable_pct"),
            "max_adverse_pct": prediction.get("max_adverse_pct"),
            "outcome_details": prediction.get("outcome_details"),
        },
        "prediction_inputs": {
            "evidence": prediction.get("evidence") or [], "risks": prediction.get("risks") or [],
            "indicator_context": indicator_context,
        },
        "analysis_output_schema": ANALYSIS_OUTPUT_SCHEMA,
    }


ANALYSIS_PROMPT = (
    "Bu, ölçülmüş bir Chat M5/M15 tahmininin sonradan analizidir. Yalnızca verilen "
    "prediction_inputs ve measured_outcome alanlarını kullan; yeni veri uydurma. "
    "Tahmin doğruysa success_factors içine hangi metrikler kararı taşıdığını yaz; "
    "yanlışsa misleading_factors içine hangi kanıtların yanılttığını yaz. "
    "Her faktör kısa bir metrik/kanıt etiketi olsun (örn. 'hacim_orani_yuksek', 'adx_yetersiz', "
    "'rejim_uyusmazligi'). outcome_direction 'range' ise hareket eşiği "
    "aşılamadığını başarısızlık nedeni olarak değerlendir. JSON dışında hiçbir şey yazma. "
    "Şema tam olarak: {\"summary\":\"...\",\"misleading_factors\":[...],\"success_factors\":[...],"
    "\"lesson\":\"...\",\"confidence_note\":\"...\"}"
)


def parse_analysis_response(text) -> dict | None:
    """Extract the postmortem JSON; tolerate fenced or prose-wrapped responses."""
    if not text:
        return None
    raw = str(text).strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        decoded = json.loads(raw[start:end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(decoded, dict) or not isinstance(decoded.get("summary"), str):
        return None
    def _tags(value, limit=4):
        if not isinstance(value, list):
            return []
        tags = []
        for item in value:
            tag = str(item or "").strip().lower().replace(" ", "_")[:60]
            if tag and tag not in tags:
                tags.append(tag)
            if len(tags) >= limit:
                break
        return tags
    factors = {
        "misleading_factors": _tags(decoded.get("misleading_factors")),
        "success_factors": _tags(decoded.get("success_factors")),
        "confidence_note": str(decoded.get("confidence_note") or "").strip()[:300] or None,
    }
    return {
        "summary": str(decoded.get("summary") or "").strip()[:400],
        "lesson": str(decoded.get("lesson") or "").strip()[:300],
        "factors": factors,
    }


def derive_insights(analyzed: list[dict], *, min_samples: int = 5) -> list[dict]:
    """Aggregate factor tags from analyzed predictions into scoped insights."""
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for row in analyzed:
        if row.get("status") != "evaluated" or row.get("analysis_status") != "done":
            continue
        horizon = int(row.get("horizon_minutes") or 0)
        symbol = str(row.get("symbol") or "").upper() or None
        grouped[(symbol, horizon)].append(row)
        grouped[(None, horizon)].append(row)

    insights = []
    for (symbol, horizon), samples in grouped.items():
        if len(samples) < min_samples:
            continue
        success = sum(bool(row.get("direction_correct")) for row in samples)
        failures = len(samples) - success
        misleading = Counter(tag for row in samples
                             for tag in ((row.get("analysis_factors") or {}).get("misleading_factors") or []))
        supporting = Counter(tag for row in samples
                             for tag in ((row.get("analysis_factors") or {}).get("success_factors") or []))
        lessons = [row.get("analysis") for row in samples if isinstance(row.get("analysis"), str) and row.get("analysis")]
        scope = f"symbol:{symbol}" if symbol else f"horizon:{horizon}"
        subject = symbol or "genel evren"
        parts = [f"{subject} · {horizon}dk chat tahminleri {len(samples)} ölçümde %{success / len(samples) * 100:.0f} doğru."]
        if misleading:
            tops = ", ".join(f"{tag} ({count})" for tag, count in misleading.most_common(3))
            parts.append(f"En sık yanıltan: {tops}.")
        if supporting:
            tops = ", ".join(f"{tag} ({count})" for tag, count in supporting.most_common(3))
            parts.append(f"Başarıyı en çok destekleyen: {tops}.")
        if lessons:
            parts.append(f"Son ders: {lessons[-1][:160]}")
        key = f"chat-prediction:{symbol or 'global'}:{horizon}"
        insights.append({
            "insight_key": key, "scope": scope, "symbol": symbol, "horizon_minutes": horizon,
            "sample_size": len(samples), "success_count": success, "failure_count": failures,
            "insight": " ".join(parts)[:600], "factors": {
                "misleading_factors": [tag for tag, _ in misleading.most_common(5)],
                "success_factors": [tag for tag, _ in supporting.most_common(5)],
            },
            "source_ids": [row.get("prediction_id") for row in samples[-20:] if row.get("prediction_id")],
            "status": "active" if len(samples) >= min_samples else "candidate",
        })
    return insights


def insight_summary(rows: list[dict], limit: int = 6) -> list[dict]:
    """Compact learned-lesson block for LLM context injection."""
    compact = []
    for row in rows[:limit]:
        factors = row.get("factors") or {}
        compact.append({
            "scope": row.get("scope"), "horizon_minutes": row.get("horizon_minutes"),
            "sample_size": row.get("sample_size"), "insight": row.get("insight"),
            "misleading_factors": factors.get("misleading_factors") or [],
            "success_factors": factors.get("success_factors") or [],
            "policy": "learned_context_only; tahmin kararı tek başına bunu zorunlu kılmaz",
        })
    return compact
