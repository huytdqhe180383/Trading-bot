import type { AnalystBudget, AnalystEvent, AnalystRuntimeStatus, Candle, ChartInterval, OrderSuggestion, SymbolCode } from "./types";

const DEFAULT_API_URL = "http://127.0.0.1:8080";
const DEFAULT_WS_URL = "ws://127.0.0.1:8080/ws/analyst";

export const API_URL = process.env.NEXT_PUBLIC_API_URL || DEFAULT_API_URL;
export const WS_URL = process.env.NEXT_PUBLIC_WS_URL || DEFAULT_WS_URL;

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const csrf = init?.method && init.method !== "GET" ? await fetchCsrfToken() : "";
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(csrf ? { "x-csrf-token": csrf } : {}),
      ...(init?.headers || {}),
    },
  });

  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = (await response.json()) as { detail?: string };
      detail = body.detail || detail;
    } catch {
      // Keep deterministic HTTP error text.
    }
    throw new Error(detail);
  }

  return response.json() as Promise<T>;
}

let csrfToken = "";
async function fetchCsrfToken(): Promise<string> {
  if (csrfToken) return csrfToken;
  const response = await fetch(`${API_URL}/api/session/csrf`, { credentials: "include" });
  if (!response.ok) throw new Error("Could not start the local operator session.");
  const data = (await response.json()) as { csrf_token?: string };
  csrfToken = data.csrf_token || "";
  return csrfToken;
}

export async function fetchCandles(symbol: SymbolCode, interval: ChartInterval, limit = 500): Promise<Candle[]> {
  const params = new URLSearchParams({ symbol, interval, limit: String(limit) });
  const data = await requestJson<{ candles: Candle[] }>(`/api/market/candles?${params.toString()}`);
  return data.candles;
}

export async function fetchAnalystEvents(limit = 80): Promise<AnalystEvent[]> {
  const data = await requestJson<{ events: AnalystEvent[] }>(`/api/analyst/events?limit=${limit}`);
  return data.events;
}

export async function fetchAnalystSignals(limit = 120): Promise<AnalystEvent[]> {
  const data = await requestJson<{ signals: AnalystEvent[] }>(`/api/analyst/signals?limit=${limit}`);
  return data.signals;
}

export async function fetchAnalystBudget(): Promise<AnalystBudget> {
  return requestJson<AnalystBudget>("/api/analyst/budget");
}

export async function runAnalystUpdate(symbol: SymbolCode): Promise<AnalystEvent> {
  return requestJson<AnalystEvent>("/api/analyst/run", {
    method: "POST",
    body: JSON.stringify({ symbol }),
  });
}

export async function askAnalyst(symbol: SymbolCode, question: string): Promise<AnalystEvent> {
  return requestJson<AnalystEvent>("/api/analyst/run", {
    method: "POST",
    body: JSON.stringify({ symbol, question }),
  });
}

export async function validateAnalystEvent(symbol: SymbolCode, alertId: string): Promise<AnalystEvent> {
  return requestJson<AnalystEvent>("/api/analyst/run", {
    method: "POST",
    body: JSON.stringify({ symbol, validate_alert_id: alertId }),
  });
}

export async function explainAnalystEvent(alertId: string): Promise<AnalystEvent> {
  return requestJson<AnalystEvent>("/api/analyst/run", {
    method: "POST",
    body: JSON.stringify({ explain_alert_id: alertId }),
  });
}

export async function fetchLatestNews(symbol: SymbolCode): Promise<AnalystEvent> {
  return requestJson<AnalystEvent>("/api/analyst/run", {
    method: "POST",
    body: JSON.stringify({ symbol, latest_news: true }),
  });
}

export async function setTimeframeSchedulerPaused(paused: boolean): Promise<{ paused: boolean; message: string }> {
  return requestJson<{ paused: boolean; message: string }>("/api/analyst/scheduler", {
    method: "POST",
    body: JSON.stringify({ paused }),
  });
}

export async function restartAnalystWeb(): Promise<{ message: string }> {
  return requestJson<{ message: string }>("/api/analyst/restart", { method: "POST" });
}

export async function fetchAnalystStatus(): Promise<AnalystRuntimeStatus> {
  return requestJson<AnalystRuntimeStatus>("/api/analyst/status");
}

export async function fetchOrderSuggestions(): Promise<OrderSuggestion[]> {
  const data = await requestJson<{ suggestions: OrderSuggestion[] }>("/api/orders/suggestions");
  return data.suggestions;
}

export async function requestOrderAdvice(symbol: SymbolCode, instruction: string): Promise<AnalystEvent> {
  return requestJson<AnalystEvent>("/api/orders/advice", { method: "POST", body: JSON.stringify({ symbol, instruction }) });
}

export async function confirmOrderSuggestion(suggestion_id: string): Promise<AnalystEvent> {
  return requestJson<AnalystEvent>("/api/orders/confirm", { method: "POST", body: JSON.stringify({ suggestion_id }) });
}

export async function rejectOrderSuggestion(suggestion_id: string): Promise<AnalystEvent> {
  return requestJson<AnalystEvent>("/api/orders/reject", { method: "POST", body: JSON.stringify({ suggestion_id }) });
}
