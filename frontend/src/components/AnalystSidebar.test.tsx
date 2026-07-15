import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AnalystSidebar from "./AnalystSidebar";
import { useTradingStore } from "@/store/useTradingStore";

const askAnalyst = vi.fn();
const fetchLatestNews = vi.fn();

vi.mock("@/lib/api", () => ({
  API_URL: "http://127.0.0.1:8080",
  WS_URL: "ws://127.0.0.1:8080/ws/analyst",
  fetchAnalystEvents: vi.fn(async () => []),
  fetchAnalystBudget: vi.fn(async () => ({
    day: "2026-07-15",
    background_used: 0,
    background_limit: 8,
    interactive_used: 0,
    interactive_limit: 12,
  })),
  askAnalyst: (...args: unknown[]) => askAnalyst(...args),
  fetchLatestNews: (...args: unknown[]) => fetchLatestNews(...args),
  explainAnalystEvent: vi.fn(),
  validateAnalystEvent: vi.fn(),
}));

class FakeWebSocket {
  onmessage: ((message: MessageEvent) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  close = vi.fn();
}

describe("AnalystSidebar", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("WebSocket", FakeWebSocket);
    useTradingStore.setState({
      symbol: "BTCUSDT",
      events: [],
      selectedEventId: "",
    });
    askAnalyst.mockResolvedValue({
      id: "bot-1",
      event_type: "chat_reply",
      status: "ok",
      title: "BTCUSDT analyst answer",
      message: "Directional advisory answer.",
      symbol: "BTCUSDT",
      role: "main_analyst",
      recommendation: "BUY",
      created_at_utc: "2026-07-15T00:00:02Z",
    });
    fetchLatestNews.mockResolvedValue({
      id: "news-1",
      event_type: "news",
      status: "ok",
      title: "BTCUSDT public crypto news",
      message: "News item one\nNews item two",
      symbol: "BTCUSDT",
      role: "system",
      created_at_utc: "2026-07-15T00:00:03Z",
    });
  });

  it("renders the user's submitted question before the bot answer", async () => {
    render(<AnalystSidebar busy={false} setBusy={vi.fn()} setError={vi.fn()} />);

    fireEvent.change(screen.getByPlaceholderText("Ask the analyst about BTCUSDT..."), {
      target: { value: "Should I take a position?" },
    });
    fireEvent.click(screen.getByRole("button", { name: /ask/i }));

    expect(await screen.findByText("Should I take a position?")).toBeInTheDocument();
    expect(await screen.findByText("Directional advisory answer.")).toBeInTheDocument();
  });

  it("opens latest news in a modal instead of the chat timeline", async () => {
    render(<AnalystSidebar busy={false} setBusy={vi.fn()} setError={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: /news/i }));

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("BTCUSDT public crypto news")).toBeInTheDocument();
    expect(screen.getByText(/News item one/)).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText("system")).not.toBeInTheDocument());
  });
});
