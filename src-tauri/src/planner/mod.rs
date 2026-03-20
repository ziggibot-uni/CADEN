use anyhow::Result;
use chrono::{DateTime, Local, NaiveDate, NaiveTime, TimeZone, Utc};
use serde::{Deserialize, Serialize};
use sqlx::SqlitePool;

use crate::db::{models::DailyPlan, ops::generate_id};

const WEEK_HOURS: f64 = 168.0;
const MAX_TASK_BLOCK_HOURS: f64 = 3.0;
const BUFFER_MINUTES: i64 = 15;
const BREAK_MINUTES: i64 = 30;
const WORK_DAY_START_HOUR: u32 = 8;
const WORK_DAY_END_HOUR: u32 = 22;

#[derive(Debug, Clone)]
pub struct TaskInput {
    pub id: String,
    pub title: String,
    pub source: String,
    pub due_date: Option<String>,
    pub effort_weight: f64, // 1-5 scale
    pub duration_minutes: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CalendarBlock {
    pub start: DateTime<Utc>,
    pub end: DateTime<Utc>,
}

/// Compute urgency score for a task.
/// Returns 0.0–100.0
pub fn compute_urgency_score(
    due_date: Option<&str>,
    effort_weight: f64,
    pattern_penalty: f64,
) -> f64 {
    let deadline_pressure = match due_date {
        None => 20.0, // no deadline = low base pressure
        Some(iso) => {
            let due = DateTime::parse_from_rfc3339(iso)
                .map(|d| d.with_timezone(&Utc))
                .unwrap_or_else(|_| Utc::now() + chrono::Duration::days(7));

            let hours_until = (due - Utc::now()).num_minutes() as f64 / 60.0;
            let pressure = 100.0 * (1.0 - (hours_until / WEEK_HOURS));
            pressure.clamp(0.0, 100.0)
        }
    };

    // Effort weight: 1-5 → 0-100
    let effort_normalized = ((effort_weight - 1.0) / 4.0) * 100.0;

    let score = (deadline_pressure * 0.5) + (effort_normalized * 0.3) + (pattern_penalty * 0.2);
    score.clamp(0.0, 100.0)
}

/// Get pattern penalty for a task type/time combination from DB.
pub async fn get_pattern_penalty(
    pool: &SqlitePool,
    task_type: &str,
    time_of_day: &str,
) -> f64 {
    let row: Option<(f64, f64, i64)> = sqlx::query_as(
        "SELECT completion_rate, avg_delay_minutes, sample_count
         FROM patterns WHERE task_type = ? AND time_of_day = ?",
    )
    .bind(task_type)
    .bind(time_of_day)
    .fetch_optional(pool)
    .await
    .unwrap_or(None);

    match row {
        Some((completion_rate, avg_delay, sample_count)) if sample_count >= 10 => {
            // Penalty based on low completion rate and high average delay
            let skip_penalty = (1.0 - completion_rate) * 60.0;
            let delay_penalty = (avg_delay / 60.0).min(40.0);
            (skip_penalty + delay_penalty).min(100.0)
        }
        _ => 0.0, // Not enough data yet
    }
}

/// Generate a daily plan for today.
pub async fn generate_daily_plan(
    pool: &SqlitePool,
    task_duration_minutes: i64,
) -> Result<Vec<DailyPlan>> {
    let today_str = Local::now().format("%Y-%m-%d").to_string();

    // Delete existing non-completed plan for today
    sqlx::query("DELETE FROM daily_plans WHERE date = ? AND completed = 0")
        .bind(&today_str)
        .execute(pool)
        .await?;

    // Fetch all pending tasks
    let tasks: Vec<(String, String, String, Option<String>, Option<String>)> = sqlx::query_as(
        "SELECT id, title, source, due_date, course_name FROM tasks_cache WHERE completed = 0",
    )
    .fetch_all(pool)
    .await?;

    if tasks.is_empty() {
        return Ok(vec![]);
    }

    // Fetch today's calendar events for free-time detection
    let today_start = format!("{}T00:00:00Z", today_str);
    let today_end = format!("{}T23:59:59Z", today_str);
    let events: Vec<(String, String)> = sqlx::query_as(
        "SELECT start_time, end_time FROM events_cache
         WHERE start_time >= ? AND start_time <= ?
         ORDER BY start_time ASC",
    )
    .bind(&today_start)
    .bind(&today_end)
    .fetch_all(pool)
    .await?;

    // Build busy blocks from calendar
    let busy_blocks: Vec<CalendarBlock> = events
        .iter()
        .filter_map(|(s, e)| {
            let start = DateTime::parse_from_rfc3339(s)
                .ok()
                .map(|d| d.with_timezone(&Utc))?;
            let end = DateTime::parse_from_rfc3339(e)
                .ok()
                .map(|d| d.with_timezone(&Utc))?;
            Some(CalendarBlock { start, end })
        })
        .collect();

    // Score all tasks
    let mut scored: Vec<(TaskInput, f64)> = Vec::new();
    for (id, title, source, due_date, course_name) in &tasks {
        let task_type = if source == "moodle" {
            course_name.as_deref().unwrap_or("moodle")
        } else {
            source.as_str()
        };

        let pattern_penalty = get_pattern_penalty(pool, task_type, "morning").await;
        let score = compute_urgency_score(due_date.as_deref(), 3.0, pattern_penalty);

        scored.push((
            TaskInput {
                id: id.clone(),
                title: title.clone(),
                source: source.clone(),
                due_date: due_date.clone(),
                effort_weight: 3.0,
                duration_minutes: task_duration_minutes,
            },
            score,
        ));
    }

    // Sort by urgency descending
    scored.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));

    // Build free-time slots
    let free_slots = compute_free_slots(&busy_blocks, &today_str);

    // Assign tasks to free slots
    let plan = assign_tasks_to_slots(scored, free_slots, &today_str);

    // Persist to DB
    for item in &plan {
        sqlx::query(
            "INSERT OR REPLACE INTO daily_plans
             (id, date, task_id, source, title, scheduled_start, scheduled_end,
              urgency_score, effort_weight, completed, completed_at, created_at)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, ?)",
        )
        .bind(&item.id)
        .bind(&item.date)
        .bind(&item.task_id)
        .bind(&item.source)
        .bind(&item.title)
        .bind(&item.scheduled_start)
        .bind(&item.scheduled_end)
        .bind(item.urgency_score)
        .bind(item.effort_weight)
        .bind(&item.created_at)
        .execute(pool)
        .await?;
    }

    Ok(plan)
}

