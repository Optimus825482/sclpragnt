# Kullanıcı Arayüzü (light tema) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `role=user` hesapları için light temalı, sade bir arayüz (Ana Sayfa, Bildirimler, Radar, Portföy, Grafik, Raporlar, Profil, Ayarlar) kurmak; admin arayüzü değişmeden kalır.

**Architecture:** `AppShell` rol dalıyla `UserShell`'e ayrılır; light tema `[data-theme="light"]` CSS katmanıdır (admin'e dokunmaz). Menü tercihleri yeni `user_ui_prefs` tablosunda tutulur. Canlı fiyat için backend tek bir `watch_prices` WS yayını yapar. Mevcut uçlar (`/api/reports/notifications`, `/api/monitoring/*`, `/api/daily-rising/live`, `/api/binance/settings`) yeniden kullanılır.

**Tech Stack:** Next.js 16 / React 18 / Tailwind 3.4 / vitest (node), FastAPI / PostgreSQL (psycopg), pytest.

**Spec:** `docs/superpowers/specs/2026-10-15-kullanici-arayuzu-design.md`

## Global Constraints

- Admin arayüzü ve admin sayfaları DEĞİŞMEZ; her yeni görünüm `role !== "admin"` dalındadır.
- Frontend testleri `environment: "node"` (jsdom yok): yalnız saf yardımcılar test edilir (`frontend/vitest.config.ts`).
- Migrasyon kuralları (`backend/migrations/README.md`): benzersiz numara (`015`), uygulanmış dosya düzenlenmez, `BEGIN/COMMIT/CONCURRENTLY` yok, idempotent (`IF NOT EXISTS`).
- API secret hiçbir yanıtta/loglarda düz yazılmaz; yeni şifreleme/tablo yok (`user_binance_keys`, `/api/binance/settings`).
- Metinler Türkçe, sentence case, kısa ve kullanıcı dilinde (DESIGN.md).
- Mobil 320–768 px: sayfa düzeyinde yatay kaydırma yok; dokunma hedefi ≥44 px; `prefers-reduced-motion` saygılı.
- Radar kesimi: sonuç/KPI uçları `RADAR_REPORTS_BASELINE_AT=2026-10-15 22:30` (UTC+3) sonrasını döndürür; `evaluated=0` → "Henüz ölçülmedi".
- Backend lint: `ruff check app tests scripts`. Frontend: `npm run typecheck`, `npm run lint`, `npm test` (frontend/ içinden).
- Her görev sonunda commit; commit mesajı `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` ile biter.

## Review Focus

- Kullanıcı admin sayfasına URL ile girerse: mevcut `RequireAdmin` korur; kullanıcı kabuğu menüsünde admin öğesi yok.
- `ui-prefs`: bilinmeyen/gizlenemez menü kimliği → 422; başka kullanıcı verisi okunamaz; boş liste geçerli.
- Fiyat yok/0 olan sembol: % değişim "—" (NaN/∞ görünmez); bildirim fiyatı 0 → "—".
- WS sessiz/kopuk: 15 sn sonra `/api/market-tickers` yoklaması; WS dönünce yoklama durur.
- `evaluated=0`, `success_rate=null`: KPI "—" ve "Henüz ölçülmedi" gösterir (sıfır yüzde değil).
- Bağlı WS istemcisi yokken `watch_prices_loop` Binance'e istek atmaz; >50 sembol 50'ye kırpılır, tekrarsız.

---

## File Structure

**Backend**
- Create `backend/migrations/015_user_ui_prefs.sql` — `user_ui_prefs` tablosu.
- Create `backend/app/ui_prefs.py` — menü kimlikleri + `normalize_hidden()` (saf).
- Create `backend/app/watch_prices.py` — `collect_watch_symbols()` (saf) + `watch_prices_loop()`.
- Modify `backend/app/database.py` — `get_user_ui_prefs`, `set_user_ui_prefs`.
- Modify `backend/app/main.py` — `/api/profile/ui-prefs` uçları; `_start_background(watch_prices_loop, ...)` (≈1147 yakını).
- Create `backend/tests/test_ui_prefs.py`, `backend/tests/test_watch_prices.py`.

**Frontend** (`frontend/app/`)
- Create `lib/userUi.ts` (+ `lib/userUi.test.ts`) — saf yardımcılar.
- Create `lib/useWatchPrices.ts` — WS + yoklama yedeği kancası.
- Create `lib/useUiPrefs.ts` — menü tercihleri (localStorage + DB).
- Create `user-theme.css` + `scripts/gen-light-theme.mjs` (frontend kökünde `scripts/`) — light tema katmanı.
- Create `components/user/UserShell.tsx`, `UserNav.tsx`, `UserBottomNav.tsx`.
- Create `components/user/KpiStrip.tsx`, `RisingLiveTable.tsx`, `RecentNotifications.tsx`.
- Create `components/user/UserHome.tsx`, `UserNotifications.tsx`, `UserRadar.tsx`, `UserSettings.tsx`.
- Modify `components/AppShell.tsx` (rol dalı), `layout.tsx` (tema özniteliği), `globals.css` (import), `page.tsx`, `monitoring/page.tsx`, `settings/page.tsx`, `reports/page.tsx` (rol dalları).

---

### Task 1: Saf yardımcılar (`userUi.ts`) — test önce

**Files:**
- Create: `frontend/app/lib/userUi.ts`
- Test: `frontend/app/lib/userUi.test.ts`

**Interfaces:**
- Produces:
  - `pctChange(base: number|null|undefined, live: number|null|undefined): number|null`
  - `statusLabel(status: string): { label: string; tone: "good"|"warn"|"bad"|"wait"|"mute" }`
  - `windowEnd(detectedAt: number, horizonMin: number): number` (epoch s)
  - `confidenceBadge(score: number|null|undefined): "Yüksek"|"Orta"|"Düşük"`
  - `MENU_ITEMS: readonly {id,href,label,icon,locked?}[]`, `visibleMenu(hidden: string[]): MenuItem[]`
  - `isUserRole(role: string|null): boolean`

- [ ] **Step 1: Write the failing test** — `frontend/app/lib/userUi.test.ts`

