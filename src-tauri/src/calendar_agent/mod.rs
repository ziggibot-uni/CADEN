//! Calendar agentic framework for CADEN.
//!
//! Design philosophy: since the local LLM (llama3.1:8b) is small and not capable
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
use serde::Deserialize;
use tauri::{AppHandle, Emitter};

use crate::google;
use crate::ollama;

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
    ];
    keywords.iter().any(|kw| lower.contains(kw))
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
  "action": "create_event" | "delete_event" | "list_events" | "create_task" | "check_availability",
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

async fn execute_intent(intent: &CalendarIntent, access_token: &str) -> Result<String> {
    match intent.action.as_str() {
        "list_events" | "check_availability" => {
            let events = google::fetch_calendar_events(access_token).await?;
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

        "delete_event" => {
            let event_id = intent.event_id.as_deref().ok_or_else(|| {
                anyhow!(
                    "I need an event ID to delete it. Try listing events first to find the right one."
                )
            })?;

            google::delete_calendar_event(access_token, "primary", event_id).await?;
            Ok(format!("Deleted event {}.", event_id))
        }

        "create_task" => {
            let title = intent
                .title
                .as_deref()
                .ok_or_else(|| anyhow!("I need a title for the task. What should it be?"))?;

            let lists = google::get_task_lists(access_token).await?;
            let list_id = lists
                .first()
                .map(|(id, _)| id.clone())
                .unwrap_or_else(|| "@default".to_string());

            let due = intent
                .date
                .as_ref()
                .map(|d| format!("{}T00:00:00Z", d));

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
                .map(|d| format!(", due {}", d))
                .unwrap_or_default();

            Ok(format!("Added task: \"{}\"{}.", title, due_label))
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

    let result = execute_intent(&intent, &access_token).await;

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

fn format_cal_time(iso: &str) -> String {
    if iso.len() < 16 {
        return iso.to_string();
    }
    // "2026-03-20T14:30:00Z" → "14:30"
    iso[11..16].to_string()
}

/// Add `minutes` to a "HH:MM" string, returning a new "HH:MM" string.
fn add_minutes_to_time(time: &str, minutes: i64) -> String {
    let parts: Vec<&str> = time.split(':').collect();
    let h: i64 = parts.first().and_then(|s| s.parse().ok()).unwrap_or(9);
    let m: i64 = parts.get(1).and_then(|s| s.parse().ok()).unwrap_or(0);
    let total = h * 60 + m + minutes;
    format!("{:02}:{:02}", (total / 60) % 24, total % 60)
}
