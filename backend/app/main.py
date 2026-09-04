import os
import asyncio
import math
import time
import logging
import subprocess
import json
import tempfile
import csv
import io
import random
import re
import hmac
import hashlib
import uuid
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Header, Request, Response
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from starlette.background import BackgroundTask
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger("scalper.main")
from app.config import config
from app.market_intelligence import (estimate_local_regime, execution_quality,
                                     symbol_safety, cost_aware_trade_metrics,
                                     walk_forward_assessment, trade_economics,
                                     microstructure_snapshot, symbol_outcome_profile,
                                     symbol_behavior_profile, regime_transition_signal)
from app.self_learning import build_learning_context
from app.market_data import MarketData
from app.microflow import microflow
from app.analyzer import ScalpAnalyzer
from app.circuit_breaker import breaker as strategy_breaker
from app import calibration as calibration_service
from app.correlation import CorrelationMonitor, cluster_exposure
from app.promotion import pipeline as promotion_pipeline
from app import universe_registry
from app import database
from app.backtest import run_backtest, run_custom_backtest, run_walk_forward, run_execution_stress, run_parameter_sensitivity, run_holdout_test, run_statistical_validation, get_backtest_data_quality, CUSTOM_IDENTIFIER_SCHEMA, CUSTOM_INDICATORS
CUSTOM_EXIT_POLICY_GUIDANCE = " exit_policy: mode=conditions_only yalnızca exit koşullarını, conditions_plus_protection koşul ve seçili korumaları, protection_only yalnızca korumaları kullanır; use_stop_loss, use_take_profit, use_trailing_stop, trailing_stop_pct, use_max_hold ve max_hold_bars alanlarıyla çıkışı seç."
from app.binance_tr_public import klines as fetch_klines, historical_klines, trading_symbols, ticker_24h, orderbook, top_gainers
from app.technical_analysis import calculate_snapshot, _atr, _bollinger, _cci, _ema, _mfi, _sma
from app.forecast_learning import normalize_direction, evaluate_forecast, derive_lessons
from app import ml_forecast
from app import chat_prediction_learning
from app import chat_prediction_replay
from app import llm_analysis
from app.embedding_worker import worker as embedding_worker, trade_document, signal_document
from app.memory_service import build_document
from app import memory_service
from app import migration_monitor
from app import alerting
from app import security
from app import pattern_research
from app.agent_learning import (new_trace_id, start_trace, append_event, finish_trace,
                                 evaluate_output, save_evaluation, save_experience, upsert_instinct, set_runtime_pool,
                                 promote_validated_instincts)
from app.ws_runtime import ws_manager
try:
    import asyncpg
except ImportError:
    asyncpg = None
from app.state import market, analyzer  # noqa: F401  (shared singletons)
from app.api_common import (  # noqa: F401
    _start_background, _background_tasks,
    _json_safe_positions, _fresh_public_price, _llm_guard_block_reason, correlation_monitor,
    _radar_snapshot, _radar_response_cache, log_user_action, client_context)
from app.routers import backtest as backtest_routes, llm_chat as llm_chat_routes
from app.routers import chart_forecast as chart_forecast_routes
from app.routers import maintenance as maintenance_routes, reports as reports_routes
from app.routers import runtime as runtime_routes, system as system_routes, velocity as velocity_routes
from app.routers.maintenance import (  # noqa: F401
    backfill_symbol_history, backfill_missing_active_history, history_candle_loop, microstructure_snapshot_loop)
from app.routers.llm_chat import (  # noqa: F401
    llm_forecast_evaluation_loop, chat_prediction_learning_loop, chat_prediction_auto_trade_loop,
    llm_position_manager_loop, _price_watch_symbol, _llm_entry_quality_gate,
    _parse_forecast_response, _complete_forecast_text, scan_market_snapshots,
    deep_analyze_symbol, detect_15m_upside_candidates, detect_5m_upside_candidates)
from app.routers.runtime import (  # noqa: F401
    ws_broadcast_loop, alert_loop, strategy_loop, radar_loop,
    refresh_top_gainer_symbols, top_gainers_refresh_loop, refresh_symbol_activity,
    bootstrap_symbol_activity, symbol_activity_loop, llm_replenish_after_close, llm_idle_trigger_loop,
    _radar_lock, _ws_snapshot_cache, correlation_refresh_loop, correlation_exposure_status)
from app.routers.velocity import velocity_learning_loop, autonomous_velocity_loop  # noqa: F401
from app.routers.chart_forecast import chart_forecast_evaluation_loop  # noqa: F401
from app.routers import monitoring  # noqa: F401

try:
    import edge_tts
except ImportError:
    edge_tts = None

app = FastAPI(title="Scalper Agent V4 - Paper Trading")
cors_origins = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:3004,http://localhost:3000").split(",") if origin.strip()]
# Explicit method/header allowlist: wildcard methods+headers combined with
# credentials is a known CORS misconfiguration risk if CORS_ORIGINS is ever
# broadened. The API only needs the methods below.
app.add_middleware(CORSMiddleware, allow_origins=cors_origins, allow_credentials=True,
                   allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
                   allow_headers=["Authorization", "Content-Type", "X-Real-IP"])

app.include_router(maintenance_routes.router)
app.include_router(llm_chat_routes.router)
app.include_router(chart_forecast_routes.router)
app.include_router(system_routes.router)
app.include_router(reports_routes.router)
app.include_router(velocity_routes.router)
app.include_router(monitoring.router)
app.include_router(backtest_routes.router)


_TTS_VOICE = "tr-TR-EmelNeural"
_TTS_EMOJI = re.compile("[\\U00010000-\\U0010ffff]")

