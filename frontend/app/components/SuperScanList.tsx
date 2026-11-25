"use client";

/**
 * Radar > "Süper Tarama" sekmesi (2026-11-25, kullanıcı isteği).
 *
 * TÜM tarama algoritmaları (hız avcısı, günlük momentum, short-squeeze, snapback,
 * erken keşif, yükseliş eğilimi, MACD MTF) tek listede: teyit eden kaynak aileleri
 * ve CMC bağlamıyla ağırlıklandırılmış tek skor.
 *
 * Sekme açıkken 30 saniyede bir tazelenir; arka planda durur.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { API_BASE, apiRequest } from "../lib/api";
import { useVisibleInterval } from "../lib/useVisibleInterval";
import SymbolLink from "./SymbolLink";

type SuperScanDiag = { rows?: number; blocked?: number; below_score?: number; below_atr?: number;
  thin_volume?: number; missing_volume?: number; duplicate_symbol?: number;
  by_source?: Record<string, number>; elapsed_ms?: number };
type SuperScanPayload = { items?: SuperRow[]; scanned?: number; eligible?: number; generated_at?: number;
  pending?: boolean; detail?: string; diagnostics?: SuperScanDiag };

type SuperRow = {
  symbol: string;
  price: number | null;
  score: number;
  super_score: number;
  source_bonus?: number;
  cmc_bonus?: number;
  family_count?: number;
  sources: string[];
  source_count: number;
  confluence: boolean;
  atr_pct_15m: number | null;
  target_pct: number | null;
  horizon_minutes: number | null;
  cmc_flags: string[];
  tags: string[];
  paper_block_reason?: "trend_conflict" | null;
  paper_candidate?: { horizon_minutes: number | null };
};

const REFRESH_MS = 30_000;
const PENDING_REFRESH_MS = 15_000;

function fmtPrice(value: number | null): string {
  if (value == null || !Number.isFinite(value)) return "—";
  if (value >= 1000) return value.toLocaleString("tr-TR", { maximumFractionDigits: 2 });
  if (value >= 1) return value.toLocaleString("tr-TR", { maximumFractionDigits: 4 });
  return value.toLocaleString("tr-TR", { maximumFractionDigits: 8 });
}

export default function SuperScanList() {
  const [rows, setRows] = useState<SuperRow[] | null>(null);
  const [meta, setMeta] = useState<{ scanned?: number; eligible?: number; generated_at?: number; diag?: SuperScanDiag }>({});
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const inFlight = useRef(false);

  const load = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      // 2026-11-25: tarama soğukken uzun sürebiliyor → 60 sn tanınır; backend
      // 20 sn'de yanıt veremezse `pending` döner ve arka planda ısıtır.
      const r = await apiRequest(`${API_BASE}/api/radar/super-scan?limit=12`, { cache: "no-store", timeoutMs: 60_000 });
      const d: SuperScanPayload | null = await r.json().catch(() => null);
      if (!r.ok) throw new Error(typeof d?.detail === "string" ? d.detail : "Tarama alınamadı");
      if (d?.pending === true) {
        setPending(true);
        setError(null);
        return;
      }
      if (!Array.isArray(d?.items)) throw new Error("Tarama yanıtı okunamadı");
      setRows(d.items);
      setMeta({ scanned: d.scanned, eligible: d.eligible, generated_at: d.generated_at, diag: d.diagnostics });
      setPending(false);
      setError(null);
    } catch (err) {
      setPending(false);
      setError(err instanceof Error ? err.message : "Tarama alınamadı");
    } finally {
      inFlight.current = false;
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);
  useVisibleInterval(load, pending ? PENDING_REFRESH_MS : REFRESH_MS);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-bunker-muted">
          {rows === null ? "Tüm tarayıcılar tek listede" : <>
            Son tarama · {meta.scanned ?? "…"} aday tarandı, {meta.eligible ?? "…"} uygun
            {meta.generated_at ? ` · ${new Date(meta.generated_at * 1000).toLocaleTimeString("tr-TR")}` : ""}
          </>}
        </p>
        <button type="button" onClick={load} className="ui-button ui-button-secondary">
          YENİLE
        </button>
      </div>

      {/* ROZET SÖZLÜĞÜ (2026-11-25, kullanıcı): kısaltmaların anlamı üstte. */}
      <details className="rounded-lg border border-bunker-800 bg-bunker-900/40 px-3 py-2 text-[11px] text-bunker-muted">
        <summary className="cursor-pointer font-mono text-xs text-bunker-muted">Rozetler ne demek?</summary>
        <ul className="mt-2 space-y-1 leading-relaxed">
          <li><span className="font-mono text-neon-green">Süper skor</span> sıralama puanıdır. Taban puanına her ek teyit ailesi için 6 puan ve CMC katkısı eklenir. Toplam 100’ü geçebilir.</li>
          <li><span className="font-mono text-white">Taban</span> adayın 0–100 puanıdır. Otonom paper girişindeki asgari skor bu puana uygulanır.</li>
          <li><span className="font-mono text-white">Teyit ailesi</span> aynı veriye dayanan kaynakları birlikte sayar. Örneğin MACD sıçrama, erken sinyal ve MTF bir aile sayılır.</li>
          <li><span className="rounded border border-neon-green/40 bg-neon-green/10 px-1 text-neon-green">UYUŞMA</span>: Master Surge’un <b>4 katmanının tamamı</b> aynı yönde — likidite · volatilite · emir akışı · çoklu zaman dilimi trendi.</li>
          <li><span className="font-mono text-white">ATR x%</span>: 15 dakikalık ortalama hareket (oynaklık). Stop ve hedef bunun üstüne kurulur.</li>
          <li><span className="font-mono text-white">hedef %X</span>: bildirimin kâr hedefi · <span className="font-mono text-white">X dk</span>: beklenen tutma süresi.</li>
          <li><span className="font-mono text-sky-300">AI · DePIN · Meme…</span>: CMC sektör etiketleri.</li>
          <li><span className="font-mono text-amber-300">HACIM_PATLAMASI</span>: 24s hacim +%100’den fazla arttı · <span className="font-mono text-amber-300">ATH_YAKIN</span>: 180 günlük zirveye %3 içinde · <span className="font-mono text-amber-300">7G_ASIRI_ISINMA</span>: 7 günde +%40 üzeri (skordan −5) · <span className="font-mono text-amber-300">7G_SERT_DUSUS</span>: 7 günde −%25 altı · <span className="font-mono text-amber-300">DUSUK_SIRALAMA</span>: CMC sıralaması 300’ün altında.</li>
          <li>Liste sekmeyi açtığında ve sekme açıkken 30 saniyede bir tazelenir. Bildirim ve otonom işlem <b>yalnız</b> bu listeden beslenir.</li>
        </ul>
      </details>

      {error && <p className="rounded-lg bg-neon-red/10 p-3 text-sm text-neon-red">{error}</p>}
      {pending && !error && (
        <p role="status" className="py-6 text-center text-sm text-amber-300">
          Tarama hazırlanıyor… Sonuç 15 saniyede bir kontrol ediliyor.
        </p>
      )}
      {rows == null && !pending && !error && <p className="py-6 text-center text-sm text-bunker-muted">Taranıyor…</p>}
      {rows && rows.length === 0 && !pending && !error && (
        <div className="rounded-lg border border-bunker-800 bg-bunker-900/40 px-3 py-3 text-center text-xs text-bunker-muted">
          <p className="text-sm text-white">Şu an kalite kapılarını geçen aday yok.</p>
          {meta.diag && (
            <p className="mt-2 font-mono text-[11px]">
              tarandı {meta.diag.rows ?? 0}
              {" · "}engelli {meta.diag.blocked ?? 0}
              {" · "}skor altı {meta.diag.below_score ?? 0}
              {" · "}ATR altı {meta.diag.below_atr ?? 0}
              {" · "}sığ hacim {meta.diag.thin_volume ?? 0}
              {" · "}hacim verisi yok {meta.diag.missing_volume ?? 0}
              {meta.diag.elapsed_ms != null ? ` · ${meta.diag.elapsed_ms} ms` : ""}
            </p>
          )}
          {meta.diag?.by_source && Object.keys(meta.diag.by_source).length > 0 && (
            <p className="mt-1 font-mono text-[11px]">
              kaynaklar: {Object.entries(meta.diag.by_source).map(([k, v]) => `${k} ${v}`).join(" · ")}
            </p>
          )}
          <p className="mt-2">
            Aday yoksa sebep genelde piyasa sakinliği (hacim patlaması yok) veya aktif sembol sayısının azlığıdır.
          </p>
        </div>
      )}

      {rows && rows.length > 0 && (
        <ol className="divide-y divide-bunker-800 rounded-xl border border-bunker-800 overflow-hidden">
          {rows.map((row, idx) => (
            <li key={`${row.symbol}-${idx}`} className="px-3 py-2.5">
              <div className="flex items-center justify-between gap-3">
                <div className="flex min-w-0 items-center gap-3">
                  <span className="w-6 shrink-0 text-right font-mono text-xs text-bunker-muted">{idx + 1}</span>
                  <SymbolLink symbol={row.symbol} className="truncate font-semibold text-white" />
                  {row.confluence && (
                    <span className="shrink-0 rounded border border-neon-green/40 bg-neon-green/10 px-1.5 py-0.5 text-[10px] text-neon-green">
                      UYUŞMA
                    </span>
                  )}
                </div>
                <div className="flex shrink-0 items-center gap-3 font-mono text-xs">
                  <span className="text-white">{fmtPrice(row.price)}</span>
                  <span className="text-neon-green font-bold">{row.super_score}</span>
                </div>
              </div>
              <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 pl-9 font-mono text-[11px] text-bunker-muted">
                <span>Taban {row.score}</span>
                {row.source_bonus != null && <span>Teyit +{row.source_bonus}</span>}
                {row.cmc_bonus != null && <span>CMC {row.cmc_bonus > 0 ? "+" : ""}{row.cmc_bonus}</span>}
                <span>{row.family_count != null ? `${row.family_count} teyit ailesi` : `${row.source_count} kaynak`} · {(row.sources || []).join(", ") || "—"}</span>
                {row.paper_block_reason === "trend_conflict" && (
                  <span className="text-amber-300">
                    {row.paper_candidate?.horizon_minutes
                      ? `Paper için değerlendirilen diğer ufuk ${row.paper_candidate.horizon_minutes} dk`
                      : "Paper girişine kapalı · ters yönlü trend"}
                  </span>
                )}
                {row.atr_pct_15m != null && <span>ATR {row.atr_pct_15m}%</span>}
                {row.target_pct != null && <span>hedef %{row.target_pct}</span>}
                {row.horizon_minutes != null && <span>{row.horizon_minutes} dk</span>}
                {(row.tags || []).length > 0 && <span className="text-sky-300">{(row.tags || []).join(" · ")}</span>}
                {(row.cmc_flags || []).map((f) => (
                  <span key={f} className="text-amber-300">{f}</span>
                ))}
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
