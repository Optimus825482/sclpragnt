"use client";

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import SymbolLink from "../components/SymbolLink";
import { useAuth } from "../lib/auth";
import { canViewMacdMonitor } from "../lib/macdAccess";
import { useLiveMessages, useLiveStatus } from "../lib/liveSocket";
import { apiFetch } from "../lib/api";
import { mergeMacdDelta } from "../lib/macdSnapshot";

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
// Aşama 2 tanımlayıcı alanlar — DAVRANIŞ DEĞİL, ölçüm/teşhis içindir.
type PreDetail = {
  proximity?: number | null;
  gap_atr?: number | null;
  m1_margin_atr?: number | null;
  dip_hist?: number | null;
  dip_delta?: number | null;
  squeeze_now?: boolean;
  expand_now?: boolean;
  transition?: boolean;
  squeeze_prev?: boolean;
  m15_squeeze_now?: boolean;
  m15_transition?: boolean;
  as_of?: Record<string, number | null>;
};
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
  pre_detail?: PreDetail | null;
  pre_key?: string[] | null;
  early_score?: number | null;
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
const ALERT_POLL_MS = 60_000;

// C3 kanıt katmanı: alarmın gerçekleşen 5m/15m/30m sonucu (paper-only).
type MacdAlert = {
  id: number;
  created_at: number;
  symbol: string;
  kind: string;
  score: number | null;
  jump_min: number | null;
  price: number | null;
  outcome_5m_pct: number | null;
  outcome_15m_pct: number | null;
  outcome_30m_pct: number | null;
  outcome_state: string;
};
type AlertHorizon = {
  n: number;
  avg_pct: number;
  hit_rate: number;
  avg_lift?: number;
  base_hit_rate?: number;
  hit_lift?: number;
};
type AlertKindStats = {
  n: number;
  avg_score?: number;
  avg_early_score?: number;
  avg_mfe?: number;
  avg_mae?: number;
} & Record<string, unknown>;
type AlertBaseline = { buckets: number; avg_pct: number; hit_rate: number; symbols: number };
type AlertStats = {
  days?: number;
  kinds?: Record<string, AlertKindStats>;
  precursors?: Record<string, AlertKindStats>;
  pending?: number;
  baseline?: Record<string, AlertBaseline>;
};
type EventStudy = {
  kind?: string;
  precursor?: string | null;
  n?: number;
  offsets?: number[];
  avg_path?: Array<number | null>;
  avg_mfe?: number | null;
  avg_mae?: number | null;
};

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

