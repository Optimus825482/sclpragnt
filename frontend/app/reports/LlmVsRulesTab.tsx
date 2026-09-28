"use client";

import { useCallback, useEffect, useState } from "react";
import { API_BASE, apiRequest } from "../lib/api";
import { fmtMinute as fmtDt, formatSignedTL, formatTL, withQuote } from "../lib/format";
import SymbolLink from "../components/SymbolLink";

type LlmVsRulesStats = {
  total_trades: number;
  total_closed: number;
  rules_pnl: number;
  rules_win_rate: number;
  llm_confirmed_count: number;
  llm_confirmed_pnl: number;
  llm_confirmed_win_rate: number;
  llm_traps_saved: number;
  llm_fake_total: number;
  llm_accuracy: number;
  eval_total: number;
};

type ComparisonTrade = {
  trade_id: number;
  symbol: string;
  status: string;
  entry_time: number;
  exit_time?: number | null;
  entry_price: number;
  exit_price?: number | null;
  quantity: number;
  order_value_try: number;
  pnl?: number | null;
  pnl_pct?: number | null;
  exit_reason?: string | null;
  peak_price?: number | null;
  take_profit?: number | null;
  stop_loss?: number | null;
  notification_score?: number | null;
  notification_target_pct?: number | null;
  llm_verdict?: string | null;
  llm_confidence?: number | null;
  llm_reasons?: string | null;
  llm_summary?: string | null;
  comparison_status: string;
  comparison_label: string;
};

