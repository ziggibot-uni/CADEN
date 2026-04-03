// SVG frequency response chart.
// freqResponse: [{frequency, magnitude}] where magnitude is linear voltage gain.
// Renders on a log-frequency axis, dB Y axis.

const W = 480;
const H = 160;
const PAD = { top: 10, right: 16, bottom: 28, left: 40 };

const PLOT_W = W - PAD.left - PAD.right;
const PLOT_H = H - PAD.top - PAD.bottom;

const F_MIN = 20;
const F_MAX = 20000;
const DB_MIN = -30;
const DB_MAX = 30;

function freqToX(f) {
  return PAD.left + (Math.log10(f / F_MIN) / Math.log10(F_MAX / F_MIN)) * PLOT_W;
}

function dbToY(db) {
  const clamped = Math.max(DB_MIN, Math.min(DB_MAX, db));
  return PAD.top + ((DB_MAX - clamped) / (DB_MAX - DB_MIN)) * PLOT_H;
}

function linToDb(lin) {
  if (lin <= 0) return -60;
  return 20 * Math.log10(lin);
}

const FREQ_LABELS = [20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000];
const DB_LINES = [-30, -20, -10, 0, 10, 20, 30];

export default function FrequencyChart({ freqResponse, fLow3db, fHigh3db, gain1khz }) {
  const hasData = freqResponse && freqResponse.length > 0;

  // Build SVG path from frequency response data
  let pathD = "";
  if (hasData) {
    const points = freqResponse
      .filter((p) => p.frequency >= F_MIN && p.frequency <= F_MAX)
      .map((p) => ({ x: freqToX(p.frequency), y: dbToY(linToDb(p.magnitude)) }));

    if (points.length > 0) {
      pathD = `M ${points[0].x} ${points[0].y} ` +
        points.slice(1).map((p) => `L ${p.x} ${p.y}`).join(" ");
    }
  }

  return (
    <div className="bg-surface-1 rounded border border-surface-2 overflow-hidden">
      <div className="px-3 py-1.5 border-b border-surface-2 flex items-center justify-between">
        <span className="text-xs font-mono text-text-muted uppercase tracking-wide">Frequency Response</span>
        {gain1khz != null && (
          <span className="text-xs font-mono text-accent">{gain1khz.toFixed(1)} dB @ 1kHz</span>
        )}
      </div>
      <svg width="100%" viewBox={`0 0 ${W} ${H}`} className="block" style={{ height: H }}>
        {/* Grid: dB lines */}
        {DB_LINES.map((db) => {
          const y = dbToY(db);
          return (
            <g key={db}>
              <line
                x1={PAD.left} y1={y} x2={W - PAD.right} y2={y}
                stroke={db === 0 ? "#366678" : "#305972"}
                strokeWidth={db === 0 ? 1 : 0.5}
                strokeDasharray={db === 0 ? "none" : "3,3"}
              />
              <text x={PAD.left - 4} y={y + 3.5} textAnchor="end" fill="#6898a8" fontSize={8} fontFamily="monospace">
                {db > 0 ? `+${db}` : db}
              </text>
            </g>
          );
        })}

        {/* Grid: frequency lines */}
        {FREQ_LABELS.map((f) => {
          const x = freqToX(f);
          const label = f >= 1000 ? `${f / 1000}k` : `${f}`;
          return (
            <g key={f}>
              <line
                x1={x} y1={PAD.top} x2={x} y2={H - PAD.bottom}
                stroke="#305972" strokeWidth={0.5} strokeDasharray="3,3"
              />
              <text x={x} y={H - PAD.bottom + 10} textAnchor="middle" fill="#6898a8" fontSize={7.5} fontFamily="monospace">
                {label}
              </text>
            </g>
          );
        })}

        {/* -3dB markers */}
        {fLow3db && fLow3db >= F_MIN && fLow3db <= F_MAX && (
          <line x1={freqToX(fLow3db)} y1={PAD.top} x2={freqToX(fLow3db)} y2={H - PAD.bottom}
            stroke="#1aabbc" strokeWidth={1} strokeDasharray="4,2" opacity={0.7}
          />
        )}
        {fHigh3db && fHigh3db >= F_MIN && fHigh3db <= F_MAX && (
          <line x1={freqToX(fHigh3db)} y1={PAD.top} x2={freqToX(fHigh3db)} y2={H - PAD.bottom}
            stroke="#1aabbc" strokeWidth={1} strokeDasharray="4,2" opacity={0.7}
          />
        )}

        {/* Response curve */}
        {hasData && pathD ? (
          <>
            {/* Glow effect */}
            <path d={pathD} fill="none" stroke="#1aabbc" strokeWidth={3} opacity={0.15} />
            <path d={pathD} fill="none" stroke="#1aabbc" strokeWidth={1.5} opacity={0.9} />
          </>
        ) : (
          <text x={W / 2} y={H / 2} textAnchor="middle" fill="#6898a8" fontSize={10} fontFamily="monospace">
            {hasData ? "no data in range" : "run a design to see frequency response"}
          </text>
        )}

        {/* Axes */}
        <line x1={PAD.left} y1={PAD.top} x2={PAD.left} y2={H - PAD.bottom} stroke="#366678" strokeWidth={1} />
        <line x1={PAD.left} y1={H - PAD.bottom} x2={W - PAD.right} y2={H - PAD.bottom} stroke="#366678" strokeWidth={1} />
      </svg>

      {/* -3dB bandwidth */}
      {(fLow3db || fHigh3db) && (
        <div className="px-3 py-1 border-t border-surface-2 flex gap-4 text-xs font-mono text-text-muted">
          {fLow3db && <span>↓3dB: <span className="text-accent">{fLow3db < 1000 ? `${fLow3db.toFixed(0)}Hz` : `${(fLow3db/1000).toFixed(2)}kHz`}</span></span>}
          {fHigh3db && <span>↑3dB: <span className="text-accent">{fHigh3db < 1000 ? `${fHigh3db.toFixed(0)}Hz` : `${(fHigh3db/1000).toFixed(2)}kHz`}</span></span>}
          {fLow3db && fHigh3db && <span>BW: <span className="text-text">{((fHigh3db - fLow3db)/1000).toFixed(1)}kHz</span></span>}
        </div>
      )}
    </div>
  );
}
