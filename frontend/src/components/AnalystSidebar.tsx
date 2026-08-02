"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, Maximize2, Minimize2, Newspaper, Send } from "lucide-react";
import {
  WS_URL,
  askAnalyst,
  fetchAnalystBudget,
  fetchAnalystEvents,
  fetchLatestNews,
} from "@/lib/api";
import { parseSupportResistanceInterval, wantsSupportResistance } from "@/lib/chartAnalysis";
import type { AnalystBudget, AnalystEvent, AnalystScenario, HorizonOutlook } from "@/lib/types";
import { useTradingStore } from "@/store/useTradingStore";

type AnalystSidebarProps = {
  busy: boolean;
  setBusy: (busy: boolean) => void;
  setError: (message: string) => void;
};

type UserChatMessage = {
  id: string;
  kind: "user";
  message: string;
  symbol: string;
  created_at_utc: string;
};

type ChatItem =
  | { kind: "event"; event: AnalystEvent; created_at_utc: string }
  | UserChatMessage;

export default function AnalystSidebar({ busy, setBusy, setError }: AnalystSidebarProps) {
  const [question, setQuestion] = useState("");
  const [budget, setBudget] = useState<AnalystBudget | null>(null);
  const [userMessages, setUserMessages] = useState<UserChatMessage[]>([]);
  const [newsEvent, setNewsEvent] = useState<AnalystEvent | null>(null);
  const [newsOpen, setNewsOpen] = useState(false);
  const [chatExpanded, setChatExpanded] = useState(false);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const { symbol, events, upsertEvent, setSelectedEventId, requestSupportResistance } = useTradingStore();

  useEffect(() => {
    Promise.all([fetchAnalystEvents(), fetchAnalystBudget()])
      .then(([initialEvents, budgetSnapshot]) => {
        initialEvents.forEach((event) => upsertEvent(event));
        setBudget(budgetSnapshot);
      })
      .catch((error) => {
        const message = error instanceof Error ? error.message : "Analyst API unavailable.";
        setError(message);
      });
  }, [setError, upsertEvent]);

  useEffect(() => {
    const ws = new WebSocket(WS_URL);
    ws.onmessage = (message) => {
      try {
        const data = JSON.parse(message.data) as { type?: string; events?: AnalystEvent[]; event?: AnalystEvent };
        if (data.type === "analyst_events" && Array.isArray(data.events)) {
          data.events.forEach((event) => upsertEvent(event));
        }
        if (data.event) {
          upsertEvent(data.event);
        }
      } catch {
        // Keep the UI deterministic; malformed websocket messages are ignored.
      }
    };
    return () => ws.close();
  }, [upsertEvent]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [events.length, userMessages.length]);

  const chatEvents = events.filter((event) => event.event_type === "chat_reply" || event.event_type === "explain");
  const chatItems: ChatItem[] = [
    ...chatEvents.map((event) => ({ kind: "event" as const, event, created_at_utc: event.created_at_utc })),
    ...userMessages,
  ].sort((left, right) => new Date(left.created_at_utc).getTime() - new Date(right.created_at_utc).getTime());
  const runAction = async (action: "ask" | "news") => {
    setBusy(true);
    setError("");
    try {
      let event: AnalystEvent;
      if (action === "ask") {
        const asked = question.trim();
        if (wantsSupportResistance(asked)) {
          requestSupportResistance(parseSupportResistanceInterval(asked) || undefined);
        }
        setUserMessages((messages) => [
          ...messages,
          {
            id: `user-${Date.now()}`,
            kind: "user",
            message: asked,
            symbol,
            created_at_utc: new Date().toISOString(),
          },
        ]);
        event = await askAnalyst(symbol, asked);
        setQuestion("");
      } else {
        event = await fetchLatestNews(symbol);
        setNewsEvent(event);
        setNewsOpen(true);
      }

      if (action !== "news") {
        upsertEvent(event);
      }
      const nextBudget = await fetchAnalystBudget().catch(() => null);
      if (nextBudget) setBudget(nextBudget);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Analyst request failed.";
      setError(message);
    } finally {
      setBusy(false);
    }
  };

  const submitAsk = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!question.trim()) return;
    void runAction("ask");
  };

  return (
    <aside className={`sidebar ${chatExpanded ? "expanded" : ""}`}>
      <div className="sidebar-header">
        <div className="sidebar-title-row">
          <h2>Manual chat</h2>
          <button
            aria-label={chatExpanded ? "Collapse chat" : "Expand chat"}
            className="button ghost sidebar-expand-button"
            onClick={() => setChatExpanded((expanded) => !expanded)}
            title={chatExpanded ? "Collapse chat" : "Expand chat"}
            type="button"
          >
            {chatExpanded ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
          </button>
        </div>
        <p>
          Manual analysis consumes only fresh timeframe evidence. It is advisory and cannot execute an order.
        </p>
        {budget && <p>Manual budget: {budget.timeframes?.manual?.used ?? budget.interactive_used}/{budget.timeframes?.manual?.limit ?? budget.interactive_limit}</p>}
      </div>

      <div ref={scrollRef} className="events">
        {chatItems.length === 0 ? (
          <div className="event-card">
            <div className="event-meta">
              <span>System</span>
              <span>waiting</span>
            </div>
            <p className="event-message">Ask a question to create a manual, evidence-backed analyst answer.</p>
          </div>
        ) : (
          chatItems.map((item) =>
            item.kind === "user" ? (
              <div className="event-card user" key={item.id}>
                <div className="event-meta">
                  <span>You · {item.symbol}</span>
                  <span>{formatTime(item.created_at_utc)}</span>
                </div>
                <div className="event-title">Question</div>
                <p className="event-message">{item.message}</p>
              </div>
            ) : (
              <button
                className={`event-card ${item.event.status === "ok" ? "" : "error"}`}
                key={item.event.id}
                onClick={() => setSelectedEventId(item.event.id)}
                style={{ textAlign: "left", color: "inherit", cursor: "pointer" }}
                type="button"
              >
                <div className="event-meta">
                  <span>{item.event.role || item.event.event_type}</span>
                  <span>{formatTime(item.event.created_at_utc)}</span>
                </div>
                <div className="event-title">
                  {item.event.recommendation && <span className="recommendation">{item.event.recommendation}</span>} {item.event.title}
                </div>
                <p className="event-message">{item.event.message}</p>
                <EventDecisionSupport event={item.event} />
                {item.event.error_code && (
                  <p className="event-message" style={{ color: "#fecaca", marginTop: 8 }}>
                    Error: {item.event.error_code}
                  </p>
                )}
              </button>
            ),
          )
        )}
      </div>

      <form className="composer" onSubmit={submitAsk}>
        <textarea
          className="textarea"
          onChange={(event) => setQuestion(event.target.value)}
          placeholder={`Ask the analyst about ${symbol}...`}
          value={question}
        />
        <div className="composer-row">
          <button className="button primary" disabled={busy || !question.trim()} type="submit">
            <Send size={15} /> Send
          </button>
          <button className="button" disabled={busy} onClick={() => runAction("news")} type="button">
            <Newspaper size={15} /> News analysis
          </button>
        </div>
        <div className="hint">
          {busy ? (
            <>
              <CheckCircle2 size={13} /> Analyst request in progress...
            </>
          ) : (
            <>
              <AlertTriangle size={13} /> LLM/API failures appear as errors; no fallback opinion is generated.
            </>
          )}
        </div>
      </form>

      {newsOpen && newsEvent && (
        <div className="news-overlay" role="dialog" aria-modal="true" aria-labelledby="news-modal-title">
          <div className="news-modal">
            <div className="news-modal-header">
              <div>
                <h3 id="news-modal-title">{newsEvent.title}</h3>
                <p className="hint">
                  {formatTime(newsEvent.created_at_utc)} · {newsEvent.symbol}
                </p>
              </div>
              <button className="button" onClick={() => setNewsOpen(false)} type="button">
                Close
              </button>
            </div>
            <p className="event-message">{newsEvent.message}</p>
            <EventDecisionSupport event={newsEvent} />
            <NewsSources event={newsEvent} />
          </div>
        </div>
      )}
    </aside>
  );
}

