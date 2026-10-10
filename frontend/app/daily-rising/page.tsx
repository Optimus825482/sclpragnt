"use client";

// Günlük Yükseliş Adayları (2026-10-10)
//
// İki bölüm:
//  1) MANUEL TARAMA: "Tara" → günlük momentum adayları listelenir; kullanıcı
//     onaylarsa KENDİ takip listesine ekler (username bazlı).
//  2) TAKİP LİSTEM: kullanıcının eklediği adaylar; öneri fiyatı ↔ anlık fiyat,
//     tavan (beklenen maksimum) ve gerçekleşen maksimum (MFE).
//  3) SİSTEM ADAYLARI: otomatik 11:30 taramasının kalıcı kayıtları.
//
// Veri kaynakları:
//   POST /api/daily-rising/manual-scan
//   GET/POST/DELETE /api/daily-rising/watchlist
//   GET /api/daily-rising/state

import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE, apiRequest } from "../lib/api";
import { formatPrice, formatNumber2, toMs, fmtDateTime } from "../lib/format";
import { Card, Badge, Button, StatCard } from "../components/ui";

type Cand = {
  symbol: string;
  price: number | null;
  target_pct: number | null;
  ceiling_pct: number | null;
  ceiling_price: number | null;
  velocity_score: number | null;
  panel_score: number | null;
  ret_8h_pct: number | null;
  adx_14: number | null;
  slope_15m: number | null;
  atr_pct_15m: number | null;
  target_price: number | null;
  target_probability: number | null;
};

type Watch = {
  symbol: string;
  added_at: number | null;
  entry_price: number | null;
  current_price: number | null;
  change_pct: number | null;
  ceiling_pct: number | null;
  ceiling_price: number | null;
  velocity_score: number | null;
  outcome_status: string | null;
  mfe_pct: number | null;
  mae_pct: number | null;
  hit_ceiling: boolean | null;
  target_price: number | null;
  target_probability: number | null;
  atr_pct_live: number | null;
};

type WatchStats = {
  total: number;
  measured: number;
  ceiling_hits: number;
  hit_rate: number | null;
  avg_mfe_pct: number | null;
  max_mfe_pct: number | null;
  positive: number;
};

type Row = {
  symbol: string;
  created_at: number | null;
  entry_price: number | null;
  current_price: number | null;
  change_pct: number | null;
  ceiling_pct: number | null;
  ceiling_price: number | null;
  status: string | null;
  mfe_pct: number | null;
};

type Stats = {
  total: number;
  hit_rate: number | null;
  avg_mfe_pct: number | null;
  max_mfe_pct: number | null;
};

const REFRESH_MS = 30_000;

function pctTone(v: number | null | undefined): string {
  if (v === null || v === undefined) return "text-bunker-muted";
  if (v > 0.5) return "text-neon-green";
  if (v < -0.5) return "text-neon-red";
  return "text-bunker-muted";
}

function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(Number(v))) return "—";
  const n = Number(v);
  return `${n > 0 ? "+" : ""}${formatNumber2(n)}%`;
}

