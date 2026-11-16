"""nginx yönlendirme sözleşmesi: backend yolları frontend'e düşmemeli.

CANLI HATA (2026-11-10): /_diag/paper ucu yazıldı, app'e kaydedildi, testler
geçti — AMA nginx'te `location /_diag/` YOKTU. İstek `/` kuralına düşüp
Next.js frontend'e gitti ve HTML 404 döndü. Backend'e hiç ulaşmadı.

Ders: uygulama içi testler bu sınıfı yakalayamaz. Proxy katmanı ayrı
doğrulanmalı.
"""
import pathlib
import re

BASE = pathlib.Path(__file__).parent.parent
NGINX = BASE.parent / "nginx" / "default.conf"


def test_nginx_config_exists():
    assert NGINX.exists(), "nginx/default.conf bulunamadı"


def test_diag_route_proxied_to_backend():
    """`/_diag/` backend'e proxy edilmeli (frontend'e DEĞİL)."""
    src = NGINX.read_text(encoding="utf-8")
    assert "location /_diag/" in src, \
        "/_diag/ yolu nginx'te tanımlı değil -> HTML 404 döner"
    # Blok içinde backend_pool olmalı
    blk = src.split("location /_diag/")[1].split("location ")[0]
    assert "backend_pool" in blk, "/_diag/ frontend'e yollanıyor"
    assert "frontend_pool" not in blk


def test_public_backend_paths_are_all_proxied():
    """Auth'suz/public backend yolları nginx'te karşılık bulmalı."""
    from app.main import require_admin_session  # noqa: F401  (import kontrolü)
    src = NGINX.read_text(encoding="utf-8")
    # main.py'deki public_paths + backend router prefix'leri
    for path in ("/health", "/api/", "/_diag/", "/ws"):
        assert f"location {path}" in src or f"location = {path}" in src, \
            f"{path} nginx'te yok"


def test_diag_access_log_off():
    """Token query string'de taşınıyor -> erişim logu kapalı olmalı."""
    src = NGINX.read_text(encoding="utf-8")
    blk = src.split("location /_diag/")[1].split("location ")[0]
    assert "access_log off" in blk, "token log'a sızabilir"


def test_braces_balanced():
    """Kaba sözdizimi kontrolü (nginx -t yok ise)."""
    src = NGINX.read_text(encoding="utf-8")
    # Yorumları çıkar
    clean = re.sub(r"#.*", "", src)
    assert clean.count("{") == clean.count("}"), "parantez dengesiz"
