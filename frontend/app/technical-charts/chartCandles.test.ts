import { beforeEach, describe, expect, it, vi } from "vitest";
import { getJSON } from "../lib/api";
import { requestChartCandles } from "./chartCandles";

vi.mock("../lib/api", () => ({ getJSON: vi.fn() }));

const fetchJson = vi.mocked(getJSON);

beforeEach(() => {
  fetchJson.mockReset();
});

describe("requestChartCandles", () => {
  it("shares concurrent requests and fetches fresh data after completion", async () => {
    fetchJson.mockResolvedValue({ candles: [[123, 1, 2, 1, 2, 4]] });

    const first = requestChartCandles("BTCTRY", "5m");
    const overlapping = requestChartCandles("BTCTRY", "5m");
    expect(first).toBe(overlapping);
    await expect(first).resolves.toHaveLength(1);
    expect(fetchJson).toHaveBeenCalledTimes(1);

    await requestChartCandles("BTCTRY", "5m");
    expect(fetchJson).toHaveBeenCalledTimes(2);
  });

  it("separates timeframes and symbols and allows retry after failure", async () => {
    fetchJson.mockRejectedValueOnce(new Error("HTTP 503"));
    fetchJson.mockResolvedValue({ candles: [] });

    const failed = requestChartCandles("BTCTRY", "5m");
    const otherInterval = requestChartCandles("BTCTRY", "15m");
    const otherSymbol = requestChartCandles("ETHTRY", "5m");
    await expect(failed).rejects.toThrow("HTTP 503");
    await Promise.all([otherInterval, otherSymbol]);
    expect(fetchJson).toHaveBeenCalledTimes(3);

    await expect(requestChartCandles("BTCTRY", "5m")).resolves.toEqual([]);
    expect(fetchJson).toHaveBeenCalledTimes(4);
  });
});
