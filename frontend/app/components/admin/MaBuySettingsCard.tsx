"use client";
import { MA_BUY_NOTIFY_TFS, formatTargetPct, formatTfList, parseTargetPct, parseTfList } from "../../lib/maBuyUi";

/** /api/config içindeki MA BUY alanları (backend `ma_buy_notify.SETTINGS_FIELDS`). */
export type MaBuySettings = {
  ma_buy_tracker_enabled?: boolean;
  ma_buy_notify_enabled?: boolean;
  ma_buy_auto_paper_enabled?: boolean;
  ma_buy_notify_timeframes?: string;
  ma_buy_notify_cooldown_min?: number;
  ma_buy_notify_max_age_sec?: number;
  ma_buy_target_pct?: string;
  ma_buy_ma_type?: string;
  ma_buy_periods?: string;
};

type Props = {
  draft: MaBuySettings;
  onChange: (patch: MaBuySettings) => void;
};

const TF_LABEL: Record<string, string> = { "1m": "M1", "5m": "M5", "15m": "M15", "30m": "M30", "1h": "H1" };
const box = "rounded-lg border border-bunker-800 bg-bunker-900 px-3 py-2";
const inputCls = "mt-1 w-full bg-bunker-950 border border-bunker-700 rounded px-2 py-1.5 font-mono text-xs text-white";

/**
 * Ayarlar > MA BUY: MA kesişim BUY sinyali → push (TF etiketli) + otonom paper.
 * Değerler sayfanın ortak taslağına yazılır; üstteki KAYDET `/api/config`'e gönderir (sunucu doğrular, kalıcı saklar).
 */
