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
import type { AnalystBudget, AnalystEvent } from "@/lib/types";
import { useTradingStore } from "@/store/useTradingStore";

type AnalystSidebarProps = {
  busy: boolean;
  setBusy: (busy: boolean) => void;
  setError: (message: string) => void;
};

export default function AnalystSidebar({ busy, setBusy, setError }: AnalystSidebarProps) {
  const [question, setQuestion] = useState("");
  const [budget, setBudget] = useState<AnalystBudget | null>(null);
  const [authNeeded, setAuthNeeded] = useState(false);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const { symbol, events, selectedEventId, setEvents, upsertEvent, setSelectedEventId } = useTradingStore();

  useEffect(() => {
    Promise.all([fetchAnalystEvents(), fetchAnalystBudget()])
      .then(([initialEvents, budgetSnapshot]) => {
        setEvents(initialEvents);
        setBudget(budgetSnapshot);
        setAuthNeeded(false);
      })
      .catch((error) => {
        const message = error instanceof Error ? error.message : "Analyst API unavailable.";
        setAuthNeeded(message.toLowerCase().includes("authentication"));
        setError(message);
      });
  }, [setError, setEvents]);

  useEffect(() => {
    const ws = new WebSocket(WS_URL);
    ws.onmessage = (message) => {
      try {
        const data = JSON.parse(message.data) as { type?: string; events?: AnalystEvent[]; event?: AnalystEvent };
        if (data.type === "analyst_events" && Array.isArray(data.events)) {
          setEvents(data.events);
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
  }, [setEvents, upsertEvent]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [events.length]);

  const selectedEvent = events.find((event) => event.id === selectedEventId) || events.at(-1);

  const runAction = async (action: "ask" | "validate" | "explain" | "news") => {
    setBusy(true);
    setError("");
    try {
      let event: AnalystEvent;
      if (action === "ask") {
        event = await askAnalyst(symbol, question.trim());
        setQuestion("");
      } else if (action === "validate") {
        event = await validateAnalystEvent(symbol, selectedEvent?.id || "");
      } else if (action === "explain") {
        event = await explainAnalystEvent(selectedEvent?.id || "");
      } else {
        event = await fetchLatestNews(symbol);
      }
      upsertEvent(event);
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
        <p>Main LLM only. Advisory output is allowed; order sizing, leverage, exchange commands, and autonomous execution stay forbidden.</p>
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
        {events.length === 0 ? (
          <div className="event-card">
            <div className="event-meta">
              <span>System</span>
              <span>waiting</span>
            </div>
            <p className="event-message">No analyst events yet. Ask a question, request an update, or fetch latest news.</p>
          </div>
        ) : (
          events.map((event) => (
            <button
              className={`event-card ${event.status === "ok" ? "" : "error"}`}
              key={event.id}
              onClick={() => setSelectedEventId(event.id)}
              style={{ textAlign: "left", color: "inherit", cursor: "pointer" }}
              type="button"
            >
              <div className="event-meta">
                <span>{event.role || event.event_type}</span>
                <span>{formatTime(event.created_at_utc)}</span>
              </div>
              <div className="event-title">
                {event.recommendation && <span className="recommendation">{event.recommendation}</span>} {event.title}
              </div>
              <p className="event-message">{event.message}</p>
              {event.error_code && (
                <p className="event-message" style={{ color: "#fecaca", marginTop: 8 }}>
                  Error: {event.error_code}
                </p>
              )}
            </button>
          ))
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
              <CheckCircle2 size={13} /> Analyst request in progress…
            </>
          ) : (
            <>
              <AlertTriangle size={13} /> LLM/API failures appear as errors; no fallback opinion is generated.
            </>
          )}
        </div>
      </form>
    </aside>
  );
}

function formatTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
