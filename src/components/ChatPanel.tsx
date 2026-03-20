import { useState, useRef, useEffect, useCallback } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import type { ChatMessage, OllamaStatus, PlannerContext } from "../types";

interface Props {
  ollamaStatus: OllamaStatus;
  context: PlannerContext;
  onRetryOllama: () => void;
}

function ThinkingDots() {
  return (
    <div className="flex items-center gap-1 px-3 py-2">
      <span className="think-dot" />
      <span className="think-dot" />
      <span className="think-dot" />
    </div>
  );
}

function MessageBubble({ msg }: { msg: ChatMessage }) {
  const isUser = msg.role === "user";
  return (
    <div
      className={`flex flex-col gap-0.5 msg-appear ${isUser ? "items-end" : "items-start"}`}
    >
      <div
        className={`max-w-[85%] rounded px-3 py-2 text-sm leading-relaxed whitespace-pre-wrap
          ${isUser
            ? "bg-surface-3 text-text"
            : "text-[#9ab8b5]"
          }`}
      >
        {msg.content}
      </div>
    </div>
  );
}

export function ChatPanel({ ollamaStatus, context, onRetryOllama }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [thinking, setThinking] = useState(false);
  const [streamingContent, setStreamingContent] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const unlistenRef = useRef<Array<() => void>>([]);

  // Scroll to bottom when messages change
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamingContent, thinking]);

  // Listen for streaming tokens from Rust
  useEffect(() => {
    let active = true;

    const setup = async () => {
      const unlistens = await Promise.all([
        listen<string>("ollama-token", (event) => {
          if (!active) return;
          setStreamingContent((prev) => prev + event.payload);
        }),
        listen<void>("ollama-done", () => {
          if (!active) return;
          setStreamingContent((prev) => {
            const content = prev;
            if (content) {
              const msg: ChatMessage = {
                id: crypto.randomUUID(),
                role: "assistant",
                content,
                timestamp: new Date().toISOString(),
              };
              setMessages((msgs) => [...msgs, msg]);
            }
            return "";
          });
          setThinking(false);
        }),
        listen<string>("ollama-error", (event) => {
          if (!active) return;
          const errMsg: ChatMessage = {
            id: crypto.randomUUID(),
            role: "assistant",
            content: event.payload,
            timestamp: new Date().toISOString(),
          };
          setMessages((msgs) => [...msgs, errMsg]);
          setStreamingContent("");
          setThinking(false);
        }),
      ]);
      unlistenRef.current = unlistens;
    };

    setup();

    return () => {
      active = false;
      unlistenRef.current.forEach((u) => u());
      unlistenRef.current = [];
    };
  }, []);

  const sendMessage = useCallback(async () => {
    const text = input.trim();
    if (!text || thinking || !ollamaStatus.online) return;

    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: text,
      timestamp: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setThinking(true);
    setStreamingContent("");

    try {
      await invoke("chat_with_ollama", {
        message: text,
        history: messages.slice(-10).map((m) => ({
          role: m.role,
          content: m.content,
        })),
        context,
      });
    } catch (err) {
      const errMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: "Something went wrong. Check that Ollama is running.",
        timestamp: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, errMsg]);
      setThinking(false);
    }
  }, [input, thinking, ollamaStatus.online, messages, context]);

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  // Auto-resize textarea
  function handleInput(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setInput(e.target.value);
    const el = e.target;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 120) + "px";
  }

  const offline = !ollamaStatus.online && !ollamaStatus.checking;

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-4 py-3 border-b border-surface-2 flex items-center justify-between">
        <div>
          <div className="text-[11px] font-mono uppercase tracking-widest text-text-dim">
            CADEN
          </div>
          <div className="text-base font-light text-text mt-0.5">
            Executive Function Navigator
          </div>
        </div>
        {ollamaStatus.model && (
          <span className="text-[10px] font-mono text-text-dim bg-surface-2 px-2 py-1 rounded">
            {ollamaStatus.model}
          </span>
        )}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-4 flex flex-col gap-3">
        {messages.length === 0 && !offline && (
          <div className="text-text-dim text-sm text-center mt-8">
            What do you need to tackle?
          </div>
        )}

        {offline && (
          <div className="flex flex-col items-center justify-center h-full gap-4 text-center">
            <div className="text-text-muted text-sm leading-relaxed">
              CADEN's brain is offline.
              <br />
              Start Ollama to continue.
            </div>
            <button
              className="btn-ghost text-sm"
              onClick={onRetryOllama}
            >
              {ollamaStatus.checking ? "Checking…" : "Try again"}
            </button>
          </div>
        )}

        {messages.map((msg) => (
          <MessageBubble key={msg.id} msg={msg} />
        ))}

        {/* Streaming response */}
        {streamingContent && (
          <div className="flex flex-col items-start msg-appear">
            <div className="max-w-[85%] text-sm leading-relaxed text-[#9ab8b5] whitespace-pre-wrap">
              {streamingContent}
            </div>
          </div>
        )}

        {thinking && !streamingContent && <ThinkingDots />}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      {!offline && (
        <div className="px-4 py-3 border-t border-surface-2">
          <div className="flex items-end gap-2 bg-surface-2 rounded px-3 py-2">
            <textarea
              ref={inputRef}
              rows={1}
              value={input}
              onChange={handleInput}
              onKeyDown={handleKeyDown}
              placeholder="Talk to CADEN…"
              disabled={thinking}
              className="flex-1 resize-none bg-transparent text-text placeholder:text-text-dim
                text-sm leading-relaxed max-h-[120px] overflow-y-auto"
              style={{ height: "auto" }}
            />
            <button
              onClick={sendMessage}
              disabled={!input.trim() || thinking}
              className="flex-shrink-0 text-accent-DEFAULT disabled:text-text-dim
                transition-colors duration-150 pb-0.5"
              aria-label="Send"
            >
              <SendIcon />
            </button>
          </div>
          <div className="text-[10px] text-text-dim mt-1.5 text-right">
            Enter to send · Shift+Enter for newline
          </div>
        </div>
      )}
    </div>
  );
}

function SendIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M14 2L7 9" />
      <path d="M14 2L9 14L7 9L2 7L14 2Z" />
    </svg>
  );
}
