use anyhow::Result;
use chrono::{DateTime, Datelike, Local, NaiveDate, NaiveTime, TimeZone, Timelike, Utc};
use serde::{Deserialize, Serialize};
use sqlx::SqlitePool;
use std::collections::HashMap;

use crate::db::{models::{DailyPlan, WorkHours}, ops::generate_id};

const WEEK_HOURS: f64 = 168.0;
const BUFFER_MINUTES: i64 = 15;

/// Conservative starting values used until enough history is accumulated.
const DEFAULT_FOCUS_BLOCK_MINUTES: i64 = 90;
const DEFAULT_BREAK_MINUTES: i64 = 25;
/// Minimum completions needed before the learned values are trusted.
const MIN_SAMPLES_TO_TRUST: usize = 5;

#[derive(Debug, Clone)]
pub struct TaskInput {
    pub id: String,
    pub title: String,
    pub source: String,
    pub task_type: String, // used for pattern lookup
    pub due_date: Option<String>,
    pub effort_weight: f64, // 1-5 scale
    pub duration_minutes: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CalendarBlock {
    pub start: DateTime<Utc>,
    pub end: DateTime<Utc>,
}

/// Convert an ISO timestamp to a time-of-day bucket.
pub fn time_of_day_from_iso(iso: &str) -> &'static str {
    let hour = DateTime::parse_from_rfc3339(iso)
        .map(|d| d.with_timezone(&Local).hour())
        .unwrap_or(12);
    time_of_day_from_hour(hour)
}

fn time_of_day_from_hour(hour: u32) -> &'static str {
    match hour {
        5..=11 => "morning",
        12..=16 => "afternoon",
        17..=20 => "evening",
        _ => "night",
    }
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
        Some((completion_rate, avg_delay, sample_count)) if sample_count >= 3 => {
            // Penalty based on low completion rate and high average delay
            let skip_penalty = (1.0 - completion_rate) * 60.0;
            let delay_penalty = (avg_delay / 60.0).min(40.0);
            (skip_penalty + delay_penalty).min(100.0)
        }
        _ => 0.0, // Not enough data yet
    }
}

/// Pre-fetch all patterns into a HashMap for efficient lookup.
async fn fetch_all_patterns(pool: &SqlitePool) -> HashMap<(String, String), (f64, f64, i64)> {
    let rows: Vec<(String, String, f64, f64, i64)> = sqlx::query_as(
        "SELECT task_type, time_of_day, completion_rate, avg_delay_minutes, sample_count
         FROM patterns",
    )
    .fetch_all(pool)
    .await
    .unwrap_or_default();

    rows.into_iter()
        .map(|(t, tod, rate, delay, count)| ((t, tod), (rate, delay, count)))
        .collect()
}

/// Look up pattern penalty from pre-fetched HashMap (no DB call).
fn pattern_penalty_from_map(
    patterns: &HashMap<(String, String), (f64, f64, i64)>,
    task_type: &str,
    time_of_day: &str,
) -> f64 {
    match patterns.get(&(task_type.to_string(), time_of_day.to_string())) {
        Some((completion_rate, avg_delay, sample_count)) if *sample_count >= 3 => {
            let skip_penalty = (1.0 - completion_rate) * 60.0;
            let delay_penalty = (avg_delay / 60.0).min(40.0);
            (skip_penalty + delay_penalty).min(100.0)
        }
        _ => 0.0,
    }
}

/// Slot fitness multiplier: how well does this task type fit this time of day?
/// Based on historical completion rate. Returns 0.5–1.0.
fn slot_fitness(
    patterns: &HashMap<(String, String), (f64, f64, i64)>,
    task_type: &str,
    time_of_day: &str,
) -> f64 {
    match patterns.get(&(task_type.to_string(), time_of_day.to_string())) {
        Some((completion_rate, _, sample_count)) if *sample_count >= 5 => {
            // Range: [0.5, 1.0] — never fully exclude, but strongly prefer historically-good fits
            0.5 + 0.5 * completion_rate
        }
        _ => 1.0, // no data → neutral (don't penalize)
    }
}

/// Fetch the circadian model — hourly completion rates for the current day of week.
/// Returns a map of hour → (completions, samples).
async fn fetch_circadian_model(pool: &SqlitePool) -> HashMap<u32, (i64, i64)> {
    let dow = Local::now().weekday().num_days_from_monday() as i32;
    let rows: Vec<(i32, i64, i64)> = sqlx::query_as(
        "SELECT hour, completions, samples FROM circadian_model
         WHERE day_of_week = ? AND samples >= 2",
    )
    .bind(dow)
    .fetch_all(pool)
    .await
    .unwrap_or_default();

    rows.into_iter()
        .map(|(h, c, s)| (h as u32, (c, s)))
        .collect()
}

/// Circadian energy multiplier for a given hour.
/// Returns 0.6–1.2 based on the hour's historical completion rate relative to the daily average.
fn circadian_multiplier(circadian: &HashMap<u32, (i64, i64)>, hour: u32) -> f64 {
    if circadian.is_empty() {
        return 1.0;
    }

    let global_rate: f64 = {
        let total_c: i64 = circadian.values().map(|(c, _)| c).sum();
        let total_s: i64 = circadian.values().map(|(_, s)| s).sum();
        if total_s == 0 {
            return 1.0;
        }
        total_c as f64 / total_s as f64
    };

    match circadian.get(&hour) {
        Some((c, s)) if *s > 0 => {
            let hour_rate = *c as f64 / *s as f64;
            // Ratio relative to daily average, clamped to [0.6, 1.2]
            let ratio = if global_rate > 0.0 { hour_rate / global_rate } else { 1.0 };
            ratio.clamp(0.6, 1.2)
        }
        _ => 0.85, // Unknown hour — slight penalty (assume below average)
    }
}

/// Returns true if the circadian model has enough data (≥8 samples) and
/// the completion rate for this hour is below 30%. The planner uses this
/// to skip scheduling hard tasks entirely in "dead zone" hours.
fn is_circadian_dead_zone(circadian: &HashMap<u32, (i64, i64)>, hour: u32) -> bool {
    match circadian.get(&hour) {
        Some((c, s)) if *s >= 8 => {
            let rate = *c as f64 / *s as f64;
            rate < 0.30
        }
        _ => false,
    }
}