fn compute_free_slots(busy: &[CalendarBlock], date_str: &str) -> Vec<CalendarBlock> {
    let day: NaiveDate = date_str.parse().unwrap_or_else(|_| Local::now().date_naive());

    let work_start = Local
        .from_local_datetime(&day.and_time(
            NaiveTime::from_hms_opt(WORK_DAY_START_HOUR, 0, 0).unwrap(),
        ))
        .single()
        .map(|d| d.with_timezone(&Utc))
        .unwrap_or_else(Utc::now);

    let work_end = Local
        .from_local_datetime(&day.and_time(
            NaiveTime::from_hms_opt(WORK_DAY_END_HOUR, 0, 0).unwrap(),
        ))
        .single()
        .map(|d| d.with_timezone(&Utc))
        .unwrap_or_else(|| Utc::now() + chrono::Duration::hours(14));

    // Start no earlier than now
    let cursor_start = work_start.max(Utc::now());

    let mut slots: Vec<CalendarBlock> = Vec::new();
    let mut cursor = cursor_start;

    let mut sorted_busy = busy.to_vec();
    sorted_busy.sort_by_key(|b| b.start);

    for block in &sorted_busy {
        if block.start > cursor && cursor < work_end {
            let slot_end = block.start.min(work_end);
            if (slot_end - cursor).num_minutes() >= 20 {
                slots.push(CalendarBlock {
                    start: cursor,
                    end: slot_end,
                });
            }
        }
        if block.end > cursor {
            cursor = block.end;
        }
    }

    // Remaining time after all busy blocks
    if cursor < work_end {
        slots.push(CalendarBlock {
            start: cursor,
            end: work_end,
        });
    }

    slots
}

