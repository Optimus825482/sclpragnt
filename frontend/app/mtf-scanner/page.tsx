"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { API_BASE, apiRequest } from "../lib/api";
import { formatPrice, QUOTE_SYMBOL } from "../lib/format";


type TfCell = {
  tf: string;
  macd: number;
  signal: number;
  hist: number;
  green: boolean;
  cross_age_bars: number;
  macd_slope_pct: number;
  signal_slope_pct: number;
  parallel_up: boolean;
  expanding?: boolean;
  fresh_bull_cross: boolean;
  hist_turn_up?: boolean;
  hist_trough?: boolean;
  squeeze?: boolean;
  zl_green?: boolean;
  zl_fresh_cross?: boolean;
  wt_bullish?: boolean;
  wt_oversold_cross?: boolean;
};

type ScanItem = {
  symbol: string;
  price: number;
  change_24h_pct: number | null;
  confluence: number | null;
  verdict: string;
  green_count: number;
  parallel_up_count: number;
  expanding_count: number;
  fresh_cross: string[];
  early_trough_count?: number;
  squeeze_count?: number;
  wt_oversold_cross?: string[];
  zl_fresh_cross?: string[];
  early_spark?: boolean;
  coverage: number;
  tfs: TfCell[];
};

type ScanResponse = {
  total_scanned: number;
  valid_count: number;
  guclu_count: number;
  orta_count: number;
  zayif_count: number;
  fresh_cross_count: number;
  parallel_up_count: number;
  early_trough_count?: number;
  squeeze_count?: number;
  early_spark_count?: number;
  tfs: string[];
  scope: string;
  duration_sec: number;
  scanned_at: number;
  items: ScanItem[];
};

type FilterType = "ALL" | "GUCLU" | "GUCLU_ORTA" | "EARLY_DIP" | "SQUEEZE" | "FRESH" | "PARALLEL";


