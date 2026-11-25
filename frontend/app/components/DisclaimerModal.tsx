"use client";

/**
 * Sorumluluk Reddi (Risk Bildirimi) — admin HARİÇ tüm kullanıcılara girişte
 * bir kez gösterilir. Her iki kabul düğmesi de onay kutusunu gerektirir.
 */
import { useEffect, useRef, useState } from "react";
import { useAuth } from "../lib/auth";

// Eski anahtar onay kutusu işaretlenmeden de yazılabildiği için yeniden onay iste.
const STORAGE_KEY = "scalper:disclaimer-accepted-v2";

export default function DisclaimerModal() {
  const { role } = useAuth();
  const isAdmin = role === "admin";
  const [visible, setVisible] = useState(false);
  const [checked, setChecked] = useState(false);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (isAdmin) return; // admin hariç
    try {
      if (localStorage.getItem(STORAGE_KEY)) return; // "BİR DAHA GÖSTERME" seçildiyse
      if (sessionStorage.getItem("scalper:disclaimer-ok")) return; // bu oturumda kabul edildiyse
    } catch { /* yoksay */ }
    const timer = window.setTimeout(() => setVisible(true), 0);
    return () => window.clearTimeout(timer);
  }, [isAdmin]);

  const showDisclaimer = visible && !isAdmin;
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!showDisclaimer || !dialog) return;
    dialog.setAttribute("closedby", "none");
    dialog.showModal();
    headingRef.current?.focus();
    return () => dialog.close();
  }, [showDisclaimer]);

  const accept = (remember: boolean) => {
    if (!checked) return;
    try { sessionStorage.setItem("scalper:disclaimer-ok", "1"); } catch { /* yoksay */ }
    if (remember) {
      try { localStorage.setItem(STORAGE_KEY, "1"); } catch { /* yoksay */ }
    }
    dialogRef.current?.close();
    setVisible(false);
  };

  if (!showDisclaimer) return null;

  return (
    <dialog
      ref={dialogRef}
      onCancel={(event) => event.preventDefault()}
      aria-labelledby="disclaimer-title"
      className="fixed inset-0 m-auto max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] max-w-2xl overflow-y-auto rounded-xl border border-yellow-300/30 bg-bunker-950 p-0 text-white shadow-2xl backdrop:bg-black/80"
    >
        <div className="flex items-center gap-2 border-b border-bunker-800 bg-yellow-300/5 px-5 py-4">
          <span className="text-xl">⚠️</span>
          <div>
            <p className="eyebrow text-yellow-300">SORUMLULUK REDDİ</p>
            <h2 id="disclaimer-title" ref={headingRef} tabIndex={-1} className="font-mono text-lg font-bold text-white">Kullanmadan önce okuyun</h2>
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
            Uygulamanın paper (sanal) ticaret bölümlerinde gerçek para kullanılmaz. Binance TR bağlantısını
            açtığınızda ise alım/satım ve SL/TP emirleri <strong className="text-white">gerçek paranızla</strong> verilir,
            geri alınamaz ve kayıp riski taşır. Alacağınız tüm kararların sorumluluğu size aittir.
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
              onClick={() => accept(true)}
              disabled={!checked}
              className="font-mono text-[11px] text-bunker-muted/70 underline-offset-2 enabled:hover:text-bunker-muted enabled:hover:underline disabled:cursor-not-allowed disabled:opacity-40"
            >
              BİR DAHA GÖSTERME
            </button>
            <button
              type="button"
              onClick={() => accept(false)}
              disabled={!checked}
              className="ui-button ui-button-primary disabled:cursor-not-allowed disabled:opacity-40"
            >
              TAMAM
            </button>
          </div>
        </div>
    </dialog>
  );
}
