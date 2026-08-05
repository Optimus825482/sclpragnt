"use client";
import { useEffect, useState } from "react";
import { API_BASE } from "../lib/api";

type Config = {
  symbols: string[];
  min_notional: number;
  default_order_usdt: number;
  min_24h_quote_volume_try: number;
  high_liquidity_bypass_volume_try: number;
  min_volume_ratio: number;
  max_spread_pct: number;
  min_orderbook_depth_multiplier: number;
  max_open_positions: number;
  hard_stop_loss_pct: number;
  cooldown_bars: number;
  take_profit_pct: number;
  trailing_stop_pct: number;
  ut_enabled: boolean;
  ut_symbols: string[];
  ut_key_value: number;
  ut_atr_period: number;
  ut_heikin_ashi: boolean;
  initial_balance_try: number;
  mode: string;
  market_data: string;
  gainer_radar_min_score: number;
  adr_filter_enabled: boolean;
  adr_period: number;
  adr_min_pct: number;
  adr_max_utilization_pct: number;
  adr_min_remaining_pct: number;
};

export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState<"symbols" | "app" | "strategies">("symbols");
  const [cfg, setCfg] = useState<Config | null>(null);
  const [draft, setDraft] = useState<Partial<Config>>({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resetting, setResetting] = useState(false);
  const [resetDone, setResetDone] = useState(false);
  const [marketSymbols, setMarketSymbols] = useState<string[]>([]);
  const [symbolQuery, setSymbolQuery] = useState("");
  const [backingUp, setBackingUp] = useState(false);
  const [backupDone, setBackupDone] = useState(false);

  useEffect(() => {
    fetch(`${API_BASE}/api/config`)
      .then((r) => r.json())
      .then((d) => { setCfg(d); setDraft(d); })
      .catch(() => setError("Backend'e bağlanılamadı (http://localhost:8004)"));
    fetch(`${API_BASE}/api/market-symbols`)
      .then((r) => r.json())
      .then((d) => setMarketSymbols(d.symbols || []))
      .catch(() => setError("Binance TR sembolleri alınamadı"));
  }, []);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/config`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(draft)
      });
      const updated = await res.json();
      setCfg(updated);
      setDraft(updated);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch {
      setError("Kaydedilemedi - backend bağlantısını kontrol et");
    } finally {
      setSaving(false);
    }
  };

  const num = (v: any) => (typeof v === "number" ? v : parseFloat(v));
  const selectedSymbols = draft.symbols || [];
  const filteredSymbols = marketSymbols.filter((s) => s.includes(symbolQuery.trim().toUpperCase()));
  const toggleSymbol = (symbol: string) => setDraft((d) => ({
    ...d,
    symbols: (d.symbols || []).includes(symbol)
      ? (d.symbols || []).filter((s) => s !== symbol)
      : [...(d.symbols || []), symbol],
  }));

  const resetTradingData = async () => {
    if (!window.confirm("Eski işlemler, sinyaller, açık pozisyonlar ve sanal cüzdan silinecek. Cüzdan 10.000 TL ile başlayacak. Devam edilsin mi?")) return;
    setResetting(true);
    setError(null);
    setResetDone(false);
    try {
      const res = await fetch(`${API_BASE}/api/reset`, { method: "POST" });
      if (!res.ok) throw new Error("reset failed");
      setResetDone(true);
      setTimeout(() => setResetDone(false), 3000);
    } catch {
      setError("Kayıtlar sıfırlanamadı - backend bağlantısını kontrol et");
    } finally {
      setResetting(false);
    }
  };

  const downloadBackup = async () => {
    setBackingUp(true);
    setError(null);
    setBackupDone(false);
    try {
      const res = await fetch(`${API_BASE}/api/backup`);
      if (!res.ok) throw new Error("backup failed");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `scalperagent-backup-${new Date().toISOString().replace(/[:.]/g, "-")}.sqlite`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      setBackupDone(true);
      setTimeout(() => setBackupDone(false), 3000);
    } catch {
      setError("Veritabanı yedeği alınamadı - backend bağlantısını kontrol et");
    } finally {
      setBackingUp(false);
    }
  };

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="font-mono text-xl font-bold tracking-tight">
            <span className="text-neon-green">AYARLAR</span>
          </h1>
          <p className="eyebrow mt-1">Strateji parametreleri - anında uygulanır</p>
        </div>
        {cfg && (
          <button
            onClick={save}
            disabled={saving}
            className={`px-5 py-2 rounded-lg border font-mono text-sm transition-colors ${saved
              ? "border-neon-green/60 bg-neon-green/20 text-neon-green"
              : "border-neon-green/40 bg-neon-green/10 text-neon-green hover:bg-neon-green/20"
              }`}
          >
            {saving ? "KAYDEDİLİYOR..." : saved ? "✓ KAYDEDİLDİ" : "KAYDET"}
          </button>
        )}
      </header>

      {error && (
        <div className="card border-neon-red/40 bg-neon-red/5">
          <p className="font-mono text-sm text-neon-red">{error}</p>
        </div>
      )}

      {!cfg && !error && (
        <div className="card"><p className="font-mono text-sm text-bunker-muted animate-pulse">Yükleniyor...</p></div>
      )}

      {cfg && (
        <nav className="flex gap-2 overflow-x-auto border-b border-bunker-800 pb-2" aria-label="Ayar sekmeleri">
          {([
            ["symbols", "Semboller", "🪙"],
            ["app", "Uygulama Ayarları", "⚙️"],
            ["strategies", "Strateji Ayarları", "📈"],
          ] as const).map(([key, label, icon]) => (
            <button key={key} onClick={() => setActiveTab(key)} className={`shrink-0 px-4 py-2 rounded-lg border font-mono text-xs transition-colors ${activeTab === key ? "border-neon-green/60 bg-neon-green/15 text-neon-green" : "border-bunker-700 bg-bunker-900 text-bunker-muted hover:text-white"}`}>
              {icon} {label}
            </button>
          ))}
        </nav>
      )}

      {cfg && (
        <>
          <div className={`card bg-bunker-950 ${activeTab !== "symbols" ? "hidden" : ""}`}>
            <div className="flex justify-between items-center mb-4">
              <div>
                <p className="eyebrow">BINANCE TR SEMBOLLERİ</p>
                <p className="text-xs text-bunker-muted mt-1">Arayın, seçerek ekleyin; seçili sembolleri aktif/pasif yapın.</p>
              </div>
              <span className="font-mono text-xs text-bunker-muted">{selectedSymbols.length} aktif</span>
            </div>
            <input
              value={symbolQuery}
              onChange={(e) => setSymbolQuery(e.target.value)}
              placeholder="Sembol ara: BTC, ETH, SOL..."
              className="w-full bg-bunker-900 border border-bunker-700 rounded-lg px-3 py-2 font-mono text-sm text-white placeholder-bunker-700 outline-none focus:border-neon-green/50"
            />
            <div className="flex flex-wrap gap-2 mt-3 max-h-36 overflow-y-auto">
              {filteredSymbols.map((symbol) => {
                const active = selectedSymbols.includes(symbol);
                return <button key={symbol} onClick={() => toggleSymbol(symbol)} className={`px-3 py-1.5 rounded-lg border font-mono text-xs transition-colors ${active ? "border-neon-green/60 bg-neon-green/20 text-neon-green" : "border-bunker-700 bg-bunker-900 text-bunker-muted hover:text-white"}`}>{active ? "✓ " : "+ "}{symbol}</button>;
              })}
              {!filteredSymbols.length && <span className="text-xs text-bunker-muted font-mono">Sembol bulunamadı</span>}
            </div>
            <div className="mt-4 pt-3 border-t border-bunker-800/60">
              <p className="eyebrow mb-2">SEÇİLEN SEMBOLLER</p>
              <div className="flex flex-wrap gap-2">
                {selectedSymbols.map((symbol) => <button key={symbol} onClick={() => toggleSymbol(symbol)} className="px-3 py-1.5 rounded-lg border border-neon-green/60 bg-neon-green/15 font-mono text-xs text-neon-green">AKTİF · {symbol}</button>)}
              </div>
            </div>
          </div>

          <div className={`card bg-bunker-950 ${activeTab !== "app" ? "hidden" : ""}`}>
            <div className="flex items-center justify-between gap-4">
              <div>
                <p className="eyebrow">GAINER RADAR MİNİMUM SKOR</p>
                <p className="text-xs text-bunker-muted mt-1">Bu skorun altındaki adaylar otomatik paper işlem için kullanılmaz. Önerilen başlangıç: 50.</p>
              </div>
              <input type="number" min={0} max={100} step={1} value={num(draft.gainer_radar_min_score)} onChange={(e) => setDraft((d) => ({ ...d, gainer_radar_min_score: e.target.value === "" ? NaN : Number(e.target.value) }))} className="w-24 bg-bunker-900 border border-bunker-700 rounded-lg px-3 py-1.5 font-mono text-sm text-white text-right focus:border-neon-green/50 outline-none" />
            </div>
            <div className="mt-5 border-t border-bunker-800 pt-4">
              <p className="eyebrow">LİKİDİTE FİLTRESİ</p>
              <p className="text-xs text-bunker-muted mt-1">İşlem açılmadan önce düşük hacim, geniş spread ve sığ emir defteri engellenir.</p>
              <div className="grid sm:grid-cols-2 gap-3 mt-3">
                {([
                  ["min_24h_quote_volume_try", "Minimum 24s hacim (TL)", 1000],
                  ["high_liquidity_bypass_volume_try", "Yüksek likidite eşiği (TL)", 1000],
                  ["min_volume_ratio", "Minimum hacim oranı", 0.1],
                  ["max_spread_pct", "Maksimum spread (%)", 0.01],
                  ["min_orderbook_depth_multiplier", "Emir defteri çarpanı", 0.5],
                ] as const).map(([key, label, step]) => (
                  <label key={key} className="flex items-center justify-between gap-3 rounded-lg border border-bunker-800 bg-bunker-900 px-3 py-2">
                    <span className="font-mono text-xs text-bunker-muted">{label}</span>
                    <input type="number" min={0} step={step} value={num((draft as any)[key])} onChange={(e) => setDraft((d) => ({ ...d, [key]: e.target.value === "" ? NaN : Number(e.target.value) }))} className="w-32 bg-bunker-950 border border-bunker-700 rounded-lg px-2 py-1.5 font-mono text-sm text-white text-right outline-none focus:border-neon-green/50" />
                  </label>
                ))}
              </div>
              <p className="text-[11px] text-bunker-muted mt-2 font-mono">Önerilen: 1.000.000 TL · 0,3x · %0,30 · 5x</p>
            </div>
            <div className="mt-5 border-t border-bunker-800 pt-4">
              <p className="eyebrow">MTF MOMENTUM · ADR FİLTRESİ</p>
              <p className="text-xs text-bunker-muted mt-1">Yalnızca MTF Momentum girişlerinde, sembolün günlük hareket kapasitesi ve gün içi aşırı uzama kontrol edilir.</p>
              <div className="grid sm:grid-cols-2 gap-3 mt-3">
                <label className="flex items-center justify-between gap-3 rounded-lg border border-bunker-800 bg-bunker-900 px-3 py-2"><span className="font-mono text-xs text-bunker-muted">ADR filtresi</span><input type="checkbox" checked={Boolean(draft.adr_filter_enabled)} onChange={(e) => setDraft((d) => ({ ...d, adr_filter_enabled: e.target.checked }))} /></label>
                {([ ["adr_period", "ADR periyodu (gün)", 1], ["adr_min_pct", "Minimum ADR (%)", 0.1], ["adr_max_utilization_pct", "Maksimum kullanım (%)", 0.01], ["adr_min_remaining_pct", "Minimum kalan hareket (%)", 0.1] ] as const).map(([key, label, step]) => <label key={key} className="flex items-center justify-between gap-3 rounded-lg border border-bunker-800 bg-bunker-900 px-3 py-2"><span className="font-mono text-xs text-bunker-muted">{label}</span><input type="number" min={0} step={step} value={key === "adr_period" ? num((draft as any)[key]) : num((draft as any)[key]) * 100} onChange={(e) => setDraft((d) => ({ ...d, [key]: e.target.value === "" ? NaN : key === "adr_period" ? Number(e.target.value) : Number(e.target.value) / 100 }))} className="w-32 bg-bunker-950 border border-bunker-700 rounded-lg px-2 py-1.5 font-mono text-sm text-white text-right outline-none focus:border-neon-green/50" /></label>)}
              </div>
              <p className="text-[11px] text-bunker-muted mt-2 font-mono">Başlangıç: 14 gün · minimum ADR %2 · gün içi kullanım en fazla %80 · kalan kapasite en az %1</p>
            </div>
          </div>

          <div className={`card border-neon-red/30 bg-neon-red/5 ${activeTab !== "app" ? "hidden" : ""}`}>
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
              <div>
                <p className="eyebrow text-neon-red">PAPER TRADING KAYITLARI</p>
                <p className="font-mono text-sm text-white mt-2">Eski işlem, sinyal, açık pozisyon ve sanal cüzdan kayıtlarını temizle</p>
                <p className="text-xs text-bunker-muted mt-1">Bu işlem geri alınamaz. Yeni bakiye 10.000 TL olur; strateji ayarları değişmez.</p>
              </div>
              <button
                onClick={resetTradingData}
                disabled={resetting}
                className={`shrink-0 px-4 py-2 rounded-lg border font-mono text-xs transition-colors ${resetDone
                  ? "border-neon-green/60 bg-neon-green/15 text-neon-green"
                  : "border-neon-red/50 bg-neon-red/10 text-neon-red hover:bg-neon-red/20"
                  }`}
              >
                {resetting ? "TEMİZLENİYOR..." : resetDone ? "✓ TEMİZLENDİ" : "ESKİ KAYITLARI RESETLE"}
              </button>
            </div>
          </div>

          <div className={`card border-neon-green/30 bg-neon-green/5 ${activeTab !== "app" ? "hidden" : ""}`}>
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
              <div>
                <p className="eyebrow text-neon-green">VERİTABANI YEDEĞİ</p>
                <p className="font-mono text-sm text-white mt-2">Canlı paper-trading veritabanının tutarlı kopyasını indir</p>
                <p className="text-xs text-bunker-muted mt-1">İşlemler, sinyaller, açık pozisyonlar ve backtest kayıtları dahil edilir. Bot durmaz.</p>
              </div>
              <button onClick={downloadBackup} disabled={backingUp} className={`shrink-0 px-4 py-2 rounded-lg border font-mono text-xs transition-colors ${backupDone ? "border-neon-green/60 bg-neon-green/20 text-neon-green" : "border-neon-green/50 bg-neon-green/10 text-neon-green hover:bg-neon-green/20"}`}>
                {backingUp ? "YEDEKLENİYOR..." : backupDone ? "✓ YEDEK İNDİRİLDİ" : "SQLITE YEDEĞİ AL"}
              </button>
            </div>
          </div>

          <div className={`card bg-bunker-950 ${activeTab !== "strategies" ? "hidden" : ""}`}>
            <div className="flex justify-between items-center mb-4">
              <p className="eyebrow">İŞLEM VE RİSK YÖNETİMİ</p>
            </div>
              <p className="text-xs text-bunker-muted mb-4">
              Spot scalping: ayarlanabilir kâr hedefi, 2 saat maksimum bekleme ve aynı sembolde tek pozisyon.
            </p>
            <div className="space-y-4">
              <div className="flex items-center justify-between gap-4 border-b border-bunker-800/50 pb-3">
                <div className="min-w-0">
                  <p className="font-mono text-sm text-white">İşlem Başına</p>
                  <p className="text-xs text-bunker-muted mt-0.5">Her girişte kullanılan sanal miktar (TRY)</p>
                </div>
                <input
                  type="number"
                  step={5}
                  min={5}
                  value={num(draft.default_order_usdt)}
                  onChange={(e) => setDraft((d) => ({ ...d, default_order_usdt: e.target.value === "" ? NaN : Number(e.target.value) }))}
                  className="w-28 bg-bunker-900 border border-bunker-700 rounded-lg px-3 py-1.5 font-mono text-sm text-white text-right focus:border-neon-green/50 outline-none"
                />
              </div>
              <div className="flex items-center justify-between gap-4 border-b border-bunker-800/50 pb-3">
                <div className="min-w-0">
                  <p className="font-mono text-sm text-white">Maksimum Açık Pozisyon</p>
                  <p className="text-xs text-bunker-muted mt-0.5">Yeni pozisyon girişleri için global üst sınır</p>
                </div>
                <input
                  type="number"
                  step={1}
                  min={1}
                  max={36}
                  value={num(draft.max_open_positions)}
                  onChange={(e) => setDraft((d) => ({ ...d, max_open_positions: e.target.value === "" ? NaN : Number(e.target.value) }))}
                  className="w-28 bg-bunker-900 border border-bunker-700 rounded-lg px-3 py-1.5 font-mono text-sm text-white text-right focus:border-neon-green/50 outline-none"
                />
              </div>
              <div className="flex items-center justify-between gap-4 border-b border-bunker-800/50 pb-3">
                <div className="min-w-0">
                  <p className="font-mono text-sm text-white">Hard Stop Loss</p>
                  <p className="text-xs text-bunker-muted mt-0.5">Spot modelde kullanılmaz</p>
                </div>
                <input
                  type="number"
                  step={0.1}
                  min={0.1}
                  value={num(draft.hard_stop_loss_pct) * 100}
                  onChange={(e) => setDraft((d) => ({ ...d, hard_stop_loss_pct: (e.target.value === "" ? NaN : Number(e.target.value)) / 100 }))}
                  className="w-28 bg-bunker-900 border border-bunker-700 rounded-lg px-3 py-1.5 font-mono text-sm text-white text-right focus:border-neon-green/50 outline-none"
                />
              </div>
              <div className="flex items-center justify-between gap-4 border-b border-bunker-800/50 pb-3">
                <div className="min-w-0">
                  <div className="mb-4 flex items-center justify-between gap-4 border-b border-bunker-800/50 pb-3">
                    <div className="min-w-0"><p className="font-mono text-sm text-white">Kapanış Sonrası Cooldown</p><p className="text-xs text-bunker-muted mt-0.5">Yeni girişten önce beklenecek mum sayısı</p></div>
                    <input type="number" step={1} min={0} max={100} value={num(draft.cooldown_bars)} onChange={(e) => setDraft((d) => ({ ...d, cooldown_bars: e.target.value === "" ? NaN : Number(e.target.value) }))} className="w-28 bg-bunker-900 border border-bunker-700 rounded-lg px-3 py-1.5 font-mono text-sm text-white text-right outline-none" />
                  </div>
                  <p className="font-mono text-sm text-white">Take Profit</p>
                  <p className="text-xs text-bunker-muted mt-0.5">Pozisyon bu kâr oranına ulaştığında satılır (komisyon hariç)</p>
                </div>
                <input
                  type="number"
                  step={0.1}
                  min={0.1}
                  value={num(draft.take_profit_pct) * 100}
                  onChange={(e) => setDraft((d) => ({ ...d, take_profit_pct: (e.target.value === "" ? NaN : Number(e.target.value)) / 100 }))}
                  className="w-28 bg-bunker-900 border border-bunker-700 rounded-lg px-3 py-1.5 font-mono text-sm text-white text-right focus:border-neon-green/50 outline-none"
                />
              </div>
              <div className="flex items-center justify-between gap-4 border-b border-bunker-800/50 pb-3">
                <div className="min-w-0">
                  <p className="font-mono text-sm text-white">Key Value (a)</p>
                  <p className="text-xs text-bunker-muted mt-0.5">Hassasiyet - ATR çarpanı</p>
                </div>
                <input
                  type="number"
                  step={0.1}
                  min={0.1}
                  value={num(draft.ut_key_value)}
                  onChange={(e) => setDraft((d) => ({ ...d, ut_key_value: e.target.value === "" ? NaN : Number(e.target.value) }))}
                  className="w-28 bg-bunker-900 border border-bunker-700 rounded-lg px-3 py-1.5 font-mono text-sm text-white text-right focus:border-neon-green/50 outline-none"
                />
              </div>
              <div className="flex items-center justify-between gap-4 border-b border-bunker-800/50 pb-3">
                <div className="min-w-0">
                  <p className="font-mono text-sm text-white">ATR Periyodu (c)</p>
                  <p className="text-xs text-bunker-muted mt-0.5">ATR hesaplama uzunluğu</p>
                </div>
                <input
                  type="number"
                  step={1}
                  min={2}
                  value={num(draft.ut_atr_period)}
                  onChange={(e) => setDraft((d) => ({ ...d, ut_atr_period: e.target.value === "" ? NaN : Number(e.target.value) }))}
                  className="w-28 bg-bunker-900 border border-bunker-700 rounded-lg px-3 py-1.5 font-mono text-sm text-white text-right focus:border-neon-green/50 outline-none"
                />
              </div>
              <div className="flex items-center justify-between gap-4 border-b border-bunker-800/50 pb-3">
                <div className="min-w-0">
                  <p className="font-mono text-sm text-white">Heikin Ashi Mumları</p>
                  <p className="text-xs text-bunker-muted mt-0.5">Sinyalleri HA mumlarından al</p>
                </div>
                <button
                  onClick={() => setDraft((d) => ({ ...d, ut_heikin_ashi: !d.ut_heikin_ashi }))}
                  className={`px-3 py-1.5 rounded-lg border font-mono text-xs transition-colors ${draft.ut_heikin_ashi
                    ? "border-neon-green/60 bg-neon-green/20 text-neon-green"
                    : "border-bunker-700 bg-bunker-900 text-bunker-muted"
                    }`}
                >
                  {draft.ut_heikin_ashi ? "AÇIK" : "KAPALI"}
                </button>
              </div>
              <div className="hidden">
                <p className="font-mono text-sm text-white mb-2">AKTİF SEMBOLLER</p>
                <div className="flex flex-wrap gap-2">
                  {cfg.symbols.map((s) => {
                    const active = (draft.ut_symbols || []).includes(s);
                    return (
                      <button
                        key={s}
                        onClick={() => setDraft((d) => ({
                          ...d,
                          ut_symbols: active
                            ? (d.ut_symbols || []).filter((x) => x !== s)
                            : [...(d.ut_symbols || []), s]
                        }))}
                        className={`px-3 py-1.5 rounded-lg border font-mono text-xs transition-colors ${active
                          ? "border-neon-green/60 bg-neon-green/20 text-neon-green"
                          : "border-bunker-700 bg-bunker-900 text-bunker-muted hover:text-white"
                          }`}
                      >
                        {s}
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
          </div>

          <div className={`card bg-bunker-950 ${activeTab !== "app" ? "hidden" : ""}`}>
            <p className="eyebrow mb-3">MOD</p>
            <div className="flex gap-3">
              <span className="px-3 py-1.5 rounded-full border border-neon-green/40 text-neon-green font-mono text-xs">
                PAPER TRADING
              </span>
              <span className="px-3 py-1.5 rounded-full border border-neon-green/40 text-neon-green font-mono text-xs">PAPER · PUBLIC API</span>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
