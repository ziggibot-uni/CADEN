use std::sync::Arc;
use tauri::Manager;
use tokio::sync::Mutex;

pub mod commands;
pub mod db;
pub mod google;
pub mod moodle;
pub mod ollama;
pub mod planner;

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
        .setup(|app| {
            let app_data_dir = app
                .path()
                .app_data_dir()
                .expect("failed to get app data dir");
            std::fs::create_dir_all(&app_data_dir)?;

            let pool = tauri::async_runtime::block_on(db::init_db(&app_data_dir))
                .expect("failed to init database");

            // Restore Google tokens from DB
            let google_tokens = tauri::async_runtime::block_on(async {
                db::get_setting(&pool, "google_tokens")
                    .await
                    .ok()
                    .flatten()
                    .and_then(|json| serde_json::from_str::<google::GoogleTokens>(&json).ok())
            });

            // Restore Moodle client from DB
            let moodle_client = tauri::async_runtime::block_on(async {
                let url = db::get_setting(&pool, "moodle_url").await.ok().flatten()?;
                let token = db::get_setting(&pool, "moodle_token").await.ok().flatten()?;
                if url.is_empty() || token.is_empty() {
                    None
                } else {
                    Some(moodle::MoodleClient::new(url, token))
                }
            });

            let state = Arc::new(Mutex::new(AppState {
                pool,
                google_tokens,
                moodle_client,
            }));

            app.manage(state);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::get_setting_value,
            commands::set_setting_value,
            commands::get_settings,
            commands::save_settings,
            commands::mark_setup_complete,
            commands::save_moodle_credentials,
            commands::get_ollama_status,
            commands::check_ollama,
            commands::pull_ollama_model,
            commands::chat_with_ollama,
            commands::start_google_oauth,
            commands::test_moodle_connection,
            commands::get_today_plan,
            commands::get_upcoming_items,
            commands::mark_plan_item_complete,
            commands::sync_all,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
