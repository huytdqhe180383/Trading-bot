import type { AnalystEvent, Candle, ChartAnnotation, ChartInterval, SymbolCode } from "./types";

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

/**
 * Return one current annotation set for the selected market.
 *
 * Analyst events are historical records. Rendering every record turns old
 * support/resistance opinions into a growing wall of chart lines, so the chart
 * uses only the newest event that actually contains valid annotations.
 */
export function selectVisibleChartAnnotations(
  events: AnalystEvent[],
  symbol: SymbolCode,
  mergeToleranceRatio = 0.0025,
): ChartAnnotation[] {
  const newestAnnotatedEvent = [...events]
    .filter((event) => event.symbol === symbol || event.symbol === "ALL")
    .sort((left, right) => Date.parse(right.created_at_utc) - Date.parse(left.created_at_utc))
    .find((event) => readChartAnnotations(event).length > 0);

  if (!newestAnnotatedEvent) return [];

  const visible: ChartAnnotation[] = [];
  for (const annotation of readChartAnnotations(newestAnnotatedEvent)) {
    const duplicate = visible.some((existing) => annotationsOverlap(existing, annotation, mergeToleranceRatio));
    if (!duplicate) visible.push(annotation);
  }
  return visible.slice(0, 6);
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

function readChartAnnotations(event: AnalystEvent): ChartAnnotation[] {
  const raw = event.payload?.chart_annotations;
  if (!Array.isArray(raw)) return [];
  return raw.filter(isChartAnnotation);
}

function isChartAnnotation(value: unknown): value is ChartAnnotation {
  if (!value || typeof value !== "object") return false;
  const item = value as Record<string, unknown>;
  const kind = item.kind;
  if ((kind === "support" || kind === "resistance") && typeof item.price === "number" && typeof item.label === "string") {
    return Number.isFinite(item.price);
  }
  return (
    kind === "trend" &&
    typeof item.start_time === "string" &&
    typeof item.end_time === "string" &&
    typeof item.start_price === "number" &&
    typeof item.end_price === "number" &&
    typeof item.label === "string"
  );
}

function annotationsOverlap(left: ChartAnnotation, right: ChartAnnotation, toleranceRatio: number): boolean {
  if (left.kind !== right.kind) return false;
  if (left.kind === "trend" && right.kind === "trend") {
    return left.start_time === right.start_time && left.end_time === right.end_time;
  }
  if (left.kind === "trend" || right.kind === "trend") return false;
  const referencePrice = Math.max(Math.abs(left.price), Math.abs(right.price), 1);
  return Math.abs(left.price - right.price) <= referencePrice * toleranceRatio;
}
