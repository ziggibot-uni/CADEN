/// Behavioral profile — aggregates Sean's patterns from historical data.
///
/// Computes:
///   - Task-type completion rates (creative vs academic preference signal)
///   - Chronic avoidances (tasks skipped 3+ consecutive times)
///   - Momentum (are completions trending up or down?)
///   - Flow window detection (back-to-back completions within short windows)
use chrono::{DateTime, Local, Timelike, Utc};
use sqlx::SqlitePool;

pub struct SeanProfile {
    /// Human-readable note about task type preferences, or empty.
    pub task_preference_note: String,
    /// Task titles that have been skipped 3+ times without a single completion.
    pub chronic_avoidances: Vec<String>,
    /// Human-readable momentum note, or empty.
    pub momentum_note: String,
    /// Detected flow windows in plain text, e.g. "Mon 10–12" — empty until enough data.
    pub flow_windows: Vec<String>,
    /// Spike signals: short labels when a notable pattern fires.
    pub spikes: Vec<String>,
}

pub async fn compute_profile(pool: &SqlitePool) -> SeanProfile {
    let task_preference_note = compute_task_preference(pool).await;
    let chronic_avoidances = detect_chronic_avoidances(pool).await;
    let momentum_note = compute_momentum(pool).await;
    let flow_windows = detect_flow_windows(pool).await;
    let spikes = fire_spikes(pool, &chronic_avoidances, &momentum_note).await;

    SeanProfile {
        task_preference_note,
        chronic_avoidances,
        momentum_note,
        flow_windows,
        spikes,
    }
}

// ─── Task preference ──────────────────────────────────────────────────────────

async fn compute_task_preference(pool: &SqlitePool) -> String {
    // Pull per-type completion rates from patterns table (need enough samples)
    let rows: Vec<(String, f64, i64)> = sqlx::query_as(
        "SELECT task_type,
                AVG(completion_rate) as avg_rate,
                SUM(sample_count)    as total
         FROM patterns
         WHERE sample_count >= 3
         GROUP BY task_type
         ORDER BY avg_rate DESC",
    )
    .fetch_all(pool)
    .await
    .unwrap_or_default();

    if rows.len() < 2 {
        return String::new();
    }

    let best = rows.iter().filter(|(_, r, _)| *r >= 0.60).take(2);
    let worst = rows.iter().rev().filter(|(_, r, _)| *r <= 0.40).take(2);

    let good: Vec<String> = best
        .map(|(t, r, _)| format!("{} ({:.0}%)", t, r * 100.0))
        .collect();
    let bad: Vec<String> = worst
        .map(|(t, r, _)| format!("{} ({:.0}%)", t, r * 100.0))
        .collect();

    let mut parts: Vec<String> = Vec::new();
    if !good.is_empty() {
        parts.push(format!("Completes well: {}", good.join(", ")));
    }
    if !bad.is_empty() {
        parts.push(format!("Struggles with: {}", bad.join(", ")));
    }
    parts.join(" | ")
}

// ─── Chronic avoidances ───────────────────────────────────────────────────────

async fn detect_chronic_avoidances(pool: &SqlitePool) -> Vec<String> {
    // Find tasks that have been skipped 3+ times in the last 30 days
    // and have ZERO completions in that same window.
    let rows: Vec<(String,)> = sqlx::query_as(
        "SELECT tc.title
         FROM tasks_cache tc
         WHERE tc.completed = 0
           AND (
               SELECT COUNT(*) FROM skips s WHERE s.task_id = tc.id
               AND s.timestamp > datetime('now', '-30 days')
           ) >= 3
           AND (
               SELECT COUNT(*) FROM completions c WHERE c.task_id = tc.id
               AND c.actual_time > datetime('now', '-30 days')
           ) = 0
         ORDER BY (
             SELECT COUNT(*) FROM skips s WHERE s.task_id = tc.id
             AND s.timestamp > datetime('now', '-30 days')
         ) DESC
         LIMIT 5",
    )
    .fetch_all(pool)
    .await
    .unwrap_or_default();

    rows.into_iter().map(|(t,)| t).collect()
}

// ─── Momentum ─────────────────────────────────────────────────────────────────

async fn compute_momentum(pool: &SqlitePool) -> String {
    // Count completions per day for the last 14 days
    let rows: Vec<(String, i64)> = sqlx::query_as(
        "SELECT DATE(actual_time, 'localtime') as day, COUNT(*) as cnt
         FROM completions
         WHERE actual_time > datetime('now', '-14 days')
         GROUP BY day
         ORDER BY day ASC",
    )
    .fetch_all(pool)
    .await
    .unwrap_or_default();

    if rows.len() < 4 {
        return String::new(); // not enough data yet
    }

    // Split into two halves and compare averages
    let half = rows.len() / 2;
    let first_avg: f64 = rows[..half].iter().map(|(_, c)| *c as f64).sum::<f64>() / half as f64;
    let second_avg: f64 =
        rows[half..].iter().map(|(_, c)| *c as f64).sum::<f64>() / (rows.len() - half) as f64;

    let delta = second_avg - first_avg;
    let overall_avg = rows.iter().map(|(_, c)| *c as f64).sum::<f64>() / rows.len() as f64;

    if delta > 0.8 {
        format!(
            "Momentum: RISING (+{:.1}/day trend, avg {:.1} completions/day)",
            delta, overall_avg
        )
    } else if delta < -0.8 {
        format!(
            "Momentum: DECLINING ({:.1}/day trend, avg {:.1} completions/day) — may need rest or a reset",
            delta, overall_avg
        )
    } else if overall_avg < 0.5 {
        "Momentum: VERY LOW — minimal task completion in the past 2 weeks".to_string()
    } else {
        String::new() // stable and normal — no note needed
    }
}

