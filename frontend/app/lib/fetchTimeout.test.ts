import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createRequestDeadline, fetchWithTimeout, isTimeoutError } from "./fetchTimeout";

/** İptal sinyaline duyarlı sahte fetch: hiç yanıt vermez, abort'ta reddeder. */
function hangingFetch() {
  return vi.fn((_input: unknown, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
    init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
  })) as unknown as typeof fetch;
}

describe("fetchWithTimeout", () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); });

  it("süre dolunca TimeoutError ile reddeder", async () => {
    const promise = fetchWithTimeout(hangingFetch(), "/x", undefined, 1000);
    const caught = promise.catch((e) => e);
    await vi.advanceTimersByTimeAsync(1000);
    const error = await caught;
    expect(isTimeoutError(error)).toBe(true);
  });

  it("yanıt gelirse zamanlayıcı temizlenir ve yanıt döner", async () => {
    const response = { ok: true } as Response;
    const impl = vi.fn().mockResolvedValue(response) as unknown as typeof fetch;
    await expect(fetchWithTimeout(impl, "/x", undefined, 1000)).resolves.toBe(response);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("çağıranın kendi iptali AbortError olarak kalır (zaman aşımı sayılmaz)", async () => {
    const outer = new AbortController();
    const caught = fetchWithTimeout(hangingFetch(), "/x", { signal: outer.signal }, 5000).catch((e) => e);
    outer.abort();
    const error = await caught;
    expect(isTimeoutError(error)).toBe(false);
    expect((error as Error).name).toBe("AbortError");
  });

  it("süre 0/undefined ise sarmalamadan doğrudan çağırır", async () => {
    const impl = vi.fn().mockResolvedValue({ ok: true }) as unknown as typeof fetch;
    await fetchWithTimeout(impl, "/x", { method: "POST" }, 0);
    await fetchWithTimeout(impl, "/y", undefined, undefined);
    expect((impl as unknown as ReturnType<typeof vi.fn>).mock.calls[0][1]).toEqual({ method: "POST" });
    expect(vi.getTimerCount()).toBe(0);
  });
});

describe("createRequestDeadline compatibility fallback", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal("AbortSignal", {});
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("propagates caller cancellation and disposes the pending timer", () => {
    const parent = new AbortController();
    const deadline = createRequestDeadline(5000, parent.signal);
    const reason = new DOMException("Navigation changed", "AbortError");
    parent.abort(reason);
    expect(deadline.signal.reason).toBe(reason);
    deadline.dispose?.();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("times out while a response is being read", async () => {
    const deadline = createRequestDeadline(5000);
    await vi.advanceTimersByTimeAsync(5000);
    expect(isTimeoutError(deadline.signal.reason)).toBe(true);
  });
});