// Alarm sonucu: kâr yeşil, zarar kırmızı (global renk kuralı).
const fmtPct = (value: number | null | undefined) => {
  if (value == null || !Number.isFinite(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(3)}%`;
};
const pctClass = (value: number | null | undefined) =>
  value == null || !Number.isFinite(value)
    ? "text-bunker-muted/60"
    : value > 0
      ? "text-neon-green"
      : value < 0
        ? "text-neon-red"
        : "text-bunker-muted";
const KIND_LABEL: Record<string, string> = { jump: "SIRÇRAMA", early: "ERKEN" };
// Erken alarm öncüleri. Anahtarlar, BACKEND'İN KAYIT ETTİĞİ etiketlerle
// birebir aynı olmalıdır (`_maybe_fire_early_alert` → signals listesi);
// aksi halde istatistik satırları ham `m1_breakout` yazar ve öncü filtresi
// (olay çalışması) hiç eşleşmez.
const PRECURSOR_LABEL: Record<string, string> = {
  approach: "M5 yaklaşma",
  m1_breakout: "M1 kırılım",
  macd_dip_turn: "MACD dip dönüşü",
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

const jumpIcons = (m5: TfSignals | null | undefined, m15: TfSignals | null | undefined, cvd: CvdInfo | null | undefined, pre: PreSignals | null | undefined, detail?: PreDetail | null) => {
  const icons: { icon: string; title: string }[] = [];
  const push = (icon: string, title: string) => icons.push({ icon, title });
  if (m5?.break) push("🚀", "M5: 20-bar yüksek kırılımı");
  if (m15?.break) push("🚀", "M15: 20-bar yüksek kırılımı");
  if (m5?.state === "expand") push("⚡", "M5: volatilite genişlemesi");
  if (m15?.state === "expand") push("⚡", "M15: volatilite genişlemesi");
  if (m5?.state === "squeeze") push("🧲", "M5: sıkışma — yay hazır");
  if (m15?.state === "squeeze") push("🧲", "M15: sıkışma — yay hazır");
  if (detail?.transition) push("🎯", "M5: sıkışma → genişleme GEÇİŞİ (yay boşandı) — tanımlayıcı, karar değil");
  if (m5?.vol) push("🔥", "M5: hacim patlaması (>1.5× ort.)");
  if (m15?.vol) push("🔥", "M15: hacim patlaması (>1.5× ort.)");
  if (cvd?.buy_dominant) push("🐋", `Agresör alıcı baskın (oran ${Number(cvd.buy_ratio ?? 0).toFixed(2)}${cvd.whale_net ? ` · balina ${cvd.whale_net > 0 ? "+" : ""}${cvd.whale_net}` : ""})`);
  if (pre?.approach) {
    const proximity = detail?.proximity;
    const age = detail?.as_of?.approach;
    const ageText = age ? ` · baz ${Math.max(0, Math.round(Date.now() / 1000 - age))} sn önce` : "";
    push("🎯", `M5: zirveye yaklaşıyor (gap ${detail?.gap_atr ?? "—"} ATR, yakınlık ${proximity == null ? "—" : proximity.toFixed(2)}) + hacim/genişleme${ageText}`);
  }
  if (pre?.m1) push("🕐", `M1 öncü kırılımı + M5 yeşil (kırılım payı ${detail?.m1_margin_atr ?? "—"} ATR)`);
  if (pre?.dip) push("📈", `M5 MACD hist dip dönüşü (hist ${detail?.dip_hist ?? "—"}, artış ${detail?.dip_delta ?? "—"} — yeşile hazır)`);
  return icons.slice(0, 9);
};

/** Erken sinyal olgunluk rozeti: early_score + öncü kimliği + yakınlık (tanımlayıcı). */
const earlyChip = (score: number | null | undefined) =>
  score == null
    ? "border-bunker-600 bg-bunker-900 text-bunker-muted"
    : score >= 60
      ? "border-sky-400/60 bg-sky-400/15 text-sky-300"
      : score >= 30
        ? "border-sky-400/40 bg-sky-400/10 text-sky-300/90"
        : "border-bunker-600 bg-bunker-900 text-bunker-muted";
const PRECURSOR_SHORT: Record<string, string> = { approach: "YAK", m1: "M1K", dip: "DİP" };

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
  // C3 kanıt katmanı: son alarmlar + isabet özeti (panel açılınca görünür)
  const [alerts, setAlerts] = useState<MacdAlert[]>([]);
  const [alertStats, setAlertStats] = useState<AlertStats | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  // A3 olay çalışması: seçili öncü için alarm etrafındaki ortalama getiri yolu.
  const [studyPrecursor, setStudyPrecursor] = useState("");
  const [study, setStudy] = useState<EventStudy | null>(null);
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

  const loadAlerts = useCallback(async () => {
    try {
      const data = await apiFetch("/api/macd-monitor/alerts?limit=100");
      setAlerts((data?.alerts as MacdAlert[]) || []);
      setAlertStats((data?.stats as AlertStats) || null);
    } catch {
      // Kanıt paneli yardımcıdır; hata ana görünümü bozmasın.
    }
  }, []);

  useEffect(() => {
    loadSnapshot();
    const timer = window.setInterval(loadSnapshot, POLL_MS);
    return () => window.clearInterval(timer);
  }, [loadSnapshot]);

  useEffect(() => {
    loadAlerts();
    const timer = window.setInterval(loadAlerts, ALERT_POLL_MS);
    return () => window.clearInterval(timer);
  }, [loadAlerts]);

  // A3: olay çalışması — öncü seçimi değiştiğinde yeniden çekilir.
  useEffect(() => {
    let cancelled = false;
    const query = studyPrecursor ? `&precursor=${encodeURIComponent(studyPrecursor)}` : "";
    apiFetch(`/api/macd-monitor/event-study?days=14&kind=early&limit=200${query}`)
      .then((data) => {
        if (!cancelled) setStudy((data as EventStudy) || null);
      })
      .catch(() => {
        if (!cancelled) setStudy(null);
      });
    return () => {
      cancelled = true;
    };
  }, [studyPrecursor]);

  const onLiveMessage = useCallback((message: any) => {
    if (message.type === "macd_monitor" && message.data) setSnapshot(message.data as Snapshot);
    // Delta yayın: yalnızca değişen sembol satırları gelir, mevcut görünüme
    // birleştirilir (tek kaynak: mergeMacdDelta). Tam yayın (her 5 pass)
    // kendini onarma işlevini görür.
    if (message.type === "macd_monitor_delta" && message.data?.symbols) {
      setSnapshot((prev) => mergeMacdDelta<Snapshot>(prev, message.data));
    }
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
          pre_any: row?.pre_any ?? null,
          pre_detail: row?.pre_detail ?? null,
          pre_key: row?.pre_key ?? null,
          early_score: row?.early_score ?? null,
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
  // Veri tazeliği: WS kapalıyken de bayat veri uyarılmalı (A11). WS açıkken
  // akış ~1 sn olduğundan 15 sn, REST yedeğinde poll 30 sn olduğundan 45 sn.
  const dataAgeSec = snapshot?.generated_at
    ? Math.max(0, Date.now() / 1000 - snapshot.generated_at)
    : null;
  const staleAfterSec = liveStatus === "open" ? 15 : 45;
  const stale = dataAgeSec != null && dataAgeSec > staleAfterSec;
  const staleLabel = `${Math.round(dataAgeSec ?? 0)} sn`;

  // İsabet özeti: alarm türü + ERKEN ÖNCÜ bazında satırlar.
  // Öncü kırılımı, "approach / m1 / dip öncülerinden hangisi işe yarıyor?"
  // sorusunu veriyle cevaplar (eşik/ağırlık ayarının önkoşulu).
  // Karar metriği LIFT'tir: avg_pct tek başına iyi/kötü demez, evren tabanına
  // göre fark gerekir (A2).
  const statRows = useMemo(() => {
    const out: Array<{
      group: string;
      label: string;
      h: string;
      n: number;
      avg: number;
      hit: number;
      lift: number | null;
      hitLift: number | null;
      mfe: number | null;
      mae: number | null;
    }> = [];
    const push = (group: string, table?: Record<string, AlertKindStats>) => {
      Object.entries(table || {}).forEach(([name, entry]) => {
        ["5m", "15m", "30m"].forEach((h) => {
          const slot = entry[h] as AlertHorizon | undefined;
          if (slot && slot.n > 0) {
            out.push({
              group,
              label: KIND_LABEL[name] ?? PRECURSOR_LABEL[name] ?? name,
              h,
              n: slot.n,
              avg: slot.avg_pct,
              hit: slot.hit_rate,
              lift: slot.avg_lift ?? null,
              hitLift: slot.hit_lift ?? null,
              mfe: entry.avg_mfe ?? null,
              mae: entry.avg_mae ?? null,
            });
          }
        });
      });
    };
    push("TÜR", alertStats?.kinds);
    push("ÖNCÜ", alertStats?.precursors);
    return out;
  }, [alertStats]);

  const baselineRows = useMemo(
    () =>
      ["5m", "15m", "30m"]
        .map((h) => ({ h, ...(alertStats?.baseline?.[h] as AlertBaseline | undefined) }))
        .filter((row): row is { h: string } & AlertBaseline => Boolean(row.buckets)),
    [alertStats],
  );

  // Olay yolu: en kötü/en iyi uç için ortak ölçek (basit çubuk gösterimi).
  const studyScale = useMemo(() => {
    const values = (study?.avg_path || []).filter((value): value is number => value != null);
    return values.length ? Math.max(0.05, ...values.map((value) => Math.abs(value))) : 1;
  }, [study]);

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
              Son veri {staleLabel} önce geldi ({staleAfterSec} sn eşiği) —{" "}
              {liveStatus === "open" ? "WS mesajları gelmiyor olabilir." : "WS kapalı, REST yedeği gecikmiş olabilir."}
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
                    <th className="px-3 py-2 text-center" title="ERKEN SİNYAL olgunluğu (0-100, TANIMLAYICI — eşik değildir): öncü sayısı + zirveye yakınlık + alıcı agresör + üst-TF yeşil hizası. Sıralama/teşhis içindir.">ERKEN</th>
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
                              const icons = jumpIcons(row.sigs?.["5m"] ?? null, row.sigs?.["15m"] ?? null, row.cvd ?? null, row.pre ?? null, row.pre_detail ?? null);
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
                      <td className="px-3 py-2 text-center">
                        {row.pre_any ? (
                          <span className="inline-flex flex-col items-center gap-0.5">
                            <span
                              title={`Erken sinyal olgunluğu ${row.early_score ?? "—"}/100 — TANIMLAYICI (eşik değildir). Öncüler: ${(row.pre_key || []).map((key) => PRECURSOR_SHORT[key] ?? key).join(" + ") || "—"}`}
                              className={`inline-flex min-w-[2.5rem] items-center justify-center rounded-md border px-2 py-1 text-xs font-bold ${earlyChip(row.early_score)}`}
                            >
                              {row.early_score ?? "—"}
                            </span>
                            <span className="flex gap-0.5 font-mono text-[9px]">
                              {(row.pre_key || []).map((key) => (
                                <span
                                  key={key}
                                  className={`rounded border px-1 ${
                                    key === "approach"
                                      ? "border-sky-400/40 bg-sky-400/10 text-sky-300"
                                      : key === "m1"
                                        ? "border-yellow-300/40 bg-yellow-300/10 text-yellow-300"
                                        : "border-neon-green/40 bg-neon-green/10 text-neon-green"
                                  }`}
                                >
                                  {PRECURSOR_SHORT[key] ?? key}
                                </span>
                              ))}
                              {row.pre_detail?.transition && (
                                <span className="rounded border border-neon-green/40 bg-neon-green/10 px-1 text-neon-green" title="M5 sıkışma → genişleme geçişi (tanımlayıcı)">
                                  ⇗
                                </span>
                              )}
                            </span>
                          </span>
                        ) : (
                          <span className="text-bunker-muted/60" title="Erken öncü yok">—</span>
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

        {/* C3 KANIT PANELİ — alarm → gerçekleşen sonuç (paper-only ölçüm) */}
        <div className="card mt-4">
          <button
            type="button"
            onClick={() => setShowHistory((value) => !value)}
            className="flex w-full items-center justify-between gap-3 text-left"
          >
            <div>
              <p className="eyebrow">ALARM GEÇMİŞİ &amp; İSABET</p>
              <p className="mt-1 font-mono text-xs text-bunker-muted">
                Üretilen her alarm 5m/15m/30m ileri getirisiyle ölçülür — eşik/ağırlık ayarı bu kanıtla yapılır.
                {alertStats?.pending != null ? ` Bekleyen: ${alertStats.pending}.` : ""}
              </p>
            </div>
            <span className="ui-button ui-button-secondary shrink-0">{showHistory ? "GİZLE" : "GÖSTER"}</span>
          </button>

          {showHistory && (
            <div className="mt-4 space-y-4">
              {baselineRows.length > 0 && (
                <div className="flex flex-wrap items-center gap-2 rounded-lg border border-bunker-700 bg-bunker-900/50 px-3 py-2 font-mono text-[11px] text-bunker-muted">
                  <span className="text-white">EVREN TABANI (aynı 5m kovası):</span>
                  {baselineRows.map((row) => (
                    <span key={row.h} className="rounded border border-bunker-600 px-1.5 py-0.5">
                      {row.h} ort <b className={pctClass(row.avg_pct)}>{fmtPct(row.avg_pct)}</b>{" "}
                      pozitif <b className="text-white">{(row.hit_rate * 100).toFixed(1)}%</b>
                    </span>
                  ))}
                  <span className="text-bunker-muted/70">
                    · <b className="text-white">LIFT</b> = alarm getirisi − taban. Karar metriği lift'tir.
                  </span>
                </div>
              )}

              {statRows.length > 0 ? (
                <div className="overflow-x-auto">
                  <table className="w-full border-collapse font-mono text-sm">
                    <thead>
                      <tr className="border-b border-bunker-800 text-left text-[11px] text-bunker-muted">
                        <th className="px-3 py-2">GRUP</th>
                        <th className="px-3 py-2">AD</th>
                        <th className="px-3 py-2 text-center">UFUK</th>
                        <th className="px-3 py-2 text-right">ÖRNEK</th>
                        <th className="px-3 py-2 text-right">ORT. GETİRİ</th>
                        <th className="px-3 py-2 text-right">LIFT</th>
                        <th className="px-3 py-2 text-right">İSABET (pozitif)</th>
                        <th className="px-3 py-2 text-right">İSABET LİFT</th>
                        <th className="px-3 py-2 text-right">MFE / MAE</th>
                      </tr>
                    </thead>
                    <tbody>
                      {statRows.map((row) => {
                        const mfe = row.mfe;
                        const mae = row.mae;
                        return (
                          <tr key={`${row.group}-${row.label}-${row.h}`} className="border-b border-bunker-800/60">
                            <td className="px-3 py-2">
                              <span className={`rounded border px-1.5 py-0.5 text-[10px] ${
                                row.group === "ÖNCÜ"
                                  ? "border-sky-400/40 bg-sky-400/10 text-sky-300"
                                  : "border-bunker-600 bg-bunker-900 text-bunker-muted"
                              }`}>
                                {row.group}
                              </span>
                            </td>
                            <td className="px-3 py-2 text-white">{row.label}</td>
                            <td className="px-3 py-2 text-center text-bunker-muted">{row.h}</td>
                            <td className="px-3 py-2 text-right text-bunker-muted">{row.n}</td>
                            <td className={`px-3 py-2 text-right font-bold ${pctClass(row.avg)}`}>{fmtPct(row.avg)}</td>
                            <td className={`px-3 py-2 text-right font-bold ${row.lift == null ? "text-bunker-muted/60" : pctClass(row.lift)}`}>
                              {row.lift == null ? "—" : fmtPct(row.lift)}
                            </td>
                            <td className="px-3 py-2 text-right text-white">{(row.hit * 100).toFixed(1)}%</td>
                            <td className={`px-3 py-2 text-right ${row.hitLift == null ? "text-bunker-muted/60" : pctClass(row.hitLift)}`}>
                              {row.hitLift == null ? "—" : `${(row.hitLift * 100).toFixed(1)}%`}
                            </td>
                            <td className="px-3 py-2 text-right text-bunker-muted">
                              {mfe == null && mae == null ? "—" : (
                                <>
                                  <span className={pctClass(mfe)}>{mfe == null ? "—" : fmtPct(mfe)}</span>
                                  {" / "}
                                  <span className={pctClass(mae)}>{mae == null ? "—" : fmtPct(mae)}</span>
                                </>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="font-mono text-xs text-bunker-muted">
                  Henüz sonucu kesinleşmiş alarm yok (alarm oluşup 30 dk geçince satırlar dolar).
                </p>
              )}

              {/* A3 OLAY ÇALIŞMASI — alarm etrafında ortalama getiri yolu */}
              <div className="rounded-lg border border-bunker-700 bg-bunker-900/40 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <p className="eyebrow">OLAY ÇALIŞMASI (LEAD TIME)</p>
                    <p className="mt-1 font-mono text-[11px] text-bunker-muted">
                      Alarm etrafında ortalama getiri yolu — &quot;daha erken&quot; iddiası ancak bu ölçülürse anlamlıdır.
                    </p>
                  </div>
                  <select
                    value={studyPrecursor}
                    onChange={(event) => setStudyPrecursor(event.target.value)}
                    className="input w-44 font-mono text-xs"
                    aria-label="Öncü seç"
                  >
                    <option value="">TÜM ÖNCÜLER</option>
                    {Object.entries(PRECURSOR_LABEL).map(([key, label]) => (
                      <option key={key} value={key}>{label}</option>
                    ))}
                  </select>
                </div>
                {study && (study.n || 0) > 0 ? (
                  <div className="mt-3 space-y-2">
                    <div className="flex flex-wrap items-end gap-1">
                      {(study.offsets || []).map((offset, index) => {
                        const value = study.avg_path?.[index] ?? null;
                        const height = value == null
                          ? 2
                          : Math.max(2, Math.round((Math.abs(value) / studyScale) * 40));
                        return (
                          <div key={offset} className="flex w-14 flex-col items-center gap-1">
                            <span className={`font-mono text-[10px] ${pctClass(value)}`}>
                              {value == null ? "—" : `${value > 0 ? "+" : ""}${value.toFixed(2)}`}
                            </span>
                            <div
                              className={`w-6 rounded-sm ${
                                value == null ? "bg-bunker-700" : value >= 0 ? "bg-neon-green/60" : "bg-neon-red/60"
                              }`}
                              style={{ height: `${height}px` }}
                              title={`t${offset >= 0 ? "+" : ""}${offset} dk: ${value == null ? "veri yok" : `${value.toFixed(3)}%`}`}
                            />
                            <span className="font-mono text-[10px] text-bunker-muted">
                              t{offset >= 0 ? "+" : ""}{offset}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                    <p className="font-mono text-[11px] text-bunker-muted">
                      n={study.n} · ortalama <b className={pctClass(study.avg_mfe)}>MFE {study.avg_mfe == null ? "—" : fmtPct(study.avg_mfe)}</b>{" "}
                      / <b className={pctClass(study.avg_mae)}>MAE {study.avg_mae == null ? "—" : fmtPct(study.avg_mae)}</b>
                      {" · "}t0 = alarm anı (kapanmış 5m mumlarından; canlı fiyat kullanılmaz).
                    </p>
                  </div>
                ) : (
                  <p className="mt-3 font-mono text-[11px] text-bunker-muted">
                    Bu seçim için yeterli doldurulmuş kayıt yok.
                  </p>
                )}
              </div>

              <div className="overflow-x-auto">
                <table className="w-full border-collapse font-mono text-sm">
                  <thead>
                    <tr className="border-b border-bunker-800 text-left text-[11px] text-bunker-muted">
                      <th className="px-3 py-2">ZAMAN</th>
                      <th className="px-3 py-2">SEMBOL</th>
                      <th className="px-3 py-2">TÜR</th>
                      <th className="px-3 py-2 text-right">SKOR</th>
                      <th className="px-3 py-2 text-right">5m</th>
                      <th className="px-3 py-2 text-right">15m</th>
                      <th className="px-3 py-2 text-right">30m</th>
                    </tr>
                  </thead>
                  <tbody>
                    {alerts.length === 0 ? (
                      <tr>
                        <td colSpan={7} className="px-3 py-6 text-center text-bunker-muted">
                          Alarm kaydı yok.
                        </td>
                      </tr>
                    ) : (
                      alerts.map((alert) => (
                        <tr key={alert.id} className="border-b border-bunker-800/60 transition-colors hover:bg-bunker-800/40">
                          <td className="px-3 py-2 text-bunker-muted">
                            {new Date(alert.created_at * 1000).toLocaleString("tr-TR")}
                          </td>
                          <td className="px-3 py-2">
                            <SymbolLink symbol={alert.symbol} className="font-bold text-white hover:text-neon-green" />
                          </td>
                          <td className="px-3 py-2 text-bunker-muted">{KIND_LABEL[alert.kind] ?? alert.kind}</td>
                          <td className="px-3 py-2 text-right text-white">{alert.score ?? "—"}</td>
                          <td className={`px-3 py-2 text-right ${pctClass(alert.outcome_5m_pct)}`}>{fmtPct(alert.outcome_5m_pct)}</td>
                          <td className={`px-3 py-2 text-right ${pctClass(alert.outcome_15m_pct)}`}>{fmtPct(alert.outcome_15m_pct)}</td>
                          <td className={`px-3 py-2 text-right ${pctClass(alert.outcome_30m_pct)}`}>{fmtPct(alert.outcome_30m_pct)}</td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
              <p className="font-mono text-[10px] text-bunker-muted/70">
                Sonuçlar <b>kapanmış 5m mumlarından</b> hesaplanır; canlı fiyat kullanılmaz. Kayıtlar yalnızca ölçüm içindir,
                sinyal davranışını değiştirmez (paper-only).
              </p>
            </div>
          )}
        </div>
      </main>
    </MacdAccessGate>
  );
}
