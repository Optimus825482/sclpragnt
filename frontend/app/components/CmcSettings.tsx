"use client";

/**
 * CoinMarketCap anahtar + kota paneli.
 *
 * NEDEN: radar/tarama katmanı piyasa geneli bağlamı (Korku & Açgözlülük, BTC
 * dominansı, trending, yükselen/düşenler) CMC'den okuyor. Anahtar buradan
 * girilir, aynı yerden kalan kredi izlenir.
 *
 * GÜVENLİK: Anahtar tarayıcıda tutulmaz. Kaydettikten sonra input temizlenir;
 * sunucu yalnız maskeli son 4 haneyi döner.
 */
import { useCallback, useEffect, useState } from "react";

import { API_BASE, apiRequest } from "../lib/api";

type Quota = {
  plan?: Record<string, any>;
  live_ok?: boolean;
  live_error?: string | null;
  local?: { date?: string; requests?: number; credits?: number; last_error?: string | null };
};

type Status = {
  configured: boolean;
  masked: string;
  source: "env" | "settings" | null;
  verified?: boolean | null;
  saved_at?: number | null;
  quota?: Quota | null;
};

function num(value: any): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  return Number.isFinite(n) ? n.toLocaleString("tr-TR") : String(value);
}

export default function CmcSettings() {
  const [status, setStatus] = useState<Status | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const r = await apiRequest(`${API_BASE}/api/cmc/settings`, { cache: "no-store" });
      if (!r.ok) {
        setStatus({ configured: false, masked: "", source: null });
        return;
      }
      setStatus(await r.json());
    } catch {
      setStatus({ configured: false, masked: "", source: null });
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!apiKey.trim() || busy) return;
    setBusy(true); setError(""); setNote("");
    try {
      const r = await apiRequest(`${API_BASE}/api/cmc/settings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: apiKey.trim() }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(typeof d?.detail === "string" ? d.detail : "Kaydedilemedi");
      if (d?.verified === false) {
        setNote("Anahtar kaydedildi (şifreli, kalıcı) ama CMC'ye ulaşılamadı — doğrulama sonra yapılacak.");
      } else {
        setNote("Anahtar doğrulandı ve şifreli olarak veritabanına kaydedildi. Tekrar girmeniz gerekmez.");
      }
      if (typeof d?.warning === "string" && d.warning) setNote((prev) => `${prev} ${d.warning}`);
      setStatus((prev) => ({ ...(prev || { configured: true, masked: "", source: "settings" }), configured: true, masked: d.masked || prev?.masked || "", source: d.source || "settings" }));
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Kaydedilemedi");
    } finally {
      setApiKey(""); // gizli değer bellekten silinir
      setBusy(false);
    }
  };

  const remove = async () => {
    if (busy) return;
    setBusy(true); setError(""); setNote("");
    try {
      const r = await apiRequest(`${API_BASE}/api/cmc/settings`, { method: "DELETE" });
      if (!r.ok) throw new Error("Silinemedi");
      setNote("Anahtar silindi.");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Silinemedi");
    } finally {
      setBusy(false);
    }
  };

  const refreshQuota = async () => {
    if (refreshing) return;
    setRefreshing(true); setError("");
    try {
      const r = await apiRequest(`${API_BASE}/api/cmc/quota?force=true`, { cache: "no-store" });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(typeof d?.detail === "string" ? d.detail : "Kota alınamadı");
      setStatus((prev) => ({ ...(prev || { configured: true, masked: "", source: "settings" }), quota: d }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Kota alınamadı");
    } finally {
      setRefreshing(false);
    }
  };

  const plan = status?.quota?.plan || {};
  const local = status?.quota?.local || {};
  const inputCls = "mt-1 w-full md:w-96 bg-bunker-900 border border-bunker-700 rounded-lg px-3 py-2 font-mono text-sm text-white focus:border-neon-green/50 outline-none";

  return (
    <div className="card bg-bunker-950">
      <p className="eyebrow text-neon-green">📊 COINMARKETCAP · ANAHTAR VE KOTA</p>
      <p className="text-xs text-bunker-muted mt-1">
        Radar katmanına piyasa geneli bağlam sağlar: Korku &amp; Açgözlülük, BTC dominansı, trending ve yükselen/düşenler.
        Anahtar yalnız sunucuda şifreli saklanır; ekranda son 4 hane görünür. Hiçbir işlem açmaz, sadece okur.
      </p>

      {error && <p className="mt-3 font-mono text-xs text-neon-red">⚠ {error}</p>}
      {note && <p className="mt-3 font-mono text-xs text-neon-green">✓ {note}</p>}
      {!status && <p className="mt-3 font-mono text-xs text-bunker-muted animate-pulse">Yükleniyor...</p>}

      <div className="mt-4 flex flex-wrap items-end gap-3">
        <div>
          <p className="eyebrow text-bunker-muted">DURUM</p>
          <p className="mt-1 font-mono text-sm">
            {status?.configured ? (
              <span className="text-neon-green">BAĞLI · {status.masked}</span>
            ) : (
              <span className="text-bunker-muted">TANIMSIZ</span>
            )}
            {status?.source === "env" && <span className="ml-2 text-[11px] text-bunker-muted">(ortam değişkeninden)</span>}
            {status?.verified === false && (
              <span className="ml-2 rounded border border-amber-400/40 bg-amber-400/10 px-1.5 py-0.5 text-[10px] text-amber-300">
                DOĞRULANAMADI (ağ)
              </span>
            )}
            {status?.verified === true && (
              <span className="ml-2 text-[10px] text-neon-green">DOĞRULANDI</span>
            )}
          </p>
          {status?.configured && status?.saved_at ? (
            <p className="mt-1 text-[11px] text-bunker-muted">
              Kalıcı kayıt: {new Date(status.saved_at * 1000).toLocaleString("tr-TR")} · şifreli saklanıyor
            </p>
          ) : null}
        </div>
      </div>

      {status?.source !== "env" && (
        <form onSubmit={save} className="mt-4 flex flex-wrap items-end gap-3">
          <div>
            <p className="eyebrow text-bunker-muted">API ANAHTARI (X-CMC_PRO_API_KEY)</p>
            <input
              type="password"
              autoComplete="off"
              spellCheck={false}
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="••••••••-••••-••••-••••-••••••••••••"
              className={inputCls}
            />
          </div>
          <button type="submit" disabled={busy || !apiKey.trim()} className="ui-button ui-button-primary">
            {busy ? "DOĞRULANIYOR…" : "DOĞRULA VE KAYDET"}
          </button>
          {status?.configured && (
            <button type="button" onClick={remove} disabled={busy} className="ui-button ui-button-secondary">
              SİL
            </button>
          )}
        </form>
      )}

      {status?.configured && (
        <div className="mt-5 border-t border-bunker-800 pt-4">
          <div className="flex items-center justify-between gap-3">
            <p className="eyebrow text-sky-300">KOTA · PLAN</p>
            <button type="button" onClick={refreshQuota} disabled={refreshing} className="ui-button ui-button-secondary">
              {refreshing ? "YENİLENİYOR…" : "YENİLE"}
            </button>
          </div>

          {status.quota?.live_ok ? (
            <div className="mt-3 grid grid-cols-2 md:grid-cols-4 gap-3">
              {[
                ["AYLIK LİMİT", num(plan.monthly_credit_limit)],
                ["BU AY KULLANILAN", num(plan.month_credits_used)],
                ["BU AY KALAN", num(plan.month_credits_left)],
                ["DAKİKA LİMİTİ", num(plan.minute_rate_limit)],
                ["BU DAKİKA İSTEK", num(plan.minute_requests_made)],
                ["BU DAKİKA KALAN", num(plan.minute_requests_left)],
                ["GÜN KALAN KREDİ", num(plan.day_credits_left)],
                ["SIFIRLANMA", plan.monthly_reset || "—"],
              ].map(([label, value]) => (
                <div key={label} className="rounded-lg border border-bunker-800 bg-bunker-900/60 px-3 py-2">
                  <p className="text-[10px] font-mono uppercase tracking-wide text-bunker-muted">{label}</p>
                  <p className="mt-0.5 font-mono text-sm text-white">{value}</p>
                </div>
              ))}
            </div>
          ) : (
            <p className="mt-3 font-mono text-xs text-amber-300">
              Canlı kota alınamadı{status.quota?.live_error ? `: ${status.quota.live_error}` : "."} Aşağıdaki yerel sayaç kullanılıyor.
            </p>
          )}

          <div className="mt-3 rounded-lg border border-bunker-800 bg-bunker-900/40 px-3 py-2">
            <p className="text-[10px] font-mono uppercase tracking-wide text-bunker-muted">YEREL SAYAÇ ({local.date || "—"})</p>
            <p className="mt-0.5 font-mono text-xs text-bunker-muted">
              istek: <span className="text-white">{num(local.requests)}</span> · tahmini kredi:{" "}
              <span className="text-white">{num(local.credits)}</span>
              {local.last_error && <span className="ml-2 text-neon-red">son hata: {local.last_error}</span>}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
