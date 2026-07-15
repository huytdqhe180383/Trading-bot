"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { AlertTriangle, Bot, CheckCircle2, LogIn, Newspaper, Send, ShieldCheck } from "lucide-react";
import {
  API_URL,
  WS_URL,
  askAnalyst,
  explainAnalystEvent,
  fetchAnalystBudget,
  fetchAnalystEvents,
  fetchLatestNews,
  validateAnalystEvent,
} from "@/lib/api";
import { parseSupportResistanceInterval, wantsSupportResistance } from "@/lib/chartAnalysis";
import type { AnalystBudget, AnalystEvent } from "@/lib/types";
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
  const [authNeeded, setAuthNeeded] = useState(false);
  const [userMessages, setUserMessages] = useState<UserChatMessage[]>([]);
  const [newsEvent, setNewsEvent] = useState<AnalystEvent | null>(null);
  const [newsOpen, setNewsOpen] = useState(false);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const { symbol, events, selectedEventId, upsertEvent, setSelectedEventId, requestSupportResistance } = useTradingStore();

  useEffect(() => {
    Promise.all([fetchAnalystEvents(), fetchAnalystBudget()])
      .then(([initialEvents, budgetSnapshot]) => {
        initialEvents.forEach((event) => upsertEvent(event));
        setBudget(budgetSnapshot);
        setAuthNeeded(false);
      })
      .catch((error) => {
        const message = error instanceof Error ? error.message : "Analyst API unavailable.";
        setAuthNeeded(message.toLowerCase().includes("authentication"));
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
    ws.onclose = (event) => {
      if (event.code === 1008) setAuthNeeded(true);
    };
    return () => ws.close();
  }, [upsertEvent]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [events.length, userMessages.length]);

  const chatEvents = events.filter((event) => event.event_type !== "news");
  const chatItems: ChatItem[] = [
    ...chatEvents.map((event) => ({ kind: "event" as const, event, created_at_utc: event.created_at_utc })),
    ...userMessages,
  ].sort((left, right) => new Date(left.created_at_utc).getTime() - new Date(right.created_at_utc).getTime());
  const selectedEvent = chatEvents.find((event) => event.id === selectedEventId) || chatEvents.at(-1);

  const runAction = async (action: "ask" | "validate" | "explain" | "news") => {
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
      } else if (action === "validate") {
        event = await validateAnalystEvent(symbol, selectedEvent?.id || "");
      } else if (action === "explain") {
        event = await explainAnalystEvent(selectedEvent?.id || "");
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
      setAuthNeeded(message.toLowerCase().includes("authentication"));
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
    <aside className="sidebar">
      <div className="sidebar-header">
        <h2>Analyst chat</h2>
        <p>
          Main Analyst for chat/deep analysis, Risk Validator for checks. Advisory output is allowed; order sizing,
          leverage, exchange commands, and autonomous execution stay forbidden.
        </p>
        {budget && (
          <p>
            Interactive budget: {budget.interactive_used}/{budget.interactive_limit} · Background: {budget.background_used}/
            {budget.background_limit}
          </p>
        )}
        {authNeeded && (
          <a className="button primary" style={{ marginTop: 12, display: "inline-flex", textDecoration: "none" }} href={`${API_URL}/login`}>
            <LogIn size={15} /> Login on backend
          </a>
        )}
      </div>

      <div ref={scrollRef} className="events">
        {chatItems.length === 0 ? (
          <div className="event-card">
            <div className="event-meta">
              <span>System</span>
              <span>waiting</span>
            </div>
            <p className="event-message">No analyst events yet. Ask a question, request an update, or fetch latest news.</p>
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
            <Send size={15} /> Ask
          </button>
          <button className="button" disabled={busy || !selectedEvent} onClick={() => runAction("explain")} type="button">
            <Bot size={15} /> Explain
          </button>
          <button className="button" disabled={busy || !selectedEvent} onClick={() => runAction("validate")} type="button">
            <ShieldCheck size={15} /> Validate
          </button>
          <button className="button" disabled={busy} onClick={() => runAction("news")} type="button">
            <Newspaper size={15} /> News
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
          </div>
        </div>
      )}
    </aside>
  );
}

function formatTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