export default function LlmVsRulesTab({ day }: { day?: string }) {
  const [data, setData] = useState<{ stats: LlmVsRulesStats; trades: ComparisonTrade[] } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<"ALL" | "DEVAM" | "FAKE" | "DIFFERENCE">("ALL");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const q = day ? `?day=${encodeURIComponent(day)}&limit=500` : "?limit=500";
      const res = await apiRequest(`${API_BASE}/api/reports/llm-vs-rules${q}`, { cache: "no-store" });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || "Karşılaştırma raporu yüklenemedi");
      setData(body);
    } catch (e: any) {
      setError(e.message || "Veri alınamadı");
    } finally {
      setLoading(false);
    }
  }, [day]);

  useEffect(() => {
    load();
  }, [load]);

  const stats = data?.stats;
  const allTrades = data?.trades || [];

  const filteredTrades = allTrades.filter((t) => {
    if (filter === "DEVAM") return t.llm_verdict === "DEVAM";
    if (filter === "FAKE") return t.llm_verdict === "FAKE";
    if (filter === "DIFFERENCE") {
      // LLM ile kuralın ayrıştığı yerler (Örn: LLM FAKE dedi ama kural işleme girdi, veya kural zarar etti ama LLM DEVAM dedi)
      return t.comparison_status === "LLM_SAVED" || t.comparison_status === "LLM_LOSS" || t.comparison_status === "LLM_MISSED";
    }
    return true;
  });

  const downloadCsv = () => {
    const q = day ? `?day=${encodeURIComponent(day)}` : "";
    window.open(`${API_BASE}/api/reports/llm-vs-rules/csv${q}`, "_blank");
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "LLM_WIN":
        return <span className="rounded-md border border-neon-green/50 bg-neon-green/15 px-2 py-0.5 font-mono text-[10px] font-bold text-neon-green">✅ Kazanç Teyitli</span>;
      case "LLM_SAVED":
        return <span className="rounded-md border border-sky-400/50 bg-sky-400/15 px-2 py-0.5 font-mono text-[10px] font-bold text-sky-300">🛡️ Zarardan Korudu</span>;
      case "LLM_MISSED":
        return <span className="rounded-md border border-yellow-400/50 bg-yellow-400/15 px-2 py-0.5 font-mono text-[10px] font-bold text-yellow-300">⚠️ Fırsat Kaçtı</span>;
      case "LLM_LOSS":
        return <span className="rounded-md border border-neon-red/50 bg-neon-red/15 px-2 py-0.5 font-mono text-[10px] font-bold text-neon-red">❌ LLM Yanıldı</span>;
      case "OPEN":
        return <span className="rounded-md border border-amber-400/40 bg-amber-400/10 px-2 py-0.5 font-mono text-[10px] font-bold text-amber-300 animate-pulse">⏳ Açık İşlem</span>;
      default:
        return <span className="rounded-md border border-bunker-700 bg-bunker-800 px-2 py-0.5 font-mono text-[10px] font-bold text-bunker-muted">⚪ Değerlendirilmedi</span>;
    }
  };

  const getVerdictBadge = (verdict?: string | null, conf?: number | null) => {
    if (!verdict) return <span className="text-bunker-muted font-mono text-xs">—</span>;
    const confStr = conf != null ? ` %${conf}` : "";
    if (verdict === "DEVAM") {
      return <span className="inline-flex items-center gap-1 font-mono text-xs font-black text-neon-green bg-neon-green/10 border border-neon-green/30 px-2 py-0.5 rounded">🧠 DEVAM{confStr}</span>;
    }
    if (verdict === "FAKE") {
      return <span className="inline-flex items-center gap-1 font-mono text-xs font-black text-neon-red bg-neon-red/10 border border-neon-red/30 px-2 py-0.5 rounded">⚠️ FAKE{confStr}</span>;
    }
    return <span className="inline-flex items-center gap-1 font-mono text-xs font-bold text-bunker-muted bg-bunker-800 border border-bunker-700 px-2 py-0.5 rounded">⚪ BELİRSİZ{confStr}</span>;
  };

  if (loading && !data) {
    return <div className="card p-12 text-center font-mono text-sm text-bunker-muted animate-pulse">🤖 Kural vs LLM karşılaştırma verileri hesaplanıyor…</div>;
  }

  if (error && !data) {
    return (
      <div className="card p-6 border-neon-red/40 bg-neon-red/10 text-center">
        <p className="font-mono text-sm text-neon-red font-bold">{error}</p>
        <button type="button" onClick={load} className="mt-3 rounded-xl bg-bunker-800 px-4 py-2 font-mono text-xs text-white hover:bg-bunker-700">Tekrar Dene</button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Üst Bilgi ve Aksiyon Çubuğu */}
      <div className="flex flex-wrap items-center justify-between gap-4 p-4 rounded-2xl border border-bunker-800 bg-bunker-950/60 shadow-lg">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-lg">🤖</span>
            <h2 className="font-mono text-lg font-black text-white">Kural Bazlı Motor vs LLM İkinci Göz Analizi</h2>
          </div>
          <p className="text-xs text-bunker-muted mt-0.5">
            Sistemin açtığı otonom işlemler ile LLM modelinin aynı sinyallere verdiği kararların (DEVAM/FAKE) paralel kârlılık kıyaslaması.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={downloadCsv}
            className="flex items-center gap-2 rounded-xl border border-neon-green/40 bg-neon-green/15 px-4 py-2 font-mono text-xs font-black text-neon-green hover:bg-neon-green/25 hover:border-neon-green transition-all shadow-sm active:scale-95"
            title="Tüm karşılaştırma verilerini Excel uyumlu CSV formatında indir"
          >
            <span>📥</span>
            <span>CSV OLARAK İNDİR</span>
          </button>
        </div>
      </div>

      {/* İstatistik Gösterge Kartları */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3.5">
        <div className="card p-4 rounded-xl border border-bunker-800 bg-bunker-900/40">
          <p className="eyebrow text-bunker-muted">KURAL BAZLI (MEVCUT)</p>
          <div className="mt-2 flex items-baseline justify-between">
            <span className={`font-mono text-2xl font-black ${(stats?.rules_pnl || 0) >= 0 ? "text-neon-green" : "text-neon-red"}`}>
              {formatSignedTL(stats?.rules_pnl)}
            </span>
            <span className="font-mono text-xs font-bold text-bunker-muted">
              %{stats?.rules_win_rate || 0} Kazanma
            </span>
          </div>
          <p className="mt-1 font-mono text-[11px] text-bunker-muted truncate">
            {stats?.total_closed || 0} kapalı işlemden
          </p>
        </div>

        <div className="card p-4 rounded-xl border border-neon-green/30 bg-neon-green/5">
          <p className="eyebrow text-neon-green">LLM ONAYLI (SADECE DEVAM)</p>
          <div className="mt-2 flex items-baseline justify-between">
            <span className={`font-mono text-2xl font-black ${(stats?.llm_confirmed_pnl || 0) >= 0 ? "text-neon-green" : "text-neon-red"}`}>
              {formatSignedTL(stats?.llm_confirmed_pnl)}
            </span>
            <span className="font-mono text-xs font-bold text-neon-green">
              %{stats?.llm_confirmed_win_rate || 0} Kazanma
            </span>
          </div>
          <p className="mt-1 font-mono text-[11px] text-bunker-muted truncate">
            {stats?.llm_confirmed_count || 0} işlem onaylandı
          </p>
        </div>

        <div className="card p-4 rounded-xl border border-sky-500/30 bg-sky-500/5">
          <p className="eyebrow text-sky-400">ÖNLENEN TUZAKLAR (FAKE)</p>
          <div className="mt-2 flex items-baseline justify-between">
            <span className="font-mono text-2xl font-black text-sky-300">
              {stats?.llm_traps_saved || 0}
            </span>
            <span className="font-mono text-xs font-bold text-sky-400">
              / {stats?.llm_fake_total || 0} Fake
            </span>
          </div>
          <p className="mt-1 font-mono text-[11px] text-bunker-muted truncate">
            Zararlı işlemleri tespit edip korudu
          </p>
        </div>

        <div className="card p-4 rounded-xl border border-amber-500/30 bg-amber-500/5">
          <p className="eyebrow text-amber-400">LLM KARAR DOĞRULUĞU</p>
          <div className="mt-2 flex items-baseline justify-between">
            <span className="font-mono text-2xl font-black text-amber-300">
              %{stats?.llm_accuracy || 0}
            </span>
            <span className="font-mono text-xs font-bold text-bunker-muted">
              {stats?.eval_total || 0} Hakemlik
            </span>
          </div>
          <p className="mt-1 font-mono text-[11px] text-bunker-muted truncate">
            (Doğru onaylar + engellenen zararlar)
          </p>
        </div>
      </div>

      {/* Tablo Filtreleme Butonları */}
      <div className="flex flex-wrap items-center gap-2 border-b border-bunker-800 pb-3">
        <span className="text-xs font-mono text-bunker-muted mr-1">Filtre:</span>
        <button
          type="button"
          onClick={() => setFilter("ALL")}
          className={`rounded-xl px-3 py-1.5 font-mono text-xs font-bold transition-all ${
            filter === "ALL"
              ? "bg-bunker-800 text-white border border-bunker-600 shadow-sm"
              : "text-bunker-muted hover:text-white bg-bunker-950 border border-bunker-900"
          }`}
        >
          Tüm İşlemler ({allTrades.length})
        </button>
        <button
          type="button"
          onClick={() => setFilter("DEVAM")}
          className={`rounded-xl px-3 py-1.5 font-mono text-xs font-bold transition-all ${
            filter === "DEVAM"
              ? "bg-neon-green/20 text-neon-green border border-neon-green/40 shadow-sm"
              : "text-bunker-muted hover:text-white bg-bunker-950 border border-bunker-900"
          }`}
        >
          🧠 Sadece LLM Onaylılar (DEVAM)
        </button>
        <button
          type="button"
          onClick={() => setFilter("FAKE")}
          className={`rounded-xl px-3 py-1.5 font-mono text-xs font-bold transition-all ${
            filter === "FAKE"
              ? "bg-neon-red/20 text-neon-red border border-neon-red/40 shadow-sm"
              : "text-bunker-muted hover:text-white bg-bunker-950 border border-bunker-900"
          }`}
        >
          ⚠️ Sadece Fake / Tuzak Uyarısı
        </button>
        <button
          type="button"
          onClick={() => setFilter("DIFFERENCE")}
          className={`rounded-xl px-3 py-1.5 font-mono text-xs font-bold transition-all ${
            filter === "DIFFERENCE"
              ? "bg-sky-500/20 text-sky-300 border border-sky-500/40 shadow-sm"
              : "text-bunker-muted hover:text-white bg-bunker-950 border border-bunker-900"
          }`}
        >
          ⚡ Ayrışmalar &amp; Korunan Zararlar
        </button>
      </div>

      {/* Karşılaştırma Tablosu */}
      <section className="card p-4 rounded-xl border border-bunker-800 bg-bunker-950/40">
        <div className="table-scroll max-h-[500px]">
          <table className="data-table table-compact w-full">
            <thead>
              <tr>
                <th>Zaman</th>
                <th>Sembol</th>
                <th>Kural Giriş / Çıkış</th>
                <th>Kural PnL</th>
                <th>Kural Çıkış Nedeni</th>
                <th>LLM Kararı</th>
                <th>Karşılaştırma Sonucu</th>
                <th>LLM Gerekçesi</th>
              </tr>
            </thead>
            <tbody>
              {filteredTrades.length === 0 ? (
                <tr>
                  <td colSpan={8} className="text-center py-8 text-bunker-muted font-mono text-xs">
                    Seçilen filtreye uygun işlem kaydı bulunamadı.
                  </td>
                </tr>
              ) : (
                filteredTrades.map((t) => {
                  const pnl = Number(t.pnl || 0);
                  const pnlPct = Number(t.pnl_pct || 0);
                  return (
                    <tr key={t.trade_id} className="hover:bg-bunker-900/40 transition-colors">
                      <td className="font-mono text-xs text-bunker-muted whitespace-nowrap">
                        {fmtDt(t.entry_time)}
                      </td>
                      <td>
                        <SymbolLink symbol={t.symbol} className="font-mono font-bold text-white hover:text-neon-green" />
                      </td>
                      <td className="font-mono text-xs text-bunker-muted">
                        <div>{withQuote(t.entry_price)}</div>
                        {t.exit_price ? <div className="text-[11px] text-white">Çıkış: {withQuote(t.exit_price)}</div> : null}
                      </td>
                      <td className="font-mono text-xs font-bold">
                        {t.status === "closed" ? (
                          <div>
                            <span className={pnl >= 0 ? "text-neon-green" : "text-neon-red"}>
                              {formatSignedTL(pnl)}
                            </span>
                            <span className={`ml-1 text-[11px] ${pnlPct >= 0 ? "text-neon-green" : "text-neon-red"}`}>
                              ({pnlPct >= 0 ? "+" : ""}{pnlPct.toFixed(2)}%)
                            </span>
                          </div>
                        ) : (
                          <span className="text-amber-300">Açık</span>
                        )}
                      </td>
                      <td className="font-mono text-xs text-bunker-muted">
                        <span className="rounded bg-bunker-900 px-1.5 py-0.5 text-[11px]">
                          {t.exit_reason || (t.status === "open" ? "Pozisyonda" : "—")}
                        </span>
                      </td>
                      <td>
                        {getVerdictBadge(t.llm_verdict, t.llm_confidence)}
                      </td>
                      <td>
                        {getStatusBadge(t.comparison_status)}
                      </td>
                      <td className="font-mono text-xs text-bunker-muted max-w-xs truncate" title={t.llm_summary || t.llm_reasons || ""}>
                        {t.llm_summary || t.llm_reasons || "—"}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
