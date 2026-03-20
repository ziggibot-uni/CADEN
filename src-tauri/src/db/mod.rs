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
        ("ollama_model", "llama3.1:8b"),
        ("task_duration_minutes", "45"),
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
