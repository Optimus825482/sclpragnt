"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE, apiRequest } from "../lib/api";
import SymbolLink from "../components/SymbolLink";

type Candidate = {
  symbol: string;
  velocity_score: number;
  target_pct: number;
  price: number;
  atr_pct: number;
  ret3_pct: number;
  mode: string;
  rank: number | null;
  horizon_minutes: number;
};

type NotificationSettings = {
  enabled: boolean;
  min_score: number;
  min_target_pct: number;
  quiet_hours_start: string | null;
  quiet_hours_end: string | null;
};

type PushNotif = {
  id?: number | null;
  symbol: string;
  title?: string | null;
  message: string;
  score?: number | null;
  target_pct?: number | null;
  price?: number | null;
  expected_price?: number | null;
  horizon_minutes?: number | null;
  mode?: string | null;
  detected_at: number | null;
  sent_via_push?: boolean;
};

type MonitoringState = {
  last_scan_at: number | null;
  scan_count: number;
  candidates: Candidate[];
  watchlist: Candidate[];
};

const SCAN_INTERVAL_MS = 30_000; // 30 saniye — izleme listesi daha sık analiz

export default function MonitoringPage() {
  const [state, setState] = useState<MonitoringState>({
    last_scan_at: null,
    scan_count: 0,
    candidates: [],
    watchlist: [],
  });
  const [scanning, setScanning] = useState(false);
  const [radarAngle, setRadarAngle] = useState(0);
  const [countdown, setCountdown] = useState(0);
  const [notifications, setNotifications] = useState<PushNotif[]>([]);
  const [history, setHistory] = useState<PushNotif[]>([]);
  const [notifPermission, setNotifPermission] = useState<NotificationPermission>("default");
  const [pushEnabled, setPushEnabled] = useState(false);
  const [pushError, setPushError] = useState<string | null>(null);
  const [settings, setSettings] = useState<NotificationSettings>({
    enabled: true,
    min_score: 1.0,
    min_target_pct: 2.0,
    quiet_hours_start: null,
    quiet_hours_end: null,
  });
  const [showSettings, setShowSettings] = useState(false);
  const [loopActive, setLoopActive] = useState(false);
  const scanTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const radarTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const countdownRef = useRef(0);

  // Request notification permission + subscribe for Web Push (PWA closed still delivers)
  const enablePush = useCallback(async () => {
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
      setPushError("Bu tarayıcı Web Push desteklemiyor.");
      return;
    }
    try {
      const perm = await Notification.requestPermission();
      setNotifPermission(perm);
      if (perm !== "granted") {
        setPushError("Bildirim izni verilmedi. Tarayıcı ayarlarından açabilirsiniz.");
        return;
      }
      const key = process.env.NEXT_PUBLIC_VAPID_PUBLIC_KEY;
      if (!key) {
        setPushError("VAPID public key yapılandırılmamış.");
        return;
      }
      const registration = await navigator.serviceWorker.ready;
      const padded = key.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (key.length % 4)) % 4);
      let subscription = await registration.pushManager.getSubscription();
      if (!subscription) {
        subscription = await registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: Uint8Array.from(atob(padded), (c) => c.charCodeAt(0)),
        });
      }
      await apiRequest(`${API_BASE}/api/alerts/push-subscription`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(subscription.toJSON()),
      });
      setPushEnabled(true);
      setPushError(null);
    } catch (error) {
      setPushError(error instanceof Error ? error.message : "Push kurulamadı");
    }
  }, []);

  // Send in-app notification
  const addNotification = useCallback((n: PushNotif) => {
    setNotifications((prev) => [n, ...prev].slice(0, 60));
  }, []);

  // Load settings from DB
  const loadSettings = useCallback(async () => {
    try {
      const res = await apiRequest(`${API_BASE}/api/monitoring/settings`, { cache: "no-store" });
      if (res.ok) {
        const data = await res.json();
        setSettings({
          enabled: data.enabled ?? true,
          min_score: data.min_score ?? 1.0,
          min_target_pct: data.min_target_pct ?? 2.0,
          quiet_hours_start: data.quiet_hours_start ?? null,
          quiet_hours_end: data.quiet_hours_end ?? null,
        });
      }
    } catch {
      // Use defaults
    }
  }, []);

  // Save settings to DB
  const saveSettings = useCallback(async (newSettings: NotificationSettings) => {
    try {
      await apiRequest(`${API_BASE}/api/monitoring/settings`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(newSettings),
      });
      setSettings(newSettings);
    } catch {
      // Failed to save
    }
  }, []);

  // Run scan (UI manual / periodic)
  const runScan = useCallback(async () => {
    setScanning(true);
    try {
      const res = await apiRequest(`${API_BASE}/api/monitoring/scan`, { cache: "no-store" });
      if (res.ok) {
        const data = await res.json();
        setState({
          last_scan_at: data.scan_at,
          scan_count: data.scan_count,
          candidates: data.candidates || [],
          watchlist: data.watchlist || [],
        });
        if (data.loop_active !== undefined) setLoopActive(!!data.loop_active);
        // Update settings from response
        if (data.settings) {
          setSettings({
            enabled: data.settings.enabled ?? true,
            min_score: data.settings.min_score ?? 1.0,
            min_target_pct: data.settings.min_target_pct ?? 2.0,
            quiet_hours_start: data.settings.quiet_hours_start ?? null,
            quiet_hours_end: data.settings.quiet_hours_end ?? null,
          });
        }
        // In-app notification for new candidate notifications (server may also push)
        if (data.new_notifications > 0 && (data.notifications || []).length > 0) {
          for (const n of data.notifications || []) {
            if (!n || !n.symbol) continue;
            addNotification(n);
          }
        }
      }
    } catch {
      // Scan failed silently
    } finally {
      setScanning(false);
    }
  }, [addNotification]);

  // Load notification history from DB
  const loadHistory = useCallback(async () => {
    try {
      const res = await apiRequest(`${API_BASE}/api/monitoring/notifications`, { cache: "no-store" });
      if (res.ok) {
        const data = await res.json();
        const merged: PushNotif[] = [];
        const seen = new Set<string>();
        for (const n of [...(data.history || []), ...(data.session || [])]) {
          if (!n || !n.symbol) continue;
          const key = `${n.symbol}:${n.detected_at}`;
          if (seen.has(key)) continue;
          seen.add(key);
          merged.push(n);
        }
        merged.sort((a, b) => (b.detected_at ?? 0) - (a.detected_at ?? 0));
        setHistory(merged.slice(0, 60));
      }
    } catch {
      // Ignore
    }
  }, []);

  // Initial load + periodic scan + radar animation
  useEffect(() => {
    loadSettings();
    loadHistory();
    apiRequest(`${API_BASE}/api/monitoring/state`, { cache: "no-store" })
      .then((r) => r.json())
      .then((data) => {
        setState({
          last_scan_at: data.last_scan_at,
          scan_count: data.scan_count,
          candidates: data.candidates || [],
          watchlist: data.watchlist || [],
        });
        if (data.loop_active !== undefined) setLoopActive(!!data.loop_active);
        setHistory((prev) => {
          const merged = [...(data.history || []), ...prev];
          const seen = new Set<string>();
          const out: PushNotif[] = [];
          for (const n of merged) {
            if (!n || !n.symbol) continue;
            const key = `${n.symbol}:${n.detected_at}`;
            if (seen.has(key)) continue;
            seen.add(key);
            out.push(n);
          }
          return out.sort((a, b) => (b.detected_at ?? 0) - (a.detected_at ?? 0)).slice(0, 60);
        });
      })
      .catch(() => {});

    // Periodic scan (server loop runs anyway; UI refreshes faster for watchlist re-analysis)
    scanTimerRef.current = setInterval(runScan, SCAN_INTERVAL_MS);
    radarTimerRef.current = setInterval(() => {
      setRadarAngle((a) => (a + 3) % 360);
    }, 50);
    // Countdown to next scan
    countdownRef.current = Math.round(SCAN_INTERVAL_MS / 1000);
    const cd = setInterval(() => {
      countdownRef.current -= 1;
      if (countdownRef.current <= 0) countdownRef.current = Math.round(SCAN_INTERVAL_MS / 1000);
      setCountdown(countdownRef.current);
    }, 1000);

    if ("Notification" in window) setNotifPermission(Notification.permission);
    // Detect existing push subscription
    if ("serviceWorker" in navigator && "PushManager" in window) {
      navigator.serviceWorker.ready
        .then((reg) => reg.pushManager.getSubscription())
        .then((sub) => setPushEnabled(!!sub))
        .catch(() => {});
    }

    return () => {
      if (scanTimerRef.current) clearInterval(scanTimerRef.current);
      if (radarTimerRef.current) clearInterval(radarTimerRef.current);
      clearInterval(cd);
    };
  }, [runScan, loadSettings, loadHistory]);

  const formatTime = (ts: number | null) => {
    if (!ts) return "—";
    return new Date(ts * 1000).toLocaleTimeString("tr-TR");
  };

  const formatFullTime = (ts: number | null) => {
    if (!ts) return "—";
    return new Date(ts * 1000).toLocaleString("tr-TR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
  };

  const getScoreColor = (score: number) => {
    if (score >= 2.0) return "text-neon-green";
    if (score >= 1.5) return "text-yellow-300";
    return "text-neon-red";
  };

  const displayedNotifs = notifications.length > 0 ? notifications : history;

  return (
    <main className="page-shell">
      <div className="page-heading flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="eyebrow text-neon-green">OTONOM İZLEME · RADAR</p>
          <h1>Monitoring</h1>
          <p className="text-bunker-muted">
            %2+ yükselme potansiyeli olan sembolleri belirli aralıklarla tarar; uygun olanları izlemeye alır,
            uygun bulunanlar için sesli + yazılı bildirim gönderir.
          </p>
        </div>
        <div className="flex gap-2 flex-wrap">
          {!pushEnabled && notifPermission !== "granted" && (
            <button onClick={enablePush} className="ui-button">
              🔔 Bildirimleri Aç (Kapalıyken de)
            </button>
          )}
          {!pushEnabled && notifPermission === "granted" && (
            <button onClick={enablePush} className="ui-button">
              📲 Push Aboneliği Kur
            </button>
          )}
          {pushEnabled && (
            <span className="inline-flex items-center gap-1 px-2 py-1 rounded-md border border-neon-green/40 bg-neon-green/10 text-xs font-mono text-neon-green">
              ✓ PWA bildirimleri açık
            </span>
          )}
          <button onClick={() => setShowSettings(!showSettings)} className="ui-button">
            ⚙️ Ayarlar
          </button>
          <button onClick={runScan} disabled={scanning} className="ui-button ui-button-primary">
            {scanning ? "TARANIYOR…" : "ŞİMDİ TARA"}
          </button>
        </div>
      </div>

      {/* Notification Permission Banner */}
      {notifPermission === "default" && (
        <div className="card border-yellow-400/30 bg-yellow-400/5 flex flex-wrap items-center justify-between gap-2">
          <div>
            <p className="font-mono text-sm text-yellow-300">📱 Bildirim İzni Gerekli</p>
            <p className="text-xs text-bunker-muted mt-1">
              Mobil ve masaüstü bildirimleri almak için izin verin. İzin verdiğinizde PWA kurulursa uygulama
              kapalıyken bile (Web Push) bildirim gönderilir.
            </p>
          </div>
          <button onClick={enablePush} className="ui-button ui-button-primary shrink-0">
            İzin Ver ve Abone Ol
          </button>
        </div>
      )}
      {notifPermission === "denied" && (
        <div className="card border-neon-red/30 bg-neon-red/5">
          <p className="font-mono text-sm text-neon-red">🚨 Bildirim İzni Reddedildi</p>
          <p className="text-xs text-bunker-muted mt-1">
            Tarayıcı ayarlarından bildirim izni verebilirsiniz. Kapalıyken bildirim için PWA + Web Push gerekir.
          </p>
        </div>
      )}
      {pushError && (
        <div className="card border-yellow-400/30 bg-yellow-400/5">
          <p className="font-mono text-sm text-yellow-300">⚠️ Push Durumu</p>
          <p className="text-xs text-bunker-muted mt-1">{pushError}</p>
        </div>
      )}

      {/* Settings Panel */}
      {showSettings && (
        <div className="card border-neon-green/20">
          <p className="eyebrow text-neon-green">BİLDİRİM AYARLARI (VERİTABANINA KAYDEDİLİR)</p>
          <div className="mt-4 space-y-4">
            {/* Enable/Disable */}
            <div className="flex items-center justify-between">
              <div>
                <p className="font-mono text-sm text-white">Bildirimleri Etkinleştir</p>
                <p className="text-xs text-bunker-muted">Yeni adaylar için bildirim gönder</p>
              </div>
              <button
                onClick={() => saveSettings({ ...settings, enabled: !settings.enabled })}
                className={`w-12 h-6 rounded-full border transition-colors relative ${settings.enabled ? "bg-neon-green/30 border-neon-green/50" : "bg-bunker-800 border-bunker-700"}`}
              >
                <span className={`absolute top-0.5 w-5 h-5 rounded-full transition-all ${settings.enabled ? "left-6 bg-neon-green" : "left-0.5 bg-bunker-muted"}`} />
              </button>
            </div>
            {/* Min Score */}
            <div>
              <div className="flex justify-between items-center mb-1">
                <p className="font-mono text-sm text-white">Minimum Skor</p>
                <span className="font-mono text-sm text-neon-green">{settings.min_score.toFixed(1)}</span>
              </div>
              <input
                type="range"
                min="0.5"
                max="3.0"
                step="0.1"
                value={settings.min_score}
                onChange={(e) => setSettings({ ...settings, min_score: parseFloat(e.target.value) })}
                onMouseUp={() => saveSettings(settings)}
                onTouchEnd={() => saveSettings(settings)}
                className="w-full accent-neon-green"
              />
              <p className="text-xs text-bunker-muted mt-1">Bu skorun üzerindeki adaylar bildirilir</p>
            </div>
            {/* Min Target % */}
            <div>
              <div className="flex justify-between items-center mb-1">
                <p className="font-mono text-sm text-white">Minimum Hedef Artış</p>
                <span className="font-mono text-sm text-neon-green">%{settings.min_target_pct.toFixed(1)}</span>
              </div>
              <input
                type="range"
                min="1.0"
                max="5.0"
                step="0.5"
                value={settings.min_target_pct}
                onChange={(e) => setSettings({ ...settings, min_target_pct: parseFloat(e.target.value) })}
                onMouseUp={() => saveSettings(settings)}
                onTouchEnd={() => saveSettings(settings)}
                className="w-full accent-neon-green"
              />
              <p className="text-xs text-bunker-muted mt-1">Bu yüzdenin üzerindeki hedefler bildirilir</p>
            </div>
            {/* Quiet Hours */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <p className="font-mono text-sm text-white mb-1">Sessiz Saat Başlangıç</p>
                <input
                  type="time"
                  value={settings.quiet_hours_start || ""}
                  onChange={(e) => saveSettings({ ...settings, quiet_hours_start: e.target.value || null })}
                  className="w-full bg-bunker-950 border border-bunker-700 rounded-lg px-3 py-1.5 font-mono text-sm text-white focus:border-neon-green/50 outline-none"
                />
              </div>
              <div>
                <p className="font-mono text-sm text-white mb-1">Sessiz Saat Bitiş</p>
                <input
                  type="time"
                  value={settings.quiet_hours_end || ""}
                  onChange={(e) => saveSettings({ ...settings, quiet_hours_end: e.target.value || null })}
                  className="w-full bg-bunker-950 border border-bunker-700 rounded-lg px-3 py-1.5 font-mono text-sm text-white focus:border-neon-green/50 outline-none"
                />
              </div>
            </div>
            <p className="text-xs text-bunker-muted">
              Sessiz saatlerde bildirim gönderilmez (sunucu tarafında da uygulanır). Ayarlar veritabanına kaydedilir
              ve tarama + bildirim, uygulama kapalıyken sunucudan devam eder.
            </p>
          </div>
        </div>
      )}

      {/* Status Bar */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <div className="card">
          <p className="eyebrow">Son Tarama</p>
          <p className="mt-2 font-mono text-lg text-white">{formatTime(state.last_scan_at)}</p>
        </div>
        <div className="card">
          <p className="eyebrow">Toplam Tarama</p>
          <p className="mt-2 font-mono text-lg text-white">{state.scan_count}</p>
        </div>
        <div className="card">
          <p className="eyebrow">Sonraki Tarama</p>
          <p className="mt-2 font-mono text-lg text-neon-green">{countdown}sn</p>
        </div>
        <div className="card">
          <p className="eyebrow">Sunucu Döngüsü</p>
          <p className={`mt-2 font-mono text-lg ${loopActive ? "text-neon-green" : "text-yellow-300"}`}>
            {loopActive ? "AKTİF" : "—"}
          </p>
        </div>
      </div>

      {/* Radar Animation — always visible during scans */}
      <div className="card flex flex-col items-center justify-center py-8">
        <div className="monitoring-radar">
          <div className="monitoring-radar-sweep" style={{ transform: `rotate(${radarAngle}deg)` }} />
          <div className="monitoring-radar-ring monitoring-radar-ring-1" />
          <div className="monitoring-radar-ring monitoring-radar-ring-2" />
          <div className="monitoring-radar-ring monitoring-radar-ring-3" />
          <div className="monitoring-radar-center" />
        </div>
        <p className="mt-4 font-mono text-sm text-neon-green animate-pulse">
          {scanning ? "SEMBOLLER TARANIYOR…" : "BELİRLİ ARALIKLARLA TARANIYOR — RADAR AKTİF"}
        </p>
      </div>

      {/* Candidates List */}
      <section className="card">
        <div className="flex justify-between items-center">
          <p className="eyebrow text-neon-green">🎯 UYGUN ADAYLAR ({state.candidates.length})</p>
          <span className="text-xs text-bunker-muted">%{settings.min_target_pct}+ potansiyel | Skor ≥ {settings.min_score}</span>
        </div>
        {state.candidates.length === 0 ? (
          <p className="mt-3 text-bunker-muted">Henüz uygun aday bulunamadı. Tarama devam ediyor…</p>
        ) : (
          <div className="mt-3 table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Sembol</th>
                  <th>Skor</th>
                  <th>Hedef</th>
                  <th>ATR%</th>
                  <th>Anlık Fiyat</th>
                  <th>Beklenen</th>
                  <th>Mod</th>
                  <th>Ufuk</th>
                </tr>
              </thead>
              <tbody>
                {state.candidates.map((c, i) => {
                  const targetPct = Number(c.target_pct);
                  const validTarget = Number.isFinite(targetPct) && targetPct > 0;
                  const price = Number(c.price);
                  const expected = validTarget && Number.isFinite(price) && price > 0 ? price * (1 + targetPct / 100) : null;
                  const modeLabel = c.mode === "trend_devam" ? "TREND" : "V-DÖNÜŞÜ";
                  return (
                    <tr key={c.symbol} className="border-l-2 border-l-neon-green/30">
                      <td className="text-bunker-muted">{i + 1}</td>
                      <td><SymbolLink symbol={c.symbol} className="text-white hover:text-neon-green" /></td>
                      <td className={`font-bold ${getScoreColor(c.velocity_score)}`}>{c.velocity_score?.toFixed(1)}</td>
                      <td className="text-neon-green">{validTarget ? `+%${targetPct.toFixed(1)}` : "—"}</td>
                      <td>{c.atr_pct != null ? `${Number(c.atr_pct).toFixed(2)}%` : "—"}</td>
                      <td>{Number.isFinite(price) && price > 0 ? price.toLocaleString("tr-TR", { maximumFractionDigits: 6 }) : "—"}</td>
                      <td className="text-neon-green">{expected != null ? expected.toLocaleString("tr-TR", { maximumFractionDigits: 6 }) : "—"}</td>
                      <td>
                        <span className={`px-2 py-0.5 rounded text-xs font-mono ${c.mode === "trend_devam" ? "bg-neon-green/15 text-neon-green" : "bg-yellow-400/15 text-yellow-300"}`}>
                          {modeLabel}
                        </span>
                      </td>
                      <td className="text-bunker-muted">{c.horizon_minutes ? `${c.horizon_minutes}dk` : "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Watchlist */}
      <section className="card">
        <div className="flex justify-between items-center">
          <p className="eyebrow text-yellow-300">👁 İZLEME LİSTESİ ({state.watchlist.length})</p>
          <span className="text-xs text-bunker-muted">Her tarama turunda daha sık yeniden analiz edilir</span>
        </div>
        {state.watchlist.length === 0 ? (
          <p className="mt-3 text-bunker-muted">İzleme listesi boş.</p>
        ) : (
          <div className="mt-3 table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Sembol</th>
                  <th>Skor</th>
                  <th>ATR%</th>
                  <th>Anlık Fiyat</th>
                  <th>Mod</th>
                </tr>
              </thead>
              <tbody>
                {state.watchlist.map((w) => (
                  <tr key={w.symbol} className="border-l-2 border-l-yellow-400/20">
                    <td><SymbolLink symbol={w.symbol} className="text-white hover:text-neon-green" /></td>
                    <td className={getScoreColor(w.velocity_score)}>{w.velocity_score?.toFixed(1)}</td>
                    <td>{w.atr_pct?.toFixed(2)}%</td>
                    <td>{w.price?.toLocaleString("tr-TR", { maximumFractionDigits: 6 })}</td>
                    <td>
                      <span className="px-2 py-0.5 rounded text-xs font-mono bg-bunker-800 text-bunker-muted">
                        {w.mode === "trend_devam" ? "TREND" : "V-DÖNÜŞÜ"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Notifications */}
      {displayedNotifs.length > 0 && (
        <section className="card">
          <div className="flex justify-between items-center">
            <p className="eyebrow text-neon-green">🔔 BİLDİRİMLER ({displayedNotifs.length})</p>
            <div className="flex gap-2 items-center">
              {pushEnabled && notifPermission === "granted" && (
                <button
                  onClick={async () => {
                    // Test push: sunucuya monitoring bildirimi gönder (kendi cihazına)
                    try {
                      await apiRequest(`${API_BASE}/api/monitoring/scan`, { cache: "no-store" });
                    } catch {
                      // ignore
                    }
                  }}
                  className="text-xs text-bunker-muted hover:text-white"
                  title="Yeni tarama çalıştır"
                >
                  ⟳ Tazele
                </button>
              )}
              <button onClick={() => setNotifications([])} className="text-xs text-bunker-muted hover:text-white">
                Oturumu Temizle
              </button>
            </div>
          </div>
          <div className="mt-3 space-y-2 max-h-96 overflow-y-auto">
            {(notifications.length > 0 ? notifications : history).map((n, i) => (
              <div key={n.symbol + ":" + (n.detected_at ?? i)} className="flex items-start gap-2 p-2 rounded-lg bg-neon-green/5 border border-neon-green/20">
                <span className="text-neon-green mt-0.5">●</span>
                <div className="flex-1 min-w-0">
                  <p className="text-xs text-white font-mono truncate">{n.message || n.title}</p>
                  <p className="text-[10px] text-bunker-muted mt-0.5">
                    {formatFullTime(n.detected_at)}
                    {n.sent_via_push === false ? " · push kapalı (sunucuda kayıtlı)" : " · push ile gönderildi"}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Recent history from DB */}
      {notifications.length === 0 && history.length === 0 && state.candidates.length === 0 && (
        <section className="card">
          <p className="text-bunker-muted">
            Henüz bildirim yok. Semboller belirli aralıklarla taranıyor; skor ve % hedef eşiğini geçen uygun
            adaylar burada ve bildirim olarak görünür.
          </p>
        </section>
      )}
    </main>
  );
}