/// Analyse recent task-completion history to learn how long Sean naturally works
/// before productivity drops (focus block) and how long his actual breaks are.
///
/// Method:
/// - Fetch all completed tasks from the last 60 days with scheduled_start and completed_at.
/// - Sort by completed_at within each day and detect "work runs" — consecutive completions
///   where the gap between one completion and the next scheduled_start is ≤ 45 minutes
///   (implying no intentional break was taken).
/// - Measure each run's total span. This is the "voluntary focus block" for that session.
/// - Measure each inter-run gap (actual break duration).
/// - EMA-smooth these observations; persist to settings so they improve over time.
/// - Returns (focus_block_minutes, break_minutes).
pub async fn compute_learned_focus_params(pool: &SqlitePool) -> (i64, i64) {
    // Load previously-learned values as the starting point
    let stored_focus: Option<i64> = crate::db::get_setting(pool, "learned_focus_block_minutes")
        .await
        .ok()
        .flatten()
        .and_then(|s| s.parse().ok());
    let stored_break: Option<i64> = crate::db::get_setting(pool, "learned_break_minutes")
        .await
        .ok()
        .flatten()
        .and_then(|s| s.parse().ok());

    let mut focus_est = stored_focus.unwrap_or(DEFAULT_FOCUS_BLOCK_MINUTES) as f64;
    let mut break_est = stored_break.unwrap_or(DEFAULT_BREAK_MINUTES) as f64;

    // Fetch recent completions: (scheduled_start, completed_at)
    let cutoff = (Utc::now() - chrono::Duration::days(60)).to_rfc3339();
    let rows: Vec<(Option<String>, Option<String>)> = sqlx::query_as(
        "SELECT scheduled_start, completed_at FROM daily_plans
         WHERE completed = 1
           AND completed_at IS NOT NULL
           AND scheduled_start IS NOT NULL
           AND completed_at >= ?
         ORDER BY completed_at ASC",
    )
    .bind(&cutoff)
    .fetch_all(pool)
    .await
    .unwrap_or_default();

    // Parse and flatten to (scheduled_start_utc, completed_at_utc)
    let mut events: Vec<(DateTime<Utc>, DateTime<Utc>)> = rows
        .into_iter()
        .filter_map(|(s, c)| {
            let start = DateTime::parse_from_rfc3339(s.as_deref()?)
                .ok()
                .map(|d| d.with_timezone(&Utc))?;
            let done = DateTime::parse_from_rfc3339(c.as_deref()?)
                .ok()
                .map(|d| d.with_timezone(&Utc))?;
            Some((start, done))
        })
        .collect();

    events.sort_by_key(|(s, _)| *s);

    // Detect work runs and inter-run gaps
    let mut run_spans: Vec<f64> = Vec::new();
    let mut break_spans: Vec<f64> = Vec::new();

    if events.len() >= 2 {
        let mut run_start = events[0].0;
        let mut run_end = events[0].1;

        for i in 1..events.len() {
            let (next_start, next_done) = events[i];
            let gap_mins = (next_start - run_end).num_minutes();

            if gap_mins <= 45 {
                // Still in the same run — extend it
                run_end = next_done;
            } else {
                // Run ended; record its span and the break that followed
                let span = (run_end - run_start).num_minutes() as f64;
                if span >= 10.0 {
                    run_spans.push(span);
                }
                let brk = gap_mins as f64;
                if brk <= 180.0 {
                    // Ignore multi-hour gaps (those are life, not breaks)
                    break_spans.push(brk);
                }
                // Start a new run
                run_start = next_start;
                run_end = next_done;
            }
        }
        // Close the last run
        let span = (run_end - run_start).num_minutes() as f64;
        if span >= 10.0 {
            run_spans.push(span);
        }
    }

    // EMA-update the estimates if we have enough data
    let alpha = 0.25_f64;
    if run_spans.len() >= MIN_SAMPLES_TO_TRUST {
        let observed_focus = run_spans.iter().sum::<f64>() / run_spans.len() as f64;
        focus_est = focus_est + alpha * (observed_focus - focus_est);
        // Clamp to sane range: 20 min – 4 hours
        focus_est = focus_est.clamp(20.0, 240.0);
        let _ = crate::db::set_setting(
            pool,
            "learned_focus_block_minutes",
            &(focus_est.round() as i64).to_string(),
        )
        .await;
    }
    if break_spans.len() >= MIN_SAMPLES_TO_TRUST {
        let observed_break = break_spans.iter().sum::<f64>() / break_spans.len() as f64;
        break_est = break_est + alpha * (observed_break - break_est);
        // Clamp to sane range: 5 min – 90 min
        break_est = break_est.clamp(5.0, 90.0);
        let _ = crate::db::set_setting(
            pool,
            "learned_break_minutes",
            &(break_est.round() as i64).to_string(),
        )
        .await;
    }

    (focus_est.round() as i64, break_est.round() as i64)
}

