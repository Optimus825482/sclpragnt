import ast, sys

FP = "D:/scalperagent_v4/backend/app/routers/monitoring.py"

def check(msg):
    with open(FP, "r", encoding="utf-8") as f:
        c = f.read()
    try:
        ast.parse(c)
        print(f"  OK after {msg}")
        return True
    except SyntaxError as e:
        print(f"  FAIL at line {e.lineno} after {msg}: {e.msg}")
        lines = c.split("\n")
        for i in range(max(0,e.lineno-3), min(len(lines),e.lineno+3)):
            print(f"    {i+1}: {repr(lines[i][:120])}")
        return False

with open(FP, "r", encoding="utf-8") as f:
    content = f.read()

print(f"Original: {len(content)} chars")

# 1: contextlib import
content = content.replace(
    "from app.alerting import deliver_web_push\nfrom app.ws_runtime import ws_manager\n\nlogger",
    "from app.alerting import deliver_web_push\nfrom app.ws_runtime import ws_manager\nfrom contextlib import asynccontextmanager\n\nlogger", 1)
with open(FP, "w", encoding="utf-8") as f: f.write(content)
if not check("1"): sys.exit(1)

# 2: _state_lock + _locked_state
content = content.replace(
    "_scan_lock = asyncio.Lock()\n\n# Runtime state DB",
    "_scan_lock = asyncio.Lock()\n\n_state_lock = asyncio.Lock()\n\n@asynccontextmanager\nasync def _locked_state():\n    async with _state_lock:\n        yield\n\n# Runtime state DB", 1)
with open(FP, "w", encoding="utf-8") as f: f.write(content)
if not check("2"): sys.exit(1)

# 3: normalize_score CAP + docstring
content = content.replace(
    "    return round(max(0.0, min(100.0, raw)), 1)\n\n\nasync def _persist_runtime_state",
    "    cap = config.MONITORING_SCORE_NORM_CAP\n    return round(max(0.0, min(100.0, raw / cap * 100)), 1)\n\n\nasync def _persist_runtime_state", 1)
content = content.replace(
    'def normalize_score(raw_score: float) -> float:\n    """velocity_score zaten 0-100 bandinda uretilir; yalnizca tasmayi kirpar.\n\n    2026-09-06 oncesi eski formul 0-200+ uretebiliyordu ve burada cape gore\n    yeniden olcekleniyordu. Yeni formul dogrudan 0-100 urettigi icin eski\n    kayitlar disinda ek donusum gerekmez; eski kayitlar `_stored_panel_score`\n    tarafindan timestamp\'e gore bir kez normalize edilir.\n    """',
    'def normalize_score(raw_score: float) -> float:\n    """velocity_score 0-400+ bandina cikabilir; MONITORING_SCORE_NORM_CAP ile\n    0-100 panel olcegine haritalanir. Cap astiysa 100, astiysa dogrusal (2026-09-07).\n    """', 1)
with open(FP, "w", encoding="utf-8") as f: f.write(content)
if not check("3"): sys.exit(1)

# 4: _persist_runtime_state wrapped (ONLY replace inside this function, not restore_runtime_state)
idx = content.find("async def _persist_runtime_state")
idx_try = content.find("\n    try:", idx)
idx_deferred = content.find("# Deferred push", idx_try)
# Use a more specific replacement: "    try:\n        # Deferred push" that occurs right after _persist_runtime_state def
snippet = content[idx_try:idx_try+200]
old = "    try:\n        # Deferred push kuyrugunu da kaydet"
new = "    try:\n        async with _locked_state():\n            # Deferred push kuyrugunu da kaydet"
snippet = snippet.replace(old, new, 1)
content = content[:idx_try] + snippet + content[idx_try+200:]
# Now fix indentation
lines = content.split("\n")
persist_idx = None
for i, l in enumerate(lines):
    if "async def _persist_runtime_state() -> None:" in l:
        persist_idx = i
        break
