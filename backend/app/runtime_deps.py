"""Çalışma zamanı geç bağlama kaydı — monkeypatch yerine açık enjeksiyon.

Neden var
---------
``main.py`` kendi tanımladığı bazı handler'ları (``llm_open_paper_trade``,
``symbol_analysis``, ``get_config``, ``get_strategy_stats``, ``gainers_radar``)
router modüllerinin **global isimlerine atayarak** bağlıyor. Bu, ``main`` ->
``routers`` yönünde döngüsel import oluşmasını önler, ama modül global'lerini
sessizce monkeypatch eder. Atama tamamlanmadan bir arka plan döngüsü ilgili
handler'ı çağırırsa Python düz ``NameError`` fırlatıyordu ve bunun için hiçbir
gard yoktu.

Bu modül iki güvence sağlar:

1. ``pending_dep(name)``: henüz bağlanmamış bir bağımlılık için yer tutucu
   döndürür. Çağrılırsa ``NameError`` yerine *neyin* eksik olduğunu ve *nasıl*
   düzeltileceğini söyleyen net bir ``RuntimeError`` verir.
2. ``assert_ready()``: açılışta, döngüler başlamadan ÖNCE tüm zorunlu
   bağımlılıkların bağlandığını doğrular. Eksik varsa süreç net bir hatayla
   durur; "sessizce ölü döngü" durumu oluşamaz.

Kullanım (router tarafı)::

    from app.runtime_deps import pending_dep
    llm_open_paper_trade = pending_dep("llm_open_paper_trade")

Kullanım (main tarafı)::

    runtime_deps.bind(runtime_routes, "llm_open_paper_trade", llm_open_paper_trade)
    ...
    runtime_deps.assert_ready()
"""
from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger("scalper.runtime_deps")

#: Bağlanması beklenen bağımlılık adları (pending_dep ile otomatik dolar).
_REQUIRED: set[str] = set()
#: Gerçekten bağlanmış adlar.
_BOUND: set[str] = set()


def pending_dep(name: str, *, required: bool = True) -> Callable[..., Any]:
    """Henüz bağlanmamış bir bağımlılık için açıklayıcı hata veren yer tutucu.

    Dönen çağrılabilir, gerçek handler ``bind()`` ile atanana kadar çağrılırsa
    ``RuntimeError`` fırlatır. ``required=False`` ise ``assert_ready()`` bu adı
    zorunlu saymaz (isteğe bağlı bağımlılıklar için).
    """
    if required:
        _REQUIRED.add(name)

    async def _unbound(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(
            f"Çalışma zamanı bağımlılığı '{name}' henüz bağlanmadı. "
            f"main.py içindeki geç bağlama bloğu (runtime_deps.bind) çalışmadan "
            f"bu fonksiyon çağrıldı. Döngü başlatma sırasını kontrol edin."
        )

    _unbound.__name__ = name
    _unbound.__qualname__ = name
    return _unbound


def bind(module: Any, name: str, handler: Callable[..., Any]) -> None:
    """``handler``'ı ``module`` üzerinde ``name`` global'ine açıkça bağlar.

    Monkeypatch'e göre farkı: hangi bağımlılığın gerçekten bağlandığı burada
    kayıt altına alınır, böylece ``assert_ready()`` eksikleri yakalayabilir.
    """
    setattr(module, name, handler)
    _BOUND.add(name)


def missing() -> list[str]:
    """Zorunlu olup henüz bağlanmamış bağımlılık adları."""
    return sorted(_REQUIRED - _BOUND)


def assert_ready(*, strict: bool = True) -> list[str]:
    """Tüm zorunlu bağımlılıklar bağlı mı? Değilse anlaşılır hata fırlatır.

    ``strict=False`` iken hata fırlatmaz, yalnızca eksik listesini döndürür
    (test/diagnostik için).
    """
    miss = missing()
    if miss:
        message = (
            "Çalışma zamanı bağımlılıkları bağlanmadı: "
            + ", ".join(miss)
            + ". main.py geç bağlama bloğunu (runtime_deps.bind) kontrol edin."
        )
        if strict:
            raise RuntimeError(message)
        logger.warning(message)
    return miss


def status() -> dict[str, Any]:
    """Diagnostik: bağlı ve eksik bağımlılıklar."""
    return {"bound": sorted(_BOUND), "missing": missing(),
            "required": sorted(_REQUIRED)}


def reset() -> None:
    """Testler için kayıt durumunu sıfırlar."""
    _REQUIRED.clear()
    _BOUND.clear()