fn assign_tasks_to_slots(
    tasks: Vec<(TaskInput, f64)>,
    mut slots: Vec<CalendarBlock>,
    date_str: &str,
) -> Vec<DailyPlan> {
    let now = Utc::now().to_rfc3339();
    let mut plan: Vec<DailyPlan> = Vec::new();
    let mut task_iter = tasks.into_iter();
    let mut consecutive_work_minutes: i64 = 0;

    'slots: for slot in &mut slots {
        let mut cursor = slot.start;

        loop {
            // Enforce break after 3 hours
            if consecutive_work_minutes >= MAX_TASK_BLOCK_HOURS as i64 * 60 {
                cursor += chrono::Duration::minutes(BREAK_MINUTES);
                consecutive_work_minutes = 0;
            }

            if cursor >= slot.end {
                continue 'slots;
            }

            match task_iter.next() {
                None => break 'slots,
                Some((task, score)) => {
                    let task_end = cursor + chrono::Duration::minutes(task.duration_minutes);
                    let actual_end = task_end.min(slot.end);

                    // Skip tasks that don't fit minimum viable block (15 min)
                    if (actual_end - cursor).num_minutes() < 15 {
                        continue 'slots;
                    }

                    plan.push(DailyPlan {
                        id: generate_id(),
                        date: date_str.to_string(),
                        task_id: task.id,
                        source: task.source,
                        title: task.title,
                        scheduled_start: Some(cursor.to_rfc3339()),
                        scheduled_end: Some(actual_end.to_rfc3339()),
                        urgency_score: score,
                        effort_weight: task.effort_weight,
                        completed: false,
                        completed_at: None,
                        created_at: now.clone(),
                    });

                    consecutive_work_minutes += (actual_end - cursor).num_minutes();
                    cursor = actual_end + chrono::Duration::minutes(BUFFER_MINUTES);
                }
            }
        }
    }

    plan
}

/// Update pattern statistics after a task completion or skip.
pub async fn update_patterns(
    pool: &SqlitePool,
    task_type: &str,
    time_of_day: &str,
    completed: bool,
    delay_minutes: f64,
) -> Result<()> {
    let existing: Option<(String, f64, f64, i64)> = sqlx::query_as(
        "SELECT id, completion_rate, avg_delay_minutes, sample_count
         FROM patterns WHERE task_type = ? AND time_of_day = ?",
    )
    .bind(task_type)
    .bind(time_of_day)
    .fetch_optional(pool)
    .await?;

    let now = Utc::now().to_rfc3339();

    match existing {
        None => {
            sqlx::query(
                "INSERT INTO patterns (id, task_type, time_of_day, completion_rate, avg_delay_minutes, sample_count, last_updated)
                 VALUES (?, ?, ?, ?, ?, 1, ?)",
            )
            .bind(generate_id())
            .bind(task_type)
            .bind(time_of_day)
            .bind(if completed { 1.0_f64 } else { 0.0_f64 })
            .bind(delay_minutes)
            .bind(&now)
            .execute(pool)
            .await?;
        }
        Some((id, rate, avg_delay, count)) => {
            let new_count = count + 1;
            // Exponential moving average
            let alpha = 0.2_f64;
            let new_rate = rate + alpha * (if completed { 1.0 } else { 0.0 } - rate);
            let new_delay = avg_delay + alpha * (delay_minutes - avg_delay);

            sqlx::query(
                "UPDATE patterns SET completion_rate = ?, avg_delay_minutes = ?,
                 sample_count = ?, last_updated = ? WHERE id = ?",
            )
            .bind(new_rate)
            .bind(new_delay)
            .bind(new_count)
            .bind(&now)
            .bind(&id)
            .execute(pool)
            .await?;
        }
    }

    Ok(())
}
