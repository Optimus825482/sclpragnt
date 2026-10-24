"use client";

/**
 * N7 TARAMA — Radar sayfasının ikinci sekmesi.
 *
 * Elle tetiklenen M1H taraması: TARA → POST /api/radar/n7-scan/run {top:3};
 * çalışırken 3 sn'de bir GET /api/radar/n7-scan; bitince en iyi 3 sembol tablo olarak.
 * Saf mantık (normalize, sıralama, biçim) `lib/n7ScanUi.ts` içinde — burada yalnız veri akışı + görünüm.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { API_BASE, apiRequest, getJSON } from "../lib/api";
import { formatPrice, toMs } from "../lib/format";
import { useVisibleInterval } from "../lib/useVisibleInterval";
import {
  N7_DEFAULT_TOP,
  N7_METHOD_NOTE,
  N7_POLL_MS,
  fmtPct,
  fmtRatioX,
  fmtScore,
  fmtSignedPct,
  isAlreadyRunning,
  normalizeState,
  pctTone,
  statusLine,
  stripTry,
  summaryLine,
  topPicks,
  type N7ScanState,
} from "../lib/n7ScanUi";

const fmtClock = (ms: number | null): string => {
  const v = toMs(ms);
  if (!v) return "—";
  return new Date(v).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" });
};

const STATUS_TONE: Record<ReturnType<typeof statusLine>["tone"], string> = {
  muted: "text-bunker-muted",
  running: "text-yellow-300",
  ok: "text-neon-green",
  error: "text-neon-red",
};

const RANK_CLS: Record<number, string> = {
  1: "border-neon-green/50 bg-neon-green/15 text-neon-green",
  2: "border-sky-400/40 bg-sky-400/10 text-sky-300",
  3: "border-yellow-400/40 bg-yellow-400/10 text-yellow-300",
};

const TH = "px-3 py-2 text-left font-medium whitespace-nowrap";
const TD = "px-3 py-2.5 whitespace-nowrap font-mono";

export default function N7ScanPanel() {
  const [state, setState] = useState<N7ScanState | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null); // 409 "zaten çalışıyor" gibi hata-olmayan durumlar
  const [starting, setStarting] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const inFlightRef = useRef(false);

  const refresh = useCallback(async () => {
    if (inFlightRef.current) return;
    inFlightRef.current = true;
    try {
      const data = await getJSON<unknown>("/api/radar/n7-scan");
      setState(normalizeState(data));
      setLoadError(null);
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : "Durum alınamadı");
    } finally {
      inFlightRef.current = false;
    }
  }, []);

  // Açılışta son sonucu bir kez çek (mikrogörev: effect gövdesinde eşzamanlı setState yok).
  useEffect(() => {
    Promise.resolve().then(refresh);
  }, [refresh]);

  const running = state?.status === "running";

  // Çalışırken 3 sn'de bir durum; bitince (done/error/idle) hook'a null verilir → zamanlayıcı durur.
  useVisibleInterval(() => { void refresh(); }, running ? N7_POLL_MS : null);
  // Geçen süre sayacı (1 sn) — yalnız çalışırken.
  useVisibleInterval(() => setNow(Date.now()), running ? 1000 : null, { runOnVisible: false });

  const runScan = useCallback(async () => {
    if (starting || running) return;
    setStarting(true);
    setNotice(null);
    try {
      const res = await apiRequest(`${API_BASE}/api/radar/n7-scan/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ top: N7_DEFAULT_TOP }),
      });
      if (!res.ok) {
        let detail = "";
        try {
          const body = await res.json();
          detail = typeof body?.detail === "string" ? body.detail : "";
        } catch {
          /* gövde JSON olmayabilir */
        }
        const err = new Error(detail || `API ${res.status}`);
        if (res.status === 409 || isAlreadyRunning(err)) {
          setNotice(detail || "Tarama zaten çalışıyor");
        } else {
          setLoadError(err.message);
        }
      } else {
        const body = await res.json().catch(() => null);
        const startedAt = Number(body?.started_at);
        // Anında "running" göster; ilk GET gelene kadar ilerleme 0/0.
        setState((prev) => ({
          status: "running",
          started_at: Number.isFinite(startedAt) && startedAt > 0 ? startedAt : Date.now(),
          finished_at: null,
          progress: { done: 0, total: 0 },
          error: null,
          top: N7_DEFAULT_TOP,
          result: prev?.result ?? null,
        }));
        setNow(Date.now());
      }
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : "Tarama başlatılamadı");
    } finally {
      setStarting(false);
      void refresh();
    }
  }, [starting, running, refresh]);

  const line = state ? statusLine(state, now) : null;
  const picks = topPicks(state?.result ?? null, N7_DEFAULT_TOP);
  const result = state?.result ?? null;

  return (
    <section className="space-y-4" aria-label="N7 taraması">
      <div className="card p-4 sm:p-5 rounded-xl border border-bunker-800 bg-bunker-900/40">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="eyebrow text-neon-green">N7 TARAMA · M1H</p>
            <h2 className="mt-1 font-mono text-lg sm:text-xl font-black text-white">1 Saatte +%2 Adayları</h2>
            <p className="mt-1 text-xs sm:text-sm text-bunker-muted max-w-2xl">
              Elle tetiklenen tarama: tüm evren taranır, en iyi {N7_DEFAULT_TOP} sembol listelenir.
            </p>
          </div>
          <button
            type="button"
            onClick={() => { void runScan(); }}
            disabled={running || starting}
            className="ui-button ui-button-primary text-xs flex items-center gap-1.5 disabled:opacity-60 disabled:cursor-not-allowed"
          >
            {running || starting ? (
              <>
                <span className="animate-spin text-sm">⏳</span> TARANIYOR…
              </>
            ) : (
              <>
                <span>⚡</span> TARA
              </>
            )}
          </button>
        </div>

        {/* Durum satırı */}
        <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-xs" aria-live="polite">
          {line ? (
            <span className={`font-bold ${STATUS_TONE[line.tone]}`}>
              {line.tone === "running" ? "● " : ""}{line.text}
            </span>
          ) : loadError ? null : (
            <span className="text-bunker-muted">Durum yükleniyor…</span>
          )}
          {notice && <span className="text-yellow-300">· {notice}</span>}
          {loadError && (
            <span className="text-neon-red" role="alert">⚠ {loadError}</span>
          )}
        </div>

        {running && state && state.progress.total > 0 && (
          <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-bunker-800" aria-hidden="true">
            <div
              className="h-full rounded-full bg-neon-green transition-[width] duration-500"
              style={{ width: `${Math.min(100, Math.round((state.progress.done / state.progress.total) * 100))}%` }}
            />
          </div>
        )}
      </div>

      {/* Sonuç */}
      <div className="card p-0 rounded-xl border border-bunker-800 bg-bunker-900/40 overflow-hidden">
        <div className="flex items-center justify-between px-4 pt-4 pb-2">
          <p className="eyebrow text-bunker-muted">EN İYİ {N7_DEFAULT_TOP}</p>
          {result && (
            <span className="font-mono text-[10px] text-bunker-muted uppercase tracking-wide">
              {result.rule ?? "m1h"}{result.source ? ` · ${result.source}` : ""}
            </span>
          )}
        </div>

        {picks.length === 0 ? (
          <p className="px-4 pb-6 pt-2 text-center font-mono text-sm text-bunker-muted">
            {running ? "Tarama sürüyor — sonuç bitince burada görünür." : "Henüz sonuç yok. TARA ile ilk taramayı başlat."}
          </p>
        ) : (
          <div className="table-scroll">
            <table className="w-full min-w-[760px] text-xs">
              <thead className="text-[10px] uppercase tracking-wider text-bunker-muted border-y border-bunker-800 bg-bunker-900/60">
                <tr>
                  <th className={`${TH} w-10`}>#</th>
                  <th className={TH}>Sembol</th>
                  <th className={`${TH} text-right`}>Giriş</th>
                  <th className={`${TH} text-right`}>Skor</th>
                  <th className={`${TH} text-right`}>1 sa / 4 sa</th>
                  <th className={`${TH} text-right`}>Hacim</th>
                  <th className={`${TH} text-right`}>VWAP</th>
                  <th className={`${TH} text-right`}>Tepeye yol</th>
                  <th className={`${TH} text-right`}>Taban +2%/1sa</th>
                  <th className={`${TH} text-right`}>ATR 15m</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-bunker-800/70">
                {picks.map((p, i) => {
                  const rank = i + 1;
                  return (
                    <tr key={p.sym} className="hover:bg-bunker-900/70 transition-colors">
                      <td className={TD}>
                        <span className={`inline-flex h-6 w-6 items-center justify-center rounded-full border text-[11px] font-black ${RANK_CLS[rank] ?? "border-bunker-700 text-bunker-muted"}`}>
                          {rank}
                        </span>
                      </td>
                      <td className={TD}>
                        <Link
                          href={`/charts?symbol=${encodeURIComponent(p.sym)}`}
                          className="inline-flex items-baseline gap-1 hover:text-neon-green"
                          title={`${p.sym} grafiğini aç`}
                        >
                          <span className="text-sm font-black text-white">{stripTry(p.sym)}</span>
                          <span className="text-[10px] text-bunker-muted">/ TRY</span>
                        </Link>
                      </td>
                      <td className={`${TD} text-right text-white`}>{formatPrice(p.px)}</td>
                      <td className={`${TD} text-right text-sm font-black text-white`}>{fmtScore(p.score)}</td>
                      <td className={`${TD} text-right`}>
                        <span className={pctTone(p.r1)}>{fmtSignedPct(p.r1)}</span>
                        <span className="text-bunker-muted"> / </span>
                        <span className={pctTone(p.r4)}>{fmtSignedPct(p.r4)}</span>
                      </td>
                      <td className={`${TD} text-right text-white`}>{fmtRatioX(p.vr)}</td>
                      <td className={`${TD} text-right ${pctTone(p.vwap_rel)}`}>{fmtSignedPct(p.vwap_rel)}</td>
                      <td className={`${TD} text-right text-white`}>{fmtPct(p.room)}</td>
                      <td className={`${TD} text-right text-white`}>{fmtPct(p.base)}</td>
                      <td className={`${TD} text-right text-bunker-muted`}>{fmtPct(p.atr15, 2)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        <div className="px-4 pb-4 pt-3 space-y-1 border-t border-bunker-800/70">
          {result && (
            <p className="font-mono text-[11px] text-bunker-muted">{summaryLine(result, fmtClock)}</p>
          )}
          <p className="text-[11px] leading-relaxed text-bunker-muted">{N7_METHOD_NOTE}</p>
        </div>
      </div>
    </section>
  );
}
