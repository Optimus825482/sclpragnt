"use client";

/**
 * RAPOR BAŞLANGICI — "bu deploy" sınırı (2026-10-07).
 *
 * Raporlar (sinyal + otonom işlem) ve KPI'lar yalnızca bu andan SONRAKİ
 * veriyle hesaplanır; öncesi "arşiv" sayılır ve varsayılan olarak gizlenir.
 *
 * NEDEN VAR: 2026-10-07'de otonom trade ayarları kanıta dayalı değerlere
 * çevrildi (docs/OTONOM_TRADE_TESHIS_2026-10-07.md §6). O tarihten önceki
 * işlemler eski (zarar eden) kurguyla açıldığı için yeni kurgunun gerçek
 * performansını kirletiyordu.
 *
 * Kaydedilen değer `llm_settings.reports_baseline_at`'e yazılır ve koda gömülü
 * varsayılanı (`REPORTS_BASELINE_DEFAULT`) EZER. Boş bırakıp kaydetmek
 * varsayılana döner; "0" yazmak filtreyi tamamen kapatır.
 */
import { useCallback, useEffect, useState } from "react";
import { getJSON, apiRequest, API_BASE } from "../lib/api";

type BaselineResponse = {
  effective_ts?: number;
  effective_local?: string | null;
  default_value?: string;
  enabled?: boolean;
  value?: string;
  ok?: boolean;
  detail?: string;
};

/** "2026-10-07 11:30" → { date: "2026-10-07", time: "11:30" } */
function splitLocal(local?: string | null): { date: string; time: string } {
  const text = String(local || "").trim();
  const m = text.match(/^(\d{4}-\d{2}-\d{2})(?:[ T](\d{2}:\d{2}))?$/);
  if (!m) return { date: "", time: "" };
  return { date: m[1], time: m[2] || "00:00" };
}