def _speech_text(value: object) -> str:
    text = str(value or "")
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!?\[([^]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[#>*_~|]", " ", text)
    text = _TTS_EMOJI.sub(" ", text)
    # Give the Turkish neural voice unambiguous financial/market notation.
    def decimal(value):
        number = str(value).replace(",", ".")
        return number.replace("-", "eksi ").replace(".", " virgül ")
    text = re.sub(r"%\s*(-?\d+(?:[.,]\d+)?)", lambda m: "yüzde " + decimal(m.group(1)), text)
    text = re.sub(r"(-?\d+(?:[.,]\d+)?)\s*%", lambda m: "yüzde " + decimal(m.group(1)), text)
    text = re.sub(r"(?<![\w%])-\s*(\d+(?:[.,]\d+)?)", lambda m: "eksi " + decimal(m.group(1)), text)
    text = re.sub(r"\b(\d+(?:[.,]\d+)?)\s*[xX]\b", r"\1 kat", text)
    text = re.sub(r"\b(\d+)m\b", r"\1 dakika", text, flags=re.I)
    text = re.sub(r"\b(\d+)h\b", r"\1 saat", text, flags=re.I)
    text = re.sub(r"(?<![\w-])(\d+)[.,](\d+)", lambda m: f"{m.group(1)} virgül {m.group(2)}", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:1200]

@app.post("/api/tts/edge")
async def edge_tts_audio(payload: dict):
    global edge_tts
    if edge_tts is None:
        try:
            import edge_tts as runtime_edge_tts
            edge_tts = runtime_edge_tts
        except ImportError:
            pass
    if edge_tts is None:
        raise HTTPException(503, "Edge TTS bağımlılığı sunucuda kurulu değil")
    text = _speech_text(payload.get("text"))
    if not text:
        raise HTTPException(400, "Seslendirilecek metin bulunamadı")
    try:
        rate = max(-50, min(100, int(payload.get("rate", 0))))
        pitch = max(-50, min(50, int(payload.get("pitch", 0))))
    except (TypeError, ValueError):
        raise HTTPException(400, "Ses hızı ve perde sayısal olmalı")
    async def audio():
        communicate = edge_tts.Communicate(text, _TTS_VOICE, rate=f"{rate:+d}%", pitch=f"{pitch:+d}Hz")
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                yield chunk["data"]
    return StreamingResponse(audio(), media_type="audio/mpeg", headers={"Cache-Control": "no-store"})


@app.middleware("http")
async def require_admin_session(request: Request, call_next):
    public_paths = {"/health", "/api/auth/status", "/api/auth/login"}
    if request.method == "OPTIONS" or request.url.path in public_paths:
        return await call_next(request)
    if not security.auth_configured():
        return JSONResponse({"detail": "Yönetici kimlik doğrulaması yapılandırılmamış"}, status_code=503)
    if not security.request_authenticated(request.headers, request.cookies):
        return JSONResponse({"detail": "Kimlik doğrulama gerekli"}, status_code=401)
    return await call_next(request)


def _session_user(request: Request):
    """Current principal from cookie/bearer, or None."""
    return security.request_user(request.headers, request.cookies)


def _require_admin(request: Request):
    """Admin-only gate; raises 403 for non-admin principals."""
    user = security.request_user(request.headers, request.cookies)
    if not user:
        raise HTTPException(status_code=401, detail="Kimlik doğrulama gerekli")
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Bu işlem yalnız sistem yöneticisine açıktır")
    return user


@app.get("/api/auth/status")
async def auth_status(request: Request):
    user = _session_user(request)
    return {"configured": security.auth_configured(),
            "authenticated": user is not None,
            "username": (user or {}).get("username"),
            "role": (user or {}).get("role")}


@app.get("/api/profile")
async def profile_current(request: Request):
    """Oturumdaki kullanıcının profil bilgisi (şifre hash'i hariç)."""
    principal = _session_user(request)
    if not principal:
        raise HTTPException(status_code=401, detail="Kimlik doğrulama gerekli")
    user = await database.get_user_by_username(principal.get("username") or "")
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
    return {"ok": True, "user": _public_user(user), "paper_only": True}


@app.put("/api/profile/password")
async def profile_update_password(payload: dict, request: Request):
    """Oturumdaki kullanıcı kendi şifresini günceller (mevcut şifre doğrulanır).

    Varsayılan env-admin (DB kaydı olmayan 'admin') şifresini bu uçtan
    değiştiremez; onun için DB kullanıcısı oluşturulmalı (admin create user).
    """
    principal = _session_user(request)
    if not principal:
        raise HTTPException(status_code=401, detail="Kimlik doğrulama gerekli")
    current_password = str(payload.get("current_password") or "")
    new_password = str(payload.get("new_password") or "")
    if len(new_password) < 6:
        raise HTTPException(status_code=422, detail="Yeni şifre en az 6 karakter olmalı")
    user = await database.get_user_by_username(principal.get("username") or "")
    if not user:
        # DB kaydı olmayan env-admin: profil şifresi değiştirilemez
        raise HTTPException(status_code=409, detail="Bu kullanıcı için profil şifre değişikliği desteklenmiyor (env yöneticisi)")
    if not security.verify_password(current_password, user.get("password_hash") or ""):
        raise HTTPException(status_code=403, detail="Mevcut şifre hatalı")
    updated = await database.update_user(int(user["id"]), password_hash=security.hash_password(new_password))
    if not updated:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
    await log_user_action(principal.get("username"), principal.get("role"), "user", "PASSWORD_CHANGE",
                          target=principal.get("username"), details={"via": "profile"}, request=request)
    return {"ok": True, "message": "Şifre güncellendi", "paper_only": True}



@app.post("/api/auth/login")
async def auth_login(payload: dict, response: Response, request: Request):
    if not security.auth_configured():
        raise HTTPException(status_code=503, detail="SCALPER_ADMIN_PASSWORD ve SCALPER_SESSION_SECRET gerekli")
    trusted_edge_ip = request.headers.get("X-Real-IP", "").strip()
    client_key = trusted_edge_ip or (request.client.host if request.client else "unknown")
    if not security.login_allowed(client_key):
        await log_user_action(None, None, "auth", "LOGIN_BLOCKED",
                              target=str(payload.get("username") or "").strip().lower() or None,
                              details={"reason": "too_many_attempts"}, request=request)
        raise HTTPException(status_code=429, detail="Çok fazla başarısız giriş; 5 dakika sonra tekrar deneyin")
    username = str(payload.get("username") or "").strip().lower()
    password = str(payload.get("password") or "")
    # Varsayılan admin (env şifresi) ile DB kullanıcısı aynı anda denenir:
    # env'de SCALPER_ADMIN_PASSWORD tanımlıysa o şifreyle "admin" girişine izin ver.
    matched = False
    user = None
    try:
        user = await database.get_user_by_username(username)
    except Exception:
        user = None
    if user is not None:
        matched = bool(user.get("is_active")) and security.verify_password(password, user.get("password_hash") or "")
        if user.get("is_active") and not matched:
            matched = False
    elif username == "admin":
        # Henüz DB'ye tohumlanmamış admin: env şifresiyle eşleşirse geçici kabul.
        matched = security.password_matches(password)
        if matched:
            user = {"username": "admin", "role": "admin", "is_active": True}
    security.record_login_result(client_key, matched)
    if not matched or user is None:
        await log_user_action(username, None, "auth", "LOGIN_FAILED",
                              target=username, details={"reason": "bad_credentials"}, request=request)
        raise HTTPException(status_code=401, detail="Kullanıcı adı veya şifre hatalı")
    role = str(user.get("role") or "user").lower()
    await log_user_action((user.get("username") or username).lower(), role, "auth", "LOGIN_SUCCESS",
                          target=(user.get("username") or username).lower(), request=request)
    response.set_cookie(security.SESSION_COOKIE,
                        security.create_session_token(username=user.get("username") or username, role=role),
                        httponly=True,
                        secure=os.getenv("SCALPER_COOKIE_SECURE", "1") == "1", samesite="strict",
                        max_age=43200, path="/")
    return {"ok": True, "authenticated": True, "username": (user.get("username") or username).lower(), "role": role}


@app.post("/api/auth/logout")
async def auth_logout(request: Request, response: Response):
    principal = _session_user(request)
    await log_user_action((principal or {}).get("username"), (principal or {}).get("role"),
                          "auth", "LOGOUT", request=request)
    response.delete_cookie(security.SESSION_COOKIE, path="/")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Admin-only user management (2026-09-03)
# ---------------------------------------------------------------------------
def _public_user(user: dict) -> dict:
    return {k: v for k, v in (user or {}).items() if k != "password_hash"}



# ---------------------------------------------------------------------------
# Admin Veritabanı sayfası (2026-09-04): tablo listesi, satır verisi, CSV/SQL export.
# Yalnızca admin rolü. PostgreSQL şeması public.
# ---------------------------------------------------------------------------
_DB_TABLE_DESCRIPTIONS = {
    "agent_eval_cases": "Ajan değerlendirme test senaryoları",
    "agent_eval_runs": "Ajan değerlendirme koşu kayıtları",
    "agent_evaluations": "Ajan çıktı değerlendirme sonuçları",
    "agent_experiences": "Ajan deneyim kayıtları (self-learning)",
    "agent_trace_events": "Ajan izleme (trace) olayları",
    "agent_traces": "Ajan işlem izleri",
    "alert_events": "Uyarı tetiklenme olayları",
    "alert_rules": "Uyarı kuralları",
    "analysis_snapshots": "Analiz anlık görüntüleri (regime/confluence)",
    "audit_logs": "Güvenlik ve kullanıcı hareket kayıtları",
    "backtests": "Backtest koşu sonuçları",
    "chart_forecasts": "Chart tahmin journal'ı",
    "chart_settings": "Chart indikatör ayarları (sembol bazlı)",
    "chat_messages": "Chat mesaj geçmişi",
    "chat_prediction_insights": "Chat tahmin öğrenme içgörüleri",
    "chat_predictions": "Chat tahmin kayıtları",
    "decision_logs": "Strateji karar günlüğü",
    "embedding_jobs": "Embedding iş kuyruğu",
    "historical_candles": "Geçmiş mum verisi",
    "historical_feature_snapshots": "Geçmiş özellik anlık görüntüleri",
    "llm_forecast_lessons": "LLM tahmin dersleri (aktif/candidate)",
    "llm_forecasts": "LLM tahmin journal'ı",
    "llm_models": "LLM model tanımları",
    "llm_providers": "LLM sağlayıcıları (API anahtarları şifreli)",
    "llm_settings": "LLM ayar anahtar-değer deposu",
    "llm_skills": "LLM uzmanlık talimatları",
    "llm_symbol_guards": "Sembol koruma/cooldown kayıtları",
    "llm_tool_logs": "LLM araç çağrı günlüğü",
    "memory_documents": "Hafıza belgeleri",
    "memory_embeddings": "Hafıza vektör embedding'leri",
    "memory_relations": "Hafıza ilişki grafiği",
    "memory_retrieval_logs": "Hafıza getirme günlüğü",
    "microstructure_snapshots": "Mikro yapı (orderbook/akış) anlık görüntüleri",
    "migration_meta": "Şema migrasyon durumu",
    "ml_model_artifacts": "ML model artifact meta verisi",
    "monitoring_notifications": "Radar bildirim geçmişi",
    "notification_channels": "Bildirim kanal tanımları",
    "paper_orders": "Paper emir kayıtları",
    "positions": "Açık pozisyonlar",
    "push_subscriptions": "Web push abonelikleri",
    "replay_klines": "Replay/analiz için geçici mum verisi",
    "research_patterns": "Desen araştırma bulguları",
    "research_runs": "Araştırma koşu kayıtları",
    "signals": "Sinyal günlüğü",
    "symbol_target_state": "Sembol bazlı adaptif hedef durumu",
    "trades": "Kapanan işlemler (paper)",
    "trading_instincts": "Öğrenilmiş işlem içgüdüleri",
    "users": "Kullanıcı hesapları",
    "velocity_candidates": "Hız avcısı aday journal'ı",
    "virtual_wallet": "Paper cüzdan bakiyeleri",
}


@app.get("/api/admin/db/tables")
async def admin_db_tables(request: Request):
    """Admin: tüm public tabloları + satır sayısı + açıklamayı listeler."""
    _require_admin(request)

    def op(conn):
        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY table_name"
        ).fetchall()
        return [dict(row) if isinstance(row, dict) else {"table_name": row[0]} for row in rows]

    tables = await database._run_db(op)
    result = []
    for t in tables:
        name = str(t["table_name"])
        try:
            count = await database._run_db(lambda conn, n=name: conn.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0])
        except Exception:
            count = None
        result.append({"table": name, "rows": count,
                       "description": _DB_TABLE_DESCRIPTIONS.get(name, "")})
    return {"paper_only": True, "tables": result}


@app.get("/api/admin/db/table")
async def admin_db_table_rows(request: Request, table: str = "", page: int = 1, page_size: int = 50):
    """Admin: seçili tablonun verilerini sayfalı döndürür."""
    _require_admin(request)
    name = str(table or "").strip()
    if not name or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
        raise HTTPException(status_code=422, detail="Geçersiz tablo adı")
    page = max(1, int(page))
    page_size = max(1, min(int(page_size), 500))
    offset = (page - 1) * page_size

    def op(conn):
        total = conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
        rows = conn.execute(f'SELECT * FROM "{name}" ORDER BY 1 DESC LIMIT %s OFFSET %s',
                            (page_size, offset)).fetchall()
        cols = [d[0] for d in (conn.execute(f'SELECT * FROM "{name}" LIMIT 0')).description]
        return {"total": int(total), "columns": cols,
                "rows": [dict(r) if isinstance(r, dict) else dict(zip(cols, r)) for r in rows]}

    try:
        return {"paper_only": True, "table": name, "page": page,
                "page_size": page_size, **await database._run_db(op)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Tablo okunamadı: {exc}")


@app.get("/api/admin/db/table/export")
async def admin_db_table_export(request: Request, table: str = "", format: str = "csv"):
    """Admin: tablo verisini CSV veya SQL (INSERT) olarak indirir."""
    _require_admin(request)
    name = str(table or "").strip()
    if not name or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
        raise HTTPException(status_code=422, detail="Geçersiz tablo adı")
    fmt = str(format or "csv").lower()
    if fmt not in {"csv", "sql"}:
        raise HTTPException(status_code=422, detail="format csv veya sql olmalı")

    def op(conn):
        rows = conn.execute(f'SELECT * FROM "{name}"').fetchall()
        cols = [d[0] for d in (conn.execute(f'SELECT * FROM "{name}" LIMIT 0')).description]
        return {"columns": cols,
                "rows": [dict(r) if isinstance(r, dict) else dict(zip(cols, r)) for r in rows]}

    try:
        data = await database._run_db(op)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Tablo okunamadı: {exc}")
    cols, rows = data["columns"], data["rows"]

    if fmt == "csv":
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            clean = {}
            for k, v in r.items():
                if isinstance(v, (dict, list)):
                    v = json.dumps(v, ensure_ascii=False, default=str)
                clean[k] = v
            writer.writerow(clean)
        content = buf.getvalue()
        media = "text/csv; charset=utf-8"
        filename = f"{name}.csv"
    else:
        lines = [f"-- {name} export {datetime.now(timezone.utc).isoformat()}"]
        for r in rows:
            vals = []
            for col in cols:
                v = r.get(col)
                if v is None:
                    vals.append("NULL")
                elif isinstance(v, (dict, list)):
                    vals.append("'" + json.dumps(v, ensure_ascii=False, default=str).replace("'", "''") + "'")
                elif isinstance(v, bool):
                    vals.append("TRUE" if v else "FALSE")
                elif isinstance(v, (int, float)):
                    vals.append(str(v))
                else:
                    vals.append("'" + str(v).replace("'", "''") + "'")
            col_list = ", ".join(f'"{cc}"' for cc in cols)
            lines.append(f'INSERT INTO "{name}" ({col_list}) VALUES ({", ".join(vals)});')
        content = "\n".join(lines)
        media = "application/sql; charset=utf-8"
        filename = f"{name}.sql"

    return Response(content=content, media_type=media, headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Length": str(len(content.encode("utf-8"))),
    })


@app.get("/api/admin/users")
async def admin_list_users(request: Request):
    _require_admin(request)
    return {"ok": True, "users": await database.list_users()}


@app.post("/api/admin/users")
async def admin_create_user(payload: dict, request: Request):
    admin = _require_admin(request)
    username = str(payload.get("username") or "").strip()
    password = str(payload.get("password") or "")
    if not username or len(username) < 3 or len(username) > 32:
        raise HTTPException(status_code=422, detail="Kullanıcı adı 3-32 karakter olmalı")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", username):
        raise HTTPException(status_code=422, detail="Kullanıcı adı yalnız harf, rakam, nokta, tire ve alt çizgi içerebilir")
    if len(password) < 6:
        raise HTTPException(status_code=422, detail="Şifre en az 6 karakter olmalı")
    existing = await database.get_user_by_username(username)
    if existing:
        raise HTTPException(status_code=409, detail="Bu kullanıcı adı zaten kayıtlı")
    role = str(payload.get("role") or "user").lower()
    if role not in {"admin", "user"}:
        raise HTTPException(status_code=422, detail="Rol 'admin' veya 'user' olmalı")
    user = await database.create_user(username, security.hash_password(password), role=role,
                                      is_active=bool(payload.get("is_active", True)))
    await log_user_action(admin.get("username"), "admin", "user", "USER_CREATE",
                          target=(user or {}).get("username") or username.lower(),
                          details={"role": role, "is_active": bool(payload.get("is_active", True))}, request=request)
    return {"ok": True, "user": _public_user(user)}


@app.put("/api/admin/users/{user_id}")
async def admin_update_user(user_id: int, payload: dict, request: Request):
    admin = _require_admin(request)
    existing = await database.get_user_by_id(user_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
    kwargs = {}
    if "username" in payload:
        username = str(payload.get("username") or "").strip()
        if not username or len(username) < 3 or len(username) > 32:
            raise HTTPException(status_code=422, detail="Kullanıcı adı 3-32 karakter olmalı")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", username):
            raise HTTPException(status_code=422, detail="Kullanıcı adı yalnız harf, rakam, nokta, tire ve alt çizgi içerebilir")
        dup = await database.get_user_by_username(username)
        if dup and int(dup["id"]) != int(user_id):
            raise HTTPException(status_code=409, detail="Bu kullanıcı adı zaten kayıtlı")
        kwargs["username"] = username
    if "password" in payload and str(payload.get("password") or "").strip():
        password = str(payload.get("password") or "")
        if len(password) < 6:
            raise HTTPException(status_code=422, detail="Şifre en az 6 karakter olmalı")
        kwargs["password_hash"] = security.hash_password(password)
    if "role" in payload:
        role = str(payload.get("role") or "user").lower()
        if role not in {"admin", "user"}:
            raise HTTPException(status_code=422, detail="Rol 'admin' veya 'user' olmalı")
        # Son admin kilitlenmesin: kendi rolünü değiştiren admin engellenir.
        if existing.get("username") == admin.get("username") and role != "admin":
            raise HTTPException(status_code=422, detail="Kendi admin rolünüzü değiştiremezsiniz")
        kwargs["role"] = role
    if "is_active" in payload:
        kwargs["is_active"] = bool(payload.get("is_active", True))
    user = await database.update_user(user_id, **kwargs)
    await log_user_action(admin.get("username"), "admin", "user", "USER_UPDATE",
                          target=(existing.get("username") or str(user_id)),
                          details={"changed": sorted(kwargs.keys()), "new_username": kwargs.get("username")}, request=request)
    return {"ok": True, "user": _public_user(user)}


@app.delete("/api/admin/users/{user_id}")
async def admin_delete_user(user_id: int, request: Request):
    admin = _require_admin(request)
    existing = await database.get_user_by_id(user_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
    if existing.get("username") == admin.get("username"):
        raise HTTPException(status_code=422, detail="Kendi hesabınızı silemezsiniz")
    if existing.get("role") == "admin":
        admins = [u for u in await database.list_users() if u.get("role") == "admin"]
        if len(admins) <= 1:
            raise HTTPException(status_code=422, detail="Son admin silinemez")
    await database.delete_user(user_id)
    await log_user_action(admin.get("username"), "admin", "user", "USER_DELETE",
                          target=existing.get("username") or str(user_id),
                          details={"role": existing.get("role")}, request=request)
    return {"ok": True, "deleted": user_id}


@app.get("/api/admin/audit-logs")
async def admin_list_audit_logs(request: Request, limit: int = 100, offset: int = 0,
                                actor: str | None = None, category: str | None = None,
                                action: str | None = None, q: str | None = None):
    """Admin-only olay kayıtları (kim, ne zaman, ne yaptı, IP, cihaz)."""
    _require_admin(request)
    logs = await database.list_audit_logs(limit, offset, actor=actor, category=category,
                                          action=action, q=q)
    total = await database.count_audit_logs(actor=actor, category=category, action=action, q=q)
    return {"ok": True, "logs": logs, "total": total, "limit": len(logs), "offset": offset}


@app.delete("/api/admin/audit-logs")
async def admin_delete_audit_logs(payload: dict = None, request: Request = None):
    """Eski olay kayıtlarını siler (varsayılan: 30 günden eski). before_ts epoch saniyedir."""
    admin = _require_admin(request)
    before_ts = float((payload or {}).get("before_ts") or 0)
    if not before_ts or before_ts > time.time():
        before_ts = time.time() - 30 * 86400
    deleted = await database.delete_audit_logs_before(before_ts)
    await log_user_action(admin.get("username"), "admin", "user", "AUDIT_LOG_PURGE",
                          details={"before_ts": before_ts, "deleted": deleted}, request=request)
    return {"ok": True, "deleted": deleted}

_pg_pool = None
_trade_repair = {"status": "idle", "phase": "idle", "progress": 0, "message": None, "logs": [], "preview": None, "result": None}




@app.get("/api/btc-5min-scan")
async def btc_5min_scan():
    raise HTTPException(status_code=410, detail="BTC_5M_ODDS_SCALPER sistemden kaldırıldı")

@app.get("/api/btc-5min-backtest")
async def btc_5min_backtest():
    raise HTTPException(status_code=410, detail="BTC_5M_ODDS_SCALPER sistemden kaldırıldı")

def _repair_log(level, message):
    _trade_repair["logs"].append({"time": time.time(), "level": level, "message": message})
    _trade_repair["logs"] = _trade_repair["logs"][-100:]

async def learning_promotion_loop():
    """Promote only evidence-backed instincts; never changes system prompts directly."""
    while True:
        try:
            if _pg_pool:
                result = await promote_validated_instincts(_pg_pool, dry_run=False)
                if result.get("promoted"):
                    print(f"[Learning] promoted instincts: {result['promoted']}")
        except Exception as exc:
            print(f"[Learning] promotion loop: {exc}")
        await asyncio.sleep(15 * 60)

async def retention_loop():
    """Periodic sweep of high-volume observability tables (paper records kept)."""
    await asyncio.sleep(120)  # let startup bursts finish before the first sweep
    while True:
        try:
            deleted = await database.prune_retention(days=int(os.getenv("RETENTION_DAYS", "30")),
                                                     microstructure_days=int(os.getenv("MICROSTRUCTURE_RETENTION_DAYS", "7")))
            if any(deleted.values()):
                print(f"[Retention] {deleted}", flush=True)
        except Exception as exc:
            print(f"[Retention] sweep hatası: {exc}")
        await asyncio.sleep(6 * 3600)

_ml_train_lock = asyncio.Lock()


async def run_ml_training(trigger: str = "scheduled"):
    """ML modelini yeniden eğitir: candle + journal örnekleri -> artifact.

    Journal satırları (doğrulanmış canlı tahmin sonuçları) ağırlıklı örnekle
    eğitime girer -> model kendi hatalarından/başarılarından pekişir.
    """
    async with _ml_train_lock:
        cutoff_ms = int((time.time() - config.ML_TRAIN_LOOKBACK_DAYS * 86400) * 1000)
        candles = await database.get_ml_training_candles(
            cutoff_ms, max_bars_per_symbol=config.ML_MAX_BARS_PER_SYMBOL)
        journal = await database.get_llm_forecasts(status="evaluated", limit=5000)
        meta = await asyncio.to_thread(ml_forecast.train, candles, journal)
        await database.save_ml_model_artifact(meta)
        print(f"[ML] eğitim ({trigger}): {meta['sample_count']} örnek, "
              f"{meta['symbol_count']} sembol, {meta['journal_sample_count']} journal örneği", flush=True)
        return meta


async def ml_training_loop():
    """Faz 1: periyodik ML eğitim döngüsü (startup + ML_TRAIN_INTERVAL_HOURS)."""
    await asyncio.sleep(300)  # startup patlaması bitsin
    try:
        await run_ml_training("startup")
    except Exception as exc:
        print(f"[ML] startup eğitimi atlandı: {exc}", flush=True)
    while True:
        await asyncio.sleep(config.ML_TRAIN_INTERVAL_HOURS * 3600)
        try:
            await run_ml_training("scheduled")
        except Exception as exc:
            print(f"[ML] eğitim hatası: {exc}", flush=True)


async def calibration_refresh_loop():
    """S3: rebuild bucketed win-rate statistics from closed trades.

    Only past trades feed today's multipliers (walk-forward-safe). Buckets
    with fewer than MIN_BUCKET_SAMPLES stay neutral.
    """
    await asyncio.sleep(180)  # let the trade history warm up
    while True:
        try:
            trades = await database.get_trades(limit=500)
            buckets = calibration_service.build_buckets(trades)
            calibration_service.store_buckets(buckets)
            informative = sum(1 for s in buckets.values() if s["samples"] >= calibration_service.MIN_BUCKET_SAMPLES)
            print(f"[Calibration] {len(buckets)} kova, {informative} karar-verebilir", flush=True)
        except Exception as exc:
            print(f"[Calibration] yenileme hatası: {exc}")
        await asyncio.sleep(7 * 24 * 3600)


async def _ensure_admin_user():
    """Admin kullanıcıyı DB'ye tohumla (yoksa). Şifre: SCALPER_ADMIN_PASSWORD env'i."""
    if await database.count_users() > 0:
        return
    password = os.getenv("SCALPER_ADMIN_PASSWORD", "").strip()
    if not password:
        raise RuntimeError(
            "SCALPER_ADMIN_PASSWORD ortam değişkeni tanımlı değil. "
            "Admin kullanıcı oluşturulamaz. Lütfen .env dosyasında güçlü bir şifre tanımlayın."
        )
    await database.create_user("admin", security.hash_password(password), role="admin", is_active=True)
    print("[Auth] admin kullanıcı oluşturuldu (şifre env'den)", flush=True)


async def startup_services():
    global _pg_pool
    await database.init_db()
    try:
        await _ensure_admin_user()
    except Exception as exc:
        print(f"[Auth] admin kullanıcı tohumlama hatası: {exc}", flush=True)
    try:
        repair = await database.fix_upside_scout_units()
        if any(repair.values()):
            print(f"[UpsideScout] birim onarımı: {repair}", flush=True)
    except Exception as exc:
        print(f"[UpsideScout] birim onarımı atlandı: {exc}")
    await database.ensure_default_scalper_skill()
    saved_config = await database.get_llm_setting("runtime_config")
    if saved_config:
        try:
            persisted = json.loads(saved_config)
            for key, attr in CONFIG_FIELDS.items():
                if key in persisted: setattr(config, attr, persisted[key])
            if persisted.get("symbols"):
                config.SYMBOLS = list(persisted["symbols"])
        except Exception as exc:
            print(f"[Config] Kalıcı ayarlar yüklenemedi: {exc}")
    await analyzer.load_state()
    await bootstrap_symbol_activity()
    if os.getenv("DB_BACKEND", "postgres").lower() == "postgres" and asyncpg and os.getenv("DATABASE_URL"):
        try:
            _pg_pool = await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=4)
            set_runtime_pool(_pg_pool)
            await embedding_worker.start(_pg_pool, llm_analysis.embedding)
        except Exception as exc:
            print(f"[Memory] PostgreSQL/embedding worker başlatılamadı: {exc}")
    # Strategy loop yalnızca tüm timeframe geçmişi ve REST ticker'ları hazır
    # olduktan sonra başlasın; aksi halde ilk tarama tüm sembolleri stale sayar.
    priority_timeframes = list(dict.fromkeys([
    ]))
    await market.fetch_historical_data(priority_timeframes)
    print(f"[MarketData] öncelikli strateji verisi hazır | timeframes={priority_timeframes} tickers={len(market.tickers)}", flush=True)
    _start_background(backfill_missing_active_history(), "historical-backfill-active")
    _start_background(history_candle_loop(), "history-candle-loop")
    _start_background(market.connect(skip_history=True), "market-connect")
    _start_background(microstructure_snapshot_loop(), "microstructure-snapshot")
    _start_background(strategy_loop(), "strategy-loop")
    _start_background(llm_forecast_evaluation_loop(), "llm-forecast-evaluator")
    _start_background(chart_forecast_evaluation_loop(), "chart-forecast-evaluator")
    _start_background(chat_prediction_learning_loop(), "chat-prediction-learner")
    _start_background(chat_prediction_auto_trade_loop(), "chat-prediction-auto-trade")
    _start_background(velocity_learning_loop(), "velocity-learner")
    _start_background(autonomous_velocity_loop(), "velocity-auto-trader")
    _start_background(radar_loop(), "radar-loop")
    _start_background(top_gainers_refresh_loop(), "top-gainers-monitor")
    _start_background(symbol_activity_loop(), "symbol-activity")
    _start_background(llm_idle_trigger_loop(), "llm-idle-trigger")
    _start_background(llm_position_manager_loop(), "llm-position-manager")
    _start_background(learning_promotion_loop(), "learning-promotion")
    _start_background(retention_loop(), "retention")
    _start_background(ml_training_loop(), "ml_training")
    _start_background(calibration_refresh_loop(), "calibration-refresh")
    _start_background(correlation_refresh_loop(), "correlation-refresh")
    _start_background(ws_broadcast_loop(), "ws-broadcast")
    _start_background(alert_loop(), "alert-engine")
    _start_background(monitoring_start_loop(), "monitoring-start")

async def monitoring_start_loop():
    """Monitoring tarama döngüsünü arka planda başlat (idempotent wrapper)."""
    try:
        monitoring.start_monitoring_loop()
    except Exception as exc:
        print(f"[Monitoring] döngü başlatılamadı: {exc}", flush=True)


async def shutdown_services():
    market.stop()
    try:
        await microflow.stop()
    except Exception:
        pass
    try:
        monitoring.stop_monitoring_loop()
    except Exception:
        pass
    tasks = list(_background_tasks)
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    _background_tasks.clear()
    await embedding_worker.stop()
    if _pg_pool:
        await _pg_pool.close()
    await database.close_db()


@asynccontextmanager
async def app_lifespan(_app):
    await startup_services()
    try:
        yield
    finally:
        await shutdown_services()


app.router.lifespan_context = app_lifespan

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    if not security.auth_configured() or not security.request_authenticated(
        websocket.headers, websocket.cookies, websocket.query_params.get("token")
    ):
        await websocket.close(code=4401)
        return
    await ws_manager.connect(websocket)
    try:
        while True: await websocket.receive_text()
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        await ws_manager.disconnect(websocket)

@app.get("/api/alerts")
async def get_alerts(active_only: bool = False):
    return {"alerts": await database.list_alert_rules(active_only=active_only), "events": await database.get_alert_events(100), "paper_only": True}

@app.get("/api/strategy/breaker")
async def strategy_breaker_status():
    """Circuit-breaker pause state per strategy (paper-only safety layer)."""
    return {"paused": strategy_breaker.status(), "paper_only": True}

@app.get("/api/strategy/calibration")
async def strategy_calibration():
    """S3 bucketed win-rate table (walk-forward-safe, past trades only)."""
    state = calibration_service.bucket_state()
    buckets = state.get("buckets") or {}
    return {"buckets": calibration_service.summarize_for_ui(buckets),
            "total_buckets": len(buckets),
            "updated_at": state.get("updated_at"),
            "min_samples": calibration_service.MIN_BUCKET_SAMPLES,
            "paper_only": True}

@app.get("/api/strategy/correlation")
async def strategy_correlation():
    """S5 BTC/ETH rolling correlations and current cluster exposure."""
    exposure = await correlation_exposure_status()
    return {"correlations": correlation_monitor.snapshot(),
            "last_updated": correlation_monitor.last_updated,
            "exposure": exposure,
            "cap_pct": config.MAX_CLUSTER_EXPOSURE_PCT if config.CORRELATION_CAP_ENABLED else None,
            "paper_only": True}

@app.get("/api/strategy/pipeline")
async def strategy_pipeline_status():
    """S7 candidate-strategy promotion pipeline state."""
    await promotion_pipeline._ensure()
    return {"strategies": promotion_pipeline.status(), "paper_only": True}

@app.post("/api/strategy/pipeline/register")
async def strategy_pipeline_register(payload: dict):
    name = str((payload or {}).get("name") or "").strip()
    stage = str((payload or {}).get("stage") or "shadow")
    if not name:
        raise HTTPException(status_code=400, detail="name gerekli")
    entry = await promotion_pipeline.register(name, stage=stage)
    return {"ok": True, "name": name, **entry, "paper_only": True}

@app.post("/api/strategy/pipeline/promote")
async def strategy_pipeline_promote(payload: dict):
    """Attempt one gated advance. active stage requires human_approved=true."""
    body = payload or {}
    name = str(body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name gerekli")

    def _num(key):
        value = body.get(key)
        return float(value) if value is not None else None
    result = await promotion_pipeline.promote(
        name,
        shadow_observations=int(body["shadow_observations"]) if body.get("shadow_observations") is not None else None,
        walk_forward_pass=bool(body.get("walk_forward_pass")),
        paper_trades=int(body["paper_trades"]) if body.get("paper_trades") is not None else None,
        paper_expectancy=_num("paper_expectancy"),
        human_approved=bool(body.get("human_approved")))
    return {"ok": True, "name": name, **result, "paper_only": True}

@app.get("/api/strategy/universe-history")
async def strategy_universe_history(limit: int = 48):
    """S7a point-in-time universe snapshots (survivorship-bias-free research)."""
    try:
        raw = await database.get_llm_setting("symbol_universe_history", "[]")
        history = json.loads(raw or "[]")
    except (ValueError, TypeError):
        history = []
    safe_limit = max(1, min(int(limit), 500))
    return {"history": history[-safe_limit:], "total": len(history), "paper_only": True}

@app.post("/api/strategy/breaker/resume")
async def strategy_breaker_resume(payload: dict = None):
    """Human-approved resume of a paused strategy. Nothing auto-resumes."""
    strategy = str((payload or {}).get("strategy") or "").strip()
    if not strategy:
        raise HTTPException(status_code=400, detail="strategy gerekli")
    if not await strategy_breaker.resume(strategy):
        raise HTTPException(status_code=404, detail=f"{strategy} duraklatılmamış")
    await database.save_signal({"symbol": "*", "action": "STRATEGY_RESUMED",
                                "reason": f"{strategy} manuel olarak devam ettirildi",
                                "strategy": strategy, "timestamp": time.time()})
    return {"ok": True, "strategy": strategy, "resumed": True, "paper_only": True}

@app.post("/api/alerts")
async def create_alert(payload: dict, request: Request):
    required = ["symbol", "operator", "threshold"]
    if any(key not in payload for key in required): raise HTTPException(400, "symbol, operator ve threshold gerekli")
    if str(payload.get("rule_type", "price")) not in {"price", "percent"}: raise HTTPException(400, "Desteklenmeyen alarm türü")
    try:
        float(payload.get("threshold"))
        if payload.get("rearm_threshold") is not None: float(payload.get("rearm_threshold"))
    except (TypeError, ValueError):
        raise HTTPException(400, "threshold ve rearm_threshold sayısal olmalıdır")
    if str(payload.get("operator", "")).lower() not in {"lt", "lte", "gt", "gte", "eq"}:
        raise HTTPException(400, "operator lt, lte, gt, gte veya eq olmalıdır")
    cooldown = payload.get("cooldown_seconds")
    if cooldown is not None and (not isinstance(cooldown, (int, float)) or cooldown < 0):
        raise HTTPException(400, "cooldown_seconds negatif olmayan bir sayı olmalıdır")
    rule_id = await database.create_alert_rule({**payload, "created_by": payload.get("created_by", "user")})
    actor = _session_username(request)
    await log_user_action(actor, None, "alert", "ALERT_CREATE",
                          target=str(payload.get("symbol") or "").upper() or None,
                          details={"rule_id": rule_id, "operator": payload.get("operator"),
                                   "threshold": payload.get("threshold"), "rule_type": payload.get("rule_type", "price")},
                          request=request)
    return {"ok": True, "id": rule_id, "paper_only": True}

@app.patch("/api/alerts/{alert_id}")
async def update_alert(alert_id: int, payload: dict, request: Request):
    actor = _session_username(request)
    await log_user_action(actor, None, "alert", "ALERT_UPDATE",
                          target=str(alert_id), details={"changed_keys": sorted(payload.keys())}, request=request)
    return {"ok": True, "alert": await database.update_alert_rule(alert_id, payload), "paper_only": True}

@app.delete("/api/alerts/{alert_id}")
async def delete_alert(alert_id: int, request: Request):
    actor = _session_username(request)
    await log_user_action(actor, None, "alert", "ALERT_DELETE", target=str(alert_id), request=request)
    return {"ok": await database.delete_alert_rule(alert_id), "paper_only": True}

@app.post("/api/alerts/push-subscription")
async def save_alert_push_subscription(payload: dict):
    return {"ok": await database.save_push_subscription(payload), "paper_only": True}

CONFIG_FIELDS = {
    "top_gainers_auto_activate": "TOP_GAINERS_AUTO_ACTIVATE",
    "top_gainers_limit": "TOP_GAINERS_LIMIT",
    "top_gainers_refresh_sec": "TOP_GAINERS_REFRESH_SEC",
    "gainer_radar_min_score": "GAINER_RADAR_MIN_SCORE",
    "min_notional": "MIN_NOTIONAL",
    "min_24h_quote_volume_try": "MIN_24H_QUOTE_VOLUME_TRY",
    "high_liquidity_bypass_volume_try": "HIGH_LIQUIDITY_BYPASS_VOLUME_TRY",
    "min_volume_ratio": "MIN_VOLUME_RATIO",
    "min_orderbook_depth_multiplier": "MIN_ORDERBOOK_DEPTH_MULTIPLIER",
    "liquidity_filter_enabled": "LIQUIDITY_FILTER_ENABLED",
    "default_order_usdt": "DEFAULT_ORDER_USDT",
    "order_pct": "ORDER_PCT",
    "symbol_activity_m1_flat_filter_enabled": "SYMBOL_ACTIVITY_M1_FLAT_FILTER_ENABLED",
    "symbol_activity_m1_flat_max_range_pct": "SYMBOL_ACTIVITY_M1_FLAT_MAX_RANGE_PCT",
    "symbol_activity_m1_flat_5m_max_count": "SYMBOL_ACTIVITY_M1_FLAT_5M_MAX_COUNT",
    "symbol_activity_m1_flat_30m_max_count": "SYMBOL_ACTIVITY_M1_FLAT_30M_MAX_COUNT",
    "symbol_order_pct": "SYMBOL_ORDER_PCT",
    "max_open_positions": "MAX_OPEN_POSITIONS",
    "take_profit_pct": "SPOT_PROFIT_TARGET_PCT",
    "hard_stop_loss_pct": "HARD_STOP_LOSS_PCT",
    "cooldown_bars": "COOLDOWN_BARS",
}



BOOL_FIELDS = {"top_gainers_auto_activate", "liquidity_filter_enabled", "symbol_activity_m1_flat_filter_enabled"}
DISABLED_LIVE_STRATEGY_FIELDS = set()
INT_FIELDS = {"top_gainers_limit", "top_gainers_refresh_sec", "gainer_radar_min_score", "max_open_positions", "cooldown_bars", "symbol_activity_m1_flat_5m_max_count", "symbol_activity_m1_flat_30m_max_count"}
STR_FIELDS = set()


@app.get("/api/config")
async def get_config():
    return {
        "top_gainers_auto_activate": config.TOP_GAINERS_AUTO_ACTIVATE,
        "top_gainers_limit": config.TOP_GAINERS_LIMIT,
        "top_gainers_refresh_sec": config.TOP_GAINERS_REFRESH_SEC,
        "gainer_radar_min_score": config.GAINER_RADAR_MIN_SCORE,
        "symbols": config.SYMBOLS,
        "min_notional": config.MIN_NOTIONAL,
        "min_24h_quote_volume_try": config.MIN_24H_QUOTE_VOLUME_TRY,
        "high_liquidity_bypass_volume_try": config.HIGH_LIQUIDITY_BYPASS_VOLUME_TRY,
        "min_volume_ratio": config.MIN_VOLUME_RATIO,
        "min_orderbook_depth_multiplier": config.MIN_ORDERBOOK_DEPTH_MULTIPLIER,
        "liquidity_filter_enabled": config.LIQUIDITY_FILTER_ENABLED,
        "default_order_usdt": config.DEFAULT_ORDER_USDT,
        "order_pct": config.ORDER_PCT,
        "symbol_order_pct": config.SYMBOL_ORDER_PCT,
        "symbol_activity_m1_flat_filter_enabled": config.SYMBOL_ACTIVITY_M1_FLAT_FILTER_ENABLED,
        "symbol_activity_m1_flat_max_range_pct": config.SYMBOL_ACTIVITY_M1_FLAT_MAX_RANGE_PCT,
        "symbol_activity_m1_flat_5m_max_count": config.SYMBOL_ACTIVITY_M1_FLAT_5M_MAX_COUNT,
        "symbol_activity_m1_flat_30m_max_count": config.SYMBOL_ACTIVITY_M1_FLAT_30M_MAX_COUNT,
        "max_open_positions": int(config.MAX_OPEN_POSITIONS),
        "hard_stop_loss_pct": config.HARD_STOP_LOSS_PCT,
        "cooldown_bars": config.COOLDOWN_BARS,
        "take_profit_pct": config.SPOT_PROFIT_TARGET_PCT,
        "trailing_stop_pct": 0.0,
        "initial_balance_try": config.INITIAL_BALANCE_TRY,
        "mode": "paper",
        "market_data": "public",
    }

@app.get("/api/market-symbols")
async def get_market_symbols():
    try:
        return {"symbols": await trading_symbols("TRY"), "quote_asset": "TRY"}
    except Exception as exc:
        return {"symbols": [], "quote_asset": "TRY", "error": str(exc)}

@app.get("/api/market-klines/{symbol}")
async def get_market_klines(symbol: str, interval: str = "5m", limit: int = 200):
    """Single public market-data adapter used by all UI candle consumers."""
    if interval not in {"1m", "5m", "15m", "30m", "1h", "4h", "1d"}:
        raise HTTPException(status_code=400, detail="Geçersiz timeframe")
    rows = await fetch_klines(symbol, interval, limit=max(20, min(int(limit), 500)))
    return {"symbol": symbol.replace("_", "").upper(), "interval": interval,
            "candles": rows, "source": "binance_tr_public"}

@app.get("/api/radar/gainers")
async def gainers_radar(execute: bool = False):
    """Coalesce concurrent dashboard and background radar scans.

    Public radar data is already sampled on a 30-second cadence.  A short
    response cache prevents multiple open browser tabs from redoing the same
    multi-timeframe work while execution requests always get a fresh run.
    """
    now = time.time()
    cached = _radar_response_cache.get("result")
    if not execute and cached and now - float(_radar_response_cache.get("generated_at") or 0) < 5:
        return cached
    async with _radar_lock:
        now = time.time()
        cached = _radar_response_cache.get("result")
        if not execute and cached and now - float(_radar_response_cache.get("generated_at") or 0) < 5:
            return cached
        result = await _gainers_radar_uncached(execute=execute)
        _radar_response_cache.clear()
        _radar_response_cache.update({"generated_at": time.time(), "result": result})
        return result


async def _gainers_radar_uncached(execute: bool = False):
    """Public-data fırsat tarayıcı: pump kovalamaz, devam edebilecek %2 adaylarını sıralar."""
    rows = []
    radar_analyzer = ScalpAnalyzer(None)
    auto_added = []
    try:
        all_tickers = await ticker_24h()
        known_try = set(await trading_symbols("TRY"))
        gainer_candidates = []
        for item in all_tickers:
            symbol = str(item.get("symbol", "")).upper()
            change = float(item.get("priceChangePercent", 0) or 0)
            quote_volume = float(item.get("quoteVolume", 0) or 0)
            if symbol in known_try and 3 <= change <= 18 and quote_volume >= config.MIN_24H_QUOTE_VOLUME_TRY:
                gainer_candidates.append((change, quote_volume, symbol))
        for _, _, symbol in sorted(gainer_candidates, reverse=True)[:10]:
            if symbol not in config.SYMBOLS:
                config.SYMBOLS.append(symbol)
                if symbol.lower() not in market.symbols:
                    market.symbols.append(symbol.lower())
                    market.reconnect_requested = True
                auto_added.append(symbol)
    except Exception as exc:
        print(f"[Radar] gainer tarama hatası: {exc}")
    for symbol in config.SYMBOLS:
        bars = market.get_ut_kline(symbol, "5m")
        closes, volumes = bars.get("closes", []), bars.get("volumes", [])
        if len(closes) < 25 or len(volumes) < 25:
            continue
        price = closes[-1]
        ret_5m = (closes[-1] / closes[-2] - 1) * 100
        ret_1h = (closes[-1] / closes[-13] - 1) * 100 if len(closes) >= 13 else 0
        ret_24h = (closes[-1] / closes[0] - 1) * 100
        avg_volume = sum(volumes[-21:-1]) / 20
        volume_ratio = volumes[-1] / avg_volume if avg_volume else 0
        flow = market.get_orderflow(symbol)
        bid, ask = flow.get("bid_qty", 0), flow.get("ask_qty", 0)
        imbalance = ((bid - ask) / (bid + ask) * 100) if bid + ask else 0
        ema9 = sum(closes[-9:]) / 9
        ema21 = sum(closes[-21:]) / 21
        trend = price > ema9 > ema21
        crsi = radar_analyzer.calculate_crsi(closes)
        crsi_score = 10 if crsi is not None and 20 <= crsi <= 75 else 0
        score = 0
        score += min(max(volume_ratio / 2, 0), 20)
        score += min(max(imbalance, 0), 25)
        score += 20 if trend else 0
        score += min(max(ret_1h * 3, 0), 15)
        score += crsi_score
        eligible = 3 <= ret_24h <= 18 and ret_1h > 0 and volume_ratio >= 2.0 and crsi is not None and 20 <= crsi <= 80 and score >= config.GAINER_RADAR_MIN_SCORE
        rows.append({"symbol": symbol, "price": price, "score": round(score, 1), "eligible": eligible,
                     "ret_5m": round(ret_5m, 2), "ret_1h": round(ret_1h, 2), "ret_24h": round(ret_24h, 2),
                     "volume_ratio": round(volume_ratio, 2), "imbalance": round(imbalance, 2), "trend": trend, "crsi": round(crsi, 2) if crsi is not None else None})
    # Soft MTF priority: this is a ranking aid, not a BUY filter.  A gainer
    # must still pass the existing liquidity, momentum and cost-aware rules.
    # Use the hot cache here so the 30-second radar refresh does not fan out
    # into five REST requests per symbol.
    mtf_timeframes = ["1m", "5m", "15m", "1h", "4h"]
    mtf_weights = {"1m": 0.10, "5m": 0.20, "15m": 0.25, "1h": 0.25, "4h": 0.20}
    for row in rows:
        states = {}
        weighted_score = 0.0
        bullish_count = 0
        for tf in mtf_timeframes:
            closes = list((market.get_ut_kline(row["symbol"], tf) or {}).get("closes", []))
            state = "unknown"
            tf_score = 0.0
            if len(closes) >= 55:
                ema9 = radar_analyzer.calculate_ema(closes, 9)
                ema21 = radar_analyzer.calculate_ema(closes, 21)
                ema50 = radar_analyzer.calculate_ema(closes, 50)
                previous_ema9 = radar_analyzer.calculate_ema(closes[:-1], 9)
                price = closes[-1]
                rising = ema9 > previous_ema9
                if price > ema9 > ema21 > ema50 and rising:
                    state, tf_score = "bullish", 100.0
                    bullish_count += 1
                elif price > ema21 and ema9 > ema21:
                    state, tf_score = "mixed", 50.0
                else:
                    state = "bearish"
            states[tf] = state
            weighted_score += mtf_weights[tf] * tf_score
        row["mtf"] = states
        row["mtf_bullish_count"] = bullish_count
        bearish_count = sum(state == "bearish" for state in states.values())
        row["mtf_bearish_count"] = bearish_count
        row["mtf_alignment_score"] = bullish_count - bearish_count
        row["mtf_score"] = round(weighted_score, 1)
        row["mtf_bullish_rank"] = ">".join(tf for tf in mtf_timeframes if states[tf] == "bullish") or "—"
        mtf_bonus = (config.GAINER_RADAR_MTF_PRIORITY_MAX_BONUS if bullish_count >= 3
                     else config.GAINER_RADAR_MTF_PRIORITY_MAX_BONUS / 2 if bullish_count >= 2 else 0.0)
        row["mtf_priority_bonus"] = round(mtf_bonus, 1)
        row["priority_score"] = round(row["score"] * 0.70 + weighted_score * 0.30 + mtf_bonus, 1)
    rows.sort(key=lambda row: (row["priority_score"], row["score"]), reverse=True)
    radar_trades = []
    if execute and config.GAINER_RADAR_AUTO_TRADE:
        for candidate in [row for row in rows if row["eligible"]][:1]:
            symbol = candidate["symbol"]
            ticker = market.get_ticker(symbol)
            if ticker and symbol not in analyzer.positions:
                bars = market.get_ut_kline(symbol, "5m")
                closes = bars.get("closes", [])
                rsi = radar_analyzer.calculate_rsi(closes, 14) if closes else None
                macd, macd_signal, hist = radar_analyzer.calculate_macd(closes, 12, 26, 9) if closes else (None, None, None)
                if macd is not None and hist is not None and macd > macd_signal and hist > 0 and rsi is not None and rsi < 70:
                    eligible, _ = await analyzer.entry_liquidity_preflight(symbol, "GAINER_RADAR")
                    if not eligible:
                        continue
                    signal = await analyzer.open_position(symbol, ticker["last_price"], "LONG", "GAINER_RADAR")
                    if signal and signal.get("action") == "BUY_SIGNAL":
                        radar_trades.append(signal)
                        await ws_manager.broadcast({"type": "signal", "data": signal})
    _radar_snapshot.clear()
    _radar_snapshot.update({
        "generated_at": time.time(),
        "items": {str(row.get("symbol", "")).upper(): dict(row) for row in rows},
    })
    return {"items": rows[:20], "auto_added": auto_added, "symbols": config.SYMBOLS, "paper_trades": radar_trades,
            "auto_trade": False, "generated_at": time.time(), "model": "public_data_continuation_2pct_mtf_priority",
            "mtf_timeframes": mtf_timeframes, "mtf_policy": "M1/M5/M15/H1/H4 weighted score plus bullish-count soft bonus; ranking only, never a BUY blocker; unknown data is not treated as bullish"}

@app.get("/api/market/top-gainers")
async def top_gainers_status(refresh: bool = False):
    """Return/optionally refresh the hourly Binance TR top-gainer activation set."""
    if refresh:
        try:
            return await refresh_top_gainer_symbols()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Binance TR top-gainer verisi alınamadı: {exc}")
    persisted = await database.get_llm_setting("runtime_config", "{}")
    try:
        runtime = json.loads(persisted or "{}")
    except json.JSONDecodeError:
        runtime = {}
    return {"ok": True, "enabled": config.TOP_GAINERS_AUTO_ACTIVATE,
            "limit": config.TOP_GAINERS_LIMIT, "refresh_seconds": config.TOP_GAINERS_REFRESH_SEC,
            "refresh_minutes": config.TOP_GAINERS_REFRESH_SEC // 60,
            "symbols": config.SYMBOLS, "refreshed_at": runtime.get("top_gainers_refreshed_at"),
            "source": "binance_tr_public_24h_ticker"}

@app.get("/api/symbol-activity")
async def symbol_activity_status():
    raw = await database.get_llm_setting("symbol_activity_status", "{}")
    try:
        statuses = json.loads(raw or "{}")
    except json.JSONDecodeError:
        statuses = {}
    return {"ok": True, "statuses": statuses,
            "active_count": sum(1 for item in statuses.values() if item.get("status") == "ACTIVE"),
            "passive_count": sum(1 for item in statuses.values() if item.get("status") == "PASSIVE"),
            "warming_count": sum(1 for item in statuses.values() if item.get("status") == "WARMING"),
            "refresh_seconds": config.SYMBOL_ACTIVITY_REFRESH_SEC,
            "thresholds": {"min_quote_volume_try": config.SYMBOL_ACTIVITY_MIN_QUOTE_VOLUME_TRY,
                           "min_range_15m_pct": config.SYMBOL_ACTIVITY_MIN_RANGE_15M_PCT,
                           "min_atr_pct": config.SYMBOL_ACTIVITY_MIN_ATR_PCT * 100,
                           "min_volume_ratio": config.SYMBOL_ACTIVITY_MIN_VOLUME_RATIO,
                           "volume_only": config.SYMBOL_ACTIVITY_VOLUME_ONLY}}

@app.post("/api/symbol-activity/refresh")
async def refresh_symbol_activity_manual():
    """User-triggered public-data activity refresh; paper positions only."""
    try:
        result = await refresh_symbol_activity()
        await ws_manager.broadcast({"type": "symbol_activity", "data": result})
        return result
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Aktivasyon kontrolü başarısız: {exc}")

@app.post("/api/radar/execute")
async def execute_gainers_radar():
    return await gainers_radar(execute=True)


def _session_username(request) -> str | None:
    """Aktif oturumdaki kullanıcı adı (kayıt için); None ise kayıt atlanır."""
    if request is None:
        return None
    try:
        user = security.request_user(request.headers, request.cookies)
    except Exception:
        return None
    return (user or {}).get("username")


@app.put("/api/config")
async def update_config(payload: dict, request: Request):
    """Persist runtime settings while always preserving the JSON API contract."""
    try:
        return await _apply_config_update(payload, request)
    except (TypeError, ValueError) as exc:
        return JSONResponse(
            status_code=422,
            content={"detail": str(exc), "code": "invalid_configuration"},
        )
    except RuntimeError as exc:
        # Symbol validation and persistence can depend on temporarily unavailable
        # services. Return a JSON response so clients never try to parse a plain
        # Starlette "Internal Server Error" page as JSON.
        print(f"[Config] ayarlar kaydedilemedi: {exc}", flush=True)
        return JSONResponse(
            status_code=503,
            content={
                "detail": "Ayarlar şu anda kaydedilemedi; lütfen tekrar deneyin.",
                "code": "settings_service_unavailable",
            },
        )
    except Exception as exc:
        # Do not expose database/provider internals, but keep the frontend API
        # response parseable and log the cause for server-side diagnosis.
        print(f"[Config] beklenmeyen ayar kaydetme hatası: {exc}", flush=True)
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Ayarlar kaydedilirken beklenmeyen bir hata oluştu.",
                "code": "settings_save_failed",
            },
        )


async def _apply_config_update(payload: dict, request: Request = None):
    payload = dict(payload or {})
    previous_symbols = set(config.SYMBOLS)
    for key, attr in CONFIG_FIELDS.items():
        if key in payload:
            val = payload[key]
            if key == "symbol_order_pct":
                if not isinstance(val, dict):
                    raise ValueError(f"{key} nesne olmalıdır")
                cleaned = {}
                for symbol, raw in val.items():
                    name = str(symbol).replace("_", "").upper()
                    number = float(raw)
                    if not 0 < number <= 1: raise ValueError(f"{name} işlem yüzdesi 0 ile 1 arasında olmalıdır")
                    cleaned[name] = number
                setattr(config, attr, cleaned)
                continue
            if key in BOOL_FIELDS:
                if key in DISABLED_LIVE_STRATEGY_FIELDS:
                    # Gainer Radar and LLM_PAPER are the only live entry sources.
                    setattr(config, attr, False)
                    continue
                if isinstance(val, str):
                    val = val.strip().lower() in {"1", "true", "yes", "on"}
                setattr(config, attr, bool(val))
            elif key in INT_FIELDS:
                number = int(val)
                if key == "top_gainers_limit" and not 1 <= number <= 50:
                    raise ValueError("top_gainers_limit 1 ile 50 arasında olmalıdır")
                if key == "top_gainers_refresh_sec" and not 60 <= number <= 3600:
                    raise ValueError("top_gainers_refresh_sec 60 ile 3600 saniye arasında olmalıdır")
                if key == "max_open_positions" and not 0 <= number <= 500:
                    raise ValueError("max_open_positions 0 (sınırsız) ile 500 arasında olmalıdır")
                if key == "gainer_radar_min_score" and not 0 <= number <= 100:
                    raise ValueError("gainer_radar_min_score 0 ile 100 arasında olmalıdır")
                if key == "symbol_activity_m1_flat_5m_max_count" and not 1 <= number <= 5:
                    raise ValueError("5 dk düz M1 mum eşiği 1 ile 5 arasında olmalıdır")
                if key == "symbol_activity_m1_flat_30m_max_count" and not 1 <= number <= 30:
                    raise ValueError("30 dk düz M1 mum eşiği 1 ile 30 arasında olmalıdır")
                setattr(config, attr, number)
            elif key in STR_FIELDS:
                setattr(config, attr, str(val))
            else:
                number = float(val)
                if key in {"min_notional", "default_order_usdt", "min_24h_quote_volume_try", "high_liquidity_bypass_volume_try", "min_volume_ratio", "min_orderbook_depth_multiplier"} and number <= 0:
                    raise ValueError(f"{key} pozitif olmalıdır")
                if key == "order_pct" and not 0 < number <= 1:
                    raise ValueError("order_pct 0 ile 1 arasında olmalıdır")
                if key == "symbol_activity_m1_flat_max_range_pct" and not 0 <= number <= 5:
                    raise ValueError("M1 düz mum maksimum aralığı yüzde 0 ile 5 arasında olmalıdır")
                setattr(config, attr, number)
    if "symbols" in payload:
        symbols = sorted({str(s).replace("_", "").upper() for s in payload["symbols"] if str(s).strip()})
        allowed = set(await trading_symbols("TRY"))
        invalid = sorted(set(symbols) - allowed)
        # The settings page submits its whole draft.  A symbol may turn BREAK
        # between page load and save; do not let that stale item block valid
        # selections such as HEMITRY.  It must nevertheless be removed from
        # the scan universe, never retained as an untradeable hidden symbol.
        if invalid:
            symbols = [symbol for symbol in symbols if symbol in allowed]
        if not symbols:
            if invalid:
                raise ValueError(f"Binance TR'de işlemde olan TRY sembolü kalmadı: {', '.join(invalid)}")
            raise ValueError("En az bir aktif sembol seçilmelidir")
        payload["symbols"] = symbols
        config.SYMBOLS = symbols
        # Per-symbol overrides for delisted/BREAK pairs cannot affect a
        # future scan or a later save.
        config.SYMBOL_ORDER_PCT = {symbol: value for symbol, value in config.SYMBOL_ORDER_PCT.items() if symbol in symbols}
        market.symbols = [s.lower() for s in symbols]
        for symbol in sorted(set(symbols) - previous_symbols):
            _start_background(backfill_symbol_history(symbol), f"history-backfill-{symbol}", single_pass=True)
    # Only a symbol/timeframe change requires a full WS reconnect + REST
    # re-warm; an unrelated toggle (e.g. a bool) must not halt trading with
    # hundreds of blocking fetches and a stale-ticker gap.
    universe_changed = bool(market.reconnect_requested) or (
        "symbols" in payload and
        {str(s).lower() for s in payload["symbols"]} != {str(s).lower() for s in previous_symbols})
    market.timeframes = market._all_timeframes()
    if universe_changed:
        # Apply symbol/timeframe changes immediately. Settings are runtime-only,
        # but the running websocket/cache must not continue using the old universe.
        market.reconnect_requested = True
        await market.fetch_historical_data()
    else:
        await market.repair_history_gaps()
    analyzer._last_signal_lengths.clear()
    existing = await database.get_llm_setting("runtime_config", "{}")
    try: persisted = json.loads(existing or "{}")
    except json.JSONDecodeError: persisted = {}
    await database.set_llm_setting("runtime_config", json.dumps(persisted, ensure_ascii=False))
    if config.TOP_GAINERS_AUTO_ACTIVATE and any(
        key in payload for key in ("top_gainers_auto_activate", "top_gainers_limit", "top_gainers_refresh_sec")
    ):
        _start_background(refresh_top_gainer_symbols(), "top-gainers-config-refresh", single_pass=True)
    updated = await get_config()
    if "symbols" in payload and invalid:
        updated["removed_invalid_symbols"] = invalid
    actor = _session_username(request)
    await log_user_action(actor, None, "config", "CONFIG_UPDATE",
                          target=actor,
                          details={"changed_keys": sorted(k for k in payload if k in CONFIG_FIELDS or k == "symbols"),
                                   "universe_changed": universe_changed},
                          request=request)
    return updated

@app.post("/api/portfolio/reconcile")
async def reconcile_portfolio(payload: dict = None, request: Request = None):
    _require_admin(request)
    if not (payload or {}).get("confirm", False):
        return {"status": "preview", **await database.preview_portfolio_reconcile()}
    result = await database.reconcile_portfolio()
    # The reconciliation mutates the persistent position set. Keep the
    # long-running analyzer in sync immediately; otherwise its next portfolio
    # broadcast can resurrect positions that were just removed from the DB.
    for item in result.get("removed_overallocated_positions", []):
        analyzer.positions.pop(str(item.get("symbol", "")).upper(), None)
    await ws_manager.broadcast({"type": "portfolio_reconciled", "data": result})
    return {"status": "ok", **result}

@app.get("/api/trade-repair/status")
async def trade_repair_status():
    return dict(_trade_repair)

@app.post("/api/trade-repair/preview")
async def trade_repair_preview():
    if _trade_repair["status"] == "running":
        return {"ok": False, **_trade_repair}
    _trade_repair.update({"status":"preview", "phase":"audit", "progress":10, "message":"Geçmiş işlem bağlantıları denetleniyor", "logs":[], "result":None})
    _repair_log("info", "Salt-okunur onarım önizlemesi başlatıldı")
    preview = await database.preview_trade_repair()
    _trade_repair.update({"progress":100, "message":"Önizleme tamamlandı", "preview":preview})
    _repair_log("info", f"Önizleme tamamlandı: {preview['actions']['assign_trade_ids']} bağlantı adayı")
    return {"ok":True, **_trade_repair}

@app.post("/api/trade-repair/apply")
async def trade_repair_apply(payload: dict = None, request: Request = None):
    _require_admin(request)
    body = payload or {}
    if body.get("confirm") is not True:
        raise HTTPException(status_code=400, detail="Onarım için confirm=true gerekli")
    preview = await database.preview_trade_repair()
    _trade_repair.update({"status":"running", "phase":"apply", "progress":15, "message":"Onaylı deterministik onarım uygulanıyor", "preview":preview, "result":None, "logs":[]})
    _repair_log("warning", "Kullanıcı onayı alındı; yalnızca silme yapmayan onarım çalışıyor")
    try:
        result = await database.apply_trade_repair()
        _trade_repair.update({"status":"complete", "phase":"complete", "progress":100, "message":"Onarım tamamlandı", "result":result})
        _repair_log("info", f"Güncellenen trade: {result['updated_trades']}, pozisyon: {result['updated_positions']}, karar logu: {result['enriched_close_logs']}")
        await ws_manager.broadcast({"type":"trade_repair_completed", "data":result})
        return {"ok":True, **_trade_repair}
    except Exception as exc:
        _trade_repair.update({"status":"error", "phase":"error", "message":str(exc)})
        _repair_log("error", str(exc))
        raise HTTPException(status_code=500, detail=str(exc))

@app.get("/api/trade-repair/legacy-cleanup")
async def legacy_trade_cleanup_preview():
    return {"records": await database.preview_legacy_trade_cleanup(), "requires_confirmation": True}

@app.post("/api/trade-repair/legacy-cleanup")
async def legacy_trade_cleanup_apply(payload: dict = None, request: Request = None):
    _require_admin(request)
    body = payload or {}
    ids = body.get("trade_ids") or []
    if body.get("confirm") is not True:
        raise HTTPException(status_code=400, detail="Silme işlemi için confirm=true gerekli")
    try:
        _trade_repair.update({"status":"running", "phase":"legacy_cleanup", "progress":20, "message":"Onaylı legacy kayıt temizliği çalışıyor", "result":None})
        _repair_log("warning", f"Onaylı legacy temizlik başlatıldı: {', '.join(map(str, ids))}")
        result = await database.purge_legacy_trade_records(ids)
        _trade_repair.update({"status":"complete", "phase":"complete", "progress":100, "message":"Legacy kayıt temizliği tamamlandı", "result":result})
        _repair_log("info", f"Legacy kayıt temizlendi: {result['deleted_count']}")
        await ws_manager.broadcast({"type":"trade_repair_completed", "data":result})
        return {"ok":True, **result, "monitor":dict(_trade_repair)}
    except Exception as exc:
        _trade_repair.update({"status":"error", "phase":"error", "progress":100, "message":str(exc)})
        _repair_log("error", str(exc))
        raise HTTPException(status_code=400, detail=str(exc))

@app.post("/api/chart/_clear-indicators")
async def clear_all_chart_indicators():
    """Tüm sembollerin kayıtlı indikatör yerleşimlerini temizler (server-side toplu temizlik).

    Amaç: kullanıcı ayarlardaki butonla tek seferde TÜM sembollerin eski indikatör
    yerleşimlerini atar; varsayılan SlingShot (frontend fallback) kalır. Yıkıcı,
    onay ister.
    """
    cleared = await database.clear_all_chart_indicators()
    return {"ok": True, "cleared_symbols": cleared, "message": "Tüm indikatör yerleşimleri temizlendi"}


@app.get("/api/chart/{symbol}")
async def get_chart_settings(symbol: str):
    data = await database.get_chart_settings(symbol)
    if data is None:
        return {"symbol": symbol, "settings": None}
    return {"symbol": symbol, "settings": data}

@app.put("/api/chart/{symbol}")
async def save_chart_settings(symbol: str, payload: dict):
    await database.save_chart_settings(symbol, payload)
    return {"symbol": symbol, "saved": True}

@app.get("/api/positions")
async def get_positions():
    positions = []
    for sym, pos in analyzer.positions.items():
        try:
            current = float((market.get_ticker(sym) or {}).get("last_price") or pos["entry_price"] or 0)
            entry = float(pos["entry_price"] or 0)
            qty = float(pos["quantity"] or 0)
            gross_pnl_try = (current - entry) * qty
            entry_commission = entry * qty * config.COMMISSION_PCT
            pnl_try = gross_pnl_try - entry_commission
            pnl_pct = (pnl_try / (entry * qty) * 100) if (entry and qty) else 0.0
            ectx = pos.get("entry_context")
            ectx = ectx if isinstance(ectx, dict) else {}
            positions.append({
                "symbol": sym,
                "side": pos.get("side", "LONG"),
                "strategy": pos.get("strategy", "UT"),
                "entry": entry,
                "current": current,
                "pnl_pct": round(pnl_pct, 4),
                "pnl_try": round(pnl_try, 4),
                "quantity": qty,
                "entry_time": pos.get("entry_time"),
                "stop": pos.get("stop_price"),
                "take_profit": pos.get("take_profit"),
                "entry_context": ectx,
                "llm_managed": pos.get("strategy") == "LLM_PAPER",
                "llm_stop_price": pos.get("llm_stop_price"),
                "llm_take_profit_price": pos.get("llm_take_profit_price"),
                "llm_max_hold_sec": pos.get("llm_max_hold_sec"),
                "plan_revision": ectx.get("plan_revision", 0),
                "last_plan_reason": ectx.get("last_plan_reason"),
                "last_plan_updated_at": ectx.get("plan_updated_at"),
            })
        except Exception as exc:
            # Tek bir bozuk pozisyonun tüm listeyi 500'le düşürmesini engelle;
            # o pozisyonu boş/uzak değerlerle ekle ki panel en azından sembolü görsün.
            logger.warning("/api/positions: %s için serileştirme hatası (%s): %s", sym, type(exc).__name__, exc)
            positions.append({
                "symbol": sym, "side": pos.get("side", "LONG"), "strategy": pos.get("strategy", "UT"),
                "entry": pos.get("entry_price"), "current": pos.get("entry_price"),
                "pnl_pct": 0.0, "pnl_try": 0.0, "quantity": pos.get("quantity"),
                "entry_time": pos.get("entry_time"), "stop": pos.get("stop_price"),
                "take_profit": pos.get("take_profit"), "entry_context": {},
                "llm_managed": False, "llm_stop_price": None, "llm_take_profit_price": None,
                "llm_max_hold_sec": None, "plan_revision": 0, "last_plan_reason": None,
                "last_plan_updated_at": None, "error": str(exc),
            })
    positions.sort(key=lambda item: float(item.get("entry_time") or 0), reverse=True)
    # Canlı sunucuda pozisyon alanlarından biri NaN/±Infinity olduğunda
    # json.dumps "Out of range float values are not JSON compliant" ile TÜM
    # yanıtı 500'e düşürüyordu ve açık pozisyon paneli boşalıyordu. NaN/Inf
    # değerler None'a çevrilir; tek pozisyon listeyi bloklamamalı.
    positions = _json_safe_positions(positions)
    return {"positions": positions}

@app.get("/api/symbol-analysis/{symbol}")
async def symbol_analysis(symbol: str, timeframe: str = ""):
    sym = symbol.upper()
    ticker = market.get_ticker(sym)
    # The analysis page can request a valid market that was not warm when the
    # process started (or whose websocket stream briefly missed an event).
    # Hydrate that symbol from the public REST API instead of reporting it as
    # unknown. This remains read-only and paper-trading safe.
    primary_history = market.klines.get(requested_timeframe, {}).get(sym, {})
    history_ready = len(primary_history.get("closes", [])) >= 55
    analysis_klines = {
        requested_timeframe: primary_history,
        "1d": market.klines.get("1d", {}).get(sym, {}),
    }
    if not ticker or not history_ready:
        try:
            available = set(await trading_symbols("TRY"))
            if sym not in available:
                return {"symbol": sym, "analysis_build": "rest-fallback-v4", "data_ready": False, "error": "Sembol Binance TR'de işlem görmüyor"}
            rows = await fetch_klines(sym, requested_timeframe, limit=300)
            if rows and len(rows) >= 55:
                hydrated = {"opens": [], "highs": [], "lows": [], "closes": [], "volumes": []}
                for row in rows:
                    hydrated["opens"].append(float(row[1]))
                    hydrated["highs"].append(float(row[2]))
                    hydrated["lows"].append(float(row[3]))
                    hydrated["closes"].append(float(row[4]))
                    hydrated["volumes"].append(float(row[5]))
                market.klines[requested_timeframe][sym] = hydrated
                analysis_klines = {
                    requested_timeframe: hydrated,
                    "1d": market.klines.get("1d", {}).get(sym, {}),
                }
                last_price = float(rows[-1][4])
                ticker = {"symbol": sym, "last_price": last_price, "timestamp": int(time.time() * 1000)}
                market.tickers[sym] = ticker
            else:
                count = len(rows) if rows else 0
                return {"symbol": sym, "analysis_build": "rest-fallback-v4", "timeframes": {requested_timeframe: {"candles": count, "required": 55}}, "data_ready": False, "error": "Teknik analiz için yeterli mum verisi alınamadı"}
        except Exception as exc:
            return {"symbol": sym, "analysis_build": "rest-fallback-v4", "data_ready": False, "error": f"Sembol verisi alınamadı: {exc}"}
    if not ticker:
        return {"symbol": sym, "analysis_build": "rest-fallback-v4", "data_ready": False, "error": "Sembol verisi bulunamadı"}
    flow = market.get_orderflow(sym)
    if not flow.get("spread_pct") or not (flow.get("bid_qty") or flow.get("ask_qty")):
        try:
            book = await orderbook(sym, 5)
            bids, asks = book.get("bids", []), book.get("asks", [])
            if bids and asks:
                bid_qty = sum(float(row[1]) for row in bids[:5])
                ask_qty = sum(float(row[1]) for row in asks[:5])
                bid, ask = float(bids[0][0]), float(asks[0][0])
                flow.update({"bid_price": bid, "ask_price": ask, "bid_qty": bid_qty, "ask_qty": ask_qty,
                             "spread_pct": ((ask - bid) / bid * 100) if bid else None,
                             "source": "binance_tr_public_rest", "updated_at": time.time()})
                market.orderflow[sym] = flow
        except Exception as exc:
            flow["rest_error"] = str(exc)
    snapshot = calculate_snapshot(sym, ticker["last_price"], analysis_klines, flow, market.ticker_24h.get(sym, 0), config.DEFAULT_ORDER_USDT, requested_timeframe)
    snapshot["analysis_build"] = "rest-fallback-v4"
    # Sembol davranış profili ve range→trend geçiş sinyali; yalnız anlık
    # snapshot alanlarından türetilir, yeni ağ çağrısı yapmaz.
    try:
        snapshot["symbol_behavior"] = symbol_behavior_profile(snapshot, market.klines.get(requested_timeframe, {}).get(sym, {}))
        snapshot["regime_transition"] = regime_transition_signal(snapshot)
    except Exception:
        pass
    return snapshot

@app.get("/api/llm/config")
async def llm_config():
    data = await llm_analysis.list_config()
    paper_enabled = (await database.get_llm_setting("llm_paper_trade_enabled", "0")) == "1"
    auto_enabled = (await database.get_llm_setting("llm_auto_paper_enabled", "0")) == "1"
    return {**data, "encryption_configured": bool(os.getenv("LLM_ENCRYPTION_KEY", "").strip()), "paper_trade_enabled": paper_enabled, "auto_paper_enabled": auto_enabled, "auto_paper_interval_minutes": 15}

@app.get("/api/llm/chat-settings")
async def get_llm_chat_settings():
    raw = await database.get_llm_setting("chat_settings", "{}")
    try: return json.loads(raw or "{}")
    except json.JSONDecodeError: return {}

@app.put("/api/llm/chat-settings")
async def save_llm_chat_settings(payload: dict):
    settings = {"active_tools": [str(value) for value in (payload.get("active_tools") or [])], "active_skills": [str(value) for value in (payload.get("active_skills") or [])]}
    await database.set_llm_setting("chat_settings", json.dumps(settings, ensure_ascii=False))
    return {"ok": True, **settings}

@app.get("/api/llm/learning")
async def llm_learning():
    """Expose the descriptive closed-trade learning summary for audit/UI."""
    return build_learning_context(await database.get_trades(), limit=200)

@app.get("/api/llm/entry-policy")
async def llm_entry_policy():
    """Expose the active deterministic LLM paper-entry contract for audit."""
    return {
        "paper_only": True,
        "policy_version": "scalper-trade-manager-v2",
        "cooldown_seconds": config.LLM_REENTRY_COOLDOWN_SEC,
        "profit_cooldown_seconds": config.LLM_PROFIT_REENTRY_COOLDOWN_SEC,
        "cooldown_policy": "Kârla kapanan LLM_PAPER işlemi: 5 dakika; zararla kapanan işlem: 30 dakika",
        "minimum_rearm_move_pct": config.LLM_REENTRY_MIN_MOVE_PCT,
        "hard_gates": {
            "max_rsi": 72,
            "max_stochastic": 92,
            "max_mfi": 80,
            "max_cci": 220,
            "min_orderflow_imbalance": -0.10,
            "higher_timeframes": ["15m", "1h"],
            "loss_streak_block_at": 2,
            "negative_expectancy_min_trades": 4,
        },
        "entry_contract": "BUY_SIGNAL only; BUY_BLOCKED and LLM_REENTRY_BLOCKED are not trades",
    }

@app.put("/api/llm/paper-trading")
async def set_llm_paper_trading(payload: dict, request: Request):
    enabled = bool(payload.get("enabled"))
    await database.set_llm_setting("llm_paper_trade_enabled", "1" if enabled else "0")
    actor = _session_username(request)
    await log_user_action(actor, None, "trade", "PAPER_TRADING_TOGGLE",
                          target=actor, details={"setting": "llm_paper_trade_enabled", "enabled": enabled}, request=request)
    return {"ok": True, "paper_trade_enabled": enabled, "real_trading": False}

@app.put("/api/llm/auto-paper-trading")
async def set_llm_auto_paper_trading(payload: dict, request: Request):
    enabled = bool(payload.get("enabled"))
    await database.set_llm_setting("llm_auto_paper_enabled", "1" if enabled else "0")
    actor = _session_username(request)
    await log_user_action(actor, None, "trade", "PAPER_TRADING_TOGGLE",
                          target=actor, details={"setting": "llm_auto_paper_enabled", "enabled": enabled}, request=request)
    return {"ok": True, "auto_paper_enabled": enabled, "trigger": "after_each_closed_position_or_10m_idle_with_balance_over_100_try", "paper_only": True}


@app.post("/api/llm/paper-trade")
async def llm_open_paper_trade(payload: dict, request: Request = None):
    if (await database.get_llm_setting("llm_paper_trade_enabled", "0")) != "1":
        raise HTTPException(status_code=403, detail="LLM paper işlem açma yetkisi ayarlardan kapalı")
    symbol = str(payload.get("symbol", "")).replace("_", "").upper()
    candidates = []
    if not symbol:
        scan = await scan_market_snapshots({"symbols": config.SYMBOLS, "timeframes": ["1m", "3m", "5m", "15m"], "limit": 5, "fresh": True})
        # scan_market_snapshots zaten bullish adayları deterministik eşik ve
        # trend filtresinden geçiriyor; burada ikinci, daha sert eşik adayları
        # gereksiz yere silip "aday yok" üretiyordu.
        candidates = list(scan.get("bullish_candidates", []))
        if not candidates:
            top = [{"symbol": row.get("symbol"), "score": row.get("score"), "risks": row.get("risks", [])}
                   for row in scan.get("ranked", [])[:5]]
            raise HTTPException(status_code=409, detail={"message": "Paper işlem için bullish aday bulunamadı", "top_ranked": top, "action": "işlem açılmadı"})
    else:
        candidates = [{"symbol": symbol, "score": None}]
    # Otomatik seçimde symbol başlangıçta boştur; geçerlilik kontrolü yalnızca
    # kullanıcı belirli bir sembol gönderdiğinde uygulanmalıdır.
    if symbol and symbol not in config.SYMBOLS:
        try:
            available_symbols = set(await trading_symbols("TRY"))
        except Exception:
            available_symbols = set()
        if symbol not in available_symbols:
            raise HTTPException(status_code=400, detail="Geçerli TRY sembolü gerekli")
    blocked = []
    historical_trades = await database.get_trades(limit=500)
    for candidate in candidates:
        symbol = str(candidate["symbol"]).upper()
        if symbol not in config.SYMBOLS:
            continue
        # Enforce re-entry policy at the orchestration boundary too; callers
        # cannot bypass the portfolio writer's guard by hitting this endpoint.
        llm_guard = await database.get_llm_symbol_guard(symbol)
        guard_reason = _llm_guard_block_reason(llm_guard)
        if guard_reason:
            blocked.append({"symbol": symbol, "reason": guard_reason})
            await database.save_signal({
                "symbol": symbol, "action": "BUY_BLOCKED", "price": None,
                "reason": guard_reason, "strategy": "LLM_PAPER", "timestamp": time.time(),
                "guard_revision": llm_guard.get("revision"),
            })
            continue
        if llm_guard and llm_guard.get("status") == "active":
            await database.upsert_llm_symbol_guard(
                symbol, llm_guard.get("guard_type") or "cooldown", "expired",
                llm_guard.get("blocked_until"), "cooldown_elapsed", llm_guard.get("evidence") or {},
            )
        ticker = market.get_ticker(symbol)
        if not ticker or not ticker.get("last_price"):
            try:
                price, ticker = await _fresh_public_price(symbol)
                if price is not None:
                    ticker = {"symbol": symbol, "last_price": price, "timestamp": time.time() * 1000, "source": (ticker or {}).get("source", "binance_tr_public_rest")}
            except Exception as exc:
                blocked.append({"symbol": symbol, "reason": f"price_unavailable:{exc}"})
        if not ticker or not ticker.get("last_price"):
            blocked.append({"symbol": symbol, "reason": "price_unavailable"})
            continue
        higher_timeframes = []
        entry_snapshot = {}
        outcome_profile = {}
        try:
            entry_snapshot = await symbol_analysis(symbol, "5m")
            outcome_profile = symbol_outcome_profile(historical_trades, symbol, "LLM_PAPER", 100)
            gate_ok, gate_reasons = _llm_entry_quality_gate(entry_snapshot, outcome_profile)
            if gate_reasons:
                gate_ok = False
        except Exception as exc:
            gate_ok, gate_reasons = False, [f"entry_snapshot_error:{type(exc).__name__}"]
        if not gate_ok:
            reason = "llm_entry_quality_gate:" + ",".join(gate_reasons)
            blocked.append({"symbol": symbol, "reason": reason})
            await database.save_signal({
                "symbol": symbol, "action": "BUY_BLOCKED", "price": ticker["last_price"],
                "reason": reason, "strategy": "LLM_PAPER", "timestamp": time.time(),
                "entry_gate_evidence": {
                    "reasons": gate_reasons,
                    "outcome_profile": outcome_profile,
                    "timeframes": {
                        "5m": (entry_snapshot.get("trend") or {}).get("alignment") if isinstance(entry_snapshot, dict) else None,
                        "15m": (higher_timeframes[0].get("trend") or {}).get("alignment") if len(higher_timeframes) > 0 else None,
                        "1h": (higher_timeframes[1].get("trend") or {}).get("alignment") if len(higher_timeframes) > 1 else None,
                    },
                },
            })
            continue
        llm_plan = payload.get("plan") or {}
        def _pct(value, fallback):
            try: return max(0.001, min(float(value), 0.25))
            except (TypeError, ValueError): return fallback
        order_value = max(config.MIN_PARTIAL_ORDER_TRY, min(float(llm_plan.get("order_value_try", config.DEFAULT_ORDER_USDT)), max(config.MIN_PARTIAL_ORDER_TRY, await database.get_wallet_balance("TRY"))))
        stop_loss_pct = _pct(llm_plan.get("stop_loss_pct"), config.HARD_STOP_LOSS_PCT)
        take_profit_pct = _pct(llm_plan.get("take_profit_pct"), config.SPOT_PROFIT_TARGET_PCT)
        hold_seconds = max(60, min(int(llm_plan.get("max_hold_seconds", config.MAX_POSITION_HOLD_SEC)), 7 * 24 * 3600))
        eligible, eligibility = await analyzer.entry_liquidity_preflight(symbol, "LLM_PAPER", order_value)
        if not eligible:
            blocked.append({"symbol": symbol, "reason": eligibility.get("reason", "entry_ineligible"), "eligibility": eligibility})
            continue
        signal = await analyzer.open_position(symbol, float(ticker["last_price"]), "LONG", "LLM_PAPER", order_value, stop_loss_pct, take_profit_pct, hold_seconds)
        if signal and str(signal.get("action", "")).upper() == "BUY_SIGNAL":
            actor = _session_username(request)
            await log_user_action(actor, None, "trade", "PAPER_TRADE_OPEN",
                                  target=symbol,
                                  details={"strategy": "LLM_PAPER", "order_value_try": order_value,
                                           "stop_loss_pct": stop_loss_pct, "take_profit_pct": take_profit_pct,
                                           "trade_id": signal.get("trade_id")},
                                  request=request)
            await ws_manager.broadcast({"type": "signal", "data": signal})
            return {"ok": True, "paper_only": True, "real_trading": False, "signal": signal, "plan": {"order_value_try": order_value, "stop_loss_pct": stop_loss_pct, "take_profit_pct": take_profit_pct, "max_hold_seconds": hold_seconds}, "research_attempts": blocked}
        blocked.append({"symbol": symbol, "reason": (signal or {}).get("reason", "risk_or_position_limit")})
    raise HTTPException(status_code=409, detail={"message": "Hiçbir aday paper işlem kurallarını geçemedi; işlem açılmadı", "blocked_candidates": blocked[:10], "retry_research": True})

@app.post("/api/llm/providers")
async def add_llm_provider(payload: dict):
    name = str(payload.get("name", "")).strip()
    base_url = str(payload.get("base_url", "")).strip()
    key = str(payload.get("api_key", "")).strip()
    if not name: raise HTTPException(status_code=400, detail="Provider adı gerekli")
    try: base_url = security._validate_provider_url_sync(base_url)
    except ValueError as exc: raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not key: raise HTTPException(status_code=400, detail="API key gerekli")
    try:
        provider_id = await database.save_llm_provider(name, base_url, llm_analysis.encrypt_key(key))
        return {"ok": True, "provider_id": provider_id}
    except RuntimeError as exc: raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc: raise HTTPException(status_code=500, detail=str(exc))

@app.get("/api/ml/status")
async def ml_status():
    """Son ML artifact metadata + metrics (Faz 1 izleme)."""
    latest = await database.get_latest_ml_model_artifact()
    if not latest:
        return {"status": "not_trained", "interval_hours": config.ML_TRAIN_INTERVAL_HOURS}
    return {"status": latest.get("status"), "artifact": latest,
            "interval_hours": config.ML_TRAIN_INTERVAL_HOURS,
            "models_dir": config.ML_MODELS_DIR}


@app.post("/api/ml/train")
async def ml_train_now():
    """Manuel eğitim tetikleme (ayarlar butonu / Faz 2 öncesi doğrulama)."""
    try:
        meta = await run_ml_training("manual")
        return {"ok": True, **meta}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"ML eğitimi başarısız: {exc}")


