"""Yerel sahte Binance TR sunucusu (yalnız testler). GERÇEK BORSAYA İSTEK YOK."""
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


def _ok(data):
    return {"code": 0, "data": data}


class FakeBinanceTR:
    def __init__(self, price=100.0, free_try=1000.0):
        self.price, self.free_try = price, free_try
        self.requests = []            # (method, path, params)
        self.fill_fraction = 1.0
        self.oco_error = None         # {"code": 3210, "msg": "..."} döndürür
        self.buy_error = None
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
                raw = json.dumps(outer.route(method, u.path, params)).encode()
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

    def route(self, method, path, params):
        if path == "/open/v1/common/time":
            return _ok({"serverTime": int(time.time() * 1000)})
        if path == "/open/v1/common/symbols":
            return _ok(SYMBOLS)
        if path == "/open/v1/account/spot":
            return _ok({"accountAssets": [{"asset": "TRY", "free": str(self.free_try), "locked": "0"}]})
        if method == "POST" and path == "/open/v1/orders":
            if self.buy_error:
                return self.buy_error
            return _ok({"orderId": 555, "symbol": params.get("symbol")})
        if method == "GET" and path == "/open/v1/orders/detail":
            quote = float(self._last_buy().get("quoteOrderQty", 0))
            qty = int(quote / self.price * 0.999 * self.fill_fraction * 100) / 100
            return _ok({"status": 2, "executedQty": str(qty),
                        "cummulativeQuoteQty": str(round(qty * self.price, 2))})
        if method == "POST" and path == "/open/v1/orders/oco":
            if self.oco_error:
                return self.oco_error
            return _ok({"orderListId": 900, "orders": []})
        return {"code": 404, "msg": f"bilinmeyen uç {path}"}

    def _last_buy(self):
        for m, p, prm in reversed(self.requests):
            if m == "POST" and p == "/open/v1/orders":
                return prm
        return {}

    def calls(self, method, path):
        return [prm for m, p, prm in self.requests if m == method and p == path]
