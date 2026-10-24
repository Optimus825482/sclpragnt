"""N7 TARAMA — elle tetiklenen M1H momentum taraması arka plan işi (2026-10-24, kullanıcı isteği).

Radar sayfasındaki "N7 TARAMA" sekmesi `POST /api/radar/n7-scan/run` ile başlatır, `GET /api/radar/n7-scan` ile izler.
Durum bellek içidir (tek süreç): aynı anda tek tarama çalışır; son sonuç bir sonraki tarama bitene kadar saklanır, yeni
tarama sürerken de cevapta kalır (arayüz eski listeyi göstermeye devam eder). Taramayı `app.momentum_scan.scan` yapar;
kesit = şimdi (açık 15 dk mumu momentum_features kendisi atar). Görev `_start_background(..., single_pass=True)` ile
açılır; çökerse durum "error" olur, yeniden başlatılmaz.
"""
from __future__ import annotations

import asyncio
import logging
import time

from app import momentum_scan
from app.api_common import _start_background

logger = logging.getLogger("scalper.n7_scan")

TASK_NAME = "n7-scan"
DEFAULT_TOP = 3
MIN_TOP, MAX_TOP = 1, 10


class AlreadyRunning(Exception):
    """Tarama zaten sürüyor; ikinci başlatma reddedilir (409)."""


def _fresh_state() -> dict:
    return {"status": "idle", "started_at": None, "finished_at": None, "progress": {"done": 0, "total": 0},
            "error": None, "top": DEFAULT_TOP, "result": None}


_state: dict = _fresh_state()


def _now_ms() -> int:
    return int(time.time() * 1000)


def clamp_top(top) -> int:
    try:
        n = int(top)
    except (TypeError, ValueError):
        n = DEFAULT_TOP
    return max(MIN_TOP, min(MAX_TOP, n))


def is_running() -> bool:
    return _state["status"] == "running"


def snapshot() -> dict:
    """GET cevabı: durum + ilerleme + son sonuç (kopya; çağıran değiştiremez)."""
    return {"status": _state["status"], "started_at": _state["started_at"], "finished_at": _state["finished_at"],
            "progress": dict(_state["progress"]), "error": _state["error"], "top": _state["top"],
            "result": _state["result"]}


def _progress(done: int, total: int) -> None:
    _state["progress"] = {"done": int(done), "total": int(total)}


def _finish_error(message: str) -> None:
    _state["status"] = "error"
    _state["error"] = message
    _state["finished_at"] = _now_ms()


async def _run(cutoff_ms: int, top: int) -> None:
    """Taramayı çalıştırır; sonucu ya da hatayı duruma yazar. Hiç istisna sızdırmaz."""
    try:
        result = await momentum_scan.scan(cutoff_ms, top, progress=_progress)
        _state["result"] = result
        _state["status"] = "done"
        _state["error"] = None
        _state["finished_at"] = _now_ms()
        logger.info("n7 tarama bitti: %d sembol, %d aday, %.1f sn", result.get("scanned", 0),
                    result.get("candidates", 0), result.get("elapsed_s", 0.0))
    except asyncio.CancelledError:
        _finish_error("Tarama iptal edildi")
        raise
    except Exception as exc:  # noqa: BLE001 — hata durumu arayüze aktarılır
        logger.exception("n7 tarama hatası")
        _finish_error(f"{type(exc).__name__}: {exc}")


def _on_task_done(task: "asyncio.Task") -> None:
    """Emniyet: görev `_run` dışında bir sebeple ölürse durum 'running'de takılı kalmasın."""
    if _state["status"] != "running":
        return
    if task.cancelled():
        _finish_error("Tarama iptal edildi")
        return
    exc = task.exception()
    _finish_error(f"{type(exc).__name__}: {exc}" if exc else "Tarama beklenmedik şekilde bitti")


def start(top=DEFAULT_TOP) -> dict:
    """Taramayı arka planda başlatır; çalışıyorsa AlreadyRunning. Önceki `result` yeni sonuç gelene dek korunur."""
    if is_running():
        raise AlreadyRunning("Tarama zaten çalışıyor")
    n = clamp_top(top)
    cutoff_ms = _now_ms()
    _state.update(status="running", started_at=cutoff_ms, finished_at=None, progress={"done": 0, "total": 0},
                  error=None, top=n)
    task = _start_background(lambda: _run(cutoff_ms, n), TASK_NAME, single_pass=True)
    task.add_done_callback(_on_task_done)
    return {"status": "running", "started_at": cutoff_ms, "top": n}


def reset() -> None:
    """Testler için: durumu sıfırla (çalışan görevi durdurmaz)."""
    _state.clear()
    _state.update(_fresh_state())
