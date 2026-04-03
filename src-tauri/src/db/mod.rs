use anyhow::Result;
use sqlx::{sqlite::SqlitePoolOptions, SqlitePool};
use std::path::Path;

pub mod models;
pub mod ops;

/// Initialize the SQLite connection pool and run schema migrations.
pub async fn init_db(data_dir: &Path) -> Result<SqlitePool> {
    let db_path = data_dir.join("caden.db");
    let db_url = format!("sqlite://{}?mode=rwc", db_path.display());

    let pool = SqlitePoolOptions::new()
        .max_connections(5)
        .connect(&db_url)
        .await?;

    // Run embedded schema
    sqlx::query(include_str!("schema.sql"))
        .execute(&pool)
        .await?;

    // Incremental migrations — ignore errors if column already exists
    let _ = sqlx::query("ALTER TABLE tasks_cache ADD COLUMN url TEXT")
        .execute(&pool)
        .await;
    let _ = sqlx::query("ALTER TABLE tasks_cache ADD COLUMN list_id TEXT")
        .execute(&pool)
        .await;
    let _ = sqlx::query("ALTER TABLE project_entries ADD COLUMN embedding BLOB")
        .execute(&pool)
        .await;
    let _ = sqlx::query("ALTER TABLE plugins ADD COLUMN dev_url TEXT")
        .execute(&pool)
        .await;
    let _ = sqlx::query("ALTER TABLE projects ADD COLUMN folder_path TEXT")
        .execute(&pool)
        .await;
    let _ = sqlx::query("ALTER TABLE project_entries ADD COLUMN completed INTEGER NOT NULL DEFAULT 0")
        .execute(&pool)
        .await;
    let _ = sqlx::query("ALTER TABLE daily_plans ADD COLUMN google_task_id TEXT")
        .execute(&pool)
        .await;
    let _ = sqlx::query("ALTER TABLE project_entries ADD COLUMN parent_id TEXT")
        .execute(&pool)
        .await;
    let _ = sqlx::query("ALTER TABLE project_entries ADD COLUMN google_task_id TEXT")
        .execute(&pool)
        .await;
    let _ = sqlx::query("ALTER TABLE tasks_cache ADD COLUMN google_task_id TEXT")
        .execute(&pool)
        .await;
    let _ = sqlx::query("ALTER TABLE projects ADD COLUMN parent_id TEXT")
        .execute(&pool)
        .await;
    // Plan → Google Calendar tracking
    let _ = sqlx::query("ALTER TABLE daily_plans ADD COLUMN cal_event_id TEXT")
        .execute(&pool)
        .await;
    // Direct project link on plan items and tasks
    let _ = sqlx::query("ALTER TABLE daily_plans ADD COLUMN linked_project_id TEXT")
        .execute(&pool)
        .await;
    let _ = sqlx::query("ALTER TABLE tasks_cache ADD COLUMN linked_project_id TEXT")
        .execute(&pool)
        .await;

    // Educat (Moodle) course link + spec file on projects
    let _ = sqlx::query("ALTER TABLE projects ADD COLUMN educat_course_id TEXT")
        .execute(&pool)
        .await;
    let _ = sqlx::query("ALTER TABLE projects ADD COLUMN educat_course_name TEXT")
        .execute(&pool)
        .await;
    let _ = sqlx::query("ALTER TABLE projects ADD COLUMN spec_path TEXT")
        .execute(&pool)
        .await;

    // Project time tracking table
    let _ = sqlx::query(
        "CREATE TABLE IF NOT EXISTS project_time_log (
            id          TEXT PRIMARY KEY NOT NULL,
            project_id  TEXT NOT NULL,
            event_title TEXT NOT NULL,
            start_time  TEXT NOT NULL,
            end_time    TEXT NOT NULL,
            duration_minutes REAL NOT NULL,
            source      TEXT NOT NULL DEFAULT 'calendar',
            created_at  TEXT NOT NULL
        )",
    )
    .execute(&pool)
    .await;

    // ── Behavioral state engine tables ─────────────────────────────────────
    // Silent LLM extraction results stored per-message
    let _ = sqlx::query(
        "CREATE TABLE IF NOT EXISTS factor_snapshots (
            id                  TEXT PRIMARY KEY NOT NULL,
            timestamp           INTEGER NOT NULL,
            source              TEXT NOT NULL DEFAULT 'passive_nlp',
            mood_score          REAL,
            energy_level        REAL,
            anxiety_level       REAL,
            thought_coherence   TEXT,
            temporal_focus      TEXT,
            valence             TEXT,
            sleep_hours_implied REAL,
            confidence          REAL NOT NULL DEFAULT 0.5,
            raw_notes           TEXT
        )",
    )
    .execute(&pool)
    .await;

    // User-logged medication doses (parsed from natural language or explicit)
    let _ = sqlx::query(
        "CREATE TABLE IF NOT EXISTS medication_log (
            id              TEXT PRIMARY KEY NOT NULL,
            logged_at       INTEGER NOT NULL,
            medication_name TEXT NOT NULL,
            dose_time       INTEGER NOT NULL,
            dose_mg         REAL,
            notes           TEXT
        )",
    )
    .execute(&pool)
    .await;

    // Daily rolled-up state summary (one row per calendar date)
    let _ = sqlx::query(
        "CREATE TABLE IF NOT EXISTS daily_state (
            date            TEXT PRIMARY KEY NOT NULL,
            wake_time       TEXT,
            sleep_hours     REAL,
            avg_energy      REAL,
            avg_mood        REAL,
            avg_anxiety     REAL,
            thought_pattern TEXT,
            output_volume   INTEGER NOT NULL DEFAULT 0,
            session_count   INTEGER NOT NULL DEFAULT 0,
            episode_risk    TEXT NOT NULL DEFAULT 'low',
            risk_confidence REAL NOT NULL DEFAULT 0.0
        )",
    )
    .execute(&pool)
    .await;

    // Task-type transition Markov model.
    // Records how often task_type B is successfully completed when it immediately
    // follows task_type A in a session. Used to sequence tasks for maximal momentum.
    let _ = sqlx::query(
        "CREATE TABLE IF NOT EXISTS task_transitions (
            id               TEXT PRIMARY KEY NOT NULL,
            from_type        TEXT NOT NULL,
            to_type          TEXT NOT NULL,
            completion_rate  REAL NOT NULL DEFAULT 0.5,
            avg_delay_minutes REAL NOT NULL DEFAULT 0.0,
            sample_count     INTEGER NOT NULL DEFAULT 0,
            last_updated     TEXT NOT NULL,
            UNIQUE(from_type, to_type)
        )",
    )
    .execute(&pool)
    .await;

    // ── Goal tracking ─────────────────────────────────────────────────────
    // Top-level goals that influence scheduling and daily planning.
    let _ = sqlx::query(
        "CREATE TABLE IF NOT EXISTS goals (
            id                  TEXT PRIMARY KEY NOT NULL,
            title               TEXT NOT NULL,
            description         TEXT,
            category            TEXT NOT NULL DEFAULT 'personal',
            priority            INTEGER NOT NULL DEFAULT 3,
            status              TEXT NOT NULL DEFAULT 'active',
            target_value        REAL,
            target_unit         TEXT,
            current_value       REAL NOT NULL DEFAULT 0.0,
            weekly_hours_target REAL NOT NULL DEFAULT 0.0,
            deadline            TEXT,
            linked_project_id   TEXT,
            linked_task_types   TEXT,
            created_at          TEXT NOT NULL,
            updated_at          TEXT NOT NULL
        )",
    )
    .execute(&pool)
    .await;

    // Progress log — filled by BTS LLM extraction and task completions.
    let _ = sqlx::query(
        "CREATE TABLE IF NOT EXISTS goal_progress (
            id          TEXT PRIMARY KEY NOT NULL,
            goal_id     TEXT NOT NULL,
            delta       REAL NOT NULL DEFAULT 0.0,
            note        TEXT,
            source      TEXT NOT NULL DEFAULT 'llm',
            timestamp   TEXT NOT NULL
        )",
    )
    .execute(&pool)
    .await;

    // Dismissed tasks — tasks the user manually removed from today's plan.
    // The planner skips these for the dismiss_date so they don't respawn on sync.
    // Rows older than 30 days are pruned on startup.
    let _ = sqlx::query(
        "CREATE TABLE IF NOT EXISTS dismissed_tasks (
            id            TEXT PRIMARY KEY NOT NULL,
            task_id       TEXT NOT NULL,
            dismiss_date  TEXT NOT NULL,
            dismissed_at  TEXT NOT NULL
        )",
    )
    .execute(&pool)
    .await;

    let _ = sqlx::query(
        "CREATE INDEX IF NOT EXISTS idx_dismissed_tasks_date ON dismissed_tasks(task_id, dismiss_date)",
    )
    .execute(&pool)
    .await;

    // Prune dismissals older than 30 days
    let _ = sqlx::query(
        "DELETE FROM dismissed_tasks WHERE dismiss_date < date('now', 'localtime', '-30 days')",
    )
    .execute(&pool)
    .await;

    // Training data table
    let _ = sqlx::query(
        "CREATE TABLE IF NOT EXISTS training_data (
            id           TEXT PRIMARY KEY NOT NULL,
            ex_type      TEXT NOT NULL,
            system_prompt TEXT,
            user_prompt  TEXT NOT NULL,
            completion   TEXT NOT NULL,
            model        TEXT NOT NULL,
            created_at   TEXT NOT NULL
        )",
    )
    .execute(&pool)
    .await;

    // One-time notification flag so the "ready to fine-tune" popup fires only once
    let _ = sqlx::query(
        "CREATE TABLE IF NOT EXISTS training_flags (
            key   TEXT PRIMARY KEY NOT NULL,
            value TEXT NOT NULL
        )",
    )
    .execute(&pool)
    .await;

    // Seed default settings if empty
    let count: (i64,) = sqlx::query_as("SELECT COUNT(*) FROM settings")
        .fetch_one(&pool)
        .await?;

    if count.0 == 0 {
        seed_defaults(&pool).await?;
    }

    Ok(pool)
}

async fn seed_defaults(pool: &SqlitePool) -> Result<()> {
    let defaults = [
        ("setup_complete", "false"),
        ("google_connected", "false"),
        ("ollama_model", "qwen3:14b"),
        ("task_duration_minutes", "45"),
        ("creative_time_minutes", "120"),
        ("system_prompt", crate::ollama::DEFAULT_SYSTEM_PROMPT),
    ];

    for (k, v) in &defaults {
        sqlx::query("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)")
            .bind(k)
            .bind(v)
            .execute(pool)
            .await?;
    }

    Ok(())
}

/// Get a single setting value by key.
pub async fn get_setting(pool: &SqlitePool, key: &str) -> Result<Option<String>> {
    let row: Option<(String,)> =
        sqlx::query_as("SELECT value FROM settings WHERE key = ?")
            .bind(key)
            .fetch_optional(pool)
            .await?;
    Ok(row.map(|(v,)| v))
}

/// Set a setting value.
pub async fn set_setting(pool: &SqlitePool, key: &str, value: &str) -> Result<()> {
    sqlx::query("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)")
        .bind(key)
        .bind(value)
        .execute(pool)
        .await?;
    Ok(())
}
