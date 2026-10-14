"""Strategy-level circuit breaker: pause a strategy whose recent trades show
a negative rolling expectancy.

The 2026-08-25 PUMP Monitor history showed 292 trades at -1680 TRY with no
mechanism to stop the bleeding: per-symbol guards existed but nothing watched
the strategy as a whole. This module evaluates the last N closed trades per
strategy after each close and flips the strategy to PAUSED when the window's
expectancy drops below the floor. Pausing is paper-signal-level only (entries
blocked, open positions still managed) and requires explicit re-enable via
config or the API — never auto-resumes on its own.
"""
import asyncio
import json
import time

from app import database

# Rolling window and floor are read from config so they stay tunable.
WINDOW_DEFAULT = 20
FLOOR_DEFAULT = -0.5  # TRY per trade


class StrategyCircuitBreaker:
    """Tracks paused strategies in llm_settings KV; evaluates after closes."""

    def __init__(self):
        self._paused = {}          # strategy -> {"paused_at": ts, "reason": str}
        self._loaded = False
        self._last_eval = {}       # strategy -> ts (per-strategy debounce)
        # D-09 (2026-09-26 denetimi, YÜKSEK) — lost update. `self._paused`
        # kilitsiz okunup yazılıyordu ve `_persist()` DİŞ sözlüğünün TAMAMINI
        # `set_llm_setting` ile tek seferde yazıyordu. İki eşzamanlı yazma
        # (örn. iki strateji aynı anda kapanış sonrası değerlendirmesi, ya da
        # `resume` + `evaluate_after_close`) birbirinin kaydını SİLİYORDU:
        # strateji A duraklatıldıktan sonra B'nin persist'i A'yı listeden
        # düşürüyordu. Aynı şekilde `_load`/`_persist` yarışı da vardı.
        # Çözüm: TÜM okuma-değiştirme-yazma döngüsü tek kilit altında;
        # `resume` de aynı kilidi kullanır.
        self._state_lock = asyncio.Lock()

    def _key(self):
        return "strategy_circuit_breaker_paused"

    async def _ensure_loaded(self):
        if self._loaded:
            return
        try:
            raw = await database.get_llm_setting(self._key(), "{}")
            stored = json.loads(raw or "{}")
            if isinstance(stored, dict):
                self._paused = stored
        except Exception:
            self._paused = {}
        self._loaded = True

    async def _persist_locked(self):
        """`_state_lock` ALINMIŞ halde çağrılır: tüm sözlük tek yazma."""
        await database.set_llm_setting(self._key(), json.dumps(self._paused))

    def is_paused(self, strategy: str) -> bool:
        """Senkron görünüm — YALNIZCA halihazırda yüklenmiş bellek durumu.

        UYARI: DB'den yükleme yapmaz. Süreç yeni başladıysa ``self._paused``
        boştur ve duraklatılmış bir strateji için False döner (D-05 "restart
        amnezi"). Giriş kapısı gibi doğruluk gerektiren çağrılar bunu DEĞİL
        ``await is_paused_async(...)`` kullanmalıdır. Bu metot yalnızca test
        ve senkron bağlamlar için tutulur.
        """
        return strategy in self._paused

    async def is_paused_async(self, strategy: str) -> bool:
        """Doğruluk gerektiren tek giriş: DB durumu yüklenene kadar bekler.

        D-05 (2026-09-12): senkron ``is_paused`` ``_ensure_loaded()``
        çağırmadığı için restart sonrası ilk kapanışa kadar duraklatılmış bir
        strateji serbestçe işlem açabiliyordu.
        """
        await self._ensure_loaded()
        return strategy in self._paused

    def status(self) -> dict:
        return {name: dict(info) for name, info in self._paused.items()}

    async def resume(self, strategy: str) -> bool:
        """Human-approved resume; nothing auto-unpauses. Persists state to DB.

        D-09 (2026-09-26): `_ensure_loaded()` ÇAĞRILMIYORDU → süreç yeniden
        başladığında `self._paused` boş olduğu için `resume` her zaman
        ``False`` döndü ve kullanıcı "devam et" dediğinde duraklatma
        KALDIRILAMIYORDU (API 404/False). Yükleme artık zorunlu.
        Ayrıca okuma-değiştirme-yazma `_state_lock` altında atomik.
        """
        async with self._state_lock:
            await self._ensure_loaded()
            if strategy in self._paused:
                self._paused.pop(strategy, None)
                await self._persist_locked()
                return True
            return False

    async def evaluate_after_close(self, strategy: str):
        """Recompute the rolling expectancy for one strategy; pause if breached.

        Returns a dict describing the decision (or None when healthy).
        """
        from app.config import config

        await self._ensure_loaded()
        now = time.time()
        # Per-strategy debounce so a close of strategy A cannot suppress the
        # evaluation of strategy B within the same 5s window.
        if now - self._last_eval.get(strategy, 0.0) < 5:
            return None
        self._last_eval[strategy] = now
        # Only judge when the full window has data; small samples stay allowed.
        window = max(5, min(int(getattr(config, "STRATEGY_BREAKER_WINDOW", WINDOW_DEFAULT)), 100))
        floor = float(getattr(config, "STRATEGY_BREAKER_EXPECTANCY_FLOOR", FLOOR_DEFAULT))
        try:
            # D-05 (2026-09-12): kayıt limiti sabit WINDOW_DEFAULT(20) idi ama
            # pencere config'den 10..100 arası gelebiliyor. window > 20 ise
            # `len(pnls)=20 < window` her zaman True kalıyor ve breaker ASLA
            # duraklatmıyordu (sessiz devre dışı). Limit pencereden küçük
            # olmamalı — bu yüzden window hesabı get_trades'ten ÖNCE yapılır.
            trades = await database.get_trades(limit=max(WINDOW_DEFAULT, window),
                                               strategy=strategy)
        except Exception:
            return None
        pnls = [float(t.get("pnl") or 0) for t in trades]
        if len(pnls) < window:
            return None
        expectancy = sum(pnls[:window]) / window  # newest-first slice
        detail = {
            "paused_at": now,
            "reason": "rolling_expectancy_below_floor",
            "window": window,
            "expectancy": round(expectancy, 4),
            "floor": floor,
            "recent_pnls": [round(p, 2) for p in pnls[:window]],
        }
        # D-09 (2026-09-26): sözlük güncellemesi + DB yazımı TEK atomik
        # bölgede. DB okuması yukarıda yapıldı; burada yalnızca bellek
        # sözlüğü değiştirilip yazılır. İki strateji aynı anda kapanırsa
        # ikisinin kaydı da korunur (kayıp güncelleme yok).
        paused_now = False
        async with self._state_lock:
            if expectancy >= floor:
                # Healthy: clear any stale pause record left over from an
                # older run.
                if strategy in self._paused:
                    self._paused.pop(strategy, None)
                    await self._persist_locked()
                return None
            if strategy not in self._paused:
                self._paused[strategy] = detail
                await self._persist_locked()
                paused_now = True
        if paused_now:
            try:
                await database.save_signal({
                    "symbol": "*", "action": "STRATEGY_PAUSED",
                    "reason": f"{strategy}: expectancy {expectancy:.2f} < {floor} over {window} trades",
                    "strategy": strategy, "timestamp": now})
            except Exception:
                pass
        return detail


breaker = StrategyCircuitBreaker()
