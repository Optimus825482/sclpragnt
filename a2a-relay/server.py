import hashlib
import hmac
import json
import os
import time
import urllib.request
from urllib.parse import urlsplit, urlunsplit
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SECRET = os.getenv("A2A_SHARED_SECRET", "").strip()
PEER_URL = os.getenv("A2A_PEER_URL", "").strip()
BACKEND_URL = (os.getenv("A2A_BACKEND_URL", "").strip()
               or os.getenv("SCALPER_A2A_URL", "").strip())
LOG_PATH = os.getenv("A2A_LOG_PATH", "/data/a2a-relay.jsonl")


def valid_signature(body, supplied):
    if not SECRET:
        return False
    expected = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    return bool(supplied) and hmac.compare_digest(supplied, expected)


def append_log(message, direction, status):
    record = {"received_at": time.time(), "direction": direction, "status": status, "message": message}
    os.makedirs(os.path.dirname(LOG_PATH) or ".", exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def forward(url, message):
    if not url:
        return {"forwarded": False, "reason": "peer_url_not_configured"}
    body = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode()
    request = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "X-A2A-Signature": "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest(),
        "X-A2A-Message-Id": str(message.get("message_id") or ""),
    })
    with urllib.request.urlopen(request, timeout=10) as response:
        return {"forwarded": 200 <= response.status < 300, "status_code": response.status}


def route_target(message):
    """Route responses/research to Scalper and Scalper events to its peer."""
    recipient = str(message.get("to") or "").strip().lower()
    if recipient.startswith("scalper"):
        return BACKEND_URL
    return PEER_URL


def backend_route_url(request_path):
    """Map a public A2A API path onto the configured backend A2A base."""
    target = urlsplit(BACKEND_URL)
    incoming = urlsplit(request_path)
    marker = "/api/a2a/"
    target_base = target.path.split(marker, 1)[0] if marker in target.path else target.path.rstrip("/")
    return urlunsplit((target.scheme, target.netloc, target_base + incoming.path,
                       incoming.query, ""))


def proxy_backend(request_path, *, body=None, method="GET", headers=None):
    request = urllib.request.Request(
        backend_route_url(request_path), data=body, method=method,
        headers=headers or {},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = response.read()
        return int(response.status), json.loads(payload) if payload else {"ok": True}


class Handler(BaseHTTPRequestHandler):
    @staticmethod
    def is_message_path(path):
        return urlsplit(path).path.rstrip("/") in {"/api/a2a/messages", "/messages"}

    def json_response(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self.json_response(200, {"ok": True, "service": "a2a-relay", "paper_only": True, "peer_configured": bool(PEER_URL), "backend_configured": bool(BACKEND_URL)})
        elif self.is_message_path(self.path) and BACKEND_URL:
            try:
                status, payload = proxy_backend(self.path)
                self.json_response(status, payload)
            except Exception as exc:
                self.json_response(502, {"ok": False, "error": f"backend_a2a_unavailable: {exc}"})
        else:
            self.json_response(404, {"ok": False})

    def do_POST(self):
        if not self.is_message_path(self.path):
            if urlsplit(self.path).path.startswith("/api/a2a/") and BACKEND_URL:
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                try:
                    status, payload = proxy_backend(
                        self.path, body=body, method="POST",
                        headers={"Content-Type": self.headers.get("Content-Type", "application/json")},
                    )
                    self.json_response(status, payload)
                except Exception as exc:
                    self.json_response(502, {"ok": False, "error": f"backend_a2a_unavailable: {exc}"})
            else:
                self.json_response(404, {"ok": False})
            return
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        if not valid_signature(body, self.headers.get("X-A2A-Signature")):
            self.json_response(401, {"ok": False, "error": "invalid_a2a_signature"})
            return
        try:
            message = json.loads(body)
        except json.JSONDecodeError:
            self.json_response(400, {"ok": False, "error": "invalid_json"})
            return
        if (message.get("protocol") != "a2a" or message.get("paper_only") is not True
                or not message.get("message_id") or not message.get("type") or not message.get("to")):
            self.json_response(400, {"ok": False, "error": "paper_only_a2a_message_required"})
            return
        try:
            created_at = float(message.get("created_at"))
        except (TypeError, ValueError):
            self.json_response(400, {"ok": False, "error": "a2a_created_at_required"})
            return
        if abs(time.time() - created_at) > 300:
            self.json_response(400, {"ok": False, "error": "stale_a2a_message"})
            return
        try:
            destination = "backend" if str(message.get("to")).lower().startswith("scalper") else "peer"
            delivery = forward(route_target(message), message)
            append_log(message, "inbound", "forwarded" if delivery.get("forwarded") else "queued")
            self.json_response(202, {"ok": True, "message_id": message.get("message_id"), "paper_only": True,
                                     "destination": destination, "delivery": delivery})
        except Exception as exc:
            append_log(message, "inbound", "error")
            self.json_response(202, {"ok": True, "message_id": message.get("message_id"), "paper_only": True, "queued": True, "error": str(exc)})


if __name__ == "__main__":
    if not SECRET:
        raise SystemExit("A2A_SHARED_SECRET gerekli")
    ThreadingHTTPServer(("0.0.0.0", int(os.getenv("PORT", "8010"))), Handler).serve_forever()
