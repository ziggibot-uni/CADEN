import { useState, useRef, useEffect, useCallback } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { useSettings } from "../context/SettingsContext";
import type { ChatMessage, OllamaStatus, PlannerContext, TraceData, ActivityItem } from "../types";
interface Props {
  ollamaStatus: OllamaStatus;
  context: PlannerContext;
  onRetryOllama: () => void;
}

// ── Activity line: one step in the chronological pipeline feed ────────────────

function ActivityLine({ item }: { item: ActivityItem }) {
  const icon =
    item.status === "running" ? "·"
    : item.status === "skipped" ? "–"
    : "✓";
  const cls =
    item.status === "running"
      ? "text-text-dim animate-pulse"
      : item.status === "skipped"
      ? "text-text-dim opacity-50"
      : "text-accent";
  return (
    <div className={`text-[11px] font-mono leading-relaxed ${cls}`}>
      <span className="inline-block w-3 text-center">{icon}</span>{" "}
      {item.label}
      {item.detail && (
        <span className="text-text-dim opacity-75 ml-1">— {item.detail}</span>
      )}
    </div>
  );
}

function ActivityFeed({ items, trace }: { items: ActivityItem[]; trace?: TraceData | null }) {
  if (items.length === 0 && !trace) return null;
  return (
    <div className="max-w-[90%] pl-1 mb-1 space-y-0.5">
      {items.map((item, i) => (
        <ActivityLine key={i} item={item} />
      ))}
      {trace && (
        <details className="mt-1 group">
          <summary className="text-[10px] font-mono text-text-dim cursor-pointer select-none
            list-none flex items-center gap-1 hover:text-text transition-colors">
            <span className="transition-transform group-open:rotate-90 inline-block text-[9px]">▶</span>
            context sent to model
          </summary>
          <div className="mt-1.5 pl-3 border-l border-surface-3 space-y-2 text-[10px] text-text-dim
            max-h-[400px] overflow-y-auto pr-1">
            {trace.needs_schedule_context && (
              <div>
                <div className="text-text-muted font-semibold mb-0.5">
                  Schedule ({trace.date})
                  {trace.plan_items && Array.isArray(trace.plan_items) && (
                    <span className="font-normal ml-1">
                      — {trace.plan_items.length} item{trace.plan_items.length !== 1 ? "s" : ""}
                    </span>
                  )}
                </div>
                <pre className="whitespace-pre-wrap">{JSON.stringify(trace.plan_items, null, 2)}</pre>
                {trace.upcoming_deadlines && Array.isArray(trace.upcoming_deadlines) && trace.upcoming_deadlines.length > 0 && (
                  <>
                    <div className="text-text-muted font-semibold mt-1 mb-0.5">Deadlines</div>
                    <pre className="whitespace-pre-wrap">{JSON.stringify(trace.upcoming_deadlines, null, 2)}</pre>
                  </>
                )}
              </div>
            )}
            {trace.needs_project_context && trace.project_context && (
              <div>
                <div className="text-text-muted font-semibold mb-0.5">Project Context</div>
                <pre className="whitespace-pre-wrap">{trace.project_context}</pre>
              </div>
            )}
            {trace.situational_briefing && (
              <div>
                <div className="text-text-muted font-semibold mb-0.5">State Briefing</div>
                <pre className="whitespace-pre-wrap">{trace.situational_briefing}</pre>
              </div>
            )}
          </div>
        </details>
      )}
    </div>
  );
}

// Phase of what CADEN is currently doing
type ThinkPhase = "idle" | "loading" | "classifying" | "analyzing" | "pulling data" | "responding" | "reasoning";

const PHASE_LABELS: Record<ThinkPhase, string> = {
  idle: "",
  loading: "loading model",
  classifying: "classifying request",
  analyzing: "analyzing context",
  "pulling data": "pulling data",
  responding: "generating response",
  reasoning: "reasoning",
};

function MessageBubble({ msg }: { msg: ChatMessage }) {
  const isUser = msg.role === "user";
  return (
    <div
      className={`flex flex-col gap-0.5 msg-appear ${isUser ? "items-end" : "items-start"}`}
    >
      {/* Activity feed: chronological pipeline steps (replaces "What I Did") */}
      {msg.activity && msg.activity.length > 0 && (
        <ActivityFeed items={msg.activity} trace={msg.trace} />
      )}
      {msg.thinking && (
        <details className="max-w-[85%] w-full mb-1 group">
          <summary className="text-[11px] font-mono text-text-dim cursor-pointer select-none
            list-none flex items-center gap-1.5 hover:text-text transition-colors">
            <span className="transition-transform group-open:rotate-90 inline-block">▶</span>
            Reasoning
          </summary>
          <div className="mt-1.5 pl-3 border-l border-surface-3 text-[12px] text-text-dim
            leading-relaxed whitespace-pre-wrap font-mono max-h-[300px] overflow-y-auto">
            {msg.thinking}
          </div>
        </details>
      )}
      <div
        className={`max-w-[85%] rounded px-3 py-2 text-sm leading-relaxed whitespace-pre-wrap
          ${isUser
            ? "bg-surface-3 text-text"
            : "text-chat-response"
          }`}
      >
        {msg.content}
      </div>
    </div>
  );
}

