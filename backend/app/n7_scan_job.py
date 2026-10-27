"""N7 TARAMA — elle tetiklenen M1H momentum taraması arka plan işi (2026-10-24, kullanıcı isteği).

Radar sayfasındaki "N7 TARAMA" sekmesi `POST /api/radar/n7-scan/run` ile başlatır, `GET /api/radar/n7-scan` ile izler.
Durum bellek içidir (tek süreç): aynı anda tek tarama çalışır; son sonuç bir sonraki tarama bitene kadar saklanır, yeni
tarama sürerken de cevapta kalır (arayüz eski listeyi göstermeye devam eder). Taramayı `app.momentum_scan.scan` yapar;
kesit = şimdi (açık 15 dk mumu momentum_features kendisi atar). Görev `_start_background(..., single_pass=True)` ile
açılır; çökerse durum "error" olur, yeniden başlatılmaz.

2026-10-26 (kullanıcı isteği): `n7_hourly_loop` taramayı her saat başı (xx:00) otomatik koşar (sonuç aynı `_state`'e
yazılır, arayüz otomatik sonucu da görür); sıra 1 ve 2'deki sonuçlardan skoru `N7_PUSH_MIN_SCORE`'dan BÜYÜK olanlar
push edilir (`push_top`). Sıra 3 ve sonrası asla doldurulmaz. Sembol başına günlük tek push kapısı
`alerting.deliver_web_push` içinde olduğundan aynı sembol gün içinde ikinci kez push edilmez.

2026-10-28 (kullanıcı isteği): N7 push'u radar / MA ile AYNI teslim düzeninde (`_deliver_one`): plan eklenir, push
gittiyse bildirim kaydedilir, uygulama içine düşer ve otonom paper denenir; push gitmediyse hiçbiri olmaz.
"""
from __future__ import annotations

import asyncio
import logging
import time

from app import momentum_scan
from app.config import config
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


def seconds_until_next_hour(now: float | None = None) -> float:
    """Bir sonraki saat başına (xx:00:00) kalan saniye. UTC ve İstanbul farkı tam saat olduğundan ikisi için aynıdır."""
    now = time.time() if now is None else now
    return 3600.0 - (now % 3600.0)


def build_notification(sym: str, rank: int, score: float, px: float, now: float) -> dict:
    """N7 bildirim zarfı — radar bildirimiyle aynı alanlar (plan, kayıt, uygulama içi, paper aynı yoldan geçer).

    `notification_key` radar satır anahtarıyla (`monitoring-{sym}-{ts}`) aynı biçimde: kayıtlı satırın planı
    geçmiş listesinde de bulunur. Hedef N7'de yoktur → otonom varsayılan; plan net %3 tabanını kendisi uygular."""
    target = float(getattr(config, "AUTO_PAPER_DEFAULT_TARGET_PCT", 1.5))
    return {
        "symbol": sym,
        "title": f"🚀 {sym} · N7 #{rank} · skor {score:.1f}",
        "message": f"{sym} | N7 saatlik tarama sıra #{rank} | skor {score:.1f} | Anlık: {px:.6f} TRY",
        "url": f"/charts?symbol={sym}&timeframe=15m",
        "tag": f"n7-{sym}",
        "detected_at": now,
        "price": px,
        "score": score,
        "target_pct": target,
        "expected_price": px * (1 + target / 100) if px else 0.0,
        "source": "n7",
        "mode": "n7",
        "horizon_minutes": 60,
        "notification_key": f"monitoring-{sym}-{int(now)}",
        "updated": False,
        "sent_via_push": False,
    }