@app.get("/api/ml/predict")
async def ml_predict(symbol: str, horizon: int = 5):
    """Tek nokta ML tahmini (Faz 2 gölge mod doğrulaması için)."""
    target = ml_forecast.predict_target(symbol, {}, horizon)
    return {"symbol": symbol.upper(), "horizon": horizon, "available": target is not None,
            "prediction": target}


@app.post("/api/llm/models")
async def add_llm_model(payload: dict):
    try:
        provider_id = int(payload["provider_id"])
        name = str(payload["name"]).strip()
        if not name: raise ValueError("Model adı gerekli")
        if provider_id <= 0: raise ValueError("Geçerli bir provider seçin")
        model_type = str(payload.get("model_type", "chat")).strip().lower()
        if model_type not in ("chat", "embedding"): raise ValueError("Model tipi chat veya embedding olmalı")
        dimensions = payload.get("dimensions")
        dimensions = int(dimensions) if dimensions not in (None, "") else None
        if model_type == "embedding" and dimensions != 2048: raise ValueError("Bu deployment için embedding dimension 2048 olmalı")
        return {"ok": True, "model_id": await database.save_llm_model(provider_id, name, float(payload.get("temperature", 0.2)), model_type, dimensions, payload.get("embedding_metric", "cosine"))}
    except (KeyError, ValueError) as exc: raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc: raise HTTPException(status_code=500, detail=str(exc))

