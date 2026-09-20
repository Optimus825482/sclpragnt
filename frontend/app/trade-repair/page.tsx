"use client";

import { useCallback, useEffect, useState } from "react";
import { API_BASE, apiRequest } from "../lib/api";
import { toMs } from "../lib/format";
import SymbolLink from "../components/SymbolLink";
import { useVisibleInterval } from "../lib/useVisibleInterval";

export default function TradeRepairPage() {
  const [data, setData] = useState<any>(null);
  const [legacy, setLegacy] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    return apiRequest(`${API_BASE}/api/trade-repair/status`, { cache: "no-store" })
      .then((r) => r.json())
      .then(setData)
      .catch(() => undefined);
  }, []);

  const loadLegacy = useCallback(() => {
    return apiRequest(`${API_BASE}/api/trade-repair/legacy-cleanup`, { cache: "no-store" })
      .then((r) => r.json())
      .then((x) => setLegacy(x.records || []))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    load();
    loadLegacy();
  }, [load, loadLegacy]);

  // Çalışma esnasında 1.5s, beklemede 6s görünürlük-farkında yoklama
  const isRunning = busy || (data?.status && data.status !== "idle" && data.status !== "completed");
  useVisibleInterval(load, isRunning ? 1500 : 6000);

  const preview = async () => {
    setBusy(true);
    try {
      await apiRequest(`${API_BASE}/api/trade-repair/preview`, { method: "POST" });
      await load();
    } finally {
      setBusy(false);
    }
  };

  const apply = async () => {
    const count = data?.preview?.actions?.assign_trade_ids ?? 0;
    if (!window.confirm(`Onaylı geçmiş veri onarımı başlatılacak. ${count} bağlantı kimliği düzeltilecek. Hiçbir kayıt silinmeyecek. Devam edilsin mi?`)) return;
    setBusy(true);
    try {
      await apiRequest(`${API_BASE}/api/trade-repair/apply`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirm: true }),
      });
      await load();
    } finally {
      setBusy(false);
    }
  };

  const purgeLegacy = async () => {
    if (!legacy.length || !window.confirm(`Şu kayıtlar kalıcı olarak silinecek: ${legacy.map(x => `${x.trade_id} (${x.symbol})`).join(", ")}. İlgili kapanış sinyal/karar ve embedding kayıtları da temizlenecek. Devam edilsin mi?`)) return;
    setBusy(true);
    try {
      await apiRequest(`${API_BASE}/api/trade-repair/legacy-cleanup`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirm: true, trade_ids: legacy.map(x => x.trade_id) }),
      });
      setLegacy([]);
      await load();
    } finally {
      setBusy(false);
    }
  };

  const p = data?.preview;

  return (
    <main className="page-shell space-y-5">
      <header className="page-heading flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="eyebrow text-neon-green">GEÇMİŞ VERİ ONARIMI</p>
          <h1 className="font-mono text-2xl font-bold text-white">Trade Repair Monitor</h1>
          <p className="mt-1 text-sm text-bunker-muted">Açılış, kapanış ve karar kayıtlarını silmeden denetleyin ve onayla düzeltin.</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => { load(); loadLegacy(); }}
            className="ui-button ui-button-secondary touch-target"
          >
            🔄 Yenile
          </button>
        </div>
      </header>

      <div className="card border-yellow-400/20 bg-yellow-400/5 text-sm p-4">
        <p className="font-mono text-xs font-bold text-yellow-300">GÜVENLİK SINIRI</p>
        <p className="mt-1 text-xs text-bunker-200">
          Önizleme salt-okunurdur. Uygulama yalnızca eksik trade_id alanlarını doldurur ve kesin eşleşen kapanış kararlarına strateji ekler. Kayıt silmez, PnL veya cüzdan değerini değiştirmez.
        </p>
      </div>

      <div className="flex flex-wrap gap-3">
        <button onClick={preview} disabled={busy} className="ui-button ui-button-secondary">
          {busy ? "İŞLENİYOR…" : "ÖNİZLEMEYİ ÇALIŞTIR"}
        </button>
        <button onClick={apply} disabled={busy || !p?.requires_confirmation} className="ui-button ui-button-primary">
          ONAYLA VE ONAR
        </button>
      </div>

      {legacy.length > 0 && (
        <div className="card border-neon-red/30 bg-neon-red/5 p-4">
          <p className="eyebrow text-neon-red">MİGRASYON KAYNAKLI LEGACY KAYITLAR</p>
          <div className="mt-3 space-y-1 font-mono text-xs max-h-48 overflow-y-auto">
            {legacy.map((x) => (
              <div key={x.trade_id} className="flex items-center gap-2 py-1 border-b border-bunker-800/40">
                <span className="text-bunker-muted">{x.trade_id}</span>
                <span>·</span>
                <SymbolLink symbol={x.symbol} className="font-bold text-white hover:text-neon-green" />
                <span>·</span>
                <span className="text-bunker-300">PnL {x.pnl == null ? "—" : `₺${Number(x.pnl).toFixed(2)}`}</span>
              </div>
            ))}
          </div>
          <button onClick={purgeLegacy} disabled={busy} className="ui-button mt-4 border-neon-red/50 text-neon-red hover:bg-neon-red/10">
            ONAYLA VE LEGACY KAYITLARINI SİL
          </button>
        </div>
      )}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {[
          ["Durum", data?.status || "idle"],
          ["Aşama", data?.phase || "—"],
          ["İlerleme", `${data?.progress ?? 0}%`],
          ["Kimlik Adayı", String(p?.actions?.assign_trade_ids ?? 0)],
        ].map(([k, v]) => (
          <div className="card p-4" key={k}>
            <p className="eyebrow">{k}</p>
            <p className="font-mono text-xl mt-2 font-bold text-white">{v}</p>
          </div>
        ))}
      </div>

      {p && (
        <div className="card p-5 space-y-3">
          <p className="eyebrow text-neon-green">ÖNİZLEME SONUCU</p>
          <div className="grid sm:grid-cols-3 gap-3 font-mono text-xs">
            <div className="rounded border border-bunker-800 bg-bunker-900/50 p-3">
              <span className="text-bunker-muted block text-[10px]">Eksik trade_id</span>
              <span className="text-base font-bold text-white">{p.missing_trade_ids?.length ?? 0}</span>
            </div>
            <div className="rounded border border-bunker-800 bg-bunker-900/50 p-3">
              <span className="text-bunker-muted block text-[10px]">Eksik pozisyon id</span>
              <span className="text-base font-bold text-white">{p.missing_position_ids?.length ?? 0}</span>
            </div>
            <div className="rounded border border-bunker-800 bg-bunker-900/50 p-3">
              <span className="text-bunker-muted block text-[10px]">Eşleşmeyen kapanış</span>
              <span className="text-base font-bold text-white">{p.unmatched_close_logs?.length ?? 0}</span>
            </div>
          </div>
          {p.unmatched_close_logs?.length > 0 && (
            <p className="text-yellow-300 text-xs mt-2">
              Eşleşmeyen kapanışlar yalnızca raporlandı; otomatik silinmeyecek.
            </p>
          )}
        </div>
      )}

      <div className="card p-5">
        <p className="eyebrow mb-3 text-neon-green">CANLI ONARIM LOGU</p>
        <div className="max-h-80 overflow-auto space-y-1.5 font-mono text-xs rounded border border-bunker-800 bg-bunker-950/60 p-3">
          {(data?.logs || []).map((l: any, i: number) => (
            <div key={i} className="border-b border-bunker-800/40 pb-1.5 last:border-b-0">
              <span className="text-bunker-muted">{new Date(toMs(l.time)).toLocaleTimeString("tr-TR")}</span>{" "}
              <span className={l.level === "error" ? "text-neon-red font-bold" : l.level === "warning" ? "text-yellow-300 font-bold" : "text-neon-green font-bold"}>
                [{l.level}]
              </span>{" "}
              <span className="text-bunker-200">{l.message}</span>
            </div>
          ))}
          {!data?.logs?.length && (
            <span className="text-bunker-muted text-xs">Henüz log yok. Önizleme ile başlayın.</span>
          )}
        </div>
      </div>
    </main>
  );
}
