"use client";

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import SymbolLink from "../components/SymbolLink";
import { useAuth } from "../lib/auth";
import { canViewMacdMonitor } from "../lib/macdAccess";
import { useLiveMessages, useLiveStatus } from "../lib/liveSocket";
import { apiFetch } from "../lib/api";

// ---------------------------------------------------------------------------
// MACD MONITOR — aktif sembollerin M1/M3/M5/M15/M30/H1 MACD histogram yönü.
// Yeşil = histogram > 0 (MACD line sinyalin üstünde), kırmızı = histogram < 0.
// Canlı veri backend'in {"type":"macd_monitor"} WS yayınıyla ~1 sn'de bir
// gelir; REST snapshot (30 sn poll) WS kapalıyken yedek sağlar.
// ---------------------------------------------------------------------------

const TF_ORDER = ["1m", "3m", "5m", "15m", "30m", "1h"];
const TF_LABELS: Record<string, string> = { "1m": "1M", "3m": "3M", "5m": "5M", "15m": "15M", "30m": "30M", "1h": "1H" };
const POLL_MS = 30_000;

type MacdCell = { green: boolean; hist: number };
type MacdTier = "strong" | "normal" | "weak";
type TfSignals = { break: boolean | null; state: string | null; vol: boolean | null };
type CvdInfo = { fresh?: boolean; buy_ratio?: number | null; whale_net?: number | null; buy_dominant?: boolean };
type PreSignals = { approach?: boolean; m1?: boolean; dip?: boolean };
type SymbolMacd = {
  last: number | null;
  tfs: Record<string, MacdCell | null>;
  r2?: number | null;
  speed?: number | null;
  strength?: number | null;
  tier?: MacdTier | null;
  jump?: number | null;
  sigs?: { "5m"?: TfSignals | null; "15m"?: TfSignals | null };
  cvd?: CvdInfo | null;
  pre?: PreSignals | null;
  pre_any?: boolean | null;
};
type Snapshot = {
  universe: string[];
  symbols: Record<string, SymbolMacd>;
  generated_at: number;
  timeframes?: string[];
  running?: boolean;
  jump_min?: number;
};
const JUMP_MIN_FALLBACK = 60;

const fmtTime = (ts: number | null | undefined) => {
  if (!ts) return "—";
  const date = new Date(ts * 1000);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleTimeString("tr-TR");
};

const fmtPrice = (value: number | null | undefined) => {
  if (value == null || !Number.isFinite(value) || value <= 0) return "—";
  const digits = value < 1 ? 8 : value < 100 ? 6 : 2;
  return Number(value).toLocaleString("tr-TR", { maximumFractionDigits: digits });
};

const histShort = (hist: number) => {
  const abs = Math.abs(hist);
  if (abs === 0) return "0";
  if (abs >= 0.0001) return hist.toFixed(4);
  return hist.toExponential(2);
};

const TIER_LABEL: Record<string, string> = { strong: "GÜÇLÜ", normal: "NORMAL", weak: "ZAYIF" };

const EARLY_LABEL: Record<string, string> = {
  approach: "M5 zirveye yakın",
  m1_breakout: "M1 öncü kırılım",
  macd_dip_turn: "MACD dip dönüşü",
};

// Yeşil ok tonu: trend gücü GÜÇLÜ ise dolu/koyu, ZAYIF ise soluk. Kırmızı
// oklar yön baskısı olduğundan güç tonlamasına girmez.
const arrowShade = (tier: MacdTier | null | undefined) => {
  if (tier === "strong") return "border-neon-green/60 bg-neon-green/25 text-neon-green";
  if (tier === "weak") return "border-neon-green/30 bg-neon-green/5 text-neon-green/80";
  return "border-neon-green/40 bg-neon-green/10 text-neon-green";
};

const strengthChip = (tier: MacdTier | null | undefined) => {
  if (tier === "strong") return "border-neon-green/50 bg-neon-green/15 text-neon-green";
  if (tier === "weak") return "border-bunker-600 bg-bunker-900 text-bunker-muted";
  return "border-yellow-300/50 bg-yellow-300/10 text-yellow-300";
};

const jumpChip = (jump: number, min: number) =>
  jump >= min
    ? "border-neon-green/60 bg-neon-green/20 text-neon-green"
    : jump >= Math.max(30, min - 20)
      ? "border-yellow-300/50 bg-yellow-300/10 text-yellow-300"
      : "border-bunker-600 bg-bunker-900 text-bunker-muted";

