import React, { useMemo } from 'react';

const MARGIN = { top: 20, right: 20, bottom: 35, left: 45 };
const FREQ_MIN = 20;
const FREQ_MAX = 20000;
const DB_MIN = -30;
const DB_MAX = 30;
const MAJOR_FREQS = [20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000];
const MAJOR_DBS = [-30, -20, -10, 0, 10, 20, 30];

function freqToX(freq, width) {
  const logMin = Math.log10(FREQ_MIN);
  const logMax = Math.log10(FREQ_MAX);
  return MARGIN.left + ((Math.log10(freq) - logMin) / (logMax - logMin)) * width;
}

function dbToY(db, height) {
  return MARGIN.top + ((DB_MAX - db) / (DB_MAX - DB_MIN)) * height;
}

function formatFreq(f) {
  if (f >= 1000) return (f / 1000) + 'k';
  return String(f);
}

export default function FrequencyResponse({ data = [] }) {
  const viewW = 500;
  const viewH = 220;
  const plotW = viewW - MARGIN.left - MARGIN.right;
  const plotH = viewH - MARGIN.top - MARGIN.bottom;

  const pathD = useMemo(() => {
    if (!data || data.length === 0) return '';
    const sorted = [...data].sort((a, b) => a.frequency - b.frequency);
    return sorted
      .map((pt, i) => {
        const x = freqToX(pt.frequency, plotW);
        const y = dbToY(pt.magnitude, plotH);
        return `${i === 0 ? 'M' : 'L'}${x},${y}`;
      })
      .join(' ');
  }, [data, plotW, plotH]);

  const minus3dBPoints = useMemo(() => {
    if (!data || data.length < 2) return [];
    const sorted = [...data].sort((a, b) => a.frequency - b.frequency);
    const peakMag = Math.max(...sorted.map((p) => p.magnitude));
    const target = peakMag - 3;
    const points = [];
    for (let i = 1; i < sorted.length; i++) {
      const prev = sorted[i - 1];
      const curr = sorted[i];
      if ((prev.magnitude - target) * (curr.magnitude - target) <= 0) {
        const ratio = (target - prev.magnitude) / (curr.magnitude - prev.magnitude);
        const freq = prev.frequency + ratio * (curr.frequency - prev.frequency);
        points.push({ frequency: freq, magnitude: target });
      }
    }
    return points;
  }, [data]);

  return (
    <div className="freq-chart">
      <svg viewBox={`0 0 ${viewW} ${viewH}`} preserveAspectRatio="xMidYMid meet">
        {/* Grid lines - frequency */}
        {MAJOR_FREQS.map((f) => {
          const x = freqToX(f, plotW);
          return (
            <g key={`f${f}`}>
              <line className="grid-line" x1={x} y1={MARGIN.top} x2={x} y2={MARGIN.top + plotH} />
              <text x={x} y={viewH - 5} textAnchor="middle">{formatFreq(f)}</text>
            </g>
          );
        })}

        {/* Grid lines - dB */}
        {MAJOR_DBS.map((db) => {
          const y = dbToY(db, plotH);
          return (
            <g key={`db${db}`}>
              <line className="grid-line" x1={MARGIN.left} y1={y} x2={MARGIN.left + plotW} y2={y} />
              <text x={MARGIN.left - 6} y={y + 3} textAnchor="end">{db}</text>
            </g>
          );
        })}

        {/* Axes */}
        <line className="axis-line" x1={MARGIN.left} y1={MARGIN.top} x2={MARGIN.left} y2={MARGIN.top + plotH} />
        <line className="axis-line" x1={MARGIN.left} y1={MARGIN.top + plotH} x2={MARGIN.left + plotW} y2={MARGIN.top + plotH} />

        {/* 0dB reference line */}
        <line
          x1={MARGIN.left}
          y1={dbToY(0, plotH)}
          x2={MARGIN.left + plotW}
          y2={dbToY(0, plotH)}
          stroke="#333"
          strokeWidth="1"
          strokeDasharray="4,4"
        />

        {/* Response curve */}
        {pathD && <path className="response-line" d={pathD} />}

        {/* -3dB points */}
        {minus3dBPoints.map((pt, i) => {
          const x = freqToX(pt.frequency, plotW);
          const y = dbToY(pt.magnitude, plotH);
          return (
            <g key={`m3db${i}`}>
              <circle cx={x} cy={y} r={4} fill="rgb(var(--c-status-star))" stroke="#0a0a0a" strokeWidth={1.5} />
              <text x={x} y={y - 8} textAnchor="middle" fill="rgb(var(--c-status-star))" fontSize="9">
                {formatFreq(Math.round(pt.frequency))}
              </text>
            </g>
          );
        })}

        {/* Label */}
        <text className="chart-label" x={viewW / 2} y={12} textAnchor="middle">
          Frequency Response
        </text>

        {/* Empty state */}
        {(!data || data.length === 0) && (
          <text x={viewW / 2} y={viewH / 2} textAnchor="middle" fill="#444" fontSize="13">
            No frequency data
          </text>
        )}
      </svg>
    </div>
  );
}