@app.post("/api/llm/skills")
async def add_llm_skill(payload: dict):
    name = str(payload.get("name", "")).strip()
    instructions = str(payload.get("instructions", "")).strip()
    if not name or not instructions: raise HTTPException(status_code=400, detail="Uzmanlık adı ve talimatları gerekli")
    try: return {"ok": True, "skill_id": await database.save_llm_skill(name, instructions)}
    except Exception as exc: raise HTTPException(status_code=500, detail=str(exc))

@app.put("/api/llm/providers/{provider_id}")
async def update_llm_provider(provider_id: int, payload: dict):
    name, base_url, key = str(payload.get("name", "")).strip(), str(payload.get("base_url", "")).strip(), str(payload.get("api_key", "")).strip()
    if not name: raise HTTPException(status_code=400, detail="Provider adı gerekli")
    try: base_url = security._validate_provider_url_sync(base_url)
    except ValueError as exc: raise HTTPException(status_code=400, detail=str(exc)) from exc
    try: await database.update_llm_provider(provider_id, name, base_url, llm_analysis.encrypt_key(key) if key else None); return {"ok": True}
    except Exception as exc: raise HTTPException(status_code=500, detail=str(exc))

@app.delete("/api/llm/providers/{provider_id}")
async def delete_llm_provider(provider_id: int):
    await database.delete_llm_provider(provider_id); return {"ok": True}

