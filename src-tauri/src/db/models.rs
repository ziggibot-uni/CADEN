use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize, sqlx::FromRow)]
pub struct EventsCache {
    pub id: String,
    pub title: String,
    pub start_time: String,
    pub end_time: String,
    pub all_day: bool,
    pub calendar_name: String,
    pub fetched_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, sqlx::FromRow)]
pub struct TasksCache {
    pub id: String,
    pub title: String,
    pub source: String,
    pub due_date: Option<String>,
    pub completed: bool,
    pub notes: Option<String>,
    pub list_name: Option<String>,
    pub course_name: Option<String>,
    pub fetched_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, sqlx::FromRow)]
pub struct DailyPlan {
    pub id: String,
    pub date: String,
    pub task_id: String,
    pub source: String,
    pub title: String,
    pub scheduled_start: Option<String>,
    pub scheduled_end: Option<String>,
    pub urgency_score: f64,
    pub effort_weight: f64,
    pub completed: bool,
    pub completed_at: Option<String>,
    pub created_at: String,
    pub google_task_id: Option<String>,
    pub cal_event_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, sqlx::FromRow)]
pub struct Completion {
    pub id: String,
    pub task_id: String,
    pub source: String,
    pub planned_time: Option<String>,
    pub actual_time: String,
    pub plan_date: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, sqlx::FromRow)]
pub struct Skip {
    pub id: String,
    pub task_id: String,
    pub source: String,
    pub reason: Option<String>,
    pub timestamp: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, sqlx::FromRow)]
pub struct Pattern {
    pub id: String,
    pub task_type: String,
    pub time_of_day: String,
    pub completion_rate: f64,
    pub avg_delay_minutes: f64,
    pub sample_count: i64,
    pub last_updated: String,
}

// ─── Frontend-facing types ───────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PlanItem {
    pub id: String,
    pub task_id: String,
    pub title: String,
    pub source: String,
    pub scheduled_start: Option<String>,
    pub scheduled_end: Option<String>,
    pub urgency_score: f64,
    pub completed: bool,
    pub completed_at: Option<String>,
    pub url: Option<String>,
    pub google_task_id: Option<String>,
    pub cal_event_id: Option<String>,
    pub due_date: Option<String>,
    pub linked_project_id: Option<String>,
    pub linked_project_name: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UpcomingItem {
    pub id: String,
    pub title: String,
    pub source: String,
    pub due_date: Option<String>,
    pub urgency_score: f64,
    pub course_name: Option<String>,
    pub url: Option<String>,
    pub google_task_id: Option<String>,
    pub linked_project_id: Option<String>,
    pub linked_project_name: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DayHours {
    /// Hour of day (0–23) to start scheduling.
    pub start: u32,
    /// Hour of day (0–23) to stop scheduling.
    pub end: u32,
}

/// Per-weekday work-hour windows. `None` means that day is a rest day.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WorkHours {
    pub mon: Option<DayHours>,
    pub tue: Option<DayHours>,
    pub wed: Option<DayHours>,
    pub thu: Option<DayHours>,
    pub fri: Option<DayHours>,
    pub sat: Option<DayHours>,
    pub sun: Option<DayHours>,
}

impl Default for WorkHours {
    fn default() -> Self {
        let day = || Some(DayHours { start: 8, end: 22 });
        Self {
            mon: day(),
            tue: day(),
            wed: day(),
            thu: day(),
            fri: day(),
            sat: None,
            sun: None,
        }
    }
}

impl WorkHours {
    /// Return the (start, end) hours for a given chrono Weekday, or None if it is a rest day.
    pub fn for_weekday(&self, wd: chrono::Weekday) -> Option<(u32, u32)> {
        use chrono::Weekday::*;
        let hours = match wd {
            Mon => &self.mon,
            Tue => &self.tue,
            Wed => &self.wed,
            Thu => &self.thu,
            Fri => &self.fri,
            Sat => &self.sat,
            Sun => &self.sun,
        };
        hours.as_ref().map(|h| (h.start, h.end))
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MedGroupEntry {
    pub name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub dose_mg: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AppSettings {
    pub google_connected: bool,
    pub moodle_url: Option<String>,
    pub moodle_token: Option<String>,
    /// The selected model. GitHub models use "provider/name" (e.g. "openai/gpt-4.1").
    /// Ollama models use the plain name (e.g. "qwen3:14b").
    pub active_model: String,
    pub github_pat: String,
    /// Up to 4 Groq API keys — rotated round-robin for background LLM calls.
    pub groq_keys: Vec<String>,
    /// OpenRouter API key — primary provider for VibeCoder coder/planner/critic.
    pub openrouter_key: String,
    pub system_prompt: String,
    pub task_duration_minutes: i64,
    /// Minutes of unscheduled free time to protect each day for creative work.
    pub creative_time_minutes: i64,
    pub font_scale: f64,
    pub contrast: f64,
    pub setup_complete: bool,
    /// Per-day work-hour windows used by the planner.
    pub work_hours: WorkHours,
    /// Morning medication group — logged all at once when user says "took my morning meds"
    pub morning_meds: Vec<MedGroupEntry>,
    /// Evening medication group
    pub evening_meds: Vec<MedGroupEntry>,
}

impl Default for AppSettings {
    fn default() -> Self {
        Self {
            google_connected: false,
            moodle_url: None,
            moodle_token: None,
            active_model: "qwen3:14b".to_string(),
            github_pat: String::new(),
            groq_keys: Vec::new(),
            openrouter_key: String::new(),
            system_prompt: crate::ollama::DEFAULT_SYSTEM_PROMPT.to_string(),
            task_duration_minutes: 45,
            creative_time_minutes: 120,
            font_scale: 1.0,
            contrast: 1.0,
            setup_complete: false,
            work_hours: WorkHours::default(),
            morning_meds: Vec::new(),
            evening_meds: Vec::new(),
        }
    }
}
