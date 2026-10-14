"""Authentication and outbound-provider safety boundaries for the paper app."""
import asyncio
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import secrets
import socket
import time
from collections import defaultdict, deque
from base64 import urlsafe_b64decode, urlsafe_b64encode
from urllib.parse import urlparse
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, build_opener
from concurrent.futures import ThreadPoolExecutor


SESSION_COOKIE = "scalper_session"
logger = logging.getLogger("scalper.security")
_LOGIN_FAILURE_LIMIT = 512
_login_failures = defaultdict(deque)
_PBKDF2_ITERATIONS = 200_000
_user_session_versions = {"admin": 0}

# LLM-03 (2026-09-12): Provider çağrıları 90–120 sn timeout ile
# bekleyebilir. Varsayılan executor `min(32, cpu+4)` PAYLAŞIMLIDIR;
# eşzamanlı birkaç LLM isteği havuzu doldurduğunda `main.py`'nin
# tarama/pozisyon döngüleri (aynı havuzu `to_thread` ile kullanır)
# kuyrukta bekler ve uygulama geneli yavaşlar. LLM çağrıları için
# ayrı ve sınırlı bir havuz ayrılır.
LLM_EXECUTOR_MAX_WORKERS = max(1, int(os.getenv("LLM_EXECUTOR_MAX_WORKERS", "8")))
_LLM_EXECUTOR = ThreadPoolExecutor(max_workers=LLM_EXECUTOR_MAX_WORKERS,
                                   thread_name_prefix="llm-provider")


def set_user_session_version(username: str, version: int):
    _user_session_versions[str(username or "").strip().lower()] = int(version or 0)


def remove_user_session_version(username: str):
    _user_session_versions.pop(str(username or "").strip().lower(), None)


def load_user_session_versions(users):
    _user_session_versions.clear()
    _user_session_versions["admin"] = 0
    for user in users or []:
        username = str(user.get("username") or "").strip().lower()
        if username:
            _user_session_versions[username] = int(user.get("session_version") or 0)


def auth_configured():
    return bool(os.getenv("SCALPER_ADMIN_PASSWORD", "").strip()
                and os.getenv("SCALPER_SESSION_SECRET", "").strip())


# ---------------------------------------------------------------------------
# Güvenilir proxy / istemci IP (P1-5, 2026-10-07)
#
# Uygulama nginx (gateway) arkasında çalışır ve nginx `X-Real-IP` başlığını
# `$remote_addr` ile DOLDURUR. Ancak backend'e doğrudan (proxy'yi atlayarak)
# erişilebilirse istemci bu başlığı SAHTELEYEBİLİR: her denemede farklı bir
# `X-Real-IP` göndererek login brute-force limitini (client_key başına 5)
# sıfırlar. Bu yüzden başlık YALNIZCA bağlantının geldiği peer adresi
# güvenilir bir proxy ise dikkate alınır; aksi halde gerçek soket adresi
# (`request.client.host`) kullanılır.
# ---------------------------------------------------------------------------
_DEFAULT_TRUSTED_PROXIES = ",".join((
    "127.0.0.0/8",      # loopback
    "10.0.0.0/8",       # özel ağ (Docker/Coolify köprüsü)
    "172.16.0.0/12",    # Docker varsayılan köprü aralığı
    "192.168.0.0/16",   # LAN
    "::1/128",          # IPv6 loopback
))
_trusted_proxy_cache: dict = {"raw": None, "nets": ()}


def _trusted_proxy_networks():
    """`SCALPER_TRUSTED_PROXIES` (virgülle ayrık IP/CIDR) → network listesi.

    Tanımsızsa özel/loopback aralıkları varsayılır: Docker içindeki nginx
    container'ı bu aralıktan bağlanır, böylece üretimde `X-Real-IP` çalışmaya
    devam eder ama dışarıdan doğrudan gelen (spoof eden) istemci başlığı
    güvenilmez. Ham değere göre önbelleklenir; aynı süreçte tekrar parse edilmez.
    """
    raw = os.getenv("SCALPER_TRUSTED_PROXIES", _DEFAULT_TRUSTED_PROXIES)
    if _trusted_proxy_cache["raw"] == raw:
        return _trusted_proxy_cache["nets"]
    nets = []
    for item in str(raw or "").split(","):
        item = item.strip()
        if not item:
            continue
        try:
            nets.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            continue
    _trusted_proxy_cache["raw"] = raw
    _trusted_proxy_cache["nets"] = tuple(nets)
    return _trusted_proxy_cache["nets"]


def _is_trusted_proxy(host) -> bool:
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(str(host))
    except ValueError:
        return False
    return any(ip in net for net in _trusted_proxy_networks())