@app.put("/api/llm/models/{model_id}")
async def update_llm_model(model_id: int, payload: dict):
    name = str(payload.get("name", "")).strip()
    if not name: raise HTTPException(status_code=400, detail="Model adı gerekli")
    model_type = payload.get("model_type")
    dimensions = payload.get("dimensions")
    await database.update_llm_model(model_id, name, float(payload.get("temperature", 0.2)), model_type, int(dimensions) if dimensions not in (None, "") else None, payload.get("embedding_metric")); return {"ok": True}

@app.delete("/api/llm/models/{model_id}")
async def delete_llm_model(model_id: int):
    await database.delete_llm_model(model_id); return {"ok": True}

@app.put("/api/llm/skills/{skill_id}")
async def update_llm_skill(skill_id: int, payload: dict):
    name, instructions = str(payload.get("name", "")).strip(), str(payload.get("instructions", "")).strip()
    if not name or not instructions: raise HTTPException(status_code=400, detail="Uzmanlık adı ve talimatları gerekli")
    await database.update_llm_skill(skill_id, name, instructions); return {"ok": True}

@app.delete("/api/llm/skills/{skill_id}")
async def delete_llm_skill(skill_id: int):
    await database.delete_llm_skill(skill_id); return {"ok": True}

@app.put("/api/llm/active")
async def activate_llm(payload: dict):
    await database.set_llm_setting("llm_enabled", "1" if payload.get("enabled") else "0")
    if payload.get("model_id") is not None: await database.set_llm_setting("active_model_id", payload["model_id"])
    return {"ok": True}

