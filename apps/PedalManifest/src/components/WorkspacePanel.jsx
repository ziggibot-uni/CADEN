import { useState, useRef, useEffect, useCallback } from "react";
import FrequencyChart from "./FrequencyChart";
import TransformPipeline from "./TransformPipeline";
import VirtualKnobs from "./VirtualKnobs";
import AudioControls from "./AudioControls";
import CircuitInfo from "./CircuitInfo";

const SYSTEM_MESSAGE = "Describe the guitar effect you want. PedalManifest will design a circuit from your inventory, validate it with SPICE, and build a real-time DSP model you can play through.";

export default function WorkspacePanel({ status, online }) {
  const [messages, setMessages] = useState([{ role: "system", text: SYSTEM_MESSAGE }]);
  const [input, setInput] = useState("");
  const [model, setModel] = useState("mistral");
  const [models, setModels] = useState([]);
  const [loading, setLoading] = useState(false);
  const [design, setDesign] = useState(null); // {intent, plan, circuit, simulation, pots}
  const [audioRunning, setAudioRunning] = useState(false);
  const bottomRef = useRef(null);
  const inputRef = useRef(null);

  // Load available Ollama models
  useEffect(() => {
    fetch("/api/ai/models")
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d?.models?.length) setModels(d.models); })
      .catch(() => {});
  }, []);

  // Sync audio running state
  const refreshAudioState = useCallback(async () => {
    try {
      const r = await fetch("/api/audio/status");
      if (r.ok) setAudioRunning((await r.json()).running);
    } catch {}
  }, []);

  useEffect(() => {
    refreshAudioState();
  }, [refreshAudioState]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function send() {
    const text = input.trim();
    if (!text || loading) return;
    setInput("");
    setMessages(m => [...m, { role: "user", text }]);
    setLoading(true);

    try {
      const r = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, model }),
      });
      const d = await r.json();

      const aiText = d.response || "Design complete.";
      setMessages(m => [...m, { role: "assistant", text: aiText }]);

      if (d.circuit || d.plan) {
        setDesign({
          intent: d.intent,
          plan: d.plan,
          circuit: d.circuit,
          simulation: d.simulation,
          pots: d.pots ?? [],
        });
      }
    } catch (e) {
      setMessages(m => [...m, { role: "assistant", text: `Error: ${e.message}` }]);
    }

    setLoading(false);
    inputRef.current?.focus();
  }

  async function saveKeeper() {
    const name = prompt("Name this design:");
    if (!name?.trim()) return;
    try {
      await fetch("/api/keepers", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.trim(), intent_description: design?.intent?.raw_input ?? name }),
      });
    } catch {}
  }

  async function resetDesign() {
    setDesign(null);
    setMessages([{ role: "system", text: SYSTEM_MESSAGE }]);
    try { await fetch("/api/design"); } catch {}
  }

  const stages = design?.plan?.stages ?? [];
  const sim = design?.simulation ?? {};
  const hasDesign = !!design;

  if (!online) {
    return (
      <div className="flex items-center justify-center h-full text-text-muted text-sm flex-col gap-2">
        <div className="w-2 h-2 rounded-full bg-red-400 animate-pulse" />
        <span>Backend starting… please wait.</span>
      </div>
    );
  }

  return (
    <div className="flex h-full overflow-hidden">
      {/* LEFT: Chat */}
      <div className="flex flex-col w-72 shrink-0 border-r border-surface-2 overflow-hidden">
        {/* Model selector + actions */}
        <div className="flex items-center gap-2 px-2 py-1.5 border-b border-surface-2 bg-surface-1 shrink-0">
          {models.length > 0 ? (
            <select
              className="flex-1 bg-surface-2 rounded px-2 py-1 text-xs text-text-muted"
              value={model}
              onChange={e => setModel(e.target.value)}
            >
              {models.map(m => <option key={m}>{m}</option>)}
            </select>
          ) : (
            <span className="flex-1 text-xs text-text-muted px-1">
              {status?.ollama_available ? "Ollama ready" : "Ollama offline"}
            </span>
          )}
          {hasDesign && (
            <button onClick={resetDesign} className="text-xs text-text-muted hover:text-text px-1">
              new
            </button>
          )}
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-3 py-3 space-y-2.5">
          {messages.map((m, i) => (
            <div key={i}>
              {m.role === "system" && (
                <p className="text-text-muted text-xs italic leading-relaxed">{m.text}</p>
              )}
              {m.role === "user" && (
                <div className="flex justify-end">
                  <div className="bg-surface-2 rounded-lg rounded-br-sm px-3 py-2 text-sm max-w-[90%]">
                    {m.text}
                  </div>
                </div>
              )}
              {m.role === "assistant" && (
                <div className="text-sm text-text leading-relaxed">{m.text}</div>
              )}
            </div>
          ))}
          {loading && (
            <div className="flex gap-1 items-center text-text-muted text-xs">
              <span className="animate-pulse">Designing</span>
              <span className="animate-bounce" style={{ animationDelay: "0ms" }}>.</span>
              <span className="animate-bounce" style={{ animationDelay: "150ms" }}>.</span>
              <span className="animate-bounce" style={{ animationDelay: "300ms" }}>.</span>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div className="px-2 py-2 border-t border-surface-2 bg-surface-1 shrink-0">
          <div className="flex gap-1.5">
            <textarea
              ref={inputRef}
              className="flex-1 bg-surface-2 rounded px-2.5 py-1.5 text-sm resize-none placeholder:text-text-dim leading-snug"
              placeholder={status?.ollama_available
                ? "e.g. warm fuzz, gated, like a Rat…"
                : "Ollama offline — check http://localhost:11434"}
              rows={2}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => {
                if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
              }}
              disabled={loading || !status?.ollama_available}
            />
            <button
              onClick={send}
              disabled={loading || !input.trim() || !status?.ollama_available}
              className="px-3 rounded bg-accent text-surface text-sm font-medium hover:bg-accent-dim disabled:opacity-40 transition-colors self-end py-1.5"
            >
              →
            </button>
          </div>
          {!status?.ollama_available && (
            <p className="text-xs text-text-muted mt-1 px-1">
              Start Ollama: <code className="font-mono text-text-dim">ollama serve</code>
            </p>
          )}
        </div>
      </div>

      {/* RIGHT: Design visualization */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {/* Frequency response chart */}
        <FrequencyChart
          freqResponse={sim.frequency_response}
          fLow3db={sim.f_low_3db_hz}
          fHigh3db={sim.f_high_3db_hz}
          gain1khz={sim.gain_1khz_db}
        />

        {/* Signal chain */}
        {stages.length > 0 && <TransformPipeline stages={stages} />}

        {/* Virtual knobs */}
        {design?.pots?.length > 0 && <VirtualKnobs pots={design.pots} />}

        {/* Two-column: BOM + Audio */}
        <div className="grid grid-cols-2 gap-3">
          <CircuitInfo circuit={design?.circuit} simulation={sim} />
          <div className="flex flex-col gap-3">
            <AudioControls audioRunning={audioRunning} onRefresh={refreshAudioState} />
            {hasDesign && (
              <button
                onClick={saveKeeper}
                className="w-full py-2 rounded bg-accent/20 border border-accent/40 text-accent text-sm font-medium hover:bg-accent/30 transition-colors"
              >
                Save as Keeper
              </button>
            )}
          </div>
        </div>

        {/* SPICE error notice */}
        {sim.error && (
          <div className="bg-red-950/30 border border-red-800/50 rounded px-3 py-2 text-xs text-red-300">
            <span className="font-semibold">Simulation note: </span>{sim.error}
          </div>
        )}

        {/* Empty state */}
        {!hasDesign && (
          <div className="flex items-center justify-center py-12 text-text-muted text-sm">
            Describe an effect in the chat to design your first circuit.
          </div>
        )}
      </div>
    </div>
  );
}
