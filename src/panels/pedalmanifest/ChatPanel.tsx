import { useState, useRef, useEffect } from "react";
import { sendChat } from "./api";

interface Message {
  role: "system" | "user" | "assistant";
  content: string;
}

interface DesignUpdate {
  circuit?: unknown;
  plan?: unknown;
  simulation?: unknown;
  pots?: unknown[];
  frequency_response?: unknown[];
}

interface ChatPanelProps {
  onDesignUpdate?: (data: DesignUpdate) => void;
  model?: string;
}

export default function ChatPanel({ onDesignUpdate, model }: ChatPanelProps) {
  const [messages, setMessages] = useState<Message[]>([
    { role: "system", content: "Welcome to PedalManifest. Describe the pedal you want to build." },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const messagesEnd = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEnd.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  const handleSend = async () => {
    const text = input.trim();
    if (!text || loading) return;
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setInput("");
    setLoading(true);
    try {
      const data = await sendChat(text, model) as Record<string, unknown>;
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: (data.response || data.message || JSON.stringify(data)) as string },
      ]);
      if (data.circuit || data.simulation || data.pots) {
        onDesignUpdate?.({
          circuit: data.circuit,
          plan: data.plan,
          simulation: data.simulation,
          pots: data.pots as unknown[],
          frequency_response: (data.simulation as Record<string, unknown>)?.frequency_response as unknown[] || [],
        });
      }
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `Error: ${(err as Error).message}` },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {messages.map((msg, i) => (
          <div
            key={i}
            className={
              msg.role === "user"
                ? "ml-6 px-3 py-2 bg-surface-1 rounded text-text text-sm whitespace-pre-wrap leading-relaxed"
                : msg.role === "system"
                ? "text-text-dim text-xs opacity-60 italic"
                : "px-3 py-2 border-l-2 border-accent-DEFAULT text-text text-sm whitespace-pre-wrap leading-relaxed"
            }
          >
            {msg.content}
          </div>
        ))}
        {loading && (
          <div className="text-text-dim text-xs animate-pulse px-3">thinking...</div>
        )}
        <div ref={messagesEnd} />
      </div>
      <div className="border-t border-surface-2 px-4 py-3">
        <div className="flex gap-2 items-end">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Describe your pedal circuit..."
            rows={2}
            className="flex-1 bg-surface-1 border border-surface-2 rounded px-3 py-2 text-sm text-text placeholder:text-text-dim focus:outline-none focus:border-accent-DEFAULT resize-none"
          />
          <button
            onClick={handleSend}
            disabled={loading || !input.trim()}
            className="px-3 py-2 bg-accent-DEFAULT text-surface rounded text-xs font-semibold disabled:opacity-30 hover:opacity-80 transition-opacity"
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
}
