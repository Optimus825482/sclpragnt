"use client";

/**
 * Sorumluluk Reddi (Risk Bildirimi) — admin HARİÇ tüm kullanıcılara girişte
 * bir kez gösterilir. Kullanıcı "Okudum, Anladım" checkbox'ını işaretleyip
 * "TAMAM" demeden panel kullanılamaz. "BİR DAHA GÖSTERME" ile kalıcı kapatılır.
 */
import { useEffect, useState } from "react";
import { useAuth } from "../lib/auth";

const STORAGE_KEY = "scalper:disclaimer-accepted";

export default function DisclaimerModal() {
  const { role } = useAuth();
  const isAdmin = role === "admin";
  const [visible, setVisible] = useState(false);
  const [checked, setChecked] = useState(false);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (isAdmin) return; // admin hariç
    try {
      if (localStorage.getItem(STORAGE_KEY)) return; // "BİR DAHA GÖSTERME" seçildiyse
      if (sessionStorage.getItem("scalper:disclaimer-ok")) return; // bu oturumda kabul edildiyse
    } catch { /* yoksay */ }
    const timer = window.setTimeout(() => setVisible(true), 600);
    return () => window.clearTimeout(timer);
  }, [isAdmin]);

  const accept = () => {
    // Kabulü yalnız oturum boyunca hatırla — her yeni girişte tekrar gösterilir.
    try { sessionStorage.setItem("scalper:disclaimer-ok", "1"); } catch { /* yoksay */ }
    setVisible(false);
  };

  const dismissForever = () => {
    try { localStorage.setItem(STORAGE_KEY, "1"); } catch { /* yoksay */ }
    setDismissed(true);
    setVisible(false);
  };

  if (!visible || dismissed) return null;

  return (
    <div className="fixed inset-0 z-[200] grid place-items-center bg-black/80 p-4" role="dialog" aria-modal="true" aria-labelledby="disclaimer-title">
      <section className="w-full max-w-2xl overflow-hidden rounded-xl border border-yellow-300/30 bg-bunker-950 shadow-2xl">
        <div className="flex items-center gap-2 border-b border-bunker-800 bg-yellow-300/5 px-5 py-4">
          <span className="text-xl">⚠️</span>
          <div>
            <p className="eyebrow text-yellow-300">SORUMLULUK REDDİ</p>
            <h2 id="disclaimer-title" className="font-mono text-lg font-bold text-white">Kullanmadan önce okuyun</h2>
          </div>
        </div>

        <div className="max-h-[55vh] space-y-3 overflow-y-auto p-5 text-sm leading-relaxed text-bunker-muted">
          <p>
            Bu sistem <strong className="text-white">henüz geliştirme aşamasındadır</strong> ve arka planda
            yapay zeka ile gelişmiş tarama algoritmaları kullanmaktadır.
          </p>
          <p>
            İnsan psikolojisi gereği bu tür sistemlere güven duyulduğunda{" "}
            <strong className="text-white">Algoritma Önyargısı (Automation Bias)</strong> oluşabilir:
            insanlar, bilgisayarlı sistemlerin ve algoritmaların kararlarını kendi kararlarından daha doğru,
            objektif ve güvenilir kabul etme eğilimindedir.
          </p>
          <p>
            Ancak unutulmamalıdır ki <strong className="text-white">kripto ticaretinin asla ve hiçbir zaman
            statik bir sistemi yoktur</strong> ve genel olarak öngörülemezdir.
          </p>
          <p>
            Scalper Agentic Trading <strong className="text-white">geleceği tahmin etmez</strong>; tamamen
            matematiksel metotlara dayalı ve kendini geliştirerek sizin trade kararlarınıza yardımcı olmak için
            tasarlanmıştır ve <strong className="text-yellow-300">herhangi bir garanti vermez</strong>.
          </p>
          <p className="rounded-lg border border-bunker-800 bg-bunker-900/60 px-3 py-2 text-xs">
            Bu uygulama yalnızca kağıt (paper) ticaret üzerinde çalışır; gerçek para kullanılmaz. Alacağınız
            tüm kararların sorumluluğu size aittir.
          </p>
        </div>

        <div className="space-y-3 border-t border-bunker-800 p-5">
          <label className="flex cursor-pointer items-start gap-3 rounded-lg border border-bunker-700 bg-bunker-900/50 p-3 hover:border-yellow-300/40">
            <input
              type="checkbox"
              checked={checked}
              onChange={(e) => setChecked(e.target.checked)}
              className="mt-0.5 h-4 w-4 accent-yellow-300"
            />
            <span className="text-sm text-white">
              Okudum, anladım; sistemin garanti vermediğini ve tüm trade kararlarının sorumluluğunun bana ait
              olduğunu kabul ediyorum.
            </span>
          </label>

          <div className="flex flex-wrap items-center justify-between gap-2">
            <button
              type="button"
              onClick={dismissForever}
              className="font-mono text-[11px] text-bunker-muted/70 underline-offset-2 hover:text-bunker-muted hover:underline"
            >
              BİR DAHA GÖSTERME
            </button>
            <button
              type="button"
              onClick={accept}
              disabled={!checked}
              className="ui-button ui-button-primary disabled:cursor-not-allowed disabled:opacity-40"
            >
              TAMAM
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}
