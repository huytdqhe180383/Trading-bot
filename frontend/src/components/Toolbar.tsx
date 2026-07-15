"use client";

import { Bot, LineChart, Newspaper, PenLine, RefreshCcw } from "lucide-react";
import { fetchLatestNews, runAnalystUpdate } from "@/lib/api";
import type { ChartInterval, IndicatorKey, SymbolCode } from "@/lib/types";
import { useTradingStore } from "@/store/useTradingStore";

const SYMBOLS: SymbolCode[] = ["BTCUSDT", "ETHUSDT"];
const INTERVALS: { value: ChartInterval; label: string }[] = [
  { value: "1m", label: "1m" },
  { value: "5m", label: "5m" },
  { value: "15m", label: "15m" },
  { value: "1h", label: "1h" },
  { value: "4h", label: "4h" },
  { value: "1d", label: "1d" },
];

type ToolbarProps = {
  drawingEnabled: boolean;
  busy: boolean;
  setBusy: (busy: boolean) => void;
  setError: (message: string) => void;
  onToggleDrawing: () => void;
};

export default function Toolbar({ drawingEnabled, busy, setBusy, setError, onToggleDrawing }: ToolbarProps) {
  const { symbol, interval, indicators, setSymbol, setInterval, toggleIndicator, upsertEvent } = useTradingStore();

  const runAction = async (action: "update" | "news") => {
    setBusy(true);
    setError("");
    try {
      const event = action === "news" ? await fetchLatestNews(symbol) : await runAnalystUpdate(symbol);
      upsertEvent(event);
    } catch (error) {
      setError(error instanceof Error ? error.message : "Analyst request failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="toolbar glass-panel">
      <div className="toolbar-group">
        <LineChart size={18} color="#f59e0b" />
        <select className="select" value={symbol} onChange={(event) => setSymbol(event.target.value as SymbolCode)}>
          {SYMBOLS.map((item) => (
            <option key={item} value={item}>
              {item}
            </option>
          ))}
        </select>
        <select className="select" value={interval} onChange={(event) => setInterval(event.target.value as ChartInterval)}>
          {INTERVALS.map((item) => (
            <option key={item.value} value={item.value}>
              {item.label}
            </option>
          ))}
        </select>
      </div>

      <div className="toolbar-group">
        {(["sma20", "ema50"] as IndicatorKey[]).map((indicator) => (
          <button
            className={`button ${indicators[indicator] ? "primary" : "ghost"}`}
            key={indicator}
            onClick={() => toggleIndicator(indicator)}
            type="button"
          >
            {indicator.toUpperCase()}
          </button>
        ))}
      </div>

      <div className="toolbar-group">
        <button className={`button ${drawingEnabled ? "primary" : "ghost"}`} onClick={onToggleDrawing} type="button">
          <PenLine size={15} /> Trendline
        </button>
        <button className="button" disabled={busy} onClick={() => runAction("update")} type="button">
          <Bot size={15} /> Analyst update
        </button>
        <button className="button" disabled={busy} onClick={() => runAction("news")} type="button">
          <Newspaper size={15} /> Latest news
        </button>
        <button className="button ghost" onClick={() => window.location.reload()} type="button">
          <RefreshCcw size={15} /> Reload
        </button>
      </div>
    </div>
  );
}
