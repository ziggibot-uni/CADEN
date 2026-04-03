//! Calendar agentic framework for CADEN.
//!
//! Design philosophy: since the local LLM (qwen2.5-coder:7b) is small and not capable
//! of complex multi-step reasoning, the framework handles all the intelligence:
//!
//! 1. **Keyword pre-filter** — detect calendar requests without any LLM call
//! 2. **Structured extraction** — give the LLM a rigid JSON template to fill;
//!    it only needs to identify values, not reason about what to do
//! 3. **Validation + retry** — the framework parses, validates, and reprompts
//!    if the LLM's output is malformed
//! 4. **API execution** — all Google Calendar/Tasks API logic lives here
//! 5. **Result formatting** — the framework writes the confirmation message;
//!    no second LLM call needed for simple operations
//!
//! Inspired by: LangChain tool-use patterns, MCP calendar server, ReAct (lite).

use anyhow::{anyhow, Result};
use chrono::{DateTime, Local, NaiveDate, TimeZone, Utc};
use serde::Deserialize;
use sqlx::SqlitePool;
use tauri::{AppHandle, Emitter};

use crate::google;
use crate::ollama;
use crate::planner;

// ─── Intent detection ─────────────────────────────────────────────────────────

/// Returns true if the message looks like a calendar management request.
/// Uses keyword matching — no LLM call needed for this layer.
pub fn is_calendar_request(message: &str) -> bool {
    let lower = message.to_lowercase();
    let keywords = [
        "schedule", "add event", "create event", "add meeting", "book",
        "appointment", "add to my calendar", "put on my calendar",
        "what's on my calendar", "what do i have", "am i free", "free time",
        "available", "add task", "create task", "remind me", "set a reminder",
        "block time", "reschedule", "cancel event", "delete event",
        "remove from calendar", "when is", "move my", "move the",
        "change the event", "update event", "edit event", "change the time",
        "move event",
        // Natural variants the model misses
        "add a task", "create a task", "create the task", "make a task",
        "make the task", "new task", "add it", "add that",
    ];
    if keywords.iter().any(|kw| lower.contains(kw)) {
        return true;
    }
    // Catch "create/add/make ... task" with words in between (e.g. "create me a task")
    let action_words = ["create", "add", "make", "put", "schedule"];
    if lower.contains("task") && action_words.iter().any(|w| lower.contains(w)) {
        return true;
    }
    // Schedule-everything requests
    let schedule_all_phrases = [
        "schedule all", "plan everything", "schedule everything",
        "plan all my tasks", "schedule my tasks", "schedule all tasks",
        "block time for all", "schedule all my work",
    ];
    if schedule_all_phrases.iter().any(|p| lower.contains(p)) {
        return true;
    }
    false
}

// ─── Intent schema ────────────────────────────────────────────────────────────

/// The structured action the LLM extracts from a user message.
/// Kept intentionally simple — small LLMs handle simple slot-filling well.
#[derive(Debug, Deserialize)]
struct CalendarIntent {
    action: String,
    title: Option<String>,
    date: Option<String>,         // YYYY-MM-DD
    start_time: Option<String>,   // HH:MM 24h
    end_time: Option<String>,     // HH:MM 24h
    duration_minutes: Option<i64>,
    description: Option<String>,
    event_id: Option<String>,
}

// ─── Extraction ───────────────────────────────────────────────────────────────

