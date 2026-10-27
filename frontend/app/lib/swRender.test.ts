import { readFileSync } from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderServiceWorker } from "./swRender";

const TEMPLATE = readFileSync(path.join(__dirname, "..", "sw.js", "sw.template.js"), "utf8");

type Handler = (event: any) => void;

/** Şablonu sahte SW ortamında çalıştırır; kayıtlı olay dinleyicilerini ve sahte önbelleği döndürür. */
function bootServiceWorker(
  build: string,
  vapid = "",
  fetchImpl?: (req: any) => Promise<any>,
  env: { windows?: any[]; userAgent?: string } = {},
) {
  const handlers: Record<string, Handler> = {};
  const stores = new Map<string, Map<string, any>>();
  const cachesStub = {
    open: async (name: string) => {
      if (!stores.has(name)) stores.set(name, new Map());
      const store = stores.get(name)!;
      return {
        put: async (req: any, res: any) => { store.set(typeof req === "string" ? req : req.url, res); },
        add: async () => undefined,
      };
    },
    keys: async () => [...stores.keys()],
    delete: async (name: string) => stores.delete(name),
    match: async (req: any) => {
      const key = typeof req === "string" ? req : req.url;
      for (const store of stores.values()) if (store.has(key)) return store.get(key);
      return undefined;
    },
  };
  const posted: unknown[] = [];
  const notifications: Array<{ title: string; options: any }> = [];
  const closed: string[] = [];
  const self = {
    navigator: { userAgent: env.userAgent ?? "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/126.0 Mobile Safari/537.36" },
    location: new URL("https://app.example/sw.js"),
    addEventListener: (type: string, fn: Handler) => { handlers[type] = fn; },
    skipWaiting: async () => undefined,
    clients: {
      claim: async () => undefined,
      matchAll: async () => env.windows ?? [{ postMessage: (m: unknown) => posted.push(m) }],
    },
    registration: {
      showNotification: async (title: string, options: any) => { notifications.push({ title, options }); },
      getNotifications: async (filter?: { tag?: string }) => notifications
        .filter((n) => !filter?.tag || n.options.tag === filter.tag)
        .map((n) => ({ close: () => { closed.push(n.options.tag); } })),
    },
  };
  const context: Record<string, unknown> = {
    self, caches: cachesStub, clients: self.clients, Request, Response, URL, Promise, setTimeout, clearTimeout,
    fetch: fetchImpl ?? (async () => ({ ok: true, type: "basic", redirected: false, clone() { return this; } })),
    atob, Uint8Array, console,
  };
  vm.runInNewContext(renderServiceWorker(TEMPLATE, build, vapid), context);
  return { handlers, stores, posted, notifications, closed };
}

function fetchEvent(url: string, init: { mode?: string; destination?: string } = {}) {
  let responded: Promise<unknown> | undefined;
  const pending: Promise<unknown>[] = [];
  const request = {
    url,
    method: "GET",
    mode: init.mode ?? "same-origin",
    destination: init.destination ?? "",
    headers: new Headers(),
  };
  return {
    request,
    respondWith: (p: Promise<unknown>) => { responded = p; },
    waitUntil: (p: Promise<unknown>) => { pending.push(p); },
    get responded() { return responded; },
    settle: () => Promise.all(pending),
  };
}

describe("renderServiceWorker", () => {
  it("build ve VAPID gömülür, jeton kalmaz", () => {
    const out = renderServiceWorker(TEMPLATE, "abc-1", "BKey_-9");
    expect(out).toContain('var BUILD = "abc-1";');
    expect(out).toContain('var VAPID_KEY = "BKey_-9";');
    expect(out).not.toContain("__SW_BUILD__");
    expect(out).not.toContain("__SW_VAPID__");
  });
  it("her build'de çıktı baytları değişir (tarayıcı güncellemesi için şart)", () => {
    expect(renderServiceWorker(TEMPLATE, "a-1", "k")).not.toBe(renderServiceWorker(TEMPLATE, "b-2", "k"));
  });
  it("değerdeki tırnak şablonu bozmaz", () => {
    const out = renderServiceWorker(TEMPLATE, 'x"y', "");
    expect(() => new vm.Script(out)).not.toThrow();
    expect(out).toContain('var BUILD = "x\\"y";');
  });
  it("boş build dev olur", () => {
    expect(renderServiceWorker(TEMPLATE, "", "")).toContain('var BUILD = "dev";');
  });
});

