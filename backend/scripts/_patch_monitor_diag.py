import ast, os

with open(r'D:\scalperagent_v4\backend\app\routers\monitoring.py', 'r', encoding='utf-8') as f:
    content = f.read()

old_return = """    return {
        "paper_only": True,
        "effective_min_score": min_score,
        "overall": summary,
        "per_symbol_worst": dict(list(sym_summary.items())[:30]),
        "settings": settings,
    }"""

new_return = """    # WS and rate limit metrics (2026-09-07)
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
    except Exception:
        pass
    return {
        "paper_only": True,
        "effective_min_score": min_score,
        "overall": summary,
        "per_symbol_worst": dict(list(sym_summary.items())[:30]),
        "settings": settings,
        "ws_health": ws_metrics,
        "rate_limiter": rate_stats,
        "freshness_sample": freshness_sample,
    }"""

if old_return in content:
    content = content.replace(old_return, new_return, 1)
    with open(r'D:\scalperagent_v4\backend\app\routers\monitoring.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("PATCHED: diagnostics return updated")
else:
    print("NOT FOUND: old_return pattern not matched")

try:
    ast.parse(content)
    print('PASS: monitoring.py compiles')
except SyntaxError as e:
    print(f'FAIL: syntax error: {e}')
