import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  getSharedAudioContext, installAlertAudioUnlock, playAlertSound, resetSharedAudioContext, unlockAlertAudio,
} from "./alertAudio";

/** Sahte AudioContext: `suspended` başlar; resume() `autoplayAllowed` ise çalışır duruma geçirir. */
class FakeAudioContext {
  static created = 0;
  static autoplayAllowed = false;
  state: "suspended" | "running" | "closed" = "suspended";
  currentTime = 0;
  destination = {};
  oscillatorsStarted = 0;
  constructor() { FakeAudioContext.created += 1; }
  resume() {
    if (FakeAudioContext.autoplayAllowed) this.state = "running";
    return FakeAudioContext.autoplayAllowed ? Promise.resolve() : new Promise<void>(() => undefined);
  }
  createBuffer() { return {}; }
  createBufferSource() { return { buffer: null, connect: () => undefined, start: () => undefined }; }
  createOscillator() {
    const ctx = this;
    return { type: "", frequency: { value: 0 }, connect: () => undefined, start: () => { ctx.oscillatorsStarted += 1; }, stop: () => undefined };
  }
  createGain() {
    return { gain: { setValueAtTime: () => undefined, exponentialRampToValueAtTime: () => undefined }, connect: () => undefined };
  }
}

function setup() {
  const win = new EventTarget() as EventTarget & Record<string, unknown>;
  win.AudioContext = FakeAudioContext;
  const doc = new EventTarget() as EventTarget & Record<string, unknown>;
  doc.visibilityState = "visible";
  Object.assign(globalThis, { window: win, document: doc });
  return { win, doc };
}

describe("alertAudio", () => {
  let env: ReturnType<typeof setup>;
  beforeEach(() => {
    vi.useFakeTimers();
    FakeAudioContext.created = 0;
    FakeAudioContext.autoplayAllowed = false;
    resetSharedAudioContext();
    env = setup();
  });
  afterEach(() => {
    vi.useRealTimers();
    for (const key of ["window", "document"]) delete (globalThis as Record<string, unknown>)[key];
  });

  it("her alarmda yeni context açılmaz: tek paylaşılan context", () => {
    const a = getSharedAudioContext();
    const b = getSharedAudioContext();
    expect(a).toBe(b);
    expect(FakeAudioContext.created).toBe(1);
  });

  it("jestsiz (askıda) context'te ses ÇALINMAZ ve bayat ses sonradan çalmaz", async () => {
    const promise = playAlertSound();
    await vi.advanceTimersByTimeAsync(1000);
    expect(await promise).toBe(false);
    const ctx = getSharedAudioContext() as unknown as FakeAudioContext;
    expect(ctx.oscillatorsStarted).toBe(0);
  });

  it("ilk kullanıcı jestinde context açılır; sonraki alarm çalar", async () => {
    const off = installAlertAudioUnlock();
    FakeAudioContext.autoplayAllowed = true; // jest anında tarayıcı izin verir
    env.win.dispatchEvent(new Event("pointerdown"));
    const ctx = getSharedAudioContext() as unknown as FakeAudioContext;
    expect(ctx.state).toBe("running");
    expect(await playAlertSound()).toBe(true);
    expect(ctx.oscillatorsStarted).toBe(3); // üç nota
    off();
  });

  it("jest dinleyicileri temizlenir", () => {
    const off = installAlertAudioUnlock();
    off();
    FakeAudioContext.autoplayAllowed = true;
    env.win.dispatchEvent(new Event("pointerdown"));
    expect(FakeAudioContext.created).toBe(0);
  });

  it("arka plandan dönünce askıdaki context yeniden denenir", () => {
    const off = installAlertAudioUnlock();
    unlockAlertAudio(); // jest yok → suspended kalır
    const ctx = getSharedAudioContext() as unknown as FakeAudioContext;
    expect(ctx.state).toBe("suspended");
    FakeAudioContext.autoplayAllowed = true;
    env.doc.dispatchEvent(new Event("visibilitychange"));
    expect(ctx.state).toBe("running");
    off();
  });
});