export default function DailyRisingPage() {
  const [cands, setCands] = useState<Cand[]>([]);
  const [watch, setWatch] = useState<Watch[]>([]);
  const [rows, setRows] = useState<Row[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [watchStats, setWatchStats] = useState<WatchStats | null>(null);
  const [scanning, setScanning] = useState(false);
  const [scanned, setScanned] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const loadState = useCallback(async () => {
    try {
      const res = await apiRequest(`${API_BASE}/api/daily-rising/state`, { cache: "no-store" });
      if (res.ok) {
        const d = await res.json();
        setRows(Array.isArray(d?.candidates) ? d.candidates : []);
        setStats(d?.stats ?? null);
        setUpdatedAt(Date.now());
      }
    } catch { /* sessiz */ } finally { setLoading(false); }
  }, []);

  const loadWatch = useCallback(async () => {
    try {
      const res = await apiRequest(`${API_BASE}/api/daily-rising/watchlist`, { cache: "no-store" });
      if (res.ok) {
        const d = await res.json();
        setWatch(Array.isArray(d?.watchlist) ? d.watchlist : []);
        setWatchStats(d?.stats ?? null);
      }
    } catch { /* sessiz */ }
  }, []);

  const refresh = useCallback(async () => { await Promise.all([loadState(), loadWatch()]); }, [loadState, loadWatch]);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      if (!alive) return;
      if (!document.hidden) await refresh();
      if (alive) timerRef.current = setTimeout(tick, REFRESH_MS);
    };
    refresh();
    timerRef.current = setTimeout(tick, REFRESH_MS);
    const onVis = () => { if (!document.hidden) refresh(); };
    document.addEventListener("visibilitychange", onVis);
    return () => { alive = false; if (timerRef.current) clearTimeout(timerRef.current); document.removeEventListener("visibilitychange", onVis); };
  }, [refresh]);

  const runScan = useCallback(async () => {
    setScanning(true); setMsg(null);
    try {
      const res = await apiRequest(`${API_BASE}/api/daily-rising/manual-scan`, { method: "POST" });
      const d = await res.json();
      if (!res.ok) throw new Error(d?.detail || `HTTP ${res.status}`);
      setCands(Array.isArray(d?.candidates) ? d.candidates : []);
      setScanned(true);
      setMsg(d?.count ? `${d.count} aday bulundu.` : "Koşulları geçen aday bulunamadı.");
    } catch (e: any) {
      setMsg(`Tarama hatası: ${e?.message || e}`);
    } finally { setScanning(false); }
  }, []);

  const addToWatch = useCallback(async (c: Cand) => {
    setBusy(c.symbol); setMsg(null);
    try {
      const res = await apiRequest(`${API_BASE}/api/daily-rising/watchlist`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol: c.symbol }),
      });
      const d = await res.json();
      if (!res.ok) throw new Error(d?.detail || `HTTP ${res.status}`);
      setMsg(`${c.symbol} takip listene eklendi.`);
      await loadWatch();
    } catch (e: any) {
      setMsg(`Eklenemedi: ${e?.message || e}`);
    } finally { setBusy(null); }
  }, [loadWatch]);

  const removeFromWatch = useCallback(async (sym: string) => {
    setBusy(sym); setMsg(null);
    try {
      const res = await apiRequest(`${API_BASE}/api/daily-rising/watchlist/${encodeURIComponent(sym)}`, { method: "DELETE" });
      const d = await res.json();
      if (!res.ok) throw new Error(d?.detail || `HTTP ${res.status}`);
      setMsg(`${sym} takip listenden çıkarıldı.`);
      await loadWatch();
    } catch (e: any) {
      setMsg(`Çıkarılamadı: ${e?.message || e}`);
    } finally { setBusy(null); }
  }, [loadWatch]);

  const watchSyms = new Set(watch.map((w) => w.symbol));

  return (
    <div className="page-shell">
      <div className="page-heading">
        <div>
          <div className="eyebrow">Günlük Momentum Katmanı</div>
          <h1 className="text-xl font-semibold">🌅 Yükseliş Adayları</h1>
          <p className="text-sm text-bunker-muted mt-1">
            Elle tara, beğendiğin adayları <b>kendi takip listene</b> ekle. Sistem ayrıca her gün
            11:30'da otomatik tarar ve adayları bildirir.
          </p>
        </div>
        <div className="flex flex-col items-end gap-2">
          <Button variant="primary" onClick={runScan} disabled={scanning}>
            {scanning ? "Taranıyor…" : "🔍 Tara"}
          </Button>
          <span className="text-xs text-bunker-muted">
            {updatedAt ? `Güncelleme: ${fmtDateTime(updatedAt)}` : ""}
          </span>
        </div>
      </div>

      {msg ? <div className="text-sm text-neon-yellow my-2">{msg}</div> : null}

      {/* 1) MANUEL TARAMA SONUCU */}
      {scanned ? (
        <Card className="my-4">
          <h2 className="font-semibold mb-2">Tarama Sonucu ({cands.length})</h2>
          {cands.length === 0 ? (
            <div className="text-sm text-bunker-muted">Koşulları geçen aday yok.</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full font-mono text-xs">
                <thead>
                  <tr className="text-left text-bunker-muted border-b border-bunker-700">
                    <th className="p-2">Sembol</th>
                    <th className="p-2 text-right">Fiyat</th>
                    <th className="p-2 text-right">Hedef</th>
                    <th className="p-2 text-right">8s Getiri</th>
                    <th className="p-2 text-right">ADX</th>
                    <th className="p-2 text-right">Eğim</th>
                    <th className="p-2 text-right">Skor</th>
                    <th className="p-2 text-center">Takibe Al</th>
                  </tr>
                </thead>
                <tbody>
                  {cands.map((c) => (
                    <tr key={c.symbol} className="border-b border-bunker-800 hover:bg-bunker-800/40">
                      <td className="p-2">
                        <a className="text-neon-green hover:underline" href={`/charts?symbol=${c.symbol}`}>{c.symbol}</a>
                      </td>
                      <td className="p-2 text-right">{c.price != null ? formatPrice(c.price) : "—"}</td>
                      <td className="p-2 text-right text-neon-yellow whitespace-nowrap">
                        {c.target_price != null
                          ? <>{formatPrice(c.target_price)}<span className="text-bunker-muted">(+%{Math.round(c.ceiling_pct ?? 0)})</span>
                              {" | "}
                              {c.target_probability != null
                                ? <span className="text-neon-green font-semibold" title="Hedefe ulaşım ihtimali (gerçek veriden kalibre)">%{Math.round(c.target_probability)}</span>
                                : <span className="text-bunker-muted">—</span>}</>
                          : "—"}
                      </td>
                      <td className={`p-2 text-right ${pctTone(c.ret_8h_pct)}`}>{fmtPct(c.ret_8h_pct)}</td>
                      <td className="p-2 text-right">{c.adx_14 != null ? formatNumber2(c.adx_14) : "—"}</td>
                      <td className="p-2 text-right">{c.slope_15m != null ? formatNumber2(c.slope_15m) : "—"}</td>
                      <td className="p-2 text-right">{c.panel_score != null ? formatNumber2(c.panel_score) : "—"}</td>
                      <td className="p-2 text-center">
                        {watchSyms.has(c.symbol) ? (
                          <Badge tone="positive">Listede</Badge>
                        ) : (
                          <Button variant="secondary" onClick={() => addToWatch(c)} disabled={busy === c.symbol}>
                            {busy === c.symbol ? "…" : "+ Ekle"}
                          </Button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      ) : null}

      {/* 2) TAKİP LİSTEM */}
      <Card className="my-4">
        <h2 className="font-semibold mb-2">⭐ Takip Listem ({watch.length})</h2>
        {watch.length > 0 && watchStats ? (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
            <StatCard label="Ölçülen" value={`${watchStats.measured}/${watchStats.total}`} />
            <StatCard label="Başarı (tavana ulaşan)" value={watchStats.hit_rate != null ? `%${formatNumber2(watchStats.hit_rate)}` : "—"} detail={`${watchStats.ceiling_hits} aday`} />
            <StatCard label="Ort. Gerçekleşen Max" value={watchStats.avg_mfe_pct != null ? `+${formatNumber2(watchStats.avg_mfe_pct)}%` : "—"} />
            <StatCard label="En Yüksek" value={watchStats.max_mfe_pct != null ? `+${formatNumber2(watchStats.max_mfe_pct)}%` : "—"} />
          </div>
        ) : null}
        {watch.length === 0 ? (
          <div className="text-sm text-bunker-muted">
            Henüz aday eklemedin. Yukarıdan "Tara" ile adayları bul, "+ Ekle" ile listene al.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full font-mono text-xs">
              <thead>
                <tr className="text-left text-bunker-muted border-b border-bunker-700">
                  <th className="p-2">Sembol</th>
                  <th className="p-2">Eklenme</th>
                  <th className="p-2 text-right">Giriş Fiyatı</th>
                  <th className="p-2 text-right">Anlık</th>
                  <th className="p-2 text-right">Değişim</th>
                  <th className="p-2 text-right">Hedef</th>
                  <th className="p-2 text-right">Gerçekleşen Max</th>
                  <th className="p-2 text-center">Tavan?</th>
                  <th className="p-2 text-center">Kaldır</th>
                </tr>
              </thead>
              <tbody>
                {watch.map((w) => (
                  <tr key={w.symbol} className="border-b border-bunker-800 hover:bg-bunker-800/40">
                    <td className="p-2">
                      <a className="text-neon-green hover:underline" href={`/charts?symbol=${w.symbol}`}>{w.symbol}</a>
                    </td>
                    <td className="p-2 text-bunker-muted">{w.added_at ? fmtDateTime(toMs(w.added_at)) : "—"}</td>
                    <td className="p-2 text-right">{w.entry_price != null ? formatPrice(w.entry_price) : "—"}</td>
                    <td className="p-2 text-right">{w.current_price != null ? formatPrice(w.current_price) : "—"}</td>
                    <td className={`p-2 text-right font-semibold ${pctTone(w.change_pct)}`}>{fmtPct(w.change_pct)}</td>
                    <td className="p-2 text-right text-neon-yellow whitespace-nowrap">
                      {w.target_price != null
                        ? <>{formatPrice(w.target_price)}<span className="text-bunker-muted">(+%{Math.round(w.ceiling_pct ?? 0)})</span>
                            {" | "}
                            {w.target_probability != null
                              ? <span className="text-neon-green font-semibold" title="Hedefe ulaşım ihtimali (gerçek veriden kalibre)">%{Math.round(w.target_probability)}</span>
                              : <span className="text-bunker-muted">—</span>}</>
                        : "—"}
                    </td>
                    <td className={`p-2 text-right font-semibold ${pctTone(w.mfe_pct)}`}>
                      {w.mfe_pct != null ? fmtPct(w.mfe_pct) : (w.outcome_status === "pending" ? "ölçülüyor…" : "—")}
                    </td>
                    <td className="p-2 text-center">
                      {w.hit_ceiling === true ? <Badge tone="positive">✓ Ulaştı</Badge>
                        : w.hit_ceiling === false ? <Badge tone="neutral">Hayır</Badge>
                        : <span className="text-bunker-muted">—</span>}
                    </td>
                    <td className="p-2 text-center">
                      <Button variant="danger" onClick={() => removeFromWatch(w.symbol)} disabled={busy === w.symbol}>
                        {busy === w.symbol ? "…" : "Çıkar"}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="text-[11px] text-bunker-muted mt-2">
          Başarı ölçümü: adayın eklendiği andan sonraki 24 saatte gerçekleşen maksimum yükseliş (MFE);
          tavan hedefine ulaşıp ulaşmadığı otomatik hesaplanır.
        </p>
      </Card>

      {/* 3) SİSTEM ADAYLARI (otomatik 11:30) */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 my-4">
        <StatCard label="Sistem Adayı (7g)" value={stats?.total ?? "—"} />
        <StatCard label="İsabet Oranı" value={stats?.hit_rate != null ? `%${formatNumber2(stats.hit_rate)}` : "—"} />
        <StatCard label="Ort. Gerçekleşen Max" value={stats?.avg_mfe_pct != null ? `+${formatNumber2(stats.avg_mfe_pct)}%` : "—"} />
        <StatCard label="En Yüksek" value={stats?.max_mfe_pct != null ? `+${formatNumber2(stats.max_mfe_pct)}%` : "—"} />
      </div>

      <Card>
        <h2 className="font-semibold mb-2">Sistem Adayları (otomatik 11:30)</h2>
        {loading ? (
          <div className="p-6 text-sm text-bunker-muted">Yükleniyor…</div>
        ) : rows.length === 0 ? (
          <div className="p-6 text-sm text-bunker-muted">Henüz sistem adayı yok.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full font-mono text-xs">
              <thead>
                <tr className="text-left text-bunker-muted border-b border-bunker-700">
                  <th className="p-2">Sembol</th>
                  <th className="p-2">Öneri Saati</th>
                  <th className="p-2 text-right">Öneri Fiyatı</th>
                  <th className="p-2 text-right">Tavan</th>
                  <th className="p-2 text-right">Anlık</th>
                  <th className="p-2 text-right">Değişim</th>
                  <th className="p-2 text-right">Gerçekleşen Max</th>
                  <th className="p-2">Durum</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={`${r.symbol}-${r.created_at}-${i}`} className="border-b border-bunker-800 hover:bg-bunker-800/40">
                    <td className="p-2">
                      <a className="text-neon-green hover:underline" href={`/charts?symbol=${r.symbol}`}>{r.symbol}</a>
                    </td>
                    <td className="p-2 text-bunker-muted">{r.created_at ? fmtDateTime(toMs(r.created_at)) : "—"}</td>
                    <td className="p-2 text-right">{r.entry_price != null ? formatPrice(r.entry_price) : "—"}</td>
                    <td className="p-2 text-right text-neon-yellow">
                      {r.ceiling_price != null ? formatPrice(r.ceiling_price) : "—"}
                    </td>
                    <td className="p-2 text-right">{r.current_price != null ? formatPrice(r.current_price) : "—"}</td>
                    <td className={`p-2 text-right font-semibold ${pctTone(r.change_pct)}`}>{fmtPct(r.change_pct)}</td>
                    <td className={`p-2 text-right ${pctTone(r.mfe_pct)}`}>{r.mfe_pct != null ? fmtPct(r.mfe_pct) : "—"}</td>
                    <td className="p-2">
                      <Badge tone={r.status === "filled" ? "positive" : r.status === "pending" ? "warning" : "neutral"}>
                        {r.status === "pending" ? "BEKLİYOR" : r.status === "filled" ? "TAMAMLANDI" : (r.status || "—").toUpperCase()}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <p className="text-[11px] text-bunker-muted mt-3">
        Bilgilendirme amaçlıdır. Sistem adayları mevcut bildirim yoluyla otomatik paper işlem açar;
        manuel takip listesi yalnız sana özeldir ve işlem açmaz.
      </p>
    </div>
  );
}