@app.post("/api/llm/test")
async def test_llm(payload: dict = None):
    result = await llm_analysis.analyze({"test": True, "message": "Return exactly: CONNECTION_OK"})
    return result

@app.post("/api/llm/embedding/test")
async def test_embedding(payload: dict = None):
    body = payload or {}
    text = str(body.get("text", "embedding bağlantı testi"))[:4000]
    return await llm_analysis.embedding(text, body.get("model_id"))

@app.post("/api/market-snapshot-scan")
async def market_snapshot_scan(payload: dict = None):
    """Tüm etkin sembolleri salt-okunur biçimde tarar; canlı portföyü değiştirmez."""
    return await scan_market_snapshots(payload or {})

@app.get("/api/market-snapshot/{symbol}/deep")
async def market_snapshot_deep(symbol: str, timeframe: str = "5m"):
    """Tek sembol için LLM'e sunulacak güncel derin snapshot'ı döndürür."""
    return await deep_analyze_symbol({"symbol": symbol, "timeframe": timeframe})

@app.get("/api/market-snapshot/upside-candidates")
async def market_snapshot_upside_candidates(limit: int = 10):
    return await detect_15m_upside_candidates({"limit": limit})

@app.get("/api/market-snapshot/upside-candidates-5m")
async def market_snapshot_upside_candidates_5m(limit: int = 10):
    return await detect_5m_upside_candidates({"limit": limit})