```ts
import { describe, expect, it } from "vitest";
import { confidenceBadge, isUserRole, pctChange, statusLabel, visibleMenu, windowEnd } from "./userUi";

describe("pctChange", () => {
  it("hesaplar", () => expect(pctChange(100, 103)).toBeCloseTo(3, 6));
  it("negatif", () => expect(pctChange(200, 190)).toBeCloseTo(-5, 6));
  it("taban 0/null/NaN → null", () => {
    expect(pctChange(0, 5)).toBeNull();
    expect(pctChange(null, 5)).toBeNull();
    expect(pctChange(NaN, 5)).toBeNull();
  });
  it("canlı yok → null", () => {
    expect(pctChange(100, null)).toBeNull();
    expect(pctChange(100, 0)).toBeNull();
    expect(pctChange(100, Infinity)).toBeNull();
  });
});

describe("statusLabel", () => {
  it("eşler", () => {
    expect(statusLabel("TAMAMEN BAŞARILI")).toEqual({ label: "Hedefe ulaştı", tone: "good" });
    expect(statusLabel("KISMİ").label).toBe("Kısmen");
    expect(statusLabel("BAŞARISIZ").label).toBe("Ulaşmadı");
    expect(statusLabel("BEKLİYOR").tone).toBe("wait");
    expect(statusLabel("ÖLÇÜLEMEDİ").tone).toBe("mute");
  });
  it("bilinmeyen → Bekliyor", () => expect(statusLabel("???").label).toBe("Bekliyor"));
});

describe("windowEnd", () => {
  it("detected + ufuk", () => expect(windowEnd(1000, 15)).toBe(1900));
  it("ufuk 0/negatif → 60 dk varsayılan", () => expect(windowEnd(1000, 0)).toBe(1000 + 3600));
});

describe("confidenceBadge", () => {
  it("eşikler", () => {
    expect(confidenceBadge(85)).toBe("Yüksek");
    expect(confidenceBadge(70)).toBe("Orta");
    expect(confidenceBadge(40)).toBe("Düşük");
    expect(confidenceBadge(null)).toBe("Düşük");
  });
});

describe("visibleMenu / isUserRole", () => {
  it("varsayılan 8 öğe", () => expect(visibleMenu([]).map((m) => m.id)).toEqual(
    ["home", "notifications", "radar", "portfolio", "charts", "reports", "profile", "settings"]));
  it("gizlenir", () => expect(visibleMenu(["charts"]).some((m) => m.id === "charts")).toBe(false));
  it("kilitliler gizlenemez", () => {
    const ids = visibleMenu(["home", "settings"]).map((m) => m.id);
    expect(ids).toContain("home");
    expect(ids).toContain("settings");
  });
  it("rol", () => {
    expect(isUserRole("user")).toBe(true);
    expect(isUserRole("admin")).toBe(false);
    expect(isUserRole(null)).toBe(false);
  });
});
```

- [ ] **Step 2: Run to verify fail** — `cd frontend && npx vitest run app/lib/userUi.test.ts` → FAIL (modül yok).

- [ ] **Step 3: Implement** — `frontend/app/lib/userUi.ts`

```ts
/** Kullanıcı arayüzü için saf yardımcılar (node'da test edilir). */

export type Tone = "good" | "warn" | "bad" | "wait" | "mute";

export function pctChange(base: number | null | undefined, live: number | null | undefined): number | null {
  const b = Number(base);
  const l = Number(live);
  if (!Number.isFinite(b) || b <= 0) return null;
  if (!Number.isFinite(l) || l <= 0) return null;
  return ((l - b) / b) * 100;
}

export function statusLabel(status: string): { label: string; tone: Tone } {
  switch (status) {
    case "TAMAMEN BAŞARILI": return { label: "Hedefe ulaştı", tone: "good" };
    case "KISMİ": return { label: "Kısmen", tone: "warn" };
    case "BAŞARISIZ": return { label: "Ulaşmadı", tone: "bad" };
    case "ÖLÇÜLEMEDİ": return { label: "Ölçülemedi", tone: "mute" };
    default: return { label: "Bekliyor", tone: "wait" };
  }
}

const DEFAULT_WINDOW_MIN = 60;

export function windowEnd(detectedAt: number, horizonMin: number): number {
  const h = Number(horizonMin);
  const minutes = Number.isFinite(h) && h > 0 ? h : DEFAULT_WINDOW_MIN;
  return Number(detectedAt) + minutes * 60;
}

export function confidenceBadge(score: number | null | undefined): "Yüksek" | "Orta" | "Düşük" {
  const s = Number(score);
  if (!Number.isFinite(s)) return "Düşük";
  if (s >= 80) return "Yüksek";
  if (s >= 60) return "Orta";
  return "Düşük";
}

export type MenuItem = { id: string; href: string; label: string; icon: string; locked?: boolean };

export const MENU_ITEMS: readonly MenuItem[] = [
  { id: "home", href: "/", label: "Ana sayfa", icon: "🏠", locked: true },
  { id: "notifications", href: "/notifications", label: "Bildirimler", icon: "🔔" },
  { id: "radar", href: "/monitoring", label: "Radar", icon: "📡" },
  { id: "portfolio", href: "/portfolio", label: "Portföy", icon: "💼" },
  { id: "charts", href: "/charts", label: "Grafik", icon: "📈" },
  { id: "reports", href: "/reports", label: "Raporlar", icon: "📋" },
  { id: "profile", href: "/profile", label: "Profil", icon: "👤" },
  { id: "settings", href: "/settings", label: "Ayarlar", icon: "⚙️", locked: true },
];

export function visibleMenu(hidden: string[]): MenuItem[] {
  const set = new Set(hidden);
  return MENU_ITEMS.filter((m) => m.locked || !set.has(m.id));
}

export function isUserRole(role: string | null): boolean {
  return !!role && role !== "admin";
}
```

- [ ] **Step 4: Run to verify pass** — `npx vitest run app/lib/userUi.test.ts` → PASS.
- [ ] **Step 5: Commit** — `git add frontend/app/lib/userUi.ts frontend/app/lib/userUi.test.ts && git commit -m "feat(user-ui): saf yardımcılar (% değişim, durum, menü)"`

> Not: `/notifications` yeni rota; Task 6 `frontend/app/notifications/page.tsx` oluşturur (rol dalıyla; admin için mevcut `/monitoring` bildirimlerine yönlendirir).

---

### Task 2: Backend — `user_ui_prefs` (migration, saf doğrulama, DB, uçlar)

**Files:**
- Create: `backend/migrations/015_user_ui_prefs.sql`, `backend/app/ui_prefs.py`
- Modify: `backend/app/database.py` (`get_user_binance_keys` yakını, ≈6177), `backend/app/main.py` (`/api/profile` sonrası, ≈357)
- Test: `backend/tests/test_ui_prefs.py`

**Interfaces:**
- Produces: `ui_prefs.MENU_IDS: tuple[str,...]`, `ui_prefs.LOCKED_IDS`, `ui_prefs.normalize_hidden(raw) -> list[str]` (ValueError), `database.get_user_ui_prefs(user_id:int)->dict` (`{"hidden_menu": list[str]}`), `database.set_user_ui_prefs(user_id:int, hidden:list[str])->dict`; `GET/PUT /api/profile/ui-prefs` → `{"ok":True,"hidden_menu":[...]}`.

- [ ] **Step 1: Failing test** — `backend/tests/test_ui_prefs.py`

