import { useState, useEffect, useCallback } from "react";
import { invoke } from "@tauri-apps/api/core";

/* ─── Types ──────────────────────────────────────────────────────────────── */

type Section =
  | "overview"
  | "goals"
  | "circadian"
  | "patterns"
  | "transitions"
  | "profile"
  | "factors"
  | "daily"
  | "completions"
  | "skips"
  | "behavioral"
  | "medications"
  | "corrections"
  | "projects"
  | "performance";

interface SectionDef {
  id: Section;
  label: string;
  icon: string;
}

const SECTIONS: SectionDef[] = [
  { id: "overview",      label: "Overview",            icon: "📊" },
  { id: "goals",         label: "Goals",               icon: "🎯" },
  { id: "circadian",     label: "Circadian Energy",    icon: "🌅" },
  { id: "patterns",      label: "Task Patterns",       icon: "📈" },
  { id: "transitions",   label: "Task Transitions",    icon: "🔀" },
  { id: "profile",       label: "Behavioral Profile",  icon: "🧠" },
  { id: "factors",       label: "Factor Snapshots",    icon: "📋" },
  { id: "daily",         label: "Daily States",        icon: "📅" },
  { id: "performance",   label: "Performance Windows", icon: "⚡" },
  { id: "completions",   label: "Completions",         icon: "✅" },
  { id: "skips",         label: "Skips",               icon: "⏭️" },
  { id: "behavioral",    label: "Behavioral Log",      icon: "🔍" },
  { id: "medications",   label: "Medications",         icon: "💊" },
  { id: "corrections",   label: "Corrections",         icon: "✏️" },
  { id: "projects",      label: "Project Time",        icon: "📁" },
];

const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/* ─── Helpers ────────────────────────────────────────────────────────────── */

function formatTs(ts: number | string | null | undefined): string {
  if (ts == null) return "—";
  const d = typeof ts === "number" ? new Date(ts * 1000) : new Date(ts);
  if (isNaN(d.getTime())) return String(ts);
  return d.toLocaleString();
}

function pct(n: number | null | undefined): string {
  if (n == null) return "—";
  return (n * 100).toFixed(1) + "%";
}

function num(n: number | null | undefined, dec = 1): string {
  if (n == null) return "—";
  return n.toFixed(dec);
}

function energyColor(ratio: number): string {
  if (ratio >= 0.8) return "bg-status-success";
  if (ratio >= 0.6) return "bg-status-success/70";
  if (ratio >= 0.4) return "bg-urgency-med/70";
  if (ratio >= 0.2) return "bg-urgency-med/40";
  return "bg-urgency-high/50";
}

function riskColor(risk: string): string {
  switch (risk) {
    case "low": return "text-status-success";
    case "elevated_manic": return "text-urgency-med";
    case "elevated_depressive": return "text-cat-decision";
    case "mixed": return "text-urgency-high";
    case "burnout": return "text-status-star";
    default: return "text-text-dim";
  }
}

function riskLabel(risk: string): string {
  return risk.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
}

/* ─── Section "Card" wrapper ─────────────────────────────────────────────── */

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-surface-1/60 border border-surface-2 rounded-lg p-4">
      <h3 className="text-sm font-semibold text-text-muted uppercase tracking-wider mb-3">
        {title}
      </h3>
      {children}
    </div>
  );
}

function Stat({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="flex flex-col items-center p-3 bg-surface-1/40 rounded-lg border border-surface-2/50">
      <span className="text-2xl font-bold text-text">{value}</span>
      <span className="text-xs text-text-muted mt-1">{label}</span>
      {sub && <span className="text-[10px] text-text-muted/60 mt-0.5">{sub}</span>}
    </div>
  );
}

/* ─── Main Component ─────────────────────────────────────────────────────── */