/// Ask the LLM to extract a structured CalendarIntent from natural language.
/// The prompt is heavily constrained so the small model only has to fill blanks.
async fn extract_intent(message: &str, date_str: &str, model: &str) -> Result<CalendarIntent> {
    let prompt = format!(
        r#"Today is {date}. Parse this calendar/task request into JSON.

Reply with ONLY a JSON object — no explanation, no markdown, no extra text.
Use null for unknown fields. Times are 24-hour format (HH:MM).

JSON schema:
{{
  "action": "create_event" | "update_event" | "delete_event" | "list_events" | "create_task" | "check_availability" | "schedule_all_tasks",
  "title": "string or null",
  "date": "YYYY-MM-DD or null",
  "start_time": "HH:MM or null",
  "end_time": "HH:MM or null",
  "duration_minutes": number or null,
  "description": "string or null",
  "event_id": null
}}

Request: "{msg}"

JSON:"#,
        date = date_str,
        msg = message
    );

    // Try up to 2 times — small LLMs sometimes add markdown fences or trailing text
    for attempt in 0..2 {
        let raw = ollama::chat_oneshot(model, &prompt).await?;
        if let Ok(intent) = parse_intent_json(&raw) {
            return Ok(intent);
        }
        if attempt == 0 {
            // Brief pause before retry
            tokio::time::sleep(std::time::Duration::from_millis(200)).await;
        }
    }

    Err(anyhow!("Could not parse calendar intent from LLM response"))
}

fn parse_intent_json(raw: &str) -> Result<CalendarIntent> {
    // Strip markdown fences if present
    let cleaned = raw
        .trim()
        .trim_start_matches("```json")
        .trim_start_matches("```")
        .trim_end_matches("```")
        .trim();

    // Find the JSON object boundaries
    let start = cleaned.find('{').ok_or_else(|| anyhow!("No JSON found"))?;
    let end = cleaned.rfind('}').ok_or_else(|| anyhow!("No JSON found"))? + 1;
    let json_str = &cleaned[start..end];

    serde_json::from_str(json_str).map_err(|e| anyhow!("JSON parse error: {}", e))
}

// ─── Execution ────────────────────────────────────────────────────────────────

