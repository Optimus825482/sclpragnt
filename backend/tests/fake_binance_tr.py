"""Yerel sahte Binance TR sunucusu (yalnız testler). GERÇEK BORSAYA İSTEK YOK.

Sözleşme kaynağı: https://www.binance.tr/apidocs/ (2026-10-18 anlık görüntüsü,
bkz. work/binance_tr_docs_audit/). Sahte sunucu belgelenmiş sözleşmeyi uygular:
imza (HMAC SHA256, query string), timestamp/recvWindow kuralı, emir tipine göre
zorunlu parametreler, OCO parametre adları ve belgelenmiş cevap alanları.
Belgelenmemiş parametre gönderilirse {"code": 1100} ile reddeder (strict).
"""
import hashlib
import hmac
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

SYMBOLS = {"list": [{
    "symbol": "ADA_TRY", "quoteAsset": "TRY", "status": "TRADING", "ocoEnable": 1,
    "filters": [
        {"filterType": "LOT_SIZE", "stepSize": "0.01", "minQty": "0.01"},
        {"filterType": "NOTIONAL", "minNotional": "10"},
        {"filterType": "PRICE_FILTER", "tickSize": "0.01", "minPrice": "0.01", "maxPrice": "100000"},
    ]}]}

# --- Belgelenmiş sözleşme (apidocs: "Account endpoints") -------------------
_COMMON = {"recvWindow", "timestamp", "signature"}
ORDER_PARAMS = {"symbol", "side", "type", "quantity", "quoteOrderQty", "price", "clientId", "stopPrice",
                "icebergQty", "timeInForce", "selfTradePreventionMode"} | _COMMON
# OCO'da tekil `clientId` / `type` YOK: listClientId, limitClientId, stopClientId.
OCO_PARAMS = {"symbol", "listClientId", "side", "quantity", "limitClientId", "price", "stopClientId",
              "stopPrice", "stopLimitPrice"} | _COMMON
OCO_REQUIRED = ("symbol", "side", "quantity", "price", "stopPrice", "stopLimitPrice")
# Detay/iptal: belgede yalnız orderId | clientId. `symbol` belgesiz ama istemci gönderiyor (UNVERIFIED) → tolere.
DETAIL_PARAMS = {"orderId", "clientId", "symbol"} | _COMMON
# type -> zorunlu ek parametreler (belge tablosu)
TYPE_REQUIRED = {"1": ("quantity", "price"), "3": ("quantity", "stopPrice"),
                 "4": ("quantity", "price", "stopPrice"), "5": ("quantity", "stopPrice"),
                 "6": ("quantity", "price", "stopPrice"), "7": ("quantity", "price")}


def _ok(data):
    return {"code": 0, "message": "success", "data": data, "timestamp": int(time.time() * 1000)}


def _err(code, msg):
    return {"code": code, "msg": msg, "timestamp": int(time.time() * 1000)}


