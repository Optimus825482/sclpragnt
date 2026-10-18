import { describe, expect, it } from "vitest";
import { firstOnboardingStep, iosSupportsWebPush, isIOSLike, parseIosVersion } from "./push";

const IPHONE_SAFARI = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1";
const IPHONE_CHROME = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/126.0.0.0 Mobile/15E148 Safari/604.1";
const IPAD_DESKTOP_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15";
const MAC_SAFARI = IPAD_DESKTOP_UA;
const IPHONE_OLD = "Mozilla/5.0 (iPhone; CPU iPhone OS 15_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.6 Mobile/15E148 Safari/604.1";
const IPHONE_16_3 = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.3 Mobile/15E148 Safari/604.1";
const IPHONE_16_4 = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.4 Mobile/15E148 Safari/604.1";

describe("isIOSLike (iPadOS algısı)", () => {
  it("iPhone/iPad UA'sı iOS'tur", () => {
    expect(isIOSLike(IPHONE_SAFARI)).toBe(true);
    expect(isIOSLike(IPHONE_CHROME)).toBe(true);
  });
  it("iPadOS masaüstü UA'sı (Macintosh) + dokunmatik = iOS", () => {
    expect(isIOSLike(IPAD_DESKTOP_UA, "MacIntel", 5)).toBe(true);
  });
  it("gerçek Mac (dokunma yok) iOS değildir", () => {
    expect(isIOSLike(MAC_SAFARI, "MacIntel", 0)).toBe(false);
  });
  it("Android iOS değildir", () => {
    expect(isIOSLike("Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/126.0 Mobile Safari/537.36", "Linux armv8l", 5)).toBe(false);
  });
});

describe("iOS sürüm kontrolü (>= 16.4)", () => {
  it("sürümü ayrıştırır", () => {
    expect(parseIosVersion(IPHONE_SAFARI)).toEqual({ major: 17, minor: 4 });
    expect(parseIosVersion(IPAD_DESKTOP_UA)).toEqual({ major: 17, minor: 4 });
    expect(parseIosVersion("Mozilla/5.0 (X11; Linux x86_64)")).toBeNull();
  });
  it("16.4 ve üstü destekler", () => {
    expect(iosSupportsWebPush(IPHONE_16_4)).toBe(true);
    expect(iosSupportsWebPush(IPHONE_SAFARI)).toBe(true);
  });
  it("16.3 ve altı desteklemez", () => {
    expect(iosSupportsWebPush(IPHONE_16_3)).toBe(false);
    expect(iosSupportsWebPush(IPHONE_OLD)).toBe(false);
  });
  it("sürüm okunamazsa engellemez", () => {
    expect(iosSupportsWebPush("garip bir ua")).toBe(true);
  });
});

describe("firstOnboardingStep", () => {
  it("iPhone Safari, kurulu değil → 'Chrome' uyarısı YOK, kurulum yönergesi; bildirim adımı YOK", () => {
    expect(firstOnboardingStep({ ios: true, iosPushOk: true, browser: "safari", standalone: false })).toBe("install");
  });
  it("iPhone'da iOS Chrome (CriOS) da 'Chrome önerilir' görmez", () => {
    expect(firstOnboardingStep({ ios: true, iosPushOk: true, browser: "safari", standalone: false })).not.toBe("browser_warn");
  });
  it("iPhone kurulu (standalone) → bildirim adımı", () => {
    expect(firstOnboardingStep({ ios: true, iosPushOk: true, browser: "safari", standalone: true })).toBe("notify");
  });
  it("iOS < 16.4 → güncelleme bilgisi (kurulu olsa bile)", () => {
    expect(firstOnboardingStep({ ios: true, iosPushOk: false, browser: "safari", standalone: true })).toBe("ios_old");
    expect(firstOnboardingStep({ ios: true, iosPushOk: false, browser: "safari", standalone: false })).toBe("ios_old");
  });
  it("Android Chrome: kurulu değil → kurulum, kurulu → bildirim", () => {
    expect(firstOnboardingStep({ ios: false, iosPushOk: true, browser: "chrome", standalone: false })).toBe("install");
    expect(firstOnboardingStep({ ios: false, iosPushOk: true, browser: "chrome", standalone: true })).toBe("notify");
  });
  it("Android'de Chrome dışı tarayıcı → eski tarayıcı uyarısı korunur", () => {
    expect(firstOnboardingStep({ ios: false, iosPushOk: true, browser: "other", standalone: false })).toBe("browser_warn");
  });
});
