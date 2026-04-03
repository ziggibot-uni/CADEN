use std::sync::Arc;
use tauri::{Emitter, Manager};
use tokio::sync::Mutex;

pub mod calendar_agent;
pub mod commands;
pub mod db;
pub mod google;
pub mod moodle;
pub mod ollama;
pub mod planner;
pub mod plugin_registry;
pub mod projects;
pub mod pty;
pub mod search;
pub mod sean_model;
pub mod state_engine;
pub mod training;

pub struct AppState {
    pub pool: sqlx::SqlitePool,
    pub google_tokens: Option<google::GoogleTokens>,
    pub moodle_client: Option<moodle::MoodleClient>,
}

pub type SharedState = Arc<Mutex<AppState>>;

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_store::Builder::new().build())
        .plugin(tauri_plugin_http::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        // Serve static plugin files via the plugin:// URI scheme.
        // Dev-server plugins are loaded directly from http://localhost:PORT
        // so they never hit this handler.
        .register_uri_scheme_protocol("plugin", |app, request| {
            use tauri::http::Response;

            let uri = request.uri().to_string();
            let without_scheme = uri.strip_prefix("plugin://").unwrap_or(&uri);
            let slash_pos = without_scheme.find('/').unwrap_or(without_scheme.len());
            let plugin_id = &without_scheme[..slash_pos];
            let raw_path = if slash_pos < without_scheme.len() {
                &without_scheme[slash_pos + 1..]
            } else {
                ""
            };
            let raw_path = raw_path.split('?').next().unwrap_or(raw_path);
            let raw_path = raw_path.split('#').next().unwrap_or(raw_path);

            let registry = app.app_handle().state::<plugin_registry::PluginRegistry>();
            let plugins = registry.plugins.read().unwrap();

            let plugin = match plugins.iter().find(|p| p.id == plugin_id) {
                Some(p) => p,
                None => {
                    return Response::builder()
                        .status(404)
                        .header("Content-Type", "text/plain")
                        .body(b"Plugin not found".to_vec())
                        .unwrap();
                }
            };

            let folder = std::path::PathBuf::from(&plugin.folder_path);
            let os_path: std::path::PathBuf = raw_path.split('/').collect();
            let abs_path = folder.join(os_path);

            let canonical_folder = match folder.canonicalize() {
                Ok(p) => p,
                Err(_) => {
                    return Response::builder()
                        .status(404)
                        .header("Content-Type", "text/plain")
                        .body(b"Plugin folder not found".to_vec())
                        .unwrap();
                }
            };
            let canonical_file = match abs_path.canonicalize() {
                Ok(p) => p,
                Err(_) => {
                    return Response::builder()
                        .status(404)
                        .header("Content-Type", "text/plain")
                        .body(b"File not found".to_vec())
                        .unwrap();
                }
            };
            if !canonical_file.starts_with(&canonical_folder) {
                return Response::builder()
                    .status(403)
                    .header("Content-Type", "text/plain")
                    .body(b"Forbidden".to_vec())
                    .unwrap();
            }

            let content = match std::fs::read(&canonical_file) {
                Ok(c) => c,
                Err(_) => {
                    return Response::builder()
                        .status(404)
                        .header("Content-Type", "text/plain")
                        .body(b"File not found".to_vec())
                        .unwrap();
                }
            };

            let mime = plugin_registry::mime_for_path(&canonical_file);

            // Inject the color-override context-menu script into HTML pages
            // so plugins get the same right-click color customization as the
            // main dashboard.
            let body = if mime == "text/html" {
                let html = String::from_utf8_lossy(&content);
                let script = include_str!("color_override_inject.js");
                let injected = format!("{}<script>{}</script>", html, script);
                injected.into_bytes()
            } else {
                content
            };

            Response::builder()
                .status(200)
                .header("Content-Type", mime)
                .header("Access-Control-Allow-Origin", "*")
                .header("Cache-Control", "no-cache, no-store, must-revalidate")
                .body(body)
                .unwrap()
        })
        .setup(|app| {
            let app_data_dir = app
                .path()
                .app_data_dir()
                .expect("failed to get app data dir");
            std::fs::create_dir_all(&app_data_dir)?;

            let pool = tauri::async_runtime::block_on(db::init_db(&app_data_dir))
                .expect("failed to init database");

            let google_tokens = tauri::async_runtime::block_on(async {
                db::get_setting(&pool, "google_tokens")
                    .await
                    .ok()
                    .flatten()
                    .and_then(|json| serde_json::from_str::<google::GoogleTokens>(&json).ok())
            });

            let moodle_client = tauri::async_runtime::block_on(async {
                let url = db::get_setting(&pool, "moodle_url").await.ok().flatten()?;
                let token = db::get_setting(&pool, "moodle_token").await.ok().flatten()?;
                if url.is_empty() || token.is_empty() {
                    None
                } else {
                    Some(moodle::MoodleClient::new(url, token))
                }
            });

            let plugins = tauri::async_runtime::block_on(
                plugin_registry::load_plugins(&pool),
            )
            .unwrap_or_default();

            let state = Arc::new(Mutex::new(AppState {
                pool: pool.clone(),
                google_tokens,
                moodle_client,
            }));

            let registry = plugin_registry::PluginRegistry::new(plugins.clone());

            app.manage(state.clone());
            app.manage(registry);
            app.manage(pty::new_pty_state());

            // ── System tray ───────────────────────────────────────────────────
            // Persistent tray icon showing CADEN is running. Click to show/focus
            // the window. Shows the next task + time in the tooltip.
            {
                use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
                use tauri::menu::{MenuBuilder, MenuItemBuilder};
                use tauri::image::Image;

                let show_item = MenuItemBuilder::with_id("show", "Show CADEN").build(app)?;
                let quit_item = MenuItemBuilder::with_id("quit", "Quit").build(app)?;
                let tray_menu = MenuBuilder::new(app)
                    .items(&[&show_item, &quit_item])
                    .build()?;

                let icon = Image::from_path("icons/icon.ico")
                    .or_else(|_| Image::from_path("icons/32x32.png"))
                    .unwrap_or_else(|_| Image::from_bytes(include_bytes!("../icons/32x32.png")).expect("bundled icon"));

                let _tray = TrayIconBuilder::with_id("main")
                    .icon(icon)
                    .tooltip("CADEN — ready")
                    .menu(&tray_menu)
                    .on_menu_event(move |app_handle, event| {
                        match event.id().as_ref() {
                            "show" => {
                                if let Some(w) = app_handle.get_webview_window("main") {
                                    let _ = w.show();
                                    let _ = w.unminimize();
                                    let _ = w.set_focus();
                                }
                            }
                            "quit" => {
                                app_handle.exit(0);
                            }
                            _ => {}
                        }
                    })
                    .on_tray_icon_event(|tray, event| {
                        if let TrayIconEvent::Click {
                            button: MouseButton::Left,
                            button_state: MouseButtonState::Up,
                            ..
                        } = event
                        {
                            let app_handle = tray.app_handle();
                            if let Some(w) = app_handle.get_webview_window("main") {
                                let _ = w.show();
                                let _ = w.unminimize();
                                let _ = w.set_focus();
                            }
                        }
                    })
                    .build(app)?;

                // ── Tray tooltip updater ──────────────────────────────────────
                // Every 5 minutes, update the tooltip with the next task and time remaining.
                let pool_tray = pool.clone();
                let app_handle_tray = app.app_handle().clone();
                tauri::async_runtime::spawn(async move {
                    let mut interval = tokio::time::interval(tokio::time::Duration::from_secs(300));
                    loop {
                        interval.tick().await;
                        let today = chrono::Local::now().format("%Y-%m-%d").to_string();
                        let now_iso = chrono::Utc::now().to_rfc3339();
                        let next: Option<(String, Option<String>)> = sqlx::query_as(
                            "SELECT title, scheduled_end FROM daily_plans
                             WHERE date = ? AND completed = 0 AND scheduled_start IS NOT NULL
                               AND scheduled_start <= ?
                             ORDER BY scheduled_start ASC LIMIT 1",
                        )
                        .bind(&today)
                        .bind(&now_iso)
                        .fetch_optional(&pool_tray)
                        .await
                        .ok()
                        .flatten();

                        let tooltip = match next {
                            Some((title, Some(end))) => {
                                let remaining = chrono::DateTime::parse_from_rfc3339(&end)
                                    .ok()
                                    .map(|dt| {
                                        let mins = (dt.with_timezone(&chrono::Utc) - chrono::Utc::now()).num_minutes();
                                        if mins > 0 { format!(" ({}m left)", mins) } else { String::new() }
                                    })
                                    .unwrap_or_default();
                                format!("CADEN — {}{}", title, remaining)
                            }
                            Some((title, None)) => format!("CADEN — {}", title),
                            None => "CADEN — all clear".to_string(),
                        };

                        if let Some(tray) = app_handle_tray.tray_by_id("main") {
                            let _ = tray.set_tooltip(Some(&tooltip));
                        }
                    }
                });
            }

            // ── Backend sync loop ─────────────────────────────────────────────
            // Runs sync_all every 15 minutes from a backend tokio task so that
            // sync continues even if the webview is frozen, minimised, or the
            // frontend JS event loop is blocked.  Emits "caden-sync-complete"
            // so the UI can refresh plan/upcoming data.
            {
                let sync_state = state.clone();
                let sync_handle = app.app_handle().clone();
                tauri::async_runtime::spawn(async move {
                    // Wait 60 s before the first backend-driven sync — the
                    // frontend already fires one immediately on startup.
                    tokio::time::sleep(tokio::time::Duration::from_secs(60)).await;
                    let mut interval =
                        tokio::time::interval(tokio::time::Duration::from_secs(15 * 60));
                    loop {
                        interval.tick().await;
                        match commands::sync_all_core(&sync_state).await {
                            Ok(outcome) => {
                                let _ = sync_handle.emit("caden-sync-complete", &outcome);
                            }
                            Err(e) => {
                                log::warn!("Backend sync failed: {}", e);
                            }
                        }
                    }
                });
            }

            // Backfill embeddings for any chat/thought entries saved before
            // nomic-embed-text was installed. Runs once in background. Soft-fail.
            {
                let backfill_pool = pool.clone();
                tauri::async_runtime::spawn(async move {
                    // Small delay so Ollama is ready before we hammer it
                    tokio::time::sleep(tokio::time::Duration::from_secs(5)).await;
                    crate::sean_model::backfill_embeddings(&backfill_pool).await;
                });
            }

            // Restart dev-server plugins in the background so CADEN startup
            // is never blocked by wait_for_port (up to 60 s per plugin).
            for plugin in plugins {
                if plugin.dev_url.is_none() || plugin.folder_path.is_empty() {
                    continue;
                }
                let folder = std::path::PathBuf::from(&plugin.folder_path);
                let pool = pool.clone();
                let app_handle = app.app_handle().clone();
                let plugin_id = plugin.id.clone();
                let plugin_name = plugin.name.clone();

                tauri::async_runtime::spawn(async move {
                    let (install_cmd, dev_cmd, port) =
                        match plugin_registry::detect_kind(&folder) {
                            Ok((
                                _,
                                plugin_registry::PluginKind::DevServer {
                                    install_cmd,
                                    dev_cmd,
                                    port,
                                },
                            )) => (install_cmd, dev_cmd, port),
                            _ => {
                                log::warn!(
                                    "Plugin '{}' was a dev server but manifest changed; skipping",
                                    plugin_name
                                );
                                return;
                            }
                        };

                    match plugin_registry::start_dev_server(
                        &folder,
                        install_cmd.as_deref(),
                        &dev_cmd,
                        port,
                    )
                    .await
                    {
                        Ok(child) => {
                            let url = format!("http://localhost:{}", port);
                            let _ = plugin_registry::update_plugin_dev_url(
                                &pool,
                                &plugin_id,
                                Some(&url),
                            )
                            .await;
                            let registry =
                                app_handle.state::<plugin_registry::PluginRegistry>();
                            registry.processes.lock().await.push(
                                plugin_registry::RunningProcess {
                                    plugin_id: plugin_id.clone(),
                                    child,
                                },
                            );
                            if let Ok(mut ps) = registry.plugins.write() {
                                if let Some(p) =
                                    ps.iter_mut().find(|p| p.id == plugin_id)
                                {
                                    p.dev_url = Some(url);
                                }
                            };
                        }
                        Err(e) => {
                            log::warn!(
                                "Could not restart dev server for '{}': {}",
                                plugin_name,
                                e
                            );
                        }
                    }
                });
            }

            // ── Proactive circadian nudge timer ───────────────────────────────
            // Fires once per hour. During a pharmacokinetic *peak* window (good
            // cognitive performance), if Sean hasn't completed a task in the
            // last 2 hours, emit a "caden-nudge" event so the frontend can show
            // a gentle dismissible prompt.
            {
                let pool_nudge = pool.clone();
                let app_handle_nudge = app.app_handle().clone();
                tauri::async_runtime::spawn(async move {
                    use chrono::{Local, Timelike, Utc};
                    // Wait one full hour before the first check so startup
                    // isn't immediately noisy.
                    tokio::time::sleep(tokio::time::Duration::from_secs(3600)).await;
                    let mut interval =
                        tokio::time::interval(tokio::time::Duration::from_secs(3600));
                    loop {
                        interval.tick().await;
                        let current_hour = Local::now().hour();

                        // Check PK performance windows
                        let windows =
                            crate::state_engine::get_performance_windows_today(&pool_nudge)
                                .await;
                        let is_peak = windows.iter().any(|w| {
                            w.kind == "peak"
                                && current_hour >= w.start_hour
                                && current_hour < w.end_hour
                        });
                        if !is_peak {
                            continue;
                        }

                        // Skip if Sean completed a task in the last 2 hours —
                        // he's already working.
                        let two_hours_ago = (Utc::now().timestamp() - 7200).to_string();
                        // completed_at is stored as ISO 8601 string; lexicographic
                        // comparison is equivalent to chronological here.
                        let recently_active: bool = sqlx::query_scalar::<_, i64>(
                            "SELECT COUNT(*) FROM daily_plans
                             WHERE completed = 1
                               AND completed_at IS NOT NULL
                               AND completed_at >= datetime(?,'unixepoch')",
                        )
                        .bind(&two_hours_ago)
                        .fetch_one(&pool_nudge)
                        .await
                        .unwrap_or(0)
                            > 0;

                        if recently_active {
                            continue;
                        }

                        // Build a nudge message based on time of day
                        let nudge = match current_hour {
                            5..=10 => {
                                "Morning peak window open — this is your highest-quality \
                                 focus time. Good moment for something that needs real thinking."
                            }
                            11..=14 => {
                                "Mid-day focus window — cognitively you're well-positioned \
                                 right now. Consider tackling something demanding."
                            }
                            15..=19 => {
                                "Afternoon peak — your meds are working well right now. \
                                 Good time for a meaningful task if you have the energy."
                            }
                            _ => {
                                "Performance window open — if you have capacity, \
                                 now's a reasonable time for focused work."
                            }
                        };

                        let _ = app_handle_nudge.emit("caden-nudge", nudge);
                    }
                });
            }

            // ── Warm Ollama model into VRAM on startup ────────────────────
            // Only warm local Ollama models (GitHub models contain '/' in name).
            {
                let pool_warm = pool.clone();
                tauri::async_runtime::spawn(async move {
                    if let Some(model) = db::get_setting(&pool_warm, "active_model")
                        .await
                        .ok()
                        .flatten()
                        .or_else(|| None)  // fallback handled below
                    {
                        // Only warm Ollama models — GitHub models are remote
                        if !model.contains('/') {
                            ollama::warm_model(&model).await;
                        }
                    }
                });
            }

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::get_setting_value,
            commands::set_setting_value,
            commands::get_settings,
            commands::save_settings,
            commands::force_replan,
            commands::delete_plan_item,
            commands::mark_setup_complete,
            commands::save_moodle_credentials,
            commands::get_ollama_status,
            commands::check_ollama,
            commands::pull_ollama_model,
            commands::chat_with_ollama,
            commands::start_google_oauth,
            commands::get_google_calendars,
            commands::debug_moodle,
            commands::test_moodle_connection,
            commands::get_today_plan,
            commands::get_upcoming_items,
            commands::mark_plan_item_complete,
            commands::unmark_plan_item_complete,
            commands::skip_plan_item,
            commands::clear_completed_plan_items,
            commands::record_correction,
            commands::sync_all,
            commands::list_projects,
            commands::link_plan_item_to_project,
            commands::link_task_to_project,
            commands::add_project,
            commands::update_project,
            commands::delete_project,
            commands::set_project_parent,
            commands::get_project_entries,
            commands::add_project_entry,
            commands::update_project_entry,
            commands::toggle_project_entry_complete,
            commands::delete_project_entry,
            commands::search_project_entries,
            commands::log_project_time,
            commands::get_project_time_log,
            commands::get_project_total_time,
            commands::pick_project_folder,
            commands::open_project_folder,
            commands::list_plugins,
            commands::register_plugin_folder,
            commands::add_web_tab,
            commands::unregister_plugin,
            commands::promote_moodle_to_task,
            commands::update_plan_item,
            commands::promote_entry_to_google_task,
            commands::promote_upcoming_to_google_task,
            commands::open_web_tab_view,
            commands::close_web_tab_view,
            commands::reload_web_tab_view,
            commands::set_web_tab_bounds,
            commands::eval_web_tab_script,
            // PTY terminal
            pty::pty_spawn,
            pty::pty_write,
            pty::pty_resize,
            pty::pty_kill,
            // AppBuilder (vibe coding)
            commands::ab_llm_chat,
            commands::ab_start_vibecoder,
            commands::ab_list_apps,
            commands::ab_pick_workspace,
            commands::ab_file_tree,
            commands::ab_list_dir,
            commands::ab_read_file,
            commands::ab_write_file,
            commands::ab_run_cmd,
            // Insights
            commands::insights_circadian_grid,
            commands::insights_patterns,
            commands::insights_transitions,
            commands::insights_factor_snapshots,
            commands::insights_daily_states,
            commands::insights_completions,
            commands::insights_skips,
            commands::insights_behavioral_log,
            commands::insights_medications,
            commands::insights_delete_factor_snapshot,
            commands::insights_update_factor_snapshot,
            commands::insights_delete_medication,
            commands::insights_update_medication,
            commands::insights_add_medication,
            commands::insights_corrections,
            commands::insights_profile,
            commands::insights_episode_risk,
            commands::insights_focus_params,
            commands::insights_active_concerns,
            commands::insights_rolling_averages,
            commands::insights_project_time_summary,
            commands::insights_db_counts,
            commands::insights_performance_windows,
            // Goals
            commands::list_goals,
            commands::add_goal,
            commands::update_goal,
            commands::delete_goal,
            commands::add_goal_progress,
            commands::get_goal_progress,
            commands::insights_goals_summary,
            commands::get_moodle_courses,
            commands::set_project_educat_course,
            commands::pick_project_spec,
            commands::open_spec_file,
            commands::get_training_counts,
            commands::export_training_data,
            // Search / Citations
            commands::search_web,
            commands::get_web_citations,
            commands::recall_web,
            // Catch-up, triage, resurfacing
            commands::get_catchup_summary,
            commands::get_resurfaced_thoughts,
            commands::triage_overdue_tasks,
        ])
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                // Read the configured model name from app state without async.
                let model = {
                    let state = window.app_handle().state::<SharedState>();
                    tauri::async_runtime::block_on(async {
                        let s = state.lock().await;
                        db::get_setting(&s.pool, "active_model")
                            .await
                            .ok()
                            .flatten()
                            .unwrap_or_default()
                    })
                };

                // Unload the model from VRAM and kill uvicorn.
                // We join the thread so these complete before the process exits.
                let handle = std::thread::spawn(move || {
                    // Only evict Ollama models (GitHub models are remote — no eviction needed).
                    if !model.is_empty() && !model.contains('/') {
                        if let Ok(client) = reqwest::blocking::Client::builder()
                            .timeout(std::time::Duration::from_secs(2))
                            .build()
                        {
                            let _ = client
                                .post("http://localhost:11434/api/generate")
                                .json(&serde_json::json!({
                                    "model": model,
                                    "prompt": "",
                                    "keep_alive": 0
                                }))
                                .send();
                        }
                    }

                    // Kill the PedalManifest uvicorn backend.
                    // wmic targets the process by commandline so it works even when
                    // the child was spawned detached (start /b) with no stored PID.
                    #[cfg(target_os = "windows")]
                    {
                        let _ = std::process::Command::new("wmic")
                            .args(["process", "where", "commandline like '%uvicorn%'", "delete"])
                            .output();

                        // Kill the Ollama process entirely.
                        let _ = std::process::Command::new("taskkill")
                            .args(["/F", "/IM", "ollama.exe"])
                            .output();
                    }
                });

                // Give shutdown tasks up to 3 seconds to complete.
                let _ = handle.join();
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