/// Generate a daily plan for today.
pub async fn generate_daily_plan(
    pool: &SqlitePool,
    task_duration_minutes: i64,
    creative_time_minutes: i64,
    work_hours: &WorkHours,
) -> Result<Vec<DailyPlan>> {
    let today_str = Local::now().format("%Y-%m-%d").to_string();

    // Snapshot any promoted google_task_ids before wiping the plan
    let promoted: Vec<(String, String)> = sqlx::query_as(
        "SELECT task_id, google_task_id FROM daily_plans
         WHERE date = ? AND google_task_id IS NOT NULL AND completed = 0",
    )
    .bind(&today_str)
    .fetch_all(pool)
    .await
    .unwrap_or_default();

    // Delete existing non-completed plan for today
    sqlx::query("DELETE FROM daily_plans WHERE date = ? AND completed = 0")
        .bind(&today_str)
        .execute(pool)
        .await?;

    // Fetch tasks due today or already overdue — future tasks stay in the upcoming panel.
    // Tasks with no due date are "anytime" work items and are always eligible.
    let tasks: Vec<(String, String, String, Option<String>, Option<String>, Option<String>)> = sqlx::query_as(
        "SELECT id, title, source, due_date, course_name, linked_project_id FROM tasks_cache
         WHERE completed = 0
           AND id NOT IN (
               SELECT task_id FROM daily_plans
               WHERE date = ? AND completed = 1
           )
           AND id NOT IN (
               SELECT task_id FROM dismissed_tasks
           )
           AND (due_date IS NULL OR date(due_date) <= date('now', 'localtime'))",
    )
    .bind(&today_str)
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

    // Pre-fetch all patterns once
    let patterns = fetch_all_patterns(pool).await;

    // Learn focus block and break duration from Sean's actual completion history
    let (focus_block_minutes, break_minutes) = compute_learned_focus_params(pool).await;

    // Current time-of-day for initial urgency scoring
    let current_tod = time_of_day_from_hour(Local::now().hour());

    // ── Goal alignment ────────────────────────────────────────────────────
    // Active goals boost priority of tasks that align with them (via linked
    // project, task_type match on linked_task_types, or title keyword).
    // High-priority goals (5) push effort_weight to 5.0; low-priority (1) leave it at 3.0.
    let active_goals: Vec<(String, i64, Option<String>, Option<String>)> = sqlx::query_as(
        "SELECT id, priority, linked_project_id, linked_task_types
         FROM goals WHERE status = 'active'",
    )
    .fetch_all(pool)
    .await
    .unwrap_or_default();

    // Build TaskInput list with urgency scores
    let mut task_inputs: Vec<(TaskInput, f64)> = Vec::new();
    for (id, title, source, due_date, course_name, linked_project_id) in &tasks {
        let task_type = if source == "moodle" {
            course_name.as_deref().unwrap_or("moodle").to_string()
        } else {
            source.clone()
        };

        // Determine goal alignment: find highest-priority matching goal
        let goal_priority = active_goals.iter().filter_map(|(_gid, prio, gproj, gtypes)| {
            // Match by linked project
            if let (Some(tp), Some(gp)) = (linked_project_id.as_deref(), gproj.as_deref()) {
                if tp == gp { return Some(*prio); }
            }
            // Match by task type list (comma-separated)
            if let Some(types_csv) = gtypes.as_deref() {
                let matched = types_csv.split(',')
                    .any(|t| t.trim().eq_ignore_ascii_case(&task_type));
                if matched { return Some(*prio); }
            }
            None
        }).max().unwrap_or(0);

        // Goal-aligned tasks get boosted effort_weight (activating the dead parameter)
        // priority 5 → effort_weight 5.0, priority 1 → 3.2, no goal → 3.0
        let effort_weight = if goal_priority > 0 {
            3.0 + (goal_priority as f64 - 1.0) * 0.5
        } else {
            3.0
        };

        // Goal alignment bonus added to urgency (0–15 points based on goal priority)
        let goal_bonus = goal_priority as f64 * 3.0;

        let pattern_penalty = pattern_penalty_from_map(&patterns, &task_type, current_tod);
        let base_score = compute_urgency_score(due_date.as_deref(), effort_weight, pattern_penalty);
        let score = (base_score + goal_bonus).min(100.0);

        task_inputs.push((
            TaskInput {
                id: id.clone(),
                title: title.clone(),
                source: source.clone(),
                task_type,
                due_date: due_date.clone(),
                effort_weight,
                duration_minutes: task_duration_minutes,
            },
            score,
        ));
    }

    // Sort by urgency descending as initial ordering
    task_inputs.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));

    // ── Mood-based plan adjustment ────────────────────────────────────────────
    // If the latest energy reading is below 4.0/10, reduce the task count by
    // ~30% (keeping only the highest-urgency items). This prevents CADEN from
    // overloading a low-energy day, which leads to cascading skips and burnout.
    // Tasks with hard deadlines today (due_date == today) are never dropped.
    {
        let (avg_energy, _, _) = crate::state_engine::get_rolling_averages(pool, 1).await;
        if let Some(energy) = avg_energy {
            if energy < 4.0 {
                let original_len = task_inputs.len();
                let keep_count = ((original_len as f64) * 0.7).ceil() as usize;
                if original_len > keep_count {
                    // Partition: tasks due today are always kept
                    let (mut must_keep, mut optional): (Vec<_>, Vec<_>) =
                        task_inputs.into_iter().partition(|(task, _)| {
                            task.due_date.as_deref()
                                .and_then(|d| chrono::DateTime::parse_from_rfc3339(d).ok())
                                .map(|dt| dt.with_timezone(&Local).format("%Y-%m-%d").to_string() == today_str)
                                .unwrap_or(false)
                        });
                    let remaining_slots = keep_count.saturating_sub(must_keep.len());
                    optional.truncate(remaining_slots);
                    must_keep.extend(optional);
                    must_keep.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
                    task_inputs = must_keep;
                }
            }
        }
    }

    // Build free-time slots
    let free_slots = compute_free_slots(&busy_blocks, &today_str, creative_time_minutes, work_hours);

    // Fetch PK low-performance hours so high-demand tasks are avoided during medication troughs/crashes
    let low_perf_hours = crate::state_engine::get_low_performance_hours_today(pool).await;
    let transitions = fetch_all_transitions(pool).await;

    // Fetch circadian model — hourly productivity data for today's day-of-week
    let circadian = fetch_circadian_model(pool).await;

    // Assign tasks to slots with time-of-day awareness
    let mut plan = assign_tasks_to_slots(
        task_inputs,
        free_slots,
        &today_str,
        &patterns,
        &low_perf_hours,
        focus_block_minutes,
        break_minutes,
        None,        // no prior completed task on a fresh daily plan
        &transitions,
        &circadian,
    );

    // Always include every task due today, even if it didn't fit a time slot.
    // These appear in the Today panel with no scheduled time.
    let now_str = Utc::now().to_rfc3339();
    {
        let scheduled_ids: std::collections::HashSet<String> =
            plan.iter().map(|p| p.task_id.clone()).collect();

        for (id, title, source, due_date, _course_name, _linked_project_id) in &tasks {
            if scheduled_ids.contains(id.as_str()) {
                continue;
            }
            let is_due_today = due_date
                .as_deref()
                .and_then(|d| chrono::DateTime::parse_from_rfc3339(d).ok())
                .map(|dt| dt.with_timezone(&Local).format("%Y-%m-%d").to_string() == today_str)
                .unwrap_or(false);
            if !is_due_today {
                continue;
            }
            let score = compute_urgency_score(due_date.as_deref(), 3.0, 0.0);
            plan.push(DailyPlan {
                id: generate_id(),
                date: today_str.clone(),
                task_id: id.clone(),
                source: source.clone(),
                title: title.clone(),
                scheduled_start: None,
                scheduled_end: None,
                urgency_score: score,
                effort_weight: 3.0,
                completed: false,
                completed_at: None,
                created_at: now_str.clone(),
                google_task_id: None,
                cal_event_id: None,
            });
        }
    }

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
    for (task_id, google_task_id) in &promoted {
        sqlx::query(
            "UPDATE daily_plans SET google_task_id = ? WHERE date = ? AND task_id = ?",
        )
        .bind(google_task_id)
        .bind(&today_str)
        .bind(task_id)
        .execute(pool)
        .await
        .ok();
    }

    Ok(plan)
}