if persist_idx:
    in_locked = False
    for j in range(persist_idx, min(persist_idx+40, len(lines))):
        if "async with _locked_state():" in lines[j]:
            in_locked = True
            continue
        if in_locked:
            stripped = lines[j].lstrip()
            if stripped.startswith(("await database.set", "except")):
                in_locked = False
            elif stripped:
                ci = len(lines[j]) - len(stripped)
                if ci == 8:
                    lines[j] = "            " + stripped
                elif ci == 12:
                    lines[j] = "                " + stripped
content = "\n".join(lines)
with open(FP, "w", encoding="utf-8") as f: f.write(content)
if not check("4"): sys.exit(1)

# 5: restore_runtime_state replacement
idx = content.find("async def restore_runtime_state() -> None:")
nxt = content.find("\ndef _effective_min_score", idx)
if idx > 0 and nxt > 0:
    new_func = 'async def restore_runtime_state() -> None:\n    """DBden runtime statei geri yukler."""\n    try:\n        raw = await database.get_llm_setting(_STATE_SETTING_KEY, "{}")\n        async with _locked_state():\n            payload = json.loads(raw or "{}")\n            if isinstance(payload, dict):\n                _monitoring_state["pending_targets"] = payload.get("pending_targets") or {}\n                _monitoring_state["notified_symbols"] = payload.get("notified_symbols") or {}\n                _monitoring_state["watchlist_seen_at"] = payload.get("watchlist_seen_at") or {}\n                _monitoring_state["candidate_streak"] = payload.get("candidate_streak") or {}\n                _monitoring_state["risk_off"] = bool(payload.get("risk_off", False))\n                _monitoring_state["history"] = (payload.get("history") or [])[:HISTORY_LIMIT]\n                deferred = payload.get("deferred_push") or []\n                _deferred_push.clear()\n                for n in deferred:\n                    _deferred_push.append(n)\n                _monitoring_state["pending_targets"] = payload.get("pending_targets") or {}\n    except Exception as exc:\n        logger.debug("monitoring state geri yuklenemedi: %s", exc)\n'
    content = content[:idx] + new_func + content[nxt:]
    with open(FP, "w", encoding="utf-8") as f: f.write(content)
if not check("5"): sys.exit(1)

# 6: _effective_min_score with RISK_OFF
idx = content.find("def _effective_min_score")
nxt = content.find("\n\nasync def get_user", idx)
if idx > 0 and nxt > 0:
    new_func = 'def _effective_min_score(settings) -> float:\n    """O an gercekten uygulanan esik: admin min_score.\n    Piyasa RISK_OFF rejimdeyse esik otomatik yukseltilir (2026-09-07).\n    """\n    base = float(settings.get("min_score", config.MONITORING_MIN_SCORE_DEFAULT))\n    if _monitoring_state.get("risk_off", False):\n        base = max(base + 20.0, 50.0)\n    return round(min(100.0, base), 1)\n'
    content = content[:idx] + new_func + content[nxt:]
    with open(FP, "w", encoding="utf-8") as f: f.write(content)
if not check("6"): sys.exit(1)

# 7: background loop
content = content.replace("async with _scan_lock:\n                await _run_scan()", "async with _scan_lock:\n                async with _locked_state():\n                    await _run_scan()", 1)
with open(FP, "w", encoding="utf-8") as f: f.write(content)
if not check("7"): sys.exit(1)

# 8: reset_notifications
content = content.replace('_require_admin(request)\n    _monitoring_state["notified_symbols"].clear()', '_require_admin(request)\n    async with _locked_state():\n        _monitoring_state["notified_symbols"].clear()', 1)
with open(FP, "w", encoding="utf-8") as f: f.write(content)
if not check("8"): sys.exit(1)

# 9: _flush_deferred_push replacement
idx = content.find("async def _flush_deferred_push")
nxt = content.find("\n\n\ndef _build_notification", idx)
if idx > 0 and nxt > 0:
    new_func = 'async def _flush_deferred_push():\n    """Sessiz saat bittiyse ertelenen push kuyrugunu bosalt."""\n    async with _locked_state():\n        if not _deferred_push:\n            return\n        settings = await get_user_notification_settings()\n        if _in_quiet_hours(settings):\n            return\n        sent = 0\n        while _deferred_push:\n            notif = _deferred_push.popleft()\n            ok = await _send_push(notif)\n            if ok:\n                sent += 1\n                nid = notif.get("id")\n                if nid:\n                    try:\n                        await database.mark_monitoring_push_sent(nid)\n                    except Exception as exc:\n                        logger.warning("push etiketi guncellenemedi %s: %s", nid, exc)\n            else:\n                _deferred_push.append(notif)\n                break\n    if sent:\n        logger.info("Monitoring: sessiz saat bitti, %d ertelenen push gonderildi", sent)\n'
    content = content[:idx] + new_func + content[nxt:]
    with open(FP, "w", encoding="utf-8") as f: f.write(content)
