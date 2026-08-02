"use client";

import { ChevronDown, Eraser, LineChart, PenLine, RefreshCcw } from "lucide-react";
import type { ChartInterval, IndicatorKey, SymbolCode } from "@/lib/types";
import { useTradingStore } from "@/store/useTradingStore";

const SYMBOLS: SymbolCode[] = ["BTCUSDT"];
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
  onToggleDrawing: () => void;
};

const INDICATOR_LABELS: Record<IndicatorKey, string> = {
  sma20: "SMA 20",
  ema50: "EMA 50",
  volume: "Volume",
};

export default function Toolbar({ drawingEnabled, onToggleDrawing }: ToolbarProps) {
  const {
    symbol,
    interval,
    indicators,
    setSymbol,
    setInterval,
    toggleIndicator,
    requestSupportResistance,
    clearChartOverlays,
  } = useTradingStore();

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
        <details className="indicator-menu">
          <summary className="button ghost">
            Indicators <ChevronDown size={14} />
          </summary>
          <div className="indicator-menu-panel">
            {(Object.keys(INDICATOR_LABELS) as IndicatorKey[]).map((indicator) => (
              <label className="indicator-option" key={indicator}>
                <input
                  checked={indicators[indicator]}
                  onChange={() => toggleIndicator(indicator)}
                  type="checkbox"
                />
                <span>{INDICATOR_LABELS[indicator]}</span>
              </label>
            ))}
          </div>
        </details>
      </div>

      <div className="toolbar-group">
        <button className={`button ${drawingEnabled ? "primary" : "ghost"}`} onClick={onToggleDrawing} type="button">
          <PenLine size={15} /> Trendline
        </button>
        <button className="button" onClick={() => requestSupportResistance()} type="button">
          <LineChart size={15} /> S/R lines
        </button>
        <button className="button ghost" onClick={clearChartOverlays} type="button">
          <Eraser size={15} /> Clear lines
        </button>
        <button className="button ghost" onClick={() => window.location.reload()} type="button">
          <RefreshCcw size={15} /> Reload
        </button>
      </div>
    </div>
  );
}