/// Find the first free work-day slot of `duration_mins` between `after` and `before`.
///
/// Walks day-by-day within work hours defined in `work_hours` (local time)
/// and returns the earliest gap that fits, avoiding any events in `calendar_events`.
/// Returns (slot_start, slot_end) in UTC, or None if no slot is found.
pub fn find_free_work_slot(
    calendar_events: &[crate::google::CalendarEvent],
    after: DateTime<Utc>,
    before: DateTime<Utc>,
    duration_mins: i64,
    work_hours: &WorkHours,
) -> Option<(DateTime<Utc>, DateTime<Utc>)> {
    let duration = chrono::Duration::minutes(duration_mins);
    // Start at least 30 min from now so we don't schedule something that's already starting
    let search_start = after.max(Utc::now() + chrono::Duration::minutes(30));
    if search_start >= before {
        return None;
    }

    let mut day = search_start.with_timezone(&Local).date_naive();
    let last_day = before.with_timezone(&Local).date_naive();

    while day <= last_day {
        let weekday = day.weekday();
        let (start_h, end_h) = match work_hours.for_weekday(weekday) {
            Some(h) => h,
            None => {
                // rest day — skip
                day = match day.succ_opt() { Some(d) => d, None => break };
                continue;
            }
        };
        let day_work_start = Local
            .from_local_datetime(&day.and_time(
                NaiveTime::from_hms_opt(start_h, 0, 0).unwrap(),
            ))
            .single()
            .map(|d| d.with_timezone(&Utc));
        let day_work_end = Local
            .from_local_datetime(&day.and_time(
                NaiveTime::from_hms_opt(end_h, 0, 0).unwrap(),
            ))
            .single()
            .map(|d| d.with_timezone(&Utc));

        if let (Some(day_work_start), Some(day_work_end)) = (day_work_start, day_work_end) {
            let window_start = day_work_start.max(search_start);
            let window_end = day_work_end.min(before);

            if window_start + duration <= window_end {
                // Collect busy blocks that overlap this window, sorted by start
                let mut busy: Vec<(DateTime<Utc>, DateTime<Utc>)> = calendar_events
                    .iter()
                    .filter_map(|e| {
                        let s = DateTime::parse_from_rfc3339(&e.start_time)
                            .ok()?.with_timezone(&Utc);
                        let end = DateTime::parse_from_rfc3339(&e.end_time)
                            .ok()?.with_timezone(&Utc);
                        if s < window_end && end > window_start {
                            Some((s, end))
                        } else {
                            None
                        }
                    })
                    .collect();
                busy.sort_by_key(|(s, _)| *s);

                let mut cursor = window_start;
                for (busy_start, busy_end) in &busy {
                    if *busy_start > cursor && cursor + duration <= *busy_start {
                        return Some((cursor, cursor + duration));
                    }
                    if *busy_end > cursor {
                        cursor = *busy_end;
                    }
                }
                // Remaining gap after all busy blocks
                if cursor + duration <= window_end {
                    return Some((cursor, cursor + duration));
                }
            }
        }

        day = match day.succ_opt() {
            Some(d) => d,
            None => break,
        };
    }

    None
}