async def _deliver_one(monitoring, notif: dict) -> bool:
    """TEK TESLİM KURALI (2026-10-28, radar/MA ile aynı): plan → push → yalnız push GİTTİYSE kayıt +
    uygulama içi bildirim + otonom paper. Push gitmediyse (günlük sembol limiti, hata) hiçbiri yapılmaz."""
    from app import database, notification_plan, signal_eta
    sym = notif["symbol"]
    await notification_plan.attach_plan(notif, signal_eta.bucket_for("n7", notif))
    ok = bool(await monitoring._send_push(notif))
    notif["push_success"] = ok
    notif["push_attempted"] = True
    notif["sent_via_push"] = ok
    if not ok:
        return False
    try:
        await database.save_monitoring_notifications([notif])
    except Exception as exc:  # noqa: BLE001 — kayıt hatası teslimi bozmaz
        logger.warning("n7 bildirim kaydı %s: %s", sym, exc)
    monitoring._monitoring_state["history"] = ([notif] + monitoring._monitoring_state["history"])[:monitoring.HISTORY_LIMIT]
    try:
        await monitoring.ws_manager.broadcast({"type": "monitoring_alert", "data": [notif]})
    except Exception as exc:  # noqa: BLE001
        logger.warning("n7 WS yayını %s: %s", sym, exc)
    try:
        from app.routers.auto_paper import try_open_from_notification
        res = await try_open_from_notification(notif)
        logger.info("n7 otonom paper %s: %s", sym, (res or {}).get("trade_id") or (res or {}).get("reason") or res)
    except Exception as exc:  # noqa: BLE001 — paper hatası bildirimi bozmaz
        logger.warning("n7 otonom paper %s: %s", sym, exc)
    return True


async def push_top(result: dict | None) -> int:
    """Tarama sonucunun sıra 1..N_PUSH_TOP satırlarından skoru eşikten BÜYÜK olanları teslim eder (sıra 3+ doldurulmaz).

    Bildirim ayarları / sessiz saat / VAPID kontrolü `ma_buy_notify.deliver` ile aynı; teslim `_deliver_one`
    (push gittiyse kayıt + uygulama içi + otonom paper). Dönüş: başarılı push sayısı."""
    picked = list((result or {}).get("picked") or [])[:max(1, int(getattr(config, "N7_PUSH_TOP", 2)))]
    min_score = float(getattr(config, "N7_PUSH_MIN_SCORE", 10.0))
    cands = []
    for rank, row in enumerate(picked, start=1):
        try:
            score = float(row.get("score"))
        except (TypeError, ValueError):
            continue
        if score > min_score and row.get("sym"):
            cands.append((rank, row, score))
    if not cands:
        return 0
    from app.routers import monitoring  # geç import: monitoring büyük ve döngüsel bağımlı
    settings = await monitoring.get_user_notification_settings()
    if not settings.get("enabled", True):
        return 0
    if monitoring._in_quiet_hours(settings):
        logger.info("n7 saatlik: sessiz saat — %d sonuç push edilmedi", len(cands))
        return 0
    if not monitoring._vapid_configured():
        logger.info("n7 saatlik: VAPID yok — %d sonuç push edilmedi", len(cands))
        return 0
    pushed = 0
    for rank, row, score in cands:
        sym = str(row["sym"]).upper()
        notif = build_notification(sym, rank, score, float(row.get("px") or 0.0), time.time())
        try:
            ok = await _deliver_one(monitoring, notif)
        except Exception as exc:  # noqa: BLE001 — tek sembol hatası diğerini engellemez
            logger.warning("n7 saatlik push hatası %s: %s", sym, exc)
            continue
        if ok:
            pushed += 1
            logger.info("n7 saatlik push gönderildi: %s #%d skor %.1f", sym, rank, score)
        elif notif.get("push_skip_reason") == "daily_symbol_limit":
            logger.info("n7 saatlik: %s bugün zaten push edildi (günlük sembol limiti)", sym)
        else:
            logger.warning("n7 saatlik push başarısız: %s", sym)
    return pushed


async def n7_hourly_loop() -> None:
    """Her saat başı N7 taramasını koşar ve sıra 1-2'yi push eder. İstisna döngüyü asla öldürmez."""
    while True:
        await asyncio.sleep(seconds_until_next_hour() + 1.0)
        try:
            if not getattr(config, "N7_HOURLY_ENABLED", True):
                continue
            if is_running():
                logger.info("n7 saatlik: elle tarama sürüyor, bu saat atlandı")
                continue
            n = clamp_top(max(DEFAULT_TOP, int(getattr(config, "N7_PUSH_TOP", 2))))
            cutoff_ms = _now_ms()
            _state.update(status="running", started_at=cutoff_ms, finished_at=None,
                          progress={"done": 0, "total": 0}, error=None, top=n)
            await _run(cutoff_ms, n)
            if _state["status"] == "done":
                await push_top(_state["result"])
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("n7 saatlik döngü hatası")
            if _state["status"] == "running":
                _finish_error("Saatlik tarama beklenmedik şekilde bitti")


def reset() -> None:
    """Testler için: durumu sıfırla (çalışan görevi durdurmaz)."""
    _state.clear()
    _state.update(_fresh_state())
