"use client";

import { useCallback, useEffect, useState } from "react";
import { apiRequest } from "./api";

const STORAGE_KEY = "odak_favorite_symbols";

// Sayfa içi ve sekmeler arası reaktif güncelleme için özel olay
const WATCHLIST_EVENT = "odak:watchlist-updated";

export function getFavoritesFromStorage(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.map((s) => String(s).toUpperCase()) : [];
  } catch {
    return [];
  }
}

export function saveFavoritesToStorage(favorites: string[]): void {
  if (typeof window === "undefined") return;
  try {
    const clean = Array.from(new Set(favorites.map((s) => s.toUpperCase())));
    localStorage.setItem(STORAGE_KEY, JSON.stringify(clean));
    window.dispatchEvent(new CustomEvent(WATCHLIST_EVENT, { detail: clean }));
  } catch {
    /* depolama hatası */
  }
}

export function useWatchlist() {
  const [favorites, setFavorites] = useState<string[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    setFavorites(getFavoritesFromStorage());
    setLoaded(true);

    const handleUpdate = (e: Event) => {
      const custom = e as CustomEvent<string[]>;
      if (custom.detail) {
        setFavorites(custom.detail);
      } else {
        setFavorites(getFavoritesFromStorage());
      }
    };

    window.addEventListener(WATCHLIST_EVENT, handleUpdate);
    window.addEventListener("storage", handleUpdate);
    return () => {
      window.removeEventListener(WATCHLIST_EVENT, handleUpdate);
      window.removeEventListener("storage", handleUpdate);
    };
  }, []);

  const toggleFavorite = useCallback((symbol: string) => {
    const upper = String(symbol || "").toUpperCase().trim();
    if (!upper) return;

    setFavorites((prev) => {
      const exists = prev.includes(upper);
      const next = exists ? prev.filter((s) => s !== upper) : [...prev, upper];
      saveFavoritesToStorage(next);

      // Backend watchlist uç noktasına arka planda bildirim (opsiyonel hata vermez)
      if (exists) {
        apiRequest(`/api/daily-rising/watchlist/${encodeURIComponent(upper)}`, { method: "DELETE" }).catch(() => {});
      } else {
        apiRequest(`/api/daily-rising/watchlist`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ symbol: upper }),
        }).catch(() => {});
      }

      return next;
    });
  }, []);

  const isFavorite = useCallback(
    (symbol: string) => {
      const upper = String(symbol || "").toUpperCase().trim();
      return favorites.includes(upper);
    },
    [favorites]
  );

  return { favorites, toggleFavorite, isFavorite, loaded };
}
