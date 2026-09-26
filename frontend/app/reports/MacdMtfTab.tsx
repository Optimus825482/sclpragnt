"use client";

import { useCallback, useEffect, useState } from "react";
import { API_BASE, apiRequest } from "../lib/api";
import { fmtDateTime } from "../lib/format";
import SymbolLink from "../components/SymbolLink";

/** MACD MTF konfluans grup satırı — backend /api/reports/macd-mtf `groups`. */
type MtfGroup = {
  verdict: string;          // GÜÇLÜ | ORTA | ZAYIF | YOK
  count: number;
  measured: number;
  touched: number;
  stopped: number;
  expired: number;
  touch_rate_pct: number | null;
  avg_mfe_pct: number | null;
  avg_mae_pct: number | null;
  fake_rate_pct: number | null;
};

type MtfRecentRow = {
  id: number;
  symbol: string;
  macd_mtf_verdict: string | null;
  macd_mtf_confluence: number | null;
  outcome_status: string | null;   // HEDEFE_ULTI | STOP | SURE_DOLDU | null
  mfe_pct: number | null;
  mae_pct: number | null;
  score: number | null;
  target_pct: number | null;
  detected_at: number | null;
  mode: string | null;
};

type MtfReport = {
  paper_only: boolean;
  days: number;
  total: number;
  fake_threshold_pct: number;
  groups: MtfGroup[];
  recent: MtfRecentRow[];
};

const verdictTone = (verdict: string): string => {
  if (verdict === "GÜÇLÜ") return "text-neon-green";
  if (verdict === "ORTA") return "text-yellow-300";
  if (verdict === "ZAYIF") return "text-bunker-muted";
  return "text-bunker-muted";
};

const outcomeLabel = (status: string | null): { label: string; cls: string } => {
  if (status === "HEDEFE_ULTI") return { label: "HEDEFE ULAŞTI", cls: "text-neon-green" };
  if (status === "STOP") return { label: "STOP", cls: "text-neon-red" };
  if (status === "SURE_DOLDU") return { label: "SÜRE DOLDU", cls: "text-bunker-muted" };
  return { label: "ÖLÇÜLMEDİ", cls: "text-bunker-muted" };
};

const pct = (v: number | null | undefined, digits = 2): string =>
  v == null ? "—" : `${v >= 0 ? "+" : ""}${Number(v).toFixed(digits)}%`;

