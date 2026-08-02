"use client";

import { useEffect, useState } from "react";
import { Check, ClipboardList, RefreshCw, X } from "lucide-react";
import { confirmOrderSuggestion, fetchOrderSuggestions, rejectOrderSuggestion, requestOrderAdvice } from "@/lib/api";
import type { AnalystEvent, OrderSuggestion, SymbolCode } from "@/lib/types";

export default function OrdersJournalPanel({ symbol }: { symbol: SymbolCode }) {
  const [instruction, setInstruction] = useState("");
  const [items, setItems] = useState<OrderSuggestion[]>([]);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");

  const refresh = async () => {
    try { setItems(await fetchOrderSuggestions()); } catch (error) { setNotice(error instanceof Error ? error.message : "Could not load order history."); }
  };
  useEffect(() => { void refresh(); }, []);
  const advise = async () => {
    if (!instruction.trim()) return;
    setBusy(true); setNotice("");
    try {
      const event: AnalystEvent = await requestOrderAdvice(symbol, instruction.trim());
      setNotice(event.message);
      setInstruction("");
      await refresh();
    } catch (error) { setNotice(error instanceof Error ? error.message : "Order advice failed."); }
    finally { setBusy(false); }
  };
  const action = async (id: string, kind: "confirm" | "reject") => {
    setBusy(true); setNotice("");
    try { const event = kind === "confirm" ? await confirmOrderSuggestion(id) : await rejectOrderSuggestion(id); setNotice(event.message); await refresh(); }
    catch (error) { setNotice(error instanceof Error ? error.message : "Order update failed."); }
    finally { setBusy(false); }
  };

  return <section className="orders-panel glass-panel">
    <header className="orders-header"><div><h2><ClipboardList size={17} /> Order advice & journal</h2><p>Advice is non-executable until you explicitly confirm a fresh demo suggestion. Submitted and closed lifecycle records stay here.</p></div><button className="button ghost" onClick={() => void refresh()} aria-label="Refresh order journal"><RefreshCw size={15} /></button></header>
    <div className="order-advice-form"><textarea className="textarea" value={instruction} onChange={(e) => setInstruction(e.target.value)} placeholder="Ask for a constrained BTCUSDT order plan using the latest evidence…" /><button className="button primary" disabled={busy || !instruction.trim()} onClick={() => void advise()}>Create advice</button></div>
    {notice && <p className="orders-notice">{notice}</p>}
    <div className="order-list">{items.length === 0 ? <p className="hint">No order suggestions yet.</p> : items.map((item) => {
      const order = item.order || {};
      return <article className="order-card" key={item.id}><div className="order-card-top"><strong>{order.inst_id || symbol} · {String(order.side || "advice").toUpperCase()}</strong><span className={`order-status ${item.status}`}>{item.status}</span></div>
        <p className="order-detail">{String(order.ord_type || "").toUpperCase()} {order.size || ""} {order.size_unit || ""} {order.price ? `at ${order.price}` : "at market"} · est. {order.estimated_notional_usdt ?? "n/a"} USDT</p>
        <p className="order-detail">{item.rationale || item.failure || "No planner rationale recorded."}</p>
        {item.risk_notes && <p className="order-risk">Risk: {item.risk_notes}</p>}
        {item.status === "pending" && <div className="event-actions"><button className="button primary" disabled={busy} onClick={() => void action(item.id, "confirm")}><Check size={15} /> Confirm demo</button><button className="button ghost" disabled={busy} onClick={() => void action(item.id, "reject")}><X size={15} /> Reject</button></div>}
      </article>;
    })}</div>
  </section>;
}