export function ChatPanel({ ollamaStatus, context, onRetryOllama }: Props) {
  const { active_model, github_pat } = useSettings();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [thinking, setThinking] = useState(false);
  const [phase, setPhase] = useState<ThinkPhase>("idle");
  // Track how long we've been loading with no tokens
  const phaseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [streamingContent, setStreamingContent] = useState("");
  const [streamingThink, setStreamingThink] = useState("");
  const [activityItems, setActivityItems] = useState<ActivityItem[]>([]);
  const activityItemsRef = useRef<ActivityItem[]>([]);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const unlistenRef = useRef<Array<() => void>>([]);
  // Refs to capture streaming values for the done handler — avoids nested setState
  const streamingContentRef = useRef("");
  const streamingThinkRef = useRef("");
  const streamingTraceRef = useRef<TraceData | null>(null);

  // Helper: append or update an activity item
  const pushActivity = useCallback((item: ActivityItem) => {
    setActivityItems((prev) => {
      // If a running item with same label exists, update it in place
      const idx = prev.findIndex((a) => a.label === item.label && a.status === "running");
      if (idx !== -1) {
        const next = [...prev];
        next[idx] = item;
        activityItemsRef.current = next;
        return next;
      }
      const next = [...prev, item];
      activityItemsRef.current = next;
      return next;
    });
  }, []);

  // Focus input on mount
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // Redirect any printable keystroke to the chat input when it isn't focused
  useEffect(() => {
    function handleGlobalKeyDown(e: KeyboardEvent) {
      if (!inputRef.current) return;
      if (document.activeElement === inputRef.current) return;
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key.length !== 1) return;
      const tag = (document.activeElement as HTMLElement)?.tagName;
      const isEditable = tag === "INPUT" || tag === "TEXTAREA" ||
        (document.activeElement as HTMLElement)?.isContentEditable;
      if (isEditable) return;
      inputRef.current.focus();
    }
    window.addEventListener("keydown", handleGlobalKeyDown);
    return () => window.removeEventListener("keydown", handleGlobalKeyDown);
  }, []);

  // Scroll to bottom when messages change or activity feed updates
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamingContent, streamingThink, thinking, activityItems]);

  // Listen for streaming tokens from Rust
  useEffect(() => {
    let active = true;
    // Track last phase to mark it done when a new phase arrives
    let lastPhaseLabel = "";

    const setup = async () => {
      unlistenRef.current.forEach((u) => u());
      unlistenRef.current = [];

      const unlistens = await Promise.all([
        listen<TraceData>("ollama-trace", (event) => {
          if (!active) return;
          streamingTraceRef.current = event.payload;
          const trace = event.payload;
          // Emit classification result as an activity line
          pushActivity({
            kind: "trace",
            label: `classified: ${trace.intent}`,
            detail: trace.one_line,
            status: "done",
          });
          // Emit analysis if present
          if (trace.analysis) {
            pushActivity({
              kind: "trace",
              label: "analyzed context",
              detail: trace.analysis.length > 120
                ? trace.analysis.slice(0, 120) + "…"
                : trace.analysis,
              status: "done",
            });
          }
        }),
        listen<{ label: string; done: boolean; skipped?: boolean; data?: string }>("caden-logging", (event) => {
          if (!active) return;
          const { label, done, skipped, data } = event.payload;
          pushActivity({
            kind: "log",
            label,
            detail: data || undefined,
            status: skipped ? "skipped" : done ? "done" : "running",
          });
        }),
        listen<string>("ollama-think-token", (event) => {
          if (!active) return;
          streamingThinkRef.current += event.payload;
          setStreamingThink((prev) => prev + event.payload);
          setPhase("reasoning");
        }),
        listen<string>("ollama-token", (event) => {
          if (!active) return;
          streamingContentRef.current += event.payload;
          setStreamingContent((prev) => prev + event.payload);
          setPhase("responding");
        }),
        listen<void>("ollama-done", () => {
          if (!active) return;
          const content = streamingContentRef.current;
          const think = streamingThinkRef.current;
          const trace = streamingTraceRef.current;
          // Mark any still-running items as done before saving
          const activity = activityItemsRef.current.length > 0
            ? activityItemsRef.current.map(a =>
                a.status === "running" ? { ...a, status: "done" as const } : a
              )
            : undefined;
          streamingContentRef.current = "";
          streamingThinkRef.current = "";
          streamingTraceRef.current = null;
          activityItemsRef.current = [];
          setStreamingContent("");
          setStreamingThink("");
          setActivityItems([]);
          if (content || think) {
            const msg: ChatMessage = {
              id: crypto.randomUUID(),
              role: "assistant",
              content,
              thinking: think || undefined,
              trace: trace ?? undefined,
              activity,
              timestamp: new Date().toISOString(),
            };
            setMessages((msgs) => [...msgs, msg]);
          }
          setThinking(false);
          setPhase("idle");
          lastPhaseLabel = "";
          if (phaseTimerRef.current) clearTimeout(phaseTimerRef.current);
        }),
        listen<string>("ollama-error", (event) => {
          if (!active) return;
          streamingContentRef.current = "";
          streamingThinkRef.current = "";
          streamingTraceRef.current = null;
          activityItemsRef.current = [];
          const errMsg: ChatMessage = {
            id: crypto.randomUUID(),
            role: "assistant",
            content: event.payload,
            timestamp: new Date().toISOString(),
          };
          setMessages((msgs) => [...msgs, errMsg]);
          setStreamingContent("");
          setStreamingThink("");
          streamingContentRef.current = "";
          streamingThinkRef.current = "";
          setActivityItems([]);
          activityItemsRef.current = [];
          setThinking(false);
          setPhase("idle");
          lastPhaseLabel = "";
          if (phaseTimerRef.current) clearTimeout(phaseTimerRef.current);
        }),
        listen<string>("caden-phase", (event) => {
          if (!active) return;
          const phase = event.payload as ThinkPhase;
          setPhase(phase);
          const label = PHASE_LABELS[phase];
          if (!label) return;
          // Skip if same phase fires again
          if (label === lastPhaseLabel) return;
          // Mark previous phase as done
          if (lastPhaseLabel) {
            pushActivity({ kind: "phase", label: lastPhaseLabel, status: "done" });
          }
          // Add new phase as running
          pushActivity({ kind: "phase", label, status: "running" });
          lastPhaseLabel = label;
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
  }, [pushActivity]);

  const sendMessage = useCallback(async () => {
    const text = input.trim();
    if (!text || thinking || !ollamaStatus.online) return;

    if (text === "/clear") {
      setMessages([]);
      setInput("");
      setStreamingContent("");
      setStreamingThink("");
      setActivityItems([]);
      streamingContentRef.current = "";
      streamingThinkRef.current = "";
      streamingTraceRef.current = null;
      activityItemsRef.current = [];
      setThinking(false);
      setPhase("idle");
      if (phaseTimerRef.current) clearTimeout(phaseTimerRef.current);
      return;
    }

    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: text,
      timestamp: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setThinking(true);
    setPhase("loading");
    if (phaseTimerRef.current) clearTimeout(phaseTimerRef.current);
    setStreamingContent("");
    setStreamingThink("");
    streamingContentRef.current = "";
    streamingThinkRef.current = "";
    streamingTraceRef.current = null;
    setActivityItems([]);
    activityItemsRef.current = [];

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
      setPhase("idle");
      if (phaseTimerRef.current) clearTimeout(phaseTimerRef.current);
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

  // If GitHub Models is configured, Ollama being down doesn't mean we're offline.
  const offline = !github_pat && !ollamaStatus.online && !ollamaStatus.checking;

  // Status pill label + color in header
  const activeModel = active_model;
  const statusPill = ollamaStatus.checking
    ? { label: "connecting…", cls: "text-text-dim animate-pulse" }
    : offline && !github_pat
    ? { label: "offline", cls: "text-urgency-high" }
    : thinking
    ? {
        label: phase === "loading" ? "loading model" : phase === "reasoning" ? "reasoning" : "responding",
        cls: "text-accent animate-pulse",
      }
    : { label: activeModel, cls: github_pat ? "text-accent" : "text-text-dim" };

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-4 py-3 border-b border-surface-2 flex items-center justify-between">
        <div>
          <div className="text-[11px] font-mono uppercase tracking-widest text-text-dim">
            Chaos-Aiming and Distress-Evasion Navigator
          </div>
          <div className="text-base font-light text-text mt-0.5">
            Talk to CADEN
          </div>
        </div>
        <span className={`text-[10px] font-mono bg-surface-2 px-2 py-1 rounded transition-colors ${statusPill.cls}`}>
          {statusPill.label}
        </span>
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
        {(streamingThink || streamingContent) && (
          <div className="flex flex-col items-start msg-appear gap-1">
            {streamingThink && (
              <details open className="w-full max-w-[85%] group">
                <summary className="text-[11px] font-mono text-text-dim cursor-pointer select-none
                  list-none flex items-center gap-1.5 hover:text-text transition-colors">
                  <span className="transition-transform group-open:rotate-90 inline-block">▶</span>
                  Reasoning
                  <span className="animate-pulse ml-1">…</span>
                </summary>
                <div className="mt-1.5 pl-3 border-l border-surface-3 text-[12px] text-text-dim
                  leading-relaxed whitespace-pre-wrap font-mono max-h-[300px] overflow-y-auto">
                  {streamingThink}
                </div>
              </details>
            )}
            {streamingContent && (
              <div className="max-w-[85%] text-sm leading-relaxed text-chat-response whitespace-pre-wrap">
                {streamingContent}
              </div>
            )}
          </div>
        )}

        {(thinking || activityItems.length > 0) && (
          <div className="msg-appear">
            <ActivityFeed items={activityItems} trace={streamingTraceRef.current} />
          </div>
        )}
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
            Enter to send · Shift+Enter for newline · /clear to reset
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
