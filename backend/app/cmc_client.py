"""CoinMarketCap Pro API istemcisi (salt okunur, önbellekli).

NEDEN VAR: radar/tarama katmanı bugüne kadar yalnız Binance fiyat-hacim verisiyle
çalışıyordu; piyasa geneli bağlam (Korku & Açgözlülük, BTC dominansı, trending
semboller, yükselen/düşenler) dışarıdan gelmiyordu. CMC bu bağlamı tek anahtarla
veriyor (bkz. https://coinmarketcap.com/api/documentation/).

TASARIM KURALLARI
- Anahtar `llm_settings` içinde `cmc_api_key` olarak ŞİFRELİ saklanır. GET
  yanıtında yalnız maskelenmiş son 4 karakter döner (Binance anahtar deseniyle
  aynı: backend/app/llm_analysis.py encrypt_key/decrypt_key).
- Bu modül HİÇBİR işlem açmaz, emir göndermez; yalnız okur.
- Kota iki kaynaktan izlenir: (a) `/v1/key/info` canlı, 60 sn önbellekli;
  (b) yerel sayaç (`cmc_usage_ledger`), anahtar bilgisi alınamadığında da
  panelde tahmini kullanım gösterir.
- Önbellek: brief 5 dk, key_info 60 sn. Aynı veriyi tekrar çekmek kredi yakar.
- Her uç nokta BAĞIMSIZ çalışır: biri plan kısıtı yüzünden 403 dönerse diğerleri
  yine döner ve o alan "unavailable" olarak işaretlenir. Uydurma değer yok.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app import database
from app.llm_analysis import decrypt_key, encrypt_key

logger = logging.getLogger("scalper.cmc")

BASE_URL = "https://pro-api.coinmarketcap.com"
KEY_HEADER = "X-CMC_PRO_API_KEY"
SETTINGS_KEY = "cmc_api_key"
LEDGER_KEY = "cmc_usage_ledger"

KEY_INFO_TTL = 60.0
BRIEF_TTL = 300.0

_KEY_INFO_CACHE: tuple[float, dict] | None = None
_BRIEF_CACHE: tuple[float, dict] | None = None


# --------------------------------------------------------------------------- #
# Anahtar saklama
# --------------------------------------------------------------------------- #
def mask_key(value: str) -> str:
    """Anahtarı panelde gösterilebilir hale getirir: ilk 4 … son 4."""
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= 8:
        return "*" * len(text)
    return f"{text[:4]}…{text[-4:]}"


async def get_api_key() -> Optional[str]:
    """Ortam değişkeni önce, yoksa şifreli kayıt. Değer loglanmaz."""
    env = (os.getenv("CMC_API_KEY") or "").strip()
    if env:
        return env
    stored = await database.get_llm_setting(SETTINGS_KEY)
    if not stored:
        return None
    try:
        return decrypt_key(stored, "LLM_ENCRYPTION_KEY", "BINANCE_ENCRYPTION_KEY")
    except Exception as exc:  # anahtar değişmiş/bozulmuş olabilir
        logger.warning("CMC anahtarı çözülemedi: %s", type(exc).__name__)
        return None


def _encrypt(value: str) -> str:
    try:
        return encrypt_key(value, "LLM_ENCRYPTION_KEY", "BINANCE_ENCRYPTION_KEY")
    except Exception as exc:
        raise RuntimeError(
            "Şifreleme anahtarı tanımlı değil (LLM_ENCRYPTION_KEY veya "
            "BINANCE_ENCRYPTION_KEY). Anahtar düz metin saklanmaz."
        ) from exc


async def save_api_key(raw_key: str) -> None:
    key = str(raw_key or "").strip()
    if not key:
        raise ValueError("API anahtarı boş olamaz")
    await database.set_llm_setting(SETTINGS_KEY, _encrypt(key))
    await _ledger_reset(key_changed=True)


async def delete_api_key() -> None:
    await database.set_llm_setting(SETTINGS_KEY, "")
    await _ledger_reset(key_changed=True)


async def key_status() -> dict:
    env = (os.getenv("CMC_API_KEY") or "").strip()
    key = env or await get_api_key()
    return {
        "configured": bool(key),
        "masked": mask_key(key),
        "source": "env" if env else ("settings" if key else None),
    }


# --------------------------------------------------------------------------- #
# Yerel kullanım sayacı
# --------------------------------------------------------------------------- #
def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


async def _ledger_load() -> dict:
    raw = await database.get_llm_setting(LEDGER_KEY)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


async def _ledger_reset(key_changed: bool = False) -> None:
    previous = await _ledger_load()
    payload = {
        "date": _today(),
        "requests": 0,
        "credits": 0,
        "last_ok_ts": previous.get("last_ok_ts"),
        "last_error": None,
    }
    if key_changed:
        payload["key_changed_ts"] = time.time()
    await database.set_llm_setting(LEDGER_KEY, json.dumps(payload))


async def _ledger_add(credits: int, error: str | None = None) -> None:
    data = await _ledger_load()
    if data.get("date") != _today():
        data = {"date": _today(), "requests": 0, "credits": 0,
                "last_ok_ts": data.get("last_ok_ts")}
    data["requests"] = int(data.get("requests") or 0) + 1
    data["credits"] = int(data.get("credits") or 0) + max(1, int(credits))
    if error:
        data["last_error"] = error
    else:
        data["last_ok_ts"] = time.time()
    await database.set_llm_setting(LEDGER_KEY, json.dumps(data))


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
def _scrub(text: str, key: str) -> str:
    """Hata metninden anahtarı temizler.

    CMC normalde anahtarı yanıtta yankılamaz; yine de üçüncü taraf hata
    gövdeleri/ara katmanlar yankılayabilir. Log'a ve panele tam anahtar
    düşmemesi için her hata metni buradan geçer.
    """
    out = str(text or "")
    token = str(key or "").strip()
    if token and token in out:
        out = out.replace(token, mask_key(token))
    return out


def _http_get(path: str, params: dict | None = None, key: str = "",
              timeout: float = 6.0) -> dict:
    """Tek GET isteği. Dönüş: {"ok": bool, "data": ..., "error": str|None, "status": int}."""
    url = f"{BASE_URL}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"
    req = Request(url, headers={
        KEY_HEADER: key,
        "Accept": "application/json",
        "User-Agent": "ScalperAgent/4.0",
    })
    try:
        with urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        status = payload.get("status") if isinstance(payload, dict) else None
        return {"ok": True, "data": payload.get("data"), "status": 200,
                "error": None if not status else status.get("error_message")}
    except HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            pass
        msg = f"HTTP {exc.code}"
        try:
            parsed = json.loads(body)
            err = (parsed.get("status") or {}).get("error_message")
            code = (parsed.get("status") or {}).get("error_code")
            if err:
                msg = f"HTTP {exc.code} ({code}): {err}"
        except Exception:
            if body:
                msg = f"HTTP {exc.code}: {body}"
        return {"ok": False, "data": None, "status": exc.code, "error": _scrub(msg, key)}
    except (URLError, TimeoutError, OSError) as exc:
        return {"ok": False, "data": None, "status": 0, "error": _scrub(f"ağ: {exc}", key)}
    except Exception as exc:  # JSON bozuk vb.
        return {"ok": False, "data": None, "status": 0,
                "error": _scrub(f"{type(exc).__name__}: {exc}", key)}


def _keyless_allowed() -> bool:
    """Anahtarsız (`/public-api`) yola izin var mı?

    VARSAYILAN KAPALI: anahtarsız yol IP bazlı ortak havuzdur; tarama döngüsü
    onu her turda çağırırsa 429 yer ve radar yavaşlar. Anahtar yokken CMC
    katmanı tamamen sessiz kalır; isteyen `CMC_ALLOW_KEYLESS=1` ile açar.
    """
    return (os.getenv("CMC_ALLOW_KEYLESS", "0") or "0").strip().lower() in {
        "1", "true", "yes", "on"
    }


async def _call(path: str, params: dict | None = None, credits: int = 1,
                public_ok: bool = False) -> dict:
    """Anahtarlı çağrı; anahtar yoksa (public_ok + izin) anahtarsız yola düşer.

    Anahtarsız yol (`/public-api`) IP bazlı ortak havuzdur ve yalnız temel
    uç noktaları destekler; trending/ATH/haber orada yoktur.
    """
    key = await get_api_key()
    if not key:
        if not (public_ok and _keyless_allowed()):
            return {"ok": False, "data": None, "status": 0,
                    "error": "CMC API anahtarı tanımlı değil"}
    if not await _budget_ok(credits):
        return {"ok": False, "data": None, "status": 0,
                "error": "günlük CMC kredi bütçesi doldu (CMC_DAILY_CREDIT_BUDGET)"}
    url_path = path if key else f"/public-api{path}"
    result = await asyncio.to_thread(_http_get, url_path, params, key)
    await _ledger_add(credits, None if result["ok"] else result["error"])
    if not result["ok"]:
        logger.info("CMC %s başarısız: %s", path, result["error"])
    return result


# --------------------------------------------------------------------------- #
# Kredi bütçesi
# --------------------------------------------------------------------------- #
def _daily_budget() -> int:
    try:
        return max(0, int(os.getenv("CMC_DAILY_CREDIT_BUDGET", "400")))
    except ValueError:
        return 400


async def _budget_ok(credits: int) -> bool:
    """Günlük yumuşak bütçe: planı yakmadan taranmayı sürdürmek için.

    Aylık limitin kendisi CMC'de; buradaki amaç radarın her taramada kredi
    tüketmesini engellemek. Bütçe dolunca çağrı yapılmaz, önbellek kullanılır.
    """
    budget = _daily_budget()
    if budget <= 0:
        return True
    ledger = await _ledger_load()
    used = int(ledger.get("credits") or 0) if ledger.get("date") == _today() else 0
    return used + max(1, credits) <= budget


# --------------------------------------------------------------------------- #
# Kota / plan bilgisi
# --------------------------------------------------------------------------- #
def _plan_from_info(data: Any) -> dict:
    """key/info yanıtını panelde gösterilecek sade yapıya çevirir.

    Alan adları CMC sürümüne göre değişebildiği için savunmacı okunur; eksik
    alan None döner, uydurulmaz.
    """
    if not isinstance(data, dict):
        return {}
    plan = data.get("plan") or {}
    usage = data.get("usage") or {}
    minute = usage.get("current_minute") or {}
    day = usage.get("current_day") or {}
    month = usage.get("current_month") or {}
    return {
        "plan_id": plan.get("credit_limit_monthly") and plan.get("id"),
        "monthly_credit_limit": plan.get("credit_limit_monthly"),
        "monthly_reset": plan.get("credit_limit_monthly_reset"),
        "monthly_reset_ts": plan.get("credit_limit_monthly_reset_timestamp"),
        "minute_rate_limit": plan.get("rate_limit_minute"),
        "minute_requests_made": minute.get("requests_made"),
        "minute_requests_left": minute.get("requests_left"),
        "day_credits_used": day.get("credits_used"),
        "day_credits_left": day.get("credits_left"),
        "month_credits_used": month.get("credits_used"),
        "month_credits_left": month.get("credits_left"),
    }


async def validate_key(candidate: str, timeout: float = 8.0) -> dict:
    """KAYDETMEDEN ÖNCE anahtarı dener: geçerliyse plan bilgisini döner.

    Kayıtlı anahtarı kullanmaz; adayı doğrudan header'a koyar. Aday anahtar
    loglanmaz ve dönüşte yer almaz.
    """
    key = str(candidate or "").strip()
    if not key:
        return {"ok": False, "error": "API anahtarı boş", "plan": {}}
    result = await asyncio.to_thread(_http_get, "/v1/key/info", None, key, timeout)
    return {
        "ok": bool(result["ok"]),
        "error": None if result["ok"] else _scrub(result["error"] or "", key),
        "plan": _plan_from_info(result["data"]) if result["ok"] else {},
    }


async def key_info(force: bool = False) -> dict:
    """`/v1/key/info` — plan limitleri ve kalan kredi (60 sn önbellek)."""
    global _KEY_INFO_CACHE
    now = time.time()
    if not force and _KEY_INFO_CACHE and (now - _KEY_INFO_CACHE[0]) < KEY_INFO_TTL:
        return _KEY_INFO_CACHE[1]
    result = await _call("/v1/key/info", credits=1)
    info = {"ok": result["ok"], "error": result["error"],
            "plan": _plan_from_info(result["data"]) if result["ok"] else {},
            "fetched_at": now}
    _KEY_INFO_CACHE = (now, info)
    return info


async def quota() -> dict:
    """Panel için kota özeti: canlı plan bilgisi + yerel sayaç."""
    info = await key_info()
    ledger = await _ledger_load()
    local = {
        "date": ledger.get("date"),
        "requests": int(ledger.get("requests") or 0),
        "credits": int(ledger.get("credits") or 0),
        "last_ok_ts": ledger.get("last_ok_ts"),
        "last_error": ledger.get("last_error"),
    }
    return {
        "plan": info.get("plan") or {},
        "live_ok": bool(info.get("ok")),
        "live_error": info.get("error"),
        "local": local,
    }


# --------------------------------------------------------------------------- #
# Radar bağlamı
# --------------------------------------------------------------------------- #
def _fear_greed(data: Any) -> Optional[dict]:
    if isinstance(data, list) and data:
        data = data[0]
    if not isinstance(data, dict):
        return None
    return {
        "value": data.get("value"),
        "classification": data.get("value_classification"),
        "updated": data.get("update_time") or data.get("timestamp"),
    }


def _global(data: Any) -> Optional[dict]:
    if not isinstance(data, dict):
        return None
    quotes = (data.get("quote") or {}).get("USD") or {}
    return {
        "market_cap_usd": quotes.get("total_market_cap"),
        "volume_24h_usd": quotes.get("total_volume_24h"),
        "btc_dominance": data.get("btc_dominance"),
        "eth_dominance": data.get("eth_dominance"),
        "market_cap_change_24h": quotes.get("total_market_cap_yesterday_percentage_change"),
    }


def _symbols(rows: Any, limit: int = 10) -> list[dict]:
    out: list[dict] = []
    if isinstance(rows, dict):
        rows = rows.get("gainers") or []
    for row in (rows or [])[:limit]:
        if not isinstance(row, dict):
            continue
        quote = ((row.get("quote") or {}).get("USD") or {})
        out.append({
            "symbol": row.get("symbol"),
            "name": row.get("name"),
            "cmc_id": row.get("id"),
            "price": quote.get("price"),
            "change_1h": quote.get("percent_change_1h"),
            "change_24h": quote.get("percent_change_24h"),
            "volume_24h": quote.get("volume_24h"),
        })
    return out


async def brief(force: bool = False) -> dict:
    """Radar için piyasa geneli özet (5 dk önbellek).

    Alt çağrılar bağımsızdır: plan kısıtı olan uç nokta boş dönerse diğer
    alanlar yine dolu gelir ve o alan `None` olur.
    """
    global _BRIEF_CACHE
    now = time.time()
    if not force and _BRIEF_CACHE and (now - _BRIEF_CACHE[0]) < BRIEF_TTL:
        return _BRIEF_CACHE[1]

    fng = await _call("/v3/fear-and-greed/latest", credits=1, public_ok=True)
    glob = await _call("/v1/global-metrics/quotes/latest", credits=1, public_ok=True)
    trending = await _call("/v1/cryptocurrency/trending/latest", {"limit": 10}, credits=2)
    movers = await _call("/v1/cryptocurrency/trending/gainers-losers", {"limit": 10}, credits=2)

    payload = {
        "fetched_at": now,
        "fear_greed": _fear_greed(fng["data"]) if fng["ok"] else None,
        "global": _global(glob["data"]) if glob["ok"] else None,
        "trending": _symbols(trending["data"]) if trending["ok"] else None,
        "gainers": _symbols(movers["data"], 10) if movers["ok"] else None,
        "errors": {name: res["error"] for name, res in
                   (("fear_greed", fng), ("global", glob),
                    ("trending", trending), ("movers", movers)) if not res["ok"]},
    }
    _BRIEF_CACHE = (now, payload)
    return payload


# --------------------------------------------------------------------------- #
# Radar zenginleştirme: sembol profili (rank, hacim, çoklu periyot, ATH mesafesi)
# --------------------------------------------------------------------------- #
QUOTE_TTL = 120.0
PERF_TTL = 1800.0

#: Binance sembolünden taban varlığı ayırmak için kote birimleri. Sıra önemli:
#: uzun ekler önce denenir (USDT, FDUSD… ) ki "BTC" gibi kısa ek yanlış kesmesin.
QUOTE_SUFFIXES = ("FDUSD", "TUSD", "USDC", "USDT", "TRY", "BTC", "ETH", "BNB", "EUR")

_QUOTES_CACHE: dict[str, tuple[float, dict]] = {}
_PERF_CACHE: dict[str, tuple[float, dict]] = {}


def base_asset(symbol: str) -> str:
    """`OPGTRY` → `OPG`, `BTCUSDT` → `BTC`, `1000SATSUSDT` → `1000SATS`."""
    text = str(symbol or "").replace("_", "").upper()
    for suffix in QUOTE_SUFFIXES:
        if text.endswith(suffix) and len(text) > len(suffix):
            return text[: -len(suffix)]
    return text


def _quote_usd(row: dict) -> dict:
    """v3 yanıtında `quote` LİSTE, v1'de SÖZLÜK olabilir; ikisini de okur."""
    quote = row.get("quote")
    if isinstance(quote, list):
        quote = next((q for q in quote if isinstance(q, dict)
                      and str(q.get("symbol") or "").upper() == "USD"), None) or {}
    return quote if isinstance(quote, dict) else {}