class FakeBinanceTR:
    def __init__(self, price=100.0, free_try=1000.0, api_key=None, secret=None):
        self.price, self.free_try = price, free_try
        self.api_key, self.secret = api_key, secret
        self.requests = []            # (method, path, params)
        self.headers = []             # istek başına başlıklar (X-MBX-APIKEY denetimi)
        self.fill_fraction = 1.0
        self.oco_error = None         # {"code": 3210, "msg": "..."} döndürür
        self.buy_error = None
        # 2026-10-18: bu öneklerle başlayan clientId/listClientId 3703 "Invalid client ID" ile reddedilir (kural belgesiz).
        self.reject_client_id_prefixes = ()
        self._srv = None

    def start(self) -> str:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _handle(self, method):
                u = urlparse(self.path)
                params = {k: v[0] for k, v in parse_qs(u.query).items()}
                outer.requests.append((method, u.path, params))
                hdrs = {k.lower(): v for k, v in self.headers.items()}
                outer.headers.append(hdrs)
                body = outer.route(method, u.path, params, raw_query=u.query, headers=hdrs)
                raw = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                self._handle("GET")

            def do_POST(self):
                self._handle("POST")

        self._srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._srv.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{self._srv.server_address[1]}"

    def stop(self):
        if self._srv:
            self._srv.shutdown()
            self._srv.server_close()

    # -- belgelenmiş imza / zaman kuralları ---------------------------------
    def _check_signed(self, params, raw_query, headers):
        if self.api_key is not None and headers.get("x-mbx-apikey") != self.api_key:
            return _err(-2015, "Invalid API-key (X-MBX-APIKEY başlığı eksik/yanlış)")
        sig = params.get("signature")
        if not sig or "timestamp" not in params:
            return _err(-1102, "signature ve timestamp zorunlu")
        if self.secret is not None:
            total = raw_query.rsplit("&signature=", 1)[0]       # totalParams = query string (+ gövde: boş)
            want = hmac.new(self.secret.encode(), total.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(want, sig.lower()):
                return _err(-1022, "Signature for this request is not valid")
        recv = int(params.get("recvWindow", 5000))
        if recv > 60000:
            return _err(-1128, "recvWindow 60000'i aşamaz")
        now_ms, ts = int(time.time() * 1000), int(params["timestamp"])
        if not (ts < now_ms + 1000 and now_ms - ts <= recv):     # belgedeki kural
            return _err(-1021, "Timestamp outside recvWindow")
        return None

    def route(self, method, path, params, raw_query="", headers=None):
        headers = headers or {}
        if path == "/open/v1/common/time":
            return {"code": 0, "msg": "success", "timestamp": int(time.time() * 1000)}   # belge: data yok
        if path == "/open/v1/common/symbols":
            return _ok(SYMBOLS)
        if path.startswith("/open/v1/"):
            bad = self._check_signed(params, raw_query, headers)
            if bad:
                return bad
        if path == "/open/v1/account/spot":
            return _ok({"accountAssets": [{"asset": "TRY", "free": str(self.free_try), "locked": "0"}]})
        if method == "POST" and path == "/open/v1/orders":
            if self.buy_error:
                return self.buy_error
            bad = self._validate_order(params)
            if bad:
                return bad
            if str(params.get("clientId") or "").startswith(tuple(self.reject_client_id_prefixes) or ("\x00",)):
                return _err(3703, "Invalid client ID")
            return _ok({"orderId": "555", "createTime": int(time.time() * 1000)})   # belge: orderId + createTime
        if method == "GET" and path == "/open/v1/orders/detail":
            extra = set(params) - DETAIL_PARAMS
            if extra:
                return _err(1100, f"belgesiz parametre: {sorted(extra)}")
            if not (params.get("orderId") or params.get("clientId")):
                return _err(1102, "orderId veya clientId zorunlu")
            last = self._last_buy()
            quote = float(last.get("quoteOrderQty", 0))
            qty = int(quote / self.price * 0.999 * self.fill_fraction * 100) / 100
            # Belgelenmiş alan adları: executedQty / executedPrice / executedQuoteQty (cummulativeQuoteQty YOK).
            return _ok({"orderId": 555, "orderListId": -1, "clientId": last.get("clientId", ""),
                        "symbol": last.get("symbol", "ADA_TRY"), "side": 0, "type": 2, "price": 0,
                        "status": 2, "origQty": 0, "origQuoteQty": quote, "executedQty": str(qty),
                        "executedPrice": self.price, "executedQuoteQty": str(round(qty * self.price, 2)),
                        "createTime": int(time.time() * 1000)})
        if method == "POST" and path == "/open/v1/orders/cancel":
            extra = set(params) - DETAIL_PARAMS
            if extra:
                return _err(1100, f"belgesiz parametre: {sorted(extra)}")
            if not (params.get("orderId") or params.get("clientId")):
                return _err(1102, "orderId veya clientId zorunlu")
            return _ok({"orderId": int(params.get("orderId") or 555), "status": 3})
        if method == "POST" and path == "/open/v1/orders/oco":
            if self.oco_error:
                return self.oco_error
            extra = set(params) - OCO_PARAMS
            if extra:
                return _err(1100, f"OCO için belgesiz parametre: {sorted(extra)}")
            missing = [k for k in OCO_REQUIRED if not params.get(k)]
            if missing:
                return _err(1102, f"OCO zorunlu parametre eksik: {missing}")
            if params["side"] not in ("0", "1"):
                return _err(1100, "side 0|1 olmalı")
            return _ok({"orderId": "900", "createTime": int(time.time() * 1000)})   # belge: orderId + createTime
        return {"code": 404, "msg": f"bilinmeyen uç {path}"}

    @staticmethod
    def _validate_order(p):
        extra = set(p) - ORDER_PARAMS
        if extra:
            return _err(1100, f"belgesiz parametre: {sorted(extra)}")
        if "_" not in p.get("symbol", ""):
            return _err(1100, "symbol alt çizgili olmalı (ADA_TRY)")
        if p.get("side") not in ("0", "1"):
            return _err(1100, "side 0=BUY|1=SELL")
        t = p.get("type")
        if t not in {"1", "2", "3", "4", "5", "6", "7"}:
            return _err(1100, "type 1..7")
        if "timeInForce" in p and p["timeInForce"] not in {"1", "2", "3", "4"}:
            return _err(1100, "timeInForce 1..4")
        if t == "2":
            need = "quantity" if p["side"] == "1" else "quoteOrderQty"      # belge: MARKET sell=quantity, buy=quoteOrderQty
            if not p.get(need):
                return _err(1102, f"MARKET için {need} zorunlu")
        else:
            miss = [k for k in TYPE_REQUIRED[t] if not p.get(k)]
            if miss:
                return _err(1102, f"zorunlu parametre eksik: {miss}")
        return None

    def _last_buy(self):
        for m, p, prm in reversed(self.requests):
            if m == "POST" and p == "/open/v1/orders":
                return prm
        return {}

    def calls(self, method, path):
        return [prm for m, p, prm in self.requests if m == method and p == path]
