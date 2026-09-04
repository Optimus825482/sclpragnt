"use client";

/**
 * Mobil/standalone PWA onboarding — tarayıcı uyarısı → kurulum uyarısı → bildirim izni.
 *
 * Akış (yalnız mobilde, oturum açılınca, bir kez):
 *  1. Chrome DEĞİLSE      → "Sistem en iyi Chrome ile çalışır" uyarısı (kapatılabilir)
 *  2. PWA kurulu DEĞİLSE  → "Uygulama olarak yükle" adımı (Android: native kurulum,
 *                           iOS: Paylaş → Ana Ekrana Ekle talimatı)
 *  3. PWA kurulu ise      → bildirim izni iste + push aboneliği kaydet
 *
 * Kurulum tamamlandıktan sonra kullanıcı PWA'yı standalone açtığında adım 3
 * (bildirim izni) tekrar gösterilir — standalone modal'ları atlamaz.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { ensurePushSubscription, detectBrowser, isMobileDevice, isStandalonePwa, pushSupported } from "../lib/push";

type Step = "browser_warn" | "install" | "notify" | null;

const STORAGE_KEY = "scalper:mobile-onboarding";
const NOTIF_ASKED_KEY = "scalper:notif-asked";

function iOS() {
  if (typeof window === "undefined") return false;
  return /iphone|ipad|ipod/i.test(navigator.userAgent || "");
}

export default function PushOnboardingModal({ active = false }: { active?: boolean }) {
  const [step, setStep] = useState<Step>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [installHelp, setInstallHelp] = useState(false); // beforeinstallprompt yoksa talimat göster
  const installPromptRef = useRef<any>(null);

  // beforeinstallprompt'u yakala (Android/Chrome native kurulum)
  useEffect(() => {
    if (!active) return;
    const handler = (e: Event) => { e.preventDefault(); installPromptRef.current = e; };
    window.addEventListener("beforeinstallprompt", handler);
    return () => window.removeEventListener("beforeinstallprompt", handler);
  }, [active]);

  // Hangi adımı göstereceğimizi belirle (yalnız mobil + oturum açık)
  useEffect(() => {
    if (!active || typeof window === "undefined") return;
    if (!isMobileDevice()) return;
    // Kullanıcı onboarding'i tamamladıysa veya izni reddettiyse bir daha sorma.
    try {
      if (localStorage.getItem(STORAGE_KEY) || localStorage.getItem(NOTIF_ASKED_KEY)) return;
    } catch { /* yoksay */ }

    let cancelled = false;
    const check = async () => {
      try {
        if (pushSupported().ok && "serviceWorker" in navigator) {
          const reg = await navigator.serviceWorker.ready;
          const existing = await reg.pushManager.getSubscription();
          if (existing) { cancelled = true; return; } // abonelik var → onboarding gereksiz
        }
      } catch { /* SW hazır değilse akışa devam */ }
      if (cancelled) return;

      const timer = window.setTimeout(() => {
        if (cancelled) return;
        // 1) Chrome dışı tarayıcı uyarısı önce gelir
        if (detectBrowser() !== "chrome") { setStep("browser_warn"); return; }
        // 2) Kurulu değilse kurulum adımı
        if (!isStandalonePwa()) { setStep("install"); return; }
        // 3) Kurulu PWA → bildirim izni (standalone'da modal atlanmaz artık)
        setStep("notify");
      }, 1200);
      return () => window.clearTimeout(timer);
    };
    check();
    return () => { cancelled = true; };
  }, [active]);

  // Onboarding'i tamamen kapat — "BİR DAHA GÖSTERME" (kalıcı, localStorage)
  const dismissForever = useCallback(() => {
    try { localStorage.setItem(STORAGE_KEY, "1"); } catch { /* yoksay */ }
    setStep(null);
  }, []);

  // Yalnız şimdilik kapat — bir dahaki oturumda tekrar sorulabilir
  const dismissNow = useCallback(() => {
    setStep(null);
  }, []);

  // Chrome uyarısını kapat → kurulum adımına geç
  const browserWarnOk = () => {
    if (!isStandalonePwa()) setStep("install");
    else setStep("notify");
  };

  const installPwa = async () => {
    setBusy(true); setError("");
    try {
      if (installPromptRef.current) {
        await installPromptRef.current.prompt();
        installPromptRef.current = null;
        setStep("notify");
      } else {
        // beforeinstallprompt tetiklenmedi (Chrome kriterleri tam karşılanmıyor
        // veya event daha önce tüketildi). Kullanıcıya menü talimatını göster.
        setInstallHelp(true);
      }
    } catch {
      setError("Kurulum başlatılamadı.");
    } finally {
      setBusy(false);
    }
  };

  const enableNotifications = async () => {
    setBusy(true); setError("");
    try {
      const result = await ensurePushSubscription();
      if (!result.ok) {
        if (result.reason === "izin_verilmedi") {
          // Kullanıcı izni reddetti — bir daha sorma
          try { localStorage.setItem(NOTIF_ASKED_KEY, "1"); } catch { /* yoksay */ }
          setError("Bildirim izni verilmedi. Tarayıcı ayarlarından açabilirsiniz.");
          dismissForever();
          return;
        }
        if (result.reason === "vapid_yok") {
          setError("Sunucu bildirim anahtarı yapılandırılmamış. Sistem yöneticisine VAPID anahtarının tanımlı olduğunu doğrulatın.");
        } else if (result.reason === "vapid_key_gecersiz" || result.reason === "vapid_key_gecersiz_boyut") {
          setError("Bildirim anahtarı geçersiz. Sistem yöneticisi VAPID public key'i yeniden üretip yapılandırmalı.");
        } else if (result.reason === "push_yok" || result.reason === "service_worker_yok") {
          setError("Bu tarayıcı/sürüm Web Push desteklemiyor — Chrome ile açmayı deneyin.");
        } else {
          setError(`Bildirimler etkinleştirilemedi: ${result.reason}`);
        }
        return;
      }
      // Abonelik kuruldu + backend'e kaydedildi → onboarding tamam
      try { localStorage.setItem(NOTIF_ASKED_KEY, "1"); } catch { /* yoksay */ }
      dismissForever();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Bildirimler etkinleştirilemedi");
    } finally {
      setBusy(false);
    }
  };

  if (!step) return null;

  const isIOS = iOS();

  return (
    <div className="fixed inset-0 z-[115] grid place-items-center bg-black/75 p-4" role="dialog" aria-modal="true" aria-labelledby="push-onboard-title">
      <section className="w-full max-w-sm overflow-hidden rounded-xl border border-bunker-700 bg-bunker-950 shadow-2xl">
        {step === "browser_warn" && (
          <>
            <div className="flex items-center gap-2 border-b border-bunker-800 px-5 py-4">
              <span className="text-xl">⚠️</span>
              <div>
                <p className="eyebrow">TARAYICI ÖNERİSİ</p>
                <h2 id="push-onboard-title" className="font-mono text-lg font-bold text-white">Chrome önerilir</h2>
              </div>
            </div>
            <div className="space-y-3 p-5">
              <p className="text-sm leading-relaxed text-bunker-muted">
                Bu sistem <strong className="text-white">en iyi Chrome tarayıcısı</strong> ile çalışır. Bildirimler ve uygulama kurulumu için lütfen Chrome kullanın.
              </p>
              {error && <p role="alert" className="rounded-lg border border-neon-red/40 bg-neon-red/10 px-3 py-2 text-sm text-neon-red">{error}</p>}
              <div className="flex justify-end gap-2 pt-1">
                <button type="button" onClick={dismissNow} className="ui-button ui-button-secondary">KAPAT</button>
                <button type="button" onClick={browserWarnOk} className="ui-button ui-button-primary">DEVAM ET</button>
              </div>
              <div className="text-center">
                <button type="button" onClick={dismissForever} className="font-mono text-[11px] text-bunker-muted/70 underline-offset-2 hover:text-bunker-muted hover:underline">
                  BİR DAHA GÖSTERME
                </button>
              </div>
            </div>
          </>
        )}

        {step === "install" && (
          <>
            <div className="flex items-center gap-2 border-b border-bunker-800 px-5 py-4">
              <span className="text-xl">📱</span>
              <div>
                <p className="eyebrow">UYGULAMA KURULUMU</p>
                <h2 id="push-onboard-title" className="font-mono text-lg font-bold text-white">Ana Ekrana Ekle</h2>
              </div>
            </div>
            <div className="space-y-3 p-5">
              {installHelp ? (
                <div className="space-y-2 rounded-lg border border-sky-400/30 bg-sky-400/5 p-3">
                  <p className="text-sm font-bold text-sky-300">Tarayıcı menüsünden kurulum</p>
                  <p className="text-sm leading-relaxed text-bunker-muted">
                    Chrome&apos;da sağ üstteki <strong className="text-white">⋮ (üç nokta) menüsü</strong> →
                    <strong className="text-white"> “Uygulamayı yükle”</strong> veya{" "}
                    <strong className="text-white">“Ana ekrana ekle”</strong> seçeneğine dokun.
                  </p>
                  <p className="text-xs text-bunker-muted">
                    Kurulum tamamlanınca uygulamayı ana ekrandan aç — bildirim izni orada sorulacak.
                  </p>
                </div>
              ) : (
                <p className="text-sm leading-relaxed text-bunker-muted">
                  {isIOS
                    ? "Safari'de Paylaş (⎋) → “Ana Ekrana Ekle” ile uygulamayı kur. Bildirimler yalnız kurulu uygulamada çalışır."
                    : "Uygulamayı cihazına kurduğunda bildirimler kapalıyken bile çalışır ve hızlı erişim sağlarsın."}
                </p>
              )}
              {error && <p role="alert" className="rounded-lg border border-neon-red/40 bg-neon-red/10 px-3 py-2 text-sm text-neon-red">{error}</p>}
              <div className="flex justify-end gap-2 pt-1">
                <button type="button" onClick={() => setStep("notify")} className="ui-button ui-button-secondary">SONRA</button>
                {isIOS ? (
                  <button type="button" onClick={() => setStep("notify")} className="ui-button ui-button-primary">ANLADIM</button>
                ) : (
                  <button type="button" onClick={installPwa} disabled={busy} className="ui-button ui-button-primary">
                    {busy ? "KURULUYOR…" : installHelp ? "KURDUM, DEVAM ET" : "📲 UYGULAMA OLARAK YÜKLE"}
                  </button>
                )}
              </div>
              <div className="text-center">
                <button type="button" onClick={dismissForever} className="font-mono text-[11px] text-bunker-muted/70 underline-offset-2 hover:text-bunker-muted hover:underline">
                  BİR DAHA GÖSTERME
                </button>
              </div>
            </div>
          </>
        )}

        {step === "notify" && (
          <>
            <div className="flex items-center gap-2 border-b border-bunker-800 px-5 py-4">
              <span className="text-xl">🔔</span>
              <div>
                <p className="eyebrow">BİLDİRİMLER</p>
                <h2 id="push-onboard-title" className="font-mono text-lg font-bold text-white">Fırsatları Kaçırma</h2>
              </div>
            </div>
            <div className="space-y-3 p-5">
              <p className="text-sm leading-relaxed text-bunker-muted">
                Radar yüksek potansiyel sembol tespit ettiğinde, uygulama <strong className="text-white">kapalı olsa bile</strong> anında bildirim almak için izin ver.
              </p>
              {error && <p role="alert" className="rounded-lg border border-neon-red/40 bg-neon-red/10 px-3 py-2 text-sm text-neon-red">{error}</p>}
              <div className="flex justify-end gap-2 pt-1">
                <button type="button" onClick={dismissNow} className="ui-button ui-button-secondary">HAYIR</button>
                <button type="button" onClick={enableNotifications} disabled={busy} className="ui-button ui-button-primary">
                  {busy ? "AÇILIYOR…" : "🔔 BİLDİRİMLERİ AÇ"}
                </button>
              </div>
              <div className="text-center">
                <button type="button" onClick={dismissForever} className="font-mono text-[11px] text-bunker-muted/70 underline-offset-2 hover:text-bunker-muted hover:underline">
                  BİR DAHA GÖSTERME
                </button>
              </div>
            </div>
          </>
        )}
      </section>
    </div>
  );
}
