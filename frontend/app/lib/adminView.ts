"use client";
import { useCallback, useEffect, useState } from "react";
import { useAuth } from "./auth";
import { isUserView, type AdminView } from "./userUi";

const KEY = "scalper:admin-view";
const EVENT = "scalper:admin-view";

function read(): AdminView {
  if (typeof window === "undefined") return "advanced";
  try {
    return localStorage.getItem(KEY) === "simple" ? "simple" : "advanced";
  } catch {
    return "advanced";
  }
}

/** Admin arayüz seçimi: "advanced" = mevcut arayüz, "simple" = kullanıcıların gördüğü arayüz. */
export function useAdminView() {
  // 2026-10-18: seçim ilk render'da okunur (SSR'da "advanced"); basit arayüzdeki admin önce gelişmiş
  // sayfayı mount edip onun isteklerini başlatmasın.
  const [view, setViewState] = useState<AdminView>(read);
  useEffect(() => {
    setViewState(read());
    const onChange = () => setViewState(read());
    window.addEventListener(EVENT, onChange);
    window.addEventListener("storage", onChange);
    return () => {
      window.removeEventListener(EVENT, onChange);
      window.removeEventListener("storage", onChange);
    };
  }, []);
  const setView = useCallback((next: AdminView) => {
    try {
      localStorage.setItem(KEY, next);
    } catch {
      /* yok say */
    }
    setViewState(next);
    window.dispatchEvent(new Event(EVENT));
  }, []);
  return { view, setView };
}

/** Rol + admin seçimine göre kullanıcı arayüzü gösterilmeli mi? */
export function useIsUserView(): boolean {
  const { role } = useAuth();
  const { view } = useAdminView();
  return isUserView(role, view);
}
