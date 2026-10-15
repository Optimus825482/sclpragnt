"use client";
import { useCallback, useEffect, useState } from "react";
import { API_BASE, apiRequest } from "./api";

const KEY = "scalper:user-hidden-menu";
const EVENT = "scalper:ui-prefs";

function readCache(): string[] {
  try {
    const raw = localStorage.getItem(KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.map(String) : [];
  } catch {
    return [];
  }
}

function writeCache(value: string[]) {
  try {
    localStorage.setItem(KEY, JSON.stringify(value));
  } catch {
    /* yok say */
  }
}

/** Menü tercihleri: önce localStorage önbelleği, sonra DB (cihazlar arası aynı menü). */
export function useUiPrefs() {
  const [hidden, setHiddenState] = useState<string[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    setHiddenState(readCache());
    const onChange = () => setHiddenState(readCache());
    window.addEventListener(EVENT, onChange);
    let alive = true;
    apiRequest(`${API_BASE}/api/profile/ui-prefs`)
      .then((r) => r.json())
      .then((d) => {
        if (alive && Array.isArray(d?.hidden_menu)) {
          const next = d.hidden_menu.map(String);
          setHiddenState(next);
          writeCache(next);
        }
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

  const setHidden = useCallback(async (next: string[]) => {
    const prev = readCache();
    setHiddenState(next);
    writeCache(next);
    window.dispatchEvent(new Event(EVENT));
    try {
      const r = await apiRequest(`${API_BASE}/api/profile/ui-prefs`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ hidden_menu: next }),
      });
      if (!r.ok) throw new Error(String(r.status));
    } catch (e) {
      setHiddenState(prev);
      writeCache(prev);
      window.dispatchEvent(new Event(EVENT));
      throw e;
    }
  }, []);

  return { hidden, setHidden, loaded };
}
