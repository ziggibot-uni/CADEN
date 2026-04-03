import { useRef, useCallback, useState } from "react";

const KNOB_SIZE = 60;
const RADIUS = 22;
const START_ANGLE = 225;
const SWEEP = 270;

function valueToAngle(value: number) {
  return START_ANGLE - value * SWEEP;
}

interface KnobControlProps {
  label: string;
  value?: number;
  onChange?: (value: number) => void;
  min?: number;
  max?: number;
  step?: number;
}

export default function KnobControl({ label, value = 0, onChange, min = 0, max = 1, step = 0.01 }: KnobControlProps) {
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
    (e: React.MouseEvent) => {
      e.preventDefault();
      dragRef.current = { startY: e.clientY, startValue: normalizedValue };
      setDragging(true);

      const handleMouseMove = (e: MouseEvent) => {
        const dy = dragRef.current.startY - e.clientY;
        let newNorm = dragRef.current.startValue + dy / 200;
        newNorm = Math.max(0, Math.min(1, newNorm));
        const newValue = min + newNorm * (max - min);
        const stepped = Math.round(newValue / step) * step;
        onChange?.(Math.max(min, Math.min(max, stepped)));
      };

      const handleMouseUp = () => {
        setDragging(false);
        window.removeEventListener("mousemove", handleMouseMove);
        window.removeEventListener("mouseup", handleMouseUp);
      };

      window.addEventListener("mousemove", handleMouseMove);
      window.addEventListener("mouseup", handleMouseUp);
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
    const active = i <= normalizedValue * 10;
    ticks.push(
      <line
        key={i}
        x1={cx + innerR * Math.cos(r)}
        y1={cy - innerR * Math.sin(r)}
        x2={cx + outerR * Math.cos(r)}
        y2={cy - outerR * Math.sin(r)}
        stroke={active ? "rgb(var(--c-accent))" : "rgb(var(--c-surface-3))"}
        strokeWidth={i % 5 === 0 ? 1.5 : 0.8}
      />
    );
  }

  const displayValue = typeof value === "number" ? value.toFixed(step < 1 ? 2 : 0) : value;

  return (
    <div className={`flex flex-col items-center gap-1 select-none${dragging ? " cursor-grabbing" : " cursor-grab"}`}>
      <div className="text-[10px] text-text-dim opacity-70 text-center leading-tight">{label}</div>
      <svg
        width={KNOB_SIZE}
        height={KNOB_SIZE}
        viewBox={`0 0 ${KNOB_SIZE} ${KNOB_SIZE}`}
        onMouseDown={handleMouseDown}
      >
        {ticks}
        <circle cx={cx} cy={cy} r={RADIUS} fill="rgb(var(--c-surface-1))" stroke="rgb(var(--c-surface-2))" strokeWidth="1.5" />
        <circle cx={cx} cy={cy} r={RADIUS - 4} fill="rgb(var(--c-surface-2))" />
        <line
          x1={innerX}
          y1={innerY}
          x2={indicatorX}
          y2={indicatorY}
          stroke="rgb(var(--c-accent))"
          strokeWidth="2.5"
          strokeLinecap="round"
        />
        <circle cx={cx} cy={cy} r={3} fill="rgb(var(--c-surface))" stroke="rgb(var(--c-surface-2))" strokeWidth="0.5" />
      </svg>
      <div className="text-[10px] text-text-dim font-mono">{displayValue}</div>
    </div>
  );
}
