"""requirements.txt / Docker imaj bağımlılık bütünlüğü testleri.

NEDEN VAR (2026-11-10, P0):
    Konteyner açılışta `RuntimeError: Form data requires "python-multipart"`
    ile çöküyordu (uvicorn hiç başlamıyordu). Kök neden: paket HİÇBİR
    bağımlılık dosyasında tanımlı değildi; testleri çalıştıran yerel venv'e
    elle kurulduğu için CI/birim testleri yemyeşil kalıyor, imaj ise
    import aşamasında ölüyordu.

    Bu testler, "çalıştığım makinede kurulu" ile "imajda kurulacak" arasındaki
    farkı kapatır: FastAPI'yi import eden bir uygulama, FastAPI'nin import
    anında zorunlu tuttuğu paketleri requirements.txt'te BULUNDURMAK ZORUNDADIR.
"""
from __future__ import annotations

import re
from pathlib import Path

REQ_PATH = Path(__file__).resolve().parent.parent / "requirements.txt"

# FastAPI, bu paketlerden biri import edilemezse uygulamayı import aşamasında
# RuntimeError ile öldürür (bkz. fastapi/dependencies/utils.py).
REQUIRED_AT_IMPORT = {
    "python-multipart": "Form/File/UploadFile içeren uç nokta tanımlandığında",
}


def _requirement_names() -> set[str]:
    text = REQ_PATH.read_text(encoding="utf-8")
    names: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # "uvicorn[standard]==1.2.3" → "uvicorn"
        m = re.match(r"^([A-Za-z0-9_.-]+)", line)
        if m:
            names.add(m.group(1).lower().replace("_", "-"))
    return names


def test_requirements_file_exists():
    assert REQ_PATH.is_file(), f"requirements.txt yok: {REQ_PATH}"


def test_python_multipart_is_declared():
    """Regresyon: eksikliği üretimde uvicorn'u açılışta çökertiyordu."""
    names = _requirement_names()
    assert "python-multipart" in names, (
        "python-multipart requirements.txt'te tanımlı değil. FastAPI uygulaması "
        "import edilirken bu paketi ister; eksikse konteyner RuntimeError ile "
        "açılmaz (yerel venv'de elle kurulu olduğu için testler bunu yakalamaz)."
    )


def test_python_multipart_pin_matches_installed():
    """Pin, gerçekten test edilen sürüme sabitlenmiş olmalı (drift koruması)."""
    import importlib.metadata as md

    text = REQ_PATH.read_text(encoding="utf-8")
    m = re.search(r"^python-multipart==([0-9][^\s#]*)", text, re.MULTILINE)
    assert m, "python-multipart sürümü sabitlenmemiş (==X.Y.Z beklenir)"
    pinned = m.group(1)
    try:
        installed = md.version("python-multipart")
    except md.PackageNotFoundError:  # pragma: no cover - venv'de kurulu değil
        return  # yerel ortamda yoksa pin doğrulaması atlanır
    assert pinned == installed, (
        f"requirements.txt python-multipart=={pinned} diyor ama ortamda "
        f"{installed} kurulu; imaj ile test ortamı ayrışır."
    )


def test_fastapi_imports_with_multipart():
    """FastAPI'nin multipart gerektiren bir uç noktayı kurabildiğini doğrular."""
    from fastapi import FastAPI, Form

    app = FastAPI()

    @app.post("/_probe")
    def _probe(x: str = Form(...)):  # noqa: ANN202
        return {"x": x}

    assert any(getattr(r, "path", None) == "/_probe" for r in app.routes)


def test_all_import_time_requirements_declared():
    """Import anında zorunlu her paket requirements.txt'te olmalı."""
    names = _requirement_names()
    missing = [pkg for pkg in REQUIRED_AT_IMPORT if pkg not in names]
    assert not missing, f"requirements.txt'te eksik zorunlu paket(ler): {missing}"
