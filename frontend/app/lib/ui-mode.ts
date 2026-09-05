"use client";

import { useCallback, useEffect, useState } from "react";

type UiMode = "simple" | "advanced";

const STORAGE_KEY = "scalper:ui-mode";

/** Kullanıcının Basit/Gelişmiş mod tercihini localStorage'ta saklar/döndürür. */
export function getUiMode(): UiMode {
  if (typeof window === "undefined") return "advanced";
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "simple" || stored === "advanced") return stored;
  } catch { /* yoksay */ }
  return "advanced";
}

export function setUiMode(mode: UiMode) {
  try { localStorage.setItem(STORAGE_KEY, mode); } catch { /* yoksay */ }
}

export function toggleUiMode(): UiMode {
  const next = getUiMode() === "simple" ? "advanced" : "simple";
  setUiMode(next);
  return next;
}

/** React hook: mod değiştiğinde yeniden render tetikler. */
export function useUiMode(): [UiMode, () => void] {
  const [mode, setMode] = useState<UiMode>("advanced");

  useEffect(() => {
    setMode(getUiMode());
  }, []);

  const toggle = useCallback(() => {
    const next = toggleUiMode();
    setMode(next);
  }, []);

  return [mode, toggle];
}