const jumpIcons = (m5: TfSignals | null | undefined, m15: TfSignals | null | undefined, cvd: CvdInfo | null | undefined, pre: PreSignals | null | undefined) => {
  const icons: { icon: string; title: string }[] = [];
  const push = (icon: string, title: string) => icons.push({ icon, title });
  if (m5?.break) push("🚀", "M5: 20-bar yüksek kırılımı");
  if (m15?.break) push("🚀", "M15: 20-bar yüksek kırılımı");
  if (m5?.state === "expand") push("⚡", "M5: volatilite genişlemesi");
  if (m15?.state === "expand") push("⚡", "M15: volatilite genişlemesi");
  if (m5?.state === "squeeze") push("🧲", "M5: sıkışma — yay hazır");
  if (m15?.state === "squeeze") push("🧲", "M15: sıkışma — yay hazır");
  if (m5?.vol) push("🔥", "M5: hacim patlaması (>1.5× ort.)");
  if (m15?.vol) push("🔥", "M15: hacim patlaması (>1.5× ort.)");
  if (cvd?.buy_dominant) push("🐋", `Agresör alıcı baskın (oran ${Number(cvd.buy_ratio ?? 0).toFixed(2)}${cvd.whale_net ? ` · balina ${cvd.whale_net > 0 ? "+" : ""}${cvd.whale_net}` : ""})`);
  if (pre?.approach) push("🎯", "M5: zirveye yaklaşıyor (≤0.5 ATR) + hacim/genişleme — YAKLAŞIYOR");
  if (pre?.m1) push("🕐", "M1 öncü kırılımı + M5 yeşil — erken sinyal");
  if (pre?.dip) push("📈", "M5 MACD hist dip dönüşü (yeşile hazır)");
  return icons.slice(0, 8);
};

/** MACD MONITOR erişim kapısı: admin VEYA lib/macdAccess izin listesindeki kullanıcı. */
function MacdAccessGate({ children }: { children: ReactNode }) {
  const { role, username } = useAuth();
  if (canViewMacdMonitor(role, username)) return <>{children}</>;
  return (
    <main className="page-shell">
      <div className="card mt-10 flex flex-col items-center gap-4 border-neon-red/30 bg-neon-red/5 px-6 py-12 text-center">
        <p className="eyebrow">YETKİSİZ ERİŞİM</p>
        <h1 className="font-mono text-xl font-bold text-white">Bu sayfayı görüntüleme yetkiniz yok</h1>
        <p className="max-w-md text-sm text-bunker-muted">
          MACD MONITOR yalnız sistem yöneticisine ve yetkilendirilmiş kullanıcılara açıktır.
        </p>
        <a href="/" className="ui-button ui-button-primary">ANA SAYFAYA DÖN</a>
      </div>
    </main>
  );
}