if not check("9"): sys.exit(1)

# 10: volume_ratio in profile
content = content.replace('"m5_pattern_ok": r.get("m5_pattern_ok"), "leading_ok": r.get("leading_ok")}', '"m5_pattern_ok": r.get("m5_pattern_ok"), "leading_ok": r.get("leading_ok"), "volume_ratio": r.get("volume_ratio")}', 1)
with open(FP, "w", encoding="utf-8") as f: f.write(content)
if not check("10"): sys.exit(1)

# 11: _db_latencies in state
content = content.replace('"risk_off": False,            # piyasa rejimi RISK_OFF (gozlem bayragi, esigi etkilemez', '"_db_latencies": [],              # notify query gecikmeleri (diagnostics icin, 2026-09-07)\n    "risk_off": False,            # piyasa rejimi RISK_OFF (gozlem bayragi, esigi etkilemez', 1)
with open(FP, "w", encoding="utf-8") as f: f.write(content)
if not check("11"): sys.exit(1)

# 12: DB timing on save
content = content.replace("await database.save_monitoring_notifications(new_entries)", "_s_t0 = time.time()\n        await database.save_monitoring_notifications(new_entries)\n        _s_t1 = time.time()\n        _db_lat = (_s_t1 - _s_t0) * 1000\n        _monitoring_state.setdefault(\"_db_latencies\", []).append(_db_lat)\n        _monitoring_state[\"_db_latencies\"] = _monitoring_state[\"_db_latencies\"][-20:]", 1)
with open(FP, "w", encoding="utf-8") as f: f.write(content)
if not check("12"): sys.exit(1)

# 13: DB timing on pending query
old_p = "pending_by_symbol = await database.get_pending_monitoring_notifications(\n            [str(c.get(\"symbol\", \"\") or \"\").upper() for c in candidates_list])\n    except Exception as exc:\n        logger.warning(\"monitoring pending toplu sorgu hatasi: %s\", exc)\n        pending_by_symbol = {}"
new_p = "_t0 = time.time()\n        pending_by_symbol = await database.get_pending_monitoring_notifications(\n            [str(c.get(\"symbol\", \"\") or \"\").upper() for c in candidates_list])\n        _t1 = time.time()\n        _db_lat = (_t1 - _t0) * 1000\n        _monitoring_state.setdefault(\"_db_latencies\", []).append(_db_lat)\n        _monitoring_state[\"_db_latencies\"] = _monitoring_state[\"_db_latencies\"][-20:]\n    except Exception as exc:\n        logger.warning(\"monitoring pending toplu sorgu hatasi: %s\", exc)\n        pending_by_symbol = {}"
if old_p in content:
    content = content.replace(old_p, new_p, 1)
    with open(FP, "w", encoding="utf-8") as f: f.write(content)
    check("13-pending-only")
else:
    print("  Patch 13: pattern not found")

