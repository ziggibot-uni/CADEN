/// Circadian energy model — tracks Sean's productivity at each hour of the week.
///
/// Maintains a 24×7 grid (hour × day_of_week) of completion rates.
/// Updated on every task completion or skip. Used to report current energy
/// level and predict the best work windows for today.
use chrono::{Datelike, Local, Timelike, Weekday};
use sqlx::SqlitePool;

/// Record a task event (completion or skip) into the circadian grid.
pub async fn record_event(pool: &SqlitePool, completed: bool) {
    let now = Local::now();
    let hour = now.hour() as i64;
    let dow = weekday_to_index(now.weekday()) as i64;
    let ts = chrono::Utc::now().to_rfc3339();

    let _ = sqlx::query(
        "INSERT INTO circadian_model (hour, day_of_week, completions, samples, last_updated)
         VALUES (?, ?, ?, 1, ?)
         ON CONFLICT(hour, day_of_week) DO UPDATE SET
             completions  = completions + ?,
             samples      = samples + 1,
             last_updated = excluded.last_updated",
    )
    .bind(hour)
    .bind(dow)
    .bind(if completed { 1_i64 } else { 0_i64 })
    .bind(&ts)
    .bind(if completed { 1_i64 } else { 0_i64 })
    .execute(pool)
    .await;
}

/// Get the productivity score (0.0–1.0) for a specific hour and day.
/// Returns 0.5 (neutral) when there is insufficient data.
pub async fn get_energy_level(pool: &SqlitePool, hour: u32, day_of_week: u32) -> f32 {
    let row: Option<(i64, i64)> = sqlx::query_as(
        "SELECT completions, samples FROM circadian_model
         WHERE hour = ? AND day_of_week = ?",
    )
    .bind(hour as i64)
    .bind(day_of_week as i64)
    .fetch_optional(pool)
    .await
    .unwrap_or(None);

    match row {
        Some((completions, samples)) if samples >= 5 => completions as f32 / samples as f32,
        Some((completions, samples)) if samples > 0 => {
            // Blend sparse data toward neutral
            let raw = completions as f32 / samples as f32;
            0.5 * (1.0 - samples as f32 / 5.0) + raw * (samples as f32 / 5.0)
        }
        _ => 0.5, // no data → neutral
    }
}

/// Return the top-N most productive hours for a given day, sorted descending.
/// Only hours with at least 3 samples are included.
pub async fn get_peak_hours_today(pool: &SqlitePool, day_of_week: u32) -> Vec<u32> {
    let rows: Vec<(i64, i64, i64)> = sqlx::query_as(
        "SELECT hour, completions, samples FROM circadian_model
         WHERE day_of_week = ? AND samples >= 3
         ORDER BY CAST(completions AS REAL) / samples DESC
         LIMIT 5",
    )
    .bind(day_of_week as i64)
    .fetch_all(pool)
    .await
    .unwrap_or_default();

    rows.into_iter()
        .filter(|(_, c, s)| *s > 0 && (*c as f32 / *s as f32) >= 0.55)
        .map(|(h, _, _)| h as u32)
        .collect()
}

/// Return the full 24-hour energy profile for a given day.
/// Values are 0.0–1.0; unsampled hours return 0.5.
pub async fn get_daily_profile(pool: &SqlitePool, day_of_week: u32) -> Vec<(u32, f32)> {
    let rows: Vec<(i64, i64, i64)> = sqlx::query_as(
        "SELECT hour, completions, samples FROM circadian_model WHERE day_of_week = ?",
    )
    .bind(day_of_week as i64)
    .fetch_all(pool)
    .await
    .unwrap_or_default();

    let mut grid = vec![0.5_f32; 24];
    for (h, c, s) in rows {
        if s > 0 && h >= 0 && h < 24 {
            grid[h as usize] = c as f32 / s as f32;
        }
    }
    grid.into_iter().enumerate().map(|(h, v)| (h as u32, v)).collect()
}

/// Convert chrono Weekday → 0-based index (Mon=0 … Sun=6).
pub fn weekday_to_index(w: Weekday) -> u32 {
    w.num_days_from_monday()
}
