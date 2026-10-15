"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
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

export type Watchlist = {
  favorites: string[];
  toggleFavorite: (symbol: string) => void;
  isFavorite: (symbol: string) => boolean;
  /** İlk GET denemesi tamamlandı (başarılı ya da başarısız). */
  loaded: boolean;
  /** Sunucu listesi başarıyla alındı; yalnız bu durumda PUT yapılır. */
  remoteReady: boolean;
  /** Son sunucu hatası (GET/PUT); arayüz isterse gösterir. */
  error: string | null;
};

const WatchlistContext = createContext<Watchlist | null>(null);

/**
 * Favori listesi — TEK sağlayıcı (denetim P1-4).
 *
 * Eski davranış: hook her bileşende ayrı mount oluyordu (N×GET) ve GET 401/5xx
 * olsa bile `remoteReady=true` yapılıp localStorage'daki (çoğu zaman boş) liste
 * sunucuya PUT ediliyordu → sunucudaki favoriler SİLİNİYORDU.
 *
 * Yeni kural:
 *   - PUT yalnız kullanıcı toggle'ında ve yalnız GET başarılıysa.
 *   - GET başarısızsa localStorage kopyası gösterilir, sunucuya yazılmaz.
 *   - Tek context: ana sayfa, TopNav, kartlar, sembol seçici aynı listeyi paylaşır.
 */
export function WatchlistProvider({ children }: { children: ReactNode }) {
  const { username } = useAuth();
  const [favorites, setFavorites] = useState<string[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [remoteReady, setRemoteReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const key = storageKey(username);
  const putTimer = useRef<number | null>(null);
  const favoritesRef = useRef(favorites);
  favoritesRef.current = favorites;

  useEffect(() => {
    let active = true;
    setFavorites(getFavoritesFromStorage(username));
    setLoaded(false);
    setRemoteReady(false);
    setError(null);

    apiRequest("/api/user/favorites", { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new Error(`Favoriler alınamadı (${response.status})`);
        const body = await response.json();
        if (!active) return;
        const symbols = normalizeSymbols(body?.symbols);
        setFavorites(symbols);
        saveFavoritesToStorage(symbols, username);
        setRemoteReady(true);
      })
      .catch((reason: unknown) => {
        if (!active) return;
        setFavorites(getFavoritesFromStorage(username));
        setRemoteReady(false);
        setError(reason instanceof Error ? reason.message : "Favoriler alınamadı");
      })
      .finally(() => {
        if (active) setLoaded(true);
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
      if (putTimer.current) window.clearTimeout(putTimer.current);
      putTimer.current = null;
    };
  }, [key, username]);

  const schedulePut = useCallback(() => {
    if (putTimer.current) window.clearTimeout(putTimer.current);
    putTimer.current = window.setTimeout(() => {
      putTimer.current = null;
      const symbols = normalizeSymbols(favoritesRef.current);
      apiRequest("/api/user/favorites", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbols }),
      })
        .then((response) => {
          if (!response.ok) throw new Error(`Favoriler kaydedilemedi (${response.status})`);
          setError(null);
        })
        .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Favoriler kaydedilemedi"));
    }, 250);
  }, []);

  const toggleFavorite = useCallback((symbol: string) => {
    const upper = String(symbol || "").toUpperCase().trim();
    if (!upper) return;
    const previous = favoritesRef.current;
    const next = previous.includes(upper) ? previous.filter((item) => item !== upper) : [...previous, upper].slice(-50);
    favoritesRef.current = next;
    setFavorites(next);
    saveFavoritesToStorage(next, username);
    // Sunucuya yazım YALNIZ açık kullanıcı eylemi + başarılı GET sonrası.
    if (remoteReady && username) schedulePut();
  }, [remoteReady, schedulePut, username]);

  const isFavorite = useCallback((symbol: string) => {
    const upper = String(symbol || "").toUpperCase().trim();
    return favorites.includes(upper);
  }, [favorites]);

  const value = useMemo<Watchlist>(
    () => ({ favorites, toggleFavorite, isFavorite, loaded, remoteReady, error }),
    [favorites, toggleFavorite, isFavorite, loaded, remoteReady, error],
  );

  return <WatchlistContext.Provider value={value}>{children}</WatchlistContext.Provider>;
}

const EMPTY_WATCHLIST: Watchlist = {
  favorites: [],
  toggleFavorite: () => undefined,
  isFavorite: () => false,
  loaded: false,
  remoteReady: false,
  error: null,
};

/** Sağlayıcı dışında (ör. giriş ekranı) güvenli boş liste döner. */
export function useWatchlist(): Watchlist {
  return useContext(WatchlistContext) ?? EMPTY_WATCHLIST;
}