describe("sw.js davranışı (sahte SW ortamı)", () => {
  it("activate: istemcilere SW_VERSION gönderir", async () => {
    const sw = bootServiceWorker("b-7");
    let done: Promise<unknown> = Promise.resolve();
    sw.handlers.activate({ waitUntil: (p: Promise<unknown>) => { done = p; } });
    await done;
    expect(sw.posted).toEqual([{ type: "SW_VERSION", build: "b-7" }]);
  });

  it("activate: eski önbellekleri siler, bir önceki nesli tutar", async () => {
    const sw = bootServiceWorker("b-3");
    for (const name of ["scalper-agent-v4-shell-b-1", "scalper-agent-v4-shell-b-2", "scalper-agent-v4-shell-b-3", "baska"]) {
      sw.stores.set(name, new Map());
    }
    let done: Promise<unknown> = Promise.resolve();
    sw.handlers.activate({ waitUntil: (p: Promise<unknown>) => { done = p; } });
    await done;
    expect([...sw.stores.keys()].sort()).toEqual(["baska", "scalper-agent-v4-shell-b-2", "scalper-agent-v4-shell-b-3"]);
  });

  it("/api isteklerine ve /ws'ye dokunmaz (navigasyon olsa bile)", () => {
    const sw = bootServiceWorker("b-1");
    for (const p of ["/api/export.csv", "/ws"]) {
      const ev = fetchEvent(`https://app.example${p}`, { mode: "navigate", destination: "document" });
      sw.handlers.fetch(ev);
      expect(ev.responded).toBeUndefined();
    }
  });

  it("navigasyonda yalnız ok+basic yanıtı önbelleğe koyar (yol anahtarıyla)", async () => {
    const good = { ok: true, type: "basic", redirected: false, clone() { return this; } };
    const sw = bootServiceWorker("b-1", "", async () => good);
    const ev = fetchEvent("https://app.example/charts?symbol=BTCTRY", { mode: "navigate", destination: "document" });
    sw.handlers.fetch(ev);
    await ev.responded;
    await ev.settle();
    expect(sw.stores.get("scalper-agent-v4-shell-b-1")?.has("https://app.example/charts")).toBe(true);
  });

  it("404/503 hata sayfası ve yönlendirilmiş yanıt önbelleğe girmez", async () => {
    for (const bad of [
      { ok: false, status: 503, type: "basic", redirected: false },
      { ok: true, type: "basic", redirected: true },
      { ok: true, type: "opaque", redirected: false },
    ]) {
      const res = { ...bad, clone() { return this; } };
      const sw = bootServiceWorker("b-1", "", async () => res);
      const ev = fetchEvent("https://app.example/portfolio", { mode: "navigate", destination: "document" });
      sw.handlers.fetch(ev);
      await ev.responded;
      await ev.settle();
      expect(sw.stores.get("scalper-agent-v4-shell-b-1")?.size ?? 0).toBe(0);
    }
  });

  it("ağ hiç yanıt vermezse (lie-fi) zaman aşımından sonra önbellekteki sayfa sunulur", async () => {
    const sw = bootServiceWorker("b-1", "", () => new Promise(() => undefined));
    const cached = { ok: true, tag: "cached" };
    sw.stores.set("scalper-agent-v4-shell-b-1", new Map([["https://app.example/portfolio", cached]]));
    const ev = fetchEvent("https://app.example/portfolio", { mode: "navigate", destination: "document" });
    sw.handlers.fetch(ev);
    expect(await ev.responded).toBe(cached);
  }, 10_000);

  it("ağ hatası + önbellek yok → geçerli (503) Response döner, undefined değil", async () => {
    const sw = bootServiceWorker("b-1", "", async () => { throw new TypeError("offline"); });
    const ev = fetchEvent("https://app.example/x", { mode: "navigate", destination: "document" });
    sw.handlers.fetch(ev);
    const res = (await ev.responded) as Response;
    expect(res.status).toBe(503);
  });
});

function pushEvent(payload: Record<string, unknown>) {
  let done: Promise<unknown> = Promise.resolve();
  return {
    data: { json: () => payload, text: () => JSON.stringify(payload) },
    waitUntil: (p: Promise<unknown>) => { done = p; },
    get done() { return done; },
  };
}

