"""Kullanıcı başına bildirim tercihleri + WhatsApp telefon numarası.

NEDEN YENİ: Mevcut sistemde bildirim ayarları YALNIZCA global/admin düzeyinde
(`monitoring_notification_settings`) ve WhatsApp hedefi tek bir GRUPTU
(`WHATSAPP_GROUP_ID`). Kullanıcının istediği model farklı: HER kullanıcı kendi
panelinde (a) uygulama-içi bildirim, (b) bildirim sesi, (c) WhatsApp bildirimi
aç/kapat ve WhatsApp açıksa TELEFON NUMARASINI girer; sistem ürettiği
bildirimleri o numaraya mesaj olarak gönderir.

DEPOLAMA: `llm_settings` anahtarı `user_notif_prefs:<username>` → JSON.
(Kullanıcı başına ikinci bir tablo açmak yerine mevcut anahtar-değer deposu
kullanılır; `push_subscriptions.username` kimlik deseniyle aynı.)

Telefon numarası HASSAS kabul edilir: GET yanıtında MASKELENİR (son 4 hane),
tam değer yalnız sunucuda tutulur ve gönderim anında kullanılır.
"""
from __future__ import annotations

import json
import logging
import re

from fastapi import APIRouter, HTTPException, Request

from app import database, security
from app.api_common import rate_limit
from app import whatsapp_notify

logger = logging.getLogger("scalper.user_prefs")

router = APIRouter()

_PREFS_PREFIX = "user_notif_prefs:"

DEFAULTS = {
    "app_notifications": True,   # uygulama içi bildirimler
    "sound": True,               # bildirim sesi
    "whatsapp_enabled": False,   # WhatsApp mesajı gönder
    "phone": "",                 # E.164/ulusal; whatsapp_enabled iken gerekli
}


def _key(username: str) -> str:
    return f"{_PREFS_PREFIX}{str(username or '').strip().lower()}"


def _current_username(request: Request | None) -> str | None:
    if request is None:
        return None
    user = security.request_user(request.headers, request.cookies,
                                 client_fingerprint=security.client_fingerprint(request))
    return (user or {}).get("username")


def mask_phone(phone: str) -> str:
    """Ülke kodunu/görünen kısmı bırakıp ortayı gizler: +90 555***67.

    NORMALİZE edilmiş rakam dizisi üzerinden maskeler (ham girdi 05xx… olsa da
    kullanıcıya ülke kodlu biçim gösterilir).
    """
    digits = normalize_phone(phone)
    if not digits:
        return ""
    return f"+{digits[:2]} {digits[2:5]}***{digits[-2:]}"


def normalize_phone(phone: str) -> str:
    """Kullanıcı girdisini WhatsApp JID yerel kısmına çevir (yalnız rakam).

    - Boş/geçersiz → "".
    - TR varsayımı: 10 hane (5XXXXXXXXX) veya baştaki 0'lı → 90 eklenir.
    - Zaten ülke kodlu (10+ hane) → olduğu gibi.
    """
    digits = re.sub(r"\D", "", str(phone or ""))
    if not digits:
        return ""
    if digits.startswith("0"):
        digits = "9" + digits  # 05xx -> 905xx
    if len(digits) == 10 and digits.startswith("5"):
        digits = "90" + digits
    if len(digits) < 11 or len(digits) > 15:
        return ""
    return digits


async def _load(username: str) -> dict:
    raw = await database.get_llm_setting(_key(username), "{}")
    try:
        data = json.loads(raw or "{}")
    except (TypeError, ValueError):
        data = {}
    merged = dict(DEFAULTS)
    if isinstance(data, dict):
        merged.update({k: data.get(k, merged[k]) for k in DEFAULTS})
    return merged


