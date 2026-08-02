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
  screening_used?: number;
  screening_limit?: number;
  scheduled_used?: number;
  scheduled_limit?: number;
  timeframes?: Record<string, { used: number; limit: number }>;
};

export type ChartAnnotation =
  | { kind: "support"; price: number; label: string }
  | { kind: "resistance"; price: number; label: string }
  | { kind: "trend"; start_time: string; start_price: number; end_time: string; end_price: number; label: string };

export type IndicatorKey = "sma20" | "ema50" | "volume";

export type HorizonOutlook = {
  horizon: "INTRADAY" | "SWING";
  timeframes: string[];
  bias: "BULLISH" | "BEARISH" | "NEUTRAL" | "MIXED" | "UNKNOWN";
  momentum: "ACCELERATING" | "STEADY" | "WEAKENING" | "REVERSING" | "MIXED" | "UNKNOWN";
  objective: string;
  watch_for: string[];
};

export type AnalystScenario = {
  name: string;
  direction: "BULLISH" | "BEARISH" | "NEUTRAL";
  condition: string;
  confirmation_timeframe: string | null;
  entry_zone_low: number | null;
  entry_zone_high: number | null;
  take_profit: number[];
  stop_loss: number | null;
  plan: string;
};

export type OrderSuggestion = {
  id: string;
  status: "pending" | "submitting" | "submitted" | "rejected" | "expired" | "failed" | string;
  created_at_utc: string;
  updated_at_utc?: string;
  expires_at_utc?: string;
  rationale?: string;
  risk_notes?: string;
  confidence?: number | null;
  order?: {
    inst_id?: string;
    side?: string;
    ord_type?: string;
    size?: string;
    size_unit?: string;
    price?: string | null;
    slippage_pct?: string;
    estimated_notional_usdt?: number | string;
  };
  execution_summary?: Record<string, unknown>;
  failure?: string;
};
