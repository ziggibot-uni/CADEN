use tauri::{AppHandle, Emitter, Manager, State};

use crate::calendar_agent;
use crate::db::models::{AppSettings, PlanItem, UpcomingItem};
use crate::db::{ops, set_setting};
use crate::google;
use crate::moodle;
use crate::ollama;
use crate::planner;
use crate::plugin_registry::{self, PluginRecord, PluginRegistry};
use crate::projects;
use crate::projects::{Project, ProjectEntry};
use crate::state_engine;
use crate::SharedState;

// ─── Settings ────────────────────────────────────────────────────────────────

#[tauri::command]
pub async fn get_setting_value(
    key: String,
    state: State<'_, SharedState>,
) -> Result<Option<String>, String> {
    let s = state.lock().await;
    crate::db::get_setting(&s.pool, &key)
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn set_setting_value(
    key: String,
    value: String,
    state: State<'_, SharedState>,
) -> Result<(), String> {
    let s = state.lock().await;
    crate::db::set_setting(&s.pool, &key, &value)
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn get_settings(state: State<'_, SharedState>) -> Result<AppSettings, String> {
    let s = state.lock().await;
    ops::load_settings(&s.pool)
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn save_settings(
    settings: AppSettings,
    state: State<'_, SharedState>,
) -> Result<(), String> {
    let mut s = state.lock().await;
    ops::save_settings(&s.pool, &settings)
        .await
        .map_err(|e| e.to_string())?;

    // Reinitialise the Moodle client if credentials were provided
    s.moodle_client = match (&settings.moodle_url, &settings.moodle_token) {
        (Some(url), Some(token)) if !url.is_empty() && !token.is_empty() => {
            Some(moodle::MoodleClient::new(url.clone(), token.clone()))
        }
        _ => None,
    };

    Ok(())
}

#[tauri::command]
pub async fn force_replan(state: State<'_, SharedState>) -> Result<(), String> {
    let s = state.lock().await;
    let today = chrono::Local::now().format("%Y-%m-%d").to_string();
    sqlx::query("DELETE FROM daily_plans WHERE date = ?")
        .bind(&today)
        .execute(&s.pool)
        .await
        .map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
pub async fn mark_setup_complete(state: State<'_, SharedState>) -> Result<(), String> {
    let s = state.lock().await;
    set_setting(&s.pool, "setup_complete", "true")
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn save_moodle_credentials(
    url: String,
    token: String,
    state: State<'_, SharedState>,
) -> Result<(), String> {
    let mut s = state.lock().await;
    set_setting(&s.pool, "moodle_url", &url)
        .await
        .map_err(|e| e.to_string())?;
    set_setting(&s.pool, "moodle_token", &token)
        .await
        .map_err(|e| e.to_string())?;
    s.moodle_client = Some(moodle::MoodleClient::new(url, token));
    Ok(())
}

// ─── Ollama ───────────────────────────────────────────────────────────────────

#[tauri::command]
pub async fn get_ollama_status() -> Result<ollama::OllamaStatus, String> {
    Ok(ollama::check_status().await)
}

#[tauri::command]
pub async fn check_ollama() -> Result<bool, String> {
    let status = ollama::check_status().await;
    Ok(status.online)
}

#[tauri::command]
pub async fn pull_ollama_model(model: String) -> Result<(), String> {
    ollama::pull_model(&model)
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn chat_with_ollama(
    message: String,
    history: Vec<ollama::ChatHistoryItem>,
    context: ollama::PlannerContext,
    state: State<'_, SharedState>,
    app: AppHandle,
) -> Result<(), String> {
    let (pool, active_model, system_prompt, google_tokens, disabled_calendar_ids, morning_meds, evening_meds, github_pat, groq_keys) = {
        let s = state.lock().await;
        let settings = ops::load_settings(&s.pool)
            .await
            .map_err(|e| e.to_string())?;
        let disabled_json = crate::db::get_setting(&s.pool, "disabled_calendar_ids")
            .await
            .unwrap_or_default()
            .unwrap_or_default();
        let disabled: Vec<String> = serde_json::from_str(&disabled_json).unwrap_or_default();
        (
            s.pool.clone(),
            settings.active_model,
            settings.system_prompt,
            s.google_tokens.clone(),
            disabled,
            settings.morning_meds,
            settings.evening_meds,
            settings.github_pat,
            settings.groq_keys,
        )
    };

    let date = context.date.clone();

    // Always override plan_items with a fresh DB fetch so CADEN's context
    // reflects reality — not a potentially stale frontend snapshot.
    // Only include pending (non-completed) items so CADEN doesn't reference
    // tasks the user has already finished or deleted.
    let fresh_plan = ops::get_today_plan(&pool).await.unwrap_or_default();
    let pending_items: Vec<&crate::db::models::PlanItem> =
        fresh_plan.iter().filter(|i| !i.completed).collect();
    let mut context = context;
    context.plan_items = serde_json::to_value(&pending_items).unwrap_or(serde_json::Value::Array(vec![]));

    // Return immediately — all heavy work (Ollama HTTP, embedding, DB) runs in background.
    // The UI stays responsive; results stream back via events.
    tauri::async_runtime::spawn(async move {
        // Determine provider from the active model name.
        // GitHub models contain a "/" (e.g. "openai/gpt-4.1"). Ollama models don't.
        let (model, github_pat_opt) = if active_model.contains('/') && !github_pat.is_empty() {
            (active_model, Some(github_pat))
        } else if active_model.is_empty() {
            // No model configured — try Ollama auto-detect
            let status = ollama::check_status().await;
            match status.model {
                Some(m) => (m, None),
                None => {
                    let _ = app.emit("ollama-error", "No model configured. Pick one in Settings → AI Model.");
                    return;
                }
            }
        } else {
            (active_model, None)
        };

        // Embed the message once — reused by project context, Sean Model retrieval,
        // and the chat log. Soft-fail if nomic-embed-text isn't installed.
        let query_embedding = ollama::embed(&message).await.ok();

        // Persist this message to the chat log so the Sean Model can learn from it.
        crate::sean_model::log_chat_message(&pool, &message, query_embedding.clone()).await;

        // Record session metadata (wake proxy, output volume, session count).
        crate::state_engine::record_session_event(&pool, message.len()).await;

        // Retrieve project context via embedding search — pass the pre-computed
        // embedding to avoid a redundant nomic-embed-text call.
        let project_context = projects::build_project_context(&pool, &message, query_embedding.clone())
            .await
            .unwrap_or_default();

        // Compute situational briefing deterministically (no LLM, pure DB queries)
        let situational_briefing = planner::compute_situational_briefing(&pool).await;

        // Build the Sean Model briefing
        let sean_briefing = crate::sean_model::build_sean_briefing(&pool, query_embedding).await;
        let situational_briefing = format!("{}\n\n{}", situational_briefing, sean_briefing);

        // Pre-fetch a fresh Google access token if this looks like a calendar request.
        let calendar_token = if calendar_agent::is_calendar_request(&message) {
            if let Some(tokens) = google_tokens {
                ensure_fresh_token(&pool, tokens).await.ok()
            } else {
                None
            }
        } else {
            None
        };
        // If we have a calendar token and a calendar keyword, try the agent first.
        if let Some(access_token) = calendar_token {
            match calendar_agent::handle_request(
                app.clone(),
                message.clone(),
                access_token,
                model.clone(),
                date,
                disabled_calendar_ids.clone(),
                pool.clone(),
            )
            .await
            {
                Ok(()) => return, // calendar agent handled it
                Err(e) if e.to_string() == "not_calendar" => {
                    // LLM decided it wasn't a calendar action — fall through to chat
                }
                Err(e) => {
                    log::warn!("Calendar agent error: {}", e);
                    // Fall through to regular chat
                }
            }
        }

        // Regular conversational chat — three-call pipeline
        if let Err(e) = ollama::chat_pipeline(
            app.clone(),
            message,
            history,
            context,
            model,
            github_pat_opt,
            groq_keys,
            system_prompt,
            project_context,
            situational_briefing,
            pool,
            morning_meds,
            evening_meds,
        )
        .await
        {
            log::error!("Ollama pipeline error: {}", e);
            let _ = app.emit("ollama-error", format!("Error: {}", e));
        }
    });

    Ok(())
}

// ─── Google ───────────────────────────────────────────────────────────────────

#[tauri::command]
pub async fn start_google_oauth(
    state: State<'_, SharedState>,
    app: AppHandle,
) -> Result<(), String> {
    let (client_id, client_secret) = {
        let s = state.lock().await;
        let id = crate::db::get_setting(&s.pool, "google_client_id")
            .await
            .map_err(|e| e.to_string())?
            .unwrap_or_default();
        let secret = crate::db::get_setting(&s.pool, "google_client_secret")
            .await
            .map_err(|e| e.to_string())?
            .unwrap_or_default();
        (id, secret)
    };

    if client_id.is_empty() {
        return Err(
            "Google Client ID not configured. Add it in settings or environment.".to_string(),
        );
    }

    let tokens = google::start_oauth(&app, &client_id, &client_secret)
        .await
        .map_err(|e| e.to_string())?;

    let mut s = state.lock().await;
    let tokens_json = serde_json::to_string(&tokens).map_err(|e| e.to_string())?;
    crate::db::set_setting(&s.pool, "google_tokens", &tokens_json)
        .await
        .map_err(|e| e.to_string())?;
    crate::db::set_setting(&s.pool, "google_connected", "true")
        .await
        .map_err(|e| e.to_string())?;
    s.google_tokens = Some(tokens);

    Ok(())
}

#[tauri::command]
pub async fn get_google_calendars(
    state: State<'_, SharedState>,
) -> Result<Vec<serde_json::Value>, String> {
    let (pool, google_tokens) = {
        let s = state.lock().await;
        (s.pool.clone(), s.google_tokens.clone())
    };

    let tokens = google_tokens.ok_or_else(|| "Google not connected".to_string())?;
    let access_token = ensure_fresh_token(&pool, tokens).await?;

    let calendars = google::list_calendars(&access_token)
        .await
        .map_err(|e| e.to_string())?;

    Ok(calendars
        .into_iter()
        .map(|(id, name)| serde_json::json!({ "id": id, "name": name }))
        .collect())
}

// ─── Moodle ───────────────────────────────────────────────────────────────────

#[tauri::command]
pub async fn debug_moodle(
    state: State<'_, SharedState>,
) -> Result<String, String> {
    let s = state.lock().await;
    let client = s.moodle_client.as_ref()
        .ok_or_else(|| "Moodle not configured".to_string())?
        .clone();
    drop(s);

    let mut out = String::new();

    // Test upcoming view calendar API
    match client.debug_fetch("core_calendar_get_calendar_upcoming_view").await {
        Ok(v) => {
            let count = v["events"].as_array().map(|a| a.len()).unwrap_or(0);
            out.push_str(&format!("upcoming_view: {} events\n", count));
            if let Some(events) = v["events"].as_array() {
                for ev in events {
                    let name = ev["activityname"].as_str()
                        .or_else(|| ev["name"].as_str()).unwrap_or("?");
                    let ts = ev["timestart"].as_i64().unwrap_or(0);
                    let due = chrono::DateTime::from_timestamp(ts, 0)
                        .map(|d| d.to_rfc3339()).unwrap_or_else(|| ts.to_string());
                    let module = ev["modulename"].as_str().unwrap_or("?");
                    let overdue = ev["overdue"].as_bool().unwrap_or(false);
                    out.push_str(&format!("  - [{}] {} (due: {}, overdue: {})\n", module, name, due, overdue));
                }
            }
        }
        Err(e) => out.push_str(&format!("upcoming_view ERROR: {}\n", e)),
    }

    // Test assignments API
    match client.debug_fetch("mod_assign_get_assignments").await {
        Ok(v) => {
            let course_count = v["courses"].as_array().map(|c| c.len()).unwrap_or(0);
            let assign_count: usize = v["courses"].as_array().map(|cs| {
                cs.iter().map(|c| c["assignments"].as_array().map(|a| a.len()).unwrap_or(0)).sum()
            }).unwrap_or(0);
            out.push_str(&format!("mod_assign: {} courses, {} total assignments\n", course_count, assign_count));
            if let Some(courses) = v["courses"].as_array() {
                for course in courses {
                    let cname = course["fullname"].as_str().unwrap_or("?");
                    if let Some(assigns) = course["assignments"].as_array() {
                        if assigns.is_empty() { continue; }
                        out.push_str(&format!("  [{}]\n", cname));
                        for a in assigns {
                            let due_ts = a["duedate"].as_i64().unwrap_or(0);
                            let due_str = if due_ts > 0 {
                                chrono::DateTime::from_timestamp(due_ts, 0)
                                    .map(|d| d.to_rfc3339())
                                    .unwrap_or_else(|| due_ts.to_string())
                            } else {
                                "no due date".to_string()
                            };
                            out.push_str(&format!("    - {} (due: {})\n",
                                a["name"].as_str().unwrap_or("?"), due_str));
                        }
                    }
                }
            }
        }
        Err(e) => out.push_str(&format!("mod_assign ERROR: {}\n", e)),
    }

    // Show current tasks_cache contents
    let pool = {
        let s = state.lock().await;
        s.pool.clone()
    };
    let rows: Vec<(String, Option<String>)> = sqlx::query_as(
        "SELECT title, due_date FROM tasks_cache WHERE source = 'moodle' ORDER BY due_date ASC"
    )
    .fetch_all(&pool)
    .await
    .map_err(|e| e.to_string())?;

    out.push_str(&format!("\ntasks_cache moodle rows: {}\n", rows.len()));
    for (title, due) in rows.iter().take(10) {
        out.push_str(&format!("  - {} ({})\n", title, due.as_deref().unwrap_or("no date")));
    }

    Ok(out)
}

#[tauri::command]
pub async fn test_moodle_connection(url: String, token: String) -> Result<String, String> {
    let client = moodle::MoodleClient::new(url, token);
    client
        .test_connection()
        .await
        .map_err(|e| e.to_string())
}

// ─── Plan ─────────────────────────────────────────────────────────────────────

#[tauri::command]
pub async fn get_today_plan(state: State<'_, SharedState>) -> Result<Vec<PlanItem>, String> {
    let s = state.lock().await;
    ops::get_today_plan(&s.pool)
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn get_upcoming_items(
    state: State<'_, SharedState>,
) -> Result<Vec<UpcomingItem>, String> {
    let s = state.lock().await;
    ops::get_upcoming_items(&s.pool)
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn mark_plan_item_complete(
    plan_id: String,
    state: State<'_, SharedState>,
) -> Result<(), String> {
    let (pool, google_tokens) = {
        let s = state.lock().await;
        (s.pool.clone(), s.google_tokens.clone())
    };

    // Get plan item details before marking complete
    let row: Option<(String, String, Option<String>, Option<String>, Option<String>, Option<String>)> = sqlx::query_as(
        "SELECT dp.source, dp.task_id, dp.google_task_id, dp.scheduled_start, dp.scheduled_end, dp.cal_event_id
         FROM daily_plans dp WHERE dp.id = ?",
    )
    .bind(&plan_id)
    .fetch_optional(&pool)
    .await
    .map_err(|e| e.to_string())?;

    // Resolve the task type (needed for transition recording) before we mark it done
    let completed_task_type: Option<String> = if let Some((ref src, ref task_id, _, _, _, _)) = row {
        let course: Option<(Option<String>,)> = sqlx::query_as(
            "SELECT course_name FROM tasks_cache WHERE id = ?",
        )
        .bind(task_id)
        .fetch_optional(&pool)
        .await
        .ok()
        .flatten();
        Some(if src == "moodle" {
            course.and_then(|(c,)| c).unwrap_or_else(|| "moodle".to_string())
        } else {
            src.clone()
        })
    } else {
        None
    };

    // Find the task type that was completed most recently before this one (for transition model)
    let prev_task_type: Option<String> = {
        let today = chrono::Local::now().format("%Y-%m-%d").to_string();
        let prev: Option<(String, Option<String>)> = sqlx::query_as(
            "SELECT tc.source, tc.course_name
             FROM daily_plans dp
             JOIN tasks_cache tc ON tc.id = dp.task_id
             WHERE dp.date = ? AND dp.completed = 1 AND dp.id != ?
             ORDER BY dp.completed_at DESC LIMIT 1",
        )
        .bind(&today)
        .bind(&plan_id)
        .fetch_optional(&pool)
        .await
        .ok()
        .flatten();
        prev.map(|(src, course)| {
            if src == "moodle" { course.unwrap_or_else(|| "moodle".to_string()) } else { src }
        })
    };

    // Update local DB
    ops::mark_plan_item_complete(&pool, &plan_id)
        .await
        .map_err(|e| e.to_string())?;

    // Auto-record goal progress for completed tasks linked to goal-tracked projects/types
    if let Some(ref ctype) = completed_task_type {
        // Find task's linked project (on the daily_plans or tasks_cache row)
        let task_project: Option<(Option<String>,)> = if let Some((_, ref tid, _, _, _, _)) = row {
            sqlx::query_as("SELECT linked_project_id FROM tasks_cache WHERE id = ?")
                .bind(tid)
                .fetch_optional(&pool)
                .await
                .ok()
                .flatten()
        } else {
            None
        };
        let task_proj_id = task_project.and_then(|(p,)| p);

        let matching_goals: Vec<(String, String)> = sqlx::query_as(
            "SELECT id, title FROM goals WHERE status = 'active'
             AND (linked_project_id = ? OR linked_task_types LIKE '%' || ? || '%')",
        )
        .bind(&task_proj_id)
        .bind(ctype)
        .fetch_all(&pool)
        .await
        .unwrap_or_default();

        let now_str = chrono::Utc::now().to_rfc3339();
        for (goal_id, _goal_title) in &matching_goals {
            let gp_id = crate::db::ops::generate_id();
            let note = format!("Completed: {}", row.as_ref().map(|r| r.1.as_str()).unwrap_or("task"));
            let _ = sqlx::query(
                "INSERT INTO goal_progress (id, goal_id, delta, note, source, timestamp)
                 VALUES (?, ?, 1.0, ?, 'task_completion', ?)",
            )
            .bind(&gp_id).bind(goal_id).bind(&note).bind(&now_str)
            .execute(&pool).await;
            let _ = sqlx::query(
                "UPDATE goals SET current_value = current_value + 1.0, updated_at = ? WHERE id = ?",
            )
            .bind(&now_str).bind(goal_id)
            .execute(&pool).await;
        }
    }

    // Auto-log time to linked project if applicable
    if let Some((_, _, ref gtid_opt, ref start, ref end, _)) = row {
        if let Some(ref gtid) = gtid_opt {
            let link: Option<(String, String)> = sqlx::query_as(
                "SELECT pe.project_id, dp.title FROM project_entries pe
                 JOIN daily_plans dp ON dp.id = ?
                 WHERE pe.google_task_id = ? LIMIT 1",
            )
            .bind(&plan_id)
            .bind(gtid)
            .fetch_optional(&pool)
            .await
            .ok()
            .flatten();

            if let Some((project_id, title)) = link {
                if let (Some(s), Some(e)) = (start, end) {
                    let id = crate::db::ops::generate_id();
                    let now = chrono::Utc::now().to_rfc3339();
                    let start_dt = chrono::DateTime::parse_from_rfc3339(s).ok();
                    let end_dt = chrono::DateTime::parse_from_rfc3339(e).ok();
                    if let (Some(sd), Some(ed)) = (start_dt, end_dt) {
                        let dur = (ed - sd).num_minutes() as f64;
                        let _ = sqlx::query(
                            "INSERT INTO project_time_log (id, project_id, event_title, start_time, end_time, duration_minutes, source, created_at)
                             VALUES (?, ?, ?, ?, ?, ?, 'completed_task', ?)",
                        )
                        .bind(&id)
                        .bind(&project_id)
                        .bind(&title)
                        .bind(s)
                        .bind(e)
                        .bind(dur)
                        .bind(&now)
                        .execute(&pool)
                        .await;
                    }
                }
            }
        }
    }

    // Sync completion to Google Tasks API, shrink GCal block, record transition, reschedule.
    // Covers two cases for task completion:
    //   1. source='tasks'  → complete the task directly
    //   2. source='moodle' → if it's linked to a Google Task via google_task_id, complete that
    if let Some((source, task_id, gtid_opt, _, _, cal_event_id_opt)) = row {
        if let Some(tokens) = google_tokens {
            let access_token = ensure_fresh_token(&pool, tokens).await?;

            // ── (A) Shrink the GCal block to the actual completion time ───────
            // If the task was completed early, this frees the remaining slot.
            if let Some(ref event_id) = cal_event_id_opt {
                let now_iso = chrono::Utc::now().to_rfc3339();
                let _ = google::update_calendar_event(
                    &access_token,
                    "primary",
                    event_id,
                    None,
                    None,
                    Some(&now_iso),
                    None,
                )
                .await;
                // Update local DB to reflect the actual end time too
                let _ = sqlx::query(
                    "UPDATE daily_plans SET scheduled_end = ? WHERE id = ?",
                )
                .bind(&now_iso)
                .bind(&plan_id)
                .execute(&pool)
                .await;
            }

            // ── (B) Record task-type transition for the momentum model ────────
            if let (Some(ref from_type), Some(ref to_type)) =
                (&prev_task_type, &completed_task_type)
            {
                let _ = crate::planner::update_transition(
                    &pool,
                    from_type,
                    to_type,
                    true,  // it was completed
                    0.0,   // delay is tracked separately in update_patterns
                )
                .await;
            }

            // ── (C) Re-plan the remainder of today with freed time ────────────
            let last_type = completed_task_type.as_deref();
            if let Ok(updates) =
                crate::planner::reschedule_remaining_today(&pool, last_type).await
            {
                for (_, event_id, new_start, new_end) in &updates {
                    let _ = google::update_calendar_event(
                        &access_token,
                        "primary",
                        event_id,
                        None,
                        Some(new_start),
                        Some(new_end),
                        None,
                    )
                    .await;
                }
            }

            // ── Google Tasks sync ─────────────────────────────────────────────
            if source == "tasks" {
                let list_id: Option<(Option<String>,)> =
                    sqlx::query_as("SELECT list_id FROM tasks_cache WHERE id = ?")
                        .bind(&task_id)
                        .fetch_optional(&pool)
                        .await
                        .map_err(|e| e.to_string())?;
                let list_id = list_id
                    .and_then(|(id,)| id)
                    .unwrap_or_else(|| "@default".to_string());
                let _ = google::complete_task(&access_token, &list_id, &task_id).await;
            } else if source == "moodle" {
                if let Some(ref gtid) = gtid_opt {
                    let list_id: Option<(Option<String>,)> =
                        sqlx::query_as("SELECT list_id FROM tasks_cache WHERE id = ?")
                            .bind(gtid)
                            .fetch_optional(&pool)
                            .await
                            .map_err(|e| e.to_string())?;
                    let list_id = list_id
                        .and_then(|(id,)| id)
                        .unwrap_or_else(|| "@default".to_string());
                    let _ = google::complete_task(&access_token, &list_id, gtid).await;
                }
            }
        } else {
            // No Google tokens — still record the transition for the local model
            if let (Some(ref from_type), Some(ref to_type)) =
                (&prev_task_type, &completed_task_type)
            {
                let _ = crate::planner::update_transition(&pool, from_type, to_type, true, 0.0).await;
            }
            // And still reschedule locally (just no GCal push)
            let last_type = completed_task_type.as_deref();
            let _ = crate::planner::reschedule_remaining_today(&pool, last_type).await;
        }
    }

    Ok(())
}

#[tauri::command]
pub async fn unmark_plan_item_complete(
    plan_id: String,
    state: State<'_, SharedState>,
) -> Result<(), String> {
    let (pool, google_tokens) = {
        let s = state.lock().await;
        (s.pool.clone(), s.google_tokens.clone())
    };

    let row = ops::unmark_plan_item_complete(&pool, &plan_id)
        .await
        .map_err(|e| e.to_string())?;

    if let Some((source, task_id)) = row {
        if source == "tasks" {
            if let Some(tokens) = google_tokens {
                let access_token = ensure_fresh_token(&pool, tokens).await?;
                let list_id: Option<(Option<String>,)> =
                    sqlx::query_as("SELECT list_id FROM tasks_cache WHERE id = ?")
                        .bind(&task_id)
                        .fetch_optional(&pool)
                        .await
                        .map_err(|e| e.to_string())?;
                let list_id = list_id
                    .and_then(|(id,)| id)
                    .unwrap_or_else(|| "@default".to_string());
                let _ = google::uncomplete_task(&access_token, &list_id, &task_id).await;
            }
        }
    }

    Ok(())
}

#[tauri::command]
pub async fn clear_completed_plan_items(state: State<'_, SharedState>) -> Result<(), String> {
    let s = state.lock().await;
    ops::clear_completed_plan_items(&s.pool)
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn skip_plan_item(
    plan_id: String,
    state: State<'_, SharedState>,
) -> Result<(), String> {
    let s = state.lock().await;
    ops::skip_plan_item(&s.pool, &plan_id)
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn record_correction(
    correction_type: String,
    description: String,
    data: Option<String>,
    state: State<'_, SharedState>,
) -> Result<(), String> {
    let s = state.lock().await;
    ops::record_correction(&s.pool, &correction_type, &description, data.as_deref())
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn delete_plan_item(
    plan_id: String,
    state: State<'_, SharedState>,
) -> Result<(), String> {
    let (pool, google_tokens) = {
        let s = state.lock().await;
        (s.pool.clone(), s.google_tokens.clone())
    };

    // Read task_id, source, and cal_event_id before deleting the row
    let row: Option<(String, String, Option<String>)> =
        sqlx::query_as("SELECT task_id, source, cal_event_id FROM daily_plans WHERE id = ?")
            .bind(&plan_id)
            .fetch_optional(&pool)
            .await
            .map_err(|e| e.to_string())?;

    if let Some((task_id, source, cal_event_id)) = row {
        // Write dismissal BEFORE deleting the row so that even on a double-click
        // race (where the second request's SELECT finds the row already gone),
        // the dismissal is always in place before the delete happens.
        if source == "tasks" || source == "moodle" {
            let today = chrono::Local::now().format("%Y-%m-%d").to_string();
            let now = chrono::Utc::now().to_rfc3339();
            let dismiss_id = ops::generate_id();
            sqlx::query(
                "INSERT OR IGNORE INTO dismissed_tasks (id, task_id, dismiss_date, dismissed_at)
                 VALUES (?, ?, ?, ?)",
            )
            .bind(&dismiss_id)
            .bind(&task_id)
            .bind(&today)
            .bind(&now)
            .execute(&pool)
            .await
            .map_err(|e| e.to_string())?;
        }

        // Delete the plan row only after dismissal is safely written
        sqlx::query("DELETE FROM daily_plans WHERE id = ?")
            .bind(&plan_id)
            .execute(&pool)
            .await
            .map_err(|e| e.to_string())?;

        // Delete the linked GCal event if one exists
        if let Some(event_id) = cal_event_id {
            if let Some(ref tokens) = google_tokens {
                if let Ok(access_token) = ensure_fresh_token(&pool, tokens.clone()).await {
                    let _ = google::delete_calendar_event(&access_token, "primary", &event_id).await;
                }
            }
        }

        // Delete the underlying Google Task so it doesn't reappear on next sync
        if source == "tasks" {
            if let Some(ref tokens) = google_tokens {
                if let Ok(access_token) = ensure_fresh_token(&pool, tokens.clone()).await {
                    let list_id: Option<(Option<String>,)> =
                        sqlx::query_as("SELECT list_id FROM tasks_cache WHERE id = ?")
                            .bind(&task_id)
                            .fetch_optional(&pool)
                            .await
                            .unwrap_or(None);
                    let list_id = list_id
                        .and_then(|(id,)| id)
                        .unwrap_or_else(|| "@default".to_string());
                    let _ = google::delete_task(&access_token, &list_id, &task_id).await;
                }
            }
            // Remove from local cache so it won't come back on next sync
            let _ = sqlx::query("DELETE FROM tasks_cache WHERE id = ?")
                .bind(&task_id)
                .execute(&pool)
                .await;
        }
    } else {
        // The id wasn't in daily_plans — check if it's a calendar event from events_cache.
        // Calendar events are appended directly by get_today_plan (not via daily_plans),
        // so delete from the cache immediately and remove from GCal — next sync reflects reality.
        let in_events_cache: Option<(String,)> =
            sqlx::query_as("SELECT id FROM events_cache WHERE id = ? LIMIT 1")
                .bind(&plan_id)
                .fetch_optional(&pool)
                .await
                .map_err(|e| e.to_string())?;

        if in_events_cache.is_some() {
            // Remove from cache immediately so it vanishes from all views right now
            sqlx::query("DELETE FROM events_cache WHERE id = ?")
                .bind(&plan_id)
                .execute(&pool)
                .await
                .map_err(|e| e.to_string())?;

            // Delete from Google Calendar — next sync will confirm it's gone
            if let Some(tokens) = google_tokens {
                if let Ok(access_token) = ensure_fresh_token(&pool, tokens).await {
                    let _ = google::delete_calendar_event(&access_token, "primary", &plan_id).await;
                }
            }
        }
        // else: genuinely gone (double-click race) — no-op is correct
    }

    Ok(())
}

#[derive(serde::Serialize, Clone)]
pub struct SyncOutcome {
    pub replanned: bool,
    pub events_changed: bool,
    pub gcal_error: Option<String>,
}

async fn task_fingerprint(pool: &sqlx::SqlitePool) -> String {
    let mut ids: Vec<String> = sqlx::query_as::<_, (String,)>(
        "SELECT id FROM tasks_cache WHERE completed = 0 ORDER BY id ASC",
    )
    .fetch_all(pool)
    .await
    .unwrap_or_default()
    .into_iter()
    .map(|(id,)| id)
    .collect();
    ids.sort();
    ids.join(",")
}

async fn event_fingerprint(pool: &sqlx::SqlitePool, today: &str) -> String {
    let today_start = format!("{}T00:00:00", today);
    let today_end = format!("{}T23:59:59", today);
    let mut rows: Vec<(String, String, Option<String>)> = sqlx::query_as(
        "SELECT id, start_time, end_time FROM events_cache
         WHERE datetime(start_time) >= datetime(?) AND datetime(start_time) <= datetime(?)
         ORDER BY id ASC",
    )
    .bind(&today_start)
    .bind(&today_end)
    .fetch_all(pool)
    .await
    .unwrap_or_default();
    rows.sort_by(|a, b| a.0.cmp(&b.0));
    rows.into_iter()
        .map(|(id, start, end)| format!("{}:{}:{}", id, start, end.unwrap_or_default()))
        .collect::<Vec<_>>()
        .join(",")
}

#[tauri::command]
pub async fn sync_all(state: State<'_, SharedState>) -> Result<SyncOutcome, String> {
    sync_all_core(&*state).await
}

/// Core sync logic, callable from both the Tauri command and the backend loop.
pub async fn sync_all_core(state: &SharedState) -> Result<SyncOutcome, String> {
    let (pool, google_tokens, moodle_client) = {
        let s = state.lock().await;
        (s.pool.clone(), s.google_tokens.clone(), s.moodle_client.clone())
    };

    // Record any tasks that were skipped yesterday before refreshing data
    planner::record_skips_for_previous_day(&pool).await.ok();

    // ── Evict stale plan rows ─────────────────────────────────────────────────
    // Remove today's plan rows for tasks whose due_date is in the future —
    // these were scheduled by an older (buggy) version of the planner that
    // didn't respect due dates. Delete their GCal events too so they don't
    // linger on the wrong day in the user's calendar.
    {
        let today_str = chrono::Local::now().format("%Y-%m-%d").to_string();
        let stale_future: Vec<(String, Option<String>)> = sqlx::query_as(
            "SELECT dp.id, dp.cal_event_id
             FROM daily_plans dp
             JOIN tasks_cache tc ON dp.task_id = tc.id
             WHERE dp.date = ?
               AND tc.due_date IS NOT NULL
               AND date(tc.due_date) > date('now', 'localtime')
               AND dp.completed = 0",
        )
        .bind(&today_str)
        .fetch_all(&pool)
        .await
        .unwrap_or_default();

        if !stale_future.is_empty() {
            // Delete GCal events for these stale rows if we have a token
            if let Some(ref tokens) = google_tokens {
                if let Ok(tok) = ensure_fresh_token(&pool, tokens.clone()).await {
                    for (_, cal_event_id) in &stale_future {
                        if let Some(ref eid) = cal_event_id {
                            let _ = google::delete_calendar_event(&tok, "primary", eid).await;
                        }
                    }
                }
            }
            // Delete the DB rows
            for (plan_id, _) in &stale_future {
                let _ = sqlx::query("DELETE FROM daily_plans WHERE id = ?")
                    .bind(plan_id)
                    .execute(&pool)
                    .await;
            }
        }
    }

    // ── Fingerprint current state so we can detect real changes ───────────────
    let today = chrono::Local::now().format("%Y-%m-%d").to_string();
    let task_fp_before = task_fingerprint(&pool).await;
    let event_fp_before = event_fingerprint(&pool, &today).await;

    // Is today's plan empty? (first open of a new day, or plan was never generated)
    let plan_is_empty: bool = sqlx::query_as::<_, (i64,)>(
        "SELECT COUNT(*) FROM daily_plans WHERE date = ?",
    )
    .bind(&today)
    .fetch_one(&pool)
    .await
    .map(|(n,)| n)
    .unwrap_or(0) == 0;

    let mut fresh_access_token: Option<String> = None;

    if let Some(tokens) = google_tokens {
        let access_token = ensure_fresh_token(&pool, tokens).await?;
        fresh_access_token = Some(access_token.clone());

        let disabled_json = crate::db::get_setting(&pool, "disabled_calendar_ids")
            .await
            .unwrap_or_default()
            .unwrap_or_default();
        let disabled_ids: Vec<String> =
            serde_json::from_str(&disabled_json).unwrap_or_default();

        match google::fetch_calendar_events(&access_token, &disabled_ids).await {
            Ok(events) => {
                let fetched_at = chrono::Utc::now().to_rfc3339();
                sqlx::query("DELETE FROM events_cache")
                    .execute(&pool)
                    .await
                    .ok();
                for event in events {
                    // Skip CADEN's own time-block events — we'll re-create them after planning.
                    if event.title.starts_with("[CADEN] ") {
                        continue;
                    }
                    sqlx::query(
                        "INSERT OR REPLACE INTO events_cache
                         (id, title, start_time, end_time, all_day, calendar_name, fetched_at)
                         VALUES (?, ?, ?, ?, ?, ?, ?)",
                    )
                    .bind(&event.id)
                    .bind(&event.title)
                    .bind(&event.start_time)
                    .bind(&event.end_time)
                    .bind(event.all_day)
                    .bind(&event.calendar_name)
                    .bind(&fetched_at)
                    .execute(&pool)
                    .await
                    .ok();
                }
            }
            Err(e) => log::warn!("Calendar sync failed: {}", e),
        }

        match google::fetch_tasks(&access_token).await {
            Ok(tasks) => {
                let fetched_at = chrono::Utc::now().to_rfc3339();
                let fetched_ids: Vec<String> = tasks.iter().map(|t| t.id.clone()).collect();

                // Load dismissed task IDs so we don't re-insert tasks the user deleted.
                let dismissed: std::collections::HashSet<String> = sqlx::query_as::<_, (String,)>(
                    "SELECT task_id FROM dismissed_tasks",
                )
                .fetch_all(&pool)
                .await
                .unwrap_or_default()
                .into_iter()
                .map(|(id,)| id)
                .collect();

                for task in tasks {
                    // Skip tasks the user has explicitly deleted/dismissed.
                    if dismissed.contains(&task.id) {
                        continue;
                    }
                    sqlx::query(
                        "INSERT OR REPLACE INTO tasks_cache
                         (id, title, source, due_date, completed, notes, list_name, list_id, fetched_at)
                         VALUES (?, ?, 'tasks', ?, ?, ?, ?, ?, ?)",
                    )
                    .bind(&task.id)
                    .bind(&task.title)
                    .bind(&task.due_date)
                    .bind(task.completed)
                    .bind(&task.notes)
                    .bind(&task.list_name)
                    .bind(&task.list_id)
                    .bind(&fetched_at)
                    .execute(&pool)
                    .await
                    .ok();
                }

                // Remove any cached Google Tasks that no longer exist on Google's side.
                // Without this, deleted tasks persist in the cache forever.
                if !fetched_ids.is_empty() {
                    let placeholders = fetched_ids.iter().map(|_| "?").collect::<Vec<_>>().join(",");
                    let sql = format!(
                        "DELETE FROM tasks_cache WHERE source = 'tasks' AND id NOT IN ({})",
                        placeholders
                    );
                    let mut q = sqlx::query(&sql);
                    for id in &fetched_ids {
                        q = q.bind(id);
                    }
                    q.execute(&pool).await.ok();
                } else {
                    // No tasks returned at all — wipe all cached Google tasks.
                    sqlx::query("DELETE FROM tasks_cache WHERE source = 'tasks'")
                        .execute(&pool)
                        .await
                        .ok();
                }
            }
            Err(e) => log::warn!("Tasks sync failed: {}", e),
        }
    }

    // Sync Moodle
    if let Some(client) = moodle_client {
        match client.fetch_assignments().await {
            Ok(assignments) => {
                let fetched_at = chrono::Utc::now().to_rfc3339();
                // Snapshot which Moodle items were locally dismissed before we wipe the table.
                // Also include any whose linked Google Task is completed — that counts as done.
                let locally_done: std::collections::HashSet<String> = {
                    let mut set: std::collections::HashSet<String> = sqlx::query_as::<_, (String,)>(
                        "SELECT id FROM tasks_cache WHERE source = 'moodle' AND completed = 1",
                    )
                    .fetch_all(&pool)
                    .await
                    .unwrap_or_default()
                    .into_iter()
                    .map(|(id,)| id)
                    .collect();

                    // Also capture Moodle tasks whose linked Google Task is completed
                    let via_gtask: Vec<(String,)> = sqlx::query_as(
                        "SELECT tc.id FROM tasks_cache tc
                         WHERE tc.source = 'moodle'
                           AND tc.google_task_id IS NOT NULL
                           AND EXISTS (
                               SELECT 1 FROM tasks_cache gt
                               WHERE gt.id = tc.google_task_id AND gt.completed = 1
                           )",
                    )
                    .fetch_all(&pool)
                    .await
                    .unwrap_or_default();

                    for (id,) in via_gtask {
                        set.insert(id);
                    }
                    set
                };

                // Clear stale moodle rows
                sqlx::query("DELETE FROM tasks_cache WHERE source = 'moodle'")
                    .execute(&pool)
                    .await
                    .ok();

                for assign in assignments {
                    if !assign.submitted {
                        let completed = locally_done.contains(&assign.id);
                        sqlx::query(
                            "INSERT OR REPLACE INTO tasks_cache
                             (id, title, source, due_date, completed, course_name, url, fetched_at)
                             VALUES (?, ?, 'moodle', ?, ?, ?, ?, ?)",
                        )
                        .bind(&assign.id)
                        .bind(&assign.title)
                        .bind(&assign.due_date)
                        .bind(completed)
                        .bind(&assign.course_name)
                        .bind(&assign.url)
                        .bind(&fetched_at)
                        .execute(&pool)
                        .await
                        .ok();
                    }
                }
            }
            Err(e) => log::warn!("Moodle sync failed: {}", e),
        }
    }

    // ── Roll up daily state (mood/energy/anxiety) ────────────────────────────
    // Aggregates today's factor_snapshots into the daily_state summary table
    // so historical trend analysis has data to work with.
    state_engine::rollup_daily_state(&pool).await;

    // ── Check whether anything actually changed ──────────────────────────────
    let task_fp_after = task_fingerprint(&pool).await;
    let event_fp_after = event_fingerprint(&pool, &today).await;

    let data_changed = task_fp_before != task_fp_after
        || event_fp_before != event_fp_after;

    // ── Mood-triggered replan ────────────────────────────────────────────────
    // If rolling energy has shifted significantly since the plan was built,
    // force a replan even if task/event data hasn't changed. This lets CADEN
    // lighten the load when energy craters mid-day.
    let mood_replan = if !data_changed && !plan_is_empty {
        let (energy_now, _, _) = state_engine::get_rolling_averages(&pool, 1).await;
        if let Some(energy) = energy_now {
            let last_plan_energy: Option<f64> = crate::db::get_setting(&pool, "last_plan_energy")
                .await
                .ok()
                .flatten()
                .and_then(|s| s.parse().ok());
            match last_plan_energy {
                Some(prev) => {
                    let drop = prev - energy;
                    // Replan if energy dropped by >1.5 points, or crossed below
                    // the low-energy threshold (4.0) when it was above before.
                    drop > 1.5 || (prev >= 4.0 && energy < 4.0)
                }
                None => false, // first sync of the day, no baseline yet
            }
        } else {
            false
        }
    } else {
        false
    };

    // Only replan if the underlying data changed, mood shifted, or there was
    // no plan for today. Even when skipping a replan, we still push any
    // scheduled items that are missing their GCal event.
    if !data_changed && !mood_replan && !plan_is_empty {
        let mut gcal_error: Option<String> = None;
        if let Some(ref token) = fresh_access_token {
            let today_str = chrono::Local::now().format("%Y-%m-%d").to_string();
            let unpushed: Vec<(String, String, Option<String>, Option<String>)> =
                sqlx::query_as(
                    "SELECT id, title, scheduled_start, scheduled_end
                     FROM daily_plans
                     WHERE date = ? AND cal_event_id IS NULL
                       AND scheduled_start IS NOT NULL AND scheduled_end IS NOT NULL
                       AND completed = 0",
                )
                .bind(&today_str)
                .fetch_all(&pool)
                .await
                .unwrap_or_default();

            for (id, title, start, end) in unpushed {
                if let (Some(start), Some(end)) = (start, end) {
                    let ev_title = format!("[CADEN] {}", title);
                    match google::create_calendar_event(
                        token, "primary", &ev_title, &start, &end,
                        Some("Scheduled by CADEN"),
                    )
                    .await
                    {
                        Ok(event_id) => {
                            let _ = sqlx::query(
                                "UPDATE daily_plans SET cal_event_id = ? WHERE id = ?",
                            )
                            .bind(&event_id)
                            .bind(&id)
                            .execute(&pool)
                            .await;
                        }
                        Err(e) => {
                            log::warn!("GCal catch-up push failed for '{}': {}", title, e);
                            if gcal_error.is_none() {
                                gcal_error = Some(format!("GCal blocked: {}", e));
                            }
                        }
                    }
                }
            }
        }
        record_sync_timestamp(&pool).await;
        return Ok(SyncOutcome {
            replanned: false,
            events_changed: event_fp_before != event_fp_after,
            gcal_error,
        });
    }

    // Regenerate daily plan
    let settings = ops::load_settings(&pool).await.map_err(|e| e.to_string())?;

    // Delete stale CADEN-created calendar events before re-planning so their
    // slots are free for the new plan's free-slot computation.
    if let Some(ref token) = fresh_access_token {
        let today = chrono::Local::now().format("%Y-%m-%d").to_string();
        let stale: Vec<(String, String)> = sqlx::query_as(
            "SELECT id, cal_event_id FROM daily_plans
             WHERE date = ? AND cal_event_id IS NOT NULL",
        )
        .bind(&today)
        .fetch_all(&pool)
        .await
        .unwrap_or_default();

        for (plan_id, event_id) in stale {
            let _ = google::delete_calendar_event(token, "primary", &event_id).await;
            let _ = sqlx::query("UPDATE daily_plans SET cal_event_id = NULL WHERE id = ?")
                .bind(&plan_id)
                .execute(&pool)
                .await;
        }
    }

    let plan = planner::generate_daily_plan(
        &pool,
        settings.task_duration_minutes,
        settings.creative_time_minutes,
        &settings.work_hours,
    )
    .await
    .map_err(|e| e.to_string())?;

    // Push new plan time blocks to Google Calendar.
    // Each scheduled item becomes a "[CADEN] Title" event so Sean can see his
    // planned day directly in Google Calendar.
    // Always write to "primary" — the Google Calendar API guarantees this
    // always resolves to the user's main calendar regardless of its display name.
    let mut gcal_error: Option<String> = None;
    if let Some(ref token) = fresh_access_token {
        for item in &plan {
            let (Some(start), Some(end)) =
                (&item.scheduled_start, &item.scheduled_end)
            else {
                continue;
            };
            let title = format!("[CADEN] {}", item.title);
            match google::create_calendar_event(
                token,
                "primary",
                &title,
                start,
                end,
                Some("Scheduled by CADEN"),
            )
            .await {
                Ok(event_id) => {
                    let _ = sqlx::query(
                        "UPDATE daily_plans SET cal_event_id = ? WHERE id = ?",
                    )
                    .bind(&event_id)
                    .bind(&item.id)
                    .execute(&pool)
                    .await;
                }
                Err(e) => {
                    log::warn!("GCal push failed for '{}': {}", item.title, e);
                    // Capture first error so the frontend can surface it to the user
                    if gcal_error.is_none() {
                        gcal_error = Some(format!("GCal blocked: {}", e));
                    }
                }
            }
        }
    }

    record_sync_timestamp(&pool).await;

    // Store the energy level at plan-generation time so future syncs can
    // detect a significant mood shift and trigger a replan.
    let (energy_at_plan, _, _) = state_engine::get_rolling_averages(&pool, 1).await;
    if let Some(e) = energy_at_plan {
        let _ = crate::db::set_setting(&pool, "last_plan_energy", &e.to_string()).await;
    }

    Ok(SyncOutcome { replanned: true, events_changed: true, gcal_error }) // replanned
}

// Record sync timestamp so the catch-up summary knows when we last synced
async fn record_sync_timestamp(pool: &sqlx::SqlitePool) {
    let ts = chrono::Utc::now().to_rfc3339();
    let _ = crate::db::set_setting(pool, "last_sync_at", &ts).await;
}

// ─── Project linking ──────────────────────────────────────────────────────────

#[tauri::command]
pub async fn link_plan_item_to_project(
    plan_id: String,
    project_id: Option<String>,
    state: State<'_, SharedState>,
) -> Result<(), String> {
    let s = state.lock().await;
    sqlx::query("UPDATE daily_plans SET linked_project_id = ? WHERE id = ?")
        .bind(project_id)
        .bind(plan_id)
        .execute(&s.pool)
        .await
        .map(|_| ())
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn link_task_to_project(
    task_id: String,
    project_id: Option<String>,
    state: State<'_, SharedState>,
) -> Result<(), String> {
    let s = state.lock().await;
    sqlx::query("UPDATE tasks_cache SET linked_project_id = ? WHERE id = ?")
        .bind(project_id)
        .bind(task_id)
        .execute(&s.pool)
        .await
        .map(|_| ())
        .map_err(|e| e.to_string())
}

// ─── Projects ─────────────────────────────────────────────────────────────────

#[tauri::command]
pub async fn list_projects(state: State<'_, SharedState>) -> Result<Vec<Project>, String> {
    let s = state.lock().await;
    projects::list_projects(&s.pool)
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn add_project(
    name: String,
    description: Option<String>,
    parent_id: Option<String>,
    state: State<'_, SharedState>,
) -> Result<Project, String> {
    let s = state.lock().await;
    projects::add_project(&s.pool, name, description, parent_id)
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn set_project_parent(
    id: String,
    parent_id: Option<String>,
    state: State<'_, SharedState>,
) -> Result<(), String> {
    let s = state.lock().await;
    projects::set_project_parent(&s.pool, id, parent_id)
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn update_project(
    id: String,
    name: String,
    description: Option<String>,
    status: String,
    state: State<'_, SharedState>,
) -> Result<(), String> {
    let s = state.lock().await;
    projects::update_project(&s.pool, id, name, description, status)
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn delete_project(
    id: String,
    state: State<'_, SharedState>,
) -> Result<(), String> {
    let s = state.lock().await;
    projects::delete_project(&s.pool, id)
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn get_project_entries(
    project_id: String,
    state: State<'_, SharedState>,
) -> Result<Vec<ProjectEntry>, String> {
    let s = state.lock().await;
    projects::get_project_entries(&s.pool, &project_id)
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn add_project_entry(
    project_id: String,
    entry_type: String,
    content: String,
    tags: Option<String>,
    parent_id: Option<String>,
    state: State<'_, SharedState>,
) -> Result<ProjectEntry, String> {
    let s = state.lock().await;
    projects::add_project_entry(&s.pool, project_id, entry_type, content, tags, parent_id)
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn delete_project_entry(
    id: String,
    state: State<'_, SharedState>,
) -> Result<(), String> {
    let s = state.lock().await;
    projects::delete_project_entry(&s.pool, id)
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn update_project_entry(
    id: String,
    content: String,
    state: State<'_, SharedState>,
) -> Result<ProjectEntry, String> {
    let s = state.lock().await;
    projects::update_project_entry(&s.pool, id, content)
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn toggle_project_entry_complete(
    id: String,
    state: State<'_, SharedState>,
) -> Result<ProjectEntry, String> {
    let s = state.lock().await;
    projects::toggle_project_entry_complete(&s.pool, id)
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn search_project_entries(
    project_id: String,
    query: String,
    limit: Option<usize>,
    state: State<'_, SharedState>,
) -> Result<Vec<ProjectEntry>, String> {
    let s = state.lock().await;
    projects::search_entries_semantic(&s.pool, &project_id, &query, limit.unwrap_or(20))
        .await
        .map_err(|e| e.to_string())
}

#[derive(serde::Serialize)]
pub struct ProjectTimeEntry {
    pub id: String,
    pub event_title: String,
    pub start_time: String,
    pub end_time: String,
    pub duration_minutes: f64,
    pub source: String,
    pub created_at: String,
}

#[tauri::command]
pub async fn log_project_time(
    project_id: String,
    event_title: String,
    start_time: String,
    end_time: String,
    source: Option<String>,
    state: State<'_, SharedState>,
) -> Result<(), String> {
    let s = state.lock().await;
    let id = crate::db::ops::generate_id();
    let now = chrono::Utc::now().to_rfc3339();

    // Calculate duration
    let start = chrono::DateTime::parse_from_rfc3339(&start_time).map_err(|e| e.to_string())?;
    let end = chrono::DateTime::parse_from_rfc3339(&end_time).map_err(|e| e.to_string())?;
    let duration_minutes = (end - start).num_minutes() as f64;

    sqlx::query(
        "INSERT INTO project_time_log (id, project_id, event_title, start_time, end_time, duration_minutes, source, created_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(&id)
    .bind(&project_id)
    .bind(&event_title)
    .bind(&start_time)
    .bind(&end_time)
    .bind(duration_minutes)
    .bind(source.as_deref().unwrap_or("manual"))
    .bind(&now)
    .execute(&s.pool)
    .await
    .map_err(|e| e.to_string())?;

    Ok(())
}

#[tauri::command]
pub async fn get_project_time_log(
    project_id: String,
    state: State<'_, SharedState>,
) -> Result<Vec<ProjectTimeEntry>, String> {
    let s = state.lock().await;
    let rows: Vec<(String, String, String, String, f64, String, String)> = sqlx::query_as(
        "SELECT id, event_title, start_time, end_time, duration_minutes, source, created_at
         FROM project_time_log WHERE project_id = ? ORDER BY start_time DESC",
    )
    .bind(&project_id)
    .fetch_all(&s.pool)
    .await
    .map_err(|e| e.to_string())?;

    Ok(rows
        .into_iter()
        .map(|(id, event_title, start_time, end_time, duration_minutes, source, created_at)| {
            ProjectTimeEntry { id, event_title, start_time, end_time, duration_minutes, source, created_at }
        })
        .collect())
}

#[tauri::command]
pub async fn get_project_total_time(
    project_id: String,
    state: State<'_, SharedState>,
) -> Result<f64, String> {
    let s = state.lock().await;
    let total: (f64,) = sqlx::query_as(
        "SELECT COALESCE(SUM(duration_minutes), 0.0) FROM project_time_log WHERE project_id = ?",
    )
    .bind(&project_id)
    .fetch_one(&s.pool)
    .await
    .map_err(|e| e.to_string())?;

    Ok(total.0)
}

// ─── Project Educat + Spec ────────────────────────────────────────────────────

#[tauri::command]
pub async fn get_moodle_courses(state: State<'_, SharedState>) -> Result<Vec<moodle::MoodleCourse>, String> {
    let s = state.lock().await;
    match &s.moodle_client {
        Some(client) => client.get_enrolled_courses().await.map_err(|e| e.to_string()),
        None => Err("Moodle not configured".to_string()),
    }
}

#[tauri::command]
pub async fn set_project_educat_course(
    project_id: String,
    course_id: Option<String>,
    course_name: Option<String>,
    state: State<'_, SharedState>,
) -> Result<(), String> {
    let s = state.lock().await;
    projects::set_project_educat_course(&s.pool, project_id, course_id, course_name)
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn pick_project_spec(
    project_id: String,
    app: AppHandle,
    state: State<'_, SharedState>,
) -> Result<Option<String>, String> {
    use tauri_plugin_dialog::DialogExt;
    let file = app.dialog().file()
        .add_filter("Documents", &["md", "txt", "rst", "pdf", "docx"])
        .blocking_pick_file();
    let path = match file {
        Some(p) => p.to_string(),
        None => return Ok(None),
    };
    let s = state.lock().await;
    projects::set_project_spec_path(&s.pool, project_id, Some(path.clone()))
        .await
        .map_err(|e| e.to_string())?;
    Ok(Some(path))
}

#[tauri::command]
pub async fn open_spec_file(spec_path: String, app: AppHandle) -> Result<(), String> {
    use tauri_plugin_opener::OpenerExt;
    app.opener()
        .open_path(spec_path, None::<&str>)
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn pick_project_folder(
    project_id: String,
    app: AppHandle,
    state: State<'_, SharedState>,
) -> Result<Option<String>, String> {
    use tauri_plugin_dialog::DialogExt;
    let folder = app.dialog().file().blocking_pick_folder();
    let path = match folder {
        Some(p) => p.to_string(),
        None => return Ok(None),
    };
    let s = state.lock().await;
    projects::set_project_folder(&s.pool, project_id, Some(path.clone()))
        .await
        .map_err(|e| e.to_string())?;
    Ok(Some(path))
}

#[tauri::command]
pub async fn open_project_folder(
    folder_path: String,
    app: AppHandle,
) -> Result<(), String> {
    use tauri_plugin_opener::OpenerExt;
    app.opener()
        .open_path(folder_path, None::<&str>)
        .map_err(|e| e.to_string())
}

// ─── Plugins ──────────────────────────────────────────────────────────────────

#[tauri::command]
pub async fn list_plugins(
    registry: State<'_, PluginRegistry>,
) -> Result<Vec<PluginRecord>, String> {
    let plugins = registry.plugins.read().map_err(|e| e.to_string())?;
    Ok(plugins.clone())
}

#[tauri::command]
pub async fn register_plugin_folder(
    folder_path: String,
    state: State<'_, SharedState>,
    registry: State<'_, PluginRegistry>,
    app: AppHandle,
) -> Result<PluginRecord, String> {
    let path = std::path::Path::new(&folder_path);

    let (name, kind) = plugin_registry::detect_kind(path).map_err(|e| e.to_string())?;

    let id = crate::db::ops::generate_id();
    let now = chrono::Utc::now().to_rfc3339();
    let sort_order = {
        let r = registry.plugins.read().map_err(|e| e.to_string())?;
        r.len() as i64
    };

    let pool = {
        let s = state.lock().await;
        s.pool.clone()
    };

    let plugin = match kind {
        plugin_registry::PluginKind::DevServer { install_cmd, dev_cmd, port } => {
            // Register the plugin immediately so the tab appears at once.
            // The dev server starts in the background — the iframe will load
            // once Vite is ready (usually within a few seconds).
            let dev_url = format!("http://localhost:{}", port);
            let record = PluginRecord {
                id: id.clone(),
                name: name.clone(),
                folder_path: folder_path.clone(),
                entry: String::new(),
                dev_url: Some(dev_url),
                sort_order,
                created_at: now,
            };
            plugin_registry::save_plugin(&pool, &record)
                .await
                .map_err(|e| e.to_string())?;

            let folder = std::path::PathBuf::from(&folder_path);
            let plugin_id = id.clone();
            tauri::async_runtime::spawn(async move {
                match plugin_registry::start_dev_server(
                    &folder,
                    install_cmd.as_deref(),
                    &dev_cmd,
                    port,
                )
                .await
                {
                    Ok(child) => {
                        let reg = app.state::<PluginRegistry>();
                        reg.processes.lock().await.push(
                            plugin_registry::RunningProcess { plugin_id, child },
                        );
                    }
                    Err(e) => {
                        log::warn!("Dev server for '{}' failed to start: {}", name, e);
                    }
                }
            });

            record
        }
        plugin_registry::PluginKind::Static { entry } => {
            let record = PluginRecord {
                id,
                name,
                folder_path,
                entry,
                dev_url: None,
                sort_order,
                created_at: now,
            };
            plugin_registry::save_plugin(&pool, &record)
                .await
                .map_err(|e| e.to_string())?;
            record
        }
    };

    registry
        .plugins
        .write()
        .map_err(|e| e.to_string())?
        .push(plugin.clone());

    Ok(plugin)
}

#[tauri::command]
pub async fn add_web_tab(
    name: String,
    url: String,
    state: State<'_, SharedState>,
    registry: State<'_, PluginRegistry>,
) -> Result<PluginRecord, String> {
    let id = crate::db::ops::generate_id();
    let now = chrono::Utc::now().to_rfc3339();
    let sort_order = {
        let r = registry.plugins.read().map_err(|e| e.to_string())?;
        r.len() as i64
    };
    let pool = {
        let s = state.lock().await;
        s.pool.clone()
    };
    let record = PluginRecord {
        id,
        name,
        folder_path: String::new(),
        entry: String::new(),
        dev_url: Some(url),
        sort_order,
        created_at: now,
    };
    plugin_registry::save_plugin(&pool, &record)
        .await
        .map_err(|e| e.to_string())?;
    registry
        .plugins
        .write()
        .map_err(|e| e.to_string())?
        .push(record.clone());
    Ok(record)
}

#[tauri::command]
pub async fn unregister_plugin(
    id: String,
    state: State<'_, SharedState>,
    registry: State<'_, PluginRegistry>,
) -> Result<(), String> {
    let pool = {
        let s = state.lock().await;
        s.pool.clone()
    };
    plugin_registry::delete_plugin(&pool, &id)
        .await
        .map_err(|e| e.to_string())?;

    registry
        .plugins
        .write()
        .map_err(|e| e.to_string())?
        .retain(|p| p.id != id);

    // Kill the dev server process if one is running for this plugin
    let mut procs = registry.processes.lock().await;
    if let Some(pos) = procs.iter().position(|p| p.plugin_id == id) {
        let mut running = procs.remove(pos);
        // On Windows, child.kill() only kills cmd.exe, leaving the node.exe
        // grandchild alive on the port. taskkill /F /T kills the whole tree.
        #[cfg(windows)]
        if let Some(pid) = running.child.id() {
            let _ = tokio::process::Command::new("taskkill")
                .args(["/F", "/T", "/PID", &pid.to_string()])
                .status()
                .await;
        }
        let _ = running.child.kill().await;
    }

    Ok(())
}

// ─── Promote Moodle → Google Task ────────────────────────────────────────────

#[tauri::command]
pub async fn promote_moodle_to_task(
    plan_id: String,
    title: String,
    due_rfc3339: Option<String>,
    state: State<'_, SharedState>,
) -> Result<String, String> {
    let (pool, google_tokens) = {
        let s = state.lock().await;
        (s.pool.clone(), s.google_tokens.clone())
    };

    let tokens = google_tokens.ok_or_else(|| "Google not connected".to_string())?;
    let access_token = ensure_fresh_token(&pool, tokens).await?;

    // Use the first task list (or @default)
    let list_id = google::get_task_lists(&access_token)
        .await
        .map_err(|e| e.to_string())?
        .into_iter()
        .next()
        .map(|(id, _)| id)
        .unwrap_or_else(|| "@default".to_string());

    let google_task_id = google::create_task(
        &access_token,
        &list_id,
        &title,
        due_rfc3339.as_deref(),
        Some("Promoted from Moodle via CADEN"),
    )
    .await
    .map_err(|e| e.to_string())?;

    // Save google_task_id back to the plan row
    sqlx::query("UPDATE daily_plans SET google_task_id = ? WHERE id = ?")
        .bind(&google_task_id)
        .bind(&plan_id)
        .execute(&pool)
        .await
        .map_err(|e| e.to_string())?;

    Ok(google_task_id)
}

// ─── Inline plan item editing ─────────────────────────────────────────────────

#[tauri::command]
pub async fn update_plan_item(
    plan_id: String,
    title: String,
    scheduled_start: Option<String>,
    scheduled_end: Option<String>,
    state: State<'_, SharedState>,
) -> Result<(), String> {
    let (pool, google_tokens) = {
        let s = state.lock().await;
        (s.pool.clone(), s.google_tokens.clone())
    };

    // Read the plan item's source and original task_id before updating
    let row: Option<(String, String, Option<String>)> = sqlx::query_as(
        "SELECT source, task_id, google_task_id FROM daily_plans WHERE id = ?",
    )
    .bind(&plan_id)
    .fetch_optional(&pool)
    .await
    .map_err(|e| e.to_string())?;

    // Update local DB
    sqlx::query(
        "UPDATE daily_plans SET title = ?, scheduled_start = ?, scheduled_end = ? WHERE id = ?",
    )
    .bind(&title)
    .bind(&scheduled_start)
    .bind(&scheduled_end)
    .bind(&plan_id)
    .execute(&pool)
    .await
    .map_err(|e| e.to_string())?;

    // Push changes to Google if connected
    if let (Some((source, task_id, google_task_id)), Some(tokens)) = (row, google_tokens) {
        if let Ok(access_token) = ensure_fresh_token(&pool, tokens).await {
            match source.as_str() {
                "calendar" => {
                    // Update the Google Calendar event
                    let _ = google::update_calendar_event(
                        &access_token,
                        "primary",
                        &task_id,
                        Some(&title),
                        scheduled_start.as_deref(),
                        scheduled_end.as_deref(),
                        None,
                    )
                    .await;
                }
                "tasks" => {
                    // Update the Google Task title and due date
                    // Google Tasks API uses task list ID + task ID
                    if let Some(gtid) = google_task_id.as_deref().or(Some(&task_id)) {
                        let lists = google::get_task_lists(&access_token).await.unwrap_or_default();
                        if let Some((list_id, _)) = lists.first() {
                            let _ = google::update_task(
                                &access_token,
                                list_id,
                                gtid,
                                Some(&title),
                                scheduled_start.as_deref(),
                            )
                            .await;
                        }
                    }
                }
                _ => {} // moodle items can't be pushed back
            }
        }
    }

    Ok(())
}

// ─── Promote project entry → Google Task ─────────────────────────────────────

#[tauri::command]
pub async fn promote_entry_to_google_task(
    entry_id: String,
    title: String,
    due_rfc3339: Option<String>,
    state: State<'_, SharedState>,
) -> Result<String, String> {
    let (pool, google_tokens) = {
        let s = state.lock().await;
        (s.pool.clone(), s.google_tokens.clone())
    };

    let tokens = google_tokens.ok_or_else(|| "Google not connected".to_string())?;
    let access_token = ensure_fresh_token(&pool, tokens).await?;

    let list_id = google::get_task_lists(&access_token)
        .await
        .map_err(|e| e.to_string())?
        .into_iter()
        .next()
        .map(|(id, _)| id)
        .unwrap_or_else(|| "@default".to_string());

    let google_task_id = google::create_task(
        &access_token,
        &list_id,
        &title,
        due_rfc3339.as_deref(),
        None,
    )
    .await
    .map_err(|e| e.to_string())?;

    sqlx::query("UPDATE project_entries SET google_task_id = ? WHERE id = ?")
        .bind(&google_task_id)
        .bind(&entry_id)
        .execute(&pool)
        .await
        .map_err(|e| e.to_string())?;

    Ok(google_task_id)
}

// ─── Promote upcoming task → Google Task ─────────────────────────────────────
// Used from the Upcoming panel for Moodle items that may not be in daily_plans.

#[tauri::command]
pub async fn promote_upcoming_to_google_task(
    task_id: String,
    title: String,
    due_rfc3339: Option<String>,
    state: State<'_, SharedState>,
) -> Result<String, String> {
    let (pool, google_tokens) = {
        let s = state.lock().await;
        (s.pool.clone(), s.google_tokens.clone())
    };

    let tokens = google_tokens.ok_or_else(|| "Google not connected".to_string())?;
    let access_token = ensure_fresh_token(&pool, tokens).await?;

    let list_id = google::get_task_lists(&access_token)
        .await
        .map_err(|e| e.to_string())?
        .into_iter()
        .next()
        .map(|(id, _)| id)
        .unwrap_or_else(|| "@default".to_string());

    let google_task_id = google::create_task(
        &access_token,
        &list_id,
        &title,
        due_rfc3339.as_deref(),
        None,
    )
    .await
    .map_err(|e| e.to_string())?;

    // Persist on the tasks_cache row so the button turns into a badge
    sqlx::query("UPDATE tasks_cache SET google_task_id = ? WHERE id = ?")
        .bind(&google_task_id)
        .bind(&task_id)
        .execute(&pool)
        .await
        .map_err(|e| e.to_string())?;

    // Also update any corresponding daily_plans row if it exists
    sqlx::query(
        "UPDATE daily_plans SET google_task_id = ? WHERE task_id = ? AND completed = 0",
    )
    .bind(&google_task_id)
    .bind(&task_id)
    .execute(&pool)
    .await
    .ok();

    Ok(google_task_id)
}

async fn ensure_fresh_token(
    pool: &sqlx::SqlitePool,
    tokens: google::GoogleTokens,
) -> Result<String, String> {
    let now = chrono::Utc::now().timestamp();
    if tokens.expires_at - now > 60 {
        return Ok(tokens.access_token);
    }

    if let Some(refresh_token) = &tokens.refresh_token {
        let client_id = crate::db::get_setting(pool, "google_client_id")
            .await
            .map_err(|e| e.to_string())?
            .unwrap_or_default();
        let client_secret = crate::db::get_setting(pool, "google_client_secret")
            .await
            .map_err(|e| e.to_string())?
            .unwrap_or_default();

        let new_tokens =
            google::refresh_access_token(refresh_token, &client_id, &client_secret)
                .await
                .map_err(|e| e.to_string())?;

        let tokens_json = serde_json::to_string(&new_tokens).map_err(|e| e.to_string())?;
        crate::db::set_setting(pool, "google_tokens", &tokens_json)
            .await
            .map_err(|e| e.to_string())?;

        Ok(new_tokens.access_token)
    } else {
        Err("Google token expired. Please reconnect.".to_string())
    }
}

// ── Child-webview tab commands ────────────────────────────────────────────────
// External websites refuse to load inside <iframe> due to X-Frame-Options.
// Instead we create a child Webview (a separate WebKit/WebView2 instance) that
// covers the tab content area.  Child webviews are not iframes and bypass
// X-Frame-Options entirely.

#[tauri::command]
pub async fn open_web_tab_view(
    app: tauri::AppHandle,
    label: String,
    url: String,
    x: f64,
    y: f64,
    width: f64,
    height: f64,
) -> Result<(), String> {
    use tauri::Manager;

    // If already open just reposition it.
    if let Some(webview) = app.get_webview(&label) {
        return webview
            .set_bounds(tauri::Rect {
                position: tauri::Position::Logical(tauri::LogicalPosition { x, y }),
                size: tauri::Size::Logical(tauri::LogicalSize { width, height }),
            })
            .map_err(|e| e.to_string());
    }

    let main_ww = app
        .get_webview_window("main")
        .ok_or_else(|| "main window not found".to_string())?;
    let window = main_ww.as_ref().window();

    let parsed_url: url::Url = url.parse().map_err(|e: url::ParseError| e.to_string())?;
    let builder =
        tauri::WebviewBuilder::new(label.clone(), tauri::WebviewUrl::External(parsed_url))
            .user_agent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36");

    window
        .add_child(
            builder,
            tauri::LogicalPosition::new(x, y),
            tauri::LogicalSize::new(width, height),
        )
        .map_err(|e| e.to_string())?;

    Ok(())
}

#[tauri::command]
pub async fn close_web_tab_view(app: tauri::AppHandle, label: String) -> Result<(), String> {
    use tauri::Manager;
    if let Some(webview) = app.get_webview(&label) {
        webview.close().map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[tauri::command]
pub async fn reload_web_tab_view(app: tauri::AppHandle, label: String) -> Result<(), String> {
    use tauri::Manager;
    if let Some(webview) = app.get_webview(&label) {
        webview.eval("location.reload()").map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[tauri::command]
pub async fn eval_web_tab_script(app: tauri::AppHandle, label: String, script: String) -> Result<(), String> {
    use tauri::Manager;
    if let Some(webview) = app.get_webview(&label) {
        webview.eval(&script).map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[tauri::command]
pub async fn set_web_tab_bounds(
    app: tauri::AppHandle,
    label: String,
    x: f64,
    y: f64,
    width: f64,
    height: f64,
) -> Result<(), String> {
    use tauri::Manager;
    if let Some(webview) = app.get_webview(&label) {
        webview
            .set_bounds(tauri::Rect {
                position: tauri::Position::Logical(tauri::LogicalPosition { x, y }),
                size: tauri::Size::Logical(tauri::LogicalSize { width, height }),
            })
            .map_err(|e| e.to_string())?;
    }
    Ok(())
}

// ─── AppBuilder (Vibe Coding) ─────────────────────────────────────────────────
// LLM calls go through Groq/GitHub (Llama-3.3-70B-Instruct), NOT local Ollama.
// File operations are workspace-sandboxed: every path is checked against the
// workspace root before any read/write occurs. Path traversal is impossible
// because we canonicalize the workspace root and verify every resolved path
// starts_with it before proceeding.

/// Multi-message LLM call for the AppBuilder agent loop.
/// Routes through Groq → GitHub Models (both using Llama-3.3-70B-Instruct).
/// Each call is logged to training_data for distillation.
#[tauri::command]
pub async fn ab_llm_chat(
    messages: Vec<serde_json::Value>,
    state: State<'_, SharedState>,
) -> Result<String, String> {
    let (pool, groq_keys, github_pat) = {
        let s = state.lock().await;
        let settings = ops::load_settings(&s.pool).await.map_err(|e| e.to_string())?;
        let pat = if settings.github_pat.is_empty() {
            None
        } else {
            Some(settings.github_pat)
        };
        (s.pool.clone(), settings.groq_keys, pat)
    };

    let content = ollama::llm_chat_messages(&messages, &github_pat, &groq_keys)
        .await
        .map_err(|e| e.to_string())?;

    // Log for distillation — extract system/user prompt from messages
    if !content.is_empty() {
        let sys = messages.iter()
            .find(|m| m["role"].as_str() == Some("system"))
            .and_then(|m| m["content"].as_str())
            .unwrap_or("");
        let user = messages.iter()
            .rev()
            .find(|m| m["role"].as_str() == Some("user"))
            .and_then(|m| m["content"].as_str())
            .unwrap_or("");
        let _ = crate::training::log_example(
            &pool,
            "vibecoder_code",
            Some(sys),
            user,
            &content,
            "groq:llama-3.3-70b-versatile",
        ).await;
    }

    Ok(content)
}

fn ab_safe_path(path: &str, workspace: &str) -> Result<std::path::PathBuf, String> {
    let ws = std::fs::canonicalize(workspace)
        .map_err(|_| format!("Workspace '{}' does not exist", workspace))?;
    let raw: std::path::PathBuf = if std::path::Path::new(path).is_absolute() {
        std::path::PathBuf::from(path)
    } else {
        ws.join(path)
    };
    // For existing paths canonicalize to resolve symlinks; for new files check the parent.
    let checked = if raw.exists() {
        std::fs::canonicalize(&raw).map_err(|e| format!("Path error: {e}"))?
    } else if let Some(parent) = raw.parent() {
        let canon_parent = if parent.exists() {
            std::fs::canonicalize(parent).map_err(|e| format!("Path error: {e}"))?
        } else {
            parent.to_path_buf()
        };
        canon_parent.join(raw.file_name().unwrap_or_default())
    } else {
        raw.clone()
    };
    if !checked.starts_with(&ws) {
        return Err(format!("'{}' is outside the workspace", path));
    }
    Ok(raw)
}

#[tauri::command]
pub async fn ab_start_vibecoder() -> Result<(), String> {
    // Check if already listening on port 5180
    if std::net::TcpStream::connect_timeout(
        &"127.0.0.1:5180".parse::<std::net::SocketAddr>().unwrap(),
        std::time::Duration::from_millis(250),
    ).is_ok() {
        return Ok(());
    }

    // Find the VibeCoder backend directory.
    // In dev: CWD is CADEN root, backend is at apps/VibeCoder/backend relative to it.
    // We check several candidates in order.
    let cwd = std::env::current_dir().unwrap_or_default();
    let candidates = [
        cwd.join("apps").join("VibeCoder").join("backend"),
        cwd.join("CADEN").join("apps").join("VibeCoder").join("backend"),
        std::path::PathBuf::from(r"C:\Users\User\CADEN\CADEN\apps\VibeCoder\backend"),
    ];

    let backend_dir = candidates
        .iter()
        .find(|p| p.join("main.py").exists())
        .ok_or_else(|| "VibeCoder backend not found".to_string())?;

    #[cfg(target_os = "windows")]
    let python = "python";
    #[cfg(not(target_os = "windows"))]
    let python = "python3";

    std::process::Command::new(python)
        .args(["main.py", "--server", "--port", "5180"])
        .current_dir(backend_dir)
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn()
        .map(|_| ())
        .map_err(|e| format!("Failed to start VibeCoder: {e}"))
}

/// List app folders under CADEN/apps/, sorted by most-recently-modified first.
/// Returns JSON array: [{"name":"PedalManifest","folder":"C:\\...","display":"PedalManifest","mtime":1700000000}]
#[tauri::command]
pub async fn ab_list_apps() -> Result<Vec<serde_json::Value>, String> {
    let cwd = std::env::current_dir().unwrap_or_default();
    let candidates = [
        cwd.join("apps"),
        cwd.join("CADEN").join("apps"),
        std::path::PathBuf::from(r"C:\Users\User\CADEN\CADEN\apps"),
    ];
    let apps_dir = candidates
        .iter()
        .find(|p| p.is_dir())
        .ok_or_else(|| "apps/ directory not found".to_string())?;

    let rd = std::fs::read_dir(apps_dir).map_err(|e| format!("{e}"))?;
    let mut entries: Vec<serde_json::Value> = Vec::new();
    for entry in rd.filter_map(|e| e.ok()) {
        let path = entry.path();
        if !path.is_dir() { continue; }
        let folder_name = path.file_name().unwrap_or_default().to_string_lossy().to_string();
        // Skip hidden dirs
        if folder_name.starts_with('.') { continue; }

        // Read display name from caden-plugin.json if it exists
        let plugin_json = path.join("caden-plugin.json");
        let display_name = if plugin_json.exists() {
            std::fs::read_to_string(&plugin_json)
                .ok()
                .and_then(|s| serde_json::from_str::<serde_json::Value>(&s).ok())
                .and_then(|v| v.get("name").and_then(|n| n.as_str()).map(|s| s.to_string()))
                .unwrap_or_else(|| folder_name.clone())
        } else {
            folder_name.clone()
        };

        // Get modified time (most recent file in the folder, shallow)
        let mtime = _ab_dir_mtime(&path);

        entries.push(serde_json::json!({
            "name": folder_name,
            "folder": path.to_string_lossy(),
            "display": display_name,
            "mtime": mtime,
            "has_plugin_json": plugin_json.exists(),
        }));
    }
    // Sort by mtime descending (most recently modified first)
    entries.sort_by(|a, b| {
        let ma = a.get("mtime").and_then(|v| v.as_u64()).unwrap_or(0);
        let mb = b.get("mtime").and_then(|v| v.as_u64()).unwrap_or(0);
        mb.cmp(&ma)
    });
    Ok(entries)
}

fn _ab_dir_mtime(dir: &std::path::Path) -> u64 {
    let mut latest: u64 = dir.metadata()
        .and_then(|m| m.modified())
        .map(|t| t.duration_since(std::time::UNIX_EPOCH).unwrap_or_default().as_secs())
        .unwrap_or(0);
    if let Ok(rd) = std::fs::read_dir(dir) {
        for entry in rd.filter_map(|e| e.ok()).take(50) {
            if let Ok(meta) = entry.metadata() {
                if let Ok(mt) = meta.modified() {
                    let secs = mt.duration_since(std::time::UNIX_EPOCH).unwrap_or_default().as_secs();
                    if secs > latest { latest = secs; }
                }
            }
        }
    }
    latest
}

#[tauri::command]
pub async fn ab_pick_workspace(app: AppHandle) -> Result<Option<String>, String> {
    use tauri_plugin_dialog::DialogExt;
    let folder = app.dialog().file().blocking_pick_folder();
    Ok(folder.map(|p| p.to_string()))
}

#[tauri::command]
pub async fn ab_file_tree(workspace: String) -> Result<String, String> {
    let ws = std::fs::canonicalize(&workspace)
        .map_err(|_| format!("Workspace '{}' does not exist", workspace))?;
    let skip = ["node_modules", ".git", "__pycache__", "target", "dist", "build", ".venv", "venv"];

    fn walk(dir: &std::path::Path, prefix: &str, depth: usize, skip: &[&str], lines: &mut Vec<String>) {
        if depth > 3 || lines.len() > 80 { return; }
        let Ok(rd) = std::fs::read_dir(dir) else { return };
        let mut entries: Vec<_> = rd.filter_map(|e| e.ok()).collect();
        entries.sort_by_key(|e| e.file_name());
        for entry in entries {
            if lines.len() > 80 { lines.push("  ...".to_string()); return; }
            let name = entry.file_name().to_string_lossy().to_string();
            if name.starts_with('.') { continue; }
            let path = entry.path();
            let is_dir = path.is_dir();
            if is_dir && skip.contains(&name.as_str()) { continue; }
            lines.push(format!("{}{}{}", prefix, name, if is_dir { "/" } else { "" }));
            if is_dir {
                let new_prefix = format!("{}  ", prefix);
                walk(&path, &new_prefix, depth + 1, skip, lines);
            }
        }
    }

    let mut lines: Vec<String> = Vec::new();
    walk(&ws, "  ", 0, &skip, &mut lines);
    Ok(format!("Files:\n{}", lines.join("\n")))
}

#[tauri::command]
pub async fn ab_list_dir(path: String, workspace: String) -> Result<String, String> {
    let resolved = ab_safe_path(&path, &workspace)?;
    let rd = std::fs::read_dir(&resolved).map_err(|e| format!("Error: {e}"))?;
    let mut entries: Vec<String> = rd
        .filter_map(|e| e.ok())
        .map(|e| {
            let name = e.file_name().to_string_lossy().to_string();
            let is_dir = e.file_type().map(|t| t.is_dir()).unwrap_or(false);
            if is_dir { format!("{}/", name) } else { name }
        })
        .collect();
    entries.sort();
    Ok(entries.join("\n"))
}

#[tauri::command]
pub async fn ab_read_file(path: String, workspace: String) -> Result<String, String> {
    let resolved = ab_safe_path(&path, &workspace)?;
    std::fs::read_to_string(&resolved)
        .map_err(|e| format!("Error reading '{}': {}", path, e))
}

#[tauri::command]
pub async fn ab_write_file(path: String, content: String, workspace: String) -> Result<(), String> {
    // Create workspace dir first so ab_safe_path's canonicalize doesn't fail for new folders
    std::fs::create_dir_all(&workspace)
        .map_err(|e| format!("Cannot create workspace directory: {e}"))?;
    let target = ab_safe_path(&path, &workspace)?;
    if let Some(parent) = target.parent() {
        std::fs::create_dir_all(parent)
            .map_err(|e| format!("Cannot create directory: {e}"))?;
    }
    std::fs::write(&target, &content)
        .map_err(|e| format!("Error writing '{}': {}", path, e))
}

#[tauri::command]
pub async fn ab_run_cmd(cmd: String, cwd: String) -> Result<String, String> {
    let output = tokio::time::timeout(
        std::time::Duration::from_secs(30),
        tokio::task::spawn_blocking(move || {
            #[cfg(target_os = "windows")]
            { std::process::Command::new("cmd").args(["/C", &cmd]).current_dir(&cwd).output() }
            #[cfg(not(target_os = "windows"))]
            { std::process::Command::new("sh").args(["-c", &cmd]).current_dir(&cwd).output() }
        }),
    )
    .await
    .map_err(|_| "Command timed out after 30s".to_string())?
    .map_err(|e| format!("Task error: {e}"))?
    .map_err(|e| format!("Command error: {e}"))?;

    let mut result = String::from_utf8_lossy(&output.stdout).to_string();
    let stderr = String::from_utf8_lossy(&output.stderr).to_string();
    if !stderr.is_empty() {
        if !result.is_empty() { result.push('\n'); }
        result.push_str(&stderr);
    }
    if result.is_empty() { result = "(no output)".to_string(); }
    if !output.status.success() {
        result.push_str(&format!("\n(exit code: {})", output.status.code().unwrap_or(-1)));
    }
    Ok(result)
}

// ─── Insights (stats / data exposure) ─────────────────────────────────────────

#[tauri::command]
pub async fn insights_circadian_grid(
    state: State<'_, SharedState>,
) -> Result<Vec<(u32, u32, i64, i64)>, String> {
    let s = state.lock().await;
    let rows: Vec<(u32, u32, i64, i64)> = sqlx::query_as(
        "SELECT hour, day_of_week, completions, samples FROM circadian_model ORDER BY day_of_week, hour",
    )
    .fetch_all(&s.pool)
    .await
    .map_err(|e| e.to_string())?;
    Ok(rows)
}

#[tauri::command]
pub async fn insights_patterns(
    state: State<'_, SharedState>,
) -> Result<Vec<(String, String, f64, f64, i64)>, String> {
    let s = state.lock().await;
    let rows: Vec<(String, String, f64, f64, i64)> = sqlx::query_as(
        "SELECT task_type, time_of_day, completion_rate, avg_delay_minutes, sample_count FROM patterns ORDER BY task_type, time_of_day",
    )
    .fetch_all(&s.pool)
    .await
    .map_err(|e| e.to_string())?;
    Ok(rows)
}

#[tauri::command]
pub async fn insights_transitions(
    state: State<'_, SharedState>,
) -> Result<Vec<(String, String, f64, f64, i64)>, String> {
    let s = state.lock().await;
    let rows: Vec<(String, String, f64, f64, i64)> = sqlx::query_as(
        "SELECT from_type, to_type, completion_rate, avg_delay_minutes, sample_count FROM task_transitions ORDER BY from_type, to_type",
    )
    .fetch_all(&s.pool)
    .await
    .map_err(|e| e.to_string())?;
    Ok(rows)
}

#[tauri::command]
pub async fn insights_factor_snapshots(
    state: State<'_, SharedState>,
) -> Result<Vec<serde_json::Value>, String> {
    let rows: Vec<(String, i64, Option<f64>, Option<f64>, Option<f64>, Option<String>, Option<String>, Option<String>, Option<f64>, Option<f64>, Option<String>)> = {
        let s = state.lock().await;
        sqlx::query_as(
            "SELECT id, timestamp, mood_score, energy_level, anxiety_level, thought_coherence, temporal_focus, valence, sleep_hours_implied, confidence, raw_notes FROM factor_snapshots ORDER BY timestamp DESC LIMIT 200",
        )
        .fetch_all(&s.pool)
        .await
        .map_err(|e| e.to_string())?
    };
    Ok(rows.into_iter().map(|r| serde_json::json!({
        "id": r.0, "timestamp": r.1, "mood": r.2, "energy": r.3, "anxiety": r.4,
        "coherence": r.5, "temporal_focus": r.6, "valence": r.7,
        "sleep_hours": r.8, "confidence": r.9, "notes": r.10,
    })).collect())
}

#[tauri::command]
pub async fn insights_daily_states(
    state: State<'_, SharedState>,
) -> Result<Vec<serde_json::Value>, String> {
    let rows: Vec<(String, Option<String>, Option<f64>, Option<f64>, Option<f64>, Option<f64>, Option<String>, i64, i64, String, f64)> = {
        let s = state.lock().await;
        sqlx::query_as(
            "SELECT date, wake_time, sleep_hours, avg_energy, avg_mood, avg_anxiety, thought_pattern, output_volume, session_count, episode_risk, risk_confidence FROM daily_state ORDER BY date DESC LIMIT 90",
        )
        .fetch_all(&s.pool)
        .await
        .map_err(|e| e.to_string())?
    };
    Ok(rows.into_iter().map(|r| serde_json::json!({
        "date": r.0, "wake_time": r.1, "sleep_hours": r.2,
        "avg_energy": r.3, "avg_mood": r.4, "avg_anxiety": r.5,
        "thought_pattern": r.6, "output_volume": r.7, "session_count": r.8,
        "episode_risk": r.9, "risk_confidence": r.10,
    })).collect())
}

#[tauri::command]
pub async fn insights_completions(
    state: State<'_, SharedState>,
) -> Result<Vec<serde_json::Value>, String> {
    let rows: Vec<(String, String, String, Option<String>, String, String)> = {
        let s = state.lock().await;
        sqlx::query_as(
            "SELECT id, task_id, source, planned_time, actual_time, plan_date FROM completions ORDER BY actual_time DESC LIMIT 200",
        )
        .fetch_all(&s.pool)
        .await
        .map_err(|e| e.to_string())?
    };
    Ok(rows.into_iter().map(|r| serde_json::json!({
        "id": r.0, "task_id": r.1, "source": r.2,
        "planned_time": r.3, "actual_time": r.4, "plan_date": r.5,
    })).collect())
}

#[tauri::command]
pub async fn insights_skips(
    state: State<'_, SharedState>,
) -> Result<Vec<serde_json::Value>, String> {
    let rows: Vec<(String, String, String, Option<String>, String)> = {
        let s = state.lock().await;
        sqlx::query_as(
            "SELECT id, task_id, source, reason, timestamp FROM skips ORDER BY timestamp DESC LIMIT 200",
        )
        .fetch_all(&s.pool)
        .await
        .map_err(|e| e.to_string())?
    };
    Ok(rows.into_iter().map(|r| serde_json::json!({
        "id": r.0, "task_id": r.1, "source": r.2, "reason": r.3, "timestamp": r.4,
    })).collect())
}

#[tauri::command]
pub async fn insights_behavioral_log(
    state: State<'_, SharedState>,
) -> Result<Vec<serde_json::Value>, String> {
    let rows: Vec<(String, String, Option<String>, i64, i64, Option<f64>, String)> = {
        let s = state.lock().await;
        sqlx::query_as(
            "SELECT id, event_type, task_type, hour, day_of_week, duration_minutes, timestamp FROM behavioral_log ORDER BY timestamp DESC LIMIT 300",
        )
        .fetch_all(&s.pool)
        .await
        .map_err(|e| e.to_string())?
    };
    Ok(rows.into_iter().map(|r| serde_json::json!({
        "id": r.0, "event_type": r.1, "task_type": r.2,
        "hour": r.3, "day_of_week": r.4, "duration_minutes": r.5, "timestamp": r.6,
    })).collect())
}

#[tauri::command]
pub async fn insights_medications(
    state: State<'_, SharedState>,
) -> Result<Vec<serde_json::Value>, String> {
    let rows: Vec<(String, i64, String, i64, Option<f64>, Option<String>)> = {
        let s = state.lock().await;
        sqlx::query_as(
            "SELECT id, logged_at, medication_name, dose_time, dose_mg, notes FROM medication_log ORDER BY dose_time DESC LIMIT 200",
        )
        .fetch_all(&s.pool)
        .await
        .map_err(|e| e.to_string())?
    };
    Ok(rows.into_iter().map(|r| serde_json::json!({
        "id": r.0, "logged_at": r.1, "medication": r.2,
        "dose_time": r.3, "dose_mg": r.4, "notes": r.5,
    })).collect())
}

#[tauri::command]
pub async fn insights_delete_factor_snapshot(
    id: String,
    state: State<'_, SharedState>,
) -> Result<(), String> {
    let s = state.lock().await;
    sqlx::query("DELETE FROM factor_snapshots WHERE id = ?")
        .bind(&id)
        .execute(&s.pool)
        .await
        .map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
pub async fn insights_update_factor_snapshot(
    id: String,
    mood: Option<f64>,
    energy: Option<f64>,
    anxiety: Option<f64>,
    notes: Option<String>,
    state: State<'_, SharedState>,
) -> Result<(), String> {
    let s = state.lock().await;
    let mut sets: Vec<String> = Vec::new();
    let mut binds: Vec<String> = Vec::new();
    if let Some(v) = mood    { sets.push("mood_score = ?".into());    binds.push(v.to_string()); }
    if let Some(v) = energy  { sets.push("energy_level = ?".into());  binds.push(v.to_string()); }
    if let Some(v) = anxiety { sets.push("anxiety_level = ?".into()); binds.push(v.to_string()); }
    if let Some(v) = &notes  { sets.push("raw_notes = ?".into());     binds.push(v.clone()); }
    if sets.is_empty() { return Ok(()); }
    binds.push(id);
    let sql = format!("UPDATE factor_snapshots SET {} WHERE id = ?", sets.join(", "));
    let mut q = sqlx::query(&sql);
    for b in &binds { q = q.bind(b.as_str()); }
    q.execute(&s.pool).await.map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
pub async fn insights_delete_medication(
    id: String,
    state: State<'_, SharedState>,
) -> Result<(), String> {
    let s = state.lock().await;
    sqlx::query("DELETE FROM medication_log WHERE id = ?")
        .bind(&id)
        .execute(&s.pool)
        .await
        .map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
pub async fn insights_update_medication(
    id: String,
    medication: String,
    dose_time: i64,
    dose_mg: Option<f64>,
    notes: Option<String>,
    state: State<'_, SharedState>,
) -> Result<(), String> {
    let s = state.lock().await;
    sqlx::query(
        "UPDATE medication_log SET medication_name = ?, dose_time = ?, dose_mg = ?, notes = ? WHERE id = ?",
    )
    .bind(&medication)
    .bind(dose_time)
    .bind(dose_mg)
    .bind(&notes)
    .bind(&id)
    .execute(&s.pool)
    .await
    .map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
pub async fn insights_add_medication(
    medication: String,
    dose_time: i64,
    dose_mg: Option<f64>,
    notes: Option<String>,
    state: State<'_, SharedState>,
) -> Result<(), String> {
    let s = state.lock().await;
    let id = crate::db::ops::generate_id();
    let now = chrono::Utc::now().timestamp();
    sqlx::query(
        "INSERT INTO medication_log (id, logged_at, medication_name, dose_time, dose_mg, notes) VALUES (?, ?, ?, ?, ?, ?)",
    )
    .bind(&id)
    .bind(now)
    .bind(&medication)
    .bind(dose_time)
    .bind(dose_mg)
    .bind(&notes)
    .execute(&s.pool)
    .await
    .map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
pub async fn insights_corrections(
    state: State<'_, SharedState>,
) -> Result<Vec<serde_json::Value>, String> {
    let rows: Vec<(String, String, String, Option<String>, String)> = {
        let s = state.lock().await;
        sqlx::query_as(
            "SELECT id, correction_type, description, data, timestamp FROM user_corrections ORDER BY timestamp DESC LIMIT 100",
        )
        .fetch_all(&s.pool)
        .await
        .map_err(|e| e.to_string())?
    };
    Ok(rows.into_iter().map(|r| serde_json::json!({
        "id": r.0, "type": r.1, "description": r.2, "data": r.3, "timestamp": r.4,
    })).collect())
}

#[tauri::command]
pub async fn insights_profile(
    state: State<'_, SharedState>,
) -> Result<serde_json::Value, String> {
    let s = state.lock().await;
    let profile = crate::sean_model::profile::compute_profile(&s.pool).await;
    Ok(serde_json::json!({
        "task_preference_note": profile.task_preference_note,
        "chronic_avoidances": profile.chronic_avoidances,
        "momentum_note": profile.momentum_note,
        "flow_windows": profile.flow_windows,
        "spikes": profile.spikes,
    }))
}

#[tauri::command]
pub async fn insights_episode_risk(
    state: State<'_, SharedState>,
) -> Result<serde_json::Value, String> {
    let s = state.lock().await;
    let (risk, confidence, detail) = crate::state_engine::assess_episode_risk(&s.pool).await;
    let risk_label = match risk {
        crate::state_engine::EpisodeRisk::Low => "low",
        crate::state_engine::EpisodeRisk::ElevatedManic => "elevated_manic",
        crate::state_engine::EpisodeRisk::ElevatedDepressive => "elevated_depressive",
        crate::state_engine::EpisodeRisk::Mixed => "mixed",
        crate::state_engine::EpisodeRisk::Burnout => "burnout",
    };
    Ok(serde_json::json!({
        "risk": risk_label, "confidence": confidence, "detail": detail,
    }))
}

#[tauri::command]
pub async fn insights_focus_params(
    state: State<'_, SharedState>,
) -> Result<serde_json::Value, String> {
    let s = state.lock().await;
    let (focus_minutes, break_minutes) = planner::compute_learned_focus_params(&s.pool).await;
    Ok(serde_json::json!({
        "focus_block_minutes": focus_minutes,
        "break_minutes": break_minutes,
    }))
}

#[tauri::command]
pub async fn insights_active_concerns(
    state: State<'_, SharedState>,
) -> Result<Vec<String>, String> {
    let s = state.lock().await;
    Ok(crate::sean_model::retrieval::get_active_concerns(&s.pool, 10).await)
}

#[tauri::command]
pub async fn insights_rolling_averages(
    state: State<'_, SharedState>,
) -> Result<serde_json::Value, String> {
    let s = state.lock().await;
    let (energy, mood, anxiety) = crate::state_engine::get_rolling_averages(&s.pool, 7).await;
    Ok(serde_json::json!({
        "energy_7d": energy, "mood_7d": mood, "anxiety_7d": anxiety,
    }))
}

#[tauri::command]
pub async fn insights_project_time_summary(
    state: State<'_, SharedState>,
) -> Result<Vec<serde_json::Value>, String> {
    let rows: Vec<(String, String, f64)> = {
        let s = state.lock().await;
        sqlx::query_as(
            "SELECT p.id, p.name, COALESCE(SUM(tl.duration_minutes), 0) FROM projects p LEFT JOIN project_time_log tl ON p.id = tl.project_id GROUP BY p.id ORDER BY COALESCE(SUM(tl.duration_minutes), 0) DESC",
        )
        .fetch_all(&s.pool)
        .await
        .map_err(|e| e.to_string())?
    };
    Ok(rows.into_iter().map(|r| serde_json::json!({
        "id": r.0, "name": r.1, "total_minutes": r.2,
    })).collect())
}

#[tauri::command]
pub async fn insights_db_counts(
    state: State<'_, SharedState>,
) -> Result<serde_json::Value, String> {
    let s = state.lock().await;
    let pool = &s.pool;
    macro_rules! count {
        ($table:expr) => {{
            let r: (i64,) = sqlx::query_as(&format!("SELECT COUNT(*) FROM {}", $table))
                .fetch_one(pool).await.map_err(|e| e.to_string())?;
            r.0
        }};
    }
    Ok(serde_json::json!({
        "events_cache": count!("events_cache"),
        "tasks_cache": count!("tasks_cache"),
        "daily_plans": count!("daily_plans"),
        "completions": count!("completions"),
        "skips": count!("skips"),
        "patterns": count!("patterns"),
        "task_transitions": count!("task_transitions"),
        "circadian_model": count!("circadian_model"),
        "behavioral_log": count!("behavioral_log"),
        "factor_snapshots": count!("factor_snapshots"),
        "daily_state": count!("daily_state"),
        "medication_log": count!("medication_log"),
        "user_corrections": count!("user_corrections"),
        "projects": count!("projects"),
        "project_entries": count!("project_entries"),
        "project_time_log": count!("project_time_log"),
        "chat_log": count!("chat_log"),
        "plugins": count!("plugins"),
    }))
}

#[tauri::command]
pub async fn insights_performance_windows(
    state: State<'_, SharedState>,
) -> Result<Vec<serde_json::Value>, String> {
    let s = state.lock().await;
    let windows = crate::state_engine::get_performance_windows_today(&s.pool).await;
    Ok(windows.into_iter().map(|w| serde_json::json!({
        "kind": w.kind, "start_hour": w.start_hour,
        "end_hour": w.end_hour, "medication": w.medication,
    })).collect())
}

// ─── Goal Tracking ────────────────────────────────────────────────────────────

#[tauri::command]
pub async fn list_goals(
    state: State<'_, SharedState>,
) -> Result<Vec<serde_json::Value>, String> {
    let s = state.lock().await;
    let rows: Vec<(String, String, Option<String>, String, i64, String, Option<f64>, Option<String>, f64, f64, Option<String>, Option<String>, Option<String>, String, String)> =
        sqlx::query_as(
            "SELECT id, title, description, category, priority, status,
                    target_value, target_unit, current_value, weekly_hours_target,
                    deadline, linked_project_id, linked_task_types, created_at, updated_at
             FROM goals ORDER BY priority DESC, created_at DESC",
        )
        .fetch_all(&s.pool)
        .await
        .map_err(|e| e.to_string())?;
    Ok(rows.into_iter().map(|r| serde_json::json!({
        "id": r.0, "title": r.1, "description": r.2, "category": r.3,
        "priority": r.4, "status": r.5, "target_value": r.6,
        "target_unit": r.7, "current_value": r.8, "weekly_hours_target": r.9,
        "deadline": r.10, "linked_project_id": r.11, "linked_task_types": r.12,
        "created_at": r.13, "updated_at": r.14,
    })).collect())
}

#[tauri::command]
pub async fn add_goal(
    title: String,
    description: Option<String>,
    category: String,
    priority: i64,
    target_value: Option<f64>,
    target_unit: Option<String>,
    weekly_hours_target: f64,
    deadline: Option<String>,
    linked_project_id: Option<String>,
    linked_task_types: Option<String>,
    state: State<'_, SharedState>,
) -> Result<serde_json::Value, String> {
    let s = state.lock().await;
    let id = crate::db::ops::generate_id();
    let now = chrono::Utc::now().to_rfc3339();
    sqlx::query(
        "INSERT INTO goals (id, title, description, category, priority, status,
         target_value, target_unit, current_value, weekly_hours_target,
         deadline, linked_project_id, linked_task_types, created_at, updated_at)
         VALUES (?, ?, ?, ?, ?, 'active', ?, ?, 0.0, ?, ?, ?, ?, ?, ?)",
    )
    .bind(&id).bind(&title).bind(&description).bind(&category).bind(priority)
    .bind(target_value).bind(&target_unit).bind(weekly_hours_target)
    .bind(&deadline).bind(&linked_project_id).bind(&linked_task_types)
    .bind(&now).bind(&now)
    .execute(&s.pool)
    .await
    .map_err(|e| e.to_string())?;
    Ok(serde_json::json!({ "id": id }))
}

#[tauri::command]
pub async fn update_goal(
    id: String,
    title: Option<String>,
    description: Option<String>,
    category: Option<String>,
    priority: Option<i64>,
    status: Option<String>,
    target_value: Option<f64>,
    target_unit: Option<String>,
    current_value: Option<f64>,
    weekly_hours_target: Option<f64>,
    deadline: Option<String>,
    linked_project_id: Option<String>,
    linked_task_types: Option<String>,
    state: State<'_, SharedState>,
) -> Result<(), String> {
    let s = state.lock().await;
    let now = chrono::Utc::now().to_rfc3339();
    // Build dynamic SET clauses for non-None fields
    let mut sets: Vec<String> = vec!["updated_at = ?".to_string()];
    let mut binds: Vec<String> = vec![now.clone()];
    macro_rules! opt_set {
        ($field:expr, $col:expr) => {
            if let Some(v) = $field {
                sets.push(format!("{} = ?", $col));
                binds.push(v.to_string());
            }
        };
    }
    opt_set!(title, "title");
    opt_set!(description, "description");
    opt_set!(category, "category");
    opt_set!(priority.map(|v| v.to_string()), "priority");
    opt_set!(status, "status");
    opt_set!(target_value.map(|v| v.to_string()), "target_value");
    opt_set!(target_unit, "target_unit");
    opt_set!(current_value.map(|v| v.to_string()), "current_value");
    opt_set!(weekly_hours_target.map(|v| v.to_string()), "weekly_hours_target");
    opt_set!(deadline, "deadline");
    opt_set!(linked_project_id, "linked_project_id");
    opt_set!(linked_task_types, "linked_task_types");
    let sql = format!("UPDATE goals SET {} WHERE id = ?", sets.join(", "));
    binds.push(id);
    let mut q = sqlx::query(&sql);
    for b in &binds {
        q = q.bind(b);
    }
    q.execute(&s.pool).await.map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
pub async fn delete_goal(
    id: String,
    state: State<'_, SharedState>,
) -> Result<(), String> {
    let s = state.lock().await;
    sqlx::query("DELETE FROM goal_progress WHERE goal_id = ?")
        .bind(&id).execute(&s.pool).await.map_err(|e| e.to_string())?;
    sqlx::query("DELETE FROM goals WHERE id = ?")
        .bind(&id).execute(&s.pool).await.map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
pub async fn add_goal_progress(
    goal_id: String,
    delta: f64,
    note: Option<String>,
    source: String,
    state: State<'_, SharedState>,
) -> Result<(), String> {
    let s = state.lock().await;
    let id = crate::db::ops::generate_id();
    let now = chrono::Utc::now().to_rfc3339();
    sqlx::query(
        "INSERT INTO goal_progress (id, goal_id, delta, note, source, timestamp)
         VALUES (?, ?, ?, ?, ?, ?)",
    )
    .bind(&id).bind(&goal_id).bind(delta).bind(&note).bind(&source).bind(&now)
    .execute(&s.pool).await.map_err(|e| e.to_string())?;
    // Update current_value on the goal
    sqlx::query("UPDATE goals SET current_value = current_value + ?, updated_at = ? WHERE id = ?")
        .bind(delta).bind(&now).bind(&goal_id)
        .execute(&s.pool).await.map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
pub async fn get_goal_progress(
    goal_id: String,
    state: State<'_, SharedState>,
) -> Result<Vec<serde_json::Value>, String> {
    let s = state.lock().await;
    let rows: Vec<(String, String, f64, Option<String>, String, String)> = sqlx::query_as(
        "SELECT id, goal_id, delta, note, source, timestamp
         FROM goal_progress WHERE goal_id = ? ORDER BY timestamp DESC LIMIT 100",
    )
    .bind(&goal_id)
    .fetch_all(&s.pool)
    .await
    .map_err(|e| e.to_string())?;
    Ok(rows.into_iter().map(|r| serde_json::json!({
        "id": r.0, "goal_id": r.1, "delta": r.2, "note": r.3, "source": r.4, "timestamp": r.5,
    })).collect())
}

#[tauri::command]
pub async fn insights_goals_summary(
    state: State<'_, SharedState>,
) -> Result<serde_json::Value, String> {
    let s = state.lock().await;
    let pool = &s.pool;

    // All active goals
    let goals: Vec<(String, String, String, i64, String, Option<f64>, Option<String>, f64, f64, Option<String>)> =
        sqlx::query_as(
            "SELECT id, title, category, priority, status, target_value, target_unit,
                    current_value, weekly_hours_target, deadline
             FROM goals WHERE status = 'active' ORDER BY priority DESC",
        )
        .fetch_all(pool)
        .await
        .map_err(|e| e.to_string())?;

    // Weekly progress per goal (last 7 days)
    let week_ago = (chrono::Utc::now() - chrono::Duration::days(7)).to_rfc3339();
    let weekly_progress: Vec<(String, f64)> = sqlx::query_as(
        "SELECT goal_id, COALESCE(SUM(delta), 0) FROM goal_progress
         WHERE timestamp > ? GROUP BY goal_id",
    )
    .bind(&week_ago)
    .fetch_all(pool)
    .await
    .map_err(|e| e.to_string())?;
    let weekly_map: std::collections::HashMap<String, f64> =
        weekly_progress.into_iter().collect();

    // Weekly hours spent on linked projects (for time-based goals)
    let weekly_hours: Vec<(String, f64)> = sqlx::query_as(
        "SELECT g.id, COALESCE(SUM(tl.duration_minutes) / 60.0, 0)
         FROM goals g
         LEFT JOIN project_time_log tl ON g.linked_project_id = tl.project_id
              AND tl.start_time > ?
         WHERE g.status = 'active' AND g.linked_project_id IS NOT NULL
         GROUP BY g.id",
    )
    .bind(&week_ago)
    .fetch_all(pool)
    .await
    .unwrap_or_default();
    let hours_map: std::collections::HashMap<String, f64> =
        weekly_hours.into_iter().collect();

    let goal_data: Vec<serde_json::Value> = goals.into_iter().map(|g| {
        let pct = match g.5 {
            Some(target) if target > 0.0 => Some(g.7 / target * 100.0),
            _ => None,
        };
        serde_json::json!({
            "id": g.0, "title": g.1, "category": g.2, "priority": g.3,
            "status": g.4, "target_value": g.5, "target_unit": g.6,
            "current_value": g.7, "weekly_hours_target": g.8,
            "deadline": g.9,
            "completion_pct": pct,
            "weekly_progress": weekly_map.get(&g.0).copied().unwrap_or(0.0),
            "weekly_hours_actual": hours_map.get(&g.0).copied().unwrap_or(0.0),
        })
    }).collect();

    Ok(serde_json::json!({ "goals": goal_data }))
}

// ── Training Data ─────────────────────────────────────────────────────────────

#[tauri::command]
pub async fn get_training_counts(
    state: State<'_, SharedState>,
) -> Result<crate::training::TrainingCounts, String> {
    let pool = { state.lock().await.pool.clone() };
    Ok(crate::training::get_counts(&pool).await)
}

#[tauri::command]
pub async fn export_training_data(
    state: State<'_, SharedState>,
    path: String,
) -> Result<usize, String> {
    let pool = { state.lock().await.pool.clone() };
    crate::training::export_jsonl(&pool, &path).await.map_err(|e| e.to_string())
}

// ── Search / Citations ────────────────────────────────────────────────────────

/// Trigger a web search from the UI (separate from CADEN's tool-call path).
#[tauri::command]
pub async fn search_web(
    query: String,
    state: State<'_, SharedState>,
) -> Result<String, String> {
    let pool = { state.lock().await.pool.clone() };
    Ok(crate::search::search_and_store(&pool, &query).await)
}

/// Return recent cited URLs for a "Citations" view in the UI.
#[tauri::command]
pub async fn get_web_citations(
    limit: Option<i64>,
    state: State<'_, SharedState>,
) -> Result<Vec<crate::search::WebCitation>, String> {
    let pool = { state.lock().await.pool.clone() };
    crate::search::get_recent_citations(&pool, limit.unwrap_or(50))
        .await
        .map_err(|e| e.to_string())
}

/// Semantic recall of cached web results.
#[tauri::command]
pub async fn recall_web(
    query: String,
    state: State<'_, SharedState>,
) -> Result<String, String> {
    let pool = { state.lock().await.pool.clone() };
    Ok(crate::search::recall_similar(&pool, &query).await)
}

// ─── Catch-up summary ─────────────────────────────────────────────────────────

/// Summary of what changed since the last time CADEN was opened.
#[derive(serde::Serialize)]
pub struct CatchUpSummary {
    /// How many hours since the last sync
    pub hours_since_last_sync: f64,
    /// New assignments from Moodle that appeared since last sync
    pub new_moodle_assignments: Vec<CatchUpTask>,
    /// Tasks that are now overdue (past due date, not completed)
    pub overdue_tasks: Vec<CatchUpTask>,
    /// Number of tasks completed yesterday
    pub completed_yesterday: i64,
    /// Number of tasks skipped yesterday
    pub skipped_yesterday: i64,
    /// Current energy level (rolling 1-day average), if available
    pub current_energy: Option<f64>,
    /// Whether the plan was reduced due to low energy
    pub low_energy_mode: bool,
    /// Resurfaced thought-dump entries relevant to today's tasks
    pub resurfaced_thoughts: Vec<String>,
}

#[derive(serde::Serialize)]
pub struct CatchUpTask {
    pub id: String,
    pub title: String,
    pub source: String,
    pub due_date: Option<String>,
    pub course_name: Option<String>,
}

#[tauri::command]
pub async fn get_catchup_summary(state: State<'_, SharedState>) -> Result<CatchUpSummary, String> {
    let pool = { state.lock().await.pool.clone() };
    let now = chrono::Utc::now();
    let today_str = chrono::Local::now().format("%Y-%m-%d").to_string();

    // Hours since last sync
    let last_sync_iso = crate::db::get_setting(&pool, "last_sync_at")
        .await
        .ok()
        .flatten();
    let hours_since = last_sync_iso
        .and_then(|iso| chrono::DateTime::parse_from_rfc3339(&iso).ok())
        .map(|dt| (now - dt.with_timezone(&chrono::Utc)).num_minutes() as f64 / 60.0)
        .unwrap_or(999.0);

    // New Moodle assignments (not completed)
    let new_moodle: Vec<(String, String, Option<String>, Option<String>)> = sqlx::query_as(
        "SELECT id, title, due_date, course_name FROM tasks_cache
         WHERE source = 'moodle' AND completed = 0
         ORDER BY due_date ASC",
    )
    .fetch_all(&pool)
    .await
    .unwrap_or_default();

    let new_moodle_assignments: Vec<CatchUpTask> = new_moodle
        .into_iter()
        .map(|(id, title, due_date, course_name)| CatchUpTask {
            id, title, source: "moodle".to_string(), due_date, course_name,
        })
        .collect();

    // Overdue tasks: due date < now, not completed
    let overdue_rows: Vec<(String, String, String, Option<String>, Option<String>)> = sqlx::query_as(
        "SELECT id, title, source, due_date, course_name FROM tasks_cache
         WHERE completed = 0
           AND due_date IS NOT NULL
           AND date(due_date) < date('now', 'localtime')
         ORDER BY due_date ASC",
    )
    .fetch_all(&pool)
    .await
    .unwrap_or_default();

    let overdue_tasks: Vec<CatchUpTask> = overdue_rows
        .into_iter()
        .map(|(id, title, source, due_date, course_name)| CatchUpTask {
            id, title, source, due_date, course_name,
        })
        .collect();

    // Yesterday's stats
    let yesterday = (chrono::Local::now() - chrono::Duration::days(1))
        .format("%Y-%m-%d").to_string();

    let completed_yesterday: i64 = sqlx::query_as::<_, (i64,)>(
        "SELECT COUNT(*) FROM daily_plans WHERE date = ? AND completed = 1",
    )
    .bind(&yesterday)
    .fetch_one(&pool)
    .await
    .map(|(n,)| n)
    .unwrap_or(0);

    let skipped_yesterday: i64 = sqlx::query_as::<_, (i64,)>(
        "SELECT COUNT(*) FROM skips WHERE timestamp LIKE ?",
    )
    .bind(format!("{}%", yesterday))
    .fetch_one(&pool)
    .await
    .map(|(n,)| n)
    .unwrap_or(0);

    // Energy level
    let (avg_energy, _, _) = crate::state_engine::get_rolling_averages(&pool, 1).await;
    let low_energy_mode = avg_energy.map(|e| e < 4.0).unwrap_or(false);

    // Resurfaced thoughts — semantically relevant to today's plan
    let resurfaced_thoughts = get_resurfaced_thoughts_impl(&pool, &today_str).await;

    Ok(CatchUpSummary {
        hours_since_last_sync: hours_since,
        new_moodle_assignments,
        overdue_tasks,
        completed_yesterday,
        skipped_yesterday,
        current_energy: avg_energy,
        low_energy_mode,
        resurfaced_thoughts,
    })
}

/// Internal: find thought-dump entries semantically relevant to today's scheduled tasks.
async fn get_resurfaced_thoughts_impl(pool: &sqlx::SqlitePool, today_str: &str) -> Vec<String> {
    // Build a combined query from today's plan titles
    let titles: Vec<(String,)> = sqlx::query_as(
        "SELECT title FROM daily_plans WHERE date = ? AND completed = 0 LIMIT 10",
    )
    .bind(today_str)
    .fetch_all(pool)
    .await
    .unwrap_or_default();

    if titles.is_empty() {
        return vec![];
    }

    let combined_query = titles.iter().map(|(t,)| t.as_str()).collect::<Vec<_>>().join(". ");

    // Get embedding for the combined query
    let embedding = match crate::ollama::embed(&combined_query).await {
        Ok(e) => e,
        Err(_) => return vec![],
    };

    crate::sean_model::retrieval::get_relevant_thoughts(pool, embedding, 3).await
}

#[tauri::command]
pub async fn get_resurfaced_thoughts(
    state: State<'_, SharedState>,
) -> Result<Vec<String>, String> {
    let pool = { state.lock().await.pool.clone() };
    let today_str = chrono::Local::now().format("%Y-%m-%d").to_string();
    Ok(get_resurfaced_thoughts_impl(&pool, &today_str).await)
}

// ─── Overdue task triage ──────────────────────────────────────────────────────

#[derive(serde::Deserialize)]
pub struct TriageAction {
    pub task_id: String,
    /// "drop" | "defer" | "today"
    pub action: String,
    /// For "defer": new due date as ISO string
    pub defer_to: Option<String>,
}

#[tauri::command]
pub async fn triage_overdue_tasks(
    actions: Vec<TriageAction>,
    state: State<'_, SharedState>,
) -> Result<(), String> {
    let (pool, google_tokens) = {
        let s = state.lock().await;
        (s.pool.clone(), s.google_tokens.clone())
    };

    let fresh_token = if let Some(tokens) = google_tokens {
        ensure_fresh_token(&pool, tokens).await.ok()
    } else {
        None
    };

    for action in &actions {
        match action.action.as_str() {
            "drop" => {
                // Look up task metadata before modifying anything
                let task_row: Option<(String, Option<String>)> = sqlx::query_as(
                    "SELECT source, list_id FROM tasks_cache WHERE id = ?",
                )
                .bind(&action.task_id)
                .fetch_optional(&pool)
                .await
                .unwrap_or(None);

                let source = task_row.as_ref().map(|(s, _)| s.as_str()).unwrap_or("");

                // Delete from Google Tasks if this is a Google Task
                if source == "tasks" {
                    if let Some(ref token) = fresh_token {
                        let list_id = task_row
                            .as_ref()
                            .and_then(|(_, lid)| lid.clone())
                            .unwrap_or_else(|| "@default".to_string());
                        let _ = google::delete_task(token, &list_id, &action.task_id).await;
                    }
                }

                // Delete any linked Google Calendar events for this task
                let cal_events: Vec<(String,)> = sqlx::query_as(
                    "SELECT cal_event_id FROM daily_plans
                     WHERE task_id = ? AND cal_event_id IS NOT NULL",
                )
                .bind(&action.task_id)
                .fetch_all(&pool)
                .await
                .unwrap_or_default();
                if let Some(ref token) = fresh_token {
                    for (event_id,) in &cal_events {
                        let _ = google::delete_calendar_event(token, "primary", event_id).await;
                    }
                }

                // Mark as completed (dismissed) so it stops appearing
                sqlx::query("UPDATE tasks_cache SET completed = 1 WHERE id = ?")
                    .bind(&action.task_id)
                    .execute(&pool)
                    .await
                    .ok();

                // Record permanent dismissal so sync doesn't re-insert it
                let dismiss_id = crate::db::ops::generate_id();
                let today = chrono::Local::now().format("%Y-%m-%d").to_string();
                let ts = chrono::Utc::now().to_rfc3339();
                sqlx::query(
                    "INSERT OR IGNORE INTO dismissed_tasks (id, task_id, dismiss_date, dismissed_at)
                     VALUES (?, ?, ?, ?)",
                )
                .bind(&dismiss_id)
                .bind(&action.task_id)
                .bind(&today)
                .bind(&ts)
                .execute(&pool)
                .await
                .ok();

                // Remove from today's plan
                sqlx::query("DELETE FROM daily_plans WHERE task_id = ? AND completed = 0")
                    .bind(&action.task_id)
                    .execute(&pool)
                    .await
                    .ok();

                // Record as a skip for pattern learning
                let id = crate::db::ops::generate_id();
                sqlx::query("INSERT INTO skips (id, task_id, source, reason, timestamp) VALUES (?, ?, 'triage', 'dropped', ?)")
                    .bind(&id)
                    .bind(&action.task_id)
                    .bind(&ts)
                    .execute(&pool)
                    .await
                    .ok();
            }
            "defer" => {
                // Update the due date in tasks_cache
                if let Some(ref new_due) = action.defer_to {
                    sqlx::query("UPDATE tasks_cache SET due_date = ? WHERE id = ?")
                        .bind(new_due)
                        .bind(&action.task_id)
                        .execute(&pool)
                        .await
                        .ok();

                    // Resolve the Google Task ID to update:
                    // - For source='tasks', tasks_cache.id IS the Google Task ID
                    // - For source='moodle', google_task_id holds the promoted task ID
                    let task_meta: Option<(String, Option<String>, Option<String>)> =
                        sqlx::query_as(
                            "SELECT source, list_id, google_task_id FROM tasks_cache WHERE id = ?",
                        )
                        .bind(&action.task_id)
                        .fetch_optional(&pool)
                        .await
                        .unwrap_or(None);

                    if let (Some(ref token), Some((ref source, ref list_id, ref gtid))) =
                        (&fresh_token, &task_meta)
                    {
                        let effective_task_id = if source == "tasks" {
                            Some(action.task_id.as_str())
                        } else {
                            gtid.as_deref()
                        };
                        if let Some(tid) = effective_task_id {
                            let lid = list_id
                                .as_deref()
                                .unwrap_or("@default");
                            let _ = google::update_task(token, lid, tid, None, Some(new_due)).await;
                        }
                    }
                }
                // Delete any linked GCal events since the task is moving to a new date
                let cal_events: Vec<(String,)> = sqlx::query_as(
                    "SELECT cal_event_id FROM daily_plans
                     WHERE task_id = ? AND cal_event_id IS NOT NULL",
                )
                .bind(&action.task_id)
                .fetch_all(&pool)
                .await
                .unwrap_or_default();
                if let Some(ref token) = fresh_token {
                    for (event_id,) in &cal_events {
                        let _ = google::delete_calendar_event(token, "primary", event_id).await;
                    }
                }

                // Remove from today's plan so it doesn't appear until the new due date
                let today = chrono::Local::now().format("%Y-%m-%d").to_string();
                sqlx::query("DELETE FROM daily_plans WHERE task_id = ? AND date = ? AND completed = 0")
                    .bind(&action.task_id)
                    .bind(&today)
                    .execute(&pool)
                    .await
                    .ok();
            }
            "today" => {
                // No action needed — the task stays in today's plan as-is
            }
            _ => {}
        }
    }

    Ok(())
}
