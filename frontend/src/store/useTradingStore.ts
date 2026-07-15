import { create } from "zustand";
import type { AnalystEvent, ChartInterval, IndicatorKey, SymbolCode } from "@/lib/types";

type TradingState = {
  symbol: SymbolCode;
  interval: ChartInterval;
  indicators: Record<IndicatorKey, boolean>;
  events: AnalystEvent[];
  selectedEventId: string;
  supportResistanceRequest: { id: number; symbol: SymbolCode; interval: ChartInterval } | null;
  clearChartOverlaysRequestId: number;
  setSymbol: (symbol: SymbolCode) => void;
  setInterval: (interval: ChartInterval) => void;
  toggleIndicator: (indicator: IndicatorKey) => void;
  setEvents: (events: AnalystEvent[]) => void;
  upsertEvent: (event: AnalystEvent) => void;
  setSelectedEventId: (id: string) => void;
  requestSupportResistance: (interval?: ChartInterval) => void;
  clearChartOverlays: () => void;
};

export const useTradingStore = create<TradingState>((set) => ({
  symbol: "BTCUSDT",
  interval: "5m",
  indicators: {
    sma20: true,
    ema50: false,
  },
  events: [],
  selectedEventId: "",
  supportResistanceRequest: null,
  clearChartOverlaysRequestId: 0,
  setSymbol: (symbol) => set({ symbol }),
  setInterval: (interval) => set({ interval }),
  toggleIndicator: (indicator) =>
    set((state) => ({
      indicators: { ...state.indicators, [indicator]: !state.indicators[indicator] },
    })),
  setEvents: (events) => set({ events }),
  upsertEvent: (event) =>
    set((state) => {
      const exists = state.events.some((row) => row.id === event.id);
      return { events: exists ? state.events.map((row) => (row.id === event.id ? event : row)) : [...state.events, event] };
    }),
  setSelectedEventId: (id) => set({ selectedEventId: id }),
  requestSupportResistance: (interval) =>
    set((state) => ({
      supportResistanceRequest: {
        id: Date.now(),
        symbol: state.symbol,
        interval: interval || state.interval,
      },
    })),
  clearChartOverlays: () =>
    set((state) => ({
      clearChartOverlaysRequestId: state.clearChartOverlaysRequestId + 1,
    })),
}));
