import React, { useRef, useCallback, useState } from 'react';

const KNOB_SIZE = 60;
const RADIUS = 22;
const START_ANGLE = 225; // 7 o'clock in degrees (0 = 3 o'clock)
const END_ANGLE = -45;   // 5 o'clock
const SWEEP = 270;

function valueToAngle(value) {
  return START_ANGLE - value * SWEEP;
}

export default function KnobControl({ label, value = 0, onChange, min = 0, max = 1, step = 0.01 }) {
  const [dragging, setDragging] = useState(false);
  const dragRef = useRef({ startY: 0, startValue: 0 });
  const cx = KNOB_SIZE / 2;
  const cy = KNOB_SIZE / 2;

  const normalizedValue = (value - min) / (max - min);
  const angle = valueToAngle(normalizedValue);
  const rad = (angle * Math.PI) / 180;
  const indicatorX = cx + (RADIUS - 4) * Math.cos(rad);
  const indicatorY = cy - (RADIUS - 4) * Math.sin(rad);
  const innerX = cx + (RADIUS - 14) * Math.cos(rad);
  const innerY = cy - (RADIUS - 14) * Math.sin(rad);

  const handleMouseDown = useCallback(
    (e) => {
      e.preventDefault();
      dragRef.current = { startY: e.clientY, startValue: normalizedValue };
      setDragging(true);

      const handleMouseMove = (e) => {
        const dy = dragRef.current.startY - e.clientY;
        const sensitivity = 200;
        let newNorm = dragRef.current.startValue + dy / sensitivity;
        newNorm = Math.max(0, Math.min(1, newNorm));
        const newValue = min + newNorm * (max - min);
        const stepped = Math.round(newValue / step) * step;
        onChange?.(Math.max(min, Math.min(max, stepped)));
      };

      const handleMouseUp = () => {
        setDragging(false);
        window.removeEventListener('mousemove', handleMouseMove);
        window.removeEventListener('mouseup', handleMouseUp);
      };

      window.addEventListener('mousemove', handleMouseMove);
      window.addEventListener('mouseup', handleMouseUp);
    },
    [normalizedValue, min, max, step, onChange]
  );

  // Tick marks
  const ticks = [];
  for (let i = 0; i <= 10; i++) {
    const t = i / 10;
    const a = valueToAngle(t);
    const r = (a * Math.PI) / 180;
    const outerR = RADIUS + 2;
    const innerR = RADIUS - 1;
    ticks.push(
      <line
        key={i}
        x1={cx + innerR * Math.cos(r)}
        y1={cy - innerR * Math.sin(r)}
        x2={cx + outerR * Math.cos(r)}
        y2={cy - outerR * Math.sin(r)}
        stroke={i <= normalizedValue * 10 ? 'rgb(var(--c-status-success))' : '#333'}
        strokeWidth={i % 5 === 0 ? 1.5 : 0.8}
      />
    );
  }

  const displayValue = typeof value === 'number' ? value.toFixed(step < 1 ? 2 : 0) : value;

  return (
    <div className="knob-wrapper">
      <div className="knob-label">{label}</div>
      <svg
        className="knob-svg"
        width={KNOB_SIZE}
        height={KNOB_SIZE}
        viewBox={`0 0 ${KNOB_SIZE} ${KNOB_SIZE}`}
        onMouseDown={handleMouseDown}
      >
        {/* Ticks */}
        {ticks}

        {/* Outer ring */}
        <circle cx={cx} cy={cy} r={RADIUS} fill="#222" stroke="#3a3a3a" strokeWidth="1.5" />

        {/* Inner fill */}
        <circle cx={cx} cy={cy} r={RADIUS - 4} fill="#2a2a2a" />

        {/* Indicator line */}
        <line
          x1={innerX}
          y1={innerY}
          x2={indicatorX}
          y2={indicatorY}
          stroke="rgb(var(--c-status-success))"
          strokeWidth="2.5"
          strokeLinecap="round"
        />

        {/* Center dot */}
        <circle cx={cx} cy={cy} r={3} fill="#1a1a1a" stroke="#333" strokeWidth="0.5" />
      </svg>
      <div className="knob-value">{displayValue}</div>
    </div>
  );
}
