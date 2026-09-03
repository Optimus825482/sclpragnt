"""Authentication and outbound-provider safety boundaries for the paper app."""
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import socket
import time
from collections import defaultdict, deque
from base64 import urlsafe_b64decode, urlsafe_b64encode
from urllib.parse import urlparse
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, build_opener


SESSION_COOKIE = "scalper_session"
_LOGIN_FAILURE_LIMIT = 512
_login_failures = defaultdict(deque)
_PBKDF2_ITERATIONS = 200_000


def auth_configured():
    return bool(os.getenv("SCALPER_ADMIN_PASSWORD", "").strip()
                and os.getenv("SCALPER_SESSION_SECRET", "").strip())


def _b64(data):
    return urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(value):
    return urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str) -> str:
    """PBKDF2-HMAC-SHA256 with a random 16-byte salt; format salt$hash."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", str(password or "").encode(), salt, _PBKDF2_ITERATIONS)
    return f"{_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_b64, hash_b64 = str(stored or "").split("$", 1)
        salt = _unb64(salt_b64)
        expected = _unb64(hash_b64)
        digest = hashlib.pbkdf2_hmac("sha256", str(password or "").encode(), salt, _PBKDF2_ITERATIONS)
        return hmac.compare_digest(digest, expected)
    except (ValueError, TypeError):
        return False


def create_session_token(username: str = "admin", role: str = "admin", ttl_seconds=43200, client_fingerprint: str = ""):
    """Session token oluşturur. İsteğe bağlı client_fingerprint (IP+UA hash) ile token'ı cihaza baglar."""
    secret = os.getenv("SCALPER_SESSION_SECRET", "").encode()
    if not secret:
        raise RuntimeError("SCALPER_SESSION_SECRET tanımlı değil")
    fp_hash = hashlib.sha256(str(client_fingerprint or "").encode()).hexdigest()[:16] if client_fingerprint else ""
    payload = _b64(json.dumps({"sub": str(username).lower(), "role": str(role).lower(),
                               "exp": int(time.time()) + int(ttl_seconds),
                               "fp": fp_hash}, separators=(",", ":")).encode())
    signature = _b64(hmac.new(secret, payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{signature}"


def verify_session_token(token, client_fingerprint: str = ""):
    """Token'ı doğrular. client_fingerprint varsa, token'ın bağlı olduğu cihazla eşleşmesini kontrol eder."""
    try:
        payload, signature = str(token or "").split(".", 1)
        secret = os.getenv("SCALPER_SESSION_SECRET", "").encode()
        expected = _b64(hmac.new(secret, payload.encode(), hashlib.sha256).digest())
        data = json.loads(_unb64(payload))
        if not (secret and hmac.compare_digest(signature, expected)
                and int(data.get("exp", 0)) > time.time()):
            return False
        # Fingerprint varsa eşleşmayı kontrol et
        stored_fp = str(data.get("fp", ""))
        if stored_fp:
            expected_fp = hashlib.sha256(str(client_fingerprint or "").encode()).hexdigest()[:16]
            if not hmac.compare_digest(stored_fp, expected_fp):
                return False
        return True
    except (ValueError, TypeError, json.JSONDecodeError):
        return False


def session_user(token) -> dict | None:
    """Decode a valid session token into {username, role}; None when invalid."""
    try:
        payload, signature = str(token or "").split(".", 1)
        secret = os.getenv("SCALPER_SESSION_SECRET", "").encode()
        expected = _b64(hmac.new(secret, payload.encode(), hashlib.sha256).digest())
        data = json.loads(_unb64(payload))
        if not (secret and hmac.compare_digest(signature, expected)
                and int(data.get("exp", 0)) > time.time()):
            return None
        username = str(data.get("sub") or "").strip().lower()
        role = str(data.get("role") or "user").lower()
        if not username:
            return None
        return {"username": username, "role": role}
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def password_matches(password):
    expected = os.getenv("SCALPER_ADMIN_PASSWORD", "")
    return bool(expected) and hmac.compare_digest(str(password or ""), expected)


def login_allowed(client_key, now=None):
    current = float(now or time.time())
    failures = _login_failures[str(client_key or "unknown")]
    while failures and failures[0] < current - 300:
        failures.popleft()
    return len(failures) < 5


def record_login_result(client_key, succeeded, now=None):
    key = str(client_key or "unknown")
    if succeeded:
        _login_failures.pop(key, None)
    else:
        # Spoofed X-Real-IP values can mint unbounded keys; cap the map so a
        # flood of unique keys cannot grow memory without bound.
        while len(_login_failures) >= _LOGIN_FAILURE_LIMIT:
            _login_failures.pop(next(iter(_login_failures)), None)
        failures = _login_failures[key]
        failures.append(float(now or time.time()))


def request_authenticated(headers, cookies=None, query_token=None):
    return request_user(headers, cookies, query_token) is not None


def request_user(headers, cookies=None, query_token=None):
    """Return {username, role} for the request principal, or None."""
    authorization = str(headers.get("authorization", ""))
    bearer = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
    admin_token = os.getenv("SCALPER_ADMIN_TOKEN", "").strip()
    if admin_token and bearer and hmac.compare_digest(bearer, admin_token):
        return {"username": "admin", "role": "admin"}
    token = (cookies or {}).get(SESSION_COOKIE) or query_token
    return session_user(token)


async def validate_provider_url(base_url):
    """Provider URL'sini doğrular — DNS bloklamasını async olarak çalıştırır."""
    parsed = urlparse(str(base_url or "").strip())
    allow_private = os.getenv("LLM_ALLOW_PRIVATE_PROVIDER", "0") == "1"
    if parsed.scheme not in ({"https", "http"} if allow_private else {"https"}):
        raise ValueError("Provider URL HTTPS olmalı")
    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Provider URL geçerli bir host içermeli ve kimlik bilgisi taşımamalı")
    try:
        # DNS bloklamasını executor'da çalıştır — event loop'u bloke etme
        loop = asyncio.get_running_loop()
        addresses = await loop.run_in_executor(
            None,
            lambda: {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))}
        )
    except socket.gaierror as exc:
        raise ValueError("Provider host çözümlenemedi") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not allow_private and (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
                                  or ip.is_reserved or ip.is_unspecified):
            raise ValueError("Provider URL özel/yerel ağ adresine yönlenemez")
    return parsed.geturl().rstrip("/")


class _ValidatedRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPError(newurl, code, "LLM provider redirects are forbidden", headers, fp)


async def safe_provider_open(request, timeout):
    """Provider URL'sini async doğrulama ile açarak event loop'u bloke etmez."""
    await validate_provider_url(request.full_url)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: build_opener(_ValidatedRedirectHandler()).open(request, timeout=timeout))
