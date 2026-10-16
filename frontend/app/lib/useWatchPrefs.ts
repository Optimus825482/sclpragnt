"use client";
import { useCallback, useEffect, useState } from "react";
import { API_BASE, apiRequest } from "./api";

/** Favori / izlemeye alınan sembol kaydı. `symbol` tam ("STRAXTRY"), `price` tıklama anındaki fiyat, `at` epoch saniye. */
export type WatchItem = { symbol: string; price: number; at: number };
export type WatchKey = "favorites" | "pinned";
export type WatchState = { favorites: WatchItem[]; pinned: WatchItem[] };

export const WATCH_MAX = 30;
const KEY = "scalper:user-watch-prefs";
const EVENT = "scalper:watch-prefs";
const EMPTY: WatchState = { favorites: [], pinned: [] };

function normSymbol(s: unknown): string {
  return String(s ?? "").replace(/_/g, "").trim().toUpperCase();
}

/** Bozuk/eksik girdiyi güvenli listeye çevirir (sembol tekrarsız, en fazla 30). */
export function normalizeWatchList(raw: unknown): WatchItem[] {
  if (!Array.isArray(raw)) return [];
  const seen = new Set<string>();
  const out: WatchItem[] = [];
  for (const it of raw) {
    const symbol = normSymbol((it as WatchItem | null)?.symbol);
    if (!symbol || seen.has(symbol)) continue;
    seen.add(symbol);
    const price = Number((it as WatchItem).price);
    const at = Number((it as WatchItem).at);
    out.push({ symbol, price: Number.isFinite(price) && price > 0 ? price : 0, at: Number.isFinite(at) && at > 0 ? at : 0 });
    if (out.length >= WATCH_MAX) break;
  }
  return out;
}

/** Listeye ekler (aynı sembol varsa değiştirir); en yeni başta, en fazla 30. */
export function addWatchItem(list: WatchItem[], item: WatchItem): WatchItem[] {
  return [item, ...list.filter((x) => x.symbol !== item.symbol)].slice(0, WATCH_MAX);
}

export function removeWatchItem(list: WatchItem[], symbol: string): WatchItem[] {
  const s = normSymbol(symbol);
  return list.filter((x) => x.symbol !== s);
}

export function hasWatchItem(list: WatchItem[], symbol: string): boolean {
  const s = normSymbol(symbol);
  return list.some((x) => x.symbol === s);
}

function readCache(): WatchState {
  try {
    const raw = localStorage.getItem(KEY);
    const p = raw ? JSON.parse(raw) : null;
    return { favorites: normalizeWatchList(p?.favorites), pinned: normalizeWatchList(p?.pinned) };
  } catch {
    return EMPTY;
  }
}

function writeCache(v: WatchState) {
  try {
    localStorage.setItem(KEY, JSON.stringify(v));
  } catch {
    /* yok say */
  }
}

/**
 * Favoriler + izlemedekiler: önce localStorage önbelleği, sonra DB (`/api/profile/ui-prefs`, cihazlar arası).
 * PUT yalnızca değişen anahtarı gönderir (`{pinned}` ya da `{favorites}`; `hidden_menu` asla).
 * İyimser güncelleme; PUT başarısızsa yalnızca o anahtar eski değerine döner ve hata fırlatılır.
 */
export function useWatchPrefs() {
  const [state, setState] = useState<WatchState>(EMPTY);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    setState(readCache());
    const onChange = () => setState(readCache());
    window.addEventListener(EVENT, onChange);
    let alive = true;
    apiRequest(`${API_BASE}/api/profile/ui-prefs`)
      .then((r) => r.json())
      .then((d) => {
        if (!alive || !d) return;
        const cur = readCache();
        const next: WatchState = {
          favorites: Array.isArray(d.favorites) ? normalizeWatchList(d.favorites) : cur.favorites,
          pinned: Array.isArray(d.pinned) ? normalizeWatchList(d.pinned) : cur.pinned,
        };
        setState(next);
        writeCache(next);
      })
      .catch(() => undefined)
      .finally(() => {
        if (alive) setLoaded(true);
      });
    return () => {
      alive = false;
      window.removeEventListener(EVENT, onChange);
    };
  }, []);

  const commit = useCallback(async (key: WatchKey, next: WatchItem[]) => {
    const before = readCache();
    const prev = before[key];
    const apply = (list: WatchItem[]) => {
      const merged = { ...readCache(), [key]: list } as WatchState;
      setState(merged);
      writeCache(merged);
      window.dispatchEvent(new Event(EVENT));
    };
    apply(next);
    try {
      const r = await apiRequest(`${API_BASE}/api/profile/ui-prefs`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ [key]: next }),
      });
      if (!r.ok) throw new Error(String(r.status));
    } catch (e) {
      apply(prev);
      throw e;
    }
  }, []);

  const toggle = useCallback(
    (key: WatchKey, symbol: string, price: number | null | undefined) => {
      const sym = normSymbol(symbol);
      if (!sym) return Promise.resolve();
      const list = readCache()[key];
      if (hasWatchItem(list, sym)) return commit(key, removeWatchItem(list, sym));
      const p = Number(price);
      return commit(key, addWatchItem(list, { symbol: sym, price: Number.isFinite(p) && p > 0 ? p : 0, at: Math.floor(Date.now() / 1000) }));
    },
    [commit],
  );

  const remove = useCallback(
    (key: WatchKey, symbol: string) => commit(key, removeWatchItem(readCache()[key], symbol)),
    [commit],
  );

  return {
    favorites: state.favorites,
    pinned: state.pinned,
    loaded,
    isFavorite: (symbol: string) => hasWatchItem(state.favorites, symbol),
    isPinned: (symbol: string) => hasWatchItem(state.pinned, symbol),
    /** Ekler/çıkarır. `price` = tıklama anındaki canlı fiyat (yoksa bildirim fiyatı). Hata → reddedilir (UI geri alınmıştır). */
    toggleFavorite: (symbol: string, price: number | null | undefined) => toggle("favorites", symbol, price),
    togglePin: (symbol: string, price: number | null | undefined) => toggle("pinned", symbol, price),
    removeFavorite: (symbol: string) => remove("favorites", symbol),
    removePin: (symbol: string) => remove("pinned", symbol),
  };
}

export type WatchPrefs = ReturnType<typeof useWatchPrefs>;