describe("push bildirimi (sahte SW ortamı)", () => {
  it("ikon ve rozet PNG'dir (Android SVG desteklemez), `sound` alanı yoktur", async () => {
    const sw = bootServiceWorker("b-1");
    const ev = pushEvent({ title: "Radar", body: "BTCTRY", tag: "radar-BTCTRY", url: "/charts?symbol=BTCTRY" });
    sw.handlers.push(ev);
    await ev.done;
    expect(sw.notifications).toHaveLength(1);
    const { options } = sw.notifications[0];
    expect(options.icon).toMatch(/\.png$/);
    expect(options.badge).toMatch(/\.png$/);
    expect(options).not.toHaveProperty("sound");
    expect(options.data.url).toBe("/charts?symbol=BTCTRY");
  });
});

describe("sayfa görünürken push (iOS bildirimsiz push riski)", () => {
  const IOS_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1";
  const CHROME_UA = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36";
  const visibleWindow = { url: "https://app.example/charts", visibilityState: "visible", focused: true };
  const hiddenWindow = { url: "https://app.example/charts", visibilityState: "hidden", focused: false };

  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); });

  it("iOS + sayfa görünür: bildirim YİNE gösterilir (sessiz) ve kısa süre sonra kapatılır", async () => {
    const sw = bootServiceWorker("b-1", "", undefined, { windows: [visibleWindow], userAgent: IOS_UA });
    const ev = pushEvent({ title: "Radar", body: "BTCTRY", tag: "radar-BTCTRY" });
    sw.handlers.push(ev);
    await vi.advanceTimersByTimeAsync(10_000);
    await ev.done;
    expect(sw.notifications).toHaveLength(1); // userVisibleOnly: her push bildirim gösterir
    const { options } = sw.notifications[0];
    expect(options.silent).toBe(true);
    expect(options.vibrate).toBeUndefined();
    expect(options.renotify).toBe(false);
    expect(sw.closed).toEqual(["radar-BTCTRY"]);
  });

  it("Chrome/Android + sayfa görünür: eskisi gibi bildirim atlanır (çift duyuru yok)", async () => {
    const sw = bootServiceWorker("b-1", "", undefined, { windows: [visibleWindow], userAgent: CHROME_UA });
    const ev = pushEvent({ title: "Radar", body: "BTCTRY", tag: "radar-BTCTRY" });
    sw.handlers.push(ev);
    await ev.done;
    expect(sw.notifications).toHaveLength(0);
  });

  it("iOS + sayfa görünür değil: normal (sesli) bildirim", async () => {
    const sw = bootServiceWorker("b-1", "", undefined, { windows: [hiddenWindow], userAgent: IOS_UA });
    const ev = pushEvent({ title: "Radar", body: "BTCTRY", tag: "radar-BTCTRY" });
    sw.handlers.push(ev);
    await ev.done;
    expect(sw.notifications).toHaveLength(1);
    expect(sw.notifications[0].options.silent).toBe(false);
    expect(sw.notifications[0].options.vibrate).toBeDefined();
    expect(sw.closed).toEqual([]);
  });
});

describe("sw şablonu: Alım yap derin bağlantısı", () => {
  it("plan_key varsa &key= (URL-kodlu) eklenir", () => {
    expect(TEMPLATE).toContain('if (data.plan_key) buyUrl += "&key=" + encodeURIComponent(String(data.plan_key));');
  });
});

describe("push: Alım yap aksiyonu", () => {
  it("TRY sembollü sinyal bildiriminde Alım yap + plan anahtarı", async () => {
    const sw = bootServiceWorker("b-1");
    const ev = pushEvent({ title: "Radar", body: "x", tag: "radar-ADATRY", symbol: "ADA_TRY", plan_key: "k1" });
    sw.handlers.push(ev);
    await ev.done;
    const { options } = sw.notifications[0];
    expect(options.actions.map((a: any) => a.action)).toEqual(["buy", "open"]);
    expect(options.data.buyUrl).toBe("/?buy=ADATRY&key=k1");
  });

  it("gerçek pozisyon çıkış hatırlatıcısında Alım yap YOK", async () => {
    const sw = bootServiceWorker("b-1");
    const ev = pushEvent({ title: "Çıkış zamanı", body: "x", tag: "exit-ADATRY-c1", url: "/binance-tr",
      source: "real_exit_reminder", symbol: "ADA_TRY", stage: "stage1" });
    sw.handlers.push(ev);
    await ev.done;
    const { options } = sw.notifications[0];
    expect(options.actions).toBeUndefined();
    expect(options.data.buyUrl).toBeUndefined();
    expect(options.data.url).toBe("/binance-tr");
  });
});