export default function ReportsBaselineTab() {
  const [date, setDate] = useState("");
  const [time, setTime] = useState("11:30");
  const [saved, setSaved] = useState<BaselineResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      const data = await getJSON<BaselineResponse>("/api/reports/baseline");
      setSaved(data);
      const parts = splitLocal(data.effective_local);
      setDate(parts.date);
      setTime(parts.time || "11:30");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Rapor başlangıcı okunamadı");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const persist = useCallback(async (value: string, okMessage: string) => {
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const res = await apiRequest(`${API_BASE}/api/reports/baseline`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ value }),
        cache: "no-store",
      });
      const body: BaselineResponse = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(body?.detail || `Kaydedilemedi (HTTP ${res.status})`);
        return;
      }
      setSaved(body);
      const parts = splitLocal(body.effective_local);
      setDate(parts.date);
      setTime(parts.time || "11:30");
      setNotice(okMessage);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Kaydedilemedi");
    } finally {
      setSaving(false);
    }
  }, []);

  /** Tarih + saati tek metne çevir (backend `YYYY-MM-DD HH:MM` bekler). */
  const combined = date ? `${date} ${time || "00:00"}` : "";

  const save = () => {
    if (!date) {
      setError("Tarih seçin. (Tüm filtreyi kapatmak için 'Filtreyi Kapat' düğmesini kullanın.)");
      return;
    }
    persist(combined, `Rapor başlangıcı kaydedildi: ${combined} (UTC+3). Raporlar ve KPI'lar artık bu andan sonrasını sayar.`);
  };

  if (loading) {
    return (
      <div className="card p-8 rounded-2xl border border-bunker-800 text-center font-mono text-sm text-bunker-muted">
        Rapor başlangıcı yükleniyor…
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <section className="card p-5 rounded-2xl border border-bunker-800 bg-bunker-950/60 shadow-xl space-y-4">
        <div className="border-b border-bunker-800 pb-3">
          <h2 className="font-mono text-base font-black text-neon-green flex items-center gap-2">
            <span>📌</span> RAPOR BAŞLANGICI
          </h2>
          <p className="mt-1 text-xs text-bunker-muted leading-relaxed">
            Bu andan <strong className="text-white">sonraki</strong> sinyaller ve otonom işlemler
            raporlara / KPI&apos;lara girer. <strong className="text-white">Öncesi arşivdir</strong> ve
            Raporlar sayfasındaki &quot;Arşivi göster&quot; kutusu işaretlenmedikçe görünmez.
          </p>
        </div>

        {/* Etkin durum */}
        <div className={`rounded-xl border p-3.5 font-mono text-xs ${
          saved?.enabled
            ? "border-neon-green/40 bg-neon-green/5 text-neon-green"
            : "border-amber-400/40 bg-amber-400/5 text-amber-300"
        }`}>
          {saved?.enabled ? (
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
              <span className="font-bold">✅ ETKİN SINIR</span>
              <span className="text-white">{saved.effective_local} <span className="text-bunker-muted">(UTC+3)</span></span>
              <span className="text-bunker-muted">epoch {Math.round(Number(saved.effective_ts) || 0)}</span>
            </div>
          ) : (
            <div className="space-y-1">
              <div className="font-bold">⚠️ FİLTRE KAPALI — tüm geçmiş raporlara giriyor</div>
              <div className="text-bunker-muted">
                Koda gömülü varsayılan: <span className="text-white">{saved?.default_value || "(yok)"}</span>
              </div>
            </div>
          )}
        </div>

        {/* Giriş */}
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1">
            <span className="text-[11px] font-mono text-bunker-muted uppercase tracking-wider">Tarih</span>
            <input
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              className="rounded-xl border border-bunker-700 bg-bunker-900 px-2.5 py-1.5 text-sm font-mono text-white focus:border-neon-green focus:outline-none"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[11px] font-mono text-bunker-muted uppercase tracking-wider">Saat (UTC+3)</span>
            <input
              type="time"
              value={time}
              onChange={(e) => setTime(e.target.value)}
              className="rounded-xl border border-bunker-700 bg-bunker-900 px-2.5 py-1.5 text-sm font-mono text-white focus:border-neon-green focus:outline-none"
            />
          </label>
          <button
            type="button"
            onClick={save}
            disabled={saving || !date}
            className="ui-button ui-button-primary px-4 py-2 text-xs disabled:opacity-50"
          >
            {saving ? "KAYDEDİLİYOR…" : "KAYDET"}
          </button>
          <button
            type="button"
            onClick={() => persist("", "Koda gömülü varsayılana dönüldü.")}
            disabled={saving}
            className="ui-button ui-button-secondary px-3 py-2 text-xs disabled:opacity-50"
          >
            VARSAYILANA DÖN
          </button>
          <button
            type="button"
            onClick={() => persist("0", "Filtre KAPATILDI — tüm geçmiş raporlara giriyor.")}
            disabled={saving}
            className="rounded-xl border border-neon-red/40 bg-neon-red/5 px-3 py-2 font-mono text-xs font-bold text-neon-red transition-colors hover:bg-neon-red/10 disabled:opacity-50"
          >
            FİLTREYİ KAPAT
          </button>
        </div>

        {notice && (
          <p className="rounded-xl border border-neon-green/30 bg-neon-green/5 p-3 font-mono text-xs text-neon-green">
            ✓ {notice}
          </p>
        )}
        {error && (
          <p className="rounded-xl border border-neon-red/40 bg-neon-red/5 p-3 font-mono text-xs text-neon-red">
            ⚠ {error}
          </p>
        )}

        <div className="rounded-xl border border-bunker-800 bg-bunker-900/50 p-3.5 text-[11px] text-bunker-muted leading-relaxed space-y-1.5">
          <p className="font-bold text-white">Nasıl çalışır</p>
          <p>
            Bu değer <span className="font-mono text-white">reports_baseline_at</span> anahtarına yazılır ve
            koda gömülü varsayılanı geçersiz kılar. Kaydettikten sonra Raporlar sayfasındaki
            sinyal ve otonom işlem sekmeleri yalnız bu andan sonrasını gösterir.
          </p>
          <p>
            <span className="text-white">FİLTREYİ KAPAT</span> sınırı sıfırlar (tüm geçmiş görünür);
            <span className="text-white"> VARSAYILANA DÖN</span> ise koda gömülü tarihi geri getirir.
            İkisi ayrı şeydir.
          </p>
        </div>
      </section>
    </div>
  );
}