```python
import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app import main, ui_prefs


class NormalizeTests(unittest.TestCase):
    def test_empty_ok(self):
        self.assertEqual([], ui_prefs.normalize_hidden([]))

    def test_dedup_and_order(self):
        self.assertEqual(["charts", "reports"], ui_prefs.normalize_hidden(["reports", "charts", "charts"]))

    def test_unknown_rejected(self):
        with self.assertRaises(ValueError):
            ui_prefs.normalize_hidden(["nope"])

    def test_locked_rejected(self):
        for locked in ("home", "settings"):
            with self.assertRaises(ValueError):
                ui_prefs.normalize_hidden([locked])

    def test_not_a_list_rejected(self):
        with self.assertRaises(ValueError):
            ui_prefs.normalize_hidden("charts")


class _Req:
    pass


class EndpointTests(unittest.TestCase):
    def _run(self, coro):
        return asyncio.run(coro)

    def test_get_returns_own_prefs_only(self):
        with patch.object(main, "_require_user", return_value={"username": "ali", "role": "user"}), \
             patch.object(main.database, "get_user_by_username", AsyncMock(return_value={"id": 7})), \
             patch.object(main.database, "get_user_ui_prefs", AsyncMock(return_value={"hidden_menu": ["charts"]})) as g:
            out = self._run(main.get_ui_prefs(_Req()))
        g.assert_awaited_once_with(7)
        self.assertEqual(["charts"], out["hidden_menu"])

    def test_put_invalid_is_422(self):
        with patch.object(main, "_require_user", return_value={"username": "ali", "role": "user"}), \
             patch.object(main.database, "get_user_by_username", AsyncMock(return_value={"id": 7})):
            with self.assertRaises(HTTPException) as cm:
                self._run(main.put_ui_prefs({"hidden_menu": ["settings"]}, _Req()))
        self.assertEqual(422, cm.exception.status_code)

    def test_put_saves_for_session_user(self):
        saved = AsyncMock(return_value={"hidden_menu": ["charts"]})
        with patch.object(main, "_require_user", return_value={"username": "ali", "role": "user"}), \
             patch.object(main.database, "get_user_by_username", AsyncMock(return_value={"id": 7})), \
             patch.object(main.database, "set_user_ui_prefs", saved):
            out = self._run(main.put_ui_prefs({"hidden_menu": ["charts"]}, _Req()))
        saved.assert_awaited_once_with(7, ["charts"])
        self.assertTrue(out["ok"])
```

- [ ] **Step 2: Run** — `cd backend && python -m pytest tests/test_ui_prefs.py -q` → FAIL (modül/uç yok).

- [ ] **Step 3: Implement**

`backend/migrations/015_user_ui_prefs.sql`
```sql
-- 015 — KULLANICI ARAYÜZ TERCİHLERİ (2026-10-15)
-- Kullanıcı menüsünde gizlenen öğeler (cihazlar arası aynı menü).
-- Idempotent: CREATE TABLE IF NOT EXISTS. Yalnız kullanıcıya özgü, hassas veri yok.
CREATE TABLE IF NOT EXISTS user_ui_prefs (
  user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  hidden_menu TEXT NOT NULL DEFAULT '[]',
  updated_at DOUBLE PRECISION NOT NULL
);
```

`backend/app/ui_prefs.py`
```python
"""Kullanıcı menü tercihleri — doğrulama (saf). Kimlikler frontend `MENU_ITEMS` ile AYNIDIR."""

MENU_IDS: tuple[str, ...] = (
    "home", "notifications", "radar", "portfolio", "charts", "reports", "profile", "settings")
LOCKED_IDS: frozenset[str] = frozenset({"home", "settings"})


def normalize_hidden(raw) -> list[str]:
    """Gizlenecek menü kimliklerini doğrula; tekrarları at, MENU_IDS sırasına koy."""
    if not isinstance(raw, list):
        raise ValueError("hidden_menu liste olmalı")
    seen: set[str] = set()
    for item in raw:
        key = str(item)
        if key not in MENU_IDS:
            raise ValueError(f"Bilinmeyen menü öğesi: {key}")
        if key in LOCKED_IDS:
            raise ValueError(f"Gizlenemez menü öğesi: {key}")
        seen.add(key)
    return [m for m in MENU_IDS if m in seen]
```

`database.py` (≈ `get_user_binance_keys` yanına):
```python
async def get_user_ui_prefs(user_id: int) -> dict:
    def op(conn):
        row = conn.execute("SELECT hidden_menu FROM user_ui_prefs WHERE user_id=%s", (int(user_id),)).fetchone()
        if not row:
            return {"hidden_menu": []}
        try:
            parsed = json.loads(row[0] or "[]")
        except (TypeError, ValueError):
            parsed = []
        return {"hidden_menu": [str(x) for x in parsed] if isinstance(parsed, list) else []}
    return await _run_db(op)


async def set_user_ui_prefs(user_id: int, hidden: list[str]) -> dict:
    def op(conn):
        conn.execute(
            "INSERT INTO user_ui_prefs(user_id, hidden_menu, updated_at) VALUES(%s,%s,%s) "
            "ON CONFLICT (user_id) DO UPDATE SET hidden_menu=EXCLUDED.hidden_menu, updated_at=EXCLUDED.updated_at",
            (int(user_id), json.dumps(list(hidden)), time.time()))
        conn.commit()
        return {"hidden_menu": list(hidden)}
    return await _run_db(op)
```

`main.py` (`profile_current` sonrasına; dosyada `ui_prefs` import edilir: `from app import ui_prefs`):
```python
async def _session_user_id(request: Request) -> int:
    principal = _require_user(request)
    user = await database.get_user_by_username(str(principal.get("username") or "").strip())
    if not user:
        raise HTTPException(status_code=401, detail="Kullanıcı bulunamadı")
    return int(user["id"])


@app.get("/api/profile/ui-prefs")
async def get_ui_prefs(request: Request):
    """Oturumdaki kullanıcının menü tercihleri (yalnız kendisininki)."""
    prefs = await database.get_user_ui_prefs(await _session_user_id(request))
    return {"ok": True, **prefs}


@app.put("/api/profile/ui-prefs")
async def put_ui_prefs(payload: dict, request: Request):
    uid = await _session_user_id(request)
    try:
        hidden = ui_prefs.normalize_hidden(payload.get("hidden_menu"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    prefs = await database.set_user_ui_prefs(uid, hidden)
    return {"ok": True, **prefs}
```

- [ ] **Step 4: Run** — `python -m pytest tests/test_ui_prefs.py tests/test_readme_router_table.py -q` ve `ruff check app tests/test_ui_prefs.py` → temiz. `backend/app/migration_plan.py` migrasyonları dosya adından keşfediyorsa ek kayıt gerekmez; değilse `015`'i aynı desenle ekle ve ilgili migration testlerini çalıştır (`grep -rn "014_llm_readonly_role" backend` ile kayıt yerini bul).
- [ ] **Step 5: Commit** — `feat(user-ui): user_ui_prefs tablosu ve /api/profile/ui-prefs`

---

### Task 3: Backend — `watch_prices` WS yayını

**Files:**
- Create: `backend/app/watch_prices.py`, `backend/tests/test_watch_prices.py`
- Modify: `backend/app/main.py` (`_start_background(binance_price_tick_loop, ...)` ≈1147 yanına)

