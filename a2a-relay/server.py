import hashlib
import hmac
import json
import os
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SECRET = os.getenv("A2A_SHARED_SECRET", "").strip()
PEER_URL = os.getenv("A2A_PEER_URL", "").strip()
SCALPER_URL = os.getenv("SCALPER_A2A_URL", "").strip()
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
    })
    with urllib.request.urlopen(request, timeout=10) as response:
        return {"forwarded": 200 <= response.status < 300, "status_code": response.status}


class Handler(BaseHTTPRequestHandler):
    def json_response(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self.json_response(200, {"ok": True, "service": "a2a-relay", "paper_only": True, "peer_configured": bool(PEER_URL)})
        else:
            self.json_response(404, {"ok": False})

    def do_POST(self):
        if self.path.rstrip("/") != "/api/a2a/messages":
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
        if message.get("protocol") != "a2a" or message.get("paper_only") is not True:
            self.json_response(400, {"ok": False, "error": "paper_only_a2a_message_required"})
            return
        try:
            peer = forward(PEER_URL, message)
            append_log(message, "inbound", "forwarded" if peer.get("forwarded") else "queued")
            self.json_response(202, {"ok": True, "message_id": message.get("message_id"), "paper_only": True, "peer": peer})
        except Exception as exc:
            append_log(message, "inbound", "error")
            self.json_response(202, {"ok": True, "message_id": message.get("message_id"), "paper_only": True, "queued": True, "error": str(exc)})


if __name__ == "__main__":
    if not SECRET:
        raise SystemExit("A2A_SHARED_SECRET gerekli")
    ThreadingHTTPServer(("0.0.0.0", int(os.getenv("PORT", "8010"))), Handler).serve_forever()
