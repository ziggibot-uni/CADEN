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
  scheduled_start: string | null; // ISO
  scheduled_end: string | null;   // ISO
  urgency_score: number;
  completed: boolean;
  completed_at: string | null;
}

// ─── Upcoming items ─────────────────────────────────────────────────────────
export interface UpcomingItem {
  id: string;
  title: string;
  source: TaskSource;
  due_date: string | null; // ISO
  urgency_score: number;
  course_name: string | null;
}

// ─── Chat ────────────────────────────────────────────────────────────────────
export type MessageRole = "user" | "assistant";

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  timestamp: string;
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
}

export interface AppSettings {
  google_connected: boolean;
  moodle_url: string | null;
  moodle_token: string | null;
  ollama_model: string;
  system_prompt: string;
  task_duration_minutes: number;
  setup_complete: boolean;
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

// ─── Planner context (sent to Ollama) ────────────────────────────────────────
export interface PlannerContext {
  date: string;
  plan_items: PlanItem[];
  upcoming_deadlines: UpcomingItem[];
  recent_completions: PlanItem[];
}