# 14: diagnostics metrics
idx = content.find("async def monitoring_diagnostics()")
nxt = content.find('@router.post("/api/monitoring/reset-notifications")', idx)
if idx > 0 and nxt > 0:
    func_section = content[idx:nxt]
    last_ret = func_section.rfind("    return {")
    after_ret = func_section[last_ret:]
    if last_ret > 0 and len(after_ret) < 600:
        before = content[:idx+last_ret]
        after = content[idx+last_ret:]
        new = '    ws_metrics = {}\n    try:\n        from app.ws_runtime import ws_manager\n        ws_metrics["active_connections"] = len(ws_manager.active_connections)\n    except Exception:\n        ws_metrics["active_connections"] = None\n    try:\n        md = market\n        ws_metrics["ws_last_event_at"] = getattr(md, "ws_last_event_at", None)\n        ws_metrics["rest_last_event_at"] = getattr(md, "rest_last_event_at", None)\n        ws_metrics["ws_last_error"] = str(getattr(md, "ws_last_error", None))[:200] if getattr(md, "ws_last_error", None) else None\n        ws_metrics["rest_last_error"] = str(getattr(md, "rest_last_error", None))[:200] if getattr(md, "rest_last_error", None) else None\n        ws_metrics["ws_connected_at"] = getattr(md, "ws_connected_at", None)\n        ws_metrics["connection_generation"] = getattr(md, "connection_generation", 0)\n        ws_metrics["reconnect_requested"] = getattr(md, "reconnect_requested", False)\n        ws_metrics["subscribed_symbols"] = len(getattr(md, "symbols", []))\n    except Exception as exc:\n        ws_metrics["error"] = str(exc)\n    rate_stats = {}\n    try:\n        from app.routers import velocity\n        if hasattr(velocity, "_rate_limit_stats"):\n            rate_stats = velocity._rate_limit_stats()\n    except Exception as exc:\n        rate_stats["error"] = str(exc)\n    memory_metrics = {}\n    try:\n        md = market\n        if hasattr(md, "klines"):\n            total_klines = 0\n            total_volumes = 0\n            for tf_kv in md.klines.values():\n                for sym_kv in tf_kv.values():\n                    if isinstance(sym_kv, dict):\n                        total_klines += len(sym_kv.get("timestamps") or [])\n                        total_volumes += len(sym_kv.get("volumes") or [])\n            memory_metrics["total_cached_klines"] = total_klines\n            memory_metrics["total_cached_volumes"] = total_volumes\n        if hasattr(md, "tickers"):\n            memory_metrics["ticker_count"] = len(md.tickers)\n        if hasattr(md, "ticker_24h"):\n            memory_metrics["ticker_24h_count"] = len(md.ticker_24h)\n        if hasattr(md, "orderflow"):\n            memory_metrics["orderflow_count"] = len(md.orderflow)\n        if hasattr(md, "trade_flow"):\n            memory_metrics["trade_flow_count"] = len(md.trade_flow)\n    except Exception as exc:\n        memory_metrics["error"] = str(exc)\n    db_latency = {}\n    try:\n        _latencies = _monitoring_state.get("_db_latencies", [])\n        recent = _latencies[-3:] if _latencies else []\n        if recent:\n            db_latency["avg_notify_ms"] = round(sum(recent) / len(recent), 1)\n            db_latency["max_notify_ms"] = round(max(recent), 1)\n        else:\n            db_latency["avg_notify_ms"] = None\n        db_latency["sample_count"] = len(recent)\n    except Exception:\n        pass\n    freshness_sample = {}\n    try:\n        for sym_item in list(_monitoring_state.get("last_candidates") or [])[:3]:\n            sym_name = str(sym_item.get("symbol", "") or "")\n            if sym_name and hasattr(market, "data_freshness"):\n                fd = market.data_freshness(sym_name, "5m")\n                freshness_sample[sym_name] = fd\n    except Exception:\n        pass\n    return {\n        "paper_only": True,\n        "effective_min_score": min_score,\n        "overall": summary,\n        "per_symbol_worst": dict(list(sym_summary.items())[:30]),\n        "settings": settings,\n        "ws_health": ws_metrics,\n        "rate_limiter": rate_stats,\n        "memory_metrics": memory_metrics,\n        "db_latency": db_latency,\n        "freshness_sample": freshness_sample,\n    }'
        content = before + new + after
        with open(FP, "w", encoding="utf-8") as f: f.write(content)
        print("  Patch 14: diagnostics extended")
    else:
        print(f"  Patch 14: problematic - last_ret={last_ret}, after_len={len(after_ret)}")

# Final check
with open(FP, "r", encoding="utf-8") as f:
    final = f.read()
try:
    ast.parse(final)
    print(f"\nPASS: all patches applied. Final: {len(final)} chars")
except SyntaxError as e:
    print(f"\nFINAL FAIL line {e.lineno}: {e.msg}")
