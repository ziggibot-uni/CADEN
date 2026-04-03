import { useState, useEffect, useCallback } from "react";
import FrequencyChart from "./FrequencyChart";
import TransformPipeline from "./TransformPipeline";

export default function DesignHistory() {
  const [keepers, setKeepers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(null);
  const [loadingId, setLoadingId] = useState(null);
  const [loadedMsg, setLoadedMsg] = useState(null);

  const load = useCallback(async () => {
    try {
      const r = await fetch("/api/keepers");
      if (r.ok) setKeepers((await r.json()).keepers ?? []);
    } catch {}
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  async function loadDesign(id) {
    setLoadingId(id);
    try {
      const r = await fetch(`/api/keepers/${id}/load`, { method: "POST" });
      if (r.ok) {
        setLoadedMsg(id);
        setTimeout(() => setLoadedMsg(null), 3000);
      }
    } catch {}
    setLoadingId(null);
  }

  async function deleteKeeper(id) {
    try {
      await fetch(`/api/keepers/${id}`, { method: "DELETE" });
      setKeepers(k => k.filter(k => k.id !== id));
      if (expanded === id) setExpanded(null);
    } catch {}
  }

  if (loading) return <div className="p-4 text-text-muted text-sm">Loading…</div>;

  if (keepers.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3 text-text-muted text-sm">
        <span className="text-3xl opacity-30">◎</span>
        <span>No designs saved yet.</span>
        <span className="text-xs text-text-dim">Design something in the Design tab and save it as a Keeper.</span>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="flex-1 overflow-y-auto divide-y divide-surface-2">
        {keepers.map((k) => {
          const sim = k.simulation_results ?? {};
          const stages = k.transform_plan?.stages ?? [];
          const isOpen = expanded === k.id;
          const components = k.circuit_graph?.components ?? [];
          const missing = components.filter(c => !c.in_inventory);
          const ts = k.timestamp || k.created_at;

          return (
            <div key={k.id}>
              {/* Row header */}
              <div
                className="flex items-start gap-3 px-4 py-3 hover:bg-surface-1/40 cursor-pointer select-none"
                onClick={() => setExpanded(isOpen ? null : k.id)}
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-sm truncate">{k.name}</span>
                    {missing.length === 0 && components.length > 0 && (
                      <span className="text-[10px] text-green-400 border border-green-800/50 rounded px-1 py-0.5 shrink-0">buildable</span>
                    )}
                    {missing.length > 0 && (
                      <span className="text-[10px] text-red-400 border border-red-800/50 rounded px-1 py-0.5 shrink-0">{missing.length} missing</span>
                    )}
                  </div>

                  {stages.length > 0 && (
                    <div className="flex items-center gap-1 mt-0.5 flex-wrap">
                      {stages
                        .filter(s => !s.transform.startsWith("buffer"))
                        .map((s, i) => (
                          <span key={i} className="text-[10px] text-text-dim font-mono">{s.transform}{i < stages.filter(s => !s.transform.startsWith("buffer")).length - 1 ? " →" : ""}</span>
                        ))}
                    </div>
                  )}

                  <div className="text-[10px] text-text-dim mt-0.5">
                    {ts ? new Date(ts).toLocaleString() : ""}
                  </div>
                </div>

                <div className="flex flex-col items-end gap-1 shrink-0 text-xs font-mono">
                  {sim.gain_1khz_db != null && (
                    <span className="text-accent">{sim.gain_1khz_db.toFixed(1)} dB</span>
                  )}
                  {sim.current_draw_ma != null && (
                    <span className="text-text-muted">{sim.current_draw_ma.toFixed(1)} mA</span>
                  )}
                </div>

                <span className="text-text-muted text-xs mt-0.5">{isOpen ? "▲" : "▼"}</span>
              </div>

              {/* Expanded detail */}
              {isOpen && (
                <div className="px-4 pb-4 bg-surface-1/20 space-y-3">
                  {/* Frequency chart */}
                  {sim.frequency_response?.length > 0 && (
                    <FrequencyChart
                      freqResponse={sim.frequency_response}
                      fLow3db={sim.f_low_3db_hz}
                      fHigh3db={sim.f_high_3db_hz}
                      gain1khz={sim.gain_1khz_db}
                    />
                  )}

                  {/* Transform pipeline */}
                  {stages.length > 0 && <TransformPipeline stages={stages} />}

                  {/* Intent */}
                  {k.intent_description && k.intent_description !== k.name && (
                    <p className="text-xs text-text-muted italic">"{k.intent_description}"</p>
                  )}

                  {/* Stats grid */}
                  {Object.keys(sim).length > 0 && (
                    <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs text-text-muted">
                      {sim.gain_1khz_db != null && <div>Gain @ 1kHz <span className="text-text float-right">{sim.gain_1khz_db.toFixed(1)} dB</span></div>}
                      {sim.f_low_3db_hz != null && <div>Low −3dB <span className="text-text float-right">{sim.f_low_3db_hz.toFixed(0)} Hz</span></div>}
                      {sim.f_high_3db_hz != null && <div>High −3dB <span className="text-text float-right">{sim.f_high_3db_hz < 1000 ? `${sim.f_high_3db_hz.toFixed(0)} Hz` : `${(sim.f_high_3db_hz/1000).toFixed(1)} kHz`}</span></div>}
                      {sim.current_draw_ma != null && <div>Current draw <span className="text-text float-right">{sim.current_draw_ma.toFixed(1)} mA</span></div>}
                      {sim.thd_1khz_percent != null && <div>THD @ 1kHz <span className="text-text float-right">{sim.thd_1khz_percent.toFixed(2)}%</span></div>}
                    </div>
                  )}

                  {/* Component count */}
                  {components.length > 0 && (
                    <div className="text-xs text-text-muted">
                      {components.length} components · {components.length - missing.length} in stock
                      {missing.length > 0 && (
                        <span className="text-red-400 ml-1">
                          · missing: {missing.slice(0, 3).map(c => c.value_display || c.type).join(", ")}
                          {missing.length > 3 && ` +${missing.length - 3}`}
                        </span>
                      )}
                    </div>
                  )}

                  {/* SPICE netlist preview */}
                  {k.spice_netlist && (
                    <details className="text-xs">
                      <summary className="text-text-muted cursor-pointer hover:text-text">SPICE netlist</summary>
                      <pre className="mt-1 p-2 bg-surface-2 rounded font-mono text-[10px] overflow-x-auto text-text-dim leading-relaxed max-h-40 overflow-y-auto">
                        {k.spice_netlist}
                      </pre>
                    </details>
                  )}

                  {/* Actions */}
                  <div className="flex gap-2 pt-1">
                    {loadedMsg === k.id ? (
                      <span className="px-3 py-1.5 rounded text-xs text-green-400">✓ Loaded into DSP engine</span>
                    ) : (
                      <button
                        onClick={() => loadDesign(k.id)}
                        disabled={loadingId === k.id}
                        className="px-3 py-1.5 rounded bg-accent text-surface text-xs font-medium hover:bg-accent-dim disabled:opacity-50 transition-colors"
                      >
                        {loadingId === k.id ? "Loading…" : "Load into DSP"}
                      </button>
                    )}
                    <button
                      onClick={() => deleteKeeper(k.id)}
                      className="px-3 py-1.5 rounded bg-surface-2 text-xs text-red-400 hover:bg-red-950/50 transition-colors"
                    >
                      Delete
                    </button>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div className="px-4 py-2 bg-surface-1 border-t border-surface-2 text-xs text-text-muted shrink-0">
        {keepers.length} saved design{keepers.length !== 1 ? "s" : ""}
      </div>
    </div>
  );
}
