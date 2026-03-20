use tauri::{AppHandle, State};

use crate::db::models::{AppSettings, PlanItem, UpcomingItem};
use crate::db::{ops, set_setting};
use crate::google;
use crate::moodle;
use crate::ollama;
use crate::planner;
use crate::SharedState;

// ─── Settings ────────────────────────────────────────────────────────────────

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
    let s = state.lock().await;
    ops::save_settings(&s.pool, &settings)
        .await
        .map_err(|e| e.to_string())
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
    let (model, system_prompt) = {
        let s = state.lock().await;
        let settings = ops::load_settings(&s.pool)
            .await
            .map_err(|e| e.to_string())?;
        (settings.ollama_model, settings.system_prompt)
    };

    tauri::async_runtime::spawn(async move {
        if let Err(e) = ollama::chat_streaming(app, message, history, context, model, system_prompt)
            .await
        {
            log::error!("Ollama chat error: {}", e);
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

// ─── Moodle ───────────────────────────────────────────────────────────────────

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
    let s = state.lock().await;
    ops::mark_plan_item_complete(&s.pool, &plan_id)
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn sync_all(state: State<'_, SharedState>) -> Result<(), String> {
    let (pool, google_tokens, moodle_client) = {
        let s = state.lock().await;
        (s.pool.clone(), s.google_tokens.clone(), s.moodle_client.clone())
    };

    // Sync Google Calendar + Tasks
    if let Some(tokens) = google_tokens {
        let access_token = ensure_fresh_token(&pool, tokens).await?;

        match google::fetch_calendar_events(&access_token).await {
            Ok(events) => {
                let fetched_at = chrono::Utc::now().to_rfc3339();
                sqlx::query("DELETE FROM events_cache")
                    .execute(&pool)
                    .await
                    .ok();
                for event in events {
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
                for task in tasks {
                    sqlx::query(
                        "INSERT OR REPLACE INTO tasks_cache
                         (id, title, source, due_date, completed, notes, list_name, fetched_at)
                         VALUES (?, ?, 'tasks', ?, ?, ?, ?, ?)",
                    )
                    .bind(&task.id)
                    .bind(&task.title)
                    .bind(&task.due_date)
                    .bind(task.completed)
                    .bind(&task.notes)
                    .bind(&task.list_name)
                    .bind(&fetched_at)
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
                for assign in assignments {
                    if !assign.submitted {
                        sqlx::query(
                            "INSERT OR REPLACE INTO tasks_cache
                             (id, title, source, due_date, completed, course_name, fetched_at)
                             VALUES (?, ?, 'moodle', ?, 0, ?, ?)",
                        )
                        .bind(&assign.id)
                        .bind(&assign.title)
                        .bind(&assign.due_date)
                        .bind(&assign.course_name)
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

    // Regenerate daily plan
    let settings = ops::load_settings(&pool).await.map_err(|e| e.to_string())?;
    planner::generate_daily_plan(&pool, settings.task_duration_minutes)
        .await
        .map_err(|e| e.to_string())?;

    Ok(())
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
