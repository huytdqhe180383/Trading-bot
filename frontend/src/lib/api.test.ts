import { beforeEach, describe, expect, it, vi } from "vitest";
import { askAnalyst, explainAnalystEvent, fetchCandles, fetchLatestNews, validateAnalystEvent } from "./api";

describe("analyst web API client", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("fetches chart candles from the current repo market endpoint", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ candles: [{ time: 1800000000, close: 100, source: "okx_public" }] }),
    } as Response);

    const candles = await fetchCandles("BTCUSDT", "1h", 50);

    expect(candles[0].source).toBe("okx_public");
    expect(String(fetchMock.mock.calls[0][0])).toContain("/api/market/candles");
    expect(String(fetchMock.mock.calls[0][0])).toContain("symbol=BTCUSDT");
  });

  it("sends analyst ask without execution fields", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ id: "1", status: "ok" }),
    } as Response);

    await askAnalyst("ETHUSDT", "What changed?");

    const body = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
    expect(body).toEqual({ symbol: "ETHUSDT", question: "What changed?" });
    expect(JSON.stringify(body)).not.toMatch(/quantity|leverage|order|allocation/i);
  });

  it("uses explicit explain, validate, and latest-news controls", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ id: "1", status: "ok" }),
    } as Response);

    await explainAnalystEvent("abc");
    await validateAnalystEvent("BTCUSDT", "abc");
    await fetchLatestNews("BTCUSDT");

    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({ explain_alert_id: "abc" });
    expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body))).toEqual({ symbol: "BTCUSDT", validate_alert_id: "abc" });
    expect(JSON.parse(String(fetchMock.mock.calls[2][1]?.body))).toEqual({ symbol: "BTCUSDT", latest_news: true });
  });
});
