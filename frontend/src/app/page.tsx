"use client";

import { useState } from "react";
import { Bot, ClipboardList, LineChart } from "lucide-react";
import AnalystSidebar from "@/components/AnalystSidebar";
import ChartPanel from "@/components/ChartPanel";
import StatusPill from "@/components/StatusPill";
import Toolbar from "@/components/Toolbar";
import OrdersJournalPanel from "@/components/OrdersJournalPanel";
import { useTradingStore } from "@/store/useTradingStore";

export default function Home() {
  const [drawingEnabled, setDrawingEnabled] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<"analysis" | "orders">("analysis");
  const { symbol, interval } = useTradingStore();

  return (
    <main className="app-shell">
      <nav className="left-rail" aria-label="Main">
        <div className="logo">AI</div>
        <StatusPill label="Analyst" />
        <LineChart color="#94a3b8" />
        <Bot color="#f59e0b" />
      </nav>

      <section className="main-column">
        <header className="top-bar">
          <div className="top-title">
            <h1>BTC/ETH Analyst Dashboard</h1>
            <span>
              {symbol} · {interval} · OKX public candles · analyst-only LLM
            </span>
          </div>
          <StatusPill label={busy ? "LLM running" : "Advisory only"} tone={busy ? "warn" : "ok"} />
        </header>

          <div className="workspace-tabs" role="tablist" aria-label="Dashboard workspace">
            <button className={`workspace-tab ${tab === "analysis" ? "active" : ""}`} onClick={() => setTab("analysis")} role="tab" aria-selected={tab === "analysis"}><LineChart size={15} /> Analysis</button>
            <button className={`workspace-tab ${tab === "orders" ? "active" : ""}`} onClick={() => setTab("orders")} role="tab" aria-selected={tab === "orders"}><ClipboardList size={15} /> Orders & journal</button>
          </div>
          {tab === "analysis" ? <div className="workspace">
            <section className="chart-workspace">
            <Toolbar
              drawingEnabled={drawingEnabled}
              onToggleDrawing={() => setDrawingEnabled((enabled) => !enabled)}
            />
            {error && <div className="event-card error">{error}</div>}
            <ChartPanel drawingEnabled={drawingEnabled} setError={setError} />
          </section>
          <AnalystSidebar busy={busy} setBusy={setBusy} setError={setError} />
          </div> : <div className="orders-workspace"><OrdersJournalPanel symbol={symbol} /></div>}
      </section>
    </main>
  );
}
