"use client";

import { useCallback, useEffect, useState } from "react";
import { API_BASE, apiRequest, getJSON } from "../lib/api";
import { useLiveMessages } from "../lib/liveSocket";
import { useVisibleInterval } from "../lib/useVisibleInterval";

type BridgeStatusResponse = {
  status: "active" | "disabled";
  settings: {
    enabled: boolean;
    secret: string;
    masked_secret: string;
    auto_trade: boolean;
    min_score: number;
    cooldown_sec: number;
  };
  statistics: {
    ok: boolean;
    total_received: number;
    pings_received: number;
    signals_received: number;
    trades_opened: number;
    trades_blocked: number;
    cooldown_skips: number;
    auth_failures: number;
    last_received_at: number | null;
    avg_latency_ms: number;
    history_count: number;
  };
};

type BridgeHistoryItem = {
  event_id: string;
  received_at: number;
  global_symbol?: string;
  tr_symbol?: string;
  signal_type: string;
  action?: string;
  score?: number;
  global_price?: number;
  tr_price?: number;
  latency_ms: number;
  status: string;
  trade?: {
    status: string;
    trade_id?: string;
    reason?: string;
  };
  remaining_sec?: number;
  cooldown_sec?: number;
};

export default function BridgeSettingsPanel() {
  const [data, setData] = useState<BridgeStatusResponse | null>(null);
  const [history, setHistory] = useState<BridgeHistoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // Form durumları
  const [enabled, setEnabled] = useState(true);
  const [autoTrade, setAutoTrade] = useState(true);
  const [minScore, setMinScore] = useState("0");
  const [cooldownSec, setCooldownSec] = useState("60");
  const [secret, setSecret] = useState("");
  const [showSecret, setShowSecret] = useState(false);

  // Ping test durumları
  const [pinging, setPinging] = useState(false);
  const [pingResult, setPingResult] = useState<{
    ok: boolean;
    latency_ms: number;
    server_time: number;
  } | null>(null);

  const loadStatus = useCallback(async () => {
    try {
      const res = await getJSON<BridgeStatusResponse>("/api/bridge/status");
      setData(res);
      setEnabled(res.settings.enabled);
      setAutoTrade(res.settings.auto_trade);
      setMinScore(String(res.settings.min_score));
      setCooldownSec(String(res.settings.cooldown_sec));
      if (!secret) {
        setSecret(res.settings.masked_secret);
      }
      setError(null);
    } catch (err: any) {
      setError(err?.message || "Köprü durumu alınamadı");
    } finally {
      setLoading(false);
    }
  }, [secret]);

  const loadHistory = useCallback(async () => {
    try {
      const res = await getJSON<{ ok: boolean; history: BridgeHistoryItem[] }>("/api/bridge/history?limit=15");
      if (res?.history) {
        setHistory(res.history.reverse());
      }
    } catch {
      // Hata sessizce yutulabilir
    }
  }, []);

  useEffect(() => {
    loadStatus();
    loadHistory();
  }, [loadStatus, loadHistory]);

  useVisibleInterval(() => {
    loadStatus();
    loadHistory();
  }, 10_000);

  // Canlı köprü sinyalleri gelince anında güncelle
  useLiveMessages(
    useCallback(
      (msg: any) => {
        if (msg.type === "global_bridge_signal" || msg.type === "signal") {
          loadStatus();
          loadHistory();
        }
      },
      [loadStatus, loadHistory]
    )
  );

  const handleSaveConfig = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    setSuccess(null);

    try {
      const payload: Record<string, any> = {
        enabled,
        auto_trade: autoTrade,
        min_score: parseFloat(minScore) || 0.0,
        cooldown_sec: parseFloat(cooldownSec) || 60.0,
      };

      // Maskelenmemiş ve değişmişse secret'ı gönder
      if (secret && !secret.includes("***")) {
        payload.secret = secret.trim();
      }

      const res = await apiRequest(`${API_BASE}/api/bridge/config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || "Ayarlar kaydedilemedi");
      }

      setSuccess("Köprü alıcı ayarları başarıyla güncellendi.");
      loadStatus();
      setTimeout(() => setSuccess(null), 4000);
    } catch (err: any) {
      setError(err.message || "Kaydetme sırasında bir hata oluştu");
    } finally {
      setSaving(false);
    }
  };

  const handleTestPing = async () => {
    setPinging(true);
    setPingResult(null);
    setError(null);

    const start = performance.now();
    try {
      const res = await apiRequest(`${API_BASE}/api/bridge/test-ping`, {
        method: "POST",
      });
      const end = performance.now();
      const roundTrip = Math.round(end - start);

      if (!res.ok) {
        throw new Error(`Ping başarısız (HTTP ${res.status})`);
      }
      const data = await res.json();
      setPingResult({
        ok: true,
        latency_ms: data.lead_lag_latency_ms || roundTrip,
        server_time: data.server_time || Date.now() / 1000,
      });
      loadStatus();
      loadHistory();
    } catch (err: any) {
      setError(err.message || "Ping testi başarısız oldu");
    } finally {
      setPinging(false);
    }
  };

  const webhookUrl = typeof window !== "undefined"
    ? `${window.location.origin}/api/bridge/global-signal`
    : "https://scalper.erkanerdem.online/api/bridge/global-signal";

  const lastReceived = data?.statistics?.last_received_at;
  const timeSinceLast = lastReceived ? Math.floor(Date.now() / 1000 - lastReceived) : null;
  const isCommunicating = Boolean(
    data?.status === "active" &&
    timeSinceLast !== null &&
    timeSinceLast < 300 // Son 5 dakika içinde sinyal/ping gelmişse
  );

  return (
    <div className="space-y-6">
      {/* 1. BAĞLANTI & HABERLEŞME DURUM KARTI */}
      <div className="card border-bunker-700 bg-bunker-900/60 p-5 rounded-2xl relative overflow-hidden shadow-lg">
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-bunker-800 pb-4">
          <div className="flex items-center gap-3">
            <span className="text-3xl">🌉</span>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="font-mono text-lg font-bold text-white">Binance Global ↔ Binance TR Köprü Durumu</h2>
                {isCommunicating ? (
                  <span className="flex items-center gap-1.5 rounded-full bg-neon-green/15 border border-neon-green/40 px-2.5 py-0.5 text-xs font-mono font-bold text-neon-green animate-pulse">
                    <span className="w-2 h-2 rounded-full bg-neon-green"></span>
                    BAĞLI &amp; HABERLEŞİYOR
                  </span>
                ) : data?.status === "active" ? (
                  <span className="flex items-center gap-1.5 rounded-full bg-amber-400/15 border border-amber-400/40 px-2.5 py-0.5 text-xs font-mono font-bold text-amber-300">
                    <span className="w-2 h-2 rounded-full bg-amber-400"></span>
                    HAZIR (Sinyal Bekleniyor)
                  </span>
                ) : (
                  <span className="flex items-center gap-1.5 rounded-full bg-neon-red/15 border border-neon-red/40 px-2.5 py-0.5 text-xs font-mono font-bold text-neon-red">
                    <span className="w-2 h-2 rounded-full bg-neon-red"></span>
                    DEVRE DIŞI
                  </span>
                )}
              </div>
              <p className="text-xs text-bunker-muted mt-1">
                Binance Global (USDT) öncü sinyalleri ile Binance TR (TRY) otomatik senkronizasyon ve lead-lag altyapısı.
              </p>
            </div>
          </div>

          <button
            type="button"
            onClick={handleTestPing}
            disabled={pinging}
            className="shrink-0 px-4 py-2.5 rounded-xl border border-neon-cyan/50 bg-neon-cyan/10 hover:bg-neon-cyan/20 text-neon-cyan font-mono text-xs font-bold transition-all flex items-center gap-2 shadow-sm"
          >
            {pinging ? (
              <>
                <span className="animate-spin text-sm">↻</span>
                <span>SINANIYOR...</span>
              </>
            ) : (
              <>
                <span>⚡</span>
                <span>BAĞLANTIYI SINA (TEST PING)</span>
              </>
            )}
          </button>
        </div>

        {/* Ping Sonucu Banner */}
        {pingResult && (
          <div className="mt-4 p-3 rounded-xl border border-neon-green/40 bg-neon-green/10 flex items-center justify-between text-xs font-mono">
            <div className="flex items-center gap-2 text-neon-green font-bold">
              <span>✓ PONG YANITI ALINDI</span>
              <span className="text-bunker-muted">|</span>
              <span>Gecikme: {pingResult.latency_ms} ms</span>
            </div>
            <span className="text-bunker-muted">
              Sunucu Zamanı: {new Date(pingResult.server_time * 1000).toLocaleTimeString("tr-TR")}
            </span>
          </div>
        )}

        {/* Durum Metrik Grid */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-4">
          <div className="p-3.5 rounded-xl border border-bunker-800 bg-bunker-950/60">
            <p className="eyebrow text-bunker-muted text-[10px]">ORTALAMA GECİKME</p>
            <p className="font-mono text-xl sm:text-2xl font-black text-neon-cyan mt-1">
              {data?.statistics?.avg_latency_ms ? `${data.statistics.avg_latency_ms} ms` : "—"}
            </p>
            <p className="text-[10px] text-bunker-muted mt-0.5 font-mono">Lead-Lag Taşıma Süresi</p>
          </div>

          <div className="p-3.5 rounded-xl border border-bunker-800 bg-bunker-950/60">
            <p className="eyebrow text-bunker-muted text-[10px]">SON HABERLEŞME</p>
            <p className="font-mono text-lg font-bold text-white mt-1">
              {timeSinceLast !== null
                ? timeSinceLast < 60
                  ? `${timeSinceLast} sn önce`
                  : `${Math.floor(timeSinceLast / 60)} dk önce`
                : "Henüz Yok"}
            </p>
            <p className="text-[10px] text-bunker-muted mt-0.5 font-mono">
              {lastReceived ? new Date(lastReceived * 1000).toLocaleTimeString("tr-TR") : "Bekleniyor"}
            </p>
          </div>

          <div className="p-3.5 rounded-xl border border-bunker-800 bg-bunker-950/60">
            <p className="eyebrow text-bunker-muted text-[10px]">ALINAN PAKETLER</p>
            <p className="font-mono text-xl sm:text-2xl font-black text-white mt-1">
              {data?.statistics?.total_received ?? 0}
            </p>
            <p className="text-[10px] text-bunker-muted mt-0.5 font-mono">
              Sinyal: {data?.statistics?.signals_received ?? 0} | Ping: {data?.statistics?.pings_received ?? 0}
            </p>
          </div>

          <div className="p-3.5 rounded-xl border border-bunker-800 bg-bunker-950/60">
            <p className="eyebrow text-bunker-muted text-[10px]">OTONOM İŞLEMLER</p>
            <p className="font-mono text-xl sm:text-2xl font-black text-neon-green mt-1">
              {data?.statistics?.trades_opened ?? 0}
            </p>
            <p className="text-[10px] text-bunker-muted mt-0.5 font-mono">
              Bloke: {data?.statistics?.trades_blocked ?? 0} | Cooldown: {data?.statistics?.cooldown_skips ?? 0}
            </p>
          </div>
        </div>
      </div>

      {/* 2. WEBHOOK ENTEGRASYON KILAVUZU */}
      <div className="card border-bunker-800 bg-bunker-950/60 p-5 rounded-2xl space-y-3">
        <div className="flex items-center gap-2">
          <span className="text-neon-cyan">🔗</span>
          <h3 className="font-mono text-sm font-bold text-white">Binance Global Tarafındaki Köprü Ayarları</h3>
        </div>
        <p className="text-xs text-bunker-muted">
          Binance Global sunucusunun <code className="text-white">.env</code> dosyasına bu URL ve Secret anahtarını ekleyerek iletimi başlatabilirsiniz:
        </p>
        <div className="bg-bunker-900 border border-bunker-800 rounded-xl p-3 font-mono text-xs text-white space-y-1 select-all overflow-x-auto">
          <p className="text-neon-cyan"># BINANCE TR LEAD-LAG SIGNAL BRIDGE</p>
          <p>BINANCE_TR_BRIDGE_ENABLED=true</p>
          <p>BINANCE_TR_BRIDGE_URL={webhookUrl}</p>
          <p>BINANCE_TR_BRIDGE_SECRET={data?.settings?.masked_secret || "guclu-bir-kopru-gizli-anahtari"}</p>
        </div>
      </div>

      {/* 3. ALICI YAPILANDIRMA FORMU */}
      <form onSubmit={handleSaveConfig} className="card border-bunker-800 bg-bunker-900/60 p-5 rounded-2xl space-y-5">
        <div className="flex items-center justify-between border-b border-bunker-800 pb-3">
          <div className="flex items-center gap-2">
            <span className="text-neon-green">⚙️</span>
            <h3 className="font-mono text-sm font-bold text-white">Köprü Alıcı &amp; Tetikleyici Parametreleri</h3>
          </div>
          {saving && <span className="text-xs font-mono text-neon-cyan animate-pulse">Kaydediliyor...</span>}
        </div>

        {error && (
          <div className="p-3 rounded-xl border border-neon-red/40 bg-neon-red/10 text-xs font-mono text-neon-red">
            {error}
          </div>
        )}
        {success && (
          <div className="p-3 rounded-xl border border-neon-green/40 bg-neon-green/10 text-xs font-mono text-neon-green font-bold">
            ✓ {success}
          </div>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {/* Alıcı Açık/Kapalı */}
          <div className="flex items-center justify-between p-3.5 rounded-xl border border-bunker-800 bg-bunker-950/60">
            <div>
              <p className="font-mono text-xs font-bold text-white">Köprü Alıcısı Aktif</p>
              <p className="text-[11px] text-bunker-muted mt-0.5">Global&apos;den gelen sinyalleri dinler ve kabul eder.</p>
            </div>
            <label className="relative inline-flex items-center cursor-pointer">
              <input
                type="checkbox"
                checked={enabled}
                onChange={(e) => setEnabled(e.target.checked)}
                className="sr-only peer"
              />
              <div className="w-11 h-6 bg-bunker-800 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-neon-green"></div>
            </label>
          </div>

          {/* Otomatik Paper İşlem */}
          <div className="flex items-center justify-between p-3.5 rounded-xl border border-bunker-800 bg-bunker-950/60">
            <div>
              <p className="font-mono text-xs font-bold text-white">Otomatik Paper Trade (Auto-Trade)</p>
              <p className="text-[11px] text-bunker-muted mt-0.5">Gelen BUY_SIGNAL ile TR&apos;de anında pozisyon açar.</p>
            </div>
            <label className="relative inline-flex items-center cursor-pointer">
              <input
                type="checkbox"
                checked={autoTrade}
                onChange={(e) => setAutoTrade(e.target.checked)}
                className="sr-only peer"
              />
              <div className="w-11 h-6 bg-bunker-800 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-neon-green"></div>
            </label>
          </div>

          {/* Minimum Global Skoru */}
          <div className="p-3.5 rounded-xl border border-bunker-800 bg-bunker-950/60">
            <label className="block font-mono text-xs font-bold text-white">Minimum Global Skoru (Eşik)</label>
            <p className="text-[11px] text-bunker-muted mt-0.5 mb-2">Bu skorun altındaki sinyaller işleme alınmaz (0 = filtre yok).</p>
            <input
              type="number"
              step="0.5"
              min="0"
              max="100"
              value={minScore}
              onChange={(e) => setMinScore(e.target.value)}
              className="w-full rounded-lg border border-bunker-700 bg-bunker-900 px-3 py-1.5 font-mono text-xs text-white focus:border-neon-green focus:outline-none"
            />
          </div>

          {/* Cooldown Süresi */}
          <div className="p-3.5 rounded-xl border border-bunker-800 bg-bunker-950/60">
            <label className="block font-mono text-xs font-bold text-white">Sinyal Cooldown Süresi (Saniye)</label>
            <p className="text-[11px] text-bunker-muted mt-0.5 mb-2">Aynı sembol için mükerrer sinyalleri engelleme süresi.</p>
            <input
              type="number"
              step="1"
              min="1"
              max="600"
              value={cooldownSec}
              onChange={(e) => setCooldownSec(e.target.value)}
              className="w-full rounded-lg border border-bunker-700 bg-bunker-900 px-3 py-1.5 font-mono text-xs text-white focus:border-neon-green focus:outline-none"
            />
          </div>

          {/* Köprü Gizli Anahtarı (X-Bridge-Secret) */}
          <div className="p-3.5 rounded-xl border border-bunker-800 bg-bunker-950/60 sm:col-span-2">
            <div className="flex items-center justify-between mb-1">
              <label className="block font-mono text-xs font-bold text-white">Köprü Gizli Anahtarı (X-Bridge-Secret)</label>
              <button
                type="button"
                onClick={() => setShowSecret(!showSecret)}
                className="text-[11px] font-mono text-neon-cyan hover:underline"
              >
                {showSecret ? "Gizle" : "Göster / Değiştir"}
              </button>
            </div>
            <p className="text-[11px] text-bunker-muted mb-2">
              Global ve TR sunucularında aynı olmalıdır. Değiştirmek istemiyorsanız maskeli bırakabilirsiniz.
            </p>
            <input
              type={showSecret ? "text" : "password"}
              value={secret}
              onChange={(e) => setSecret(e.target.value)}
              placeholder="Yeni gizli anahtar yazın..."
              className="w-full rounded-lg border border-bunker-700 bg-bunker-900 px-3 py-1.5 font-mono text-xs text-white focus:border-neon-green focus:outline-none"
            />
          </div>
        </div>

        <div className="flex justify-end pt-2">
          <button
            type="submit"
            disabled={saving}
            className="px-6 py-2.5 rounded-xl border border-neon-green/60 bg-neon-green/20 hover:bg-neon-green/30 text-neon-green font-mono text-xs font-bold transition-all shadow-sm"
          >
            {saving ? "KAYDEDİLİYOR..." : "AYARLARI KAYDET"}
          </button>
        </div>
      </form>

      {/* 4. SON HABERLEŞME & SİNYAL AKIŞI (CANLI TABLO) */}
      <div className="card border-bunker-800 bg-bunker-900/60 p-5 rounded-2xl space-y-3">
        <div className="flex items-center justify-between border-b border-bunker-800 pb-3">
          <div className="flex items-center gap-2">
            <span className="text-neon-cyan">📡</span>
            <h3 className="font-mono text-sm font-bold text-white">Son Sinyal ve Haberleşme Akışı (Canlı Kayıt)</h3>
          </div>
          <button
            type="button"
            onClick={loadHistory}
            className="text-xs font-mono text-bunker-muted hover:text-white"
          >
            ↻ Yenile
          </button>
        </div>

        {history.length === 0 ? (
          <p className="text-xs text-bunker-muted font-mono py-6 text-center">
            Henüz Global&apos;den alınan bir sinyal veya test ping paketi kaydı bulunmuyor.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left font-mono text-xs">
              <thead>
                <tr className="border-b border-bunker-800 text-[11px] text-bunker-muted uppercase">
                  <th className="py-2 px-2">Zaman</th>
                  <th className="py-2 px-2">Sembol</th>
                  <th className="py-2 px-2">Tür</th>
                  <th className="py-2 px-2 text-right">Skor</th>
                  <th className="py-2 px-2 text-right">Gecikme</th>
                  <th className="py-2 px-2 text-right">Sonuç</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-bunker-800/60">
                {history.map((row, idx) => (
                  <tr key={row.event_id || idx} className="hover:bg-bunker-800/40 transition-colors">
                    <td className="py-2.5 px-2 text-bunker-muted whitespace-nowrap">
                      {new Date(row.received_at * 1000).toLocaleTimeString("tr-TR")}
                    </td>
                    <td className="py-2.5 px-2 font-bold text-white whitespace-nowrap">
                      {row.tr_symbol ? (
                        <span>
                          <span className="text-bunker-muted">{row.global_symbol} → </span>
                          <span className="text-neon-cyan">{row.tr_symbol}</span>
                        </span>
                      ) : (
                        <span className="text-bunker-muted">— (Ping)</span>
                      )}
                    </td>
                    <td className="py-2.5 px-2 text-bunker-muted whitespace-nowrap">
                      <span className="rounded bg-bunker-800 px-1.5 py-0.5 text-[10px]">
                        {row.signal_type}
                      </span>
                    </td>
                    <td className="py-2.5 px-2 text-right font-bold text-white whitespace-nowrap">
                      {row.score ? row.score.toFixed(1) : "—"}
                    </td>
                    <td className="py-2.5 px-2 text-right text-neon-cyan whitespace-nowrap">
                      {row.latency_ms ? `${row.latency_ms} ms` : "—"}
                    </td>
                    <td className="py-2.5 px-2 text-right whitespace-nowrap">
                      {row.status === "pong" ? (
                        <span className="text-neon-green">✓ Pong</span>
                      ) : row.status === "executed" ? (
                        <span className="text-neon-green font-bold">🚀 İşlem Açıldı</span>
                      ) : row.status === "cooldown_skipped" ? (
                        <span className="text-amber-400 font-bold" title={`Kalan soğuma süresi: ${row.remaining_sec || 60} sn`}>
                          ⏱ Cooldown ({row.remaining_sec ? `${Math.round(row.remaining_sec)}s` : "60s"})
                        </span>
                      ) : row.status === "already_open" || row.status === "blocked_already_open" ? (
                        <span className="text-neon-cyan font-bold" title="Aynı sembolde zaten açık pozisyon mevcut">
                          🔄 Açık Pozisyon
                        </span>
                      ) : row.status === "score_below_minimum" ? (
                        <span className="text-bunker-muted">Düşük Skor</span>
                      ) : row.status === "blocked" ? (
                        <span className="text-neon-red" title={row.trade?.reason}>
                          ⛔ Bloke ({row.trade?.reason || "Filtre"})
                        </span>
                      ) : (
                        <span className="text-sky-300 font-bold">🔔 Bildirim Gönderildi</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