function EventDecisionSupport({ event }: { event: AnalystEvent }) {
  const outlook = asArray<HorizonOutlook>(event.payload?.horizon_outlook);
  const scenarios = asArray<AnalystScenario>(event.payload?.scenarios);
  if (outlook.length === 0 && scenarios.length === 0 && !event.risk_notes && !event.invalidation) return null;
  return (
    <div className="decision-support">
      {outlook.map((item) => (
        <section key={item.horizon}>
          <strong>{item.horizon}</strong>
          <p>{item.bias} · momentum {item.momentum.toLowerCase()} · {item.objective}</p>
          {item.watch_for.length > 0 && <p>Watch: {item.watch_for.join(" · ")}</p>}
        </section>
      ))}
      {scenarios.map((scenario) => (
        <section key={`${scenario.direction}-${scenario.name}`}>
          <strong>{scenario.direction}: {scenario.name}</strong>
          <p>{scenario.condition}</p>
          <p>{formatScenarioLevels(scenario)}</p>
          <p>{scenario.plan}</p>
        </section>
      ))}
      {event.risk_notes && <p><strong>Risks:</strong> {event.risk_notes}</p>}
      {event.invalidation && <p><strong>Invalidation:</strong> {event.invalidation}</p>}
    </div>
  );
}

function NewsSources({ event }: { event: AnalystEvent }) {
  const snapshot = event.payload?.news_snapshot;
  if (!snapshot || typeof snapshot !== "object") return null;
  const items = asArray<{ title?: string; url?: string; source?: string }>((snapshot as Record<string, unknown>).items);
  if (items.length === 0) return null;
  return (
    <section className="news-sources">
      <h4>Source headlines</h4>
      {items.map((item, index) => (
        <a href={item.url} key={`${item.url || item.title}-${index}`} rel="noreferrer" target="_blank">
          <span>{item.source || "source"}</span> {item.title || "Untitled item"}
        </a>
      ))}
    </section>
  );
}

function asArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

function formatScenarioLevels(scenario: AnalystScenario): string {
  const entry = scenario.entry_zone_low && scenario.entry_zone_high
    ? `Entry zone ${formatPrice(scenario.entry_zone_low)}–${formatPrice(scenario.entry_zone_high)}`
    : "Entry waits for confirmation";
  const targets = scenario.take_profit.length ? `TP ${scenario.take_profit.map(formatPrice).join(" / ")}` : "TP not supported";
  const stop = scenario.stop_loss ? `SL ${formatPrice(scenario.stop_loss)}` : "SL not supported";
  const timeframe = scenario.confirmation_timeframe ? `Confirm on ${scenario.confirmation_timeframe}` : "Confirmation timeframe unavailable";
  return `${timeframe} · ${entry} · ${targets} · ${stop}`;
}

function formatPrice(value: number): string {
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value);
}

function formatTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