fn compute_free_slots(busy: &[CalendarBlock], date_str: &str, creative_time_minutes: i64, work_hours: &WorkHours) -> Vec<CalendarBlock> {
    let day: NaiveDate = date_str.parse().unwrap_or_else(|_| Local::now().date_naive());
    let weekday = day.weekday();

    let (start_hour, end_hour) = match work_hours.for_weekday(weekday) {
        Some(h) => h,
        None => return vec![], // rest day — schedule nothing
    };

    let work_start = Local
        .from_local_datetime(&day.and_time(
            NaiveTime::from_hms_opt(start_hour, 0, 0).unwrap(),
        ))
        .single()
        .map(|d| d.with_timezone(&Utc))
        .unwrap_or_else(Utc::now);

    let work_end = Local
        .from_local_datetime(&day.and_time(
            NaiveTime::from_hms_opt(end_hour, 0, 0).unwrap(),
        ))
        .single()
        .map(|d| d.with_timezone(&Utc))
        .unwrap_or_else(|| Utc::now() + chrono::Duration::hours(14));

    // Start no earlier than now
    let cursor_start = work_start.max(Utc::now());

    // Reserve creative time by ending the schedulable window early.
    // This leaves the tail of the day free for creative/personal work.
    let creative_reserve = chrono::Duration::minutes(creative_time_minutes.max(0));
    let work_end = (work_end - creative_reserve).max(cursor_start);

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

/// Assign tasks to free slots with time-of-day awareness.
/// For each slot position, picks the task that best fits the slot's time of day
/// by multiplying urgency score by the historical slot-fitness for that task type.
/// High-demand tasks are further penalized during PK low-performance hours.
/// focus_block_minutes and break_minutes are learned from Sean's actual history.
/// last_completed_type applies a transition multiplier to favour productive sequences.
fn assign_tasks_to_slots(
    tasks: Vec<(TaskInput, f64)>,
    slots: Vec<CalendarBlock>,
    date_str: &str,
    patterns: &HashMap<(String, String), (f64, f64, i64)>,
    low_perf_hours: &[u32],
    focus_block_minutes: i64,
    break_minutes: i64,
    last_completed_type: Option<&str>,
    transitions: &HashMap<(String, String), (f64, i64)>,
    circadian: &HashMap<u32, (i64, i64)>,
) -> Vec<DailyPlan> {
    let now = Utc::now().to_rfc3339();
    let mut plan: Vec<DailyPlan> = Vec::new();
    let mut remaining: Vec<(TaskInput, f64)> = tasks;
    let mut consecutive_work_minutes: i64 = 0;
    // Track the last scheduled task type so transition multiplier updates slot-by-slot
    let mut current_last_type: Option<String> = last_completed_type.map(|s| s.to_string());

    'slots: for slot in &slots {
        let mut cursor = slot.start;

        loop {
            // Insert a break once the learned focus-block duration is reached
            if consecutive_work_minutes >= focus_block_minutes {
                cursor += chrono::Duration::minutes(break_minutes);
                consecutive_work_minutes = 0;
            }

            if cursor >= slot.end || remaining.is_empty() {
                continue 'slots;
            }

            // Determine time-of-day for this slot position
            let slot_tod = time_of_day_from_hour(cursor.with_timezone(&Local).hour());

            // Find the best-fitting task for this slot
            let slot_local_hour = cursor.with_timezone(&Local).hour();
            let is_low_perf_slot = low_perf_hours.contains(&slot_local_hour);

            // Circadian dead-zone check: if history shows <30% completion at this
            // hour (with ≥8 samples), skip scheduling high-effort tasks entirely.
            // Low-effort tasks (effort_weight ≤ 2.0) can still be placed here.
            let is_dead_zone = is_circadian_dead_zone(circadian, slot_local_hour);

            // Circadian multiplier for this specific hour based on learned productivity data
            let circ_mult = circadian_multiplier(circadian, slot_local_hour);

            let best_idx = remaining
                .iter()
                .enumerate()
                .filter(|(_, (task, _))| {
                    // In circadian dead zones, only allow low-effort tasks
                    if is_dead_zone && task.effort_weight > 2.0 {
                        return false;
                    }
                    true
                })
                .map(|(i, (task, urgency))| {
                    let fitness = slot_fitness(patterns, &task.task_type, slot_tod);
                    // During medication trough/crash hours, strongly discourage high-demand tasks
                    let pk_multiplier = if is_low_perf_slot
                        && (task.effort_weight > 3.0 || task.source == "moodle")
                    {
                        0.3
                    } else {
                        1.0
                    };
                    // Transition momentum: if one task type tends to follow well after another, boost it
                    let trans_mult = match &current_last_type {
                        Some(prev) => transition_multiplier(transitions, prev, &task.task_type),
                        None => 1.0,
                    };
                    let adjusted = urgency * fitness * pk_multiplier * trans_mult * circ_mult;
                    (i, adjusted)
                })
                .max_by(|a, b| a.1.partial_cmp(&b.1).unwrap_or(std::cmp::Ordering::Equal))
                .map(|(i, _)| i);

            match best_idx {
                None => break 'slots,
                Some(idx) => {
                    let (task, score) = remaining.remove(idx);
                    let task_end = cursor + chrono::Duration::minutes(task.duration_minutes);
                    let actual_end = task_end.min(slot.end);

                    // Skip if remaining time is less than minimum viable block (15 min)
                    if (actual_end - cursor).num_minutes() < 15 {
                        // Task doesn't fit this slot — put it back and try next slot
                        remaining.insert(0, (task, score));
                        continue 'slots;
                    }

                    current_last_type = Some(task.task_type.clone());
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
                        google_task_id: None,
                        cal_event_id: None,
                    });

                    consecutive_work_minutes += (actual_end - cursor).num_minutes();
                    cursor = actual_end + chrono::Duration::minutes(BUFFER_MINUTES);
                }
            }
        }
    }

    plan
}

/// Update the task-type transition model after a completion.
/// Call with (from_type = what was completed before, to_type = what was just completed).
/// The `completed` flag tells us whether `to_type` was successfully done.
pub async fn update_transition(
    pool: &SqlitePool,
    from_type: &str,
    to_type: &str,
    completed: bool,
    delay_minutes: f64,
) -> Result<()> {
    let existing: Option<(String, f64, f64, i64)> = sqlx::query_as(
        "SELECT id, completion_rate, avg_delay_minutes, sample_count
         FROM task_transitions WHERE from_type = ? AND to_type = ?",
    )
    .bind(from_type)
    .bind(to_type)
    .fetch_optional(pool)
    .await?;

    let now = Utc::now().to_rfc3339();
    let alpha = 0.2_f64;

    match existing {
        None => {
            sqlx::query(
                "INSERT INTO task_transitions
                 (id, from_type, to_type, completion_rate, avg_delay_minutes, sample_count, last_updated)
                 VALUES (?, ?, ?, ?, ?, 1, ?)",
            )
            .bind(generate_id())
            .bind(from_type)
            .bind(to_type)
            .bind(if completed { 1.0_f64 } else { 0.0_f64 })
            .bind(delay_minutes)
            .bind(&now)
            .execute(pool)
            .await?;
        }
        Some((id, rate, avg_delay, count)) => {
            let new_rate = rate + alpha * (if completed { 1.0 } else { 0.0 } - rate);
            let new_delay = avg_delay + alpha * (delay_minutes - avg_delay);
            sqlx::query(
                "UPDATE task_transitions
                 SET completion_rate = ?, avg_delay_minutes = ?, sample_count = ?, last_updated = ?
                 WHERE id = ?",
            )
            .bind(new_rate)
            .bind(new_delay)
            .bind(count + 1)
            .bind(&now)
            .bind(&id)
            .execute(pool)
            .await?;
        }
    }

    Ok(())
}

/// Returns a multiplier [0.4, 1.5] reflecting how well `to_type` tends to perform
/// after `from_type`. Above 1.0 = momentum boost; below 1.0 = friction penalty.
/// Returns 1.0 (neutral) if there's no data or fewer than 5 samples.
fn transition_multiplier(
    transitions: &HashMap<(String, String), (f64, i64)>,
    from_type: &str,
    to_type: &str,
) -> f64 {
    match transitions.get(&(from_type.to_string(), to_type.to_string())) {
        Some((completion_rate, sample_count)) if *sample_count >= 5 => {
            // Map [0, 1] completion_rate to [0.4, 1.5]
            // 0.5 completion → 1.0 (neutral baseline)
            // 1.0 completion → 1.5 (strong momentum)
            // 0.0 completion → 0.4 (friction)
            0.4 + 1.1 * completion_rate
        }
        _ => 1.0,
    }
}

