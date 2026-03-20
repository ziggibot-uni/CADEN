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
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UpcomingItem {
    pub id: String,
    pub title: String,
    pub source: String,
    pub due_date: Option<String>,
    pub urgency_score: f64,
    pub course_name: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AppSettings {
    pub google_connected: bool,
    pub moodle_url: Option<String>,
    pub moodle_token: Option<String>,
    pub ollama_model: String,
    pub system_prompt: String,
    pub task_duration_minutes: i64,
    pub setup_complete: bool,
}

impl Default for AppSettings {
    fn default() -> Self {
        Self {
            google_connected: false,
            moodle_url: None,
            moodle_token: None,
            ollama_model: "llama3.1:8b".to_string(),
            system_prompt: crate::ollama::DEFAULT_SYSTEM_PROMPT.to_string(),
            task_duration_minutes: 45,
            setup_complete: false,
        }
    }
}