**Interfaces:**
- Produces: `watch_prices.collect_watch_symbols(notif_rows: list[dict], rising_rows: list[dict], cap: int = 50) -> list[str]`; `async def watch_prices_loop()`; WS mesajı `{"type":"watch_prices","data":{"prices":{"BTCTRY":123.4},"time":epoch}}`.

- [ ] **Step 1: Failing test** — `backend/tests/test_watch_prices.py`

```python
import unittest

from app.watch_prices import collect_watch_symbols


class CollectTests(unittest.TestCase):
    def test_union_dedup_upper(self):
        out = collect_watch_symbols([{"symbol": "btctry"}, {"symbol": "ETHTRY"}],
                                    [{"symbol": "BTCTRY"}, {"symbol": "XRPTRY"}])
        self.assertEqual(["BTCTRY", "ETHTRY", "XRPTRY"], out)

    def test_cap_50(self):
        rows = [{"symbol": f"S{i:03d}TRY"} for i in range(80)]
        self.assertEqual(50, len(collect_watch_symbols(rows, [])))

    def test_skips_blank_and_bad(self):
        self.assertEqual(["AAATRY"], collect_watch_symbols([{"symbol": ""}, {}, {"symbol": "x y"}, {"symbol": "AAATRY"}], []))
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** — `backend/app/watch_prices.py`

```python
"""Kullanıcı arayüzü canlı fiyatları: tüm bağlı kullanıcılar için TEK sembol birleşimi, ~3 sn'de bir yayın."""
import asyncio
import logging
import re
import time

logger = logging.getLogger("scalper.watch_prices")

_SYMBOL_RE = re.compile(r"^[A-Z0-9]{5,20}$")
WATCH_CAP = 50
WATCH_INTERVAL_SEC = 3.0


def collect_watch_symbols(notif_rows: list[dict], rising_rows: list[dict], cap: int = WATCH_CAP) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for row in list(notif_rows) + list(rising_rows):
        sym = str((row or {}).get("symbol") or "").strip().upper()
        if not _SYMBOL_RE.match(sym) or sym in seen:
            continue
        seen.add(sym)
        out.append(sym)
        if len(out) >= cap:
            break
    return out


async def watch_prices_loop():
    """Bağlı WS istemcisi yoksa Binance'e istek ATMAZ. Hata döngüyü öldürmez."""
    from app import database
    from app.main import ws_manager
    from app.routers import monitoring
    await asyncio.sleep(5)
    while True:
        try:
            if not getattr(ws_manager, "active_connections", None):
                await asyncio.sleep(WATCH_INTERVAL_SEC)
                continue
            notifs = await database.list_monitoring_notifications(limit=20)
            rising = await database.list_daily_rising(days=7)
            symbols = collect_watch_symbols(notifs, rising or [])
            if symbols:
                prices = await monitoring._batch_prices(symbols)
                clean = {s: float(p) for s, p in (prices or {}).items() if p}
                if clean:
                    await ws_manager.broadcast({"type": "watch_prices",
                                                "data": {"prices": clean, "time": time.time()}})
        except Exception as exc:  # noqa: BLE001 — döngü ölmemeli
            logger.debug("watch_prices atlandı: %s", type(exc).__name__)
        await asyncio.sleep(WATCH_INTERVAL_SEC)
