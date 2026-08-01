export type SymbolCode = "BTCUSDT" | "ETHUSDT";
export type ChartInterval = "1m" | "5m" | "15m" | "1h" | "4h" | "1d";
export type AnalystRecommendation = "BUY" | "SELL" | "REDUCE" | "HOLD" | "AVOID";

export type Candle = {
  time: number;
  timestamp_ms: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  symbol: SymbolCode;
  source: "okx_public";
};

export type AnalystEvent = {
  id: string;
  event_type: string;
  status: string;
  title: string;
  message: string;
  symbol: string;
  role: string;
  recommendation?: AnalystRecommendation | null;
  confidence?: number | null;
  rationale?: string;
  risk_notes?: string;
  invalidation?: string;
  error_code?: string;
  created_at_utc: string;
  payload?: Record<string, unknown>;
};

export type AnalystBudget = {
  day: string;
  background_used: number;
  background_limit: number;
  interactive_used: number;
  interactive_limit: number;
};

export type ChartAnnotation =
  | { kind: "support"; price: number; label: string }
  | { kind: "resistance"; price: number; label: string }
  | { kind: "trend"; start_time: string; start_price: number; end_time: string; end_price: number; label: string };

export type IndicatorKey = "sma20" | "ema50";