def trusted_client_ip(request) -> str | None:
    """Login rate-limit anahtarı için istemci IP'si.

    `X-Real-IP` YALNIZ peer güvenilir proxy ise kullanılır; aksi halde gerçek
    soket adresi döner. Böylece başlığı sahteleştirerek limit sıfırlama yolu
    kapanır; meşru proxy arkasında ise gerçek istemci IP'si korunur (limit
    proxy başına değil istemci başına uygulanır).
    """
    if request is None:
        return None
    peer = None
    try:
        peer = request.client.host if request.client is not None else None
    except Exception:
        peer = None
    header_ip = ""
    try:
        if request.headers:
            header_ip = (request.headers.get("X-Real-IP") or "").strip()
    except Exception:
        header_ip = ""
    if header_ip and _is_trusted_proxy(peer):
        return header_ip
    return str(peer) if peer else (header_ip or None)


def client_fingerprint(request) -> str:
    """Oturumu cihaza bağlayan parmak izi (P1-5, 2026-10-07).

    NEDEN YALNIZ User-Agent: token'ı IP'ye bağlamak cep/gezici ağda IP her
    değiştiğinde oturumu düşürür ve meşru yeniden bağlanmaları bozar. User-Agent
    ise aynı tarayıcıda kararlıdır; çalınan bir cookie FARKLI bir istemcide
    kullanılırsa (tarayıcı/otomasyon UA'sı farklı) yakalanır. Başlık yoksa
    (curl/test) boş döner → parmak izi bağlanmaz (fail-open), böylece meşru
    betik/araç istemcileri kırılmaz.
    """
    if request is None:
        return ""
    try:
        ua = (request.headers.get("user-agent") or "").strip() if request.headers else ""
    except Exception:
        ua = ""
    return ua[:512]


def _ws_allowed_origins() -> set[str]:
    """`SCALPER_WS_ALLOWED_ORIGINS` (virgülle ayrık tam origin) listesi."""
    raw = os.getenv("SCALPER_WS_ALLOWED_ORIGINS", "")
    return {item.strip().rstrip("/") for item in str(raw or "").split(",") if item.strip()}


def origin_allowed(origin, host) -> bool:
    """WebSocket Origin allowlist (cross-site WebSocket hijacking koruması).

    Tarayıcılar WS el sıkışmasında `Origin` başlığını ZORUNLU gönderir; saldırgan
    sayfası da kurbanın cookie'siyle bağlantı açarken kendi origin'ini gönderir.
    Bu yüzden:
      - `Origin` YOKSA: tarayıcı dışı istemci (test/CLI) → kabul. CSWH vektörü
        değildir; reddetmek meşru istemcileri kırardı.
      - `Origin` varsa: same-origin (`Origin` netloc == `Host`) VEYA açık
        `SCALPER_WS_ALLOWED_ORIGINS` listesinde ise kabul.
    """
    value = str(origin or "").strip()
    if not value:
        return True
    if value.rstrip("/") in _ws_allowed_origins():
        return True
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False
    host_value = str(host or "").strip().lower()
    return bool(host_value) and parsed.netloc.lower() == host_value


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


