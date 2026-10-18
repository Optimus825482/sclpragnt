import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * liveSocket yaşam döngüsü testleri. Ortam `node` (jsdom yok): window/document/WebSocket sahte.
 * Modül durumu (tekil soket) testler arası sızmasın diye her testte `vi.resetModules()`.
 */
class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  readyState = 0;
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: ((e: { code: number }) => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;
  constructor(public url: string) { FakeWebSocket.instances.push(this); }
  close() { this.closed = true; this.readyState = 3; }
  open() { this.readyState = 1; this.onopen?.(); }
  message(obj: unknown) { this.onmessage?.({ data: JSON.stringify(obj) }); }
}

function setupGlobals() {
  const win = new EventTarget() as EventTarget & Record<string, unknown>;
  win.location = { hostname: "app.test", origin: "https://app.test" };
  const doc = new EventTarget() as EventTarget & Record<string, unknown>;
  doc.visibilityState = "visible";
  Object.assign(globalThis, { window: win, document: doc, WebSocket: FakeWebSocket });
  return { win, doc };
}

async function load() {
  vi.resetModules();
  return import("./liveSocket");
}

describe("liveSocket yaşam döngüsü", () => {
  let env: ReturnType<typeof setupGlobals>;

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-18T10:00:00Z"));
    FakeWebSocket.instances = [];
    env = setupGlobals();
  });
  afterEach(() => {
    vi.useRealTimers();
    for (const key of ["window", "document", "WebSocket"]) delete (globalThis as Record<string, unknown>)[key];
  });

  it("öne gelince geri çekilme zamanlayıcısını beklemeden hemen bağlanır", async () => {
    const live = await load();
    const unsubscribe = live.subscribeLive(() => undefined, ["portfolio"]);
    FakeWebSocket.instances[0].open();
    FakeWebSocket.instances[0].onclose?.({ code: 1006 }); // bağlantı koptu → backoff bekliyor
    expect(FakeWebSocket.instances).toHaveLength(1);

    env.doc.dispatchEvent(new Event("visibilitychange"));
    expect(FakeWebSocket.instances).toHaveLength(2); // 2-3 sn beklemeden yeni soket
    unsubscribe();
  });

  it("gizli sekmeye geçişte (hidden) yeniden bağlanmaz", async () => {
    const live = await load();
    const unsubscribe = live.subscribeLive(() => undefined);
    FakeWebSocket.instances[0].open();
    FakeWebSocket.instances[0].onclose?.({ code: 1006 });
    env.doc.visibilityState = "hidden";
    env.doc.dispatchEvent(new Event("visibilitychange"));
    expect(FakeWebSocket.instances).toHaveLength(1);
    unsubscribe();
  });

  it("açık görünen ama sessiz (ölü) soket öne gelince hemen yenilenir", async () => {
    const live = await load();
    const unsubscribe = live.subscribeLive(() => undefined);
    const first = FakeWebSocket.instances[0];
    first.open();
    first.message({ type: "portfolio", data: {} });
    vi.setSystemTime(Date.now() + live.RESUME_STALE_MS + 1_000); // arka planda sessiz kaldı
    env.doc.dispatchEvent(new Event("visibilitychange"));
    expect(first.closed).toBe(true);
    expect(FakeWebSocket.instances).toHaveLength(2);
    unsubscribe();
  });

  it("taze (az önce mesaj almış) soket öne gelince gereksiz yenilenmez", async () => {
    const live = await load();
    const unsubscribe = live.subscribeLive(() => undefined);
    const first = FakeWebSocket.instances[0];
    first.open();
    first.message({ type: "portfolio", data: {} });
    env.doc.dispatchEvent(new Event("visibilitychange"));
    expect(first.closed).toBe(false);
    expect(FakeWebSocket.instances).toHaveLength(1);
    unsubscribe();
  });

  it("ağ dönünce (online) sağlıklı görünse bile soketi yeniler", async () => {
    const live = await load();
    const unsubscribe = live.subscribeLive(() => undefined);
    const first = FakeWebSocket.instances[0];
    first.open();
    first.message({ type: "portfolio", data: {} });
    env.win.dispatchEvent(new Event("online"));
    expect(first.closed).toBe(true);
    expect(FakeWebSocket.instances).toHaveLength(2);
    unsubscribe();
  });

  it("bfcache'ten dönüşte (pageshow persisted) soketi yeniler; normal yüklemede dokunmaz", async () => {
    const live = await load();
    const unsubscribe = live.subscribeLive(() => undefined);
    const first = FakeWebSocket.instances[0];
    first.open();
    first.message({ type: "portfolio", data: {} });
    env.win.dispatchEvent(Object.assign(new Event("pageshow"), { persisted: false }));
    expect(first.closed).toBe(false);
    env.win.dispatchEvent(Object.assign(new Event("pageshow"), { persisted: true }));
    expect(first.closed).toBe(true);
    expect(FakeWebSocket.instances).toHaveLength(2);
    unsubscribe();
  });

  it("20 sn sessizlikte ölü soket kendiliğinden atılıp yeniden kurulur (eskiden ~60 sn)", async () => {
    const live = await load();
    const unsubscribe = live.subscribeLive(() => undefined);
    const first = FakeWebSocket.instances[0];
    first.open();
    first.message({ type: "portfolio", data: {} });
    await vi.advanceTimersByTimeAsync(live.STALE_AFTER_MS + live.HEARTBEAT_CHECK_MS);
    expect(first.closed).toBe(true);
    expect(FakeWebSocket.instances).toHaveLength(2);
    unsubscribe();
  });

  it("yeniden bağlanınca kesinti başlangıcıyla telafi bildirimi verir; ilk bağlanışta vermez", async () => {
    const live = await load();
    const seen: number[] = [];
    const off = live.subscribeLiveReconnect(({ since }) => seen.push(since));
    const unsubscribe = live.subscribeLive(() => undefined);
    FakeWebSocket.instances[0].open();
    expect(seen).toEqual([]);
    const lastMessage = Date.now();
    FakeWebSocket.instances[0].message({ type: "portfolio", data: {} });
    vi.setSystemTime(Date.now() + 60_000);
    env.win.dispatchEvent(new Event("online"));
    FakeWebSocket.instances[1].open();
    expect(seen).toEqual([lastMessage]);
    off();
    unsubscribe();
  });

  it("son dinleyici ayrılınca yaşam döngüsü dinleyicileri kaldırılır, sonra bağlanmaz", async () => {
    const live = await load();
    const unsubscribe = live.subscribeLive(() => undefined);
    FakeWebSocket.instances[0].open();
    unsubscribe();
    env.doc.dispatchEvent(new Event("visibilitychange"));
    env.win.dispatchEvent(new Event("online"));
    expect(FakeWebSocket.instances).toHaveLength(1);
  });
});

describe("reconnectDelayMs", () => {
  it("üstel artar, 30 sn tavanını (jitter hariç) aşmaz", async () => {
    const live = await load().catch(() => null);
    // Saf fonksiyon: ortam kurulumu gerektirmez.
    const mod = live ?? (await import("./liveSocket"));
    expect(mod.reconnectDelayMs(0, 0)).toBe(2_000);
    expect(mod.reconnectDelayMs(1, 0)).toBe(4_000);
    expect(mod.reconnectDelayMs(3, 0)).toBe(16_000);
    expect(mod.reconnectDelayMs(10, 0)).toBe(30_000);
    expect(mod.reconnectDelayMs(0, 0.999)).toBeLessThan(3_000);
  });
});
