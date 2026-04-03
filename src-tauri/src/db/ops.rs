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
            "active_model" | "ollama_model" => {
                // Support legacy "ollama_model" key from old databases
                if let Some(v) = v {
                    s.active_model = v;
                }
            }
            "github_pat" => {
                if let Some(v) = v {
                    s.github_pat = v;
                }
            }
            "groq_keys" => {
                if let Some(v) = v {
                    s.groq_keys = serde_json::from_str(&v).unwrap_or_default();
                }
            }
            "openrouter_key" => {
                if let Some(v) = v {
                    s.openrouter_key = v;
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
            "creative_time_minutes" => {
                if let Some(v) = v {
                    s.creative_time_minutes = v.parse().unwrap_or(120);
                }
            }
            "font_scale" => {
                if let Some(v) = v {
                    s.font_scale = v.parse().unwrap_or(1.0);
                }
            }
            "contrast" => {
                if let Some(v) = v {
                    s.contrast = v.parse().unwrap_or(1.0);
                }
            }
            "setup_complete" => s.setup_complete = v.as_deref() == Some("true"),
            "work_hours" => {
                if let Some(v) = v {
                    if let Ok(wh) = serde_json::from_str(&v) {
                        s.work_hours = wh;
                    }
                }
            }
            "morning_meds" => {
                if let Some(v) = v {
                    if let Ok(m) = serde_json::from_str(&v) {
                        s.morning_meds = m;
                    }
                }
            }
            "evening_meds" => {
                if let Some(v) = v {
                    if let Ok(m) = serde_json::from_str(&v) {
                        s.evening_meds = m;
                    }
                }
            }
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
    set_setting(pool, "active_model", &settings.active_model).await?;
    set_setting(pool, "github_pat", &settings.github_pat).await?;
    if let Ok(j) = serde_json::to_string(&settings.groq_keys) {
        set_setting(pool, "groq_keys", &j).await?;
    }
    set_setting(pool, "openrouter_key", &settings.openrouter_key).await?;
    set_setting(pool, "system_prompt", &settings.system_prompt).await?;
    set_setting(
        pool,
        "task_duration_minutes",
        &settings.task_duration_minutes.to_string(),
    )
    .await?;
    set_setting(
        pool,
        "creative_time_minutes",
        &settings.creative_time_minutes.to_string(),
    )
    .await?;
    set_setting(pool, "font_scale", &settings.font_scale.to_string()).await?;
    set_setting(pool, "contrast", &settings.contrast.to_string()).await?;
    set_setting(pool, "setup_complete", &settings.setup_complete.to_string()).await?;
    if let Ok(wh_json) = serde_json::to_string(&settings.work_hours) {
        set_setting(pool, "work_hours", &wh_json).await?;
    }
    if let Ok(j) = serde_json::to_string(&settings.morning_meds) {
        set_setting(pool, "morning_meds", &j).await?;
    }
    if let Ok(j) = serde_json::to_string(&settings.evening_meds) {
        set_setting(pool, "evening_meds", &j).await?;
    }
    Ok(())
}

// ─── User corrections ─────────────────────────────────────────────────────────

/// Immediately record a skip for a plan item, updating pattern and circadian models.
/// Call this when Sean explicitly says he's not doing something. Separate from the
/// overnight batch skip detection which catches things he just didn't do.
pub async fn skip_plan_item(pool: &SqlitePool, plan_id: &str) -> Result<()> {
    use chrono::Utc;

    let now = Utc::now().to_rfc3339();

    // Fetch plan item details
    let item: Option<(String, String, Option<String>)> = sqlx::query_as(
        "SELECT task_id, source, scheduled_start FROM daily_plans WHERE id = ?",
    )
    .bind(plan_id)
    .fetch_optional(pool)
    .await?;

    let Some((task_id, source, scheduled_start)) = item else {
        return Ok(());
    };

    // Look up task type for pattern update
    let task_info: Option<(String, Option<String>)> = sqlx::query_as(
        "SELECT source, course_name FROM tasks_cache WHERE id = ?",
    )
    .bind(&task_id)
    .fetch_optional(pool)
    .await
    .unwrap_or(None);

    let (src, course) = task_info.unwrap_or_else(|| (source.clone(), None));
    let task_type = if src == "moodle" {
        course.as_deref().unwrap_or("moodle").to_string()
    } else {
        src.clone()
    };

    let time_of_day = scheduled_start
        .as_deref()
        .map(crate::planner::time_of_day_from_iso)
        .unwrap_or("morning");

    // Record in skips table (ignore if already skipped)
    sqlx::query(
        "INSERT OR IGNORE INTO skips (id, task_id, source, reason, timestamp) VALUES (?, ?, ?, 'explicit_skip', ?)",
    )
    .bind(generate_id())
    .bind(&task_id)
    .bind(&source)
    .bind(&now)
    .execute(pool)
    .await
    .ok();

    // Update pattern and circadian models immediately
    crate::planner::update_patterns(pool, &task_type, time_of_day, false, 0.0)
        .await
        .ok();
    crate::sean_model::circadian::record_event(pool, false).await;

    Ok(())
}

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

#[derive(sqlx::FromRow)]
struct PlanRow {
    id: String,
    task_id: String,
    title: String,
    source: String,
    scheduled_start: Option<String>,
    scheduled_end: Option<String>,
    urgency_score: f64,
    completed: bool,
    completed_at: Option<String>,
    url: Option<String>,
    google_task_id: Option<String>,
    cal_event_id: Option<String>,
    due_date: Option<String>,
    linked_project_id: Option<String>,
    linked_project_name: Option<String>,
}

/// Ensures every task that is due today or overdue has a row in `daily_plans`
/// so it appears in the Today panel without requiring a full sync.
/// Tasks due in the future stay in the Upcoming panel only.
async fn ensure_today_tasks_in_plan(pool: &SqlitePool) -> Result<()> {
    use chrono::{Local, Utc};

    let today = Local::now().format("%Y-%m-%d").to_string();
    let now_str = Utc::now().to_rfc3339();

    // Only fetch tasks due today or overdue (date <= today in local time)
    let candidates: Vec<(String, String, String, Option<String>)> = sqlx::query_as(
        "SELECT id, title, source, due_date FROM tasks_cache
         WHERE completed = 0
           AND (due_date IS NULL OR date(due_date) <= date('now', 'localtime'))
           AND id NOT IN (
               SELECT task_id FROM dismissed_tasks
               WHERE dismiss_date = date('now', 'localtime')
           )",
    )
    .fetch_all(pool)
    .await?;

    for (id, title, source, due_date) in candidates {
        // Skip if already in today's plan
        let exists: Option<(String,)> = sqlx::query_as(
            "SELECT id FROM daily_plans WHERE task_id = ? AND date = ? LIMIT 1",
        )
        .bind(&id)
        .bind(&today)
        .fetch_optional(pool)
        .await?;
        if exists.is_some() {
            continue;
        }

        let score = crate::planner::compute_urgency_score(due_date.as_deref(), 3.0, 0.0);
        sqlx::query(
            "INSERT OR IGNORE INTO daily_plans
             (id, date, task_id, source, title, scheduled_start, scheduled_end,
              urgency_score, effort_weight, completed, created_at, google_task_id)
             VALUES (?, ?, ?, ?, ?, NULL, NULL, ?, 3.0, 0, ?, NULL)",
        )
        .bind(generate_id())
        .bind(&today)
        .bind(&id)
        .bind(&source)
        .bind(&title)
        .bind(score)
        .bind(&now_str)
        .execute(pool)
        .await?;
    }

    Ok(())
}

pub async fn get_today_plan(pool: &SqlitePool) -> Result<Vec<PlanItem>> {
    // Ensure all tasks due today are visible without requiring a full sync
    ensure_today_tasks_in_plan(pool).await.ok();

    let today = chrono::Local::now().format("%Y-%m-%d").to_string();
    let rows: Vec<PlanRow> = sqlx::query_as(
        "SELECT dp.id, dp.task_id, dp.title, dp.source,
                dp.scheduled_start, dp.scheduled_end, dp.urgency_score,
                dp.completed, dp.completed_at, dp.google_task_id, tc.url,
                dp.cal_event_id, tc.due_date,
                COALESCE(dp.linked_project_id, tc.linked_project_id) AS linked_project_id,
                p.name AS linked_project_name
         FROM daily_plans dp
         LEFT JOIN tasks_cache tc ON dp.task_id = tc.id
         LEFT JOIN projects p ON COALESCE(dp.linked_project_id, tc.linked_project_id) = p.id
         WHERE dp.date = ?
         ORDER BY dp.scheduled_start ASC NULLS LAST",
    )
    .bind(&today)
    .fetch_all(pool)
    .await?;

    let mut items: Vec<PlanItem> = rows
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
            url: r.url,
            google_task_id: r.google_task_id,
            cal_event_id: r.cal_event_id,
            due_date: r.due_date,
            linked_project_id: r.linked_project_id,
            linked_project_name: r.linked_project_name,
        })
        .collect();

    // Fallback: look up linked projects for items with google_task_ids that have no direct link
    for item in &mut items {
        if item.linked_project_id.is_some() { continue; }
        if let Some(ref gtid) = item.google_task_id {
            let link: Option<(String, String)> = sqlx::query_as(
                "SELECT p.id, p.name FROM project_entries pe
                 JOIN projects p ON pe.project_id = p.id
                 WHERE pe.google_task_id = ? LIMIT 1",
            )
            .bind(gtid)
            .fetch_optional(pool)
            .await
            .ok()
            .flatten();
            if let Some((pid, pname)) = link {
                item.linked_project_id = Some(pid);
                item.linked_project_name = Some(pname);
            }
        }
    }

    // Include today's calendar events from events_cache, excluding any the user dismissed
    let date_prefix = format!("{}%", today);
    let events: Vec<(String, String, String, String)> = sqlx::query_as(
        "SELECT id, title, start_time, end_time FROM events_cache
         WHERE start_time LIKE ?
         ORDER BY start_time ASC",
    )
    .bind(&date_prefix)
    .fetch_all(pool)
    .await?;

    for (id, title, start_time, end_time) in events {
        items.push(PlanItem {
            id: id.clone(),
            task_id: id,
            title,
            source: "calendar".to_string(),
            scheduled_start: Some(start_time),
            scheduled_end: Some(end_time),
            urgency_score: 0.0,
            completed: false,
            completed_at: None,
            url: None,
            google_task_id: None,
            cal_event_id: None,
            due_date: None,
            linked_project_id: None,
            linked_project_name: None,
        });
    }

    // Re-sort everything by scheduled_start
    items.sort_by(|a, b| {
        a.scheduled_start.cmp(&b.scheduled_start)
    });

    Ok(items)
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

        // Mark the source task as completed so the planner won't re-add it on next sync
        sqlx::query("UPDATE tasks_cache SET completed = 1 WHERE id = ?")
            .bind(&item.task_id)
            .execute(pool)
            .await?;

        // Cross-mark linked tasks so the same real-world assignment doesn't reappear
        // from a different source after sync.

        // Case 1: this task (e.g. Moodle) has a google_task_id pointing to a Google Task row
        let linked_id: Option<String> = sqlx::query_as::<_, (Option<String>,)>(
            "SELECT google_task_id FROM tasks_cache WHERE id = ?",
        )
        .bind(&item.task_id)
        .fetch_optional(pool)
        .await
        .ok()
        .flatten()
        .and_then(|(id,)| id);

        if let Some(ref gid) = linked_id {
            sqlx::query("UPDATE tasks_cache SET completed = 1 WHERE id = ?")
                .bind(gid)
                .execute(pool)
                .await
                .ok();
            sqlx::query(
                "UPDATE daily_plans SET completed = 1, completed_at = ? \
                 WHERE task_id = ? AND date = ? AND completed = 0",
            )
            .bind(&now)
            .bind(gid)
            .bind(&item.date)
            .execute(pool)
            .await
            .ok();
        }

        // Case 2: this task (e.g. a Google Task) is linked to by one or more Moodle tasks
        sqlx::query("UPDATE tasks_cache SET completed = 1 WHERE google_task_id = ?")
            .bind(&item.task_id)
            .execute(pool)
            .await
            .ok();
        sqlx::query(
            "UPDATE daily_plans SET completed = 1, completed_at = ? \
             WHERE date = ? AND completed = 0 \
               AND task_id IN (SELECT id FROM tasks_cache WHERE google_task_id = ?)",
        )
        .bind(&now)
        .bind(&item.date)
        .bind(&item.task_id)
        .execute(pool)
        .await
        .ok();

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

        // Update pattern statistics
        let task_info: Option<(String, Option<String>)> = sqlx::query_as(
            "SELECT source, course_name FROM tasks_cache WHERE id = ?",
        )
        .bind(&item.task_id)
        .fetch_optional(pool)
        .await
        .unwrap_or(None);

        let (src, course) = task_info.unwrap_or_else(|| (item.source.clone(), None));
        let task_type = if src == "moodle" {
            course.as_deref().unwrap_or("moodle").to_string()
        } else {
            src.clone()
        };

        let time_of_day = item.scheduled_start
            .as_deref()
            .map(crate::planner::time_of_day_from_iso)
            .unwrap_or("morning");

        // Compute delay: how many minutes after the scheduled start did they actually complete?
        let delay_minutes = match &item.scheduled_start {
            Some(start) => {
                let planned = chrono::DateTime::parse_from_rfc3339(start)
                    .map(|d| d.with_timezone(&Utc))
                    .unwrap_or_else(|_| Utc::now());
                let actual = chrono::DateTime::parse_from_rfc3339(&now)
                    .map(|d| d.with_timezone(&Utc))
                    .unwrap_or_else(|_| Utc::now());
                let diff = (actual - planned).num_minutes() as f64;
                diff.max(0.0) // negative = early; treat as 0 delay
            }
            None => 0.0,
        };

        crate::planner::update_patterns(pool, &task_type, time_of_day, true, delay_minutes)
            .await
            .ok();

        // Update the Sean Model circadian grid — record this as a completion event
        crate::sean_model::circadian::record_event(pool, true).await;
    }

    Ok(())
}