export default function MacdMonitorPage() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [onlyGreen, setOnlyGreen] = useState(false);
  const [sortAlpha, setSortAlpha] = useState(false);
  const [lastAlert, setLastAlert] = useState<{ symbol: string; score: number; at: number } | null>(null);
  const [lastEarly, setLastEarly] = useState<{ symbol: string; signals: string[]; at: number } | null>(null);
  const liveStatus = useLiveStatus();

  const loadSnapshot = useCallback(async () => {
    try {
      const data = await apiFetch("/api/macd-monitor");
      setSnapshot(data as Snapshot);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSnapshot();
    const timer = window.setInterval(loadSnapshot, POLL_MS);
    return () => window.clearInterval(timer);
  }, [loadSnapshot]);

  const onLiveMessage = useCallback((message: any) => {
    if (message.type === "macd_monitor" && message.data) setSnapshot(message.data);
    if (message.type === "macd_monitor_alert" && message.data?.symbol) {
      setLastAlert({ symbol: message.data.symbol, score: Number(message.data.score) || 0, at: Date.now() / 1000 });
    }
    if (message.type === "macd_early_alert" && message.data?.symbol) {
      setLastEarly({ symbol: message.data.symbol, signals: message.data.signals || [], at: Date.now() / 1000 });
    }
  }, []);
  useLiveMessages(onLiveMessage);

  const tfs = useMemo(() => {
    const source = snapshot?.timeframes?.length ? snapshot.timeframes : TF_ORDER;
    return TF_ORDER.filter((tf) => source.includes(tf));
  }, [snapshot]);

  const rows = useMemo(() => {
    const symbols = snapshot?.symbols || {};
    const universe = snapshot?.universe?.length
      ? snapshot.universe
      : Object.keys(symbols);
    const upperQuery = query.trim().toUpperCase();

    const list = universe
      .filter((symbol) => !upperQuery || symbol.toUpperCase().includes(upperQuery))
      .map((symbol) => {
        const row = symbols[symbol];
        const tfsMap = row?.tfs || {};
        const greenCount = tfs.reduce((sum, tf) => sum + (tfsMap[tf]?.green ? 1 : 0), 0);
        return {
          symbol,
          last: row?.last ?? null,
          tfsMap,
          greenCount,
          r2: row?.r2 ?? null,
          speed: row?.speed ?? null,
          strength: row?.strength ?? null,
          tier: row?.tier ?? null,
          sigs: row?.sigs ?? null,
          cvd: row?.cvd ?? null,
          jump: row?.jump ?? null,
          pre: row?.pre ?? null,
        };
      })
      .filter((r) => !onlyGreen || r.greenCount === tfs.length);

    list.sort((a, b) =>
      sortAlpha
        ? a.symbol.localeCompare(b.symbol)
        : b.greenCount - a.greenCount || a.symbol.localeCompare(b.symbol),
    );
    return list;
  }, [snapshot, query, onlyGreen, sortAlpha, tfs]);

  const allGreenSymbols = useMemo(() => {
    const symbols = snapshot?.symbols || {};
    return (snapshot?.universe?.length ? snapshot.universe : Object.keys(symbols)).filter(
      (symbol) => tfs.length > 0 && tfs.every((tf) => symbols[symbol]?.tfs?.[tf]?.green),
    ).length;
  }, [snapshot, tfs]);

  const jumpMin = Number(snapshot?.jump_min ?? JUMP_MIN_FALLBACK);
  const jumpCount = useMemo(() => {
    const symbols = snapshot?.symbols || {};
    return (snapshot?.universe?.length ? snapshot.universe : Object.keys(symbols)).filter(
      (symbol) => Number(symbols[symbol]?.jump) >= jumpMin,
    ).length;
  }, [snapshot, jumpMin]);

  const universeCount = snapshot?.universe?.length || Object.keys(snapshot?.symbols || {}).length;
  const stale = liveStatus === "open" && snapshot?.generated_at
    && Date.now() / 1000 - snapshot.generated_at > 15;

  return (
    <MacdAccessGate>
      <main className="page-shell">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="eyebrow">CANLI MACD MONİTÖR</p>
            <h1 className="font-mono text-2xl font-bold text-white">MACD MONITOR</h1>
            <p className="mt-1 text-sm text-bunker-muted">
              Aktif sembollerin MACD histogram yönü — <b className="text-neon-green">yeşil</b> hist &gt; 0,{" "}
              <b className="text-neon-red">kırmızı</b> hist &lt; 0 (fiyat tick&apos;leriyle ~1 sn&apos;de bir tazelenir)
            </p>
          </div>
          <div className={`flex items-center gap-2 rounded-lg border px-3 py-2 font-mono text-xs ${liveStatus === "open" ? "border-neon-green/40 bg-neon-green/5 text-neon-green" : "border-yellow-300/40 bg-yellow-300/5 text-yellow-300"}`}>
            <span className={`w-2 h-2 rounded-full ${liveStatus === "open" ? "bg-neon-green animate-pulse" : "bg-yellow-300"}`} />
            {liveStatus === "open" ? "CANLI · WS BAĞLI" : "WS KAPALI · REST YEDEK"}
          </div>
        </div>

        {lastAlert && (
          <div className="mt-3 flex items-center gap-2 rounded-lg border border-yellow-400/50 bg-yellow-400/10 px-3 py-2 font-mono text-xs text-yellow-300">
            <span>🚀 SIRÇRAMA ALARMI</span>
            <b className="text-white">{lastAlert.symbol}</b>
            <span>skor {lastAlert.score}/100</span>
            <span className="text-yellow-300/70">· {fmtTime(lastAlert.at)}</span>
          </div>
        )}

        {lastEarly && (
          <div className="mt-3 flex flex-wrap items-center gap-2 rounded-lg border border-sky-400/50 bg-sky-400/10 px-3 py-2 font-mono text-xs text-sky-300">
            <span>🌱 ERKEN SİNYAL — YAKLAŞIYOR</span>
            <b className="text-white">{lastEarly.symbol}</b>
            <span className="flex flex-wrap gap-1">
              {lastEarly.signals.map((signal) => (
                <span key={signal} className="rounded border border-sky-400/40 bg-sky-400/10 px-1.5 py-0.5 text-[10px]">
                  {EARLY_LABEL[signal] ?? signal}
                </span>
              ))}
            </span>
            <span className="text-sky-300/70">· {fmtTime(lastEarly.at)}</span>
          </div>
        )}

        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <div className="card">
            <p className="eyebrow">AKTİF SEMBOL</p>
            <p className="mt-1 font-mono text-2xl font-bold text-white">{universeCount}</p>
          </div>
          <div className="card">
            <p className="eyebrow">TAM YEŞİL ({tfs.length}/{tfs.length})</p>
            <p className="mt-1 font-mono text-2xl font-bold text-neon-green">{allGreenSymbols}</p>
          </div>
          <div className="card">
            <p className="eyebrow">SIRÇRAMA ≥ {jumpMin}</p>
            <p className="mt-1 font-mono text-2xl font-bold text-neon-green">{jumpCount}</p>
          </div>
          <div className="card">
            <p className="eyebrow">SON GÜNCELLEME</p>
            <p className="mt-1 font-mono text-lg font-bold text-white">{fmtTime(snapshot?.generated_at)}</p>
          </div>
          <div className="card">
            <p className="eyebrow">VERİ KAPSAMI</p>
            <p className="mt-1 font-mono text-lg font-bold text-bunker-muted">{tfs.map((tf) => TF_LABELS[tf]).join(" · ")}</p>
          </div>
        </div>

        <div className="card mt-4">
          <div className="flex flex-wrap items-center gap-3">
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Sembol ara (örn. BTC)…"
              className="input w-56"
              aria-label="Sembol ara"
            />
            <label className="flex cursor-pointer items-center gap-2 font-mono text-xs text-bunker-muted">
              <input type="checkbox" checked={onlyGreen} onChange={(event) => setOnlyGreen(event.target.checked)} className="accent-neon-green" />
              Sadece {tfs.length}/{tfs.length} yeşil
            </label>
            <label className="flex cursor-pointer items-center gap-2 font-mono text-xs text-bunker-muted">
              <input type="checkbox" checked={sortAlpha} onChange={(event) => setSortAlpha(event.target.checked)} className="accent-neon-green" />
              Alfabetik sırala
            </label>
            <button type="button" onClick={loadSnapshot} className="ui-button ui-button-secondary ml-auto">YENİLE</button>
          </div>

          {stale && (
            <p className="mt-3 rounded-lg border border-yellow-300/40 bg-yellow-300/5 px-3 py-2 font-mono text-xs text-yellow-300">
              Son veri 15 sn&apos;den eski — WS mesajları gelmiyor olabilir.
            </p>
          )}
          {error && (
            <p className="mt-3 rounded-lg border border-neon-red/40 bg-neon-red/5 px-3 py-2 font-mono text-xs text-neon-red">
              Veri alınamadı: {error}
            </p>
          )}

          <div className="mt-4 overflow-x-auto">
            {loading && !snapshot ? (
              <p className="py-10 text-center font-mono text-sm text-bunker-muted">Veri bekleniyor… (ilk M3/M30 serileri ısınıyor)</p>
            ) : rows.length === 0 ? (
              <p className="py-10 text-center font-mono text-sm text-bunker-muted">
                {universeCount === 0 ? "Henüz aktif sembol yok. Activity taraması tamamlanınca liste dolar." : "Filtreye uyan sembol yok."}
              </p>
            ) : (
              <table className="w-full border-collapse font-mono text-sm">
                <thead>
                  <tr className="border-b border-bunker-800 text-left text-[11px] text-bunker-muted">
                    <th className="px-3 py-2">SEMBOL</th>
                    <th className="px-3 py-2 text-right">FİYAT</th>
                    {tfs.map((tf) => (
                      <th key={tf} className="px-3 py-2 text-center">{TF_LABELS[tf]}</th>
                    ))}
                    <th className="px-3 py-2 text-center" title={`${tfs.length} zaman diliminde yeşil sayısı`}>YEŞİL</th>
                    <th className="px-3 py-2 text-center" title="Trend gücü: 20 barlık lineer regresyon — R² (düzenlilik) × eğim/bar-aralığı (hız); evren içinde 0-10 normalize">GÜÇ · 0-10</th>
                    <th className="px-3 py-2 text-center" title={`Sıçrama adayı skoru (0-100): trend gücü + MACD yeşil + M5/M15 kırılım, volatilite genişlemesi, hacim ve agresör teyidi. ≥ ${jumpMin} = aday (alarm/push ayarlardan yönetilir)`}>SIRÇRAMA</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.symbol} className="border-b border-bunker-800/60 transition-colors hover:bg-bunker-800/40">
                      <td className="px-3 py-2">
                        <SymbolLink symbol={row.symbol} className="font-bold text-white hover:text-neon-green" />
                      </td>
                      <td className="px-3 py-2 text-right text-bunker-muted">{fmtPrice(row.last)}</td>
                      {tfs.map((tf) => {
                        const cell = row.tfsMap[tf];
                        return (
                          <td key={tf} className="px-3 py-2 text-center">
                            {cell ? (
                              <span
                                title={`histogram: ${histShort(cell.hist)}`}
                                className={`inline-flex min-w-[2.25rem] items-center justify-center rounded-md border px-2 py-1 text-xs font-bold ${
                                  cell.green ? arrowShade(row.tier) : "border-neon-red/40 bg-neon-red/10 text-neon-red"
                                }`}
                              >
                                {cell.green ? "▲" : "▼"}
                              </span>
                            ) : (
                              <span className="text-bunker-muted/60" title="Yetersiz mum verisi">—</span>
                            )}
                          </td>
                        );
                      })}
                      <td className="px-3 py-2 text-center">
                        <span
                          className={`inline-flex min-w-[2.25rem] items-center justify-center rounded-md border px-2 py-1 text-xs font-bold ${
                            row.greenCount === tfs.length && tfs.length > 0
                              ? "border-neon-green/50 bg-neon-green/15 text-neon-green"
                              : row.greenCount === 0
                                ? "border-neon-red/50 bg-neon-red/15 text-neon-red"
                                : "border-bunker-600 bg-bunker-900 text-white"
                          }`}
                        >
                          {tfs.length > 0 ? `${row.greenCount}/${tfs.length}` : "—"}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-center">
                        {row.strength != null && row.tier ? (
                          <span
                            title={`Trend gücü: R² ${row.r2 ?? "—"} · hız ${row.speed ?? "—"} (20 barlık lineer regresyon; evren içinde 0-10 normalize)`}
                            className={`inline-flex items-center justify-center gap-1 rounded-md border px-2 py-1 text-xs font-bold ${strengthChip(row.tier)}`}
                          >
                            {row.strength.toFixed(1)}
                            <span className="hidden lg:inline text-[9px] tracking-wide">{TIER_LABEL[row.tier]}</span>
                          </span>
                        ) : (
                          <span className="text-bunker-muted/60" title="Trend verisi yok (mum serisi ısınana kadar)">—</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-center">
                        {row.jump != null ? (
                          <span className="inline-flex items-center justify-center gap-1.5">
                            <span
                              title={`Sıçrama skoru ${row.jump}/100 (≥ ${jumpMin} aday)`}
                              className={`inline-flex min-w-[2.5rem] items-center justify-center rounded-md border px-2 py-1 text-xs font-bold ${jumpChip(row.jump, jumpMin)}`}
                            >
                              {row.jump}
                            </span>
                            {(() => {
                              const icons = jumpIcons(row.sigs?.["5m"] ?? null, row.sigs?.["15m"] ?? null, row.cvd ?? null, row.pre ?? null);
                              return icons.length > 0 ? (
                                <span className="flex gap-0.5 text-[11px] leading-none">
                                  {icons.map((item, index) => (
                                    <span key={`${item.icon}-${index}`} title={item.title}>{item.icon}</span>
                                  ))}
                                </span>
                              ) : null;
                            })()}
                          </span>
                        ) : (
                          <span className="text-bunker-muted/60" title="Sinyal verisi yok">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
          <p className="mt-3 font-mono text-[10px] text-bunker-muted/70">
            Hesaplama: kapanmış mum serisine canlı fiyat eklenerek MACD (12, 26, 9). M3/M30 serileri REST ile aralıklı tazelenir.
          </p>
          <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[10px] text-bunker-muted/70">
            <span>▲ yeşil tonu → trend gücü:</span>
            <span className="inline-flex items-center gap-1"><span className="inline-block h-3 w-4 rounded border border-neon-green/60 bg-neon-green/25" /> GÜÇLÜ</span>
            <span className="inline-flex items-center gap-1"><span className="inline-block h-3 w-4 rounded border border-neon-green/40 bg-neon-green/10" /> NORMAL</span>
            <span className="inline-flex items-center gap-1"><span className="inline-block h-3 w-4 rounded border border-neon-green/30 bg-neon-green/5" /> ZAYIF</span>
            <span className="text-bunker-muted/50">· GÜÇ: 20 barlık lineer regresyon — R² (trend düzenliliği) × eğim/bar-aralığı (hız); evren içinde 0-10 normalize.</span>
            <span className="text-bunker-muted/50">Ağırlıklar: M5·M15 önde, H1/M30 orta, M3/M1 düşük.</span>
            <span className="text-bunker-muted/50">SIRÇRAMA ikonları: 🚀 20-bar kırılım · ⚡ genişleme · 🧲 sıkışma · 🔥 hacim · 🐋 alıcı agresör.</span>
          </p>
        </div>
      </main>
    </MacdAccessGate>
  );
}
