"""Agent-to-agent (A2A) messaging loops and routes."""
import asyncio
import os
import json
import hmac
import time

from fastapi import APIRouter, HTTPException, Header

from app import a2a
from app import database
from app.self_learning import build_learning_context
from app import llm_analysis
from app.config import config

router = APIRouter()


async def publish_a2a_event(message_type, payload, *, correlation_id=None, requires_user_approval=False):
    """Publish a paper-only diagnostic/capability event without affecting the request."""
    message = a2a.make_message(
        sender="scalper-server-llm",
        recipient="codex-agent",
        message_type=message_type,
        payload=payload,
        correlation_id=correlation_id,
        requires_user_approval=requires_user_approval,
    )
    delivery = await a2a.deliver(message)
    await database.save_a2a_message(
        message,
        direction="outbound",
        status="delivered" if delivery.get("delivered") else "queued",
        error=delivery.get("error") or delivery.get("reason"),
    )
    return {"message_id": message["message_id"], "delivery": delivery}


async def process_a2a_research_message(message):
    """Let the server LLM synthesize an inbound Codex result without mutating state."""
    payload = message.get("payload") or {}
    context = {
        "type": "a2a_re_evaluation",
        "paper_only": True,
        "correlation_id": message.get("correlation_id"),
        "external_research": payload,
        "instruction": "Codex araştırmasını kanıt olarak değerlendir. Çelişkileri belirt. Gerçek emir, ayar mutasyonu veya pozisyon değişikliği yapma; yalnızca sonraki paper kararını açıkla.",
        "self_learning": build_learning_context(await database.get_trades(), limit=100),
    }
    result = await llm_analysis.chat(context, [{
        "role": "user",
        "content": "Yeni A2A araştırma sonucu geldi. Bunu Scalper paper-trading bağlamında değerlendir ve Türkçe kısa bir karar özeti üret.",
    }], tools=None, tool_executor=None)
    response = a2a.make_message(
        sender="scalper-server-llm",
        recipient="codex-agent",
        message_type="a2a_decision",
        payload={"text": result.get("text"), "status": result.get("status"), "model": result.get("model"), "source_message_id": message.get("message_id")},
        correlation_id=message.get("correlation_id") or message.get("message_id"),
        requires_user_approval=True,
    )
    delivery = await a2a.deliver(response)
    await database.save_a2a_message(response, direction="outbound", status="delivered" if delivery.get("delivered") else "queued", error=delivery.get("error") or delivery.get("reason") or result.get("error"))
    await database.update_a2a_message_status(message.get("message_id"), "processed")
    return response


async def a2a_inbox_loop():
    """Process new research responses asynchronously; never block market loops."""
    await asyncio.sleep(10)
    while True:
        try:
            messages = await database.get_a2a_messages(limit=20, status="received")
            for message in messages:
                if message.get("message_type") not in {"research_result", "capability_response", "tool_review"}:
                    continue
                try:
                    await process_a2a_research_message(message)
                except Exception as exc:
                    await database.update_a2a_message_status(message.get("message_id"), "error", {**(message.get("payload") or {}), "processing_error": str(exc)})
                    print(f"[A2A] inbound mesaj işlenemedi: {exc}")
        except Exception as exc:
            print(f"[A2A] inbox loop hatası: {exc}")
        await asyncio.sleep(10)


async def a2a_outbox_loop():
    """Retry stranded outbound A2A messages that were queued on transport failure."""
    await asyncio.sleep(30)
    while True:
        try:
            messages = await database.get_a2a_messages(limit=50, status="queued")
            for message in messages:
                if message.get("direction") != "outbound":
                    continue
                try:
                    delivery = await a2a.deliver(message.get("payload") or message)
                    if delivery.get("delivered"):
                        await database.save_a2a_message(
                            message.get("payload") or message,
                            direction="outbound",
                            status="delivered",
                        )
                except Exception as exc:
                    print(f"[A2A] outbox retry failed for {message.get('message_id')}: {exc}")
        except Exception as exc:
            print(f"[A2A] outbox loop error: {exc}")
        await asyncio.sleep(300)


LLM_POSITION_CONTEXT_TOOL = {"type": "function", "function": {"name": "get_llm_open_position", "description": "Acik LLM paper pozisyonunun guncel state ve planini getirir.", "parameters": {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]}}}
LLM_UPDATE_POSITION_TOOL = {"type": "function", "function": {"name": "update_llm_position_plan", "description": "LLM paper pozisyonunun TP, SL veya maksimum bekleme planını günceller; gerçek emir göndermez.", "parameters": {"type": "object", "properties": {"symbol": {"type": "string"}, "changes": {"type": "object", "properties": {"stop_loss_pct": {"type": "number"}, "take_profit_pct": {"type": "number"}, "max_hold_seconds": {"type": "integer"}}}, "reason": {"type": "string"}, "evidence": {"type": "object"}}, "required": ["symbol", "changes", "reason"]}}}
LLM_CLOSE_POSITION_TOOL = {"type": "function", "function": {"name": "close_llm_position", "description": "Güncel fiyatla LLM paper pozisyonunu kapatır; gerçek emir göndermez.", "parameters": {"type": "object", "properties": {"symbol": {"type": "string"}, "reason": {"type": "string"}}, "required": ["symbol", "reason"]}}}
LLM_SET_SYMBOL_GUARD_TOOL = {"type":"function","function":{"name":"set_llm_symbol_guard","description":"LLM’nin kendi oluşturduğu sembol bazlı BUY guard’ını oluşturur veya günceller. Paper execution guard’ıdır; strateji parametresi değiştirmez.","parameters":{"type":"object","properties":{"symbol":{"type":"string"},"guard_type":{"type":"string","enum":["cooldown","symbol_block","min_movement"]},"blocked_until":{"type":"number","description":"Unix timestamp; boşsa süresiz blok"},"reason":{"type":"string"},"evidence":{"type":"object"}},"required":["symbol","guard_type","reason"]}}}
LLM_REMOVE_SYMBOL_GUARD_TOOL = {"type":"function","function":{"name":"remove_llm_symbol_guard","description":"LLM’nin daha önce oluşturduğu sembol BUY guard’ını kaldırır.","parameters":{"type":"object","properties":{"symbol":{"type":"string"},"reason":{"type":"string"}},"required":["symbol","reason"]}}}
LLM_LIST_SYMBOL_GUARDS_TOOL = {"type":"function","function":{"name":"list_llm_symbol_guards","description":"Aktif ve geçmiş LLM sembol guard’larını getirir.","parameters":{"type":"object","properties":{"active_only":{"type":"boolean"}},"required":[]}}}