// ─── Flow window detection ────────────────────────────────────────────────────
//
// A flow window is 2+ completions within a 90-minute span on the same day.
// We look at the last 30 days and find the most common hour-of-day blocks
// where this happens — these are Sean's historically reliable flow slots.

async fn detect_flow_windows(pool: &SqlitePool) -> Vec<String> {
    let rows: Vec<(String,)> = sqlx::query_as(
        "SELECT actual_time FROM completions
         WHERE actual_time > datetime('now', '-30 days')
         ORDER BY actual_time ASC",
    )
    .fetch_all(pool)
    .await
    .unwrap_or_default();

    if rows.len() < 4 {
        return vec![];
    }

    let times: Vec<DateTime<Utc>> = rows
        .iter()
        .filter_map(|(t,)| DateTime::parse_from_rfc3339(t).ok())
        .map(|dt| dt.with_timezone(&Utc))
        .collect();

    // Bucket flow windows by starting hour (local time)
    let mut hour_flow_counts: [u32; 24] = [0; 24];

    for i in 0..times.len() {
        // Count how many other completions are within 90 minutes after times[i]
        let window_end = times[i] + chrono::Duration::minutes(90);
        let count = times[i + 1..]
            .iter()
            .take_while(|&&t| t <= window_end)
            .count();

        if count >= 1 {
            // times[i] is the start of a flow burst
            let local_hour = times[i].with_timezone(&Local).hour() as usize;
            if local_hour < 24 {
                hour_flow_counts[local_hour] += 1;
            }
        }
    }

    // Return hours where flow happens ≥2 times (reliable pattern)
    let mut flow_hours: Vec<u32> = hour_flow_counts
        .iter()
        .enumerate()
        .filter(|(_, &c)| c >= 2)
        .map(|(h, _)| h as u32)
        .collect();

    flow_hours.sort();

    if flow_hours.is_empty() {
        return vec![];
    }

    // Merge adjacent hours into ranges
    let mut windows: Vec<String> = Vec::new();
    let mut start = flow_hours[0];
    let mut prev = flow_hours[0];

    for &h in &flow_hours[1..] {
        if h == prev + 1 {
            prev = h;
        } else {
            windows.push(format!("{:02}:00–{:02}:00", start, prev + 1));
            start = h;
            prev = h;
        }
    }
    windows.push(format!("{:02}:00–{:02}:00", start, prev + 1));

    windows
}

// ─── Spike signals ────────────────────────────────────────────────────────────
//
// Lightweight "spiking" pattern recognition: each condition fires a short signal
// when a notable behavioral state is detected. These are injected as one-line
// alerts into the briefing so CADEN can adapt its tone and advice accordingly.

async fn fire_spikes(
    pool: &SqlitePool,
    chronic_avoidances: &[String],
    momentum_note: &str,
) -> Vec<String> {
    let mut spikes: Vec<String> = Vec::new();
    let now = Local::now();
    let hour = now.hour();

    // ── PRIME_WINDOW_UNUSED: it's peak hours but nothing done yet today ───────
    let completed_today: i64 = sqlx::query_as::<_, (i64,)>(
        "SELECT COUNT(*) FROM daily_plans
         WHERE date = DATE('now', 'localtime') AND completed = 1",
    )
    .fetch_one(pool)
    .await
    .map(|(n,)| n)
    .unwrap_or(0);

    let energy_high_window = (9..=14).contains(&hour);
    if energy_high_window && completed_today == 0 {
        spikes.push("⚡ PRIME_WINDOW: productive hours are active but no tasks completed yet today — good moment to start".to_string());
    }

    // ── STUCK: multiple chronic avoidances, same thing keeps not happening ────
    if chronic_avoidances.len() >= 2 {
        spikes.push(format!(
            "🔁 STUCK: {} tasks have been skipped 3+ times with zero completions — these need to be broken down or removed",
            chronic_avoidances.len()
        ));
    }

    // ── BURNOUT: declining momentum ───────────────────────────────────────────
    if momentum_note.contains("DECLINING") {
        spikes.push("🔴 BURNOUT_RISK: completion rate trending down — protect creative time, reduce academic load if possible".to_string());
    }

    // ── RISING: good momentum, reinforce it ──────────────────────────────────
    if momentum_note.contains("RISING") {
        spikes.push("🟢 FLOW_MOMENTUM: completions trending up — capitalize on this, front-load harder tasks".to_string());
    }

    // ── LATE_DAY_OVERLOAD: it's evening and a lot is still unfinished ─────────
    if hour >= 18 {
        let remaining_today: i64 = sqlx::query_as::<_, (i64,)>(
            "SELECT COUNT(*) FROM daily_plans
             WHERE date = DATE('now', 'localtime') AND completed = 0",
        )
        .fetch_one(pool)
        .await
        .map(|(n,)| n)
        .unwrap_or(0);

        if remaining_today >= 4 {
            spikes.push(format!(
                "🌙 LATE_OVERLOAD: {} tasks still undone at {:02}:00 — don't pile on, help Sean pick ONE and defer the rest",
                remaining_today, hour
            ));
        }
    }

    spikes
}