async fn execute_intent(
    intent: &CalendarIntent,
    access_token: &str,
    disabled_ids: &[String],
    pool: &SqlitePool,
) -> Result<String> {
    match intent.action.as_str() {
        "list_events" | "check_availability" => {
            let events = google::fetch_calendar_events(access_token, disabled_ids).await?;
            if events.is_empty() {
                return Ok("Your calendar is clear for the next week.".to_string());
            }
            let label = if intent.action == "check_availability" {
                "Scheduled"
            } else {
                "Upcoming events"
            };
            let list = events
                .iter()
                .take(10)
                .map(|e| {
                    let start = format_cal_time(&e.start_time);
                    let end = format_cal_time(&e.end_time);
                    format!("• {} — {} to {} ({})", e.title, start, end, e.calendar_name)
                })
                .collect::<Vec<_>>()
                .join("\n");
            Ok(format!("{}:\n{}", label, list))
        }

        "create_event" => {
            let title = intent
                .title
                .as_deref()
                .ok_or_else(|| anyhow!("I need a title for the event. What should it be called?"))?;

            let date = intent.date.as_deref().ok_or_else(|| {
                anyhow!("I need a date for the event. When should it be scheduled?")
            })?;

            let start = intent.start_time.as_deref().unwrap_or("09:00");
            let end = if let Some(e) = &intent.end_time {
                e.clone()
            } else {
                let dur = intent.duration_minutes.unwrap_or(60);
                add_minutes_to_time(start, dur)
            };

            // Build timezone-naive ISO datetimes (server uses local time)
            let start_iso = format!("{}T{}:00", date, start);
            let end_iso = format!("{}T{}:00", date, end);

            let calendars = google::list_calendars(access_token).await?;
            let cal_id = calendars
                .first()
                .map(|(id, _)| id.clone())
                .unwrap_or_else(|| "primary".to_string());

            google::create_calendar_event(
                access_token,
                &cal_id,
                title,
                &start_iso,
                &end_iso,
                intent.description.as_deref(),
            )
            .await?;

            Ok(format!(
                "Done. Added \"{}\" on {} from {} to {}.",
                title, date, start, end
            ))
        }

        "update_event" => {
            let event_id = intent.event_id.as_deref().ok_or_else(|| {
                anyhow!(
                    "I need to know which event to update. Try listing your events first."
                )
            })?;

            let start_iso = match (&intent.date, &intent.start_time) {
                (Some(d), Some(t)) => Some(format!("{}T{}:00", d, t)),
                _ => None,
            };
            let end_iso = match (&intent.date, &intent.end_time) {
                (Some(d), Some(t)) => Some(format!("{}T{}:00", d, t)),
                (Some(d), None) => {
                    if start_iso.is_some() {
                        let dur = intent.duration_minutes.unwrap_or(60);
                        let start_t = intent.start_time.as_deref().unwrap_or("09:00");
                        Some(format!("{}T{}:00", d, add_minutes_to_time(start_t, dur)))
                    } else {
                        None
                    }
                }
                _ => None,
            };

            google::update_calendar_event(
                access_token,
                "primary",
                event_id,
                intent.title.as_deref(),
                start_iso.as_deref(),
                end_iso.as_deref(),
                intent.description.as_deref(),
            )
            .await?;

            let mut changes = Vec::new();
            if intent.title.is_some() { changes.push("title"); }
            if start_iso.is_some() { changes.push("time"); }
            if intent.description.is_some() { changes.push("description"); }
            let what = if changes.is_empty() { "event".to_string() } else { changes.join(", ") };

            Ok(format!("Updated {} for event {}.", what, event_id))
        }

        "delete_event" => {
            let event_id = intent.event_id.as_deref().ok_or_else(|| {
                anyhow!(
                    "I need an event ID to delete it. Try listing events first to find the right one."
                )
            })?;

            google::delete_calendar_event(access_token, "primary", event_id).await?;
            Ok(format!("Deleted event {}.", event_id))
        }

        "schedule_all_tasks" => {
            // ── Schedule ALL tasks ────────────────────────────────────────────
            // Fetch all incomplete tasks with due dates from the local DB
            let tasks: Vec<(String, String, Option<String>)> = sqlx::query_as(
                "SELECT id, title, due_date FROM tasks_cache
                 WHERE completed = 0 AND due_date IS NOT NULL
                 ORDER BY due_date ASC",
            )
            .fetch_all(pool)
            .await
            .unwrap_or_default();

            if tasks.is_empty() {
                return Ok("No upcoming tasks with due dates found to schedule.".to_string());
            }

            // Fetch default task duration from settings (falls back to 90 min)
            let task_duration_mins: i64 = crate::db::get_setting(pool, "task_duration_minutes")
                .await
                .ok()
                .flatten()
                .and_then(|s| s.parse().ok())
                .unwrap_or(90);

            let now = Utc::now();
            let window_end = now + chrono::Duration::days(30);

            // Fetch all existing events for the next 30 days to avoid double-booking
            let mut live_events = google::fetch_events_in_range(
                access_token,
                disabled_ids,
                &now.to_rfc3339(),
                &window_end.to_rfc3339(),
            )
            .await
            .unwrap_or_default();

            let calendars = google::list_calendars(access_token).await?;
            let cal_id = calendars
                .first()
                .map(|(id, _)| id.clone())
                .unwrap_or_else(|| "primary".to_string());

            let mut scheduled = 0usize;
            let mut already_booked = 0usize;

            for (task_id, title, due_date_str) in &tasks {
                // Skip if a work block is already on the calendar for this task
                let marker = format!("CADEN:task_id={}", task_id);
                if live_events.iter().any(|e| {
                    e.title.starts_with("Work on: ") && e.title.contains(title.as_str())
                        || e.calendar_name == "CADEN"
                }) {
                    // A coarser check — just skip tasks whose work-block title already exists
                    let work_title = format!("Work on: {}", title);
                    if live_events.iter().any(|e| e.title == work_title) {
                        already_booked += 1;
                        continue;
                    }
                }
                let _ = marker;

                let deadline = due_date_str
                    .as_deref()
                    .and_then(|s| {
                        // "YYYY-MM-DDT..." or "YYYY-MM-DD"
                        let date_part = &s[..s.len().min(10)];
                        NaiveDate::parse_from_str(date_part, "%Y-%m-%d").ok()
                    })
                    .and_then(|nd| {
                        Local
                            .from_local_datetime(&nd.and_hms_opt(22, 0, 0).unwrap())
                            .single()
                    })
                    .map(|d| d.with_timezone(&Utc))
                    .unwrap_or(window_end);

                if deadline <= now {
                    continue; // already past due
                }

                let search_until = deadline.min(window_end);
                if let Some((slot_start, slot_end)) = planner::find_free_work_slot(
                    &live_events,
                    now,
                    search_until,
                    task_duration_mins,
                    &crate::db::models::WorkHours::default(),
                ) {
                    let work_title = format!("Work on: {}", title);
                    let desc = format!("CADEN:task_id={}\nScheduled work block.", task_id);
                    if google::create_calendar_event(
                        access_token,
                        &cal_id,
                        &work_title,
                        &slot_start.to_rfc3339(),
                        &slot_end.to_rfc3339(),
                        Some(&desc),
                    )
                    .await
                    .is_ok()
                    {
                        // Register this new block as busy so subsequent tasks respect it
                        live_events.push(crate::google::CalendarEvent {
                            id: String::new(),
                            title: work_title,
                            start_time: slot_start.to_rfc3339(),
                            end_time: slot_end.to_rfc3339(),
                            all_day: false,
                            calendar_name: "CADEN".to_string(),
                        });
                        scheduled += 1;
                    }
                }
            }

            let skip_note = if already_booked > 0 {
                format!(" ({} already had work blocks.)", already_booked)
            } else {
                String::new()
            };
            Ok(format!(
                "Scheduled {} work block{} across your calendar for the next 30 days.{}",
                scheduled,
                if scheduled == 1 { "" } else { "s" },
                skip_note
            ))
        }

        "create_task" => {
            let title = intent
                .title
                .as_deref()
                .ok_or_else(|| anyhow!("I need a title for the task. What should it be?"))?;

            // ── 1. Create Google Task ─────────────────────────────────────────
            let lists = google::get_task_lists(access_token).await?;
            let list_id = lists
                .first()
                .map(|(id, _)| id.clone())
                .unwrap_or_else(|| "@default".to_string());

            let due = intent.date.as_ref().map(|d| format!("{}T00:00:00Z", d));

            google::create_task(
                access_token,
                &list_id,
                title,
                due.as_deref(),
                intent.description.as_deref(),
            )
            .await?;

            let due_label = intent
                .date
                .as_ref()
                .map(|d| format!(" due {}", d))
                .unwrap_or_default();

            // ── 2. Find a free work slot and block calendar time ───────────────
            let now = Utc::now();

            // Deadline = end of due date (local 22:00), or 7 days if no date given
            let deadline = intent
                .date
                .as_deref()
                .and_then(|s| NaiveDate::parse_from_str(s, "%Y-%m-%d").ok())
                .and_then(|nd| {
                    Local
                        .from_local_datetime(&nd.and_hms_opt(22, 0, 0).unwrap())
                        .single()
                })
                .map(|d| d.with_timezone(&Utc))
                .unwrap_or_else(|| now + chrono::Duration::days(7));

            // Duration: from intent, or from settings, or 90 min default
            let duration_mins = intent.duration_minutes.unwrap_or_else(|| {
                // Try to read from DB settings synchronously — use a reasonable default otherwise
                90
            });

            // Fetch existing events up to the deadline to avoid conflicts
            let time_max = deadline.to_rfc3339();
            let events = google::fetch_events_in_range(
                access_token,
                disabled_ids,
                &now.to_rfc3339(),
                &time_max,
            )
            .await
            .unwrap_or_default();

            let block_note = if let Some((slot_start, slot_end)) =
                planner::find_free_work_slot(&events, now, deadline, duration_mins, &crate::db::models::WorkHours::default())
            {
                let calendars = google::list_calendars(access_token).await?;
                let cal_id = calendars
                    .first()
                    .map(|(id, _)| id.clone())
                    .unwrap_or_else(|| "primary".to_string());

                let work_title = format!("Work on: {}", title);
                let desc = format!("CADEN-scheduled work block for: {}", title);
                let _ = google::create_calendar_event(
                    access_token,
                    &cal_id,
                    &work_title,
                    &slot_start.to_rfc3339(),
                    &slot_end.to_rfc3339(),
                    Some(&desc),
                )
                .await;

                format!(
                    " Blocked {} min on {} at {} to work on it.",
                    duration_mins,
                    fmt_date_utc(slot_start),
                    fmt_time_utc(slot_start),
                )
            } else {
                " (Couldn't find a free slot before the deadline — check your calendar.)".to_string()
            };

            Ok(format!("Added task: \"{}\"{}.{}", title, due_label, block_note))
        }

        _ => Err(anyhow!("not_calendar")),
    }
}