export default function MacdMtfTab() {
  const [days, setDays] = useState(14);
  const [report, setReport] = useState<MtfReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async (d: number) => {
    setLoading(true);
    setError("");
    try {
      const res = await apiRequest(`${API_BASE}/api/reports/macd-mtf?days=${d}`, { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setReport(await res.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Rapor yüklenemedi");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(days);
  }, [load, days]);

  return (
    <div className="space-y-4">
      {/* Açıklama + karar kuralı */}
      <section className="card rounded-2xl border border-bunker-800 bg-bunker-950/60 p-4 space-y-2">
        <h2 className="font-mono text-base font-black text-white">🧠 MACD MTF Konfluans Ölçümü</h2>
        <p className="text-xs text-bunker-muted">
          Sinyalin <b className="text-white">ateşlendiği andaki</b> M1/M3/M5/M15 MACD-Signal konfluansı
          (GÜÇLÜ/ORTA/ZAYIF) ile pencere sonundaki gerçek sonucu karşılaştırır. Amaç: kullanıcının
          &quot;kesişim + paralel yukarı&quot; metodunun eşiklere bağlanıp bağlanmayacağına kanıt üretmek.
        </p>
        <p className="rounded-lg border border-yellow-400/30 bg-yellow-400/5 px-3 py-2 text-xs text-yellow-200">
          ⚖️ <b>Karar kuralı (veri görülmeden önce sabitlendi):</b> GÜÇLÜ grubun hedefe dokunma oranı
          ZAYIF&apos;tan en az <b>+10 puan</b> yüksek VE grup başına <b>≥30 ölçülmüş</b> olay varsa konfluans
          eşiklere girer (warm terfisi / fake kapısı); aksi halde yalnız bilgi rozeti olarak kalır.
        </p>
      </section>

      {/* Dönem seçici */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-mono text-bunker-muted">Dönem:</span>
        {[7, 14, 30].map((d) => (
          <button
            key={d}
            type="button"
            onClick={() => setDays(d)}
            className={`rounded-lg px-3 py-1.5 font-mono text-xs font-bold transition-all ${
              days === d ? "bg-neon-green/15 text-neon-green border border-neon-green/40" : "text-bunker-muted hover:text-white border border-bunker-800"
            }`}
          >
            {d} gün
          </button>
        ))}
        <button
          type="button"
          onClick={() => void load(days)}
          className="rounded-lg border border-bunker-700 px-3 py-1.5 font-mono text-xs text-bunker-muted hover:text-white"
        >
          ↻ YENİLE
        </button>
        {report && (
          <span className="ml-auto text-xs font-mono text-bunker-muted">
            {report.total} bildirim · fake eşiği {report.fake_threshold_pct}%
          </span>
        )}
      </div>

      {loading && <p className="py-6 text-center font-mono text-sm text-bunker-muted">Rapor yükleniyor…</p>}
      {error && <p className="py-4 font-mono text-sm text-neon-red">⚠ {error}</p>}

      {report && !loading && !error && (
        <>
          {/* Grup karşılaştırma tablosu */}
          <section className="card rounded-2xl border border-bunker-800 bg-bunker-950/60 p-4">
            <div className="table-scroll max-h-[360px]">
              <table className="data-table table-compact">
                <thead>
                  <tr>
                    <th className="text-left">Konfluans</th>
                    <th className="text-right">Sinyal</th>
                    <th className="text-right">Ölçülen</th>
                    <th className="text-right">Dokunma %</th>
                    <th className="text-right">Ort. MFE</th>
                    <th className="text-right">Ort. MAE</th>
                    <th className="text-right">Fake %</th>
                  </tr>
                </thead>
                <tbody>
                  {report.groups.length === 0 ? (
                    <tr>
                      <td colSpan={7} className="py-6 text-center font-mono text-xs text-bunker-muted">
                        Bu dönemde konfluans snapshot&apos;lı bildirim yok — veri birikiyor.
                      </td>
                    </tr>
                  ) : (
                    report.groups.map((g) => (
                      <tr key={g.verdict}>
                        <td className={`font-mono text-xs font-black ${verdictTone(g.verdict)}`}>{g.verdict}</td>
                        <td className="text-right tabular-nums font-mono text-xs text-white">{g.count}</td>
                        <td className="text-right tabular-nums font-mono text-xs text-white">{g.measured}</td>
                        <td className={`text-right tabular-nums font-mono text-xs font-bold ${g.touch_rate_pct != null ? "text-neon-green" : "text-bunker-muted"}`}>
                          {g.touch_rate_pct == null ? "—" : `%${g.touch_rate_pct.toFixed(1)}`}
                        </td>
                        <td className={`text-right tabular-nums font-mono text-xs ${g.avg_mfe_pct != null ? "text-white" : "text-bunker-muted"}`}>
                          {pct(g.avg_mfe_pct)}
                        </td>
                        <td className={`text-right tabular-nums font-mono text-xs ${g.avg_mae_pct != null && g.avg_mae_pct < 0 ? "text-neon-red" : "text-white"}`}>
                          {pct(g.avg_mae_pct)}
                        </td>
                        <td className="text-right tabular-nums font-mono text-xs text-bunker-muted">
                          {g.fake_rate_pct == null ? "—" : `%${g.fake_rate_pct.toFixed(1)}`}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
            <p className="mt-2 text-[11px] text-bunker-muted">
              Ölçülen = sonuç penceresi (ufuk + tolerans) dolmuş sinyaller. Fake % = pencere içinde
              giriş fiyatının fake eşiğinin altına düştüğü sinyallerin oranı.
            </p>
          </section>

          {/* Son sinyaller */}
          <section className="card rounded-2xl border border-bunker-800 bg-bunker-950/60 p-4">
            <h3 className="mb-3 font-mono text-sm font-black text-white">Son Sinyaller (en yeni 30)</h3>
            <div className="table-scroll max-h-[420px]">
              <table className="data-table table-compact">
                <thead>
                  <tr>
                    <th className="text-left">Sembol</th>
                    <th className="text-left">MTF</th>
                    <th className="text-right">Skor</th>
                    <th className="text-right">Hedef</th>
                    <th className="text-left">Sonuç</th>
                    <th className="text-right">MFE</th>
                    <th className="text-right">MAE</th>
                    <th className="text-right">Zaman</th>
                  </tr>
                </thead>
                <tbody>
                  {report.recent.map((r) => {
                    const outcome = outcomeLabel(r.outcome_status);
                    return (
                      <tr key={r.id}>
                        <td className="font-mono text-xs font-bold text-white"><SymbolLink symbol={r.symbol} /></td>
                        <td className={`font-mono text-xs font-bold ${verdictTone(r.macd_mtf_verdict || "YOK")}`}>
                          {r.macd_mtf_verdict ?? "—"}
                          {r.macd_mtf_confluence != null ? ` ${Math.round(r.macd_mtf_confluence)}` : ""}
                        </td>
                        <td className="text-right tabular-nums font-mono text-xs text-bunker-muted">
                          {r.score == null ? "—" : Number(r.score).toFixed(1)}
                        </td>
                        <td className="text-right tabular-nums font-mono text-xs text-bunker-muted">
                          {r.target_pct == null ? "—" : `+%${Number(r.target_pct).toFixed(1)}`}
                        </td>
                        <td className={`font-mono text-xs font-bold ${outcome.cls}`}>{outcome.label}</td>
                        <td className="text-right tabular-nums font-mono text-xs text-white">{pct(r.mfe_pct)}</td>
                        <td className={`text-right tabular-nums font-mono text-xs ${r.mae_pct != null && r.mae_pct < 0 ? "text-neon-red" : "text-bunker-muted"}`}>
                          {pct(r.mae_pct)}
                        </td>
                        <td className="text-right font-mono text-[11px] text-bunker-muted">
                          {r.detected_at ? fmtDateTime(r.detected_at) : "—"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  );
}
