"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "../lib/api";
import { formatTL } from "../lib/format";
import { useVisibleInterval } from "../lib/useVisibleInterval";

// H-25: kâr yeşil, zarar kırmızı, bilinmeyen/başabaş nötr (0'ı yeşile boyamak
// yasak — proje kuralı: veri yok = nötr).
const tone = (v: unknown) => {
  if (v == null || v === "") return "text-bunker-muted";
  const n = Number(v);
  if (!Number.isFinite(n)) return "text-bunker-muted";
  return n > 0 ? "text-neon-green" : n < 0 ? "text-neon-red" : "text-bunker-muted";
};

export default function RiskPage() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    return apiFetch("/api/risk/summary")
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch(() => {
        setError("Risk özeti verisi alınamadı. Bağlantıyı kontrol edin.");
      })
      .finally(() => {
        setLoading(false);
      });
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // 15 sn'de bir görünürlük-farkında güncelle
  useVisibleInterval(load, 15_000);

  // H-31: `risk_flags` null ise sayfa çökmesin; PnL alanları da NaN basabiliyordu.
  const flags = data?.risk_flags || {};

  const cards: Array<[string, string, string, string?]> = [
    ["AÇIK POZİSYON", `${data?.open_positions ?? "—"} / ${data?.max_positions ?? "—"}`, "", "Mevcut / Maksimum Limit"],
    ["GERÇEKLEŞMİŞ PnL", formatTL(data?.realized_pnl), tone(data?.realized_pnl), "Toplam realize kar/zarar"],
    ["BUGÜNKÜ PnL", formatTL(data?.today_pnl), tone(data?.today_pnl), "Günün kümülatif net PnL"],
    ["KOMİSYON", formatTL(data?.commission), "", "Tahmini toplam maliyet"],
    ["ARDIŞIK ZARAR", String(data?.consecutive_losses ?? "—"), data?.consecutive_losses > 2 ? "text-yellow-300 font-bold" : "", "Son ardışık kayıp serisi"],
  ];

  return (
    <main className="page-shell space-y-6">
      <div className="page-heading flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="eyebrow text-neon-green">RİSK & SERMAYE KORUMA</p>
          <h1 className="font-mono text-2xl font-bold text-white">Risk ve Pozisyon Özeti</h1>
          <p className="mt-1 text-sm text-bunker-muted">Paper-trading kayıtlarından hesaplanan görünürlük ve güvenlik paneli.</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => { setLoading(true); load(); }}
            className="ui-button ui-button-secondary touch-target"
            disabled={loading}
          >
            {loading ? "YÜKLENİYOR…" : "🔄 Yenile"}
          </button>
        </div>
      </div>

      {error && (
        <div role="alert" className="card border-neon-red/40 bg-neon-red/5 p-4 text-neon-red font-mono text-sm flex items-center justify-between gap-3">
          <span>⚠ {error}</span>
          <button
            type="button"
            onClick={load}
            className="rounded border border-neon-red/40 px-2 py-1 text-xs hover:bg-neon-red/10"
          >
            YENİDEN DENE
          </button>
        </div>
      )}

      {/* Metrik kartları */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        {cards.map(([a, b, t, hint]) => (
          <div className="card p-4 flex flex-col justify-between" key={a}>
            <div>
              <p className="eyebrow">{a}</p>
              <p className={`text-xl font-mono font-bold mt-2 ${t || "text-white"}`}>{loading && !data ? "…" : b}</p>
            </div>
            {hint && <p className="mt-2 text-[10px] text-bunker-muted">{hint}</p>}
          </div>
        ))}
      </div>

      {/* Risk Uyarıları & Eşik Durumu */}
      <div className="card p-5 space-y-4">
        <div className="flex items-center justify-between border-b border-bunker-800 pb-3">
          <h2 className="font-mono text-base font-bold text-white flex items-center gap-2">
            <span>🛡️</span> Risk Kontrol Kapıları
          </h2>
          <span className="font-mono text-[10px] text-bunker-muted">Otonom & manuel scalp koruması</span>
        </div>

        <div className="grid sm:grid-cols-2 gap-3">
          <div className={`rounded-lg border p-4 transition-colors ${
            flags.consecutive_loss_streak
              ? "border-neon-red/50 bg-neon-red/10"
              : "border-bunker-800 bg-bunker-900/40"
          }`}>
            <div className="flex items-center justify-between">
              <span className="font-mono text-xs font-bold text-white">Ardışık Zarar Eşiği</span>
              <span className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold ${
                flags.consecutive_loss_streak
                  ? "bg-neon-red/20 text-neon-red"
                  : "bg-neon-green/10 text-neon-green"
              }`}>
                {flags.consecutive_loss_streak ? "UYARI: EŞİK AŞILDI" : "NORMAL"}
              </span>
            </div>
            <p className="mt-2 text-xs text-bunker-300">
              {flags.consecutive_loss_streak
                ? "Ardışık zarar serisi eşiğe ulaştı: yeni otonom girişler için dikkatli olunması gerekir."
                : "Ardışık zarar serisi limit altında. Sistem normal parametrelerle çalışmaya devam ediyor."}
            </p>
          </div>

          <div className={`rounded-lg border p-4 transition-colors ${
            flags.daily_loss
              ? "border-amber-400/50 bg-amber-400/10"
              : "border-bunker-800 bg-bunker-900/40"
          }`}>
            <div className="flex items-center justify-between">
              <span className="font-mono text-xs font-bold text-white">Günlük Kayıp Durumu</span>
              <span className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold ${
                flags.daily_loss
                  ? "bg-amber-400/20 text-amber-300"
                  : "bg-neon-green/10 text-neon-green"
              }`}>
                {flags.daily_loss ? "NEGATİF GÜN" : "POZİTİF / NÖTR"}
              </span>
            </div>
            <p className="mt-2 text-xs text-bunker-300">
              {flags.daily_loss
                ? "Bugünkü kümülatif PnL negatif bölgede. Günlük stop limiti risk koruması devrededir."
                : "Bugünkü işlemler kârlı veya nötr bölgede seyrediyor."}
            </p>
          </div>
        </div>
      </div>
    </main>
  );
}