def _compact_quote(row: dict) -> dict:
    q = _quote_usd(row)
    price = q.get("price")
    ath = row.get("_ath")
    ath_distance = None
    if price and ath:
        try:
            ath_distance = round((float(price) / float(ath) - 1) * 100, 2)
        except (TypeError, ValueError, ZeroDivisionError):
            ath_distance = None
    return {
        "cmc_id": row.get("id"),
        "slug": row.get("slug"),
        "rank": row.get("cmc_rank") or row.get("rank"),
        "price_usd": price,
        "market_cap_usd": q.get("market_cap"),
        "volume_24h_usd": q.get("volume_24h"),
        "volume_change_24h_pct": q.get("volume_change_24h"),
        "pct_1h": q.get("percent_change_1h"),
        "pct_24h": q.get("percent_change_24h"),
        "pct_7d": q.get("percent_change_7d"),
        "pct_30d": q.get("percent_change_30d"),
        "dominance": q.get("market_cap_dominance"),
        "ath_usd": ath,
        "ath_distance_pct": ath_distance,
        "updated_at": q.get("last_updated"),
    }


async def quotes_map(symbols: list[str]) -> dict:
    """Taban varlık → kompakt CMC profili. Tek HTTP çağrısı, 120 sn önbellek.

    Sembol çoklu eşleşirse CMC en yüksek piyasa değerli olanı döner; bu, radar
    için doğru varsayımdır (ör. birden çok "SOL" yoksa sorun yok).
    """
    wanted = [str(s).upper() for s in dict.fromkeys(base_asset(s) for s in symbols or []) if s]
    if not wanted:
        return {}
    now = time.time()
    out: dict[str, dict] = {}
    missing: list[str] = []
    for sym in wanted:
        cached = _QUOTES_CACHE.get(sym)
        if cached and (now - cached[0]) < QUOTE_TTL:
            out[sym] = cached[1]
        else:
            missing.append(sym)
    if missing:
        result = await _call("/v3/cryptocurrency/quotes/latest",
                             {"symbol": ",".join(missing), "convert": "USD",
                              "skip_invalid": "true"},
                             credits=max(1, len(missing) // 250 + 1), public_ok=True)
        if result["ok"]:
            data = result["data"] or {}
            rows = data.values() if isinstance(data, dict) else data
            for row in rows:
                if not isinstance(row, dict):
                    continue
                sym = str(row.get("symbol") or "").upper()
                if not sym:
                    continue
                compact = _compact_quote(row)
                _QUOTES_CACHE[sym] = (now, compact)
                if sym in missing:
                    out[sym] = compact
    return out


async def performance_map(symbols: list[str]) -> dict:
    """ATH/ATL bilgisi (`price-performance-stats`). 30 dk önbellek.

    Anahtarsız erişilemez ve plan yetmezse 403 döner; bu durumda boş sözlük
    döner ve `ath_distance_pct` alanı None kalır. Uydurma yok.
    """
    wanted = [str(s).upper() for s in dict.fromkeys(base_asset(s) for s in symbols or []) if s]
    if not wanted:
        return {}
    now = time.time()
    out: dict[str, dict] = {}
    missing: list[str] = []
    for sym in wanted:
        cached = _PERF_CACHE.get(sym)
        if cached and (now - cached[0]) < PERF_TTL:
            out[sym] = cached[1]
        else:
            missing.append(sym)
    if missing:
        result = await _call("/v2/cryptocurrency/price-performance-stats/latest",
                             {"symbol": ",".join(missing), "convert": "USD",
                              "skip_invalid": "true", "time_period": "all_time"},
                             credits=max(1, len(missing) // 250 + 1))
        if result["ok"]:
            data = result["data"] or {}
            rows = data.values() if isinstance(data, dict) else data
            for row in rows:
                if not isinstance(row, dict):
                    continue
                sym = str(row.get("symbol") or "").upper()
                periods = (row.get("periods") or {}).get("all_time") or {}
                high = periods.get("high")
                quote = row.get("quote") or {}
                if isinstance(quote, list):
                    quote = next((q for q in quote if isinstance(q, dict)), {}) or {}
                price = quote.get("price")
                dist = None
                if high and price:
                    try:
                        dist = round((float(price) / float(high) - 1) * 100, 2)
                    except (TypeError, ValueError, ZeroDivisionError):
                        dist = None
                compact = {"ath_usd": high, "atl_usd": periods.get("low"),
                           "ath_distance_pct": dist}
                if sym:
                    _PERF_CACHE[sym] = (now, compact)
                    if sym in missing:
                        out[sym] = compact
    return out


def _flags(profile: dict, ath: dict | None) -> list[str]:
    """Radar/LLM için yorumlanmış bayraklar. Eşikler muhafazakâr seçildi."""
    flags: list[str] = []
    try:
        vol_chg = profile.get("volume_change_24h_pct")
        if vol_chg is not None and float(vol_chg) >= 100:
            flags.append("HACIM_PATLAMASI")
        pct7 = profile.get("pct_7d")
        if pct7 is not None and float(pct7) >= 40:
            flags.append("7G_ASIRI_ISINMA")
        if pct7 is not None and float(pct7) <= -25:
            flags.append("7G_SERT_DUSUS")
        dist = (ath or {}).get("ath_distance_pct") or profile.get("ath_distance_pct")
        if dist is not None and float(dist) >= -3:
            flags.append("ATH_YAKIN")
        rank = profile.get("rank")
        if rank is not None and float(rank) > 300:
            flags.append("DUSUK_SIRALAMA")
    except (TypeError, ValueError):
        pass
    return flags


async def attach_market_context(rows: list[dict], top_n: int = 15) -> dict:
    """Tarama satırlarına CMC profilini ekler (satır içinde `cmc`, `cmc_flags`).

    NEDEN: radar yalnız Binance fiyat/hacmiyle çalışıyordu; aynı hareket, piyasa
    değeri 5 milyon dolarlık bir token'da ve 5 milyar dolarlık bir token'da çok
    farklı davranır. CMC profili bu bağlamı tek bakışta verir.

    MALİYET: yalnız en yüksek skorlu `top_n` satır, en fazla 2 HTTP çağrısı
    (quotes + performance), 120 sn/30 dk önbellek. Anahtar yoksa anahtarsız yol
    denenir; o da olmazsa satırlar dokunulmadan döner.
    """
    if not rows:
        return {"enriched": 0}
    ordered = sorted(rows, key=lambda r: float(r.get("unified_score") or r.get("scan_score") or 0),
                     reverse=True)[:max(1, top_n)]
    symbols = [str(r.get("symbol") or "") for r in ordered]
    profiles = await quotes_map(symbols)
    if not profiles:
        return {"enriched": 0, "reason": "CMC verisi yok"}
    perf = await performance_map(symbols)
    enriched = 0
    for row in ordered:
        sym = base_asset(str(row.get("symbol") or ""))
        profile = profiles.get(sym)
        if not profile:
            continue
        ath = perf.get(sym)
        merged = dict(profile)
        if ath:
            merged.update({k: v for k, v in ath.items() if v is not None})
        row["cmc"] = merged
        row["cmc_flags"] = _flags(merged, ath)
        enriched += 1
    return {"enriched": enriched, "requested": len(ordered)}


async def news(symbol: str | None = None, limit: int = 5) -> list[dict]:
    """Son haber başlıkları (`/v1/content/latest`, 0 kredi). Plan yetmezse boş."""
    params = {"limit": max(1, min(20, limit)), "news_type": "news"}
    if symbol:
        params["symbol"] = base_asset(symbol)
    result = await _call("/v1/content/latest", params, credits=1)
    if not result["ok"]:
        return []
    out = []
    for item in (result["data"] or [])[:limit]:
        if not isinstance(item, dict):
            continue
        out.append({
            "title": item.get("title"),
            "source": item.get("source_name"),
            "url": item.get("source_url"),
            "published_at": item.get("released_at") or item.get("created_at"),
        })
    return out