pub async fn get_upcoming_items(pool: &SqlitePool) -> Result<Vec<UpcomingItem>> {
    let now = Utc::now().to_rfc3339();
    let week = (Utc::now() + chrono::Duration::days(7)).to_rfc3339();
    let far = (Utc::now() + chrono::Duration::days(60)).to_rfc3339();

    let yesterday = (Utc::now() - chrono::Duration::days(1)).to_rfc3339();

    let rows: Vec<(String, String, String, Option<String>, Option<String>, Option<String>, Option<String>, Option<String>, Option<String>)> =
        sqlx::query_as(
            "SELECT tc.id, tc.title, tc.source, tc.due_date, tc.course_name, tc.url, tc.google_task_id,
                    tc.linked_project_id, p.name
             FROM tasks_cache tc
             LEFT JOIN projects p ON tc.linked_project_id = p.id
             WHERE tc.completed = 0
               AND (tc.due_date IS NULL OR (tc.due_date >= ? AND tc.due_date <= ?))
             ORDER BY tc.due_date ASC NULLS LAST
             LIMIT 100",
        )
        .bind(&yesterday)
        .bind(&far)
        .fetch_all(pool)
        .await?;

    let mut items: Vec<UpcomingItem> = rows
        .into_iter()
        .map(|(id, title, source, due_date, course_name, url, google_task_id, linked_project_id, linked_project_name)| {
            let urgency_score = crate::planner::compute_urgency_score(
                due_date.as_deref(),
                3.0,
                0.0,
            );
            UpcomingItem {
                id,
                title,
                source,
                due_date,
                urgency_score,
                course_name,
                url,
                google_task_id,
                linked_project_id,
                linked_project_name,
            }
        })
        .collect();

    // Include upcoming calendar events from events_cache
    let events: Vec<(String, String, String, String)> = sqlx::query_as(
        "SELECT id, title, start_time, calendar_name FROM events_cache
         WHERE start_time >= ? AND start_time <= ?
         ORDER BY start_time ASC",
    )
    .bind(&now)
    .bind(&week)
    .fetch_all(pool)
    .await?;

    for (id, title, start_time, calendar_name) in events {
        let urgency_score =
            crate::planner::compute_urgency_score(Some(&start_time), 1.0, 0.0);
        items.push(UpcomingItem {
            id,
            title,
            source: "calendar".to_string(),
            due_date: Some(start_time),
            urgency_score,
            course_name: Some(calendar_name),
            url: None,
            google_task_id: None,
            linked_project_id: None,
            linked_project_name: None,
        });
    }

    items.sort_by(|a, b| a.due_date.cmp(&b.due_date));

    Ok(items)
}

pub async fn unmark_plan_item_complete(pool: &SqlitePool, plan_id: &str) -> Result<Option<(String, String)>> {
    // Returns (source, task_id) so the caller can undo the Google API call
    let row: Option<(String, String)> =
        sqlx::query_as("SELECT source, task_id FROM daily_plans WHERE id = ?")
            .bind(plan_id)
            .fetch_optional(pool)
            .await?;

    if let Some((ref source, ref task_id)) = row {
        sqlx::query("UPDATE daily_plans SET completed = 0, completed_at = NULL WHERE id = ?")
            .bind(plan_id)
            .execute(pool)
            .await?;

        sqlx::query("UPDATE tasks_cache SET completed = 0 WHERE id = ?")
            .bind(task_id)
            .execute(pool)
            .await?;

        // Remove from completions log
        sqlx::query("DELETE FROM completions WHERE task_id = ? AND source = ?")
            .bind(task_id)
            .bind(source)
            .execute(pool)
            .await?;
    }

    Ok(row)
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