@router.get("/.well-known/a2a-agent-card.json")
async def a2a_agent_card():
    return {
        "name": "scalper-server-llm",
        "description": "Scalper paper-trading research and diagnostics agent",
        "protocol": "a2a",
        "protocol_version": a2a.PROTOCOL_VERSION,
        "url": "/api/a2a/messages",
        "capabilities": ["paper_trading_research", "tool_diagnostics", "backtest", "memory_retrieval"],
        "safety": {"paper_only": True, "real_orders": False, "requires_user_approval_for_mutation": True},
    }


@router.get("/api/a2a/messages")
async def a2a_messages(limit: int = 100, status: str | None = None):
    return {"messages": await database.get_a2a_messages(limit, status)}


@router.post("/api/a2a/messages")
async def receive_a2a_message(
    payload: dict,
    x_a2a_signature: str | None = Header(default=None, alias="X-A2A-Signature"),
):
    secret = os.getenv("A2A_SHARED_SECRET", "").strip()
    if not secret:
        raise HTTPException(status_code=503, detail="A2A_SHARED_SECRET yapılandırılmamış")
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    expected = a2a.signature(raw, secret)
    if not x_a2a_signature or not hmac.compare_digest(x_a2a_signature, expected):
        raise HTTPException(status_code=401, detail="Geçersiz A2A imzası")
    if payload.get("protocol") != "a2a" or not payload.get("message_id") or not payload.get("type"):
        raise HTTPException(status_code=400, detail="Geçersiz A2A mesajı: protocol, message_id ve type gerekli")
    if payload.get("paper_only") is not True:
        raise HTTPException(status_code=400, detail="A2A kanalı paper_only=true gerektirir")
    try:
        created_at = float(payload.get("created_at"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="A2A created_at gerekli")
    if abs(time.time() - created_at) > 300:
        raise HTTPException(status_code=400, detail="A2A mesaj zaman penceresi geçersiz")
    inserted = await database.save_a2a_message(payload, direction="inbound", status="received", insert_only=True)
    if not inserted:
        return {"ok": True, "message_id": payload["message_id"], "status": "duplicate_ignored", "paper_only": True}
    return {"ok": True, "message_id": payload["message_id"], "status": "received", "paper_only": True}


@router.post("/api/a2a/messages/{message_id}/ack")
async def acknowledge_a2a(message_id: str):
    if not await database.acknowledge_a2a_message(message_id):
        raise HTTPException(status_code=404, detail="A2A mesajı bulunamadı")
    return {"ok": True, "message_id": message_id, "status": "acknowledged"}


@router.post("/api/a2a/messages/{message_id}/respond")
async def respond_to_a2a_message(message_id: str, payload: dict):
    """Store an external research/capability response against an inbound message."""
    response = a2a.make_message(
        sender=str(payload.get("from") or "codex-agent"),
        recipient="scalper-server-llm",
        message_type=str(payload.get("type") or "research_result"),
        payload=payload.get("payload") or {},
        correlation_id=message_id,
        requires_user_approval=bool(payload.get("requires_user_approval")),
    )
    if not await database.update_a2a_message_status(message_id, "acknowledged"):
        raise HTTPException(status_code=404, detail="A2A inbound mesajı bulunamadı")
    await database.save_a2a_message(response, direction="inbound", status="received")
    return {"ok": True, "message_id": response["message_id"], "correlation_id": message_id, "status": "received", "paper_only": True}


@router.post("/api/a2a/emit")
async def emit_a2a_event(payload: dict):
    """Create and deliver a server event; transport errors remain in outbox."""
    message = a2a.make_message(
        sender="scalper-server-llm",
        recipient=str(payload.get("to") or "codex-agent"),
        message_type=str(payload.get("type") or "event"),
        payload=payload.get("payload") or {},
        correlation_id=payload.get("correlation_id"),
        requires_user_approval=bool(payload.get("requires_user_approval")),
    )
    delivery = await a2a.deliver(message)
    await database.save_a2a_message(message, direction="outbound", status="delivered" if delivery.get("delivered") else "queued", error=delivery.get("error") or delivery.get("reason"))
    return {"ok": True, "message": message, "delivery": delivery, "paper_only": True}
