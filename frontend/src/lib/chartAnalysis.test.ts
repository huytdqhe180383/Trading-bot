import { describe, expect, it } from "vitest";
import { calculateSupportResistance, parseSupportResistanceInterval, wantsSupportResistance } from "./chartAnalysis";
import type { Candle } from "./types";

function candle(index: number, low: number, high: number, close = (low + high) / 2): Candle {
  return {
    time: 1800000000 + index * 60,
    timestamp_ms: (1800000000 + index * 60) * 1000,
    open: close,
    high,
    low,
    close,
    volume: 10 + index,
    symbol: "BTCUSDT",
    source: "okx_public",
  };
}

describe("chartAnalysis", () => {
  it("detects support/resistance requests and timeframe", () => {
    expect(wantsSupportResistance("draw support and resistance on 1h frame")).toBe(true);
    expect(parseSupportResistanceInterval("draw support and resistance on 1h frame")).toBe("1h");
    expect(parseSupportResistanceInterval("what is the trend?")).toBeNull();
  });

  it("calculates support and resistance lines from pivots", () => {
    const candles = [
      candle(0, 100, 110),
      candle(1, 98, 112),
      candle(2, 95, 115),
      candle(3, 99, 111),
      candle(4, 101, 109),
      candle(5, 102, 120),
      candle(6, 103, 118),
      candle(7, 97, 113),
      candle(8, 94, 116),
      candle(9, 98, 112),
      candle(10, 100, 108),
      candle(11, 101, 121),
      candle(12, 102, 117),
    ];

    const lines = calculateSupportResistance(candles);

    expect(lines.some((line) => line.kind === "support")).toBe(true);
    expect(lines.some((line) => line.kind === "resistance")).toBe(true);
  });
});
