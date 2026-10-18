import { describe, expect, it } from "vitest";
import { CHUNK_RELOAD_COOLDOWN_MS, claimChunkReload, isChunkLoadError } from "./chunkError";

function memoryStorage(initial: Record<string, string> = {}) {
  const data = { ...initial };
  return {
    getItem: (k: string) => (k in data ? data[k] : null),
    setItem: (k: string, v: string) => { data[k] = v; },
  };
}

describe("isChunkLoadError", () => {
  it("webpack ChunkLoadError adı", () => {
    const e = new Error("x"); e.name = "ChunkLoadError";
    expect(isChunkLoadError(e)).toBe(true);
  });
  it("Loading chunk … failed mesajı", () => {
    expect(isChunkLoadError(new Error("Loading chunk 123 failed.\n(error: /_next/static/chunks/123.js)"))).toBe(true);
  });
  it("dinamik import hatası (Safari/Chrome ifadeleri)", () => {
    expect(isChunkLoadError(new TypeError("Failed to fetch dynamically imported module: https://x/a.js"))).toBe(true);
    expect(isChunkLoadError(new TypeError("Importing a module script failed."))).toBe(true);
  });
  it("sıradan hata chunk hatası değildir", () => {
    expect(isChunkLoadError(new Error("Cannot read properties of undefined"))).toBe(false);
    expect(isChunkLoadError(null)).toBe(false);
  });
});

describe("claimChunkReload (tek seferlik yenileme)", () => {
  it("ilk hatada izin verir ve zamanı yazar", () => {
    const s = memoryStorage();
    expect(claimChunkReload(s, 1_000_000)).toBe(true);
    expect(s.getItem("scalper_chunk_reload_at")).toBe("1000000");
  });
  it("yenilemeden hemen sonraki ikinci hatada izin vermez (döngü koruması)", () => {
    const s = memoryStorage();
    claimChunkReload(s, 1_000_000);
    expect(claimChunkReload(s, 1_000_000 + 5_000)).toBe(false);
  });
  it("bekleme süresi dolunca (yeni deploy) tekrar izin verir", () => {
    const s = memoryStorage();
    claimChunkReload(s, 1_000_000);
    expect(claimChunkReload(s, 1_000_000 + CHUNK_RELOAD_COOLDOWN_MS)).toBe(true);
  });
  it("depolama yoksa yenilemez", () => {
    expect(claimChunkReload(null)).toBe(false);
  });
});