```

`main.py`'de başlatma (mevcut `_start_background(binance_price_tick_loop, "binance-price-tick")` satırının altına): `_start_background(watch_prices.watch_prices_loop, "watch-prices")` (+ `from app import watch_prices`). **Uygulayıcı doğrulaması (kod okuyarak):** `ws_manager`'ın bağlantı listesinin gerçek adı (`active_connections` mi?), `database.list_daily_rising` imzası ve `monitoring._batch_prices` dönüş biçimi (`dict[str,float]`); farklıysa bu dosyada uyarlayıp aynı sözleşmeyi koru.

- [ ] **Step 4: Run** — `python -m pytest tests/test_watch_prices.py -q`; `ruff check app/watch_prices.py tests/test_watch_prices.py`.
- [ ] **Step 5: Commit** — `feat(user-ui): watch_prices WS yayını (tek birleşik sembol seti)`

---

### Task 4: Light tema katmanı + `UserShell` + rol dalı

**Files:**
- Create: `frontend/scripts/gen-light-theme.mjs`, `frontend/app/user-theme.css` (üretilen + elle bölüm), `frontend/app/components/user/UserShell.tsx`, `UserNav.tsx`, `UserBottomNav.tsx`
- Modify: `frontend/app/components/AppShell.tsx`, `frontend/app/layout.tsx`, `frontend/app/globals.css` (import)

**Interfaces:**
- Consumes: `isUserRole`, `visibleMenu` (Task 1); `useUiPrefs()` (Task 5 — bu görevde geçici `hidden=[]`; Task 5 bağlar).
- Produces: `<UserShell>{children}</UserShell>`; `<html data-theme="light">` yalnız kullanıcı rolünde.

- [ ] **Step 1: Tema üreteci** — `frontend/scripts/gen-light-theme.mjs` (kodda kullanılan `bunker-*`, `neon-*`, `white` renk sınıflarını tarar, `[data-theme="light"]` kurallarını üretir):

```js
import { readFileSync, writeFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

const ROOT = new URL("../app", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const MAP = {
  "bunker-950": [245, 247, 251], "bunker-900": [255, 255, 255], "bunker-800": [227, 232, 242],
  "bunker-700": [203, 211, 227], "bunker-600": [139, 148, 173], "bunker-muted": [91, 100, 120],
  "neon-green": [15, 138, 78], "neon-greenHover": [11, 110, 62], "neon-red": [200, 40, 40],
  "neon-yellow": [166, 110, 8], white: [15, 23, 42], black: [15, 23, 42],
};
const PROPS = { bg: "background-color", text: "color", border: "border-color", divide: "border-color" };
const re = /\b(bg|text|border|divide)-(bunker-(?:950|900|800|700|600|muted)|neon-(?:green|greenHover|red|yellow)|white|black)(?:\/(\d{1,3}))?\b/g;

function walk(dir, out = []) {
  for (const f of readdirSync(dir)) {
    const p = join(dir, f);
    if (statSync(p).isDirectory()) { if (!["node_modules", ".next"].includes(f)) walk(p, out); }
    else if (/\.(tsx|ts|css)$/.test(f) && f !== "user-theme.css") out.push(p);
  }
  return out;
}

const found = new Set();
for (const file of walk(ROOT)) {
  for (const m of readFileSync(file, "utf8").matchAll(re)) found.add(m[0]);
}
const rules = [...found].sort().map((cls) => {
  const [, kind, color, alpha] = cls.match(/^(bg|text|border|divide)-(.+?)(?:\/(\d{1,3}))?$/);
  const [r, g, b] = MAP[color];
  const value = alpha ? `rgb(${r} ${g} ${b} / ${Number(alpha) / 100})` : `rgb(${r} ${g} ${b})`;
  const sel = `.${cls.replace(/\//g, "\\/")}`;
  const target = kind === "divide" ? `${sel} > :not([hidden]) ~ :not([hidden])` : sel;
  return `[data-theme="light"] ${target}{${PROPS[kind]}:${value}}`;
});
const header = "/* ÜRETİLDİ: node scripts/gen-light-theme.mjs — elle düzenleme yapma; elle kurallar user-theme.manual.css'te. */\n";
writeFileSync(new URL("../app/user-theme.generated.css", import.meta.url), header + rules.join("\n") + "\n");
console.log(`${rules.length} kural üretildi`);
```

Elle kurallar `frontend/app/user-theme.manual.css`:
```css
[data-theme="light"] body { background: #f5f7fb; color: #0f172a; }
[data-theme="light"] { color-scheme: light; }
[data-theme="light"] .card { background: #fff; border-color: #e3e8f2; box-shadow: 0 1px 2px rgb(15 23 42 / .06); }
[data-theme="light"] .topbar { background: rgb(255 255 255 / .9); border-color: #e3e8f2; }
[data-theme="light"] .input { background: #fff; color: #0f172a; border-color: #cbd3e3; }
[data-theme="light"] .ui-button-primary { background: #0f8a4e; color: #fff; }
[data-theme="light"] .ui-button-secondary { background: #eef2f9; color: #0f172a; border-color: #cbd3e3; }
@media (prefers-reduced-motion: reduce) { [data-theme="light"] * { animation: none !important; transition: none !important; } }
```
`globals.css` sonuna: `@import "./user-theme.generated.css"; @import "./user-theme.manual.css";` (CSS `@import`'lar dosyanın başında olmalı; `globals.css` zaten Tailwind direktifleri kullanıyorsa import'ları `layout.tsx`'te `import "./user-theme.generated.css"; import "./user-theme.manual.css";` olarak ekle.)

- [ ] **Step 2: Çalıştır ve doğrula** — `cd frontend && node scripts/gen-light-theme.mjs` → "N kural üretildi"; üretilen dosya git'e girer.

- [ ] **Step 3: `UserShell` / `UserNav` / `UserBottomNav`**

`frontend/app/components/user/UserShell.tsx`
```tsx
"use client";
import { useEffect } from "react";
import UserNav from "./UserNav";
import UserBottomNav from "./UserBottomNav";
import RadarAlertModal from "../RadarAlertModal";
import { useUiPrefs } from "../../lib/useUiPrefs";

export default function UserShell({ children }: { children: React.ReactNode }) {
  const { hidden } = useUiPrefs();
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", "light");
    document.documentElement.classList.remove("dark");
    return () => {
      document.documentElement.removeAttribute("data-theme");
      document.documentElement.classList.add("dark");
    };
  }, []);
  return (
    <div className="min-h-screen bg-bunker-950 text-white">
      <UserNav hidden={hidden} />
      <main className="mx-auto max-w-5xl px-4 pb-24 pt-4 md:pb-8">{children}</main>
      <UserBottomNav hidden={hidden} />
      <RadarAlertModal />
    </div>
  );
}
```
`UserNav.tsx`: üst yatay menü (≥md), `visibleMenu(hidden)` ile `Link` listesi, aktif öğe `usePathname()` ile vurgulanır, sağda kullanıcı adı + "Çıkış" (`useAuth().logout`).
```tsx
"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "../../lib/auth";
import { visibleMenu } from "../../lib/userUi";

export default function UserNav({ hidden }: { hidden: string[] }) {
  const pathname = usePathname();
  const { username, logout } = useAuth();
  return (
    <header className="sticky top-0 z-30 hidden border-b border-bunker-800 bg-bunker-900 md:block">
      <nav aria-label="Ana menü" className="mx-auto flex max-w-5xl items-center gap-1 px-4 py-2">
        {visibleMenu(hidden).map((m) => {
          const active = m.href === "/" ? pathname === "/" : pathname.startsWith(m.href);
          return (
            <Link key={m.id} href={m.href} aria-current={active ? "page" : undefined}
              className={`rounded-lg px-3 py-2 text-sm font-medium ${active ? "bg-bunker-800 text-white" : "text-bunker-muted hover:text-white"}`}>
              <span aria-hidden className="mr-1">{m.icon}</span>{m.label}
            </Link>
          );
        })}
        <span className="ml-auto text-sm text-bunker-muted">{username}</span>
        <button type="button" onClick={() => void logout?.()} className="ui-button ui-button-secondary ml-2 px-3 py-1.5 text-sm">Çıkış</button>
      </nav>
    </header>
  );
}
```
`UserBottomNav.tsx`: `md:hidden fixed bottom-0` çubuğu; ilk 4 görünür öğe + "Diğer" (kalan öğeleri açan `details` listesi); `touch-target` sınıfı (≥44 px), `pb-[env(safe-area-inset-bottom)]`.
```tsx
"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { visibleMenu } from "../../lib/userUi";

export default function UserBottomNav({ hidden }: { hidden: string[] }) {
  const pathname = usePathname();
  const items = visibleMenu(hidden);
  const main = items.slice(0, 4);
  const rest = items.slice(4);
  const isActive = (href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href));
  return (
    <nav aria-label="Alt menü" className="fixed inset-x-0 bottom-0 z-30 border-t border-bunker-800 bg-bunker-900 pb-[env(safe-area-inset-bottom)] md:hidden">
      <ul className="flex">
        {main.map((m) => (
          <li key={m.id} className="flex-1">
            <Link href={m.href} aria-current={isActive(m.href) ? "page" : undefined}
              className={`touch-target flex min-h-[44px] flex-col items-center justify-center text-xs ${isActive(m.href) ? "text-neon-green" : "text-bunker-muted"}`}>
              <span aria-hidden className="text-lg">{m.icon}</span>{m.label}
            </Link>
          </li>
        ))}
        {rest.length > 0 && (
          <li className="relative flex-1">
            <details className="group">
              <summary className="touch-target flex min-h-[44px] cursor-pointer list-none flex-col items-center justify-center text-xs text-bunker-muted">
                <span aria-hidden className="text-lg">☰</span>Diğer
              </summary>
              <ul className="absolute bottom-full right-0 mb-1 w-44 rounded-xl border border-bunker-800 bg-bunker-900 p-1 shadow-lg">
                {rest.map((m) => (
                  <li key={m.id}><Link href={m.href} className="flex min-h-[44px] items-center gap-2 rounded-lg px-3 text-sm text-white"><span aria-hidden>{m.icon}</span>{m.label}</Link></li>
                ))}
              </ul>
            </details>
          </li>
        )}
      </ul>
    </nav>
  );
}
```

- [ ] **Step 4: Rol dalı** — `AppShell.tsx`: dosya başına `import UserShell from "./user/UserShell"; import { useAuth } from "../lib/auth"; import { isUserRole } from "../lib/userUi";`. Bileşen içinde `const { role } = useAuth();` ve **mevcut `return (` bloğundan önce** (embedded dalından sonra):
```tsx
  if (isUserRole(role)) {
    return <UserShell>{children}</UserShell>;
  }
```
Hook sırasını bozmamak için `useAuth()` çağrısı diğer hook'larla birlikte en üstte olmalı. `layout.tsx` değişmez (tema, `UserShell` içindeki efektle yazılır; ilk boyamada kısa koyu parlama olmaması için `layout.tsx`'e `<html suppressHydrationWarning>` zaten gerekliyse korunur).

- [ ] **Step 5: Doğrula** — `npm run typecheck && npm run lint && npm test`; tarayıcıda `user` hesabı ile giriş → light kabuk, admin ile koyu kabuk (ekran görüntüsü).
- [ ] **Step 6: Commit** — `feat(user-ui): light tema katmanı, UserShell ve rol dalı`

---

### Task 5: Menü tercihleri kancası (`useUiPrefs`) + Ayarlar'da göster/gizle

**Files:**
- Create: `frontend/app/lib/useUiPrefs.ts`

**Interfaces:**
- Consumes: `GET/PUT /api/profile/ui-prefs` (Task 2), `apiRequest`/`API_BASE` (`lib/api.ts`).
- Produces: `useUiPrefs(): { hidden: string[]; setHidden(next: string[]): Promise<void>; loaded: boolean }`.

- [ ] **Step 1: Implement**
```ts
"use client";
import { useCallback, useEffect, useState } from "react";
import { API_BASE, apiRequest } from "./api";

const KEY = "scalper:user-hidden-menu";

function readCache(): string[] {
  try {
    const raw = localStorage.getItem(KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.map(String) : [];
  } catch { return []; }
}
function writeCache(v: string[]) { try { localStorage.setItem(KEY, JSON.stringify(v)); } catch { /* yok say */ } }

export function useUiPrefs() {
  const [hidden, setHiddenState] = useState<string[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    setHiddenState(readCache());
    let alive = true;
    apiRequest(`${API_BASE}/api/profile/ui-prefs`)
      .then((r) => r.json())
      .then((d) => { if (alive && Array.isArray(d?.hidden_menu)) { setHiddenState(d.hidden_menu); writeCache(d.hidden_menu); } })
      .catch(() => undefined)
      .finally(() => { if (alive) setLoaded(true); });
    return () => { alive = false; };
  }, []);

  const setHidden = useCallback(async (next: string[]) => {
    const prev = readCache();
    setHiddenState(next); writeCache(next);
    try {
      const r = await apiRequest(`${API_BASE}/api/profile/ui-prefs`, {
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ hidden_menu: next }),
      });
      if (!r.ok) throw new Error(String(r.status));
    } catch (e) {
      setHiddenState(prev); writeCache(prev);   // geri al
      throw e;
    }
  }, []);

  return { hidden, setHidden, loaded };
}
```
Çoklu bileşenin (UserShell + UserSettings) aynı durumu görmesi için `window.dispatchEvent(new Event("scalper:ui-prefs"))` yayınla ve kancada dinle (`useEffect` içinde `readCache`'i yeniden oku).

- [ ] **Step 2: Doğrula** — typecheck; iki sekmede menü gizle → yenileyince DB'den geri gelir.
- [ ] **Step 3: Commit** — `feat(user-ui): menü tercihleri kancası (localStorage + DB)`

---

### Task 6: Canlı fiyat kancası + Ana Sayfa + Bildirimler

**Files:**
- Create: `frontend/app/lib/useWatchPrices.ts`, `components/user/KpiStrip.tsx`, `RisingLiveTable.tsx`, `RecentNotifications.tsx`, `UserHome.tsx`, `UserNotifications.tsx`, `frontend/app/notifications/page.tsx`
- Modify: `frontend/app/page.tsx` (rol dalı)

**Interfaces:**
- Consumes: Task 1 yardımcıları; `useLiveMessages`, `useLiveStatus`, `liveSilenceMs` (`lib/liveSocket.ts`), `useVisibleInterval(cb, ms)` (`lib/useVisibleInterval.ts`; imzayı dosyada doğrula), `getJSON` (`lib/api.ts`).
- Produces: `useWatchPrices(symbols: string[]): Record<string, number>`.

- [ ] **Step 1: `useWatchPrices.ts`**
```ts
"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { getJSON } from "./api";
import { liveSilenceMs, useLiveMessages } from "./liveSocket";
import { useVisibleInterval } from "./useVisibleInterval";

const SILENCE_MS = 15_000;

export function useWatchPrices(symbols: string[]): Record<string, number> {
  const [prices, setPrices] = useState<Record<string, number>>({});
  const symbolsRef = useRef<string[]>([]);
  symbolsRef.current = [...new Set(symbols.filter(Boolean))].slice(0, 50);

  useLiveMessages(useCallback((m: any) => {
    if (m?.type !== "watch_prices") return;
    const next = m?.data?.prices;
    if (next && typeof next === "object") setPrices((cur) => ({ ...cur, ...next }));
  }, []), ["watch_prices"]);

  // Yedek: WS 15 sn sessizse tek toplu istekle yokla.
  const poll = useCallback(async () => {
    const list = symbolsRef.current;
    if (!list.length || liveSilenceMs("watch_prices") < SILENCE_MS) return;
    try {
      const d = await getJSON<{ tickers?: { symbol: string; available: boolean; last: number }[] }>(
        `/api/market-tickers?symbols=${list.join(",")}`);
      const next: Record<string, number> = {};
      for (const t of d.tickers ?? []) if (t.available && t.last > 0) next[t.symbol] = t.last;
      setPrices((cur) => ({ ...cur, ...next }));
    } catch { /* sessiz */ }
  }, []);
  useVisibleInterval(poll, 5_000);
  useEffect(() => { void poll(); }, [poll, symbols.join(",")]);
  return prices;
}
```
**Doğrulama notu:** `liveSilenceMs`'in imzasını (`liveSocket.ts` sonu) oku; tip-başına sessizlik vermiyorsa genel `liveSilenceMs()` kullan ve son `watch_prices` zamanını `useRef` ile tut. `UNCONSUMED_LIVE_TYPES`'a `watch_prices` EKLEME.

- [ ] **Step 2: `UserHome.tsx`** — üç blok, veri `useVisibleInterval` ile 15 sn'de bir:
```tsx
"use client";
import { useCallback, useState } from "react";
import { getJSON } from "../../lib/api";
import { useVisibleInterval } from "../../lib/useVisibleInterval";
import { useWatchPrices } from "../../lib/useWatchPrices";
import KpiStrip from "./KpiStrip";
import RisingLiveTable from "./RisingLiveTable";
import RecentNotifications from "./RecentNotifications";

export default function UserHome() {
  const [kpiToday, setKpiToday] = useState<any>(null);
  const [kpiAll, setKpiAll] = useState<any>(null);
  const [rising, setRising] = useState<any[]>([]);
  const [recent, setRecent] = useState<any[]>([]);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const [today, all, live, hist] = await Promise.all([
        getJSON<any>("/api/reports/notifications?limit=1&history_only=false"),
        getJSON<any>("/api/reports/notifications?day=all&limit=1"),
        getJSON<any>("/api/daily-rising/live"),
        getJSON<any>("/api/monitoring/notifications"),
      ]);
      setKpiToday(today?.breakdown ?? null);
      setKpiAll(all?.overall ?? null);
      setRising(live?.live ?? []);
      setRecent((hist?.history ?? []).slice(0, 5));
      setError("");
    } catch (e) { setError(e instanceof Error ? e.message : "Veriler yüklenemedi"); }
  }, []);
  useVisibleInterval(load, 15_000);
  // ilk yük useVisibleInterval içinde çalışmıyorsa: useEffect(() => { void load(); }, [load]);

  const prices = useWatchPrices([...rising.map((r) => r.symbol), ...recent.map((r) => r.symbol)]);
  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Ana sayfa</h1>
      {error && <p role="alert" className="rounded-lg bg-neon-red/10 p-3 text-sm text-neon-red">{error}</p>}
      <KpiStrip today={kpiToday} all={kpiAll} />
      <RisingLiveTable rows={rising} prices={prices} />
      <RecentNotifications rows={recent} prices={prices} />
    </div>
  );
}
```
`KpiStrip.tsx`: iki kart "Bugünkü başarı" / "Toplam başarı"; değer `success_rate` (`null` → "—"), alt satır `${success_count}/${evaluated} bildirim hedefe ulaştı`; `evaluated===0` → "Henüz ölçülmedi". `RisingLiveTable.tsx`: sütunlar Sembol, Bildirim fiyatı (`entry_price`), Canlı (`prices[symbol] ?? current_price`), Değişim (`pctChange(entry, live)`; ▲ yeşil / ▼ kırmızı, `—`), Tavan (`ceiling_pct`), mobilde kart. `RecentNotifications.tsx`: sütunlar Zaman (`detected_at`, `toLocaleTimeString("tr-TR")` + göreli), Sembol (`SymbolLink`), Bildirim fiyatı (`price`), Canlı, Değişim. Boş durum: "Henüz bildirim yok. Sistem yeni bir fırsat bulduğunda burada görünür." Sayı biçimi `lib/format.ts` yardımcılarıyla.

- [ ] **Step 3: `UserNotifications.tsx` + rota** — `GET /api/reports/notifications?limit=200&day=${day}` (`day`: `"all"` veya bugünün `YYYY-MM-DD`'si UTC+3), filtre düğmeleri Bugün / Tümü / Yalnız hedefe ulaşanlar (`status==="TAMAMEN BAŞARILI"`). Tablo sütunları: Zaman, Sembol, Bildirim fiyatı, Hedef % (`target_pct`), Ufuk (`${horizon_minutes} dk`), Sonuç (`statusLabel(status)` rozeti), Pencere bitişi (`windowEnd(detected_at, horizon_minutes)` → saat; `BEKLİYOR` ise "kalan N dk"). Mobilde kart. `frontend/app/notifications/page.tsx`:
```tsx
"use client";
import { useAuth } from "../lib/auth";
import { isUserRole } from "../lib/userUi";
import UserNotifications from "../components/user/UserNotifications";