export default function MaBuySettingsCard({ draft, onChange }: Props) {
  const tfs = parseTfList(draft.ma_buy_notify_timeframes);
  const targets = parseTargetPct(draft.ma_buy_target_pct);
  const toggleTf = (tf: string, on: boolean) => {
    const next = new Set(tfs);
    if (on) next.add(tf); else next.delete(tf);
    onChange({ ma_buy_notify_timeframes: formatTfList(next) });
  };
  const setTarget = (tf: string, raw: string) => {
    const n = raw === "" ? NaN : Number(raw);
    onChange({ ma_buy_target_pct: formatTargetPct({ ...targets, [tf]: n }) });
  };
  const numVal = (v: number | undefined) => (typeof v === "number" && Number.isFinite(v) ? v : "");
  const periods = String(draft.ma_buy_periods ?? "7,20,99").split(",").map((x) => x.trim());
  const setPeriod = (idx: number, raw: string) => {
    const next = [0, 1, 2].map((i) => (i === idx ? raw : periods[i] ?? ""));
    onChange({ ma_buy_periods: next.join(",") });
  };

  return (
    <div className="card bg-bunker-950 space-y-5">
      <div>
        <p className="eyebrow text-neon-green">MA BUY SİNYALİ → PUSH + OTONOM PAPER</p>
        <p className="text-xs text-bunker-muted mt-1">
          Grafikteki BUY rozetiyle aynı kural (EMA7/20/99 kesişimi). Seçili zaman dilimlerinde yeni kapanan mumda sinyal çıkınca
          “📈 SEMBOL · MA BUY (M1/M5)” push’u gider; push gittiyse otonom paper denenir. Genel bildirim anahtarı ve sessiz saat uygulanır.
        </p>
      </div>

      <div>
        <p className="font-mono text-xs text-bunker-muted">Ortalamalar — grafikteki MA Ribbon ile AYNI olmalı (1./2./3. çizgi = turuncu/mavi/mor)</p>
        <div className="grid sm:grid-cols-4 gap-3 mt-2">
          <label className={box}>
            <span className="font-mono text-xs text-bunker-muted">Tür</span>
            <select value={String(draft.ma_buy_ma_type ?? "sma").toLowerCase()} onChange={(e) => onChange({ ma_buy_ma_type: e.target.value })} className={inputCls}>
              <option value="sma">SMA</option>
              <option value="ema">EMA</option>
            </select>
          </label>
          {["Hızlı (turuncu)", "Orta (mavi)", "Yavaş (mor)"].map((label, i) => (
            <label key={label} className={box}>
              <span className="font-mono text-xs text-bunker-muted">{label}</span>
              <input type="number" min={1} max={500} step={1} value={periods[i] ?? ""} onChange={(e) => setPeriod(i, e.target.value)} className={inputCls} />
            </label>
          ))}
        </div>
        <p className="text-xs text-bunker-muted mt-2">Tür ya da uzunluk grafikten farklıysa bildirim, grafikteki BUY rozetiyle çelişir (ör. grafikte aşağı kesişen mumda “yukarı kesti”).</p>
      </div>

      <div className="grid sm:grid-cols-3 gap-3">
        <label className={`${box} flex items-center justify-between gap-3`}>
          <span className="font-mono text-xs text-bunker-muted">Sinyal taraması</span>
          <input type="checkbox" checked={draft.ma_buy_tracker_enabled !== false} onChange={(e) => onChange({ ma_buy_tracker_enabled: e.target.checked })} />
        </label>
        <label className={`${box} flex items-center justify-between gap-3`}>
          <span className="font-mono text-xs text-bunker-muted">Push bildirimi</span>
          <input type="checkbox" checked={draft.ma_buy_notify_enabled !== false} onChange={(e) => onChange({ ma_buy_notify_enabled: e.target.checked })} />
        </label>
        <label className={`${box} flex items-center justify-between gap-3`}>
          <span className="font-mono text-xs text-bunker-muted">Otonom paper aç</span>
          <input type="checkbox" checked={draft.ma_buy_auto_paper_enabled !== false} onChange={(e) => onChange({ ma_buy_auto_paper_enabled: e.target.checked })} />
        </label>
      </div>

      <div>
        <p className="font-mono text-xs text-bunker-muted">Zaman dilimleri ve paper hedefi (TP %)</p>
        <div className="grid sm:grid-cols-3 gap-3 mt-2">
          {MA_BUY_NOTIFY_TFS.map((tf) => (
            <div key={tf} className={box}>
              <label className="flex items-center justify-between gap-3">
                <span className="font-mono text-xs text-white">{TF_LABEL[tf]} bildirimi</span>
                <input type="checkbox" checked={tfs.has(tf)} onChange={(e) => toggleTf(tf, e.target.checked)} />
              </label>
              <label className="block mt-2">
                <span className="font-mono text-xs text-bunker-muted">Hedef (+%)</span>
                <input
                  type="number" min={0.1} max={20} step={0.1} value={targets[tf] ?? ""} placeholder="varsayılan"
                  onChange={(e) => setTarget(tf, e.target.value)} className={inputCls}
                />
              </label>
            </div>
          ))}
        </div>
        {tfs.size === 0 && <p className="text-xs text-yellow-300 mt-2">Hiç zaman dilimi seçili değil: MA BUY push’u ve paper girişi olmaz.</p>}
        <p className="text-xs text-bunker-muted mt-2">Hedef boşsa Otonom Paper varsayılan hedefi kullanılır; zarar durdur Otonom Paper ayarından gelir.</p>
      </div>

      <div className="grid sm:grid-cols-2 gap-3">
        <label className={box}>
          <span className="font-mono text-xs text-bunker-muted">Aynı sembolde bekleme (dk, 0–240)</span>
          <input
            type="number" min={0} max={240} step={1} value={numVal(draft.ma_buy_notify_cooldown_min)}
            onChange={(e) => onChange({ ma_buy_notify_cooldown_min: e.target.value === "" ? NaN : Number(e.target.value) })} className={inputCls}
          />
        </label>
        <label className={box}>
          <span className="font-mono text-xs text-bunker-muted">Tazelik sınırı (sn, 10–600)</span>
          <input
            type="number" min={10} max={600} step={5} value={numVal(draft.ma_buy_notify_max_age_sec)}
            onChange={(e) => onChange({ ma_buy_notify_max_age_sec: e.target.value === "" ? NaN : Number(e.target.value) })} className={inputCls}
          />
        </label>
      </div>
      <p className="text-xs text-bunker-muted">
        Bekleme: bir sembole MA push’u gittikten sonra bu süre boyunca ikinci push yok (TF’ler ortak; aynı anda M1 ve M5 çıkarsa M5 gider).
        Tazelik: mum kapanışından bu süre geçtiyse sinyal bildirilmez.
      </p>
    </div>
  );
}
