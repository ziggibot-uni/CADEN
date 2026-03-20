use anyhow::Result;
use chrono::Utc;
use sqlx::SqlitePool;

use super::models::{AppSettings, DailyPlan, PlanItem, UpcomingItem};
use super::set_setting;

// ─── Settings ────────────────────────────────────────────────────────────────

pub async fn load_settings(pool: &SqlitePool) -> Result<AppSettings> {
    let rows: Vec<(String, Option<String>)> =
        sqlx::query_as("SELECT key, value FROM settings")
            .fetch_all(pool)
            .await?;

    let mut s = AppSettings::default();
    for (k, v) in rows {
        match k.as_str() {
            "google_connected" => s.google_connected = v.as_deref() == Some("true"),
            "moodle_url" => s.moodle_url = v,
            "moodle_token" => s.moodle_token = v,
            "ollama_model" => {
                if let Some(v) = v {
                    s.ollama_model = v;
                }
            }
            "system_prompt" => {
                if let Some(v) = v {
                    s.system_prompt = v;
                }
            }
            "task_duration_minutes" => {
                if let Some(v) = v {
                    s.task_duration_minutes = v.parse().unwrap_or(45);
                }
            }
            "font_scale" => {
                if let Some(v) = v {
                    s.font_scale = v.parse().unwrap_or(1.0);
                }
            }
            "setup_complete" => s.setup_complete = v.as_deref() == Some("true"),
            _ => {}
        }
    }
    Ok(s)
}

pub async fn save_settings(pool: &SqlitePool, settings: &AppSettings) -> Result<()> {
    set_setting(pool, "google_connected", &settings.google_connected.to_string()).await?;
    set_setting(
        pool,
        "moodle_url",
        settings.moodle_url.as_deref().unwrap_or(""),
    )
    .await?;
    set_setting(
        pool,
        "moodle_token",
        settings.moodle_token.as_deref().unwrap_or(""),
    )
    .await?;
    set_setting(pool, "ollama_model", &settings.ollama_model).await?;
    set_setting(pool, "system_prompt", &settings.system_prompt).await?;
    set_setting(
        pool,
        "task_duration_minutes",
        &settings.task_duration_minutes.to_string(),
    )
    .await?;
    set_setting(pool, "font_scale", &settings.font_scale.to_string()).await?;
    set_setting(pool, "setup_complete", &settings.setup_complete.to_string()).await?;
    Ok(())
}

// ─── User corrections ─────────────────────────────────────────────────────────

pub async fn record_correction(
    pool: &SqlitePool,
    correction_type: &str,
    description: &str,
    data: Option<&str>,
) -> Result<()> {
    let now = Utc::now().to_rfc3339();
    sqlx::query(
        "INSERT INTO user_corrections (id, correction_type, description, data, timestamp)
         VALUES (?, ?, ?, ?, ?)",
    )
    .bind(generate_id())
    .bind(correction_type)
    .bind(description)
    .bind(data)
    .bind(&now)
    .execute(pool)
    .await?;
    Ok(())
}

pub async fn get_recent_corrections(pool: &SqlitePool, limit: i64) -> Result<Vec<(String, String, Option<String>)>> {
    let rows: Vec<(String, String, Option<String>)> = sqlx::query_as(
        "SELECT correction_type, description, data FROM user_corrections
         ORDER BY timestamp DESC LIMIT ?",
    )
    .bind(limit)
    .fetch_all(pool)
    .await?;
    Ok(rows)
}

// ─── Plan items ───────────────────────────────────────────────────────────────

pub async fn get_today_plan(pool: &SqlitePool) -> Result<Vec<PlanItem>> {
    let today = chrono::Local::now().format("%Y-%m-%d").to_string();
    let rows: Vec<DailyPlan> =
        sqlx::query_as("SELECT * FROM daily_plans WHERE date = ? ORDER BY scheduled_start ASC NULLS LAST")
            .bind(&today)
            .fetch_all(pool)
            .await?;

    Ok(rows
        .into_iter()
        .map(|r| PlanItem {
            id: r.id,
            task_id: r.task_id,
            title: r.title,
            source: r.source,
            scheduled_start: r.scheduled_start,
            scheduled_end: r.scheduled_end,
            urgency_score: r.urgency_score,
            completed: r.completed,
            completed_at: r.completed_at,
        })
        .collect())
}

pub async fn mark_plan_item_complete(pool: &SqlitePool, plan_id: &str) -> Result<()> {
    let now = Utc::now().to_rfc3339();

    // Fetch plan item details before marking complete
    let item: Option<DailyPlan> =
        sqlx::query_as("SELECT * FROM daily_plans WHERE id = ?")
            .bind(plan_id)
            .fetch_optional(pool)
            .await?;

    if let Some(item) = item {
        // Update plan item
        sqlx::query("UPDATE daily_plans SET completed = 1, completed_at = ? WHERE id = ?")
            .bind(&now)
            .bind(plan_id)
            .execute(pool)
            .await?;

        // Log completion
        sqlx::query(
            "INSERT INTO completions (id, task_id, source, planned_time, actual_time, plan_date)
             VALUES (?, ?, ?, ?, ?, ?)",
        )
        .bind(generate_id())
        .bind(&item.task_id)
        .bind(&item.source)
        .bind(&item.scheduled_start)
        .bind(&now)
        .bind(&item.date)
        .execute(pool)
        .await?;
    }

    Ok(())
}

pub async fn get_upcoming_items(pool: &SqlitePool) -> Result<Vec<UpcomingItem>> {
    let now = Utc::now().to_rfc3339();
    let week = (Utc::now() + chrono::Duration::days(7)).to_rfc3339();

    let rows: Vec<(String, String, String, Option<String>, Option<String>)> =
        sqlx::query_as(
            "SELECT id, title, source, due_date, course_name FROM tasks_cache
             WHERE completed = 0 AND (due_date IS NULL OR (due_date >= ? AND due_date <= ?))
             ORDER BY due_date ASC NULLS LAST
             LIMIT 50",
        )
        .bind(&now)
        .bind(&week)
        .fetch_all(pool)
        .await?;

    Ok(rows
        .into_iter()
        .map(|(id, title, source, due_date, course_name)| {
            let urgency_score = crate::planner::compute_urgency_score(
                due_date.as_deref(),
                3.0, // default effort
                0.0, // no pattern penalty initially
            );
            UpcomingItem {
                id,
                title,
                source,
                due_date,
                urgency_score,
                course_name,
            }
        })
        .collect())
}

pub async fn clear_completed_plan_items(pool: &SqlitePool) -> Result<()> {
    let today = chrono::Local::now().format("%Y-%m-%d").to_string();
    sqlx::query("DELETE FROM daily_plans WHERE date = ? AND completed = 1")
        .bind(&today)
        .execute(pool)
        .await?;
    Ok(())
}

pub fn generate_id() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};
    let t = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    // Add a small random suffix to avoid collisions on fast inserts
    use std::sync::atomic::{AtomicU64, Ordering};
    static COUNTER: AtomicU64 = AtomicU64::new(0);
    let count = COUNTER.fetch_add(1, Ordering::Relaxed);
    format!("{:x}{:x}", t, count)
}