export default function MtfScannerPage() {
  const [data, setData] = useState<ScanResponse | null>(null);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState("");
  const [scope, setScope] = useState<"active" | "all">("active");
  const [filter, setFilter] = useState<FilterType>("ALL");
  const [search, setSearch] = useState("");


  const runScan = useCallback(
    async (targetScope: "active" | "all" = scope, force = true) => {
      setScanning(true);
      setError("");
      try {
        const res = await apiRequest(
          `${API_BASE}/api/macd-mtf/scan?scope=${targetScope}&force_refresh=${force}`,
          { method: "POST", cache: "no-store" }
        );
        if (!res.ok) {
          throw new Error(`Tarama başarısız (HTTP ${res.status})`);
        }
        const json: ScanResponse = await res.json();
        setData(json);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Tarama sırasında hata oluştu");
      } finally {
        setScanning(false);
      }
    },
    [scope]
  );

  // Sayfa açıldığında otomatik ilk tarama
  useEffect(() => {
    void runScan(scope, false);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Filtrelenmiş sembol listesi
  const filteredItems = useMemo(() => {
    if (!data?.items) return [];
    let list = [...data.items];

    if (search.trim()) {
      const q = search.trim().toUpperCase();
      list = list.filter((it) => it.symbol.includes(q));
    }

    if (filter === "GUCLU") {
      list = list.filter((it) => it.verdict === "GÜÇLÜ");
    } else if (filter === "GUCLU_ORTA") {
      list = list.filter((it) => it.verdict === "GÜÇLÜ" || it.verdict === "ORTA");
    } else if (filter === "EARLY_DIP") {
      list = list.filter((it) => (it.early_trough_count || 0) >= 2 || it.early_spark);
    } else if (filter === "SQUEEZE") {
      list = list.filter(
        (it) =>
          (it.squeeze_count || 0) >= 1 &&
          ((it.green_count || 0) >= 1 || (it.early_trough_count || 0) >= 1)
      );
    } else if (filter === "FRESH") {
      list = list.filter((it) => it.fresh_cross && it.fresh_cross.length > 0);
    } else if (filter === "PARALLEL") {
      list = list.filter((it) => it.parallel_up_count >= 2);
    }


    return list;
  }, [data, filter, search]);

  const verdictBadge = (verdict: string) => {
    if (verdict === "GÜÇLÜ") {
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-black font-mono bg-neon-green/15 text-neon-green border border-neon-green/40 shadow-sm shadow-neon-green/10">
          <span className="w-2 h-2 rounded-full bg-neon-green animate-pulse" />
          GÜÇLÜ
        </span>
      );
    }
    if (verdict === "ORTA") {
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-bold font-mono bg-yellow-400/15 text-yellow-300 border border-yellow-400/40">
          <span className="w-1.5 h-1.5 rounded-full bg-yellow-400" />
          ORTA
        </span>
      );
    }
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-mono bg-bunker-800 text-bunker-muted border border-bunker-700">
        ZAYIF
      </span>
    );
  };

  return (
    <div className="space-y-5 max-w-7xl mx-auto pb-12">
      {/* ── ÜST BAŞLIK & METOT AÇIKLAMASI ─────────────────────────────── */}
      <header className="rounded-2xl border border-bunker-800 bg-gradient-to-r from-bunker-950 via-bunker-900 to-bunker-950 p-5 shadow-xl">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2.5 flex-wrap">
              <span className="text-2xl">🧠</span>
              <h1 className="font-mono text-xl sm:text-2xl font-black text-white tracking-tight">
                MACD MTF <span className="text-neon-green">CANLI TARAYICI</span>
              </h1>
              <span className="rounded-full border border-neon-green/40 bg-neon-green/10 px-2.5 py-0.5 font-mono text-[10px] font-bold text-neon-green">
                M1 · M3 · M5 · M15 · M30
              </span>
            </div>
            <p className="mt-1.5 text-xs text-bunker-muted leading-relaxed max-w-3xl">
              MACD ve Signal çizgilerinin yönü ve kesişimlerine ek olarak, <b className="text-white">🌱 Histogram Dip Dönüşü (kesişimden 3-7 bar önceki en erken dip)</b>, <b className="text-white">⚡ Squeeze (patlama öncesi enerji sıkışması)</b>, <b className="text-white">🚀 Zero-Lag MACD</b> ve <b className="text-white">⭐ WaveTrend</b> öncü göstergelerini çoklu zaman diliminde tarar. Listelenen bir sembole tıkladığınızda doğrudan{" "}
              <b className="text-neon-green">4&apos;lü Teknik Grafik</b> ekranı açılır.
            </p>
          </div>

          {/* Aksiyon Butonu */}
          <div className="flex items-center gap-2 shrink-0">
            <button
              type="button"
              onClick={() => void runScan(scope, true)}
              disabled={scanning}
              className={`flex items-center gap-2.5 rounded-xl px-5 py-3 font-mono text-sm font-black transition-all shadow-lg ${
                scanning
                  ? "bg-bunker-800 text-bunker-muted cursor-not-allowed border border-bunker-700"
                  : "bg-neon-green text-black hover:bg-neon-green/90 border border-neon-green shadow-neon-green/20 hover:scale-[1.02] active:scale-[0.98]"
              }`}
            >
              {scanning ? (
                <>
                  <span className="w-4 h-4 border-2 border-black/40 border-t-black rounded-full animate-spin" />
                  TARANIYOR…
                </>
              ) : (
                <>
                  <span className="text-base">🚀</span>
                  PİYASAYI TARA (MANUEL)
                </>
              )}
            </button>
          </div>
        </div>

        {/* Bilgi bandı & son tarama süresi */}
        {data && (
          <div className="mt-4 pt-3 border-t border-bunker-800/80 flex flex-wrap items-center justify-between gap-2 text-xs font-mono text-bunker-muted">
            <div className="flex items-center gap-3">
              <span>
                Son tarama:{" "}
                <b className="text-white">
                  {new Date(data.scanned_at * 1000).toLocaleTimeString("tr-TR")}
                </b>
              </span>
              <span>·</span>
              <span>
                Süre: <b className="text-neon-green">{data.duration_sec}s</b>
              </span>
              <span>·</span>
              <span>
                Kapsam:{" "}
                <b className="text-white">
                  {data.scope === "all"
                    ? "Tüm Binance TR Çiftleri"
                    : "Aktif & İzlenen"}
                </b>

              </span>
            </div>
            <div>
              <span>
                Toplam <b className="text-white">{data.valid_count}</b> sembol incelendi
              </span>
            </div>
          </div>
        )}
      </header>

      {/* ── KPI KARTLARI ────────────────────────────────────────────────── */}
      {data && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2.5 font-mono">
          <div className="rounded-xl border border-neon-green/30 bg-neon-green/5 p-3">
            <div className="flex items-center justify-between">
              <span className="text-[11px] text-neon-green font-bold">GÜÇLÜ SİNYAL</span>
              <span className="text-sm">🔥</span>
            </div>
            <p className="text-2xl font-black text-neon-green mt-1">{data.guclu_count}</p>
            <p className="text-[10px] text-bunker-muted mt-0.5">Yüksek konfluans</p>
          </div>

          <div className="rounded-xl border border-emerald-400/30 bg-emerald-400/5 p-3">
            <div className="flex items-center justify-between">
              <span className="text-[11px] text-emerald-300 font-bold">🌱 ERKEN DİP</span>
              <span className="text-sm">🌱</span>
            </div>
            <p className="text-2xl font-black text-emerald-300 mt-1">{data.early_trough_count || 0}</p>
            <p className="text-[10px] text-bunker-muted mt-0.5">Hist dip dönüşü (en erken)</p>
          </div>

          <div className="rounded-xl border border-amber-400/30 bg-amber-400/5 p-3">
            <div className="flex items-center justify-between">
              <span className="text-[11px] text-amber-300 font-bold">⚡ SIKIŞMA (SQZ)</span>
              <span className="text-sm">⚡</span>
            </div>
            <p className="text-2xl font-black text-amber-300 mt-1">{data.squeeze_count || 0}</p>
            <p className="text-[10px] text-bunker-muted mt-0.5">Patlama öncesi enerji</p>
          </div>

          <div className="rounded-xl border border-cyan-400/30 bg-cyan-400/5 p-3">
            <div className="flex items-center justify-between">
              <span className="text-[11px] text-cyan-300 font-bold">TAZE KESİŞİM</span>
              <span className="text-sm">🚀</span>
            </div>
            <p className="text-2xl font-black text-cyan-300 mt-1">{data.fresh_cross_count}</p>
            <p className="text-[10px] text-bunker-muted mt-0.5">Son 1-3 barda kesen</p>
          </div>

          <div className="rounded-xl border border-purple-400/30 bg-purple-400/5 p-3">
            <div className="flex items-center justify-between">
              <span className="text-[11px] text-purple-300 font-bold">PARALEL YUKARI</span>
              <span className="text-sm">⇈</span>
            </div>
            <p className="text-2xl font-black text-purple-300 mt-1">{data.parallel_up_count}</p>
            <p className="text-[10px] text-bunker-muted mt-0.5">≥2 TF pozitif eğim</p>
          </div>

          <div className="rounded-xl border border-bunker-800 bg-bunker-950/60 p-3">
            <div className="flex items-center justify-between">
              <span className="text-[11px] text-bunker-muted font-bold">TARANAN</span>
              <span className="text-sm">📊</span>
            </div>
            <p className="text-2xl font-black text-white mt-1">{data.total_scanned}</p>
            <p className="text-[10px] text-bunker-muted mt-0.5">{data.valid_count} aktif sembol</p>
          </div>
        </div>
      )}

      {/* ── FİLTRELER & ARAMA ───────────────────────────────────────────── */}
      <div className="card rounded-2xl border border-bunker-800 bg-bunker-950/70 p-4 space-y-3">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3">
          {/* Hızlı Filtre Butonları */}
          <div className="flex flex-wrap items-center gap-1.5 font-mono text-xs">
            <span className="text-bunker-muted mr-1">Filtre:</span>
            <button
              type="button"
              onClick={() => setFilter("ALL")}
              className={`rounded-lg px-3 py-1.5 font-bold transition-colors ${
                filter === "ALL"
                  ? "bg-white text-black border border-white"
                  : "bg-bunker-900 text-bunker-muted border border-bunker-800 hover:text-white"
              }`}
            >
              Tümü ({data?.items?.length || 0})
            </button>
            <button
              type="button"
              onClick={() => setFilter("EARLY_DIP")}
              className={`rounded-lg px-3 py-1.5 font-bold transition-colors flex items-center gap-1.5 ${
                filter === "EARLY_DIP"
                  ? "bg-emerald-400/20 text-emerald-300 border border-emerald-400/60 shadow-sm shadow-emerald-400/10"
                  : "bg-bunker-900 text-bunker-muted border border-bunker-800 hover:text-emerald-300"
              }`}
              title="Kesişimden 3-7 bar önce dipten dönenler (En Erken)"
            >
              <span>🌱</span> Erken Dip ({data?.early_trough_count || 0})
            </button>
            <button
              type="button"
              onClick={() => setFilter("SQUEEZE")}
              className={`rounded-lg px-3 py-1.5 font-bold transition-colors flex items-center gap-1.5 ${
                filter === "SQUEEZE"
                  ? "bg-amber-400/20 text-amber-300 border border-amber-400/60 shadow-sm shadow-amber-400/10"
                  : "bg-bunker-900 text-bunker-muted border border-bunker-800 hover:text-amber-300"
              }`}
              title="Bollinger-Keltner enerji sıkışması yaşayanlar (En Doğru Patlama Öncüsü)"
            >
              <span>⚡</span> Sıkışma / Patlama ({data?.squeeze_count || 0})
            </button>
            <button
              type="button"
              onClick={() => setFilter("GUCLU")}
              className={`rounded-lg px-3 py-1.5 font-bold transition-colors flex items-center gap-1.5 ${
                filter === "GUCLU"
                  ? "bg-neon-green/20 text-neon-green border border-neon-green/50"
                  : "bg-bunker-900 text-bunker-muted border border-bunker-800 hover:text-neon-green"
              }`}
            >
              <span>🔥</span> Sadece GÜÇLÜ ({data?.guclu_count || 0})
            </button>
            <button
              type="button"
              onClick={() => setFilter("GUCLU_ORTA")}
              className={`rounded-lg px-3 py-1.5 font-bold transition-colors flex items-center gap-1.5 ${
                filter === "GUCLU_ORTA"
                  ? "bg-yellow-400/20 text-yellow-300 border border-yellow-400/50"
                  : "bg-bunker-900 text-bunker-muted border border-bunker-800 hover:text-yellow-300"
              }`}
            >
              <span>⚡</span> GÜÇLÜ & ORTA ({(data?.guclu_count || 0) + (data?.orta_count || 0)})
            </button>
            <button
              type="button"
              onClick={() => setFilter("FRESH")}
              className={`rounded-lg px-3 py-1.5 font-bold transition-colors flex items-center gap-1.5 ${
                filter === "FRESH"
                  ? "bg-cyan-400/20 text-cyan-300 border border-cyan-400/50"
                  : "bg-bunker-900 text-bunker-muted border border-bunker-800 hover:text-cyan-300"
              }`}
            >
              <span>🚀</span> Taze Kesişenler ({data?.fresh_cross_count || 0})
            </button>
            <button
              type="button"
              onClick={() => setFilter("PARALLEL")}
              className={`rounded-lg px-3 py-1.5 font-bold transition-colors flex items-center gap-1.5 ${
                filter === "PARALLEL"
                  ? "bg-purple-400/20 text-purple-300 border border-purple-400/50"
                  : "bg-bunker-900 text-bunker-muted border border-bunker-800 hover:text-purple-300"
              }`}
            >
              <span>⇈</span> Paralel Yukarı ({data?.parallel_up_count || 0})
            </button>
          </div>


          {/* Kapsam & Arama */}
          <div className="flex items-center gap-2">
            <select
              value={scope}
              onChange={(e) => {
                const newScope = e.target.value as "active" | "all";
                setScope(newScope);
                void runScan(newScope, true);
              }}
              className="rounded-lg border border-bunker-700 bg-bunker-900 px-2.5 py-1.5 font-mono text-xs text-white focus:border-neon-green focus:outline-none"
            >
              <option value="active">Aktif & İzlenen (~50)</option>
              <option value="all">Tüm Çiftler</option>
            </select>

            <input
              type="text"
              placeholder="Sembol ara (örn. BTC, ONE)…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-36 sm:w-48 rounded-lg border border-bunker-700 bg-bunker-900 px-3 py-1.5 font-mono text-xs text-white placeholder-bunker-muted focus:border-neon-green focus:outline-none"
            />
          </div>
        </div>
      </div>

      {/* ── HATA / YÜKLENİYOR ───────────────────────────────────────────── */}
      {scanning && (
        <div className="card rounded-2xl border border-neon-green/30 bg-bunker-950/80 p-8 text-center space-y-3">
          <div className="inline-block w-8 h-8 border-2 border-neon-green/30 border-t-neon-green rounded-full animate-spin" />
          <p className="font-mono text-sm font-bold text-white">Piyasa taranıyor…</p>
          <p className="font-mono text-xs text-bunker-muted">
            M1, M3, M5, M15 ve M30 kapanış mumları üzerinden MACD-Signal çizgileri ve eğimleri analiz ediliyor.
          </p>
        </div>
      )}

      {error && (
        <div className="card rounded-2xl border border-neon-red/40 bg-neon-red/10 p-4 text-center">
          <p className="font-mono text-sm font-bold text-neon-red">⚠ {error}</p>
        </div>
      )}

      {/* ── SONUÇ LİSTESİ / TABLOSU ────────────────────────────────────── */}
      {!scanning && data && (
        <section className="card rounded-2xl border border-bunker-800 bg-bunker-950/70 p-4 space-y-4 shadow-xl">
          <div className="flex items-center justify-between">
            <h2 className="font-mono text-sm font-black text-white flex items-center gap-2">
              <span>📋</span> TARAMA SONUÇLARI ({filteredItems.length} sembol)
            </h2>
            <span className="text-xs font-mono text-bunker-muted">
              Herhangi bir satırdaki <b className="text-white">📈 Grafik</b> butonuna tıklayarak doğrudan 4&apos;lü ekranda izleyebilirsiniz.
            </span>
          </div>

          {filteredItems.length === 0 ? (
            <div className="py-12 text-center font-mono space-y-2">
              <p className="text-base text-bunker-muted">Seçili filtreye uygun sembol bulunamadı.</p>
              <button
                type="button"
                onClick={() => setFilter("ALL")}
                className="text-xs text-neon-green underline"
              >
                Filtreyi temizle ve tümünü göster
              </button>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse font-mono text-xs">
                <thead>
                  <tr className="border-b border-bunker-800 text-bunker-muted text-[11px]">
                    <th className="py-3 px-3">SEMBOL</th>
                    <th className="py-3 px-2 text-right">FİYAT</th>
                    <th className="py-3 px-2 text-right">24S DEĞİŞİM</th>
                    <th className="py-3 px-3 text-center">KARAR</th>
                    <th className="py-3 px-2 text-center">SKOR</th>
                    <th className="py-3 px-2 text-center">ÖNCÜ SİNYAL</th>
                    <th className="py-3 px-3 text-center">ZAMAN DİLİMLERİ (M1 · M3 · M5 · M15 · M30)</th>
                    <th className="py-3 px-2 text-center">TAZE KESİŞİM</th>
                    <th className="py-3 px-2 text-center">PARALEL YUKARI</th>
                    <th className="py-3 px-3 text-right">AKSİYON</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-bunker-800/60">
                  {filteredItems.map((item) => {
                    const changeColor =
                      (item.change_24h_pct || 0) > 0
                        ? "text-neon-green"
                        : (item.change_24h_pct || 0) < 0
                        ? "text-neon-red"
                        : "text-bunker-muted";

                    return (
                      <tr
                        key={item.symbol}
                        className="hover:bg-bunker-900/50 transition-colors group"
                      >
                        {/* Sembol */}
                        <td className="py-3 px-3">
                          <Link
                            href={`/technical-charts?symbol=${item.symbol}`}
                            className="font-bold text-sm text-white hover:text-neon-green transition-colors flex items-center gap-1.5"
                            title="4'lü Teknik Grafikte Aç"
                          >
                            <span>{item.symbol}</span>
                            <span className="text-[10px] text-neon-green opacity-0 group-hover:opacity-100 transition-opacity">
                              ↗
                            </span>
                          </Link>
                        </td>

                        {/* Fiyat */}
                        <td className="py-3 px-2 text-right font-medium text-white">
                          {QUOTE_SYMBOL}{formatPrice(item.price)}
                        </td>

                        {/* 24s Değişim */}
                        <td className={`py-3 px-2 text-right font-bold ${changeColor}`}>
                          {item.change_24h_pct != null
                            ? `${item.change_24h_pct >= 0 ? "+" : ""}${item.change_24h_pct}%`
                            : "—"}
                        </td>

                        {/* Karar */}
                        <td className="py-3 px-3 text-center">
                          {verdictBadge(item.verdict)}
                        </td>

                        {/* Skor */}
                        <td className="py-3 px-2 text-center">
                          <div className="inline-flex items-center gap-1.5">
                            <span
                              className={`font-black text-xs ${
                                (item.confluence || 0) >= 75
                                  ? "text-neon-green"
                                  : (item.confluence || 0) >= 45
                                  ? "text-yellow-300"
                                  : "text-bunker-muted"
                              }`}
                            >
                              {item.confluence != null ? item.confluence : "—"}
                            </span>
                          </div>
                        </td>

                        {/* Öncü Sinyal (Erken Dip / Squeeze / WT / ZL) */}
                        <td className="py-3 px-2 text-center">
                          <div className="flex flex-col items-center gap-1">
                            {(item.early_trough_count || 0) >= 2 && (
                              <span
                                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-bold bg-emerald-400/15 text-emerald-300 border border-emerald-400/40"
                                title="Histogram kesişimden 3-7 bar önce dipten yukarı ivmelendi"
                              >
                                <span>🌱</span> {item.early_trough_count} TF Dip
                              </span>
                            )}
                            {(item.squeeze_count || 0) >= 1 && (
                              <span
                                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-bold bg-amber-400/15 text-amber-300 border border-amber-400/40"
                                title="Bollinger/Keltner enerji sıkışması aktif"
                              >
                                <span>⚡</span> {item.squeeze_count} TF SQZ
                              </span>
                            )}
                            {item.wt_oversold_cross && item.wt_oversold_cross.length > 0 && (
                              <span
                                className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-bold bg-pink-400/15 text-pink-300 border border-pink-400/40"
                                title="WaveTrend aşırı satım kesişimi"
                              >
                                <span>⭐</span> WT {item.wt_oversold_cross.join(",")}
                              </span>
                            )}
                            {item.zl_fresh_cross && item.zl_fresh_cross.length > 0 && (
                              <span
                                className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-bold bg-indigo-400/15 text-indigo-300 border border-indigo-400/40"
                                title="Zero-Lag MACD taze kesişim"
                              >
                                <span>🚀</span> ZL {item.zl_fresh_cross.join(",")}
                              </span>
                            )}
                            {!(item.early_trough_count && item.early_trough_count >= 2) &&
                              !(item.squeeze_count && item.squeeze_count >= 1) &&
                              !(item.wt_oversold_cross && item.wt_oversold_cross.length > 0) &&
                              !(item.zl_fresh_cross && item.zl_fresh_cross.length > 0) && (
                                <span className="text-bunker-muted/50 text-[10px]">—</span>
                            )}
                          </div>
                        </td>

                        {/* Zaman Dilimleri Hapları (M1..M30) */}
                        <td className="py-3 px-3 text-center">
                          <div className="flex items-center justify-center gap-1.5 flex-wrap">
                            {["1m", "3m", "5m", "15m", "30m"].map((tfName) => {
                              const cell = item.tfs?.find((c) => c.tf === tfName);
                              if (!cell) {
                                return (
                                  <span
                                    key={tfName}
                                    className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-bunker-900 text-bunker-muted border border-bunker-800"
                                    title={`${tfName}: Veri yok`}
                                  >
                                    {tfName}
                                  </span>
                                );
                              }

                              const isGreen = cell.green;
                              const isFresh = cell.fresh_bull_cross;
                              const isParallel = cell.parallel_up;
                              const isExpanding = cell.expanding;
                              const isTrough = cell.hist_trough;
                              const isSqueeze = cell.squeeze;
                              const isWtCross = cell.wt_oversold_cross;

                              return (
                                <div
                                  key={tfName}
                                  className={`px-1.5 py-0.5 rounded text-[10px] font-mono flex items-center gap-1 border transition-all ${
                                    isGreen
                                      ? "bg-neon-green/10 border-neon-green/40 text-neon-green"
                                      : isTrough
                                      ? "bg-emerald-400/10 border-emerald-400/50 text-emerald-300 shadow-sm shadow-emerald-400/10"
                                      : "bg-neon-red/10 border-neon-red/30 text-neon-red/80"
                                  }`}
                                  title={`${tfName.toUpperCase()} · MACD: ${cell.macd.toFixed(
                                    4
                                  )} · Sig: ${cell.signal.toFixed(4)} · Hist: ${cell.hist.toFixed(
                                    4
                                  )} | ${
                                    isGreen
                                      ? "Yeşil (MACD > Sig)"
                                      : isTrough
                                      ? "🌱 Erken Dip Dönüşü (Hist yukarı büküldü)"
                                      : "Kırmızı (Negatif)"
                                  } ${isFresh ? "· 🚀 Taze Kesişim" : ""} ${
                                    isParallel ? "· ⇈ Paralel Yukarı" : ""
                                  } ${isSqueeze ? "· ⚡ Sıkışma Aktif" : ""} ${
                                    isWtCross ? "· ⭐ WaveTrend Dip Kesişimi" : ""
                                  }`}
                                >
                                  <span className="font-bold">{tfName}</span>
                                  {isSqueeze && (
                                    <span className="text-[9px] text-amber-300" title="Sıkışma">
                                      ⚡
                                    </span>
                                  )}
                                  {isFresh ? (
                                    <span title="Taze Kesişim">🚀</span>
                                  ) : isParallel ? (
                                    <span title="Paralel Yukarı">⇈</span>
                                  ) : isExpanding ? (
                                    <span title="Araları Açık">↗</span>
                                  ) : isGreen ? (
                                    <span>✔</span>
                                  ) : isTrough ? (
                                    <span title="Erken Dip Dönüşü" className="text-emerald-400 font-bold">
                                      🌱
                                    </span>
                                  ) : (
                                    <span>✖</span>
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        </td>


                        {/* Taze Kesişim */}
                        <td className="py-3 px-2 text-center">
                          {item.fresh_cross && item.fresh_cross.length > 0 ? (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-bold bg-cyan-400/15 text-cyan-300 border border-cyan-400/40">
                              <span>🚀</span>
                              {item.fresh_cross.join(", ")}
                            </span>
                          ) : (
                            <span className="text-bunker-muted/60">—</span>
                          )}
                        </td>

                        {/* Paralel Yukarı */}
                        <td className="py-3 px-2 text-center">
                          {item.parallel_up_count > 0 ? (
                            <span
                              className={`font-bold ${
                                item.parallel_up_count >= 3
                                  ? "text-neon-green"
                                  : "text-purple-300"
                              }`}
                            >
                              {item.parallel_up_count} / {item.coverage} TF
                            </span>
                          ) : (
                            <span className="text-bunker-muted/60">0</span>
                          )}
                        </td>

                        {/* Aksiyon Butonu */}
                        <td className="py-3 px-3 text-right">
                          <div className="flex items-center justify-end gap-2">
                            <Link
                              href={`/technical-charts?symbol=${item.symbol}`}
                              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg font-bold text-xs bg-neon-green/15 text-neon-green border border-neon-green/40 hover:bg-neon-green hover:text-black transition-all shadow-sm shadow-neon-green/10"
                              title={`${item.symbol} 4'lü MTF Teknik Grafiğini Aç`}
                            >
                              <span>📈</span>
                              <span>Grafikte Aç</span>
                            </Link>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
