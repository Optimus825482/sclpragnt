"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getJSON } from "./api";
import { useVisibleInterval } from "./useVisibleInterval";

export type PollState<T> = { data: T | null; error: string | null; loading: boolean; reload: () => void };

/**
 * GET + periyodik yenileme, ZAMAN AŞIMLI.
 *
 * Neden timeout: bazı backend uçları (ör. `/api/daily-rising/state`, gönderilmiş
 * liste yokken canlı kombine taramaya düşer) onlarca saniye askıda kalabiliyor.
 * Tarayıcı `fetch`'inin varsayılan zaman aşımı yoktur → asılı istek `loading`
 * durumunu sonsuza dek açık bırakır ve sayfa iskelet üstünde donar. AbortController
 * ile sınırlıyoruz; aşılırsa `error` yazılır ve arayüz yaşamaya devam eder.
 */
export function usePoll<T>(path: string | null, intervalMs: number | null, timeoutMs = 12_000): PollState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(Boolean(path));
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const reload = useCallback(() => {
    if (!path) return;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    getJSON<T>(path, { signal: controller.signal })
      .then((value) => {
        if (!mounted.current) return;
        setData(value);
        setError(null);
      })
      .catch((reason: unknown) => {
        if (!mounted.current) return;
        if (reason instanceof DOMException && reason.name === "AbortError") {
          setError(`Zaman aşımı (${timeoutMs / 1000}sn) — sunucu yanıt vermedi`);
        } else {
          setError(reason instanceof Error ? reason.message : "Bağlantı hatası");
        }
      })
      .finally(() => {
        clearTimeout(timer);
        if (mounted.current) setLoading(false);
      });
  }, [path, timeoutMs]);

  useEffect(() => {
    if (!path) return;
    setLoading(true);
    reload();
  }, [path, reload]);

  useVisibleInterval(reload, intervalMs);

  return { data, error, loading, reload };
}
