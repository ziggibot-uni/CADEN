// ─── Source tags ────────────────────────────────────────────────────────────
export type TaskSource = "calendar" | "tasks" | "moodle";

// ─── Urgency ────────────────────────────────────────────────────────────────
export type UrgencyLevel = "high" | "med" | "low";

export function urgencyFromScore(score: number): UrgencyLevel {
  if (score >= 70) return "high";
  if (score >= 35) return "med";
  return "low";
}

// ─── Plan items ─────────────────────────────────────────────────────────────
export interface PlanItem {
  id: string;
  task_id: string;
  title: string;
  source: TaskSource;
  scheduled_start: string | null; // ISO — when CADEN schedules you to *do* this
  scheduled_end: string | null;   // ISO
  due_date: string | null;        // ISO — when the task is actually *due*
  urgency_score: number;
  completed: boolean;
  completed_at: string | null;
  url: string | null;
  google_task_id: string | null;
  cal_event_id: string | null;    // set when a GCal time block exists
  linked_project_id: string | null;
  linked_project_name: string | null;
}

// ─── Upcoming items ─────────────────────────────────────────────────────────
export interface UpcomingItem {
  id: string;
  title: string;
  source: TaskSource;
  due_date: string | null; // ISO
  urgency_score: number;
  course_name: string | null;
  url: string | null;
  google_task_id: string | null;
  linked_project_id: string | null;
  linked_project_name: string | null;
}

// ─── Chat ────────────────────────────────────────────────────────────────────
export type MessageRole = "user" | "assistant";

export interface TraceData {
  model: string;
  intent: string;
  one_line: string;
  needs_project_context: boolean;
  needs_schedule_context: boolean;
  classification_raw: string;
  analysis: string;
  situational_briefing: string;
  project_context: string;
  date: string;
  plan_items: unknown[];
  upcoming_deadlines: unknown[];
}

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  thinking?: string;
  trace?: TraceData;
  timestamp: string;
  logs?: LogEntry[];
  activity?: ActivityItem[];
}

export interface LogEntry {
  label: string;
  data?: string;
  done: boolean;
  skipped?: boolean;
}

export interface ActivityItem {
  kind: "phase" | "log" | "trace";
  label: string;
  detail?: string;
  status: "running" | "done" | "skipped";
}

// ─── App state ───────────────────────────────────────────────────────────────
export interface OllamaStatus {
  online: boolean;
  model: string | null;
  checking: boolean;
}

export interface SyncStatus {
  last_sync: string | null;
  syncing: boolean;
  gcal_error: string | null;
}

export interface SyncOutcome {
  replanned: boolean;
  events_changed: boolean;
  gcal_error: string | null;
}

export interface DayHours {
  start: number; // 0–23
  end: number;   // 0–23
}

export interface WorkHours {
  mon: DayHours | null;
  tue: DayHours | null;
  wed: DayHours | null;
  thu: DayHours | null;
  fri: DayHours | null;
  sat: DayHours | null;
  sun: DayHours | null;
}

export interface AppSettings {
  google_connected: boolean;
  moodle_url: string | null;
  moodle_token: string | null;
  /** Selected model. GitHub models contain "/" (e.g. "openai/gpt-4.1"). Ollama models don't. */
  active_model: string;
  github_pat: string;
  /** Up to 4 Groq API keys — rotated round-robin for background calls. */
  groq_keys: string[];
  /** OpenRouter API key — primary provider for coder/planner/critic. */
  openrouter_key: string;
  system_prompt: string;
  task_duration_minutes: number;
  /** Minutes of free time to keep unscheduled each day for creative work. */
  creative_time_minutes: number;
  font_scale: number;
  contrast: number;
  setup_complete: boolean;
  work_hours: WorkHours;
  morning_meds: MedGroupEntry[];
  evening_meds: MedGroupEntry[];
}

export interface MedGroupEntry {
  name: string;
  dose_mg?: number;
}

// ─── First run wizard steps ──────────────────────────────────────────────────
export type WizardStep =
  | "ollama_check"
  | "ollama_pull"
  | "google_auth"
  | "moodle_setup"
  | "done";

// ─── Google ──────────────────────────────────────────────────────────────────
export interface CalendarEvent {
  id: string;
  title: string;
  start_time: string;
  end_time: string;
  all_day: boolean;
  calendar_name: string;
}

// ─── Moodle ──────────────────────────────────────────────────────────────────
export interface MoodleAssignment {
  id: string;
  title: string;
  course_name: string;
  due_date: string | null;
  submitted: boolean;
  urgency_score: number;
}

// ─── Plugins ─────────────────────────────────────────────────────────────────
export interface Plugin {
  id: string;
  name: string;
  folder_path: string;
  /** Relative path for static plugins; empty for dev-server plugins. */
  entry: string;
  /** Live dev-server URL, e.g. "http://localhost:5173". Null for static plugins. */
  dev_url: string | null;
  sort_order: number;
  created_at: string;
}

// ─── Planner context (sent to Ollama) ────────────────────────────────────────
export interface PlannerContext {
  date: string;
  plan_items: PlanItem[];
  upcoming_deadlines: UpcomingItem[];
  recent_completions: PlanItem[];
}

// ─── Catch-up summary ────────────────────────────────────────────────────────
export interface CatchUpTask {
  id: string;
  title: string;
  source: string;
  due_date: string | null;
  course_name: string | null;
}

export interface CatchUpSummary {
  hours_since_last_sync: number;
  new_moodle_assignments: CatchUpTask[];
  overdue_tasks: CatchUpTask[];
  completed_yesterday: number;
  skipped_yesterday: number;
  current_energy: number | null;
  low_energy_mode: boolean;
  resurfaced_thoughts: string[];
}

// ─── Overdue triage ──────────────────────────────────────────────────────────
export interface TriageAction {
  task_id: string;
  action: "drop" | "defer" | "today";
  defer_to?: string;
}
