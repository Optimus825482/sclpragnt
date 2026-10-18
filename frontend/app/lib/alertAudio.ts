/**
 * Alarm sesi için TEK paylaşılan AudioContext + kullanıcı jestiyle "kilit açma".
 *
 * Sorun (mobil denetimi P6/#19): iOS Safari/standalone ve Chrome autoplay politikası, kullanıcı
 * jesti olmadan oluşturulan/başlatılan AudioContext'i `suspended` bırakır. Eskiden her alarmda yeni
 * bir context açılıyordu → WS ile gelen radar modalı sessiz kalıyordu. Şimdi: tek context, ilk
 * dokunuşta (pointerdown/touchend/keydown) `resume()` + sessiz tampon ile açılır; arka plandan
 * dönünce ya da sistem askıya alınca ("interrupted" iOS) bir sonraki jestte yeniden açılır.
 *
 * NOT: iOS'ta cihazın SESSİZ (zil) anahtarı kapalıysa Web Audio da susar — yazılımla aşılamaz.
 */
type AudioContextCtor = new () => AudioContext;

let shared: AudioContext | null = null;

function contextCtor(): AudioContextCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as { AudioContext?: AudioContextCtor; webkitAudioContext?: AudioContextCtor };
  return w.AudioContext ?? w.webkitAudioContext ?? null;
}

export function getSharedAudioContext(): AudioContext | null {
  if (shared && shared.state !== "closed") return shared;
  const Ctor = contextCtor();
  if (!Ctor) return null;
  try {
    shared = new Ctor();
  } catch {
    shared = null;
  }
  return shared;
}

/** Test/yeniden kurulum için paylaşılan context'i bırakır. */
export function resetSharedAudioContext() {
  shared = null;
}

/** Kullanıcı jesti İÇİNDE çağrılmalı: context'i oluşturur, `resume()` eder, sessiz 1 örneklik tampon çalar. */
export function unlockAlertAudio(): void {
  const context = getSharedAudioContext();
  if (!context) return;
  try {
    if (context.state !== "running") void context.resume().catch(() => undefined);
    // iOS'ta bazı sürümler yalnız gerçek bir kaynak başlatılınca açılır.
    const source = context.createBufferSource();
    source.buffer = context.createBuffer(1, 1, 22050);
    source.connect(context.destination);
    source.start(0);
  } catch {
    /* ses desteklenmiyor: modal yine görünür */
  }
}

const GESTURE_EVENTS = ["pointerdown", "touchend", "keydown", "click"] as const;

/**
 * İlk (ve context askıdaysa her) kullanıcı jestinde sesi açar; sekme tekrar görünür olunca
 * askıdaki context'i dener. Dönen fonksiyon dinleyicileri kaldırır.
 */
export function installAlertAudioUnlock(): () => void {
  if (typeof window === "undefined" || typeof document === "undefined") return () => undefined;
  const onGesture = () => {
    if (!shared || shared.state !== "running") unlockAlertAudio();
  };
  const onVisible = () => {
    if (document.visibilityState === "visible" && shared && shared.state !== "running") {
      void shared.resume().catch(() => undefined);
    }
  };
  for (const name of GESTURE_EVENTS) window.addEventListener(name, onGesture, { capture: true, passive: true });
  document.addEventListener("visibilitychange", onVisible);
  return () => {
    for (const name of GESTURE_EVENTS) window.removeEventListener(name, onGesture, { capture: true });
    document.removeEventListener("visibilitychange", onVisible);
  };
}

const NOTES: ReadonlyArray<readonly [number, number, number]> = [
  [1046.5, 0, 0.12],     // C6
  [1318.5, 0.14, 0.12],  // E6
  [1568.0, 0.28, 0.22],  // G6
];

/** Çalmadan önce context'in çalışır olması için en çok bu kadar beklenir (jestsiz resume() askıda kalabilir). */
const RESUME_WAIT_MS = 400;

function scheduleNotes(context: AudioContext) {
  const now = context.currentTime;
  for (const [freq, offset, dur] of NOTES) {
    const start = now + offset;
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    oscillator.type = "sine";
    oscillator.frequency.value = freq;
    gain.gain.setValueAtTime(0.0001, start);
    gain.gain.exponentialRampToValueAtTime(0.22, start + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + dur);
    oscillator.connect(gain);
    gain.connect(context.destination);
    oscillator.start(start);
    oscillator.stop(start + dur + 0.02);
  }
}

/**
 * Kısa, keskin "radar" sesi: üç notalı yükselen ton. Paylaşılan context askıdaysa kısa süre
 * `resume()` beklenir; açılamazsa SESSİZ geçilir (geç gelen bayat ses bir sonraki dokunuşta çalmasın).
 * @returns ses planlandıysa true
 */
export async function playAlertSound(): Promise<boolean> {
  const context = getSharedAudioContext();
  if (!context) return false;
  try {
    if (context.state !== "running") {
      await Promise.race([
        context.resume().catch(() => undefined),
        new Promise((resolve) => setTimeout(resolve, RESUME_WAIT_MS)),
      ]);
    }
    if (context.state !== "running") return false;
    scheduleNotes(context);
    return true;
  } catch {
    return false;
  }
}

/** Android'de titreşim (ses açılamasa bile dikkat çeker); iOS desteklemez. */
export function vibrateAlert(): void {
  try {
    if (typeof navigator !== "undefined" && typeof navigator.vibrate === "function") navigator.vibrate([200, 100, 200]);
  } catch {
    /* yok say */
  }
}
