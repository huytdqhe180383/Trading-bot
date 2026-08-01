import { describe, expect, it } from "vitest";
import { useTradingStore } from "./useTradingStore";

describe("useTradingStore", () => {
  it("starts the chart on the one-hour timeframe", () => {
    expect(useTradingStore.getState().interval).toBe("1h");
  });
});
