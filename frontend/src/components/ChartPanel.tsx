"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  IChartApi,
  ISeriesApi,
  ISeriesMarkersPluginApi,
  LineSeries,
  MouseEventParams,
  SeriesMarker,
  Time,
  UTCTimestamp,
} from "lightweight-charts";
import { fetchAnalystSignals, fetchCandles } from "@/lib/api";
import type { AnalystEvent, Candle } from "@/lib/types";
import { useTradingStore } from "@/store/useTradingStore";

type ChartPanelProps = {
  drawingEnabled: boolean;
  setError: (message: string) => void;
};

type DrawingPoint = {
  time: Time;
  value: number;
};

const markerColor: Record<string, string> = {
  BUY: "#10b981",
  SELL: "#ef4444",
  REDUCE: "#f59e0b",
  HOLD: "#94a3b8",
  AVOID: "#f97316",
};
const CANDLE_REFRESH_MS = 15_000;
const SIGNAL_REFRESH_MS = 10_000;

export default function ChartPanel({ drawingEnabled, setError }: ChartPanelProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick", Time> | null>(null);
  const markerApiRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const indicatorSeriesRef = useRef<ISeriesApi<"Line", Time>[]>([]);
  const drawingSeriesRef = useRef<ISeriesApi<"Line", Time>[]>([]);
  const pendingPointRef = useRef<DrawingPoint | null>(null);
  const [candles, setCandles] = useState<Candle[]>([]);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState("");
  const { symbol, interval, indicators, setEvents, events } = useTradingStore();

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#cbd5e1",
      },
      grid: {
        vertLines: { color: "rgba(148, 163, 184, 0.08)" },
        horzLines: { color: "rgba(148, 163, 184, 0.08)" },
      },
      rightPriceScale: {
        borderColor: "rgba(148, 163, 184, 0.15)",
      },
      timeScale: {
        borderColor: "rgba(148, 163, 184, 0.15)",
        timeVisible: true,
        secondsVisible: false,
      },
      crosshair: {
        mode: 1,
      },
    });
    const candlesSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#10b981",
      downColor: "#ef4444",
      wickUpColor: "#10b981",
      wickDownColor: "#ef4444",
      borderVisible: false,
    });

    chartRef.current = chart;
    candleSeriesRef.current = candlesSeries;
    markerApiRef.current = createSeriesMarkers(candlesSeries, []);

    const resizeObserver = new ResizeObserver(([entry]) => {
      chart.applyOptions({
        width: Math.floor(entry.contentRect.width),
        height: Math.floor(entry.contentRect.height),
      });
    });
    resizeObserver.observe(containerRef.current);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      markerApiRef.current = null;
      indicatorSeriesRef.current = [];
      drawingSeriesRef.current = [];
      pendingPointRef.current = null;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    let firstLoad = true;

    const refreshCandles = async () => {
      if (firstLoad) {
        setLoading(true);
      }
      setError("");
      try {
        const rows = await fetchCandles(symbol, interval, 500);
        if (cancelled) return;
        setCandles(rows);
        candleSeriesRef.current?.setData(
          rows.map((row) => ({
            time: row.time as UTCTimestamp,
            open: row.open,
            high: row.high,
            low: row.low,
            close: row.close,
          })),
        );
        setLastUpdated(new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }));
        if (firstLoad) {
          chartRef.current?.timeScale().fitContent();
        }
      } catch (error) {
        if (!cancelled) setError(error instanceof Error ? error.message : "Failed to load OKX candles.");
      } finally {
        firstLoad = false;
        if (!cancelled) setLoading(false);
      }
    };

    void refreshCandles();
    const timer = window.setInterval(() => {
      void refreshCandles();
    }, CANDLE_REFRESH_MS);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [interval, setError, symbol]);

  useEffect(() => {
    let cancelled = false;
    const refreshSignals = async () => {
      try {
        const signals = await fetchAnalystSignals();
        if (cancelled) return;
        setEvents(signals);
      } catch {
        // The sidebar will show auth/API problems; chart markers are advisory only.
      }
    };

    void refreshSignals();
    const timer = window.setInterval(() => {
      void refreshSignals();
    }, SIGNAL_REFRESH_MS);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [setEvents]);

  const markers = useMemo(() => buildMarkers(events, candles), [events, candles]);

  useEffect(() => {
    markerApiRef.current?.setMarkers(markers);
  }, [markers]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || candles.length === 0) return;

    indicatorSeriesRef.current.forEach((series) => chart.removeSeries(series));
    indicatorSeriesRef.current = [];

    if (indicators.sma20) {
      const series = chart.addSeries(LineSeries, { color: "#38bdf8", lineWidth: 2, priceLineVisible: false });
      series.setData(movingAverage(candles, 20));
      indicatorSeriesRef.current.push(series);
    }
    if (indicators.ema50) {
      const series = chart.addSeries(LineSeries, { color: "#f59e0b", lineWidth: 2, priceLineVisible: false });
      series.setData(exponentialMovingAverage(candles, 50));
      indicatorSeriesRef.current.push(series);
    }
  }, [candles, indicators.ema50, indicators.sma20]);

  useEffect(() => {
    const chart = chartRef.current;
    const candleSeries = candleSeriesRef.current;
    if (!chart || !candleSeries) return;

    const onClick = (param: MouseEventParams) => {
      if (!drawingEnabled || !param.point || !param.time) return;
      const value = candleSeries.coordinateToPrice(param.point.y);
      if (value === null) return;
      const nextPoint = { time: param.time, value };
      const previous = pendingPointRef.current;
      if (!previous) {
        pendingPointRef.current = nextPoint;
        return;
      }
      const line = chart.addSeries(LineSeries, {
        color: "#fbbf24",
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      line.setData([previous, nextPoint]);
      drawingSeriesRef.current.push(line);
      pendingPointRef.current = null;
    };

    chart.subscribeClick(onClick);
    return () => chart.unsubscribeClick(onClick);
  }, [drawingEnabled]);

  return (
    <div className="chart-card glass-panel">
      <div ref={containerRef} className="chart-container" />
      {loading && <div className="chart-empty">Loading OKX public candles...</div>}
      {!loading && candles.length === 0 && <div className="chart-empty">No candle data available.</div>}
      {lastUpdated && (
        <div className="status-pill" style={{ position: "absolute", right: 16, top: 16 }}>
          <span className="dot" />
          Live refresh {lastUpdated}
        </div>
      )}
      {drawingEnabled && (
        <div className="status-pill" style={{ position: "absolute", left: 16, top: 16 }}>
          <span className="dot" style={{ background: "#f59e0b", boxShadow: "0 0 12px #f59e0b" }} />
          Trendline: click two chart points
        </div>
      )}
    </div>
  );
}

function buildMarkers(events: AnalystEvent[], candles: Candle[]): SeriesMarker<Time>[] {
  const candleTimes = candles.map((row) => row.time);
  return events
    .filter((event) => event.recommendation)
    .map((event) => {
      const recommendation = String(event.recommendation || "HOLD");
      const eventTime = Math.floor(new Date(event.created_at_utc).getTime() / 1000);
      const time = nearestTime(eventTime, candleTimes) as UTCTimestamp;
      const isBullish = recommendation === "BUY";
      const isBearish = recommendation === "SELL" || recommendation === "AVOID";
      return {
        time,
        position: isBullish ? "belowBar" : "aboveBar",
        color: markerColor[recommendation] || "#94a3b8",
        shape: isBullish ? "arrowUp" : isBearish ? "arrowDown" : "circle",
        text: `${recommendation} - ${event.role}`,
      };
    });
}

function nearestTime(target: number, times: number[]): number {
  if (times.length === 0) return target;
  return times.reduce((best, current) => (Math.abs(current - target) < Math.abs(best - target) ? current : best), times[0]);
}

function movingAverage(candles: Candle[], period: number) {
  const rows = [];
  for (let index = period - 1; index < candles.length; index += 1) {
    const window = candles.slice(index - period + 1, index + 1);
    const value = window.reduce((sum, row) => sum + row.close, 0) / period;
    rows.push({ time: candles[index].time as UTCTimestamp, value });
  }
  return rows;
}

function exponentialMovingAverage(candles: Candle[], period: number) {
  if (candles.length < period) return [];
  const multiplier = 2 / (period + 1);
  const rows = [];
  let ema = candles.slice(0, period).reduce((sum, row) => sum + row.close, 0) / period;
  rows.push({ time: candles[period - 1].time as UTCTimestamp, value: ema });
  for (let index = period; index < candles.length; index += 1) {
    ema = (candles[index].close - ema) * multiplier + ema;
    rows.push({ time: candles[index].time as UTCTimestamp, value: ema });
  }
  return rows;
}
