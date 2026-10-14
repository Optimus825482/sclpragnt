"use client";

import { useCallback, useEffect, useState } from "react";
import { apiRequest } from "./api";
import { useAuth } from "./auth";

const WATCHLIST_EVENT = "odak:watchlist-updated";

function storageKey(username: string | null) {
  return `odak_favorite_symbols:${String(username || "anonymous").toLowerCase()}`;
}

function normalizeSymbols(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return Array.from(new Set(value.map((symbol) => String(symbol).toUpperCase().trim()).filter(Boolean))).slice(0, 50);
}

export function getFavoritesFromStorage(username: string | null = null): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(storageKey(username));
    return raw ? normalizeSymbols(JSON.parse(raw)) : [];
  } catch {
    return [];
  }
}

function saveFavoritesToStorage(favorites: string[], username: string | null): void {
  if (typeof window === "undefined") return;
  const symbols = normalizeSymbols(favorites);
  try {
    localStorage.setItem(storageKey(username), JSON.stringify(symbols));
  } catch {
    return;
  }
  window.dispatchEvent(new CustomEvent(WATCHLIST_EVENT, { detail: { username, symbols } }));
}

export function useWatchlist() {
  const { username } = useAuth();
  const [favorites, setFavorites] = useState<string[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [remoteReady, setRemoteReady] = useState(false);
  const key = storageKey(username);

  useEffect(() => {
    let active = true;
    setFavorites(getFavoritesFromStorage(username));
    setLoaded(false);
    setRemoteReady(false);

    apiRequest("/api/user/favorites", { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new Error(`Favoriler alınamadı (${response.status})`);
        const body = await response.json();
        if (!active) return;
        const symbols = normalizeSymbols(body?.symbols);
        setFavorites(symbols);
        saveFavoritesToStorage(symbols, username);
      })
      .catch(() => {
        if (active) setFavorites(getFavoritesFromStorage(username));
      })
      .finally(() => {
        if (!active) return;
        setLoaded(true);
        setRemoteReady(true);
      });

    const handleUpdate = (event: Event) => {
      const custom = event as CustomEvent<{ username?: string | null; symbols?: string[] }>;
      if (custom.detail && String(custom.detail.username || "").toLowerCase() === String(username || "").toLowerCase()) {
        setFavorites(normalizeSymbols(custom.detail.symbols));
        return;
      }
      if (event.type === "storage" && (event as StorageEvent).key === key) {
        setFavorites(getFavoritesFromStorage(username));
      }
    };

    window.addEventListener(WATCHLIST_EVENT, handleUpdate);
    window.addEventListener("storage", handleUpdate);
    return () => {
      active = false;
      window.removeEventListener(WATCHLIST_EVENT, handleUpdate);
      window.removeEventListener("storage", handleUpdate);
    };
  }, [key, username]);

  useEffect(() => {
    if (!remoteReady || !username) return;
    const symbols = normalizeSymbols(favorites);
    saveFavoritesToStorage(symbols, username);
    const timer = window.setTimeout(() => {
      apiRequest("/api/user/favorites", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbols }),
      }).catch(() => {});
    }, 250);
    return () => window.clearTimeout(timer);
  }, [favorites, remoteReady, username]);

  const toggleFavorite = useCallback((symbol: string) => {
    const upper = String(symbol || "").toUpperCase().trim();
    if (!upper) return;
    setFavorites((previous) => previous.includes(upper)
      ? previous.filter((item) => item !== upper)
      : [...previous, upper].slice(-50));
  }, []);

  const isFavorite = useCallback((symbol: string) => {
    const upper = String(symbol || "").toUpperCase().trim();
    return favorites.includes(upper);
  }, [favorites]);

  return { favorites, toggleFavorite, isFavorite, loaded };
}
