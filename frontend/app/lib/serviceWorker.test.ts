import { describe, expect, it } from "vitest";
import { serviceWorkerUrl } from "./serviceWorker";

describe("serviceWorkerUrl", () => {
  it("build ve vapid anahtarını sorguya koyar", () => {
    expect(serviceWorkerUrl("abc123", "BKey_-9")).toBe("/sw.js?v=abc123&vapid=BKey_-9");
  });
  it("vapid yoksa yalnız build", () => {
    expect(serviceWorkerUrl("abc123", "")).toBe("/sw.js?v=abc123");
  });
  it("build boşsa dev", () => {
    expect(serviceWorkerUrl("", "")).toBe("/sw.js?v=dev");
  });
  it("özel karakterleri kodlar", () => {
    expect(serviceWorkerUrl("1", "a+b/c")).toBe("/sw.js?v=1&vapid=a%2Bb%2Fc");
  });
});