async fn fetch_all_transitions(
    pool: &SqlitePool,
) -> HashMap<(String, String), (f64, i64)> {
    let rows: Vec<(String, String, f64, i64)> = sqlx::query_as(
        "SELECT from_type, to_type, completion_rate, sample_count FROM task_transitions",
    )
    .fetch_all(pool)
    .await
    .unwrap_or_default();

    rows.into_iter()
        .map(|(f, t, rate, count)| ((f, t), (rate, count)))
        .collect()
}

/// Re-plan the remainder of today immediately after a task is completed.
/// Frees the time between now and the scheduled ends of unfinished tasks,
/// re-scores everything with the fresh transition signal, and returns
/// the updated list of (plan_id, new_scheduled_start, new_scheduled_end).
/// The caller is responsible for pushing the updated slots to GCal.
pub async fn reschedule_remaining_today(
    pool: &SqlitePool,
    last_completed_type: Option<&str>,
) -> Result<Vec<(String, String, String, String)>> {
    let today_str = Local::now().format("%Y-%m-%d").to_string();
    let settings = crate::db::ops::load_settings(pool).await?;

    // Fetch unfinished plan items for today that have a scheduled slot
    let remaining: Vec<(String, String, String, String, Option<String>, Option<String>, f64)> =
        sqlx::query_as(
            "SELECT dp.id, dp.task_id, dp.title, dp.source,
                    tc.course_name, dp.scheduled_end,
                    dp.effort_weight
             FROM daily_plans dp
             LEFT JOIN tasks_cache tc ON tc.id = dp.task_id
             WHERE dp.date = ? AND dp.completed = 0 AND dp.scheduled_start IS NOT NULL
             ORDER BY dp.scheduled_start ASC",
        )
        .bind(&today_str)
        .fetch_all(pool)
        .await
        .unwrap_or_default();

    if remaining.is_empty() {
        return Ok(vec![]);
    }

    // Build task inputs from the remaining unfinished items
    let patterns = fetch_all_patterns(pool).await;
    let transitions = fetch_all_transitions(pool).await;
    let low_perf_hours = crate::state_engine::get_low_performance_hours_today(pool).await;
    let (focus_block_minutes, break_minutes) = compute_learned_focus_params(pool).await;

    let current_tod = time_of_day_from_hour(Local::now().hour());
    let task_inputs: Vec<(TaskInput, f64)> = remaining
        .iter()
        .map(|(id, _task_id, title, source, course, _sched_end, effort)| {
            let task_type = if source == "moodle" {
                course.as_deref().unwrap_or("moodle").to_string()
            } else {
                source.clone()
            };
            let pattern_penalty = pattern_penalty_from_map(&patterns, &task_type, current_tod);
            let score = compute_urgency_score(None, *effort, pattern_penalty);
            (
                TaskInput {
                    id: id.clone(),
                    title: title.clone(),
                    source: source.clone(),
                    task_type,
                    due_date: None,
                    effort_weight: *effort,
                    duration_minutes: settings.task_duration_minutes,
                },
                score,
            )
        })
        .collect();

    // Compute free slots from now, treating existing scheduled_ends in today's
    // completed items as busy so we don't double-book.
    let now_utc = Utc::now();
    let completed_blocks: Vec<CalendarBlock> = sqlx::query_as::<_, (Option<String>, Option<String>)>(
        "SELECT scheduled_start, scheduled_end FROM daily_plans
         WHERE date = ? AND completed = 1
           AND scheduled_start IS NOT NULL AND scheduled_end IS NOT NULL",
    )
    .bind(&today_str)
    .fetch_all(pool)
    .await
    .unwrap_or_default()
    .into_iter()
    .filter_map(|(s, e)| {
        let start = DateTime::parse_from_rfc3339(s.as_deref()?).ok()?.with_timezone(&Utc);
        let end = DateTime::parse_from_rfc3339(e.as_deref()?).ok()?.with_timezone(&Utc);
        // Only include if the block end is in the future (already-completed past blocks
        // are truly free time; what we care about is the shrunken end we just wrote)
        if end > now_utc { Some(CalendarBlock { start, end }) } else { None }
    })
    .collect();

    // Also pull calendar events so we don't reschedule into real meetings
    let today_start = format!("{}T00:00:00Z", today_str);
    let today_end   = format!("{}T23:59:59Z", today_str);
    let cal_events: Vec<CalendarBlock> = sqlx::query_as::<_, (String, String)>(
        "SELECT start_time, end_time FROM events_cache
         WHERE start_time >= ? AND start_time <= ? ORDER BY start_time ASC",
    )
    .bind(&today_start)
    .bind(&today_end)
    .fetch_all(pool)
    .await
    .unwrap_or_default()
    .into_iter()
    .filter_map(|(s, e)| {
        let start = DateTime::parse_from_rfc3339(&s).ok()?.with_timezone(&Utc);
        let end   = DateTime::parse_from_rfc3339(&e).ok()?.with_timezone(&Utc);
        Some(CalendarBlock { start, end })
    })
    .collect();

    let mut busy: Vec<CalendarBlock> = completed_blocks;
    busy.extend(cal_events);

    let free_slots = compute_free_slots(&busy, &today_str, settings.creative_time_minutes, &settings.work_hours);

    let circadian = fetch_circadian_model(pool).await;
    let new_plan = assign_tasks_to_slots(
        task_inputs,
        free_slots,
        &today_str,
        &patterns,
        &low_perf_hours,
        focus_block_minutes,
        break_minutes,
        last_completed_type,
        &transitions,
        &circadian,
    );

    // Persist the new slot times and return the changes so the caller can update GCal
    let mut updates: Vec<(String, String, String, String)> = Vec::new(); // (plan_id, old_id, new_start, new_end)
    for item in &new_plan {
        if let (Some(start), Some(end)) = (&item.scheduled_start, &item.scheduled_end) {
            sqlx::query(
                "UPDATE daily_plans SET scheduled_start = ?, scheduled_end = ?
                 WHERE id = ?",
            )
            .bind(start)
            .bind(end)
            .bind(&item.id)
            .execute(pool)
            .await
            .ok();

            // Get existing cal_event_id for this plan row
            let cal_event_id: Option<String> = sqlx::query_as::<_, (Option<String>,)>(
                "SELECT cal_event_id FROM daily_plans WHERE id = ?",
            )
            .bind(&item.id)
            .fetch_optional(pool)
            .await
            .ok()
            .flatten()
            .and_then(|(v,)| v);

            if let Some(ceid) = cal_event_id {
                updates.push((item.id.clone(), ceid, start.clone(), end.clone()));
            }
        }
    }

    Ok(updates)
}