export default function NotificationsPage() {
  const { role } = useAuth();
  if (!isUserRole(role)) return <p className="p-4 text-sm text-bunker-muted">Yönetici bildirimleri Radar sayfasındaki Bildirimler sekmesindedir.</p>;
  return <UserNotifications />;
}
```
- [ ] **Step 4: `page.tsx` rol dalı** — `export default function Page()` içinde, hook'lardan sonra (Hook sırası sabit kalsın diye mevcut bileşeni `AdminHome` olarak yeniden adlandır, yeni `Page` şunu döndürür): `isUserRole(role) ? <UserHome /> : <AdminHome />`.
- [ ] **Step 5: Doğrula** — typecheck/lint/test; kullanıcı hesabıyla elle: KPI, canlı tablo, son 5; WS'i kes (devtools offline) → 15 sn sonra yoklama; 375 px ekran görüntüsü.
- [ ] **Step 6: Commit** — `feat(user-ui): Ana Sayfa, Bildirimler ve canlı fiyat kancası`

---

### Task 7: Radar — bileşen çıkarma + sade kullanıcı Radar'ı

**Files:**
- Create: `frontend/app/components/user/UserRadar.tsx`
- Modify: `frontend/app/monitoring/page.tsx` (rol dalı; admin davranışı aynı)

**Interfaces:**
- Consumes: `GET /api/monitoring/state` (`warm`, `watchlist`, `candidates`), `GET /api/monitoring/notifications` (`history`), `useWatchPrices`, `confidenceBadge`, `pctChange`, `useLiveMessages(["monitoring_alert"])`.

- [ ] **Step 1:** `monitoring/page.tsx` içinde varsayılan export `MonitoringPage` → `AdminMonitoringPage` olarak yeniden adlandır; yeni varsayılan export: `isUserRole(role) ? <UserRadar /> : <AdminMonitoringPage />`. Admin kodu başka hiçbir yerde değişmez (bileşen çıkarma gerekmez — kullanıcı Radar'ı kendi sade satırını çizer; kopyalanan mantık yalnız `panelScore` ve parse yardımcılarının ihtiyaç duyulan kısmıdır, küçükse `UserRadar` içinde yerel tutulur).
- [ ] **Step 2: `UserRadar.tsx`** — üç sekme (`role="tablist"`): **Isınanlar** (`state.warm`), **İzlemedekiler** (`state.watchlist`), **Gönderilen bildirimler** (`history`). Veri: `loadState` 30 sn (`useVisibleInterval`) + `monitoring_alert` WS'inde 2.5 sn debounce'lu yenileme. Her satır (kart): sembol (`SymbolLink`), tek cümle durum, fiyat, hedef %, güven rozeti (`confidenceBadge(score)`), canlı değişim (`pctChange(price, prices[symbol])`). Durum cümleleri: Isınanlar → "Hareketlenme başladı, henüz izlemede değil"; İzlemedekiler → "Sistem bu coini izliyor"; Bildirimler → "Bildirim gönderildi · {göreli zaman}". Detay: satıra tıklayınca `<dialog>`/modal — "Neden önerildi" (`message` ilk cümle, yoksa "Sistem bu coinde güçlü bir yükseliş sinyali buldu"), hedef %, ufuk, "Grafikte gör" (`/charts?symbol=`). Boş durumlar: "Şu an ısınan coin yok. Sistem tarama yapmaya devam ediyor." Sekme seçimi `localStorage` (`scalper:user-radar-tab`).
- [ ] **Step 3: Doğrula** — admin ile `/monitoring` eskisi gibi (ekran görüntüsü karşılaştır), kullanıcı ile sade görünüm; typecheck/lint.
- [ ] **Step 4: Commit** — `feat(user-ui): sade kullanıcı Radar'ı (Isınanlar, İzlemedekiler, Bildirimler)`

