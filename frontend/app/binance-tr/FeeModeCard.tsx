"use client";

import { useCallback, useEffect, useState } from "react";
import { API_BASE, apiRequest } from "../lib/api";

type FeeMode = {
  bnb_burn_supported: boolean;
  spot_bnb_burn: boolean | null;
  maker_commission: number | null;
  taker_commission: number | null;
  bnb_balance: number | null;
  source?: string;
};

/** BNB bakiyesi bu eşiğin altındaysa (ve tahmini günlük komisyon verilmediyse) uyarı gösterilir. */
const BNB_LOW_THRESHOLD = 0.005;

function pct(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `%${(v * 100).toLocaleString("tr-TR", { maximumFractionDigits: 3 })}`;
}

/**
 * Komisyon ödeme modu kartı: BNB ile komisyon AÇIK/KAPALI/BİLİNMİYOR, maker/taker oranı
 * ve BNB bakiyesi. Binance TR API'sinde mod değiştirme ucu yoksa düğme pasif kalır.
 */
export default function FeeModeCard({ estimatedDailyFeeBnb }: { estimatedDailyFeeBnb?: number | null }) {
  const [data, setData] = useState<FeeMode | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const r = await apiRequest(`${API_BASE}/api/binance/fee-mode`, { cache: "no-store" });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || "Komisyon bilgisi alınamadı");
      setData(d as FeeMode);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Komisyon bilgisi alınamadı");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const toggle = useCallback(async () => {
    if (!data || !data.bnb_burn_supported || data.spot_bnb_burn == null) return;
    const next = !data.spot_bnb_burn;
    if (!window.confirm(`BNB ile komisyon ödeme ${next ? "AÇILSIN" : "KAPATILSIN"} mı?`)) return;
    setSaving(true);
    setError("");
    try {
      const r = await apiRequest(`${API_BASE}/api/binance/fee-mode`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ spot_bnb_burn: next, confirm: true }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || "Komisyon modu değiştirilemedi");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Komisyon modu değiştirilemedi");
    } finally {
      setSaving(false);
    }
  }, [data, load]);

  const supported = !!data?.bnb_burn_supported;
  const mode = data?.spot_bnb_burn;
  const modeLabel = mode === true ? "AÇIK" : mode === false ? "KAPALI" : "BİLİNMİYOR";
  const modeClass =
    mode === true
      ? "bg-neon-green/10 text-neon-green border border-neon-green/30"
      : mode === false
        ? "bg-yellow-400/10 text-yellow-400 border border-yellow-400/30"
        : "bg-bunker-800 text-bunker-muted border border-bunker-700";

  const bnb = data?.bnb_balance ?? null;
  const lowThreshold =
    estimatedDailyFeeBnb != null && estimatedDailyFeeBnb > 0 ? estimatedDailyFeeBnb : BNB_LOW_THRESHOLD;
  const bnbLow = bnb != null && bnb < lowThreshold;

  return (
    <div className="card relative overflow-hidden">
      <div className="absolute top-0 left-0 h-1 w-full bg-yellow-400/40" />
      <div className="flex items-center justify-between gap-2">
        <p className="eyebrow">KOMİSYON MODU</p>
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          className="ui-button ui-button-secondary !py-0.5 !px-2 !text-[10px]"
          title="Komisyon bilgisini yenile"
        >
          {loading ? "…" : "⟳"}
        </button>
      </div>

      {error && <p className="mt-1 text-[11px] text-neon-red">{error}</p>}
      {!data && !error && <p className="mt-1 text-[11px] text-bunker-muted">{loading ? "Yükleniyor…" : "—"}</p>}

      {data && (
        <>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <span className="text-[11px] text-bunker-muted">BNB ile komisyon:</span>
            <span className={`rounded px-1.5 py-0.5 font-mono text-[10px] font-bold ${modeClass}`}>{modeLabel}</span>
          </div>
          <p className="mt-1 font-mono text-[11px] text-bunker-muted">
            maker {pct(data.maker_commission)} · taker {pct(data.taker_commission)}
          </p>
          <p className="mt-0.5 font-mono text-[11px] text-bunker-muted">
            BNB bakiyesi: {bnb == null ? "—" : bnb.toLocaleString("tr-TR", { maximumFractionDigits: 6 })}
          </p>
          {bnbLow && (
            <p className="mt-1 text-[11px] text-yellow-400">
              BNB bakiyesi düşük — BNB ile komisyon açıksa indirim uygulanamaz, komisyon işlem varlığından düşer.
            </p>
          )}
          <div className="mt-2">
            {supported ? (
              <button
                type="button"
                onClick={() => void toggle()}
                disabled={saving || mode == null}
                className="ui-button ui-button-secondary !py-1 !text-xs"
                title="BNB ile komisyon ödemeyi aç/kapat"
              >
                {saving ? "Kaydediliyor…" : mode ? "BNB ile komisyonu KAPAT" : "BNB ile komisyonu AÇ"}
              </button>
            ) : (
              <>
                <button
                  type="button"
                  disabled
                  className="ui-button ui-button-secondary !py-1 !text-xs cursor-not-allowed opacity-50"
                  title="Binance TR API'si komisyon modunu değiştirmeye izin vermiyor"
                >
                  BNB ile komisyonu değiştir
                </button>
                <p className="mt-1 text-[11px] text-bunker-muted">
                  Binance TR → Ayarlar → Komisyon
                </p>
              </>
            )}
          </div>
        </>
      )}
    </div>
  );
}
