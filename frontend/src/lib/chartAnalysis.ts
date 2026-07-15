import type { Candle, ChartInterval } from "./types";

export type SupportResistanceLine = {
  price: number;
  kind: "support" | "resistance";
  touches: number;
};

const INTERVAL_PATTERN = /\b(1m|5m|15m|1h|4h|1d)\b/i;

export function parseSupportResistanceInterval(message: string): ChartInterval | null {
  if (!/(support|resistance|s\/r|\bsr\b)/i.test(message)) return null;
  const match = message.match(INTERVAL_PATTERN);
  return (match?.[1]?.toLowerCase() as ChartInterval | undefined) || null;
}

export function wantsSupportResistance(message: string): boolean {
  return /(support|resistance|s\/r|\bsr\b)/i.test(message);
}

export function calculateSupportResistance(candles: Candle[], maxLines = 6): SupportResistanceLine[] {
  if (candles.length < 12) return [];
  const recent = candles.slice(-180);
  const pivots: SupportResistanceLine[] = [];

  for (let index = 2; index < recent.length - 2; index += 1) {
    const row = recent[index];
    const isPivotLow =
      row.low <= recent[index - 1].low &&
      row.low <= recent[index - 2].low &&
      row.low <= recent[index + 1].low &&
      row.low <= recent[index + 2].low;
    const isPivotHigh =
      row.high >= recent[index - 1].high &&
      row.high >= recent[index - 2].high &&
      row.high >= recent[index + 1].high &&
      row.high >= recent[index + 2].high;

    if (isPivotLow) pivots.push({ price: row.low, kind: "support", touches: 1 });
    if (isPivotHigh) pivots.push({ price: row.high, kind: "resistance", touches: 1 });
  }

  if (pivots.length === 0) {
    const lows = recent.map((row) => row.low).sort((a, b) => a - b);
    const highs = recent.map((row) => row.high).sort((a, b) => b - a);
    const fallback: SupportResistanceLine[] = [
      { price: lows[Math.floor(lows.length * 0.1)], kind: "support", touches: 1 },
      { price: highs[Math.floor(highs.length * 0.1)], kind: "resistance", touches: 1 },
    ];
    return fallback.filter((line) => Number.isFinite(line.price));
  }

  const close = recent.at(-1)?.close || pivots.at(-1)?.price || 1;
  const tolerance = close * 0.0025;
  const clusters: SupportResistanceLine[] = [];
  for (const pivot of pivots) {
    const cluster = clusters.find((line) => line.kind === pivot.kind && Math.abs(line.price - pivot.price) <= tolerance);
    if (cluster) {
      cluster.price = (cluster.price * cluster.touches + pivot.price) / (cluster.touches + 1);
      cluster.touches += 1;
    } else {
      clusters.push({ ...pivot });
    }
  }

  const supports = clusters
    .filter((line) => line.kind === "support")
    .sort((left, right) => right.touches - left.touches || Math.abs(close - left.price) - Math.abs(close - right.price))
    .slice(0, Math.ceil(maxLines / 2));
  const resistances = clusters
    .filter((line) => line.kind === "resistance")
    .sort((left, right) => right.touches - left.touches || Math.abs(close - left.price) - Math.abs(close - right.price))
    .slice(0, Math.floor(maxLines / 2));

  return [...supports, ...resistances].sort((left, right) => left.price - right.price);
}
