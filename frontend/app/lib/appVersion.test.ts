import { describe, expect, it, vi } from "vitest";
import { fetchRemoteBuild, shouldOfferUpdate } from "./appVersion";

describe("shouldOfferUpdate", () => {
  it("kimlikler farklıysa şerit çıkar", () => {
    expect(shouldOfferUpdate("aaa-1", "bbb-2")).toBe(true);
  });
  it("aynı kimlikte çıkmaz", () => {
    expect(shouldOfferUpdate("aaa-1", "aaa-1")).toBe(false);
  });
  it("uzak kimlik yok/boşsa çıkmaz", () => {
    expect(shouldOfferUpdate("aaa-1", null)).toBe(false);
    expect(shouldOfferUpdate("aaa-1", "")).toBe(false);
    expect(shouldOfferUpdate("aaa-1", undefined)).toBe(false);
  });
  it("geliştirme (dev) kimliğinde çıkmaz", () => {
    expect(shouldOfferUpdate("dev", "bbb-2")).toBe(false);
    expect(shouldOfferUpdate("aaa-1", "dev")).toBe(false);
  });
});

describe("fetchRemoteBuild", () => {
  const ok = (body: unknown) => vi.fn().mockResolvedValue({ ok: true, json: async () => body });

  it("build alanını okur ve önbelleği atlar", async () => {
    const fetchImpl = ok({ build: "zzz-9" });
    expect(await fetchRemoteBuild(fetchImpl as unknown as typeof fetch)).toBe("zzz-9");
    expect(fetchImpl.mock.calls[0][0]).toBe("/build-id.json");
    expect(fetchImpl.mock.calls[0][1]).toMatchObject({ cache: "no-store" });
  });
  it("HTTP hatasında null", async () => {
    const fetchImpl = vi.fn().mockResolvedValue({ ok: false, json: async () => ({}) });
    expect(await fetchRemoteBuild(fetchImpl as unknown as typeof fetch)).toBeNull();
  });
  it("ağ hatasında null (sessiz)", async () => {
    const fetchImpl = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    expect(await fetchRemoteBuild(fetchImpl as unknown as typeof fetch)).toBeNull();
  });
  it("bozuk gövdede null", async () => {
    expect(await fetchRemoteBuild(ok({ build: 5 }) as unknown as typeof fetch)).toBeNull();
    expect(await fetchRemoteBuild(ok(null) as unknown as typeof fetch)).toBeNull();
  });
  it("zaman aşımında istek iptal edilir ve null döner", async () => {
    const fetchImpl = vi.fn((_url: string, init?: RequestInit) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
    }));
    expect(await fetchRemoteBuild(fetchImpl as unknown as typeof fetch, 20)).toBeNull();
  });
});