/// Pre-compute a plain-text situational briefing for injection into Call 2 of the pipeline.
/// All values are deterministic — no LLM involved.
pub async fn compute_situational_briefing(pool: &SqlitePool) -> String {
    let now = Utc::now();
    let today = chrono::Local::now().format("%Y-%m-%d").to_string();
    let now_iso = now.to_rfc3339();
    let seven_days_ago = (now - chrono::Duration::days(7)).to_rfc3339();

    // Today's plan: total and completed
    let total_planned: i64 = sqlx::query_as::<_, (i64,)>(
        "SELECT COUNT(*) FROM daily_plans WHERE date = ?",
    )
    .bind(&today)
    .fetch_one(pool)
    .await
    .map(|(n,)| n)
    .unwrap_or(0);

    let completed_today: i64 = sqlx::query_as::<_, (i64,)>(
        "SELECT COUNT(*) FROM daily_plans WHERE date = ? AND completed = 1",
    )
    .bind(&today)
    .fetch_one(pool)
    .await
    .map(|(n,)| n)
    .unwrap_or(0);

    // Overdue tasks — only items still on today's active plan, not yet completed
    let one_hour_ago = (now - chrono::Duration::hours(1)).to_rfc3339();
    let overdue: Vec<(String, Option<String>)> = sqlx::query_as(
        "SELECT tc.title, tc.due_date FROM tasks_cache tc
         INNER JOIN daily_plans dp ON dp.task_id = tc.id
         WHERE tc.completed = 0 AND dp.completed = 0
           AND tc.due_date IS NOT NULL AND tc.due_date < ?
         ORDER BY tc.due_date ASC LIMIT 5",
    )
    .bind(&one_hour_ago)
    .fetch_all(pool)
    .await
    .unwrap_or_default();

    // Next upcoming calendar event
    let next_event: Option<(String, String)> = sqlx::query_as(
        "SELECT title, start_time FROM events_cache
         WHERE start_time > ? ORDER BY start_time ASC LIMIT 1",
    )
    .bind(&now_iso)
    .fetch_optional(pool)
    .await
    .ok()
    .flatten();

    // 7-day completion rate for momentum
    let week_ago = (now - chrono::Duration::days(7)).to_rfc3339();
    let week_completions: i64 = sqlx::query_as::<_, (i64,)>(
        "SELECT COUNT(*) FROM completions WHERE actual_time > ?",
    )
    .bind(&week_ago)
    .fetch_one(pool)
    .await
    .map(|(n,)| n)
    .unwrap_or(0);
    let week_avg = week_completions as f64 / 7.0;

    // Recent thought dump entries (last 7 days, up to 6 most recent)
    let recent_thoughts: Vec<(String, String)> = sqlx::query_as(
        "SELECT pe.content, pe.created_at
         FROM project_entries pe
         JOIN projects p ON pe.project_id = p.id
         WHERE p.name = '__thoughts__' AND pe.created_at > ?
         ORDER BY pe.created_at DESC LIMIT 6",
    )
    .bind(&seven_days_ago)
    .fetch_all(pool)
    .await
    .unwrap_or_default();

    // Patterns with enough data — best and worst task-type/time combos
    let pattern_insights: Vec<(String, String, f64, i64)> = sqlx::query_as(
        "SELECT task_type, time_of_day, completion_rate, sample_count
         FROM patterns WHERE sample_count >= 5
         ORDER BY completion_rate DESC",
    )
    .fetch_all(pool)
    .await
    .unwrap_or_default();

    // Recent skip/incomplete patterns (what Sean avoids)
    let recent_skips: Vec<(String,)> = sqlx::query_as(
        "SELECT title FROM daily_plans
         WHERE date >= date(?, '-14 days') AND completed = 0 AND scheduled_start IS NOT NULL
         ORDER BY date DESC LIMIT 5",
    )
    .bind(&today)
    .fetch_all(pool)
    .await
    .unwrap_or_default();

    // ── Assemble ─────────────────────────────────────────────────────────────

    let mut lines: Vec<String> = Vec::new();

    // Time of day — explicit so the model knows what hour it is
    let hour = chrono::Local::now().hour();
    let time_label = match hour {
        0..=4   => "late night (sleep hours — do NOT push schoolwork or tasks; creative work is fine)",
        5..=8   => "early morning",
        9..=11  => "morning",
        12..=13 => "midday",
        14..=17 => "afternoon",
        18..=20 => "evening",
        21..=22 => "late evening (winding down — creative work welcome, light on schoolwork)",
        _       => "late night (sleep hours — do NOT push schoolwork or tasks; creative work is fine)",
    };
    lines.push(format!(
        "Current local time: {:02}:{:02} — {}",
        hour,
        chrono::Local::now().minute(),
        time_label
    ));

    // Cognitive load
    let past_noon = hour >= 12;
    let cognitive_load = if overdue.len() >= 2
        || (total_planned > 0 && completed_today == 0 && past_noon)
    {
        "HIGH"
    } else if !overdue.is_empty() || (total_planned > 0 && completed_today < total_planned / 2) {
        "MEDIUM"
    } else {
        "LOW"
    };
    lines.push(format!("Cognitive load: {}", cognitive_load));

    // Progress
    lines.push(format!(
        "Today: {}/{} tasks completed",
        completed_today, total_planned
    ));

    // Momentum
    if week_avg > 0.3 {
        let momentum = if completed_today as f64 >= week_avg * 1.2 {
            "above average"
        } else if (completed_today as f64) < week_avg * 0.4 {
            "below average"
        } else {
            "on track"
        };
        lines.push(format!(
            "Momentum: {} (7-day avg {:.1}/day)",
            momentum, week_avg
        ));
    }

    // Overdue items
    if !overdue.is_empty() {
        let items: Vec<String> = overdue
            .iter()
            .map(|(title, due)| {
                if let Some(d) = due {
                    if let Ok(dt) = chrono::DateTime::parse_from_rfc3339(d) {
                        let hours_ago = (now - dt.with_timezone(&Utc)).num_hours();
                        if hours_ago < 24 {
                            return format!("{} ({}h overdue)", title, hours_ago);
                        } else {
                            return format!("{} ({}d overdue)", title, hours_ago / 24);
                        }
                    }
                }
                title.clone()
            })
            .collect();
        lines.push(format!("Overdue: {}", items.join(", ")));
    }

    // Time to next event
    if let Some((title, start)) = next_event {
        if let Ok(dt) = chrono::DateTime::parse_from_rfc3339(&start) {
            let mins = (dt.with_timezone(&Utc) - now).num_minutes();
            if mins >= 0 && mins < 480 {
                lines.push(format!("Next event: '{}' in {}m", title, mins));
            }
        }
    }

    if lines.is_empty() {
        lines.push("No tasks planned or overdue. No upcoming events in the next 8 hours.".to_string());
    }

    // Recent thoughts from the thought dump
    if !recent_thoughts.is_empty() {
        lines.push(String::new());
        lines.push("Recent thoughts (last 7 days):".to_string());
        for (content, created_at) in &recent_thoughts {
            let age = chrono::DateTime::parse_from_rfc3339(created_at)
                .ok()
                .map(|dt| {
                    let days = (now - dt.with_timezone(&Utc)).num_days();
                    if days == 0 { "today".to_string() } else { format!("{}d ago", days) }
                })
                .unwrap_or_default();
            // Truncate long thoughts to keep briefing concise
            let truncated = if content.len() > 120 {
                format!("{}…", &content[..120])
            } else {
                content.clone()
            };
            lines.push(format!("  [{}] {}", age, truncated));
        }
    }

    // What Sean has been skipping recently
    if !recent_skips.is_empty() {
        let skip_titles: Vec<&str> = recent_skips.iter().map(|(t,)| t.as_str()).collect();
        lines.push(format!("Recently skipped tasks: {}", skip_titles.join(", ")));
    }

    // Active goals — so the LLM knows what Sean is working toward
    let goals: Vec<(String, String, i64, Option<f64>, Option<String>, f64, Option<String>)> = sqlx::query_as(
        "SELECT title, category, priority, target_value, target_unit, current_value, deadline
         FROM goals WHERE status = 'active' ORDER BY priority DESC",
    )
    .fetch_all(pool)
    .await
    .unwrap_or_default();

    if !goals.is_empty() {
        lines.push(String::new());
        lines.push("Active goals:".to_string());
        for (title, category, priority, target, unit, current, deadline) in &goals {
            let progress = match (target, unit.as_deref()) {
                (Some(t), Some(u)) if *t > 0.0 => format!(" — {:.0}/{} {} ({:.0}%)", current, t, u, current / t * 100.0),
                _ => String::new(),
            };
            let dl = deadline.as_deref().map(|d| format!(" [due {}]", d)).unwrap_or_default();
            lines.push(format!("  [P{}|{}] {}{}{}", priority, category, title, progress, dl));
        }
    }

    // Historical pattern insights — only surface if there's meaningful data
    if !pattern_insights.is_empty() {
        let good: Vec<String> = pattern_insights
            .iter()
            .filter(|(_, _, rate, _)| *rate >= 0.7)
            .take(3)
            .map(|(task_type, tod, rate, _)| {
                format!("{} in {} ({:.0}% done)", task_type, tod, rate * 100.0)
            })
            .collect();
        let bad: Vec<String> = pattern_insights
            .iter()
            .rev()
            .filter(|(_, _, rate, _)| *rate <= 0.35)
            .take(2)
            .map(|(task_type, tod, rate, _)| {
                format!("{} in {} ({:.0}% done)", task_type, tod, rate * 100.0)
            })
            .collect();
        if !good.is_empty() {
            lines.push(format!("Historically works well: {}", good.join("; ")));
        }
        if !bad.is_empty() {
            lines.push(format!("Historically struggles: {}", bad.join("; ")));
        }
    }

    // Explicit completeness marker so the model knows this is the full picture
    lines.push("(This is the complete current state. There are no other tasks, events, emails, or commitments not listed here.)".to_string());

    lines.join("\n")
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

/// Detect yesterday's uncompleted plan items, record them as skips,
/// and update pattern statistics accordingly. Call this at the start of each sync.
pub async fn record_skips_for_previous_day(pool: &SqlitePool) -> Result<()> {
    let yesterday = (Local::now() - chrono::Duration::days(1))
        .format("%Y-%m-%d")
        .to_string();

    // Find uncompleted (skipped) plan items from yesterday
    let uncompleted: Vec<(String, String, Option<String>)> = sqlx::query_as(
        "SELECT dp.task_id, dp.source, dp.scheduled_start
         FROM daily_plans dp
         WHERE dp.date = ? AND dp.completed = 0",
    )
    .bind(&yesterday)
    .fetch_all(pool)
    .await?;

    let now_str = Utc::now().to_rfc3339();

    for (task_id, source, scheduled_start) in uncompleted {
        // Look up task type from tasks_cache
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
            .map(time_of_day_from_iso)
            .unwrap_or("morning");

        // Record skip in the skips table (ignore duplicates)
        sqlx::query(
            "INSERT OR IGNORE INTO skips
             (id, task_id, source, reason, timestamp)
             VALUES (?, ?, ?, 'not_completed', ?)",
        )
        .bind(generate_id())
        .bind(&task_id)
        .bind(&source)
        .bind(&now_str)
        .execute(pool)
        .await
        .ok();

        // Update pattern: skipped = not completed, delay = 0
        update_patterns(pool, &task_type, time_of_day, false, 0.0).await.ok();

        // Update Sean Model circadian grid — record this as a skip event
        crate::sean_model::circadian::record_event(pool, false).await;
    }

    Ok(())
}