---

### Task 8: Kullanıcı Ayarları (menü göster/gizle + Binance API anahtarı)

**Files:**
- Create: `frontend/app/components/user/UserSettings.tsx`
- Modify: `frontend/app/settings/page.tsx` (rol dalı: kullanıcıya `UserSettings`, admin mevcut `RequireAdmin` sayfası)

**Interfaces:**
- Consumes: `useUiPrefs` (Task 5), `MENU_ITEMS`, `GET/POST /api/binance/settings` (`{configured, sell_enabled, sell_source}` / gövde `{api_key, api_secret}`; secret dönmez), `requestNotificationPermission` benzeri mevcut `lib/push.ts` işlevleri (adı dosyada doğrula).

- [ ] **Step 1: Menü bölümü** — `MENU_ITEMS` listesi; `locked` öğeler pasif ("Her zaman görünür"); diğerleri `role="switch"` düğmesi (`aria-checked`). Değişiklik `setHidden([...])`; hata → "Kaydedilemedi, tekrar dene".
- [ ] **Step 2: Binance anahtarı bölümü**
```tsx
// durum: GET /api/binance/settings → configured
// form: <input type="text" autoComplete="off" name="api_key"> ve <input type="password" autoComplete="new-password" name="api_secret">
// kaydet: POST /api/binance/settings { api_key, api_secret }  (yalnız ikisi de doluysa)
// başarı: alanlar temizlenir, durum "Anahtar kayıtlı" (secret asla geri gösterilmez)
// güvenlik notu: "Anahtarın yalnız okuma ve spot işlem yetkisi olsun; para çekme yetkisi VERME."
```
`real_sell_enabled` bu ekranda **gösterilmez/değiştirilmez** (kapalı kalır; mevcut Binance TR sayfasındaki ayrı onay akışı geçerli). Formda tarayıcı otomatik doldurma kapalı; gönderimden sonra `state` temizlenir; hata mesajı backend `detail`'ini gösterir (secret içermez).
- [ ] **Step 3: Bildirim bölümü** — mevcut push yardımcılarıyla "Bildirim izni: açık/kapalı" durumu ve "Bildirimleri aç" düğmesi.
- [ ] **Step 4: `settings/page.tsx` rol dalı** — mevcut bileşeni `AdminSettingsPage` olarak yeniden adlandır (içindeki `RequireAdmin` korunur); yeni varsayılan export `isUserRole(role) ? <UserSettings /> : <AdminSettingsPage />`.
- [ ] **Step 5: Doğrula** — typecheck/lint; kullanıcıyla: menü gizle → alt/üst menü anında değişir, yenileyince kalır; anahtar kaydet → ağ sekmesinde yanıtta secret yok; `git grep -n "api_secret" frontend/app/components/user` yalnız form alanı/gönderimde geçer, `console.log` yok.
- [ ] **Step 6: Commit** — `feat(user-ui): kullanıcı ayarları (menü ve Binance anahtarı)`

