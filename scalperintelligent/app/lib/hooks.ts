"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getJSON } from "./api";
import { useVisibleInterval } from "./useVisibleInterval";

export type PollState<T> = {
  data: T | null;
  error: string | null;
  loading: boolean;
  /** Son BAŞARILI yanıtın zamanı (ms). Hata bandında "son güncelleme X sn önce" için. */
  updatedAt: number | null;
  reload: () => void;
};

/**
 * Birden çok bileşenin aynı anda çektiği uçlar (ana sayfada PortfolioStrip,
 * ActiveTradesTable ve OrderPanel üçü de `/api/binance/settings` ister).
 * Aynı yola 5 sn içinde gelen istekler TEK fetch'i paylaşır; ağ yükü ve
 * backend baskısı düşer. SWR benzeri bir bağımlılık eklenmeden, en küçük
 * yeterli dedupe.
 */
const SHARED_TTL_MS = 5_000;
const SHARED_PATHS: ReadonlySet<string> = new Set([
  "/api/binance/settings",
  "/api/binance/positions",
  "/api/market-symbols",
]);
const sharedInflight = new Map<string, { at: number; promise: Promise<unknown> }>();

function sharedGet<T>(path: string, timeoutMs: number): Promise<T> {
  const existing = sharedInflight.get(path);
  if (existing && Date.now() - existing.at < SHARED_TTL_MS) return existing.promise as Promise<T>;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const promise = getJSON<T>(path, { signal: controller.signal })
    .catch((reason: unknown) => {
      // Hatalı yanıt önbellekte kalmasın; bir sonraki çağrı yeniden denesin.
      if (sharedInflight.get(path)?.promise === promise) sharedInflight.delete(path);
      throw reason;
    })
    .finally(() => clearTimeout(timer));
  sharedInflight.set(path, { at: Date.now(), promise });
  return promise;
}

/**
 * GET + periyodik yenileme, ZAMAN AŞIMLI ve SIRA KORUMALI.
 *
 * Neden timeout: bazı backend uçları (ör. `/api/daily-rising/state`, gönderilmiş
 * liste yokken canlı kombine taramaya düşer) onlarca saniye askıda kalabiliyor.
 * Tarayıcı `fetch`'inin varsayılan zaman aşımı yoktur → asılı istek `loading`
 * durumunu sonsuza dek açık bırakır ve sayfa iskelet üstünde donar. AbortController
 * ile sınırlıyoruz; aşılırsa `error` yazılır ve arayüz yaşamaya devam eder.
 *
 * Denetim P1-3 (2026-10-15):
 *   - `path` değişince eski istek iptal edilir ve `data` sıfırlanır; OrderPanel
 *     eski sembolün fiyatıyla SL/TP dolduramaz.
 *   - İstek sıra numarası: geç gelen eski yanıt yenisini ezemez.
 *   - Uçuşta istek varken yeni istek açılmaz (interval + reload üst üste binmez).
 */
export function usePoll<T>(path: string | null, intervalMs: number | null, timeoutMs = 12_000): PollState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(Boolean(path));
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const mounted = useRef(true);
  const sequence = useRef(0);
  const inflight = useRef<AbortController | null>(null);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      inflight.current?.abort();
      inflight.current = null;
    };
  }, []);

  const reload = useCallback(() => {
    if (!path) return;
    if (inflight.current) return;
    const controller = new AbortController();
    inflight.current = controller;
    const id = ++sequence.current;
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    const request = SHARED_PATHS.has(path) ? sharedGet<T>(path, timeoutMs) : getJSON<T>(path, { signal: controller.signal });
    request
      .then((value) => {
        if (!mounted.current || id !== sequence.current) return;
        setData(value);
        setError(null);
        setUpdatedAt(Date.now());
      })
      .catch((reason: unknown) => {
        if (!mounted.current || id !== sequence.current) return;
        if (reason instanceof DOMException && reason.name === "AbortError") {
          setError(`Zaman aşımı (${timeoutMs / 1000}sn) — sunucu yanıt vermedi`);
        } else {
          setError(reason instanceof Error ? reason.message : "Bağlantı hatası");
        }
      })
      .finally(() => {
        clearTimeout(timer);
        if (inflight.current === controller) inflight.current = null;
        if (mounted.current && id === sequence.current) setLoading(false);
      });
  }, [path, timeoutMs]);

  useEffect(() => {
    // Yol değişti: eski isteği geçersiz kıl, önceki yolun verisini gösterme.
    sequence.current += 1;
    inflight.current?.abort();
    inflight.current = null;
    setData(null);
    setError(null);
    setUpdatedAt(null);
    if (!path) {
      setLoading(false);
      return;
    }
    setLoading(true);
    reload();
    return () => {
      inflight.current?.abort();
      inflight.current = null;
    };
  }, [path, reload]);

  useVisibleInterval(reload, intervalMs);

  return { data, error, loading, updatedAt, reload };
}
