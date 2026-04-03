import { useRef, useCallback, useState } from "react";
import KnobControl from "./KnobControl";
import { updateKnob, toggleBypass } from "./api";

interface Pot {
  stage_index?: number;
  param_name?: string;
  name?: string;
  label?: string;
  value?: number;
  default?: number;
  min?: number;
  max?: number;
  step?: number;
}

interface ControlPanelProps {
  pots?: Pot[];
  bypassed?: boolean;
  onBypassChange?: (bypassed: boolean) => void;
}

export default function ControlPanel({ pots = [], bypassed, onBypassChange }: ControlPanelProps) {
  const [localPots, setLocalPots] = useState<Record<string, number>>({});
  const debounceTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  const handleKnobChange = useCallback((stageIndex: number, paramName: string, value: number) => {
    const key = `${stageIndex}-${paramName}`;
    setLocalPots((prev) => ({ ...prev, [key]: value }));
    if (debounceTimers.current[key]) clearTimeout(debounceTimers.current[key]);
    debounceTimers.current[key] = setTimeout(() => {
      updateKnob(stageIndex, paramName, value).catch((err) =>
        console.error("Knob update failed:", err)
      );
    }, 50);
  }, []);

  const handleBypass = async () => {
    try {
      const newState = !bypassed;
      await toggleBypass(newState);
      onBypassChange?.(newState);
    } catch (err) {
      console.error("Bypass toggle failed:", err);
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-3">
        <button
          onClick={handleBypass}
          className={`px-3 py-1 rounded text-xs font-bold transition-all ${
            bypassed
              ? "bg-surface-2 text-text-dim border border-surface-3"
              : "bg-accent-DEFAULT text-surface"
          }`}
        >
          {bypassed ? "OFF" : "ON"}
        </button>
        <span className="text-xs text-text-dim">{bypassed ? "Bypassed" : "Active"}</span>
      </div>

      <div className="flex flex-wrap gap-4">
        {pots.length === 0 && (
          <span className="text-text-dim text-xs opacity-40">No controls available</span>
        )}
        {pots.map((pot, idx) => {
          const key = `${pot.stage_index ?? idx}-${pot.param_name ?? pot.name ?? idx}`;
          const displayValue = localPots[key] ?? pot.value ?? pot.default ?? 0.5;
          return (
            <KnobControl
              key={key}
              label={pot.label || pot.name || pot.param_name || `Knob ${idx + 1}`}
              value={displayValue}
              min={pot.min ?? 0}
              max={pot.max ?? 1}
              step={pot.step ?? 0.01}
              onChange={(v) =>
                handleKnobChange(pot.stage_index ?? idx, pot.param_name ?? pot.name ?? String(idx), v)
              }
            />
          );
        })}
      </div>
    </div>
  );
}