// ─── Public entry point ───────────────────────────────────────────────────────

/// Handle a calendar management request end-to-end.
/// Emits `ollama-token` / `ollama-done` / `ollama-error` events like normal chat.
pub async fn handle_request(
    app: AppHandle,
    message: String,
    access_token: String,
    model: String,
    date: String,
    disabled_ids: Vec<String>,
    pool: SqlitePool,
) -> Result<()> {
    let intent = match extract_intent(&message, &date, &model).await {
        Ok(i) => i,
        Err(_) => {
            // Extraction failed — fall back to regular chat
            return Err(anyhow!("not_calendar"));
        }
    };

    // If the LLM decided this isn't a calendar action, fall back
    if intent.action == "none" || intent.action.is_empty() {
        return Err(anyhow!("not_calendar"));
    }

    let result = execute_intent(&intent, &access_token, &disabled_ids, &pool).await;

    let response = match result {
        Ok(msg) => msg,
        Err(e) => {
            let msg = e.to_string();
            if msg == "not_calendar" {
                return Err(anyhow!("not_calendar"));
            }
            // Check for permission errors (user needs to reconnect with write scope)
            if msg.contains("403") || msg.contains("insufficient") || msg.contains("Forbidden") {
                "Calendar write access denied. You need to reconnect Google with updated permissions — go to Settings and click Connect Google again.".to_string()
            } else {
                // Surface the error as a user-readable message
                format!("Couldn't complete that: {}", msg)
            }
        }
    };

    let _ = app.emit("ollama-token", &response);
    let _ = app.emit("ollama-done", ());
    Ok(())
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

/// Format a UTC DateTime as a human-readable date string ("Mon Mar 30")
fn fmt_date_utc(dt: DateTime<Utc>) -> String {
    dt.with_timezone(&Local)
        .format("%a %b %-d")
        .to_string()
}

/// Format a UTC DateTime as a human-readable time string ("2:30 PM")
fn fmt_time_utc(dt: DateTime<Utc>) -> String {
    dt.with_timezone(&Local)
        .format("%-I:%M %p")
        .to_string()
}

fn format_cal_time(iso: &str) -> String {
    if iso.len() < 16 {
        return iso.to_string();
    }
    // "2026-03-20T14:30:00Z" → "2:30 PM"
    let h: u32 = iso[11..13].parse().unwrap_or(0);
    let m: u32 = iso[14..16].parse().unwrap_or(0);
    let suffix = if h < 12 { "AM" } else { "PM" };
    let h12 = match h % 12 { 0 => 12, x => x };
    format!("{}:{:02} {}", h12, m, suffix)
}

/// Add `minutes` to a "HH:MM" string, returning a new "HH:MM" string.
fn add_minutes_to_time(time: &str, minutes: i64) -> String {
    let parts: Vec<&str> = time.split(':').collect();
    let h: i64 = parts.first().and_then(|s| s.parse().ok()).unwrap_or(9);
    let m: i64 = parts.get(1).and_then(|s| s.parse().ok()).unwrap_or(0);
    let total = h * 60 + m + minutes;
    format!("{:02}:{:02}", (total / 60) % 24, total % 60)
}
