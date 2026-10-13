"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getJSON } from "./api";
import { useVisibleInterval } from "./useVisibleInterval";

export type PollState<T> = { data: T | null; error: string | null; loading: boolean; reload: () => void };

/**
 * GET + periyodik yenileme. Ağ hatası `error`'a yazılır (sessizce "veri yok"
 * gibi gösterilmez — koyu tema H-05 ilkesi). Sekme gizliyken durur.
 */
export function usePoll<T>(path: string | null, intervalMs: number | null): PollState<T> {
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
    getJSON<T>(path)
      .then((value) => {
        if (!mounted.current) return;
        setData(value);
        setError(null);
      })
      .catch((reason: unknown) => {
        if (!mounted.current) return;
        setError(reason instanceof Error ? reason.message : "Bağlantı hatası");
      })
      .finally(() => {
        if (mounted.current) setLoading(false);
      });
  }, [path]);

  useEffect(() => {
    if (!path) return;
    setLoading(true);
    reload();
  }, [path, reload]);

  useVisibleInterval(reload, intervalMs);

  return { data, error, loading, reload };
}