---

### Task 9: Aşama 2 — Portföy, Grafik, Raporlar, Profil light taraması

**Files:**
- Modify: `frontend/app/user-theme.manual.css`, gerektiğinde `frontend/app/charts/*` (grafik renkleri), `frontend/app/reports/page.tsx` (rol dalı)

- [ ] **Step 1: Raporlar rol dalı** — `reports/page.tsx` `MAIN_TABS` filtresi: kullanıcıya yalnız `overview` ve `radar` sekmeleri (+ `combined_paper` değil); varsayılan sekme `overview`; "Arşivi göster" ve rapor başlangıcı notu kullanıcıya gösterilir. Yönetici sekmeleri (`advanced`) zaten admin; `positions`, `llm_compare`, `symbols`, `mtf`, `daily_rising` kullanıcıdan gizlenir.
- [ ] **Step 2: Tema taraması** — her sayfa için kullanıcı hesabıyla 375 px ve 1280 px ekran görüntüsü al; kontrast (WCAG AA), okunmayan metin, beyaz-üstü-beyaz, gradyan (`from-/to-/via-` sınıfları üretilmez → `user-theme.manual.css`'e elle), SVG/Canvas grafik renkleri. Her bulgu için `user-theme.manual.css`'e hedefli kural ekle; kapsam dışı koyu kalan bileşen varsa listele.
- [ ] **Step 3: Grafik** — `charts/` altında mum grafik kütüphanesinin arka plan/grid/metin renklerini `document.documentElement.dataset.theme === "light"` ise açık palete çevir (grafik oluşturulurken okunur; admin etkilenmez).
- [ ] **Step 4: Doğrula** — admin hesabı ile aynı sayfalar DEĞİŞMEDİ (ekran görüntüsü karşılaştır); typecheck/lint/test.
- [ ] **Step 5: Commit** — `feat(user-ui): Aşama 2 — Portföy, Grafik, Raporlar, Profil light temada`

---

### Task 10: Bütünleşik doğrulama

- [ ] **Step 1:** `cd backend && python -m pytest tests -q` (Postgres gerektirenler ortamda yoksa belirt) ve `ruff check app tests scripts`.
- [ ] **Step 2:** `cd frontend && npm run typecheck && npm run lint && npm test`.
- [ ] **Step 3:** Uçtan uca elle: (a) `user` girişi → light kabuk, 8 öğe; (b) admin girişi → koyu, değişmemiş; (c) menü gizle → farklı tarayıcıda aynı; (d) Ana Sayfa canlı değişim güncelleniyor; (e) WS kes → yoklama; (f) Bildirimler sonuç sütunu; (g) Radar 3 sekme; (h) Ayarlar'da anahtar kaydı, yanıtta secret yok; (i) kullanıcı `/admin`'e gider → yetki ekranı.
- [ ] **Step 4:** `docs/DENEY_KAYDI.md` gerekmez (eşik/bayrak değişikliği yok); `README.md` router tablosu testi (`test_readme_router_table.py`) geçmeli.
- [ ] **Step 5: Commit/PR notu** — kalan bilinen eksikleri yaz.

---

## Self-Review (spec ↔ plan)

- §2 rol/tema → Task 4; §3 menü+DB → Task 2, 5, 8; §4 Ana Sayfa + WS → Task 3, 6; §5 Bildirimler → Task 6; §6 Radar → Task 7; §7 Ayarlar/API key → Task 8; §8 Aşama 2 → Task 9; §10 test → Task 1–3, 10. Boşluk yok.
- Tip tutarlılığı: `pctChange`, `statusLabel`, `windowEnd`, `confidenceBadge`, `visibleMenu`, `isUserRole`, `MENU_IDS` (backend) ↔ `MENU_ITEMS` kimlikleri (frontend) aynı sekiz kimlik: home, notifications, radar, portfolio, charts, reports, profile, settings; kilitli: home, settings.
- Bilinçli doğrulama noktaları (kod okunarak teyit edilecek, yer tutucu değil): `ws_manager` bağlantı özniteliği adı, `database.list_daily_rising` imzası, `_batch_prices` dönüş biçimi, `liveSilenceMs` imzası, `useVisibleInterval` imzası, `lib/push.ts` işlev adları, migration kayıt mekanizması.
