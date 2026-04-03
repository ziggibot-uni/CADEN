import React, { useRef, useCallback, useState } from 'react';
import KnobControl from './KnobControl';
import { updateKnob, toggleBypass } from '../utils/api';

export default function ControlPanel({ pots = [], bypassed, onBypassChange }) {
  const [localPots, setLocalPots] = useState({});
  const debounceTimers = useRef({});

  const handleKnobChange = useCallback(
    (stageIndex, paramName, value) => {
      const key = `${stageIndex}-${paramName}`;
      setLocalPots((prev) => ({ ...prev, [key]: value }));

      if (debounceTimers.current[key]) {
        clearTimeout(debounceTimers.current[key]);
      }

      debounceTimers.current[key] = setTimeout(() => {
        updateKnob(stageIndex, paramName, value).catch((err) =>
          console.error('Knob update failed:', err)
        );
      }, 50);
    },
    []
  );

  const handleBypass = async () => {
    try {
      const newState = !bypassed;
      await toggleBypass(newState);
      onBypassChange?.(newState);
    } catch (err) {
      console.error('Bypass toggle failed:', err);
    }
  };

  return (
    <div className="control-panel">
      <div className="bypass-toggle">
        <button
          className={`bypass-btn ${bypassed ? 'bypassed' : 'active'}`}
          onClick={handleBypass}
        >
          {bypassed ? 'OFF' : 'ON'}
        </button>
        <span className="bypass-label">{bypassed ? 'Bypassed' : 'Active'}</span>
      </div>

      <div className="control-panel-knobs">
        {pots.length === 0 && (
          <span style={{ color: '#555', fontSize: 13 }}>No controls available</span>
        )}
        {pots.map((pot, idx) => {
          const key = `${pot.stage_index ?? idx}-${pot.param_name ?? pot.name}`;
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
                handleKnobChange(
                  pot.stage_index ?? idx,
                  pot.param_name ?? pot.name,
                  v
                )
              }
            />
          );
        })}
      </div>
    </div>
  );
}
