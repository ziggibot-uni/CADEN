// Visual display of the signal transform chain.

const TRANSFORM_LABELS = {
  buffer_input: "Input Buffer",
  buffer_output: "Output Buffer",
  gain_clean: "Clean Gain",
  gain_soft_clip: "Soft Clip",
  gain_hard_clip: "Hard Clip",
  gain_asymmetric: "Asym Clip",
  gain_fuzz: "Fuzz",
  filter_lp: "Low Pass",
  filter_hp: "High Pass",
  filter_bp: "Band Pass",
  filter_notch: "Notch",
  filter_tonestack: "Tone Stack",
  compress: "Compressor",
  modulate_tremolo: "Tremolo",
  modulate_vibrato: "Vibrato",
  modulate_chorus: "Chorus",
};

const TRANSFORM_COLOR = {
  buffer_input: "text-text-muted border-surface-3",
  buffer_output: "text-text-muted border-surface-3",
  gain_clean: "text-blue-300 border-blue-800",
  gain_soft_clip: "text-amber-300 border-amber-800",
  gain_hard_clip: "text-orange-300 border-orange-800",
  gain_asymmetric: "text-orange-300 border-orange-800",
  gain_fuzz: "text-red-300 border-red-800",
  filter_lp: "text-emerald-300 border-emerald-800",
  filter_hp: "text-emerald-300 border-emerald-800",
  filter_bp: "text-emerald-300 border-emerald-800",
  filter_notch: "text-emerald-300 border-emerald-800",
  filter_tonestack: "text-emerald-300 border-emerald-800",
  compress: "text-purple-300 border-purple-800",
  modulate_tremolo: "text-sky-300 border-sky-800",
  modulate_vibrato: "text-sky-300 border-sky-800",
  modulate_chorus: "text-sky-300 border-sky-800",
};

export default function TransformPipeline({ stages }) {
  if (!stages || stages.length === 0) return null;

  return (
    <div className="bg-surface-1 rounded border border-surface-2 px-3 py-2">
      <div className="text-xs font-mono text-text-muted uppercase tracking-wide mb-2">Signal Chain</div>
      <div className="flex items-center gap-1 flex-wrap">
        {stages.map((stage, i) => {
          const label = TRANSFORM_LABELS[stage.transform] || stage.transform;
          const color = TRANSFORM_COLOR[stage.transform] || "text-text-muted border-surface-3";
          const isBuffer = stage.transform.startsWith("buffer");
          return (
            <div key={i} className="flex items-center gap-1">
              <div
                className={`px-2 py-0.5 rounded border text-xs font-mono ${color} ${
                  isBuffer ? "opacity-50" : ""
                }`}
                title={stage.transform}
              >
                {label}
              </div>
              {i < stages.length - 1 && (
                <span className="text-surface-3 text-xs">→</span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