export default function InsightsPanel() {
  const [section, setSection] = useState<Section>("overview");
  const [loading, setLoading] = useState(false);

  // Data stores — each section fetches its own data on first view
  const [dbCounts, setDbCounts]           = useState<Record<string, number> | null>(null);
  const [rollingAvg, setRollingAvg]       = useState<any>(null);
  const [episodeRisk, setEpisodeRisk]     = useState<any>(null);
  const [focusParams, setFocusParams]     = useState<any>(null);
  const [concerns, setConcerns]           = useState<string[] | null>(null);
  const [profile, setProfile]             = useState<any>(null);
  const [circadian, setCircadian]         = useState<[number, number, number, number][] | null>(null);
  const [patterns, setPatterns]           = useState<[string, string, number, number, number][] | null>(null);
  const [transitions, setTransitions]     = useState<[string, string, number, number, number][] | null>(null);
  const [factors, setFactors]             = useState<any[] | null>(null);
  const [dailyStates, setDailyStates]     = useState<any[] | null>(null);
  const [completions, setCompletions]     = useState<any[] | null>(null);
  const [skips, setSkips]                 = useState<any[] | null>(null);
  const [behavioral, setBehavioral]       = useState<any[] | null>(null);
  const [medications, setMedications]     = useState<any[] | null>(null);
  const [corrections, setCorrections]     = useState<any[] | null>(null);
  const [projectTime, setProjectTime]     = useState<any[] | null>(null);
  const [perfWindows, setPerfWindows]     = useState<any[] | null>(null);
  const [goalsSummary, setGoalsSummary]   = useState<any>(null);

  const load = useCallback(async (s: Section) => {
    setLoading(true);
    try {
      switch (s) {
        case "overview": {
          const [c, r, e, f, cn] = await Promise.all([
            dbCounts     ?? invoke("insights_db_counts"),
            rollingAvg   ?? invoke("insights_rolling_averages"),
            episodeRisk  ?? invoke("insights_episode_risk"),
            focusParams  ?? invoke("insights_focus_params"),
            concerns     ?? invoke("insights_active_concerns"),
          ]);
          if (!dbCounts)    setDbCounts(c as any);
          if (!rollingAvg)  setRollingAvg(r);
          if (!episodeRisk) setEpisodeRisk(e);
          if (!focusParams) setFocusParams(f);
          if (!concerns)    setConcerns(cn as string[]);
          break;
        }
        case "goals":
          if (!goalsSummary) setGoalsSummary(await invoke("insights_goals_summary"));
          break;
        case "circadian":
          if (!circadian) setCircadian(await invoke("insights_circadian_grid") as any);
          break;
        case "patterns":
          if (!patterns) setPatterns(await invoke("insights_patterns") as any);
          break;
        case "transitions":
          if (!transitions) setTransitions(await invoke("insights_transitions") as any);
          break;
        case "profile": {
          const [p, ep] = await Promise.all([
            profile     ?? invoke("insights_profile"),
            episodeRisk ?? invoke("insights_episode_risk"),
          ]);
          if (!profile)     setProfile(p);
          if (!episodeRisk) setEpisodeRisk(ep);
          break;
        }
        case "factors":
          if (!factors) setFactors(await invoke("insights_factor_snapshots") as any[]);
          break;
        case "daily":
          if (!dailyStates) setDailyStates(await invoke("insights_daily_states") as any[]);
          break;
        case "completions":
          if (!completions) setCompletions(await invoke("insights_completions") as any[]);
          break;
        case "skips":
          if (!skips) setSkips(await invoke("insights_skips") as any[]);
          break;
        case "behavioral":
          if (!behavioral) setBehavioral(await invoke("insights_behavioral_log") as any[]);
          break;
        case "medications":
          if (!medications) setMedications(await invoke("insights_medications") as any[]);
          break;
        case "corrections":
          if (!corrections) setCorrections(await invoke("insights_corrections") as any[]);
          break;
        case "projects":
          if (!projectTime) setProjectTime(await invoke("insights_project_time_summary") as any[]);
          break;
        case "performance":
          if (!perfWindows) setPerfWindows(await invoke("insights_performance_windows") as any[]);
          break;
      }
    } catch (e) {
      console.error("Insights load error:", e);
    } finally {
      setLoading(false);
    }
  }, [dbCounts, rollingAvg, episodeRisk, focusParams, concerns, profile, circadian, patterns, transitions, factors, dailyStates, completions, skips, behavioral, medications, corrections, projectTime, perfWindows, goalsSummary]);

  useEffect(() => { load(section); }, [section]);

  const refresh = async () => {
    // Clear all cached data for current section
    switch (section) {
      case "overview":    setDbCounts(null); setRollingAvg(null); setEpisodeRisk(null); setFocusParams(null); setConcerns(null); break;
      case "goals":       setGoalsSummary(null); break;
      case "circadian":   setCircadian(null); break;
      case "patterns":    setPatterns(null); break;
      case "transitions": setTransitions(null); break;
      case "profile":     setProfile(null); setEpisodeRisk(null); break;
      case "factors":     setFactors(null); break;
      case "daily":       setDailyStates(null); break;
      case "completions": setCompletions(null); break;
      case "skips":       setSkips(null); break;
      case "behavioral":  setBehavioral(null); break;
      case "medications": setMedications(null); break;
      case "corrections": setCorrections(null); break;
      case "projects":    setProjectTime(null); break;
      case "performance": setPerfWindows(null); break;
    }
    // load will re-fire via the useEffect since we set null
    setTimeout(() => load(section), 0);
  };

  return (
    <div className="flex h-full text-text">
      {/* Sidebar navigation */}
      <nav className="w-48 shrink-0 border-r border-surface-2 bg-surface-1/30 overflow-y-auto">
        <div className="p-3 text-xs font-bold uppercase tracking-widest text-text-muted border-b border-surface-2">
          Insights
        </div>
        {SECTIONS.map((s) => (
          <button
            key={s.id}
            onClick={() => setSection(s.id)}
            className={`w-full text-left px-3 py-2 text-sm flex items-center gap-2 transition-colors
              ${section === s.id
                ? "bg-accent/15 text-accent border-r-2 border-accent"
                : "text-text-muted hover:bg-surface-1/60 hover:text-text"
              }`}
          >
            <span className="text-base">{s.icon}</span>
            {s.label}
          </button>
        ))}
      </nav>

      {/* Content area */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-lg font-semibold">
            {SECTIONS.find(s => s.id === section)?.icon}{" "}
            {SECTIONS.find(s => s.id === section)?.label}
          </h2>
          <button
            onClick={refresh}
            disabled={loading}
            className="text-xs px-3 py-1 rounded border border-surface-2 text-text-muted hover:bg-surface-1/60 disabled:opacity-40"
          >
            {loading ? "Loading…" : "Refresh"}
          </button>
        </div>

        {section === "overview" && <OverviewSection counts={dbCounts} rolling={rollingAvg} risk={episodeRisk} focus={focusParams} concerns={concerns} />}
        {section === "goals" && <GoalsSection data={goalsSummary} onRefresh={refresh} />}
        {section === "circadian" && <CircadianSection data={circadian} />}
        {section === "patterns" && <PatternsSection data={patterns} />}
        {section === "transitions" && <TransitionsSection data={transitions} />}
        {section === "profile" && <ProfileSection profile={profile} risk={episodeRisk} />}
        {section === "factors" && <FactorsSection data={factors} onRefresh={refresh} />}
        {section === "daily" && <DailySection data={dailyStates} />}
        {section === "completions" && <CompletionsSection data={completions} />}
        {section === "skips" && <SkipsSection data={skips} />}
        {section === "behavioral" && <BehavioralSection data={behavioral} />}
        {section === "medications" && <MedicationsSection data={medications} onRefresh={refresh} />}
        {section === "corrections" && <CorrectionsSection data={corrections} />}
        {section === "projects" && <ProjectsSection data={projectTime} />}
        {section === "performance" && <PerformanceSection data={perfWindows} />}
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   Individual Section Components
   ═══════════════════════════════════════════════════════════════════════════ */

/* ── Overview ─────────────────────────────────────────────────── */

function OverviewSection({ counts, rolling, risk, focus, concerns }: {
  counts: Record<string, number> | null;
  rolling: any;
  risk: any;
  focus: any;
  concerns: string[] | null;
}) {
  if (!counts) return <Loading />;
  return (
    <div className="space-y-4">
      {/* Risk + Rolling averages */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {risk && (
          <Stat
            label="Episode Risk"
            value={riskLabel(risk.risk)}
            sub={`${pct(risk.confidence)} confidence`}
          />
        )}
        {rolling && <>
          <Stat label="Energy (7d avg)" value={num(rolling.energy_7d)} />
          <Stat label="Mood (7d avg)" value={num(rolling.mood_7d)} />
          <Stat label="Anxiety (7d avg)" value={num(rolling.anxiety_7d)} />
        </>}
      </div>

      {/* Focus params */}
      {focus && (
        <Card title="Learned Focus Parameters">
          <div className="flex gap-6 text-sm">
            <span>Focus block: <strong>{focus.focus_block_minutes} min</strong></span>
            <span>Break: <strong>{focus.break_minutes} min</strong></span>
          </div>
          <p className="text-xs text-text-muted mt-1">
            Computed via exponentially-weighted moving average of your actual focus/break durations.
          </p>
        </Card>
      )}

      {/* Active concerns */}
      {concerns && concerns.length > 0 && (
        <Card title="Active Concerns (Semantic Retrieval)">
          <ul className="list-disc list-inside text-sm space-y-1">
            {concerns.map((c, i) => <li key={i}>{c}</li>)}
          </ul>
        </Card>
      )}

      {/* Database row counts */}
      <Card title="Database Table Sizes">
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2 text-sm">
          {Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([table, count]) => (
            <div key={table} className="flex justify-between px-2 py-1 rounded bg-surface-1/40 border border-surface-2/30">
              <span className="text-text-muted">{table.replace(/_/g, " ")}</span>
              <span className="font-mono font-semibold">{count.toLocaleString()}</span>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

/* ── Goals ─────────────────────────────────────────────────────── */

function GoalsSection({ data, onRefresh }: { data: any; onRefresh: () => void }) {
  const [editingProgress, setEditingProgress] = useState<string | null>(null);
  const [progressVal, setProgressVal] = useState("");
  const [savingProgress, setSavingProgress] = useState(false);

  if (!data) return <Loading />;
  const goals: any[] = data.goals ?? [];
  if (goals.length === 0) return <Empty msg="No active goals yet. Add goals through the chat — tell CADEN what you're working toward." />;

  const CATEGORY_COLORS: Record<string, string> = {
    academic:  "bg-cat-decision/15 text-cat-decision border-cat-decision/30",
    creative:  "bg-cat-idea/15 text-cat-idea border-cat-idea/30",
    health:    "bg-status-success/15 text-status-success border-status-success/30",
    personal:  "bg-status-star/15 text-status-star border-status-star/30",
  };

  const saveProgress = async (goalId: string) => {
    const v = parseFloat(progressVal);
    if (isNaN(v)) return;
    setSavingProgress(true);
    try {
      await invoke("update_goal", {
        id: goalId, title: null, description: null, category: null, priority: null,
        status: null, targetValue: null, targetUnit: null, currentValue: v,
        weeklyHoursTarget: null, deadline: null, linkedProjectId: null, linkedTaskTypes: null,
      });
      setEditingProgress(null);
      onRefresh();
    } finally {
      setSavingProgress(false);
    }
  };

  return (
    <div className="space-y-4">
      <Card title="How Goals Influence Scheduling">
        <p className="text-xs text-text-muted">
          CADEN uses your goals to prioritize tasks during daily planning. Here's how:
          <br /><br />
          <strong>1. Urgency boost:</strong> Tasks linked to a goal get up to <code className="text-accent">+15 points</code> added
          to their urgency score (based on goal priority 1–5).
          <br />
          <strong>2. Effort weight activation:</strong> The planner's <code className="text-accent">effort_weight</code> parameter
          (normally a dead 3.0) gets boosted to 3.0–5.0 for goal-aligned tasks, making them occupy
          more of the scheduling formula: <code className="text-accent">0.5×deadline + 0.3×effort + 0.2×pattern</code>.
          <br />
          <strong>3. BTS progress tracking:</strong> Every message you send is silently analyzed for goal-relevant
          progress (same pattern as factor extraction). Task completions on linked projects automatically log progress.
          <br />
          <strong>4. Briefing injection:</strong> Active goals are included in the situational briefing so the LLM
          knows what you're working toward and can reference them in conversations.
        </p>
      </Card>

      {goals.map((g: any) => {
        const catClass = CATEGORY_COLORS[g.category] ?? CATEGORY_COLORS.personal;
        const pctVal = g.completion_pct != null ? g.completion_pct.toFixed(0) : null;
        const barWidth = pctVal != null ? Math.min(parseFloat(pctVal), 100) : 0;
        const hoursOnTrack = g.weekly_hours_target > 0
          ? g.weekly_hours_actual >= g.weekly_hours_target
          : null;

        return (
          <Card key={g.id} title={g.title}>
            <div className="space-y-3">
              {/* Header badges */}
              <div className="flex flex-wrap gap-2 items-center">
                <span className={`px-2 py-0.5 rounded text-xs border ${catClass}`}>
                  {g.category}
                </span>
                <span className="text-xs text-text-muted">
                  Priority: <strong>{"★".repeat(g.priority)}{"☆".repeat(5 - g.priority)}</strong>
                </span>
                {g.deadline && (
                  <span className="text-xs text-text-muted">
                    Due: {g.deadline}
                  </span>
                )}
              </div>

              {/* Progress bar (if target-based) */}
              {pctVal != null && (
                <div className="space-y-1">
                  <div className="flex justify-between items-center text-xs gap-2">
                    {editingProgress === g.id ? (
                      <div className="flex items-center gap-1">
                        <input type="number" value={progressVal} onChange={e => setProgressVal(e.target.value)}
                          className="w-20 bg-surface-2 rounded px-1 py-0.5 border border-surface-2 focus:border-accent outline-none text-xs"
                          placeholder={String(g.current_value ?? 0)} />
                        <span className="text-text-muted">/ {num(g.target_value)} {g.target_unit}</span>
                        <button onClick={() => saveProgress(g.id)} disabled={savingProgress}
                          className="px-2 py-0.5 rounded bg-accent/20 text-accent text-[10px] hover:bg-accent/30 disabled:opacity-40">
                          {savingProgress ? "…" : "✓"}
                        </button>
                        <button onClick={() => setEditingProgress(null)}
                          className="px-1.5 py-0.5 rounded bg-surface-2 text-text-muted text-[10px]">✕</button>
                      </div>
                    ) : (
                      <span
                        className="cursor-pointer hover:text-accent transition-colors"
                        onClick={() => { setEditingProgress(g.id); setProgressVal(String(g.current_value ?? 0)); }}
                        title="Click to edit current value">
                        {num(g.current_value)} / {num(g.target_value)} {g.target_unit} ✏
                      </span>
                    )}
                    <span className="font-mono">{pctVal}%</span>
                  </div>
                  <div className="h-2.5 bg-surface-1/40 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-accent/70 rounded-full transition-all"
                      style={{ width: `${barWidth}%` }}
                    />
                  </div>
                </div>
              )}

              {/* Weekly hours */}
              {g.weekly_hours_target > 0 && (
                <div className="flex items-center gap-2 text-xs">
                  <span className={hoursOnTrack ? "text-status-success" : "text-urgency-med"}>
                    {hoursOnTrack ? "✓" : "⚠"}
                  </span>
                  <span>
                    {num(g.weekly_hours_actual)}h / {num(g.weekly_hours_target)}h this week
                  </span>
                </div>
              )}

              {/* Weekly progress delta */}
              {g.weekly_progress !== 0 && (
                <div className="text-xs text-text-muted">
                  Progress this week: <strong className={g.weekly_progress > 0 ? "text-status-success" : "text-urgency-high"}>
                    {g.weekly_progress > 0 ? "+" : ""}{num(g.weekly_progress)}
                  </strong> {g.target_unit ?? "units"}
                </div>
              )}

              {/* Scheduling impact */}
              <div className="text-[10px] text-text-muted/60 border-t border-surface-2/20 pt-2">
                Scheduling: urgency +{g.priority * 3}pts | effort_weight = {num(3.0 + (g.priority - 1) * 0.5)}
              </div>
            </div>
          </Card>
        );
      })}
    </div>
  );
}

/* ── Circadian Energy Grid ────────────────────────────────────── */

function CircadianSection({ data }: { data: [number, number, number, number][] | null }) {
  if (!data) return <Loading />;
  if (data.length === 0) return <Empty msg="No circadian data yet. CADEN builds this as you complete tasks." />;

  // Build a 24×7 matrix: ratio = completions/samples
  const grid: (number | null)[][] = Array.from({ length: 7 }, () => Array(24).fill(null));
  let maxRatio = 0;
  for (const [hour, dow, completions, samples] of data) {
    const ratio = samples > 0 ? completions / samples : 0;
    grid[dow][hour] = ratio;
    if (ratio > maxRatio) maxRatio = ratio;
  }

  return (
    <div className="space-y-4">
      <Card title="How CADEN Computes This">
        <p className="text-xs text-text-muted">
          Every time you complete or skip a task, CADEN records the hour (0–23) and day of week (0–6).
          The circadian model stores <code className="text-accent">completions</code> and <code className="text-accent">samples</code> per cell.
          The ratio (completions÷samples) reveals when you're most productive. Brighter = higher completion rate.
        </p>
      </Card>

      <Card title="Energy Grid (completion rate by hour × day)">
        <div className="overflow-x-auto">
          <table className="text-xs border-collapse">
            <thead>
              <tr>
                <th className="pr-2 text-right text-text-muted">Hour</th>
                {DOW.map(d => <th key={d} className="px-1 text-center text-text-muted w-10">{d}</th>)}
              </tr>
            </thead>
            <tbody>
              {Array.from({ length: 24 }, (_, h) => (
                <tr key={h}>
                  <td className="pr-2 text-right text-text-muted font-mono">{h === 0 ? "12 AM" : h < 12 ? `${h} AM` : h === 12 ? "12 PM" : `${h - 12} PM`}</td>
                  {DOW.map((_, dow) => {
                    const val = grid[dow]?.[h];
                    const normalized = val != null && maxRatio > 0 ? val / maxRatio : 0;
                    return (
                      <td key={dow} className="p-0.5">
                        <div
                          className={`w-10 h-5 rounded-sm flex items-center justify-center text-[10px] font-mono
                            ${val == null ? "bg-surface-1/30" : energyColor(normalized)}`}
                          title={val != null ? `${(val * 100).toFixed(0)}% completion` : "no data"}
                        >
                          {val != null ? `${(val * 100).toFixed(0)}%` : ""}
                        </div>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

/* ── Task Patterns ────────────────────────────────────────────── */

function PatternsSection({ data }: { data: [string, string, number, number, number][] | null }) {
  if (!data) return <Loading />;
  if (data.length === 0) return <Empty msg="No pattern data yet." />;

  return (
    <div className="space-y-4">
      <Card title="How Patterns Are Computed">
        <p className="text-xs text-text-muted">
          CADEN groups your completions and skips by <code className="text-accent">task_type</code> × <code className="text-accent">time_of_day</code> (morning/afternoon/evening/night).
          <br />
          <strong>Completion rate</strong> = completions ÷ (completions + skips).
          <strong> Avg delay</strong> = mean minutes between scheduled time and actual completion.
          <br />
          The planner uses these to apply a <em>pattern penalty</em> when scheduling: <code className="text-accent">penalty = 1 − completion_rate</code>.
          High-penalty slots are avoided.
        </p>
      </Card>

      <Card title="Pattern Data">
        <DataTable
          headers={["Task Type", "Time of Day", "Completion Rate", "Avg Delay (min)", "Samples"]}
          rows={data.map(([type_, tod, rate, delay, samples]) => [
            type_, tod, pct(rate), num(delay, 0), String(samples),
          ])}
        />
      </Card>
    </div>
  );
}

/* ── Task Transitions (Markov) ────────────────────────────────── */

function TransitionsSection({ data }: { data: [string, string, number, number, number][] | null }) {
  if (!data) return <Loading />;
  if (data.length === 0) return <Empty msg="No transition data yet." />;

  return (
    <div className="space-y-4">
      <Card title="How Transitions Work">
        <p className="text-xs text-text-muted">
          CADEN tracks which task types you do <em>after</em> which other task types.
          This builds a Markov-style transition model.
          When scheduling, the planner multiplies a <code className="text-accent">transition_fitness</code> score into slot assignment:
          <br />
          <code className="text-accent">score = urgency × pk_multiplier × transition_fitness</code>
          <br />
          Higher completion rates for a from→to pair means CADEN is more likely to schedule that sequence.
        </p>
      </Card>

      <Card title="Transition Matrix">
        <DataTable
          headers={["From Type", "To Type", "Completion Rate", "Avg Delay (min)", "Samples"]}
          rows={data.map(([from, to, rate, delay, samples]) => [
            from, to, pct(rate), num(delay, 0), String(samples),
          ])}
        />
      </Card>
    </div>
  );
}

/* ── Behavioral Profile ──────────────────────────────────────── */

function ProfileSection({ profile, risk }: { profile: any; risk: any }) {
  if (!profile) return <Loading />;

  return (
    <div className="space-y-4">
      <Card title="How The Profile Is Built">
        <p className="text-xs text-text-muted">
          CADEN's "Sean Model" analyzes your completions, skips, timing patterns, and chat content to build a behavioral profile.
          <br />
          • <strong>Task preferences</strong>: creative vs academic completion rate difference
          <br />
          • <strong>Chronic avoidances</strong>: tasks skipped 3+ consecutive times without any completion
          <br />
          • <strong>Momentum</strong>: are completions trending up or down? (compared to previous week)
          <br />
          • <strong>Flow windows</strong>: detected periods of back-to-back completions within short intervals
          <br />
          • <strong>Spikes</strong>: notable pattern signals that fire based on current data
        </p>
      </Card>

      {risk && (
        <Card title="Episode Risk Assessment">
          <div className="flex items-center gap-4">
            <span className={`text-xl font-bold ${riskColor(risk.risk)}`}>
              {riskLabel(risk.risk)}
            </span>
            <span className="text-sm text-text-muted">
              Confidence: {pct(risk.confidence)}
            </span>
          </div>
          {risk.detail && (
            <p className="text-xs text-text-muted mt-2">{risk.detail}</p>
          )}
          <p className="text-[10px] text-text-muted/60 mt-2">
            Computed from factor snapshots (mood, energy, anxiety), sleep, output volume, and thought coherence patterns.
            Categories: Low, Elevated Manic, Elevated Depressive, Mixed, Burnout.
          </p>
        </Card>
      )}

      {profile.task_preference_note && (
        <Card title="Task Preferences">
          <p className="text-sm">{profile.task_preference_note}</p>
        </Card>
      )}

      {profile.chronic_avoidances?.length > 0 && (
        <Card title="Chronic Avoidances">
          <div className="flex flex-wrap gap-2">
            {profile.chronic_avoidances.map((a: string, i: number) => (
              <span key={i} className="px-2 py-0.5 rounded text-xs bg-urgency-high/15 text-urgency-high border border-urgency-high/30">
                {a}
              </span>
            ))}
          </div>
        </Card>
      )}

      {profile.momentum_note && (
        <Card title="Momentum">
          <p className="text-sm">{profile.momentum_note}</p>
        </Card>
      )}

      {profile.flow_windows?.length > 0 && (
        <Card title="Detected Flow Windows">
          <div className="flex flex-wrap gap-2">
            {profile.flow_windows.map((w: string, i: number) => (
              <span key={i} className="px-2 py-0.5 rounded text-xs bg-status-success/15 text-status-success border border-status-success/30">
                {w}
              </span>
            ))}
          </div>
        </Card>
      )}

      {profile.spikes?.length > 0 && (
        <Card title="Active Spikes">
          <div className="flex flex-wrap gap-2">
            {profile.spikes.map((s: string, i: number) => (
              <span key={i} className="px-2 py-0.5 rounded text-xs bg-status-star/15 text-status-star border border-status-star/30">
                {s}
              </span>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}

/* ── Factor Snapshots ─────────────────────────────────────────── */

function FactorsSection({ data, onRefresh }: { data: any[] | null; onRefresh: () => void }) {
  const [editId, setEditId] = useState<string | null>(null);
  const [editMood, setEditMood] = useState("");
  const [editEnergy, setEditEnergy] = useState("");
  const [editAnxiety, setEditAnxiety] = useState("");
  const [editNotes, setEditNotes] = useState("");
  const [saving, setSaving] = useState(false);

  if (!data) return <Loading />;
  if (data.length === 0) return <Empty msg="No factor snapshots yet." />;

  const startEdit = (r: any) => {
    setEditId(r.id);
    setEditMood(r.mood != null ? (r.mood * 10).toFixed(1) : "");
    setEditEnergy(r.energy != null ? (r.energy * 10).toFixed(1) : "");
    setEditAnxiety(r.anxiety != null ? (r.anxiety * 10).toFixed(1) : "");
    setEditNotes(r.notes ?? "");
  };

  const saveEdit = async () => {
    if (!editId) return;
    setSaving(true);
    try {
      const toFloat = (s: string) => s.trim() === "" ? null : parseFloat(s) / 10;
      await invoke("insights_update_factor_snapshot", {
        id: editId,
        mood: toFloat(editMood),
        energy: toFloat(editEnergy),
        anxiety: toFloat(editAnxiety),
        notes: editNotes.trim() || null,
      });
      setEditId(null);
      onRefresh();
    } finally {
      setSaving(false);
    }
  };

  const deleteRow = async (id: string) => {
    if (!confirm("Delete this factor snapshot?")) return;
    await invoke("insights_delete_factor_snapshot", { id });
    onRefresh();
  };

  return (
    <div className="space-y-4">
      <Card title="How Factors Are Extracted">
        <p className="text-xs text-text-muted">
          Every time you chat with CADEN, the state engine runs an LLM pass to extract your current factors:
          mood (0–10), energy (0–10), anxiety (0–10), thought coherence, temporal focus, valence, and implied sleep hours.
          Low-confidence extractions (&lt;0.3) are dropped. Click any row to correct a bad reading.
        </p>
      </Card>

      <Card title={`Recent Snapshots (${data.length})`}>
        <div className="overflow-x-auto max-h-[32rem] overflow-y-auto">
          <table className="w-full text-xs border-collapse">
            <thead>
              <tr>
                {["Time", "Mood", "Energy", "Anxiety", "Coherence", "Focus", "Sleep (h)", "Conf.", "Notes", ""].map((h, i) => (
                  <th key={i} className="text-left px-2 py-1 text-text-muted border-b border-surface-2/30 font-medium whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.map((r: any) => editId === r.id ? (
                <tr key={r.id} className="bg-surface-1/60">
                  <td className="px-2 py-1 text-text-dim text-[10px]">{formatTs(r.timestamp)}</td>
                  <td className="px-1 py-1">
                    <input type="number" step="0.1" min="0" max="10" value={editMood}
                      onChange={e => setEditMood(e.target.value)}
                      className="w-14 bg-surface-2 rounded px-1 py-0.5 text-xs text-text border border-surface-2 focus:border-accent outline-none" />
                  </td>
                  <td className="px-1 py-1">
                    <input type="number" step="0.1" min="0" max="10" value={editEnergy}
                      onChange={e => setEditEnergy(e.target.value)}
                      className="w-14 bg-surface-2 rounded px-1 py-0.5 text-xs text-text border border-surface-2 focus:border-accent outline-none" />
                  </td>
                  <td className="px-1 py-1">
                    <input type="number" step="0.1" min="0" max="10" value={editAnxiety}
                      onChange={e => setEditAnxiety(e.target.value)}
                      className="w-14 bg-surface-2 rounded px-1 py-0.5 text-xs text-text border border-surface-2 focus:border-accent outline-none" />
                  </td>
                  <td className="px-2 py-1 text-text-dim">{r.coherence ?? "—"}</td>
                  <td className="px-2 py-1 text-text-dim">{r.temporal_focus ?? "—"}</td>
                  <td className="px-2 py-1 text-text-dim">{num(r.sleep_hours)}</td>
                  <td className="px-2 py-1 text-text-dim">{num(r.confidence)}</td>
                  <td className="px-1 py-1">
                    <input type="text" value={editNotes}
                      onChange={e => setEditNotes(e.target.value)}
                      className="w-32 bg-surface-2 rounded px-1 py-0.5 text-xs text-text border border-surface-2 focus:border-accent outline-none" />
                  </td>
                  <td className="px-1 py-1 flex gap-1">
                    <button onClick={saveEdit} disabled={saving}
                      className="px-2 py-0.5 rounded bg-accent/20 text-accent text-[10px] hover:bg-accent/30 disabled:opacity-40">
                      {saving ? "…" : "Save"}
                    </button>
                    <button onClick={() => setEditId(null)}
                      className="px-2 py-0.5 rounded bg-surface-2 text-text-muted text-[10px] hover:bg-surface-3">
                      ✕
                    </button>
                  </td>
                </tr>
              ) : (
                <tr key={r.id} className="hover:bg-surface-1/30 group cursor-pointer" onClick={() => startEdit(r)}>
                  <td className="px-2 py-1 border-b border-surface-2/10 whitespace-nowrap">{formatTs(r.timestamp)}</td>
                  <td className="px-2 py-1 border-b border-surface-2/10">{r.mood != null ? (r.mood * 10).toFixed(1) : "—"}</td>
                  <td className="px-2 py-1 border-b border-surface-2/10">{r.energy != null ? (r.energy * 10).toFixed(1) : "—"}</td>
                  <td className="px-2 py-1 border-b border-surface-2/10">{r.anxiety != null ? (r.anxiety * 10).toFixed(1) : "—"}</td>
                  <td className="px-2 py-1 border-b border-surface-2/10">{r.coherence ?? "—"}</td>
                  <td className="px-2 py-1 border-b border-surface-2/10">{r.temporal_focus ?? "—"}</td>
                  <td className="px-2 py-1 border-b border-surface-2/10">{num(r.sleep_hours)}</td>
                  <td className="px-2 py-1 border-b border-surface-2/10">{num(r.confidence)}</td>
                  <td className="px-2 py-1 border-b border-surface-2/10 max-w-[12rem] truncate">{r.notes?.substring(0, 60) ?? "—"}</td>
                  <td className="px-1 py-1 border-b border-surface-2/10 opacity-0 group-hover:opacity-100">
                    <button
                      onClick={e => { e.stopPropagation(); deleteRow(r.id); }}
                      className="px-1.5 py-0.5 rounded bg-urgency-high/15 text-urgency-high text-[10px] hover:bg-urgency-high/30">
                      del
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-[10px] text-text-dim mt-2 px-2">Click any row to edit. Values are on a 0–10 scale.</p>
        </div>
      </Card>
    </div>
  );
}

/* ── Daily States ─────────────────────────────────────────────── */

function DailySection({ data }: { data: any[] | null }) {
  if (!data) return <Loading />;
  if (data.length === 0) return <Empty msg="No daily state data yet." />;

  return (
    <div className="space-y-4">
      <Card title="How Daily State Is Aggregated">
        <p className="text-xs text-text-muted">
          At end-of-day (or next morning), CADEN aggregates all factor snapshots into a daily summary.
          It records: average mood, energy, anxiety, session count, output volume, thought pattern, and episode risk level.
          This history is used for the rolling averages shown on the Overview page and for trend analysis.
        </p>
      </Card>

      <Card title={`Daily History (${data.length} days)`}>
        <div className="overflow-x-auto max-h-96 overflow-y-auto">
          <DataTable
            headers={["Date", "Wake", "Sleep (h)", "Energy", "Mood", "Anxiety", "Pattern", "Output", "Sessions", "Risk", "Conf."]}
            rows={data.map((r: any) => [
              r.date, r.wake_time ?? "—", num(r.sleep_hours), num(r.avg_energy),
              num(r.avg_mood), num(r.avg_anxiety), r.thought_pattern ?? "—",
              String(r.output_volume), String(r.session_count), r.episode_risk ?? "—",
              num(r.risk_confidence),
            ])}
          />
        </div>
      </Card>
    </div>
  );
}

/* ── Performance Windows ──────────────────────────────────────── */

function PerformanceSection({ data }: { data: any[] | null }) {
  if (!data) return <Loading />;
  if (data.length === 0) return <Empty msg="No performance windows today — log medications for CADEN to compute PK-based windows." />;

  return (
    <div className="space-y-4">
      <Card title="How Performance Windows Are Computed">
        <p className="text-xs text-text-muted">
          CADEN uses pharmacokinetic (PK) models for your logged medications to predict peak and trough concentration windows.
          Stimulants (Vyvanse/lisdexamfetamine) have T-max ~3–4h, duration ~10–12h.
          Depressants (quetiapine) cause a post-wake trough.
          The planner multiplies a <code className="text-accent">pk_multiplier</code> into task scheduling: peak windows get higher priority for demanding tasks.
        </p>
      </Card>

      <Card title="Today's Windows">
        <div className="space-y-2">
          {data.map((w: any, i: number) => (
            <div key={i} className={`flex items-center gap-3 px-3 py-2 rounded border ${
              w.kind === "peak" ? "bg-status-success/10 border-status-success/30" : "bg-urgency-med/10 border-urgency-med/30"
            }`}>
              <span className={`text-sm font-bold ${w.kind === "peak" ? "text-status-success" : "text-urgency-med"}`}>
                {w.kind.toUpperCase()}
              </span>
              <span className="text-sm font-mono">
                {String(w.start_hour).padStart(2, "0")}:00 – {String(w.end_hour).padStart(2, "0")}:00
              </span>
              <span className="text-xs text-text-muted">({w.medication})</span>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

/* ── Completions ──────────────────────────────────────────────── */

function CompletionsSection({ data }: { data: any[] | null }) {
  if (!data) return <Loading />;
  if (data.length === 0) return <Empty msg="No completions recorded yet." />;

  return (
    <div className="space-y-4">
      <Card title="How Completions Feed The Model">
        <p className="text-xs text-text-muted">
          Each completion updates: the circadian model (hour × day_of_week cell), the pattern table (task_type × time_of_day),
          the transition model (if preceded by another task), and the behavioral log. The delay between planned and actual time
          feeds into the pattern's avg_delay_minutes, which the planner uses to adjust scheduling.
          <br />
          Urgency formula: <code className="text-accent">0.5 × deadline_factor + 0.3 × effort_factor + 0.2 × pattern_penalty</code>
        </p>
      </Card>

      <Card title={`Recent Completions (${data.length})`}>
        <div className="overflow-x-auto max-h-96 overflow-y-auto">
          <DataTable
            headers={["Plan Date", "Source", "Planned", "Completed", "Task ID"]}
            rows={data.map((r: any) => [
              r.plan_date, r.source, r.planned_time ?? "—", formatTs(r.actual_time), r.task_id.substring(0, 12) + "…",
            ])}
          />
        </div>
      </Card>
    </div>
  );
}

/* ── Skips ─────────────────────────────────────────────────────── */

function SkipsSection({ data }: { data: any[] | null }) {
  if (!data) return <Loading />;
  if (data.length === 0) return <Empty msg="No skips recorded yet." />;

  return (
    <div className="space-y-4">
      <Card title="How Skips Affect The Model">
        <p className="text-xs text-text-muted">
          Skips lower the completion rate in the pattern table for that task_type × time_of_day slot.
          3+ consecutive skips of the same task trigger a "chronic avoidance" flag in your behavioral profile.
          The planner penalizes scheduling tasks in time slots where skip rates are high.
        </p>
      </Card>

      <Card title={`Recent Skips (${data.length})`}>
        <div className="overflow-x-auto max-h-96 overflow-y-auto">
          <DataTable
            headers={["Time", "Source", "Reason", "Task ID"]}
            rows={data.map((r: any) => [
              formatTs(r.timestamp), r.source, r.reason ?? "—", r.task_id.substring(0, 12) + "…",
            ])}
          />
        </div>
      </Card>
    </div>
  );
}

/* ── Behavioral Log ───────────────────────────────────────────── */

function BehavioralSection({ data }: { data: any[] | null }) {
  if (!data) return <Loading />;
  if (data.length === 0) return <Empty msg="No behavioral events logged yet." />;

  return (
    <div className="space-y-4">
      <Card title="What Gets Logged">
        <p className="text-xs text-text-muted">
          The behavioral log records raw events: task starts, completions, skips, focus sessions, and breaks.
          Each entry captures the event type, task type, hour, day of week, and duration.
          This data feeds the circadian model, pattern computations, and flow window detection.
        </p>
      </Card>

      <Card title={`Recent Events (${data.length})`}>
        <div className="overflow-x-auto max-h-96 overflow-y-auto">
          <DataTable
            headers={["Time", "Event", "Task Type", "Hour", "Day", "Duration (min)"]}
            rows={data.map((r: any) => [
              formatTs(r.timestamp), r.event_type, r.task_type ?? "—",
              String(r.hour), DOW[r.day_of_week] ?? String(r.day_of_week),
              num(r.duration_minutes),
            ])}
          />
        </div>
      </Card>
    </div>
  );
}

/* ── Medications ──────────────────────────────────────────────── */

function MedicationsSection({ data, onRefresh }: { data: any[] | null; onRefresh: () => void }) {
  const [editId, setEditId] = useState<string | null>(null);
  const [editName, setEditName] = useState("");
  const [editDoseTime, setEditDoseTime] = useState(""); // YYYY-MM-DDTHH:MM (local)
  const [editDoseMg, setEditDoseMg] = useState("");
  const [editNotes, setEditNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [adding, setAdding] = useState(false);
  const [addName, setAddName] = useState("");
  const [addDoseTime, setAddDoseTime] = useState("");
  const [addDoseMg, setAddDoseMg] = useState("");
  const [addNotes, setAddNotes] = useState("");
  const [addSaving, setAddSaving] = useState(false);

  if (!data) return <Loading />;

  // Convert unix ts → datetime-local string (YYYY-MM-DDTHH:MM)
  const tsToLocal = (ts: number): string => {
    const d = new Date(ts * 1000);
    const pad = (n: number) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  };

  const localToTs = (s: string): number => Math.floor(new Date(s).getTime() / 1000);

  const startEdit = (r: any) => {
    setEditId(r.id);
    setEditName(r.medication ?? "");
    setEditDoseTime(r.dose_time != null ? tsToLocal(r.dose_time) : "");
    setEditDoseMg(r.dose_mg != null ? String(r.dose_mg) : "");
    setEditNotes(r.notes ?? "");
  };

  const saveEdit = async () => {
    if (!editId || !editName.trim() || !editDoseTime) return;
    setSaving(true);
    try {
      await invoke("insights_update_medication", {
        id: editId,
        medication: editName.trim(),
        doseTime: localToTs(editDoseTime),
        doseMg: editDoseMg.trim() ? parseFloat(editDoseMg) : null,
        notes: editNotes.trim() || null,
      });
      setEditId(null);
      onRefresh();
    } finally {
      setSaving(false);
    }
  };

  const deleteRow = async (id: string, name: string) => {
    if (!confirm(`Delete ${name} entry?`)) return;
    await invoke("insights_delete_medication", { id });
    onRefresh();
  };

  const saveNew = async () => {
    if (!addName.trim() || !addDoseTime) return;
    setAddSaving(true);
    try {
      await invoke("insights_add_medication", {
        medication: addName.trim(),
        doseTime: localToTs(addDoseTime),
        doseMg: addDoseMg.trim() ? parseFloat(addDoseMg) : null,
        notes: addNotes.trim() || null,
      });
      setAdding(false);
      setAddName(""); setAddDoseTime(""); setAddDoseMg(""); setAddNotes("");
      onRefresh();
    } finally {
      setAddSaving(false);
    }
  };

  return (
    <div className="space-y-4">
      <Card title="How Medications Affect Scheduling">
        <p className="text-xs text-text-muted">
          CADEN uses pharmacokinetic models to estimate concentration curves from your medication logs.
          Stimulants create "peak" performance windows (T-max ~3–4h after dose).
          Sedatives create "low" windows (post-dose trough). The planner uses a
          <code className="text-accent"> pk_multiplier</code> to boost demanding task scheduling into peak windows
          and schedule easier tasks during troughs.
        </p>
      </Card>

      <Card title={`Medication Log (${data.length})`}>
        <div className="flex justify-end mb-2">
          <button
            onClick={() => setAdding(a => !a)}
            className="text-xs px-3 py-1 rounded border border-accent/40 text-accent hover:bg-accent/10">
            {adding ? "Cancel" : "+ Add entry"}
          </button>
        </div>

        {adding && (
          <div className="mb-3 p-3 rounded bg-surface-1/60 border border-surface-2 space-y-2">
            <div className="flex gap-2 flex-wrap">
              <div className="flex flex-col gap-0.5">
                <label className="text-[10px] text-text-muted">Medication*</label>
                <input value={addName} onChange={e => setAddName(e.target.value)} placeholder="e.g. Vyvanse"
                  className="w-32 bg-surface-2 rounded px-2 py-1 text-xs border border-surface-2 focus:border-accent outline-none" />
              </div>
              <div className="flex flex-col gap-0.5">
                <label className="text-[10px] text-text-muted">Dose time*</label>
                <input type="datetime-local" value={addDoseTime} onChange={e => setAddDoseTime(e.target.value)}
                  className="bg-surface-2 rounded px-2 py-1 text-xs border border-surface-2 focus:border-accent outline-none" />
              </div>
              <div className="flex flex-col gap-0.5">
                <label className="text-[10px] text-text-muted">Dose (mg)</label>
                <input type="number" value={addDoseMg} onChange={e => setAddDoseMg(e.target.value)} placeholder="—"
                  className="w-20 bg-surface-2 rounded px-2 py-1 text-xs border border-surface-2 focus:border-accent outline-none" />
              </div>
              <div className="flex flex-col gap-0.5">
                <label className="text-[10px] text-text-muted">Notes</label>
                <input value={addNotes} onChange={e => setAddNotes(e.target.value)} placeholder="optional"
                  className="w-36 bg-surface-2 rounded px-2 py-1 text-xs border border-surface-2 focus:border-accent outline-none" />
              </div>
            </div>
            <button onClick={saveNew} disabled={addSaving || !addName.trim() || !addDoseTime}
              className="text-xs px-3 py-1 rounded bg-accent/20 text-accent border border-accent/30 hover:bg-accent/30 disabled:opacity-40">
              {addSaving ? "Saving…" : "Save"}
            </button>
          </div>
        )}

        {data.length === 0 ? (
          <Empty msg="No medication entries logged yet." />
        ) : (
          <div className="overflow-x-auto max-h-96 overflow-y-auto">
            <table className="w-full text-xs border-collapse">
              <thead>
                <tr>
                  {["Logged", "Medication", "Dose Time", "Dose (mg)", "Notes", ""].map((h, i) => (
                    <th key={i} className="text-left px-2 py-1 text-text-muted border-b border-surface-2/30 font-medium whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.map((r: any) => editId === r.id ? (
                  <tr key={r.id} className="bg-surface-1/60">
                    <td className="px-2 py-1 text-text-dim text-[10px]">{formatTs(r.logged_at)}</td>
                    <td className="px-1 py-1">
                      <input value={editName} onChange={e => setEditName(e.target.value)}
                        className="w-28 bg-surface-2 rounded px-1 py-0.5 text-xs border border-surface-2 focus:border-accent outline-none" />
                    </td>
                    <td className="px-1 py-1">
                      <input type="datetime-local" value={editDoseTime} onChange={e => setEditDoseTime(e.target.value)}
                        className="bg-surface-2 rounded px-1 py-0.5 text-xs border border-surface-2 focus:border-accent outline-none" />
                    </td>
                    <td className="px-1 py-1">
                      <input type="number" value={editDoseMg} onChange={e => setEditDoseMg(e.target.value)}
                        className="w-16 bg-surface-2 rounded px-1 py-0.5 text-xs border border-surface-2 focus:border-accent outline-none" />
                    </td>
                    <td className="px-1 py-1">
                      <input value={editNotes} onChange={e => setEditNotes(e.target.value)}
                        className="w-28 bg-surface-2 rounded px-1 py-0.5 text-xs border border-surface-2 focus:border-accent outline-none" />
                    </td>
                    <td className="px-1 py-1 flex gap-1">
                      <button onClick={saveEdit} disabled={saving}
                        className="px-2 py-0.5 rounded bg-accent/20 text-accent text-[10px] hover:bg-accent/30 disabled:opacity-40">
                        {saving ? "…" : "Save"}
                      </button>
                      <button onClick={() => setEditId(null)}
                        className="px-2 py-0.5 rounded bg-surface-2 text-text-muted text-[10px] hover:bg-surface-3">
                        ✕
                      </button>
                    </td>
                  </tr>
                ) : (
                  <tr key={r.id} className="hover:bg-surface-1/30 group cursor-pointer" onClick={() => startEdit(r)}>
                    <td className="px-2 py-1 border-b border-surface-2/10 whitespace-nowrap">{formatTs(r.logged_at)}</td>
                    <td className="px-2 py-1 border-b border-surface-2/10">{r.medication}</td>
                    <td className="px-2 py-1 border-b border-surface-2/10 whitespace-nowrap">{formatTs(r.dose_time)}</td>
                    <td className="px-2 py-1 border-b border-surface-2/10">{r.dose_mg != null ? String(r.dose_mg) : "—"}</td>
                    <td className="px-2 py-1 border-b border-surface-2/10">{r.notes ?? "—"}</td>
                    <td className="px-1 py-1 border-b border-surface-2/10 opacity-0 group-hover:opacity-100">
                      <button
                        onClick={e => { e.stopPropagation(); deleteRow(r.id, r.medication); }}
                        className="px-1.5 py-0.5 rounded bg-urgency-high/15 text-urgency-high text-[10px] hover:bg-urgency-high/30">
                        del
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="text-[10px] text-text-dim mt-2 px-2">Click any row to edit. Changes take effect on next briefing build.</p>
          </div>
        )}
      </Card>
    </div>
  );
}

/* ── User Corrections ─────────────────────────────────────────── */

function CorrectionsSection({ data }: { data: any[] | null }) {
  if (!data) return <Loading />;
  if (data.length === 0) return <Empty msg="No corrections recorded yet." />;

  return (
    <div className="space-y-4">
      <Card title="What Corrections Do">
        <p className="text-xs text-text-muted">
          When you tell CADEN it got something wrong (e.g. rescheduling a task, adjusting a mood reading),
          the correction is stored so the model can learn from mistakes. Corrections influence future factor
          extraction confidence and scheduling decisions.
        </p>
      </Card>

      <Card title={`Corrections (${data.length})`}>
        <div className="overflow-x-auto max-h-96 overflow-y-auto">
          <DataTable
            headers={["Time", "Type", "Description", "Data"]}
            rows={data.map((r: any) => [
              formatTs(r.timestamp), r.type, r.description,
              r.data ? r.data.substring(0, 80) + "…" : "—",
            ])}
          />
        </div>
      </Card>
    </div>
  );
}

/* ── Project Time ─────────────────────────────────────────────── */

function ProjectsSection({ data }: { data: any[] | null }) {
  if (!data) return <Loading />;
  if (data.length === 0) return <Empty msg="No project time data yet." />;

  const totalMin = data.reduce((s: number, r: any) => s + r.total_minutes, 0);

  return (
    <div className="space-y-4">
      <Card title="Project Time Tracking">
        <p className="text-xs text-text-muted">
          Time logged per project via the project time tracker. Total across all projects: <strong>{num(totalMin / 60)} hours</strong>.
        </p>
      </Card>

      <Card title="Time by Project">
        <div className="space-y-2">
          {data.map((r: any) => {
            const barWidth = totalMin > 0 ? (r.total_minutes / totalMin) * 100 : 0;
            return (
              <div key={r.id} className="space-y-0.5">
                <div className="flex justify-between text-sm">
                  <span>{r.name}</span>
                  <span className="font-mono text-text-muted">{num(r.total_minutes / 60)}h</span>
                </div>
                <div className="h-2 bg-surface-1/40 rounded-full overflow-hidden">
                  <div className="h-full bg-accent/60 rounded-full" style={{ width: `${barWidth}%` }} />
                </div>
              </div>
            );
          })}
        </div>
      </Card>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   Shared UI Components
   ═══════════════════════════════════════════════════════════════════════════ */

function Loading() {
  return <div className="text-center text-text-muted py-8">Loading…</div>;
}

function Empty({ msg }: { msg: string }) {
  return <div className="text-center text-text-muted/60 py-8 text-sm">{msg}</div>;
}

function DataTable({ headers, rows }: { headers: string[]; rows: string[][] }) {
  return (
    <table className="w-full text-xs border-collapse">
      <thead>
        <tr>
          {headers.map((h, i) => (
            <th key={i} className="text-left px-2 py-1 text-text-muted border-b border-surface-2/30 font-medium">
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, ri) => (
          <tr key={ri} className="hover:bg-surface-1/30">
            {row.map((cell, ci) => (
              <td key={ci} className="px-2 py-1 border-b border-surface-2/10 whitespace-nowrap">
                {cell}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
