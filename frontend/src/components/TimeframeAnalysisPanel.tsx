"use client";

import { useEffect, useMemo, useState } from "react";
import { Pause, Play, RefreshCw } from "lucide-react";
import { fetchAnalystStatus, setTimeframeSchedulerPaused } from "@/lib/api";
import type { AnalystRuntimeStatus } from "@/lib/types";
import { useTradingStore } from "@/store/useTradingStore";

const FILTERS = ["all", "1m", "15m", "1h", "4h"] as const;
type Filter = (typeof FILTERS)[number];

export default function TimeframeAnalysisPanel() {
  const [filter, setFilter] = useState<Filter>("15m");
  const [status, setStatus] = useState<AnalystRuntimeStatus | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const { events } = useTradingStore();
  const refresh = async () => {
    try { setStatus(await fetchAnalystStatus()); } catch (error) { setMessage(error instanceof Error ? error.message : "Scheduler status unavailable."); }
  };
  useEffect(() => { void refresh(); const timer = window.setInterval(() => void refresh(), 15_000); return () => window.clearInterval(timer); }, []);
  const entries = useMemo(() => events.filter((event) => {
    if (event.symbol !== "BTCUSDT" || !event.event_type.startsWith("timeframe_")) return false;
    return filter === "all" || event.event_type === `timeframe_${filter}`;
  }).slice().reverse(), [events, filter]);
  const toggle = async () => {
    setBusy(true); setMessage("");
    try { const next = await setTimeframeSchedulerPaused(!status?.scheduler?.paused); setMessage(next.message); await refresh(); }
    catch (error) { setMessage(error instanceof Error ? error.message : "Could not change the scheduler."); }
    finally { setBusy(false); }
  };
  const paused = Boolean(status?.scheduler?.paused);
  return <section className="timeframe-panel glass-panel">
    <header className="timeframe-header"><div><h2>BTC timeframe analysis</h2><p>{paused ? "Paused — no new timeframe analysis will start." : "Closed-candle analysis only; filtered separately from manual chat."}</p></div><div className="timeframe-actions"><button className="button ghost" onClick={() => void refresh()} aria-label="Refresh timeframe status"><RefreshCw size={14} /></button><button className={`button ${paused ? "primary" : "ghost"}`} onClick={() => void toggle()} disabled={busy}>{paused ? <><Play size={14} /> Resume</> : <><Pause size={14} /> Stop</>}</button></div></header>
    <div className="timeframe-filters">{FILTERS.map((item) => <button key={item} className={`filter-chip ${filter === item ? "active" : ""}`} onClick={() => setFilter(item)}>{item === "all" ? "All" : item}</button>)}</div>
    {message && <p className="timeframe-message">{message}</p>}
    <div className="timeframe-events">{entries.length === 0 ? <p className="hint">No BTC {filter === "all" ? "timeframe" : filter} analysis yet.</p> : entries.map((event) => <article className={`timeframe-event ${event.status === "ok" ? "" : "error"}`} key={event.id}><div><span className="timeframe-tag">{event.event_type.replace("timeframe_", "")}</span><span className="event-meta">{formatTime(event.created_at_utc)}</span></div><strong>{event.recommendation || event.status}</strong><p>{event.message}</p>{event.risk_notes && <small>{event.risk_notes}</small>}</article>)}</div>
  </section>;
}

function formatTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