def create_session_token(username: str = "admin", role: str = "admin", ttl_seconds=43200,
                         client_fingerprint: str = "", session_version: int | None = None):
    """Session token oluşturur. İsteğe bağlı client_fingerprint (IP+UA hash) ile token'ı cihaza baglar.

    Negatif ttl_seconds, iptal/test senaryoları için exp'yi geçmişe atar ve
    token üretildiği anda geçersiz olur.
    """
    secret = os.getenv("SCALPER_SESSION_SECRET", "").encode()
    if not secret:
        raise RuntimeError("SCALPER_SESSION_SECRET tanımlı değil")
    fp_hash = hashlib.sha256(str(client_fingerprint or "").encode()).hexdigest()[:16] if client_fingerprint else ""
    ttl = int(ttl_seconds)
    # Negatif/geçersiz ttl: iptal/test senaryoları — token üretildiği anda
    # geçersiz olsun (exp = 0). Epoch + negatif ttl hâlâ geleceğe işaret
    # ettiği için doğrudan 0'a sabitlemek gerekir.
    exp = (int(time.time()) + ttl) if ttl >= 0 else 0
    version = int(session_version if session_version is not None else _user_session_versions.get(str(username).lower(), 0))
    payload = _b64(json.dumps({"sub": str(username).lower(), "role": str(role).lower(),
                               "exp": exp,
                               "fp": fp_hash, "sv": version}, separators=(",", ":")).encode())
    signature = _b64(hmac.new(secret, payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{signature}"


def _decode_session(token, client_fingerprint=None) -> dict | None:
    """Oturum token'ının TEK doğrulama yolu (imza + exp + sv + fingerprint).

    G-22 (2026-09-12): Eskiden ``verify_session_token`` ölü koddı — üretim yolu
    (``session_user``) kendi kopyasını çalıştırıyordu ve fingerprint kontrolü
    hiçbir zaman uygulanmıyordu. Artık ikisi de bu çekirdeği kullanır, yani
    testlerin doğruladığı davranış üretimdeki davranışın ta kendisidir.
    Geçersiz token için ``None`` döner.

    ``client_fingerprint``: ``None`` → doğrulayıcı parmak izi sağlamadı, kontrol
    ATLANIR (geriye dönük uyum; yalnız token'da fp varsa zorlanır denemez).
    Boş olmayan bir değer → token bağlıysa ZORUNLU eşleşme (P1-5).
    """
    try:
        payload, signature = str(token or "").split(".", 1)
        secret = os.getenv("SCALPER_SESSION_SECRET", "").encode()
        expected = _b64(hmac.new(secret, payload.encode(), hashlib.sha256).digest())
        data = json.loads(_unb64(payload))
        username = str(data.get("sub") or "").strip().lower()
        if not username:
            return None
        # Oturum iptali (logout → session_version bump) imza kontrolünden önce
        # değil sonra uygulanır; sıra sonucu değiştirmez ama imzasız bir
        # payload'ın sv alanına güvenilmemesi için önce imzayı doğrularız.
        if not (secret and hmac.compare_digest(signature, expected)
                and int(data.get("exp", 0)) > time.time()):
            return None
        # Oturum sürümü (sv) kontrolü — DENETİM 3.3 #21 (2026-09-26):
        # Eskiden `expected_version is None` (kullanıcı sözlükte YOK) iken bu blok
        # ATLANIYORDU; böylece silinmiş/askıya alınmış kullanıcının token'ı (payload'da
        # imzalı `sub` olduğu için) üretimde 12 saat geçerli kalıyordu. Artık bilinmeyen
        # kullanıcı da geçersizdir (fail-closed): `sub` sözlükte yoksa token reddedilir.
        # Not: `load_user_session_versions` DB'deki tüm kullanıcıları startup'ta yükler;
        # silinen kullanıcı listeden düştüğü için token'ı bir sonraki doğrulamada
        # (veya logout'ta `remove_user_session_version`) geçersizleşir.
        expected_version = _user_session_versions.get(username)
        if expected_version is None:
            return None
        if int(data.get("sv", -1)) != expected_version:
            return None
        # Fingerprint varsa eşleşmayı kontrol et.
        #
        # P1-5 (2026-10-07): Parmak izi ARTIK login'de User-Agent'tan üretilip
        # tüm oturum uçlarında doğrulanır. NEDEN SIKI (reject): audit "flag"
        # seçeneği yeterli değildi — çalınmış bir cookie farklı istemcide
        # kullanıldığında istek yine de yetkilendiriliyordu. Meşru yeniden
        # bağlanma User-Agent'ı değiştirmediği için kırılmaz; eşleşmeyen istemci
        # yeni bir giriş yapar (fail-closed, oturum hırsızlığı ölür).
        #
        # ``client_fingerprint is None`` → doğrulayıcı parmak izi SAĞLAMADI
        # (geriye dönük uyum): yalnız token'da fp varsa ve doğrulayıcı bir değer
        # verdiyse zorlanır. İstemci bu parametreyi kontrol EDEMEZ (sunucu tarafı
        # türetilir); güvenlik kapıları (middleware/require_admin/WS) daima gerçek
        # UA parmak izini geçirir, böylece skip yolu istismar edilemez.
        stored_fp = str(data.get("fp", ""))
        if stored_fp and client_fingerprint is not None:
            expected_fp = hashlib.sha256(str(client_fingerprint).encode()).hexdigest()[:16]
            if not hmac.compare_digest(stored_fp, expected_fp):
                logger.warning("oturum parmak izi uyuşmuyor (%s) — token reddedildi",
                               username)
                return None
        return data
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def verify_session_token(token, client_fingerprint=None) -> bool:
    """Token geçerli mi? (imza + süre + oturum sürümü + fingerprint)"""
    return _decode_session(token, client_fingerprint) is not None


def session_user(token, client_fingerprint=None) -> dict | None:
    """Decode a valid session token into {username, role}; None when invalid."""
    data = _decode_session(token, client_fingerprint)
    if data is None:
        return None
    return {"username": str(data.get("sub") or "").strip().lower(),
            "role": str(data.get("role") or "user").lower()}


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


def request_authenticated(headers, cookies=None, query_token=None, client_fingerprint=None):
    return request_user(headers, cookies, query_token, client_fingerprint) is not None


#: G-15 (2026-09-12): Statik yönetici token'ı yalnızca bu bayrak açıkken çalışır.
STATIC_ADMIN_TOKEN_FLAG = "SCALPER_ADMIN_TOKEN_ALLOW_STATIC"


def static_admin_token_enabled() -> bool:
    """Statik ``SCALPER_ADMIN_TOKEN`` yolu açıkça etkinleştirildi mi?

    Gerekçe: statik token ``exp``, ``sv`` (oturum sürümü) ve fingerprint
    kontrollerini atlar, logout ile iptal edilemez ve süresi yoktur. Varsayılan
    olarak KAPALIDIR; böylece ``SCALPER_ADMIN_TOKEN`` yanlışlıkla set edilse
    bile süresiz tam yetkili bir anahtar oluşmaz. Operatör bu yolu bilinçli
    olarak isterse ``SCALPER_ADMIN_TOKEN_ALLOW_STATIC=1`` verir ve token
    rotasyonu ile süresiz erişim riskini kabul eder (dokümantasyon: bu modül).
    """
    return os.getenv(STATIC_ADMIN_TOKEN_FLAG, "0").strip().lower() in {"1", "true", "yes", "on"}


def request_user(headers, cookies=None, query_token=None, client_fingerprint=None):
    """Return {username, role} for the request principal, or None."""
    authorization = str(headers.get("authorization", ""))
    bearer = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
    admin_token = os.getenv("SCALPER_ADMIN_TOKEN", "").strip()
    if admin_token and static_admin_token_enabled() and bearer and hmac.compare_digest(bearer, admin_token):
        # G-15: yalnız açık env bayrağı ile; oturum sürümü/süre kontrolü yoktur.
        return {"username": "admin", "role": "admin"}
    token = (cookies or {}).get(SESSION_COOKIE) or query_token
    return session_user(token, client_fingerprint)


def require_admin(request) -> dict:
    """Yönetici kapısı (G-23): ortak uygulama burada, ``main`` içinde DEĞİL.

    ``main._require_admin`` ve router'lar (``app.api_common.require_admin``
    üzerinden) aynı kapıyı kullanır. Eksik principal → 401, admin olmayan →
    403. Davranış eskisiyle birebir aynıdır.
    """
    from fastapi import HTTPException

    # P1-5: fingerprint doğrulaması burada da uygulanır (router kapıları
    # middleware'i atlar ve doğrudan buraya gelir).
    user = request_user(request.headers, request.cookies,
                        client_fingerprint=client_fingerprint(request))
    if not user:
        raise HTTPException(status_code=401, detail="Kimlik doğrulama gerekli")
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Bu işlem yalnız sistem yöneticisine açıktır")
    return user


def _validate_provider_url_sync(base_url):
    """Provider URL'sini senkron doğrular (DNS çözümlemesi dahil).

    Hem doğrudan (LLM config doğrulama, testler) hem async sarmalayıcı
    tarafından kullanılır. Geri dönüş: normalize edilmiş base_url.
    """
    parsed = urlparse(str(base_url or "").strip())
    allow_private = os.getenv("LLM_ALLOW_PRIVATE_PROVIDER", "0") == "1"
    if parsed.scheme not in ({"https", "http"} if allow_private else {"https"}):
        raise ValueError("Provider URL HTTPS olmalı")
    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Provider URL geçerli bir host içermeli ve kimlik bilgisi taşımamalı")
    try:
        # DNS bloklaması — senkron çekirdek; async çağıranlar executor kullanır.
        addresses = {item[4][0] for item in socket.getaddrinfo(
            parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))}
    except socket.gaierror as exc:
        raise ValueError("Provider host çözümlenemedi") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not allow_private and (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
                                  or ip.is_reserved or ip.is_unspecified):
            raise ValueError("Provider URL özel/yerel ağ adresine yönlenemez")
    return parsed.geturl().rstrip("/")


async def validate_provider_url(base_url):
    """Provider URL'sini doğrular — DNS bloklamasını async olarak çalıştırır."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_LLM_EXECUTOR, _validate_provider_url_sync, base_url)


class _ValidatedRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPError(newurl, code, "LLM provider redirects are forbidden", headers, fp)


async def safe_provider_open(request, timeout):
    """Provider URL'sini async doğrulama ile açarak event loop'u bloke etmez."""
    await validate_provider_url(request.full_url)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_LLM_EXECUTOR, lambda: build_opener(_ValidatedRedirectHandler()).open(request, timeout=timeout))