@app.post("/api/positions/{symbol}/close")
async def close_position_manual(symbol: str, request: Request):
    """Açık pozisyonu manuel kapat (komisyon + işlem geçmişi dahil)."""
    symbol = symbol.replace("_", "").upper()
    price, ticker = await _fresh_public_price(symbol)
    if price is None:
        return {"ok": False, "message": f"{symbol} için güncel fiyat bulunamadı"}
    sig = await analyzer.close_position(symbol.upper(), price, "manual_close")
    if not sig:
        return {"ok": False, "message": f"{symbol} için açık pozisyon yok"}
    actor = _session_username(request)
    await log_user_action(actor, None, "trade", "POSITION_CLOSE_MANUAL",
                          target=symbol,
                          details={"reason": "manual_close", "price": price,
                                   "trade_id": sig.get("trade_id")},
                          request=request)
    await ws_manager.broadcast({"type": "signal", "data": sig})
    if str(sig.get("strategy", "")).upper() != "LLM_PAPER":
        _start_background(llm_replenish_after_close(), "llm-replenish-after-close", single_pass=True)
    return {"ok": True, "message": f"{symbol} kapatıldı @ {price:.2f}", "signal": sig}

@app.get("/api/trades")
async def get_trades(limit: int = 100, offset: int = 0, symbol: str = "", strategy: str = ""):
    """Kapanan pozisyonların işlem geçmişi."""
    return {"trades": await database.get_trades(limit, offset, symbol or None, strategy or None),
            "total": await database.get_trade_count(symbol or None, strategy or None), "limit": limit, "offset": offset}


@app.get("/api/portfolio/summary")
async def portfolio_summary():
    """Single source for global chart/portfolio headline metrics (paper only)."""
    snapshot = _ws_snapshot_cache.get("portfolio") or {}
    try:
        snapshot = database._json_safe(snapshot)
    except Exception:
        pass
    return {
        "portfolio": snapshot,
        "metrics": await database.get_portfolio_trade_metrics(),
        "generated_at": time.time(),
        "paper_only": True,
    }


@app.get("/api/chart/{symbol}/timeframe-trends")
async def chart_timeframe_trends(symbol: str):
    """Fast, completed-candle EMA alignment ribbon for the chart terminal."""
    sym = str(symbol).replace("_", "").upper()
    timeframes = ("1m", "5m", "15m", "30m", "1h", "4h", "1d")
    ticker = market.get_ticker(sym) or {}
    price = float(ticker.get("last_price") or 0.0)
    daily = market.klines.get("1d", {}).get(sym, {})
    flow = market.get_orderflow(sym)
    rows = []
    for timeframe in timeframes:
        history = market.klines.get(timeframe, {}).get(sym, {})
        closes = history.get("closes") or []
        if len(closes) < 55:
            rows.append({"timeframe": timeframe, "alignment": "unknown", "data_ready": False})
            continue
        snapshot = calculate_snapshot(
            sym, price or float(closes[-1]), {timeframe: history, "1d": daily}, flow,
            market.ticker_24h.get(sym, 0), config.DEFAULT_ORDER_USDT, timeframe,
        )
        alignment = str((snapshot.get("trend") or {}).get("alignment") or "unknown")
        rows.append({
            "timeframe": timeframe,
            "alignment": alignment if alignment in {"bullish", "bearish", "mixed"} else "unknown",
            "data_ready": bool(snapshot.get("data_ready")),
            "closed_at_ms": int(history.get("last_closed_at_ms") or 0),
        })
    return {"symbol": sym, "timeframes": rows, "generated_at": time.time(), "candle_policy": "completed_only"}

def _require_postgres_target() -> str:
    if os.getenv("DB_BACKEND", "postgres").lower() != "postgres":
        raise HTTPException(status_code=503, detail="Sistem yalnızca PostgreSQL kullanmalıdır; DB_BACKEND=postgres yapın")
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise HTTPException(status_code=503, detail="DATABASE_URL tanımlı değil")
    return database_url


