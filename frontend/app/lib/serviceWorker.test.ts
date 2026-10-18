import { describe, expect, it } from "vitest";
import { MIN_UPDATE_CHECK_GAP_MS, SERVICE_WORKER_URL, shouldRunUpdateCheck } from "./serviceWorker";

describe("serviceWorker", () => {
  it("SW adresi sabit: sorgu (build/vapid) yok", () => {
    expect(SERVICE_WORKER_URL).toBe("/sw.js");
  });

  it("sürüm denetimi: hiç yapılmadıysa çalışır", () => {
    expect(shouldRunUpdateCheck(0, 1_000)).toBe(true);
  });
  it("sürüm denetimi: aralık dolmadan tekrarlanmaz", () => {
    expect(shouldRunUpdateCheck(10_000, 10_000 + MIN_UPDATE_CHECK_GAP_MS - 1)).toBe(false);
  });
  it("sürüm denetimi: aralık dolunca çalışır", () => {
    expect(shouldRunUpdateCheck(10_000, 10_000 + MIN_UPDATE_CHECK_GAP_MS)).toBe(true);
  });
});
