"""VAPID anahtar teşhisi (2026-09-16).

NEDEN GEREKLİ:
    Backend log'unda şu uyarı vardı:
        "Monitoring push: VAPID_PRIVATE_KEY/VAPID_PUBLIC_KEY yapılandırılmamış —
         tarayıcı push bildirimleri GÖNDERİLMEYECEK"
    Ama frontend derlemesinde `NEXT_PUBLIC_VAPID_PUBLIC_KEY` VAR (88 bayt) ve
    4 abonelik kayıtlı. Yani anahtarların yarısı yerinde; push yine de sessizce
    ölü. Bu modül, sessiz ölümün İKİ klasik nedenini başlangıçta yakalar:

    1. `VAPID_PRIVATE_KEY` hiç ayarlanmamış → push gönderilemez (tek gerekli
       anahtar budur; pywebpush public anahtarı private'dan türetir).
    2. Private anahtar ile tarayıcının abone olurken kullandığı public anahtar
       UYUŞMUYOR → push servisi her isteği 401 ile reddeder, abonelikler ölü
       görünür ve hata hiçbir yerde "VAPID" demez (tanısı en zor hata budur).

AYRICA: `VAPID_PUBLIC_KEY` backend için ZORUNLU DEĞİLDİR (yalnızca frontend
kullanır). Bu modül private'dan doğru public'i türetip loglar; böylece kullanıcı
frontend'in `NEXT_PUBLIC_VAPID_PUBLIC_KEY` değerini bu çıktıyla karşılaştırabilir.

DÜZELTME (2026-09-16, "yanlış alarm"):
    Yukarıdaki teşhis doğruydu ama "VAPID_PUBLIC_KEY ayarlı değil" notu
    `problems` listesine konmuştu → `monitoring_background_loop` bunu
    `logger.warning("Monitoring push: ...")` olarak basıyordu. Sistem TAMAMEN
    SAĞLIKLIYKEN kullanıcı korkutucu bir uyarı görüyordu. Bu not artık `info`
    listesindedir; `problems` YALNIZCA push'u gerçekten kıran durumları taşır.

    `problems` ile `info` ayrımı önemli: problems = aksiyon gerektirir,
    info = durum bilgisi. Log seviyesi buna göre seçilir.

TARAYICI HANGİ ANAHTARI KULLANMALI:
    `alerting._send_push` pywebpush'a YALNIZCA `vapid_private_key` verir; kütüphane
    public anahtarı private'dan türetir. Bu yüzden tarayıcının
    `applicationServerKey` değeri HER ZAMAN `derived_public_key` olmalıdır —
    `VAPID_PUBLIC_KEY` env değişkeni bu karşılaştırmada ROL OYNAMAZ.
    Panelin doğru anahtarı gösterebilmesi için bu değer `effective_public_key`
    olarak dışa verilir.
"""
from __future__ import annotations

import base64
import binascii
import logging
import os

logger = logging.getLogger("scalper.vapid")


def _b64url_decode(value: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded)


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def derive_public_key(private_key_b64: str) -> str | None:
    """VAPID private (base64url, 32 bayt P-256) → public (base64url, 65 bayt).

    Hatalı/garbage anahtar için None döner; çağıran uyarıyı basar.
    """
    try:
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import serialization

        raw = _b64url_decode(private_key_b64)
        if len(raw) != 32:
            return None
        private_value = int.from_bytes(raw, "big")
        private_obj = ec.derive_private_key(private_value, ec.SECP256R1())
        public_bytes = private_obj.public_key().public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint,
        )
        return _b64url_encode(public_bytes)
    except (ImportError, ValueError, binascii.Error, TypeError):
        return None