async def _pg_dump_stream(database_url: str):
    """Stream a pg_dump custom-format dump while it runs.

    Büyük veritabanında tüm yedeği sunucuda tamponlayıp sonra göndermek,
    ilk bayt gitmeden bekleyen proxy/tarayıcı bağlantısını zaman aşımına
    düşürüyordu; pg_dump çıktısı üretildikçe akıtılır.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "pg_dump", "--format=custom", "--no-owner", "--no-acl", database_url,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail="PostgreSQL yedek aracı pg_dump backend imajında kurulu değil") from exc
    first = await proc.stdout.read(5)
    if first != b"PGDMP":
        proc.kill()
        stderr = (await proc.stderr.read() or b"")[-2000:].decode("utf-8", "replace")
        raise HTTPException(status_code=502, detail=stderr or "pg_dump geçerli PostgreSQL custom-format çıktısı üretmedi")
    yield first
    try:
        while True:
            chunk = await proc.stdout.read(256 * 1024)
            if not chunk:
                break
            yield chunk
        returncode = await proc.wait()
        if returncode != 0:
            stderr = (await proc.stderr.read() or b"")[-2000:].decode("utf-8", "replace")
            logger.error("pg_dump akışı hatalı bitti (rc=%s): %s", returncode, stderr)
    finally:
        if proc.returncode is None:
            proc.kill()


def _backup_headers() -> dict:
    return {"X-Backup-Format": "postgresql-custom", "X-Backup-Verified": "PGDMP",
            "Content-Disposition": f'attachment; filename="scalperagent-postgres-{time.strftime("%Y%m%d-%H%M%S")}.dump"'}


async def _create_postgres_backup():
    """Create a validated PostgreSQL custom-format backup (streamed helper).

    pg_dump çıktısını akıtırken ilk 5 baytın PGDMP imzasını doğrular;
    geçersiz üretimde HTTPException fırlatır. Dönüş: (async generator,
    headers sözlüğü).
    """
    database_url = _require_postgres_target()
    headers={"X-Backup-Format": "postgresql-custom", "X-Backup-Verified": "PGDMP"}
    headers["Content-Disposition"] = f'attachment; filename="scalperagent-postgres-{time.strftime("%Y%m%d-%H%M%S")}.dump"'
    try:
        proc = await asyncio.create_subprocess_exec(
            "pg_dump", "--format=custom", "--no-owner", "--no-acl", database_url,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail="PostgreSQL yedek aracı pg_dump backend imajında kurulu değil") from exc
    first = await proc.stdout.read(5)
    if first != b"PGDMP":
        proc.kill()
        stderr = (await proc.stderr.read() or b"")[-2000:].decode("utf-8", "replace")
        raise HTTPException(status_code=502, detail=stderr or "pg_dump geçerli PostgreSQL custom-format çıktısı üretmedi")

    async def _stream():
        yield first
        try:
            while True:
                chunk = await proc.stdout.read(256 * 1024)
                if not chunk:
                    break
                yield chunk
            returncode = await proc.wait()
            if returncode != 0:
                stderr = (await proc.stderr.read() or b"")[-2000:].decode("utf-8", "replace")
                logger.error("pg_dump akışı hatalı bitti (rc=%s): %s", returncode, stderr)
        finally:
            if proc.returncode is None:
                proc.kill()

    return _stream(), headers


@app.get("/api/backup")
async def download_backup():
    """Download a PostgreSQL custom-format dump (streamed while pg_dump runs)."""
    stream, headers = await _create_postgres_backup()
    return StreamingResponse(stream, media_type="application/octet-stream", headers=headers)


@app.get("/api/postgres/backup")
async def download_postgres_backup():
    """Explicit alias for clients that use the PostgreSQL-specific route."""
    stream, headers = await _create_postgres_backup()
    return StreamingResponse(stream, media_type="application/octet-stream", headers=headers)

@app.post("/api/postgres/restore")
async def restore_postgres_backup(payload: dict = None, request: Request = None):
    _require_admin(request)
    body = payload or {}; raw_path = str(body.get("path", ""))
    if body.get("confirmation") != "RESTORE_POSTGRES": raise HTTPException(status_code=400, detail="RESTORE_POSTGRES onayı gerekli")
    if not os.getenv("DATABASE_URL"): raise HTTPException(status_code=400, detail="DATABASE_URL gerekli")
    # Only dumps this backend created may be restored: an arbitrary client
    # path combined with --clean would wipe the live schema from any file.
    path = os.path.abspath(raw_path)
    backup_dir = os.path.abspath(tempfile.gettempdir()) + os.sep
    if not path.startswith(backup_dir) or not os.path.basename(path).startswith("scalper-postgres-") or not path.endswith(".dump"):
        raise HTTPException(status_code=400, detail="Yalnızca sunucu tarafından üretilen scalper-postgres-*.dump yedekleri geri yüklenebilir")
    if not os.path.isfile(path): raise HTTPException(status_code=404, detail="Belirtilen yedek dosyası bulunamadı")
    try:
        with open(path, "rb") as backup_file:
            if backup_file.read(5) != b"PGDMP":
                raise HTTPException(status_code=400, detail="Dosya geçerli bir PostgreSQL custom-format yedeği değil")
        validation = await asyncio.to_thread(subprocess.run, ["pg_restore", "--list", path], capture_output=True, text=True, timeout=120)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Yedek doğrulanamadı: {exc}") from exc
    if validation.returncode != 0:
        raise HTTPException(status_code=400, detail=validation.stderr[-2000:] or "Yedek dosyası pg_restore --list doğrulamasından geçemedi")
    result = await asyncio.to_thread(subprocess.run, ["pg_restore", "--clean", "--if-exists", "--no-owner", "--dbname", os.environ["DATABASE_URL"], path], capture_output=True, text=True, timeout=1200)
    if result.returncode != 0: raise HTTPException(status_code=502, detail=result.stderr[-3000:] or "pg_restore başarısız")
    return {"ok": True, "message": "PostgreSQL backup geri yüklendi; backend yeniden başlatılması önerilir"}

@app.post("/api/memory/reset")
async def reset_memory(request: Request = None):
    _require_admin(request)
    if not _pg_pool: raise HTTPException(status_code=503, detail="PostgreSQL memory backend aktif değil")
    async with _pg_pool.acquire() as conn:
        await conn.execute("TRUNCATE memory_retrieval_logs, memory_embeddings, memory_documents RESTART IDENTITY")
    embedding_worker.stats.update({"queued":0,"processed":0,"failed":0,"last_error":None,"last_processed_at":None})
    return {"ok": True, "message": "LLM memory kayıtları sıfırlandı; paper-trading kayıtları korunuyor"}

@app.get("/api/llm/agent-traces")
async def get_agent_traces(limit: int = 50):
    if not _pg_pool: return {"enabled": False, "traces": []}
    async with _pg_pool.acquire() as conn:
        rows = await conn.fetch("""SELECT trace_id,session_id,intent,status,started_at,completed_at
            FROM agent_traces ORDER BY started_at DESC LIMIT $1""", max(1, min(int(limit), 200)))
    return {"enabled": True, "traces": [dict(row) for row in rows]}

@app.get("/api/llm/evaluations")
async def get_agent_evaluations(limit: int = 100):
    if not _pg_pool: return {"enabled": False, "evaluations": []}
    async with _pg_pool.acquire() as conn:
        rows = await conn.fetch("""SELECT id,trace_id,evaluator_type,score,passed,failure_category,explanation,created_at
            FROM agent_evaluations ORDER BY created_at DESC LIMIT $1""", max(1, min(int(limit), 500)))
    return {"enabled": True, "evaluations": [dict(row) for row in rows]}

@app.get("/api/llm/instincts")
async def get_agent_instincts(status: str = "", limit: int = 100):
    if not _pg_pool: return {"enabled": False, "instincts": []}
    async with _pg_pool.acquire() as conn:
        if status:
            rows = await conn.fetch("""SELECT * FROM trading_instincts WHERE status=$1
                ORDER BY confidence DESC,last_seen_at DESC LIMIT $2""", status, max(1, min(int(limit), 500)))
        else:
            rows = await conn.fetch("""SELECT * FROM trading_instincts
                ORDER BY confidence DESC,last_seen_at DESC LIMIT $1""", max(1, min(int(limit), 500)))
    return {"enabled": True, "instincts": [dict(row) for row in rows]}

@app.get("/api/llm/eval-cases")
async def get_agent_eval_cases():
    path = os.path.join(os.path.dirname(__file__), "..", "evals", "golden_cases.json")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return {"cases": json.load(handle)}
    except Exception as exc:
        return {"cases": [], "error": str(exc)}

@app.post("/api/llm/evals/run")
async def run_agent_golden_evals(payload: dict = None, request: Request = None):
    _require_admin(request)
    """Run the versioned golden cases against the configured LLM and persist results."""
    if not _pg_pool: raise HTTPException(status_code=503, detail="PostgreSQL eval backend aktif değil")
    cases_response = await get_agent_eval_cases()
    cases = cases_response.get("cases", [])
    requested = set((payload or {}).get("case_keys") or [])
    attempts = max(1, min(int((payload or {}).get("attempts", 1)), 3))
    results = []
    for case in cases:
            if requested and case.get("case_key") not in requested: continue
            async with _pg_pool.acquire() as conn:
                case_row = await conn.fetchrow("""INSERT INTO agent_eval_cases(case_key,category,input,expected)
                    VALUES($1,$2,$3::jsonb,$4::jsonb)
                    ON CONFLICT(case_key) DO UPDATE SET category=EXCLUDED.category,input=EXCLUDED.input,expected=EXCLUDED.expected
                    RETURNING id""", case["case_key"], case["category"], json.dumps(case["input"], ensure_ascii=False), json.dumps(case.get("expected", {}), ensure_ascii=False))
            for attempt in range(1, attempts + 1):
                trace_id = new_trace_id(f"eval-{case['case_key']}")
                await start_trace(_pg_pool, trace_id=trace_id, session_id=f"eval:{case['case_key']}", intent=case["case_key"], metadata={"golden": True})
                result = await llm_analysis.chat({"type":"golden_eval", "case":case["case_key"], "expected":case.get("expected", {}), "data_policy":"Paper-only; do not invent live data."}, case["input"].get("messages", []), [], None)
                evaluation = evaluate_output(result.get("text"), intent=case["case_key"], expected=case.get("expected", {}))
                passed = bool(evaluation.get("passed")) and result.get("status") == "ok"
                trajectory = {"checked": False, "reason": "Golden runner buffered response pathında araç çağrısı devre dışı"}
                details = {"response": result.get("text"), "evaluation": evaluation, "trajectory": trajectory, "model": result.get("model")}
                async with _pg_pool.acquire() as conn:
                    await conn.execute("""INSERT INTO agent_eval_runs(case_id,trace_id,attempt_no,passed,score,details)
                        VALUES($1,$2,$3,$4,$5,$6::jsonb)""", int(case_row["id"]), trace_id, attempt, passed, evaluation.get("score"), json.dumps(details, ensure_ascii=False, default=str))
                await save_evaluation(_pg_pool, trace_id, {**evaluation, "passed": passed}, evaluator_type="golden_deterministic")
                await finish_trace(_pg_pool, trace_id, "completed" if passed else "failed")
                results.append({"case_key":case["case_key"],"attempt":attempt,"passed":passed,"score":evaluation.get("score"),"trace_id":trace_id,"trajectory":trajectory})
    aggregates = []
    for case_key in sorted({item["case_key"] for item in results}):
        items = [item for item in results if item["case_key"] == case_key]
        pass_count = sum(1 for item in items if item["passed"])
        k = len(items)
        aggregates.append({"case_key": case_key, "k": k, "pass_at_k": pass_count > 0, "pass_all_k": pass_count == k,
                           "pass_rate": round(pass_count / k, 4) if k else 0.0})
    return {"ok": True, "total": len(results), "passed": sum(1 for item in results if item["passed"]),
            "pass_at_k": sum(1 for item in aggregates if item["pass_at_k"]),
            "pass_all_k": sum(1 for item in aggregates if item["pass_all_k"]),
            "aggregates": aggregates, "results": results}

@app.put("/api/llm/instincts/{instinct_id}/approve")
async def approve_agent_instinct(instinct_id: int):
    if not _pg_pool: raise HTTPException(status_code=503, detail="PostgreSQL learning backend aktif değil")
    async with _pg_pool.acquire() as conn:
        row = await conn.fetchrow("""UPDATE trading_instincts SET status='approved',approved_at=now()
            WHERE id=$1 RETURNING id,instinct_key,status,confidence""", int(instinct_id))
    if not row: raise HTTPException(status_code=404, detail="Instinct bulunamadı")
    return {"ok": True, "instinct": dict(row)}

@app.post("/api/llm/instincts/promote")
async def promote_agent_instincts(payload: dict = None):
    if not _pg_pool: raise HTTPException(status_code=503, detail="PostgreSQL learning backend aktif değil")
    return await promote_validated_instincts(_pg_pool, dry_run=not bool((payload or {}).get("apply")))

@app.get("/api/risk/summary")
async def risk_summary():
    trades = await database.get_trades(limit=None)
    positions = analyzer.positions
    realized = sum(float(t.get("pnl") or 0.0) for t in trades)
    commission = sum(float(t.get("commission") or 0.0) for t in trades)
    losses = 0
    for trade in trades:
        if float(trade.get("pnl") or 0.0) < 0: losses += 1
        else: break
    today_start = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
    today_pnl = sum(float(t.get("pnl") or 0.0) for t in trades if float(t.get("exit_time") or 0) >= today_start)
    return {"open_positions": len(positions), "realized_pnl": realized, "today_pnl": today_pnl,
            "commission": commission, "consecutive_losses": losses, "max_positions": config.MAX_OPEN_POSITIONS,
            "risk_flags": {"consecutive_loss_streak": losses >= 3, "daily_loss": today_pnl < 0}}

@app.post("/api/reset")
async def reset_all(request: Request = None):
    _require_admin(request)
    """Eski paper-trading/strateji geçmişini sil, ayarları koru ve cüzdanı sıfırla."""
    analyzer.positions.clear()
    analyzer.pending_orders.clear()
    # Reset sonrası mevcut mum uzunlukları eski sinyal durumuyla karşılaştırılmasın;
    # aksi halde yeni mum kapanana kadar tüm stratejiler sessiz kalabiliyordu.
    analyzer._last_signal_lengths.clear()
    analyzer._cooldown_until.clear()
    analyzer._timeout_block_until.clear()
    analyzer._hard_stop_block_until.clear()
    deleted = await database.reset_trading_data()
    await ws_manager.broadcast({"type": "reset", "data": {"ok": True}})
    return {
        "ok": True,
        "message": "Eski paper-trading kayıtları silindi, cüzdan 10.000 TRY'ye sıfırlandı",
        "deleted": deleted,
    }



# Geç bağlama: router modülleri burada tanımlı app düzeyi handler'ları çağrı
# zamanında çözer. main modülü tam yüklendikten sonra atanır; böylece router
# -> main yönünde döngüsel import oluşmaz.
llm_chat_routes.llm_open_paper_trade = llm_open_paper_trade
llm_chat_routes.symbol_analysis = symbol_analysis
llm_chat_routes.get_config = get_config
async def get_strategy_stats():
    """LLM aracı: strateji bazlı işlem istatistikleri (kayıt olan stratejiler)."""
    trades = await database.get_trades(limit=None)
    stats = {}
    for t in trades:
        name = str(t.get("strategy") or "Bilinmeyen")
        row = stats.setdefault(name, {"strategy": name, "trades": 0, "wins": 0, "pnl": 0.0, "commission": 0.0})
        pnl = float(t.get("pnl") or 0.0)
        row["trades"] += 1
        row["pnl"] += pnl
        row["commission"] += float(t.get("commission") or 0.0)
        if pnl > 0:
            row["wins"] += 1
    for row in stats.values():
        row["win_rate"] = (row["wins"] / row["trades"] * 100) if row["trades"] else 0.0
    return {"stats": stats, "active": ["CHAT_PREDICTION", "LLM_PAPER"]}


llm_chat_routes.get_strategy_stats = get_strategy_stats
runtime_routes.llm_open_paper_trade = llm_open_paper_trade
runtime_routes.gainers_radar = gainers_radar
