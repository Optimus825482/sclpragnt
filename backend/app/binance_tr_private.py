"""Binance TR private (authenticated, read-only) REST adapter.

HMAC-SHA256 imzalı salt-okunur Binance TR endpoint çağrıları.
Paper-only felsefesi: asla emir gönderme, çekim veya trade yapma.
"""
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REST_BASE = "https://api.binance.me"
REST_TIMEOUT_SEC = 15


def _signed_request(method: str, path: str, params: dict | None,
                    api_key: str, api_secret: str) -> dict | list:
    """HMAC-SHA256 imzalı Binance TR isteği (yalnız okuma, emir yok)."""
    params = dict(params or {})
    params["timestamp"] = int(time.time() * 1000)
    query = urlencode(sorted(params.items()))
    signature = hmac.new(api_secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()
    query += f"&signature={signature}"
    url = f"{REST_BASE}{path}?{query}"
    headers = {"X-MBX-APIKEY": api_key}
    req = Request(url, headers=headers, method=method)
    with urlopen(req, timeout=REST_TIMEOUT_SEC) as resp:
        raw = resp.read()
        data = json.loads(raw.decode("utf-8"))
    if isinstance(data, dict) and data.get("code") not in (None, 0):
        raise RuntimeError(f"Binance TR API hatası {data.get('code')}: {data.get('msg', 'bilinmiyor')}")
    return data


def get_account_balance(api_key: str, api_secret: str) -> list[dict]:
    """GET /api/v3/account → balances listesi (salt okunur)."""
    data = _signed_request("GET", "/api/v3/account", None, api_key, api_secret)
    return data.get("balances", [])


def get_open_orders(api_key: str, api_secret: str, symbol: str = "") -> list[dict]:
    """GET /api/v3/openOrders — varsa açık emirler (salt okunur)."""
    params = {}
    if symbol:
        params["symbol"] = symbol
    return _signed_request("GET", "/api/v3/openOrders", params, api_key, api_secret)


def get_trade_history(api_key: str, api_secret: str, symbol: str,
                      start_time: int | None = None, end_time: int | None = None,
                      limit: int = 100, offset: int = 0) -> list[dict]:
    """GET /api/v3/myTrades — geçmiş işlemler (salt okunur, fromId pagination)."""
    params = {"symbol": symbol, "limit": min(max(1, limit), 1000)}
    if start_time:
        params["startTime"] = int(start_time)
    if end_time:
        params["endTime"] = int(end_time)
    if offset > 0:
        params["fromId"] = int(offset)
    trades = _signed_request("GET", "/api/v3/myTrades", params, api_key, api_secret)
    return trades


def get_exchange_info() -> dict:
    """GET /api/v3/exchangeInfo — sembol filtreleri, lot büyüklükleri vb. (public)."""
    url = f"{REST_BASE}/api/v3/exchangeInfo"
    with urlopen(url, timeout=REST_TIMEOUT_SEC) as resp:
        return json.loads(resp.read().decode("utf-8"))