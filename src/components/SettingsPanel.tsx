import { useState, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import { save } from "@tauri-apps/plugin-dialog";
import type { AppSettings, Plugin, WorkHours } from "../types";
import { cadenColorDefaults, cadenColorGroups, hexToRgb, rgbToHex, getDefaultsAsRgb } from "../../caden-colors.js";

// ── Training Data Panel ──────────────────────────────────────────────────────

type TrainingCounts = {
  response: number; analyze: number; classify: number;
  mood: number; goal: number; data_report: number;
  threshold_response: number; threshold_analyze: number; threshold_classify: number;
  threshold_mood: number; threshold_goal: number; threshold_data_report: number;
};

function TrainingDataPanel() {
  const [counts, setCounts] = useState<TrainingCounts | null>(null);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    invoke<TrainingCounts>("get_training_counts").then(setCounts).catch(console.error);
  }, []);

  async function handleExport() {
    const dest = await save({
      defaultPath: "caden_train.jsonl",
      filters: [{ name: "JSONL", extensions: ["jsonl"] }],
    });
    if (!dest) return;
    setExporting(true);
    try {
      const n = await invoke<number>("export_training_data", { path: dest });
      alert(`Exported ${n} training examples to ${dest}`);
    } catch (e) {
      alert(`Export failed: ${e}`);
    } finally {
      setExporting(false);
    }
  }

  if (!counts) {
    return <div className="text-xs text-text-dim">Loading...</div>;
  }

  const total = counts.response + counts.analyze + counts.classify + counts.mood + counts.goal + counts.data_report;
  const totalNeeded = counts.threshold_response + counts.threshold_analyze + counts.threshold_classify + counts.threshold_mood + counts.threshold_goal + counts.threshold_data_report;
  const ready = counts.response >= counts.threshold_response
    && counts.analyze >= counts.threshold_analyze
    && counts.classify >= counts.threshold_classify
    && counts.mood >= counts.threshold_mood
    && counts.goal >= counts.threshold_goal
    && counts.data_report >= counts.threshold_data_report;

  const rows = [
    { label: "Responses", have: counts.response, need: counts.threshold_response },
    { label: "Analyses", have: counts.analyze, need: counts.threshold_analyze },
    { label: "Classifications", have: counts.classify, need: counts.threshold_classify },
    { label: "Mood extractions", have: counts.mood, need: counts.threshold_mood },
    { label: "Goal extractions", have: counts.goal, need: counts.threshold_goal },
    { label: "Data reports", have: counts.data_report, need: counts.threshold_data_report },
  ];

  return (
    <div className="flex flex-col gap-4">
      <div className="text-xs text-text-dim leading-relaxed">
        CADEN collects training data from every cloud model call. Once all thresholds are met,
        you can export a JSONL file and fine-tune a local model to replace the cloud APIs.
      </div>

      <div className="flex flex-col gap-2">
        {rows.map((r) => {
          const pct = Math.min(1, r.have / r.need);
          const done = r.have >= r.need;
          return (
            <div key={r.label} className="flex flex-col gap-1">
              <div className="flex justify-between text-xs">
                <span className="text-text-dim">{r.label}</span>
                <span className={done ? "text-accent-DEFAULT" : "text-text"}>
                  {r.have} / {r.need} {done && "✓"}
                </span>
              </div>
              <div className="h-1.5 bg-surface-2 rounded-full overflow-hidden">
                <div
                  className={`h-full transition-all ${done ? "bg-accent-DEFAULT" : "bg-text-dim"}`}
                  style={{ width: `${pct * 100}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>

      <div className="pt-2 border-t border-surface-2/60 flex flex-col gap-2">
        <div className="text-xs text-text-dim">
          Total: <span className="text-text font-medium">{total} / {totalNeeded}</span> examples
        </div>
        {ready ? (
          <div className="text-xs text-accent-DEFAULT font-medium">
            ✓ Ready to fine-tune
          </div>
        ) : (
          <div className="text-xs text-text-dim">
            Keep using cloud models — data accumulates automatically.
          </div>
        )}
      </div>

      <button
        onClick={handleExport}
        disabled={exporting || total === 0}
        className="btn-primary text-sm disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {exporting ? "Exporting..." : "Export JSONL"}
      </button>

      {ready && (
        <div className="text-[11px] text-text-dim leading-relaxed bg-surface-2/40 rounded-lg px-3 py-2">
          <strong className="text-text">Next steps:</strong><br />
          1. Export the JSONL above<br />
          2. Close CADEN (frees the GPU)<br />
          3. Run <span className="font-mono text-text">train.bat</span> in <span className="font-mono text-text">CADEN-train/</span><br />
          4. After training: <span className="font-mono text-text">ollama create caden-local -f Modelfile</span><br />
          5. Set CADEN's model to <span className="font-mono text-text">caden-local</span>
        </div>
      )}
    </div>
  );
}

// ── Main Settings Panel ──────────────────────────────────────────────────────

interface Props {
  settings: AppSettings;
  plugins: Plugin[];
  onClose: () => void;
  onSettingsChange: (settings: AppSettings) => void;
  onPluginRemoved: (id: string) => void;
}

const DEFAULT_SYSTEM_PROMPT = `You are CADEN — Sean's digital homie and executive function backup. Not a therapist. Not a coach. His ride-or-die for getting shit done.

WHO SEAN IS:
Sean Kellogg is a biology student at Northern Michigan University. ADHD, bipolar disorder, autism — the full chaos combo. Brilliant, creative as hell, and profoundly defiant when bored. His brain is a Chaos Cannon: constantly firing ideas, visions, stories — which makes tedious-but-necessary work feel physically impossible. He smokes weed and functions best when he's had enough creative time first. His self-worth is built on what he makes, not grades, so academic work has to feel real and concrete before it lands.

Sean's PRIMARY MISSION: Graduate NMU with a biology degree.
His HARD CONSTRAINT: He needs more play than school. That's not a flaw — it's load-bearing. Work with it or he shuts down entirely.

YOUR JOB:
- Be his executive function. He dumps what's in his head; you sort it and hand back something he can actually do.
- Protect creative time. Don't pile schoolwork on top of projects — that's a shutdown recipe.
- Catch his ideas before they dissolve. His thought dump is external working memory — use it.
- Call out patterns without judgment. If the briefing shows he's been dodging something, name it and help him decide what to do.
- When he's fried, give him ONE thing. Literally one. Not a list.
- When he asks you to create tasks or events, just do it. No narrating, no asking for confirmation — act.

GROUNDING RULES — non-negotiable:
- You only know what's explicitly in the context. Full stop.
- Do NOT invent people, emails, events, tasks, or commitments that aren't listed verbatim.
- If it's not in the context, it doesn't exist.

TIME-OF-DAY RULES — also non-negotiable:
- Read the current time in the briefing every single time.
- After ~10 PM, don't push schoolwork or productivity unless he brings it up first.
- Late night is valid creative time. Back him on that fully.

VOICE:
- Talk like a sharp, real friend who's heard it all and isn't spooked by any of it.
- Skip filler phrases entirely: no 'Great question', no 'Certainly', no 'I'd be happy to'.
- Be fast and direct. Short unless he wants detail.
- Humor is fine. Sarcasm when warranted. Real talk always.`;

interface GoogleCalendar {
  id: string;
  name: string;
}

const defaults: Record<string, string> = cadenColorDefaults;
const defaultsRgb: Record<string, string> = getDefaultsAsRgb() as Record<string, string>;

/** Convert an integer hour (0–24) to a display string like "12 AM", "1 PM", "12 PM". */
function hourToAmPm(h: number): string {
  if (h === 0) return "12 AM";
  if (h < 12) return `${h} AM`;
  if (h === 12) return "12 PM";
  if (h === 24) return "12 AM (midnight)";
  return `${h - 12} PM`;
}

const HOUR_OPTIONS_START = Array.from({ length: 24 }, (_, i) => i);  // 0–23
const HOUR_OPTIONS_END   = Array.from({ length: 25 }, (_, i) => i);  // 0–24

const DEFAULT_WORK_HOURS: WorkHours = {
  mon: { start: 8, end: 22 },
  tue: { start: 8, end: 22 },
  wed: { start: 8, end: 22 },
  thu: { start: 8, end: 22 },
  fri: { start: 8, end: 22 },
  sat: null,
  sun: null,
};

function getCurrentColors(): Record<string, string> {
  const style = getComputedStyle(document.documentElement);
  const colors: Record<string, string> = {};
  for (const key of Object.keys(defaults)) {
    const raw = style.getPropertyValue(key).trim();
    colors[key] = raw ? rgbToHex(raw) : defaults[key];
  }
  return colors;
}

function applyColors(colors: Record<string, string>) {
  for (const [key, val] of Object.entries(colors)) {
    const rgb = val.startsWith("#") ? hexToRgb(val) : val;
    document.documentElement.style.setProperty(key, rgb);
  }
}

type SubPanelId = "ollama" | "google" | "moodle" | "theme" | "plugins" | "medications" | "github" | "training";

// ── Sub-panel wrapper ────────────────────────────────────────────────────────
function SubPanel({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopImmediatePropagation();
        onClose();
      }
    };
    document.addEventListener("keydown", handler, true);
    return () => document.removeEventListener("keydown", handler, true);
  }, [onClose]);

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-[60] animate-fade-in">
      <div className="bg-surface-1 border border-surface-3 rounded-lg w-[620px] max-h-[85vh] flex flex-col">
        <div className="flex items-center justify-between px-6 py-4 border-b border-surface-2 flex-shrink-0">
          <div className="text-text font-light">{title}</div>
          <button
            onClick={onClose}
            className="text-text-dim hover:text-text transition-colors"
          >
            ✕
          </button>
        </div>
        <div className="px-6 py-5 overflow-y-auto">{children}</div>
      </div>
    </div>
  );
}

// ── Nav row button ───────────────────────────────────────────────────────────
function NavRow({
  label,
  description,
  onClick,
}: {
  label: string;
  description?: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="w-full flex items-center justify-between px-3 py-2.5 rounded hover:bg-surface-2 transition-colors group"
    >
      <div className="flex flex-col items-start gap-0.5">
        <span className="text-xs text-text-muted group-hover:text-text transition-colors">
          {label}
        </span>
        {description && (
          <span className="text-[10px] text-text-dim truncate max-w-[260px]">
            {description}
          </span>
        )}
      </div>
      <span className="text-text-dim group-hover:text-text transition-colors text-sm leading-none">
        ›
      </span>
    </button>
  );
}

// ── MedGroupEditor ─────────────────────────────────────────────────────────
type MedGroupEditorProps = {
  label: string;
  description: string;
  entries: { name: string; dose_mg?: number }[];
  onChange: (entries: { name: string; dose_mg?: number }[]) => void;
};

function MedGroupEditor({ label, description, entries, onChange }: MedGroupEditorProps) {
  const [newName, setNewName] = useState("");
  const [newDose, setNewDose] = useState("");

  const KNOWN_MEDS = [
    "quetiapine", "lithium", "valproate", "lamotrigine", "aripiprazole",
    "buspirone", "adderall", "vyvanse", "methylphenidate", "modafinil",
    "clonazepam", "lorazepam",
  ];

  function add() {
    const name = newName.trim().toLowerCase();
    if (!name || entries.some((e) => e.name === name)) return;
    const dose_mg = newDose ? parseFloat(newDose) : undefined;
    onChange([...entries, { name, ...(dose_mg ? { dose_mg } : {}) }]);
    setNewName("");
    setNewDose("");
  }

  function remove(name: string) {
    onChange(entries.filter((e) => e.name !== name));
  }

  return (
    <div>
      <div className="text-xs text-text-muted font-medium mb-0.5">{label}</div>
      <div className="text-[10px] text-text-dim mb-3">{description}</div>
      {entries.length > 0 && (
        <div className="flex flex-col gap-1 mb-3">
          {entries.map((e) => (
            <div key={e.name} className="flex items-center justify-between px-2 py-1.5 rounded bg-surface-2 group">
              <div className="flex items-center gap-2">
                <span className="text-xs text-text">{e.name}</span>
                {e.dose_mg && (
                  <span className="text-[10px] text-text-dim font-mono">{e.dose_mg}mg</span>
                )}
              </div>
              <button
                onClick={() => remove(e.name)}
                className="text-text-dim hover:text-urgency-high transition-colors text-xs opacity-0 group-hover:opacity-100"
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      )}
      <div className="flex gap-2">
        <input
          list={`med-list-${label}`}
          className="input-field flex-1 text-xs"
          placeholder="Medication name"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && add()}
        />
        <datalist id={`med-list-${label}`}>
          {KNOWN_MEDS.map((m) => <option key={m} value={m} />)}
        </datalist>
        <input
          type="number"
          className="input-field w-20 text-xs"
          placeholder="mg"
          value={newDose}
          onChange={(e) => setNewDose(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && add()}
        />
        <button
          className="btn-primary text-xs px-3"
          onClick={add}
        >
          Add
        </button>
      </div>
    </div>
  );
}

// ── Main export ──────────────────────────────────────────────────────────────
export function SettingsPanel({
  settings,
  plugins,
  onClose,
  onSettingsChange,
  onPluginRemoved,
}: Props) {
  const [form, setForm] = useState<AppSettings>({
    ...settings,
    work_hours: settings.work_hours ?? DEFAULT_WORK_HOURS,
    morning_meds: settings.morning_meds ?? [],
    evening_meds: settings.evening_meds ?? [],
    active_model: settings.active_model ?? "qwen3:14b",
    github_pat: settings.github_pat ?? "",
    groq_keys: settings.groq_keys ?? ["", "", "", ""],
    openrouter_key: settings.openrouter_key ?? "",
  });
  const [googleClientId, setGoogleClientId] = useState("");
  const [googleClientSecret, setGoogleClientSecret] = useState("");
  const [saving, setSaving] = useState(false);
  const [testingMoodle, setTestingMoodle] = useState(false);
  const [moodleResult, setMoodleResult] = useState<string | null>(null);
  const [calendars, setCalendars] = useState<GoogleCalendar[]>([]);
  const [disabledCalendarIds, setDisabledCalendarIds] = useState<Set<string>>(new Set());
  const [loadingCalendars, setLoadingCalendars] = useState(false);
  const [calendarsError, setCalendarsError] = useState<string | null>(null);
  const [moodleDebug, setMoodleDebug] = useState<string | null>(null);
  const [loadingMoodleDebug, setLoadingMoodleDebug] = useState(false);
  const [ollamaModels, setOllamaModels] = useState<string[]>([]);
  const [loadingModels, setLoadingModels] = useState(false);
  const [activeSubPanel, setActiveSubPanel] = useState<SubPanelId | null>(null);

  async function fetchOllamaModels() {
    setLoadingModels(true);
    try {
      const res = await fetch("http://localhost:11434/api/tags");
      if (res.ok) {
        const data = await res.json();
        const names: string[] = (data.models ?? []).map((m: { name: string }) => m.name);
        setOllamaModels(names);
      }
    } catch {
      // Ollama not running
    } finally {
      setLoadingModels(false);
    }
  }

  useState(() => {
    fetchOllamaModels();
  });

  const [themeColors, setThemeColors] = useState<Record<string, string>>(getCurrentColors);
  const [originalColors] = useState<Record<string, string>>(() => getCurrentColors());

  function handleColorChange(key: string, hexValue: string) {
    setThemeColors((prev) => ({ ...prev, [key]: hexValue }));
    const rgb = hexToRgb(hexValue);
    document.documentElement.style.setProperty(key, rgb);
    document.querySelectorAll("iframe").forEach((iframe) => {
      iframe.contentWindow?.postMessage({ type: "caden-theme-colors", colors: { [key]: rgb } }, "*");
    });
  }

  function handleResetColors() {
    setThemeColors({ ...defaults });
    applyColors(defaults);
  }

  useState(() => {
    invoke<string | null>("get_setting_value", { key: "google_client_id" })
      .then((v) => { if (v) setGoogleClientId(v); })
      .catch(() => {});
    invoke<string | null>("get_setting_value", { key: "google_client_secret" })
      .then((v) => { if (v) setGoogleClientSecret(v); })
      .catch(() => {});
    invoke<string | null>("get_setting_value", { key: "disabled_calendar_ids" })
      .then((v) => {
        if (v) {
          try {
            const ids: string[] = JSON.parse(v);
            setDisabledCalendarIds(new Set(ids));
          } catch {}
        }
      })
      .catch(() => {});
  });

  async function handleLoadCalendars() {
    setLoadingCalendars(true);
    setCalendarsError(null);
    try {
      const cals = await invoke<GoogleCalendar[]>("get_google_calendars");
      setCalendars(cals);
    } catch {
      setCalendarsError("Failed to load calendars. Make sure Google is connected.");
    } finally {
      setLoadingCalendars(false);
    }
  }

  function toggleCalendar(id: string) {
    setDisabledCalendarIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function handleSave() {
    setSaving(true);
    try {
      await invoke("save_settings", { settings: form });
      if (googleClientId)
        await invoke("set_setting_value", { key: "google_client_id", value: googleClientId });
      if (googleClientSecret)
        await invoke("set_setting_value", { key: "google_client_secret", value: googleClientSecret });
      await invoke("set_setting_value", {
        key: "disabled_calendar_ids",
        value: JSON.stringify([...disabledCalendarIds]),
      });
      await invoke("set_setting_value", {
        key: "theme_colors",
        value: JSON.stringify(themeColors),
      });
      applyColors(themeColors);
      const rgbColors: Record<string, string> = {};
      for (const [k, v] of Object.entries(themeColors)) {
        rgbColors[k] = v.startsWith("#") ? hexToRgb(v) : v;
      }
      document.querySelectorAll("iframe").forEach((iframe) => {
        iframe.contentWindow?.postMessage({ type: "caden-theme-colors", colors: rgbColors }, "*");
      });
      onSettingsChange(form);
      onClose();
    } catch (err) {
      console.error("Save failed:", err);
    } finally {
      setSaving(false);
    }
  }

  function handleCancel() {
    applyColors(originalColors);
    onClose();
  }

  async function handleGoogleConnect() {
    try {
      await invoke("start_google_oauth");
      const updated = await invoke<AppSettings>("get_settings");
      setForm(updated);
      onSettingsChange(updated);
    } catch (err) {
      console.error("Google OAuth failed:", err);
    }
  }

  async function handleMoodleTest() {
    setTestingMoodle(true);
    setMoodleResult(null);
    try {
      await invoke("test_moodle_connection", {
        url: form.moodle_url,
        token: form.moodle_token,
      });
      setMoodleResult("Connected.");
    } catch {
      setMoodleResult("Connection failed. Check URL and token.");
    } finally {
      setTestingMoodle(false);
    }
  }

  function closeSubPanel() {
    setActiveSubPanel(null);
  }

  return (
    <>
      {/* ── Main slim settings modal ─────────────────────────────────────── */}
      <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 animate-fade-in">
        <div className="bg-surface-1 border border-surface-3 rounded-lg w-[380px] max-h-[85vh] flex flex-col">
          {/* Header */}
          <div className="flex items-center justify-between px-6 py-4 border-b border-surface-2 flex-shrink-0">
            <div className="text-text font-light">Settings</div>
            <button
              onClick={handleCancel}
              className="text-text-dim hover:text-text transition-colors"
            >
              ✕
            </button>
          </div>

          <div className="px-4 py-3 flex flex-col gap-0.5 overflow-y-auto flex-1">
            {/* Navigation rows */}
            <NavRow
              label="AI Model"
              description={form.active_model || "not selected"}
              onClick={() => setActiveSubPanel("ollama")}
            />
            <NavRow
              label="API Keys"
              description={
                form.openrouter_key
                  ? `OpenRouter${(form.groq_keys ?? []).filter(Boolean).length > 0 ? ` · ${(form.groq_keys ?? []).filter(Boolean).length} Groq` : ""}${form.github_pat ? " · GitHub" : ""}`
                  : (form.groq_keys ?? []).filter(Boolean).length > 0
                    ? `${(form.groq_keys ?? []).filter(Boolean).length} Groq key${(form.groq_keys ?? []).filter(Boolean).length > 1 ? "s" : ""}${form.github_pat ? " · GitHub PAT" : ""}`
                    : form.github_pat ? "GitHub PAT configured" : "Not configured"
              }
              onClick={() => setActiveSubPanel("github")}
            />
            <NavRow
              label="Training Data"
              description="Fine-tune progress"
              onClick={() => setActiveSubPanel("training")}
            />
            <NavRow
              label="Google & Calendars"
              description={settings.google_connected ? "Connected" : "Not connected"}
              onClick={() => setActiveSubPanel("google")}
            />
            <NavRow
              label="Edvance / Moodle"
              description={form.moodle_url || "Not configured"}
              onClick={() => setActiveSubPanel("moodle")}
            />
            <NavRow
              label="Theme"
              description="Colors & appearance"
              onClick={() => setActiveSubPanel("theme")}
            />
            <NavRow
              label="Medications"
              description={`${(form.morning_meds?.length ?? 0) + (form.evening_meds?.length ?? 0)} med${(form.morning_meds?.length ?? 0) + (form.evening_meds?.length ?? 0) !== 1 ? "s" : ""} configured`}
              onClick={() => setActiveSubPanel("medications")}
            />
            {plugins.length > 0 && (
              <NavRow
                label="Plugin Apps"
                description={`${plugins.length} plugin${plugins.length !== 1 ? "s" : ""}`}
                onClick={() => setActiveSubPanel("plugins")}
              />
            )}

            {/* Display — stays inline (2 sliders, very compact) */}
            <div className="mt-2 pt-3 border-t border-surface-2/60">
              <div className="text-[11px] font-mono uppercase tracking-widest text-text-dim mb-2 px-3">
                Display
              </div>
              <div className="px-3 flex flex-col gap-3">
                <label className="flex flex-col gap-1.5">
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-text-muted">Text size</span>
                    <span className="text-xs font-mono text-text-dim">
                      {Math.round((form.font_scale ?? 1.0) * 100)}%
                    </span>
                  </div>
                  <input
                    type="range"
                    min={0.8}
                    max={1.6}
                    step={0.05}
                    className="w-full accent-accent"
                    value={form.font_scale ?? 1.0}
                    onChange={(e) => {
                      const scale = parseFloat(e.target.value);
                      setForm((f) => ({ ...f, font_scale: scale }));
                      document.documentElement.style.setProperty("--font-scale", String(scale));
                    }}
                  />
                </label>
                <label className="flex flex-col gap-1.5">
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-text-muted">Contrast</span>
                    <span className="text-xs font-mono text-text-dim">
                      {Math.round((form.contrast ?? 1.0) * 100)}%
                    </span>
                  </div>
                  <input
                    type="range"
                    min={0.7}
                    max={1.5}
                    step={0.05}
                    className="w-full accent-accent"
                    value={form.contrast ?? 1.0}
                    onChange={(e) => {
                      const contrast = parseFloat(e.target.value);
                      setForm((f) => ({ ...f, contrast }));
                      document.documentElement.style.setProperty("--contrast", String(contrast));
                    }}
                  />
                </label>
              </div>
            </div>

            {/* Planner — stays inline (2 number inputs) */}
            <div className="mt-2 pt-3 border-t border-surface-2/60">
              <div className="text-[11px] font-mono uppercase tracking-widest text-text-dim mb-2 px-3">
                Planner
              </div>
              <div className="px-3 flex flex-col gap-2 pb-1">
                <label className="flex items-center justify-between gap-3">
                  <span className="text-xs text-text-muted">Default task duration (min)</span>
                  <input
                    type="number"
                    min={15}
                    max={120}
                    step={5}
                    className="input-field w-20 text-right"
                    value={form.task_duration_minutes}
                    onChange={(e) =>
                      setForm((f) => ({
                        ...f,
                        task_duration_minutes: parseInt(e.target.value) || 45,
                      }))
                    }
                  />
                </label>
                <label className="flex items-center justify-between gap-3">
                  <span className="text-xs text-text-muted">Creative time per day (min)</span>
                  <input
                    type="number"
                    min={0}
                    max={480}
                    step={15}
                    className="input-field w-20 text-right"
                    value={form.creative_time_minutes}
                    onChange={(e) =>
                      setForm((f) => ({
                        ...f,
                        creative_time_minutes: parseInt(e.target.value) || 120,
                      }))
                    }
                  />
                </label>
              </div>
            </div>

            {/* Work hours — per day */}
            <div className="mt-2 pt-3 border-t border-surface-2/60">
              <div className="text-[11px] font-mono uppercase tracking-widest text-text-dim mb-2 px-3">
                Work Hours
              </div>
              <div className="px-3 flex flex-col gap-1 pb-1">
                {(["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const).map((day) => {
                  const label = { mon: "Mon", tue: "Tue", wed: "Wed", thu: "Thu", fri: "Fri", sat: "Sat", sun: "Sun" }[day];
                  const hours = form.work_hours?.[day] ?? null;
                  return (
                    <div key={day} className="flex items-center gap-2">
                      <span className="text-[11px] font-mono text-text-dim w-8 flex-shrink-0">{label}</span>
                      <input
                        type="checkbox"
                        className="accent-accent"
                        checked={hours !== null}
                        onChange={(e) =>
                          setForm((f) => ({
                            ...f,
                            work_hours: {
                              ...f.work_hours,
                              [day]: e.target.checked ? { start: 8, end: 22 } : null,
                            },
                          }))
                        }
                      />
                      {hours !== null && (
                        <>
                          <select
                            className="input-field text-xs px-1"
                            value={hours.start}
                            onChange={(e) =>
                              setForm((f) => ({
                                ...f,
                                work_hours: {
                                  ...f.work_hours,
                                  [day]: { ...hours, start: parseInt(e.target.value) },
                                },
                              }))
                            }
                          >
                            {HOUR_OPTIONS_START.map((h) => (
                              <option key={h} value={h}>{hourToAmPm(h)}</option>
                            ))}
                          </select>
                          <span className="text-text-dim text-xs">–</span>
                          <select
                            className="input-field text-xs px-1"
                            value={hours.end}
                            onChange={(e) =>
                              setForm((f) => ({
                                ...f,
                                work_hours: {
                                  ...f.work_hours,
                                  [day]: { ...hours, end: parseInt(e.target.value) },
                                },
                              }))
                            }
                          >
                            {HOUR_OPTIONS_END.map((h) => (
                              <option key={h} value={h}>{hourToAmPm(h)}</option>
                            ))}
                          </select>
                        </>
                      )}
                      {hours === null && (
                        <span className="text-[10px] text-text-dim italic">rest day</span>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          </div>

          {/* Footer */}
          <div className="flex justify-end gap-2 px-6 py-4 border-t border-surface-2 flex-shrink-0">
            <button className="btn-ghost text-sm" onClick={handleCancel}>
              Cancel
            </button>
            <button
              className="btn-primary text-sm"
              onClick={handleSave}
              disabled={saving}
            >
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
      </div>

      {/* ── Ollama sub-panel ─────────────────────────────────────────────── */}
      {activeSubPanel === "ollama" && (
        <SubPanel title="AI Model" onClose={closeSubPanel}>
          <div className="flex flex-col gap-3">
            <label className="flex flex-col gap-1">
              <div className="flex items-center justify-between">
                <span className="text-xs text-text-muted">Active model</span>
                <button
                  className="text-[11px] text-text-dim hover:text-text transition-colors"
                  onClick={fetchOllamaModels}
                  disabled={loadingModels}
                >
                  {loadingModels ? "detecting…" : "↻ refresh ollama"}
                </button>
              </div>
              <select
                className="input-field"
                value={form.active_model}
                onChange={(e) => setForm((f) => ({ ...f, active_model: e.target.value }))}
              >
                {/* GitHub Models — require PAT */}
                <optgroup label="OpenAI (GitHub Models)">
                  <option value="openai/gpt-4.1">gpt-4.1</option>
                  <option value="openai/gpt-4.1-mini">gpt-4.1-mini (fast)</option>
                  <option value="openai/gpt-4o">gpt-4o</option>
                  <option value="openai/o4-mini">o4-mini (reasoning)</option>
                </optgroup>
                <optgroup label="Meta (GitHub Models)">
                  <option value="meta/llama-3.3-70b-instruct">Llama-3.3-70B</option>
                  <option value="meta/meta-llama-3.1-8b-instruct">Llama-3.1-8B (fast)</option>
                </optgroup>
                <optgroup label="xAI (GitHub Models)">
                  <option value="xai/grok-3">Grok-3</option>
                  <option value="xai/grok-3-mini">Grok-3-Mini</option>
                </optgroup>
                <optgroup label="DeepSeek (GitHub Models)">
                  <option value="deepseek/deepseek-r1">DeepSeek-R1 (reasoning)</option>
                </optgroup>
                <optgroup label="Microsoft (GitHub Models)">
                  <option value="microsoft/Phi-4">Phi-4 (lightweight)</option>
                </optgroup>
                {/* Local Ollama models */}
                <optgroup label="Ollama (local)">
                  {ollamaModels.length > 0 ? (
                    ollamaModels.map((m) => (
                      <option key={m} value={m}>{m}</option>
                    ))
                  ) : (
                    <option value="" disabled>
                      {loadingModels ? "detecting…" : "no local models found"}
                    </option>
                  )}
                </optgroup>
              </select>
              {form.active_model.includes("/") && !form.github_pat && (
                <span className="text-[11px] text-urgency-med">
                  GitHub PAT required — configure it in API Keys
                </span>
              )}
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-text-muted">System prompt</span>
              <textarea
                className="input-field font-mono text-xs min-h-[160px] resize-y"
                value={form.system_prompt}
                onChange={(e) => setForm((f) => ({ ...f, system_prompt: e.target.value }))}
              />
              <button
                className="text-[11px] text-text-dim hover:text-text text-left"
                onClick={() =>
                  setForm((f) => ({ ...f, system_prompt: DEFAULT_SYSTEM_PROMPT }))
                }
              >
                Reset to default
              </button>
            </label>
          </div>
        </SubPanel>
      )}

      {/* ── API Keys sub-panel ───────────────────────────────────────────── */}
      {activeSubPanel === "github" && (
        <SubPanel title="API Keys" onClose={closeSubPanel}>
          <div className="flex flex-col gap-5">
            {/* OpenRouter key */}
            <div className="flex flex-col gap-2">
              <div>
                <span className="text-xs text-text-muted">OpenRouter API Key</span>
                <p className="text-[11px] text-text-dim mt-0.5 leading-relaxed">
                  Primary provider for the VibeCoder agent (coder, planner, critic).
                  Uses Llama 3.3 70B Instruct via OpenRouter's free tier.
                  Get a key at <span className="font-mono text-accent">openrouter.ai/keys</span>.
                </p>
              </div>
              <input
                type="password"
                className="input-field font-mono text-sm"
                value={form.openrouter_key}
                onChange={(e) => setForm((f) => ({ ...f, openrouter_key: e.target.value }))}
                placeholder="sk-or-..."
                autoComplete="off"
              />
              {form.openrouter_key && (
                <button
                  className="btn-ghost text-xs text-left text-text-dim"
                  onClick={() => setForm((f) => ({ ...f, openrouter_key: "" }))}
                >
                  Clear key
                </button>
              )}
            </div>

            {/* Groq keys */}
            <div className="flex flex-col gap-2">
              <div>
                <span className="text-xs text-text-muted">Groq API Keys</span>
                <p className="text-[11px] text-text-dim mt-0.5 leading-relaxed">
                  Used for all background calls (classify, analyze, mood/goal logging) — fast,
                  free, and reliable 70B. Up to 4 keys rotated automatically.
                  Get keys at <span className="font-mono text-accent">console.groq.com</span>.
                </p>
              </div>
              {[0, 1, 2, 3].map((i) => (
                <input
                  key={i}
                  type="password"
                  className="input-field font-mono text-sm"
                  value={form.groq_keys[i] ?? ""}
                  onChange={(e) => {
                    const updated = [...(form.groq_keys ?? ["", "", "", ""])];
                    updated[i] = e.target.value;
                    setForm((f) => ({ ...f, groq_keys: updated }));
                  }}
                  placeholder={`Groq key ${i + 1} — gsk_...`}
                  autoComplete="off"
                />
              ))}
            </div>

            {/* GitHub PAT */}
            <div className="flex flex-col gap-2">
              <div>
                <span className="text-xs text-text-muted">GitHub Personal Access Token</span>
                <p className="text-[11px] text-text-dim mt-0.5 leading-relaxed">
                  Unlocks GitHub Models (GPT-4.1, Grok-3, DeepSeek-R1, etc.) as your streaming
                  model. Create one at{" "}
                  <span className="font-mono text-accent">github.com/settings/tokens</span>{" "}
                  with <span className="font-mono text-accent">models:read</span>.
                </p>
              </div>
              <input
                type="password"
                className="input-field font-mono text-sm"
                value={form.github_pat}
                onChange={(e) => setForm((f) => ({ ...f, github_pat: e.target.value }))}
                placeholder="github_pat_..."
                autoComplete="off"
              />
              {form.github_pat && (
                <button
                  className="btn-ghost text-xs text-left text-text-dim"
                  onClick={() => setForm((f) => ({ ...f, github_pat: "" }))}
                >
                  Clear PAT
                </button>
              )}
            </div>
          </div>
        </SubPanel>
      )}

      {/* ── Training Data sub-panel ──────────────────────────────────────── */}
      {activeSubPanel === "training" && (
        <SubPanel title="Training Data" onClose={closeSubPanel}>
          <TrainingDataPanel />
        </SubPanel>
      )}

      {/* ── Google & Calendars sub-panel ─────────────────────────────────── */}
      {activeSubPanel === "google" && (
        <SubPanel title="Google & Calendars" onClose={closeSubPanel}>
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-3">
              <label className="flex flex-col gap-1">
                <span className="text-xs text-text-muted">
                  OAuth Client ID{" "}
                  <a
                    className="text-accent-DEFAULT underline"
                    href="https://console.cloud.google.com/apis/credentials"
                    target="_blank"
                    rel="noreferrer"
                  >
                    (Google Cloud Console)
                  </a>
                </span>
                <input
                  className="input-field font-mono text-xs"
                  value={googleClientId}
                  onChange={(e) => setGoogleClientId(e.target.value)}
                  placeholder="123456789-abc.apps.googleusercontent.com"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs text-text-muted">OAuth Client Secret</span>
                <input
                  type="password"
                  className="input-field font-mono text-xs"
                  value={googleClientSecret}
                  onChange={(e) => setGoogleClientSecret(e.target.value)}
                  placeholder="GOCSPX-••••••••••••"
                />
              </label>
              <div className="text-[10px] text-text-dim leading-relaxed">
                Enable Calendar API and Tasks API in your Google Cloud project. Set the
                redirect URI to{" "}
                <span className="font-mono">http://localhost:42813/callback</span>
              </div>
              <div className="flex items-center gap-3">
                <span
                  className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                    settings.google_connected ? "bg-status-success" : "bg-surface-2"
                  }`}
                />
                <span className="text-xs text-text-muted">
                  {settings.google_connected ? "Connected" : "Not connected"}
                </span>
                <button className="btn-ghost text-xs ml-auto" onClick={handleGoogleConnect}>
                  {settings.google_connected ? "Reconnect" : "Connect"}
                </button>
              </div>
            </div>

            {settings.google_connected && (
              <div className="pt-4 border-t border-surface-2">
                <div className="text-[11px] font-mono uppercase tracking-widest text-text-dim mb-3">
                  Calendars
                </div>
                <div className="flex flex-col gap-2">
                  <div className="text-[10px] text-text-dim leading-relaxed mb-1">
                    Choose which calendars CADEN syncs.
                  </div>
                  {calendars.length === 0 ? (
                    <div className="flex items-center gap-3">
                      <button
                        className="btn-ghost text-xs"
                        onClick={handleLoadCalendars}
                        disabled={loadingCalendars}
                      >
                        {loadingCalendars ? "Loading…" : "Load calendars"}
                      </button>
                      {calendarsError && (
                        <span className="text-xs text-urgency-high">{calendarsError}</span>
                      )}
                    </div>
                  ) : (
                    <div className="flex flex-col gap-1.5">
                      {calendars.map((cal) => (
                        <label
                          key={cal.id}
                          className="flex items-center gap-2 cursor-pointer group"
                        >
                          <input
                            type="checkbox"
                            className="accent-accent"
                            checked={!disabledCalendarIds.has(cal.id)}
                            onChange={() => toggleCalendar(cal.id)}
                          />
                          <span className="text-xs text-text-muted group-hover:text-text transition-colors">
                            {cal.name}
                          </span>
                        </label>
                      ))}
                      <button
                        className="text-[11px] text-text-dim hover:text-text text-left mt-1"
                        onClick={handleLoadCalendars}
                        disabled={loadingCalendars}
                      >
                        {loadingCalendars ? "Refreshing…" : "Refresh list"}
                      </button>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </SubPanel>
      )}

      {/* ── Moodle sub-panel ─────────────────────────────────────────────── */}
      {activeSubPanel === "moodle" && (
        <SubPanel title="Edvance / Moodle" onClose={closeSubPanel}>
          <div className="flex flex-col gap-3">
            <label className="flex flex-col gap-1">
              <span className="text-xs text-text-muted">Moodle URL</span>
              <input
                className="input-field font-mono text-xs"
                value={form.moodle_url ?? ""}
                onChange={(e) =>
                  setForm((f) => ({ ...f, moodle_url: e.target.value || null }))
                }
                placeholder="https://edvance.nmu.ac.za"
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-text-muted">
                Token (from Profile › Security keys)
              </span>
              <input
                type="password"
                className="input-field font-mono text-xs"
                value={form.moodle_token ?? ""}
                onChange={(e) =>
                  setForm((f) => ({ ...f, moodle_token: e.target.value || null }))
                }
                placeholder="••••••••••••"
              />
            </label>
            <div className="flex items-center gap-3">
              <button
                className="btn-ghost text-xs"
                onClick={handleMoodleTest}
                disabled={testingMoodle || !form.moodle_url || !form.moodle_token}
              >
                {testingMoodle ? "Testing…" : "Test connection"}
              </button>
              <button
                className="btn-ghost text-xs"
                onClick={async () => {
                  setLoadingMoodleDebug(true);
                  setMoodleDebug(null);
                  try {
                    const result = await invoke<string>("debug_moodle");
                    setMoodleDebug(result);
                  } catch (e) {
                    setMoodleDebug(String(e));
                  } finally {
                    setLoadingMoodleDebug(false);
                  }
                }}
                disabled={loadingMoodleDebug}
              >
                {loadingMoodleDebug ? "Checking…" : "Debug sync"}
              </button>
              {moodleResult && (
                <span
                  className={`text-xs ${
                    moodleResult === "Connected." ? "text-urgency-low" : "text-urgency-high"
                  }`}
                >
                  {moodleResult}
                </span>
              )}
            </div>
            {moodleDebug && (
              <pre className="text-[10px] font-mono text-text-dim bg-surface-2 rounded p-2 overflow-x-auto whitespace-pre-wrap break-all">
                {moodleDebug}
              </pre>
            )}
          </div>
        </SubPanel>
      )}

      {/* ── Theme sub-panel ──────────────────────────────────────────────── */}
      {activeSubPanel === "theme" && (
        <SubPanel title="Theme" onClose={closeSubPanel}>
          <div className="flex flex-col gap-4">
            <div className="flex justify-end">
              <button
                className="text-[11px] text-text-dim hover:text-text"
                onClick={handleResetColors}
              >
                Reset to defaults
              </button>
            </div>

            {/* Color groups */}
            <div className="flex flex-col gap-4">
              {cadenColorGroups.map(
                (group: { name: string; description: string; keys: string[]; labels: string[] }) => (
                  <div key={group.name}>
                    <div className="flex items-center gap-2 mb-1.5">
                      <span className="text-xs text-text-muted font-medium">{group.name}</span>
                      <span className="text-[10px] text-text-dim">— {group.description}</span>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {group.keys.map((key: string, i: number) => (
                        <label
                          key={key}
                          className="flex items-center gap-1.5 cursor-pointer group/swatch"
                        >
                          <input
                            type="color"
                            value={themeColors[key] || defaults[key]}
                            onChange={(e) => handleColorChange(key, e.target.value)}
                            className="w-6 h-6 rounded border border-surface-3 cursor-pointer p-0 bg-transparent [&::-webkit-color-swatch-wrapper]:p-0.5 [&::-webkit-color-swatch]:rounded"
                          />
                          <span className="text-[10px] text-text-dim group-hover/swatch:text-text transition-colors">
                            {group.labels[i]}
                          </span>
                        </label>
                      ))}
                    </div>
                  </div>
                )
              )}
            </div>

            {/* Live preview */}
            <div className="rounded border border-surface-3 overflow-hidden">
              <div className="text-[10px] font-mono uppercase tracking-widest text-text-dim px-2 py-1 border-b border-surface-3">
                Preview
              </div>
              <div className="flex h-24" style={{ backgroundColor: themeColors["--c-surface"] }}>
                <div
                  className="flex-1 p-2 border-r"
                  style={{
                    backgroundColor: themeColors["--c-surface-1"],
                    borderColor: themeColors["--c-surface-2"],
                  }}
                >
                  <div
                    className="text-[8px] font-mono uppercase mb-1"
                    style={{ color: themeColors["--c-text-dim"] }}
                  >
                    Today
                  </div>
                  <div className="flex items-center gap-1 mb-1">
                    <span
                      className="w-1 h-1 rounded-full"
                      style={{ backgroundColor: themeColors["--c-urgency-high"] }}
                    />
                    <span className="text-[8px] truncate" style={{ color: themeColors["--c-text"] }}>
                      Assignment due
                    </span>
                  </div>
                  <div className="flex items-center gap-1 mb-1">
                    <span
                      className="w-1 h-1 rounded-full"
                      style={{ backgroundColor: themeColors["--c-urgency-med"] }}
                    />
                    <span className="text-[8px] truncate" style={{ color: themeColors["--c-text"] }}>
                      Study session
                    </span>
                  </div>
                  <div className="flex items-center gap-1">
                    <span
                      className="w-1 h-1 rounded-full"
                      style={{ backgroundColor: themeColors["--c-urgency-low"] }}
                    />
                    <span
                      className="text-[8px] truncate"
                      style={{ color: themeColors["--c-text-muted"] }}
                    >
                      Free time
                    </span>
                  </div>
                </div>
                <div
                  className="flex-[2] p-2"
                  style={{ backgroundColor: themeColors["--c-surface"] }}
                >
                  <div
                    className="text-[8px] font-mono uppercase mb-1"
                    style={{ color: themeColors["--c-text-dim"] }}
                  >
                    Chat
                  </div>
                  <div className="text-[8px] mb-1" style={{ color: themeColors["--c-text"] }}>
                    What should I work on?
                  </div>
                  <div className="text-[8px]" style={{ color: themeColors["--c-accent"] }}>
                    Start with your bio homework.
                  </div>
                </div>
                <div
                  className="flex-1 p-2 border-l"
                  style={{
                    backgroundColor: themeColors["--c-surface-1"],
                    borderColor: themeColors["--c-surface-2"],
                  }}
                >
                  <div
                    className="text-[8px] font-mono uppercase mb-1"
                    style={{ color: themeColors["--c-text-dim"] }}
                  >
                    Next 7 days
                  </div>
                  <div className="text-[8px] mb-0.5" style={{ color: themeColors["--c-text-muted"] }}>
                    Lab report
                  </div>
                  <div className="text-[8px] mb-0.5" style={{ color: themeColors["--c-text-muted"] }}>
                    Quiz prep
                  </div>
                  <div
                    className="rounded px-1 py-0.5 text-[7px] inline-block mt-1"
                    style={{
                      backgroundColor: themeColors["--c-accent-muted"],
                      color: themeColors["--c-accent"],
                    }}
                  >
                    Task
                  </div>
                </div>
              </div>
            </div>
          </div>
        </SubPanel>
      )}

      {/* ── Medications sub-panel ─────────────────────────────────────── */}
      {activeSubPanel === "medications" && (
        <SubPanel title="Medications" onClose={closeSubPanel}>
          <MedGroupEditor
            label="Morning Meds"
            description='Logged when you say “took my morning meds”'
            entries={form.morning_meds ?? []}
            onChange={(entries) => setForm((f) => ({ ...f, morning_meds: entries }))}
          />
          <div className="mt-5 pt-4 border-t border-surface-2/60">
            <MedGroupEditor
              label="Evening Meds"
              description='Logged when you say “took my evening meds”'
              entries={form.evening_meds ?? []}
              onChange={(entries) => setForm((f) => ({ ...f, evening_meds: entries }))}
            />
          </div>
          <p className="mt-4 text-[10px] text-text-dim leading-relaxed">
            CADEN logs each med individually when you report taking a group.
            PK peak/trough calculations use each medication’s own stats, not the group label.
          </p>
        </SubPanel>
      )}

      {/* ── Plugins sub-panel ────────────────────────────────────────────── */}
      {activeSubPanel === "plugins" && plugins.length > 0 && (
        <SubPanel title="Plugin Apps" onClose={closeSubPanel}>
          <div className="flex flex-col gap-1.5">
            {plugins.map((plugin) => (
              <div
                key={plugin.id}
                className="flex items-center justify-between gap-3 py-2 border-b border-surface-2/50"
              >
                <div className="min-w-0">
                  <div className="text-xs text-text-muted font-medium truncate">
                    {plugin.name}
                  </div>
                  <div className="text-[10px] text-text-dim font-mono truncate">
                    {plugin.folder_path}
                  </div>
                </div>
                <button
                  onClick={() => onPluginRemoved(plugin.id)}
                  className="text-[11px] text-text-dim hover:text-urgency-high transition-colors flex-shrink-0"
                >
                  Disconnect
                </button>
              </div>
            ))}
          </div>
        </SubPanel>
      )}
    </>
  );
}
