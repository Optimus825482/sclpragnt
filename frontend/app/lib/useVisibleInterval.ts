"use client";

import { useEffect, useRef } from "react";

export interface VisibleIntervalOptions {
  runOnVisible?: boolean;
}

/**
 * Görünürlük-farkında periyodik interval hook'u.
 * Sekme arka plandayken zamanlayıcıyı durdurur; gereksiz ağ ve CPU tüketimini önler.
 * Sekme tekrar öne geldiğinde hemen çalışır (isteğe bağlı) ve periyot devam eder.
 */
export function useVisibleInterval(
  callback: () => void,
  ms: number | null,
  options?: VisibleIntervalOptions
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
          if (typeof document !== "undefined" && !document.hidden) {
            cbRef.current();
          }
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
        if (runOnVisible) {
          cbRef.current();
        }
        start();
      } else {
        stop();
      }
    };

    if (typeof document === "undefined" || document.visibilityState === "visible") {
      start();
    }

    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      stop();
    };
  }, [ms, runOnVisible]);
}