async def _save(username: str, prefs: dict) -> dict:
    clean = dict(DEFAULTS)
    clean["app_notifications"] = bool(prefs.get("app_notifications", DEFAULTS["app_notifications"]))
    clean["sound"] = bool(prefs.get("sound", DEFAULTS["sound"]))
    clean["whatsapp_enabled"] = bool(prefs.get("whatsapp_enabled", DEFAULTS["whatsapp_enabled"]))
    clean["phone"] = str(prefs.get("phone", "") or "").strip()
    await database.set_llm_setting(_key(username), json.dumps(clean))
    return clean


def _public(prefs: dict) -> dict:
    return {
        "app_notifications": bool(prefs.get("app_notifications", True)),
        "sound": bool(prefs.get("sound", True)),
        "whatsapp_enabled": bool(prefs.get("whatsapp_enabled", False)),
        "phone_masked": mask_phone(prefs.get("phone", "")),
        "phone_set": bool(normalize_phone(prefs.get("phone", ""))),
        "whatsapp_available": whatsapp_notify.whatsapp_enabled(),
    }


async def get_prefs_for(username: str) -> dict:
    """Gönderim yolundan (monitoring) çağrılır: ham tercihleri döndürür."""
    if not username:
        return dict(DEFAULTS)
    return await _load(username)


@router.get("/api/user/preferences")
async def get_user_preferences(request: Request):
    username = _current_username(request)
    if not username:
        raise HTTPException(status_code=401, detail="Kimlik doğrulama gerekli")
    return {"ok": True, "preferences": _public(await _load(username))}


@router.put("/api/user/preferences")
async def put_user_preferences(payload: dict, request: Request):
    """Tercihleri güncelle. `phone` verilirse normalize edilir; whatsapp açıkken
    telefon boşsa 422 (aksi halde bildirim gönderilemez)."""
    username = _current_username(request)
    if not username:
        raise HTTPException(status_code=401, detail="Kimlik doğrulama gerekli")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Gövde bir JSON nesnesi olmalı")

    current = await _load(username)
    # Yalnız gönderilen alanlar güncellenir (merge).
    if "app_notifications" in payload:
        current["app_notifications"] = bool(payload.get("app_notifications"))
    if "sound" in payload:
        current["sound"] = bool(payload.get("sound"))
    if "whatsapp_enabled" in payload:
        current["whatsapp_enabled"] = bool(payload.get("whatsapp_enabled"))
    if "phone" in payload:
        current["phone"] = str(payload.get("phone") or "").strip()

    if current["whatsapp_enabled"] and not normalize_phone(current["phone"]):
        raise HTTPException(status_code=422, detail="WhatsApp için geçerli bir telefon numarası girin")

    saved = await _save(username, current)
    return {"ok": True, "preferences": _public(saved)}


@router.post("/api/user/whatsapp/test")
async def test_user_whatsapp(request: Request):
    """Kullanıcının kayıtlı numarasına deneme WhatsApp mesajı gönder."""
    username = _current_username(request)
    if not username:
        raise HTTPException(status_code=401, detail="Kimlik doğrulama gerekli")
    # 2026-10-15 (denetim düzeltmesi): kullanıcı başına 60 sn'de 1 deneme
    # mesajı; aksi halde WhatsApp köprüsü spam/maliyet aracına dönüşüyordu.
    if not rate_limit(f"whatsapp_test:{username}", rate_per_sec=1 / 60.0, burst=1):
        raise HTTPException(status_code=429, detail="Deneme mesajı en fazla dakikada bir gönderilebilir")
    prefs = await _load(username)
    number = normalize_phone(prefs.get("phone", ""))
    if not number:
        raise HTTPException(status_code=422, detail="Önce Ayarlar'dan telefon numaranızı kaydedin")
    if not whatsapp_notify.whatsapp_enabled():
        raise HTTPException(status_code=409, detail="WhatsApp köprüsü yapılandırılmamış")
    ok = await whatsapp_notify.send_whatsapp_to_number(
        f"✅ Scalper Intelligent Trade Systems · test bildirimi\nKullanıcı: {username}", number)
    if not ok:
        raise HTTPException(status_code=502, detail="WhatsApp gönderilemedi (köprü bağlı değil olabilir)")
    return {"ok": True, "to_masked": mask_phone(number)}
