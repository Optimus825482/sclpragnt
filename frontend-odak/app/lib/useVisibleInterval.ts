"use client";

import { useEffect, useRef } from "react";

/**
 * Görünürlük-farkında periyodik interval. Sekme arka plandayken durur; öne
 * geldiğinde hemen çalışır (varsayılan). Koyu tema frontend'iyle aynı davranış.
 */
export function useVisibleInterval(
  callback: () => void,
  ms: number | null,
  options?: { runOnVisible?: boolean },
) {
  const cbRef = useRef(callback);
  useEffect(() => {
    cbRef.current = callback;
  }, [callback]);

  const runOnVisible = options?.runOnVisible ?? true;

  useEffect(() => {
    if (ms === null || ms <= 0) return;
    let timer: ReturnType<typeof setInterval> | null = null;
    const start = () => {
      if (!timer) {
        timer = setInterval(() => {
          if (typeof document !== "undefined" && !document.hidden) cbRef.current();
        }, ms);
      }
    };
    const stop = () => {
      if (timer) {
        clearInterval(timer);
        timer = null;
      }
    };
    const onVisibility = () => {
      if (typeof document === "undefined") return;
      if (document.visibilityState === "visible") {
        if (runOnVisible) cbRef.current();
        start();
      } else {
        stop();
      }
    };
    if (typeof document === "undefined" || document.visibilityState === "visible") start();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      stop();
    };
  }, [ms, runOnVisible]);
}