def diagnose_vapid() -> dict:
    """VAPID yapılandırmasının durumunu ve sorunlarını döndür.

    Dönen sözlük:
        configured           : backend push gönderebilir mi (private var + geçerli)
        private_set          : VAPID_PRIVATE_KEY boş değil mi
        private_valid        : private anahtar geçerli P-256 mı
        derived_public_key   : private'dan türetilen public
        effective_public_key : TARAYICININ abone olması gereken anahtar (=derived)
        configured_public    : VAPID_PUBLIC_KEY env değeri (varsa)
        public_key_matches   : ikisi de varsa uyuşuyor mu (None = karşılaştırılamaz)
        problems             : push'u GERÇEKTEN kıran durumlar (aksiyon gerekir)
        info                 : arıza OLMAYAN durum notları (uyarı olarak basılmaz)
    """
    private_key = os.getenv("VAPID_PRIVATE_KEY", "").strip()
    configured_public = os.getenv("VAPID_PUBLIC_KEY", "").strip()

    result = {
        "configured": False,
        "private_set": bool(private_key),
        "private_valid": False,
        "derived_public_key": None,
        "effective_public_key": None,
        "configured_public": configured_public or None,
        "public_key_matches": None,
        "problems": [],
        "info": [],
    }

    if not private_key:
        result["problems"].append(
            "VAPID_PRIVATE_KEY ayarlanmamış — tarayıcı push'u gönderilemez. "
            "Frontend'de NEXT_PUBLIC_VAPID_PUBLIC_KEY var ama backend'in private "
            "anahtarı yok; ikisi AYNI anahtar çiftinden gelmelidir.")
        return result

    derived = derive_public_key(private_key)
    result["derived_public_key"] = derived
    if derived is None:
        result["problems"].append(
            "VAPID_PRIVATE_KEY geçersiz (32 baytlık base64url P-256 anahtarı bekleniyor) — "
            "push gönderilemez. `npx web-push generate-vapid-keys` ile yeniden üretin.")
        return result

    result["private_valid"] = True
    result["configured"] = True
    # pywebpush public'i private'dan türetir → tarayıcının kullanması gereken
    # anahtar HER ZAMAN budur (VAPID_PUBLIC_KEY env'i bundan bağımsızdır).
    result["effective_public_key"] = derived

    if configured_public:
        result["public_key_matches"] = (configured_public == derived)
        if not result["public_key_matches"]:
            result["problems"].append(
                "VAPID_PRIVATE_KEY ile VAPID_PUBLIC_KEY AYNI çiftten DEĞİL — push servisi "
                "her isteği 401 ile reddeder ve abonelikler sessizce ölür. "
                f"Tarayıcının abone olurken kullanması gereken public: {derived} "
                "(VAPID_PUBLIC_KEY'i buna eşitleyin ya da hiç ayarlamayın).")
    else:
        # ARIZA DEĞİL: backend public'e ihtiyaç duymaz (private'dan türetir).
        # Eskiden `problems` içindeydi ve sağlıklı sistemde "warning" basıyordu.
        result["info"].append(
            "VAPID_PUBLIC_KEY backend'de ayarlı değil — ZORUNLU DEĞİL (pywebpush public "
            "anahtarı private'dan türetir). Tarayıcının abone olurken kullanması gereken "
            f"public anahtar: {derived}")

    return result


def log_vapid_diagnosis() -> dict:
    """Başlangıçta bir kez VAPID durumunu logla (sessiz ölümü görünür yap).

    YALNIZCA `problems` uyarı olarak basılır. `info` notları INFO seviyesinde
    gider — böylece sağlıklı bir sistemde log'da sahte "warning" görünmez.
    """
    diag = diagnose_vapid()
    for problem in diag["problems"]:
        logger.warning("VAPID: %s", problem)
    for note in diag["info"]:
        logger.info("VAPID: %s", note)
    if not diag["configured"]:
        logger.warning(
            "VAPID: tarayıcı push'u GÖNDERİLEMEZ (panel geçmişi ve uygulama içi "
            "bildirimler çalışmaya devam eder).")
    return diag
