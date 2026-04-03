import { useState, useCallback } from "react";

async function postKnob(stageIndex, paramName, value) {
  try {
    await fetch("/api/knob", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stage_index: stageIndex, param_name: paramName, value }),
    });
  } catch {}
}

function Knob({ pot }) {
  const [value, setValue] = useState(pot.default ?? ((pot.min + pot.max) / 2));

  const handleChange = useCallback((e) => {
    const v = parseFloat(e.target.value);
    setValue(v);
    postKnob(pot.stage_index, pot.param_name, v);
  }, [pot.stage_index, pot.param_name]);

  const pct = ((value - pot.min) / (pot.max - pot.min)) * 100;
  const displayVal = pot.unit === "Hz"
    ? value >= 1000 ? `${(value / 1000).toFixed(1)}k` : `${Math.round(value)}`
    : pot.unit === "dB"
    ? `${value >= 0 ? "+" : ""}${value.toFixed(1)}`
    : value.toFixed(value % 1 === 0 ? 0 : 2);

  return (
    <div className="flex flex-col gap-1.5 items-center min-w-[72px]">
      {/* SVG knob indicator */}
      <div className="relative w-12 h-12">
        <svg viewBox="0 0 48 48" className="w-full h-full">
          {/* Track arc */}
          <circle cx="24" cy="24" r="18" fill="none" stroke="#305972" strokeWidth="3" />
          {/* Value arc */}
          <circle
            cx="24" cy="24" r="18"
            fill="none"
            stroke="#1aabbc"
            strokeWidth="3"
            strokeLinecap="round"
            strokeDasharray={`${pct * 1.131} 113.1`}
            strokeDashoffset="0"
            transform="rotate(-90 24 24)"
            opacity={0.85}
          />
          {/* Center dot */}
          <circle cx="24" cy="24" r="4" fill="#244b5f" stroke="#366678" strokeWidth="1.5" />
        </svg>
      </div>

      <input
        type="range"
        min={pot.min}
        max={pot.max}
        step={(pot.max - pot.min) / 200}
        value={value}
        onChange={handleChange}
        className="w-full accent-accent h-0.5"
        style={{ width: "72px" }}
      />

      <div className="text-center">
        <div className="text-[10px] font-mono text-accent">{displayVal}{pot.unit && pot.unit !== "Hz" && pot.unit !== "dB" ? ` ${pot.unit}` : ""}{pot.unit === "Hz" ? "Hz" : ""}</div>
        <div className="text-[9px] text-text-muted mt-0.5 leading-tight max-w-[72px] truncate">{pot.label}</div>
      </div>
    </div>
  );
}

export default function VirtualKnobs({ pots }) {
  if (!pots || pots.length === 0) return null;

  return (
    <div className="bg-surface-1 rounded border border-surface-2 px-3 py-2">
      <div className="text-xs font-mono text-text-muted uppercase tracking-wide mb-3">Controls</div>
      <div className="flex gap-4 flex-wrap">
        {pots.map((pot, i) => (
          <Knob key={`${pot.stage_index}-${pot.param_name}-${i}`} pot={pot} />
        ))}
      </div>
    </div>
  );
}
