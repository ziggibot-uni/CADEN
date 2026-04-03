import { useState, useEffect } from "react";

export default function AudioControls({ audioRunning, onRefresh }) {
  const [devices, setDevices] = useState([]);
  const [inputDevice, setInputDevice] = useState(null);
  const [outputDevice, setOutputDevice] = useState(null);
  const [bufferSize, setBufferSize] = useState(256);
  const [loading, setLoading] = useState(false);
  const [bypass, setBypass] = useState(false);
  const [showDevices, setShowDevices] = useState(false);
  const [levels, setLevels] = useState({ in: 0, out: 0 });

  useEffect(() => {
    fetch("/api/audio/devices").then(r => r.ok ? r.json() : null).then(d => {
      if (d?.devices) setDevices(d.devices);
    }).catch(() => {});
  }, []);

  // Poll levels when audio is running
  useEffect(() => {
    if (!audioRunning) { setLevels({ in: 0, out: 0 }); return; }
    const id = setInterval(async () => {
      try {
        const r = await fetch("/api/audio/status");
        if (r.ok) {
          const d = await r.json();
          setLevels({ in: d.input_level ?? 0, out: d.output_level ?? 0 });
          setBypass(d.bypass ?? false);
        }
      } catch {}
    }, 150);
    return () => clearInterval(id);
  }, [audioRunning]);

  async function startAudio() {
    setLoading(true);
    try {
      // Configure first
      await fetch("/api/audio/configure", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          input_device: inputDevice,
          output_device: outputDevice,
          buffer_size: bufferSize,
        }),
      });
      await fetch("/api/audio/start", { method: "POST" });
      onRefresh?.();
    } catch {}
    setLoading(false);
  }

  async function stopAudio() {
    setLoading(true);
    try { await fetch("/api/audio/stop", { method: "POST" }); onRefresh?.(); }
    catch {}
    setLoading(false);
  }

  async function toggleBypass() {
    const next = !bypass;
    try {
      await fetch(`/api/audio/bypass?enabled=${next}`, { method: "POST" });
      setBypass(next);
    } catch {}
  }

  function LevelBar({ value }) {
    const pct = Math.min(100, value * 100);
    const color = pct > 80 ? "#e05050" : pct > 50 ? "#d4a030" : "#1aabbc";
    return (
      <div className="w-full h-1.5 bg-surface-2 rounded-full overflow-hidden">
        <div className="h-full rounded-full transition-all duration-75" style={{ width: `${pct}%`, backgroundColor: color }} />
      </div>
    );
  }

  const inputDevices = devices.filter(d => d.max_input_channels > 0);
  const outputDevices = devices.filter(d => d.max_output_channels > 0);

  return (
    <div className="bg-surface-1 rounded border border-surface-2 overflow-hidden">
      <div className="px-3 py-1.5 border-b border-surface-2 flex items-center justify-between">
        <span className="text-xs font-mono text-text-muted uppercase tracking-wide">Audio</span>
        <button
          onClick={() => setShowDevices(s => !s)}
          className="text-xs text-text-muted hover:text-text transition-colors"
        >
          {showDevices ? "hide" : "devices"}
        </button>
      </div>

      {showDevices && (
        <div className="px-3 py-2 border-b border-surface-2 space-y-2 text-xs">
          <div className="flex gap-2 flex-wrap">
            <div className="flex flex-col gap-1 flex-1 min-w-[140px]">
              <label className="text-text-muted">Input</label>
              <select
                className="bg-surface-2 rounded px-2 py-1 text-text"
                value={inputDevice ?? ""}
                onChange={e => setInputDevice(e.target.value === "" ? null : Number(e.target.value))}
              >
                <option value="">Default</option>
                {inputDevices.map(d => (
                  <option key={d.index} value={d.index}>{d.name}</option>
                ))}
              </select>
            </div>
            <div className="flex flex-col gap-1 flex-1 min-w-[140px]">
              <label className="text-text-muted">Output</label>
              <select
                className="bg-surface-2 rounded px-2 py-1 text-text"
                value={outputDevice ?? ""}
                onChange={e => setOutputDevice(e.target.value === "" ? null : Number(e.target.value))}
              >
                <option value="">Default</option>
                {outputDevices.map(d => (
                  <option key={d.index} value={d.index}>{d.name}</option>
                ))}
              </select>
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-text-muted">Buffer</label>
              <select
                className="bg-surface-2 rounded px-2 py-1 text-text"
                value={bufferSize}
                onChange={e => setBufferSize(Number(e.target.value))}
              >
                {[64, 128, 256, 512].map(b => (
                  <option key={b} value={b}>{b} samples</option>
                ))}
              </select>
            </div>
          </div>
        </div>
      )}

      <div className="px-3 py-2 flex items-center gap-3">
        {/* Start/Stop */}
        <button
          onClick={audioRunning ? stopAudio : startAudio}
          disabled={loading}
          className={`px-3 py-1.5 rounded text-sm font-medium transition-colors disabled:opacity-40 ${
            audioRunning
              ? "bg-green-800/50 text-green-300 border border-green-700/50 hover:bg-green-800/70"
              : "bg-surface-2 text-text-muted hover:bg-surface-3"
          }`}
        >
          {loading ? "…" : audioRunning ? "● Audio ON" : "Start Audio"}
        </button>

        {/* Bypass */}
        {audioRunning && (
          <button
            onClick={toggleBypass}
            className={`px-3 py-1.5 rounded text-sm font-medium transition-colors border ${
              bypass
                ? "border-surface-3 text-text-muted bg-transparent"
                : "border-accent/60 text-accent bg-accent/10 hover:bg-accent/20"
            }`}
          >
            {bypass ? "Bypassed" : "Effect ON"}
          </button>
        )}

        {/* Level meters */}
        {audioRunning && (
          <div className="flex-1 flex flex-col gap-1 text-[10px] text-text-muted">
            <div className="flex items-center gap-1.5">
              <span className="w-3 shrink-0">IN</span>
              <LevelBar value={levels.in} />
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-3 shrink-0">OUT</span>
              <LevelBar value={levels.out} />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
