"""Paper-only pattern research registry and bounded research orchestration.

This module deliberately stores evidence, not trading instructions.  A pattern
can become ``validated`` only after the caller supplies fee-aware OOS/forward
evidence; the LLM must never treat a candidate as a guaranteed edge.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from app import database

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_TIMEFRAMES = {"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "1d"}

# A source-aware catalogue makes the research boundary explicit: code visibility
# does not imply an approved trading rule, and a chart-only data source is not
# silently represented as exchange microstructure.
INDICATOR_RESEARCH_CATALOG = {
    "td9_exhaustion": {
        "status": "available_snapshot_feature", "source_visibility": "open_source_reference",
        "data_required": ["closed_ohlcv"], "entry_eligible": False,
        "purpose": "Momentum exhaustion context; requires independent trend/volume confirmation.",
    },
    "market_structure_fvg_order_block": {
        "status": "available_snapshot_feature", "source_visibility": "open_source_reference",
        "data_required": ["closed_ohlcv"], "entry_eligible": False,
        "purpose": "Confirmed swing/BOS, three-candle FVG and causal order-block context.",
    },
    "wick_rejection_zscore": {
        "status": "available_snapshot_feature", "source_visibility": "derived_public_formula",
        "data_required": ["closed_ohlcv"], "entry_eligible": False,
        "purpose": "Statistical wick outlier; confirmation required.",
    },
    "volume_profile_context": {
        "status": "available_proxy_feature", "source_visibility": "open_source_reference",
        "data_required": ["closed_ohlcv"], "entry_eligible": False,
        "purpose": "Typical-price OHLCV POC/value-area proxy, not price-level traded volume.",
    },
    "lorentzian_classification": {
        "status": "research_backlog", "source_visibility": "open_source_reference",
        "data_required": ["long_clean_ohlcv_history", "frozen_feature_spec", "held_out_labels"], "entry_eligible": False,
        "purpose": "Separate classifier experiment; no production or paper-entry activation without OOS/forward evidence.",
    },
    "footprint_cvd": {
        "status": "data_infrastructure_required", "source_visibility": "open_source_reference",
        "data_required": ["trade_level_aggressor_data", "historical_trade_archive"], "entry_eligible": False,
        "purpose": "True footprint/CVD cannot be reconstructed from OHLCV or top-of-book snapshots.",
    },
    "liquidation_levels": {
        "status": "data_infrastructure_required", "source_visibility": "open_source_proxy_only",
        "data_required": ["futures_liquidation_feed_or_explicit_proxy_definition"], "entry_eligible": False,
        "purpose": "Spot OHLCV cannot establish actual liquidation levels.",
    },
}


def _clean_timeframes(values):
    values = values or ["1m", "5m", "15m", "1h", "4h"]
    return list(dict.fromkeys(str(v).lower() for v in values if str(v).lower() in ALLOWED_TIMEFRAMES))[:8]


async def list_patterns(args: dict):
    rows = await database.get_research_patterns(
        status=args.get("status"), timeframe=args.get("timeframe"), limit=args.get("limit", 30)
    )
    return {"ok": True, "paper_only": True, "count": len(rows), "patterns": rows}


async def list_indicator_catalog(args: dict):
    status = str(args.get("status") or "").strip()
    items = {
        name: value for name, value in INDICATOR_RESEARCH_CATALOG.items()
        if not status or value["status"] == status
    }
    return {"ok": True, "paper_only": True, "count": len(items), "indicators": items,
            "rule": "Catalog entries are research capabilities, never automatic entry authorization."}


async def save_pattern(args: dict):
    name = str(args.get("name") or "").strip()
    definition = args.get("definition")
    evidence = args.get("evidence") or {}
    if not name or not isinstance(definition, dict):
        return {"ok": False, "paper_only": True, "error": "name ve definition gerekli"}
    status = str(args.get("status") or "candidate").lower()
    if status not in {"candidate", "validated", "deprecated"}:
        status = "candidate"
    # Validated is intentionally evidence-gated.  This prevents an LLM tool
    # call from silently turning a single attractive backtest into memory.
    if status == "validated":
        required = ("oos", "forward", "fees_included", "sample_size")
        missing = [key for key in required if evidence.get(key) in (None, "", False)]
        if missing:
            return {"ok": False, "paper_only": True, "error": "validated kayıt için OOS/forward/ücret/örnek kanıtı eksik", "missing": missing}
        if int(evidence.get("sample_size", 0) or 0) < 20:
            return {"ok": False, "paper_only": True, "error": "validated kayıt için en az 20 gözlem gerekir"}
    pattern_id = await database.save_research_pattern({
        "name": name, "description": args.get("description"), "symbols_scope": args.get("symbols_scope", "active"),
        "symbols": args.get("symbols") or [], "timeframes": _clean_timeframes(args.get("timeframes")),
        "definition": definition, "evidence": evidence, "status": status,
        "confidence": max(0.0, min(float(args.get("confidence", 0.3)), 1.0)),
        "source_run_id": args.get("source_run_id"),
    })
    return {"ok": True, "paper_only": True, "pattern_id": pattern_id, "status": status,
            "message": "Desen araştırma hafızasına kaydedildi; canlı stratejiye otomatik uygulanmadı."}


async def run_universe_research(args: dict):
    """Run the existing all-symbol causal spike research script safely.

    The script is an allow-listed local research entrypoint.  No user supplied
    shell command is accepted, and the process has a bounded timeout.
    """
    days = max(1, min(int(args.get("days", 7)), 30))
    threshold = max(0.1, min(float(args.get("threshold_pct", 5.0)), 100.0))
    horizon = max(1, min(int(args.get("horizon_minutes", 15)), 240))
    output = ROOT / f"pattern-research-{int(time.time())}.json"
    cmd = [sys.executable, str(ROOT / "scripts" / "research_m1_spikes_all_symbols.py"),
           "--hours", str(days * 24), "--fetch-days", str(min(days + 1, 30)), "--threshold-pct", str(threshold),
           "--horizon-minutes", str(horizon), "--output", str(output)]
    selected_symbols = [str(s).replace("_", "").upper() for s in (args.get("symbols") or []) if str(s).strip()]
    if selected_symbols:
        cmd[2:2] = ["--symbols", *selected_symbols]

    def run():
        return subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                              timeout=3600, check=False)
    proc = await __import__("asyncio").to_thread(run)
    if proc.returncode != 0:
        return {"ok": False, "paper_only": True, "error": "research process failed", "stderr": proc.stderr[-2000:]}
    result = {}
    try:
        result = json.loads(output.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"ok": False, "paper_only": True, "error": f"research çıktısı okunamadı: {exc}", "stdout": proc.stdout[-1000:]}
    run_id = await database.save_research_run({
        "run_type": "universe_spike_scan", "scope": args.get("scope", "all"),
        "symbols": args.get("symbols") or [], "timeframes": _clean_timeframes(args.get("timeframes")),
        "parameters": {"days": days, "threshold_pct": threshold, "horizon_minutes": horizon},
        "result": {"event_count": result.get("event_count"), "symbol_count": len(result.get("max_forward_move_by_symbol", {})), "output": str(output)},
        "status": "completed", "paper_only": True,
    })
    return {"ok": True, "paper_only": True, "run_id": run_id, "event_count": result.get("event_count"),
            "symbol_count": len(result.get("max_forward_move_by_symbol", {})), "output": str(output),
            "limitations": result.get("limitations", []) + ["Bu ilk evren tarayıcısı M1 causal etiket taramasıdır; M5/M15/H1/H4 feature/replay doğrulaması ayrı araştırma adımıdır."]}


async def get_runs(args: dict):
    rows = await database.get_research_runs(limit=args.get("limit", 20), run_type=args.get("run_type"))
    return {"ok": True, "paper_only": True, "count": len(rows), "runs": rows}
