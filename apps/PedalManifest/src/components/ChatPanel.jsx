import { useState, useRef, useEffect } from "react";

export default function ChatPanel({ online, status }) {
  const [messages, setMessages] = useState([
    { role: "system", text: "Describe a guitar effect in plain language. PedalForge will design a circuit from your inventory, validate it with SPICE, and build a DSP model you can play through." },
  ]);
  const [input, setInput] = useState("");
  const [model, setModel] = useState("mistral");
  const [models, setModels] = useState([]);
  const [loading, setLoading] = useState(false);
  const [design, setDesign] = useState(null);
  const [pots, setPots] = useState([]);
  const bottomRef = useRef(null);

  useEffect(() => {
    fetch("/api/ai/models").then(r => r.ok ? r.json() : null).then(d => {
      if (d?.models?.length) setModels(d.models);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function send() {
    if (!input.trim() || loading) return;
    const userMsg = input.trim();
    setInput("");
    setMessages(m => [...m, { role: "user", text: userMsg }]);
    setLoading(true);
    try {
      const r = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: userMsg, model }),
      });
      const d = await r.json();
      setMessages(m => [...m, { role: "assistant", text: d.response || "No response." }]);
      if (d.circuit) setDesign(d);
      if (d.pots) setPots(d.pots || []);
    } catch (e) {
      setMessages(m => [...m, { role: "assistant", text: `Error: ${e.message}` }]);
    }
    setLoading(false);
  }

  async function updateKnob(stageIndex, paramName, value) {
    await fetch("/api/knob", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stage_index: stageIndex, param_name: paramName, value }),
    });
  }

  async function toggleAudio() {
    if (status?.audio_running) {
      await fetch("/api/audio/stop", { method: "POST" });
    } else {
      await fetch("/api/audio/start", { method: "POST" });
    }
  }

  async function saveKeeper() {
    if (!design) return;
    const name = prompt("Name this design:");
    if (!name) return;
    await fetch("/api/keepers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, intent_description: name }),
    });
  }

  if (!online) {
    return (
      <div className="flex items-center justify-center h-full text-text-muted text-sm">
        Backend not running — CADEN is starting it now. Please wait.
      </div>
    );
  }

  return (
    <div className="flex h-full overflow-hidden">
      {/* Chat column */}
      <div className="flex flex-col flex-1 overflow-hidden">
        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-3 py-2 space-y-2">
          {messages.map((m, i) => (
            <div
              key={i}
              className={`text-sm leading-relaxed ${
                m.role === "user"
                  ? "text-text bg-surface-2 rounded-lg px-3 py-2 self-end max-w-[80%] ml-auto"
                  : m.role === "system"
                  ? "text-text-muted italic"
                  : "text-text"
              }`}
            >
              {m.text}
            </div>
          ))}
          {loading && <div className="text-text-muted text-sm animate-pulse">Designing…</div>}
          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div className="flex gap-2 px-3 py-2 border-t border-surface-2 bg-surface-1 shrink-0">
          {models.length > 0 && (
            <select
              className="bg-surface-2 rounded px-2 py-1 text-xs text-text-muted"
              value={model}
              onChange={e => setModel(e.target.value)}
            >
              {models.map(m => <option key={m}>{m}</option>)}
            </select>
          )}
          <input
            className="flex-1 bg-surface-2 rounded px-3 py-1.5 text-sm placeholder:text-text-dim"
            placeholder="Describe an effect… e.g. warm fuzz, gated, like a Rat"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === "Enter" && send()}
          />
          <button
            onClick={send}
            disabled={loading || !input.trim()}
            className="px-3 py-1.5 rounded bg-accent text-surface text-sm font-medium hover:bg-accent-dim disabled:opacity-40 transition-colors"
          >
            Send
          </button>
        </div>
      </div>

      {/* Right panel: design state + controls */}
      {design && (
        <div className="w-52 border-l border-surface-2 bg-surface-1 flex flex-col overflow-hidden shrink-0">
          <div className="px-3 py-2 border-b border-surface-2 text-xs font-semibold text-text-muted uppercase tracking-wide">
            Design
          </div>
          <div className="flex-1 overflow-y-auto px-3 py-2 space-y-3 text-xs">
            {/* Simulation stats */}
            {design.simulation?.success && (
              <div className="space-y-1 text-text-muted">
                {design.simulation.gain_1khz_db !== undefined && (
                  <div>Gain: <span className="text-text">{design.simulation.gain_1khz_db.toFixed(1)} dB</span></div>
                )}
                {design.simulation.f_low_3db_hz !== undefined && (
                  <div>Low −3dB: <span className="text-text">{design.simulation.f_low_3db_hz.toFixed(0)} Hz</span></div>
                )}
                {design.simulation.f_high_3db_hz !== undefined && (
                  <div>High −3dB: <span className="text-text">{design.simulation.f_high_3db_hz.toFixed(0)} Hz</span></div>
                )}
                {design.simulation.current_draw_ma !== undefined && (
                  <div>Current: <span className="text-text">{design.simulation.current_draw_ma.toFixed(1)} mA</span></div>
                )}
              </div>
            )}

            {/* Pots */}
            {pots.length > 0 && (
              <div className="space-y-2">
                <div className="text-text-muted font-semibold">Controls</div>
                {pots.map((pot, idx) => (
                  <div key={idx}>
                    <div className="text-text-muted mb-0.5">{pot.label || `Pot ${idx + 1}`}</div>
                    <input
                      type="range" min="0" max="1" step="0.01"
                      defaultValue="0.5"
                      className="w-full accent-accent"
                      onChange={e => updateKnob(pot.stage_index, pot.param_name, Number(e.target.value))}
                    />
                  </div>
                ))}
              </div>
            )}

            {/* Inventory */}
            {design.circuit?.components && (
              <div className="space-y-1">
                <div className="text-text-muted font-semibold">Components</div>
                {design.circuit.components.filter(c => !c.in_inventory).slice(0, 5).map((c, i) => (
                  <div key={i} className="text-red-300">⚠ {c.value_display} {c.type}</div>
                ))}
                {design.circuit.components.every(c => c.in_inventory) && (
                  <div className="text-green-300">All in stock</div>
                )}
              </div>
            )}
          </div>

          {/* Actions */}
          <div className="px-3 py-2 border-t border-surface-2 space-y-1 shrink-0">
            <button
              onClick={toggleAudio}
              className={`w-full py-1.5 rounded text-xs font-medium transition-colors ${
                status?.audio_running
                  ? "bg-green-800/60 text-green-300 hover:bg-green-800/80"
                  : "bg-surface-2 text-text-muted hover:bg-surface-3"
              }`}
            >
              {status?.audio_running ? "● Audio ON" : "Start Audio"}
            </button>
            <button
              onClick={saveKeeper}
              className="w-full py-1.5 rounded text-xs bg-surface-2 text-text-muted hover:bg-surface-3"
            >
              Save as Keeper
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
