/// CADEN Behavioral State Engine
///
/// Tracks Sean's mood, energy, thought patterns, and medication timing
/// using a combination of:
///   - Silent LLM extraction on every message (passive, never shown to user)
///   - Natural language medication logging ("took my quetiapine at 10pm")
///   - Rolling 5-day baseline with deviation scoring
///   - Episode risk classification (low / manic / depressive / mixed / burnout)
///   - PK medication timing model (pharmacokinetics → low/peak performance windows)
///   - Session metadata tracking (wake proxy, output volume, fragmentation)
///   - Daily state rollup (one row per day aggregated from factor_snapshots)
///
/// All data is stored locally in SQLite. Nothing leaves the device.
use anyhow::Result;
use chrono::{Local, NaiveTime, TimeZone, Timelike, Utc};
use serde::{Deserialize, Serialize};
use sqlx::SqlitePool;

// ─── Core types ──────────────────────────────────────────────────────────────

/// Structured state extracted from a single message via silent LLM pass.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct FactorExtraction {
    pub mood_score: Option<f64>,
    pub energy_level: Option<f64>,
    pub anxiety_level: Option<f64>,
    pub sleep_hours_implied: Option<f64>,
    /// "fragmented" | "normal" | "racing"
    pub thought_coherence: Option<String>,
    /// "past" | "present" | "future" | "mixed"
    pub temporal_focus: Option<String>,
    /// "negative" | "neutral" | "positive" | "mixed"
    pub emotional_valence: Option<String>,
    pub ideation_pressure: Option<bool>,
    /// 0.0–1.0 — how much evidence the message actually provides
    pub state_confidence: Option<f64>,
    pub notes: Option<String>,
}

/// Episode risk level for planning and briefing purposes.
#[derive(Debug, Clone, PartialEq)]
pub enum EpisodeRisk {
    Low,
    ElevatedManic,
    ElevatedDepressive,
    Mixed,
    Burnout,
}

impl EpisodeRisk {
    pub fn as_str(&self) -> &'static str {
        match self {
            EpisodeRisk::Low => "low",
            EpisodeRisk::ElevatedManic => "elevated_manic",
            EpisodeRisk::ElevatedDepressive => "elevated_depressive",
            EpisodeRisk::Mixed => "mixed",
            EpisodeRisk::Burnout => "burnout",
        }
    }
}

// ─── Storage ─────────────────────────────────────────────────────────────────

/// Persist a factor extraction to the DB.
/// Silently drops low-confidence snapshots (< 0.3) to avoid noise.
pub async fn store_factor_snapshot(
    pool: &SqlitePool,
    extraction: &FactorExtraction,
    source: &str,
) -> Result<()> {
    let confidence = extraction.state_confidence.unwrap_or(0.0);
    if confidence < 0.3 {
        return Ok(());
    }

    let id = crate::db::ops::generate_id();
    let now = Utc::now().timestamp();

    sqlx::query(
        "INSERT INTO factor_snapshots
         (id, timestamp, source, mood_score, energy_level, anxiety_level,
          thought_coherence, temporal_focus, valence, sleep_hours_implied, confidence, raw_notes)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(&id)
    .bind(now)
    .bind(source)
    .bind(extraction.mood_score)
    .bind(extraction.energy_level)
    .bind(extraction.anxiety_level)
    .bind(&extraction.thought_coherence)
    .bind(&extraction.temporal_focus)
    .bind(&extraction.emotional_valence)
    .bind(extraction.sleep_hours_implied)
    .bind(confidence)
    .bind(&extraction.notes)
    .execute(pool)
    .await?;

    Ok(())
}

/// Log a medication dose event to the medication_log table.
pub async fn log_medication(
    pool: &SqlitePool,
    medication_name: &str,
    dose_time_unix: i64,
    dose_mg: Option<f64>,
    notes: Option<&str>,
) -> Result<()> {
    let id = crate::db::ops::generate_id();
    let now = Utc::now().timestamp();

    sqlx::query(
        "INSERT INTO medication_log (id, logged_at, medication_name, dose_time, dose_mg, notes)
         VALUES (?, ?, ?, ?, ?, ?)",
    )
    .bind(&id)
    .bind(now)
    .bind(medication_name)
    .bind(dose_time_unix)
    .bind(dose_mg)
    .bind(notes)
    .execute(pool)
    .await?;

    Ok(())
}

// ─── State assessment ─────────────────────────────────────────────────────────

/// Get rolling averages from the last `days` days of factor snapshots.
/// Returns (avg_energy, avg_mood, avg_anxiety) — any may be None if no data.
pub async fn get_rolling_averages(
    pool: &SqlitePool,
    days: i64,
) -> (Option<f64>, Option<f64>, Option<f64>) {
    let cutoff = Utc::now().timestamp() - (days * 24 * 3600);
    let result: Option<(Option<f64>, Option<f64>, Option<f64>)> = sqlx::query_as(
        "SELECT AVG(energy_level), AVG(mood_score), AVG(anxiety_level)
         FROM factor_snapshots
         WHERE timestamp > ? AND confidence >= 0.4",
    )
    .bind(cutoff)
    .fetch_optional(pool)
    .await
    .unwrap_or(None);

    result.unwrap_or((None, None, None))
}

/// Assess episode risk from the last 48 hours of snapshots.
/// Returns (risk_level, confidence_0_to_1, human-readable details).
pub async fn assess_episode_risk(pool: &SqlitePool) -> (EpisodeRisk, f64, String) {
    let cutoff = Utc::now().timestamp() - (48 * 3600);

    let rows: Vec<(Option<f64>, Option<f64>, Option<f64>, Option<String>)> = sqlx::query_as(
        "SELECT energy_level, mood_score, anxiety_level, thought_coherence
         FROM factor_snapshots
         WHERE timestamp > ? AND confidence >= 0.4
         ORDER BY timestamp DESC
         LIMIT 20",
    )
    .bind(cutoff)
    .fetch_all(pool)
    .await
    .unwrap_or_default();

    if rows.is_empty() {
        return (
            EpisodeRisk::Low,
            0.0,
            "Insufficient data — send more messages to build baseline".to_string(),
        );
    }

    let n = rows.len() as f64;
    let energies: Vec<f64> = rows.iter().filter_map(|(e, _, _, _)| *e).collect();
    let moods: Vec<f64> = rows.iter().filter_map(|(_, m, _, _)| *m).collect();
    let anxieties: Vec<f64> = rows.iter().filter_map(|(_, _, a, _)| *a).collect();
    let racing = rows
        .iter()
        .filter(|(_, _, _, tc)| tc.as_deref() == Some("racing"))
        .count();
    let fragmented = rows
        .iter()
        .filter(|(_, _, _, tc)| tc.as_deref() == Some("fragmented"))
        .count();

    if energies.is_empty() && moods.is_empty() {
        return (EpisodeRisk::Low, 0.0, String::new());
    }

    let avg_energy = if energies.is_empty() {
        5.0
    } else {
        energies.iter().sum::<f64>() / energies.len() as f64
    };
    let avg_mood = if moods.is_empty() {
        5.0
    } else {
        moods.iter().sum::<f64>() / moods.len() as f64
    };
    let avg_anxiety = if anxieties.is_empty() {
        5.0
    } else {
        anxieties.iter().sum::<f64>() / anxieties.len() as f64
    };
    let racing_ratio = racing as f64 / n;

    // Mixed state: high energy + low mood (dysphoric mania — highest-risk combination)
    if avg_energy >= 7.0 && avg_mood <= 4.0 {
        let conf =
            ((avg_energy - 7.0) / 3.0 * 0.5 + (4.0 - avg_mood) / 4.0 * 0.5).min(1.0);
        return (
            EpisodeRisk::Mixed,
            conf,
            format!(
                "Energy {:.1}/10 with mood {:.1}/10 — mixed/dysphoric pattern. High impulsivity risk.",
                avg_energy, avg_mood
            ),
        );
    }

    // Manic/hypomanic: high energy + racing thoughts
    if avg_energy >= 7.5 && racing_ratio > 0.35 {
        let conf = ((avg_energy - 7.5) / 2.5 * 0.6 + racing_ratio * 0.4).min(1.0);
        return (
            EpisodeRisk::ElevatedManic,
            conf,
            format!(
                "Energy {:.1}/10 + racing thoughts in {:.0}% of signals — hypomanic trajectory.",
                avg_energy,
                racing_ratio * 100.0
            ),
        );
    }

    // Burnout: high anxiety + low energy + fragmented thinking
    if avg_anxiety >= 6.5 && avg_energy <= 5.0 && fragmented as f64 / n > 0.3 {
        let conf = ((avg_anxiety - 6.5) / 3.5 * 0.4
            + (5.0 - avg_energy).max(0.0) / 5.0 * 0.3
            + fragmented as f64 / n * 0.3)
            .min(1.0);
        return (
            EpisodeRisk::Burnout,
            conf,
            format!(
                "High anxiety ({:.1}/10) + low energy ({:.1}/10) + fragmented thinking — burnout pattern.",
                avg_anxiety, avg_energy
            ),
        );
    }

    // Depressive: low energy + low mood sustained
    if avg_energy <= 3.5 && avg_mood <= 4.0 {
        let conf =
            ((3.5 - avg_energy) / 3.5 * 0.5 + (4.0 - avg_mood) / 4.0 * 0.5).min(1.0);
        return (
            EpisodeRisk::ElevatedDepressive,
            conf,
            format!(
                "Low energy ({:.1}/10) + low mood ({:.1}/10) — depressive pattern. Reduce task pressure.",
                avg_energy, avg_mood
            ),
        );
    }

    (EpisodeRisk::Low, 0.1, String::new())
}

/// Fetch recent medication logs for the last 24 hours.
pub async fn get_recent_medications(pool: &SqlitePool) -> Vec<(String, i64)> {
    let cutoff = Utc::now().timestamp() - (24 * 3600);
    sqlx::query_as::<_, (String, i64)>(
        "SELECT medication_name, dose_time FROM medication_log
         WHERE dose_time > ? ORDER BY dose_time DESC LIMIT 8",
    )
    .bind(cutoff)
    .fetch_all(pool)
    .await
    .unwrap_or_default()
}

// ─── Briefing ─────────────────────────────────────────────────────────────────

/// Build the behavioral state section for the Sean Model briefing.
/// Injected into every LLM context so CADEN is always aware of Sean's current state.
pub async fn build_state_briefing(pool: &SqlitePool) -> String {
    let (avg_energy, avg_mood, avg_anxiety) = get_rolling_averages(pool, 5).await;
    let (risk, confidence, risk_notes) = assess_episode_risk(pool).await;
    let meds = get_recent_medications(pool).await;

    let mut lines = vec!["=== BEHAVIORAL STATE ===".to_string()];

    if avg_energy.is_some() || avg_mood.is_some() {
        let e_str = avg_energy
            .map(|v| format!("{:.1}/10", v))
            .unwrap_or_else(|| "?".to_string());
        let m_str = avg_mood
            .map(|v| format!("{:.1}/10", v))
            .unwrap_or_else(|| "?".to_string());
        let a_str = avg_anxiety
            .map(|v| format!("{:.1}/10", v))
            .unwrap_or_else(|| "?".to_string());
        lines.push(format!(
            "5-day rolling: Energy {e_str} | Mood {m_str} | Anxiety {a_str}"
        ));
    } else {
        lines.push(
            "Behavioral state: still calibrating — insufficient data yet.".to_string(),
        );
    }

    if risk != EpisodeRisk::Low && confidence > 0.3 && !risk_notes.is_empty() {
        lines.push(format!(
            "⚠ State flag: {} ({:.0}% confidence) — {}",
            risk.as_str().replace('_', " "),
            confidence * 100.0,
            risk_notes
        ));
    }

    if !meds.is_empty() {
        let med_strs: Vec<String> = meds
            .iter()
            .map(|(name, t)| {
                let dt = Utc
                    .timestamp_opt(*t, 0)
                    .single()
                    .map(|d| d.with_timezone(&Local).format("%-I:%M %p").to_string())
                    .unwrap_or_else(|| "??:??".to_string());
                format!("{} @ {}", name, dt)
            })
            .collect();
        lines.push(format!(
            "Medications (last 24h): {}",
            med_strs.join(", ")
        ));
    }

    lines.push("=== END BEHAVIORAL STATE ===".to_string());
    lines.join("\n")
}

// ─── LLM extraction prompt ────────────────────────────────────────────────────

/// Build the silent extraction prompt for a user message.
/// The result goes to a background LLM call the user never sees.
pub fn build_extraction_prompt(message: &str) -> String {
    format!(
        r#"You are a silent clinical state analyst. The user does not know you are analyzing this message and will never see your output.

Analyze the following message for behavioral and mood signals. Return ONLY a valid JSON object — no markdown fences, no explanation, no extra text.

Message: "{}"

Return exactly this JSON structure (use null for fields with insufficient evidence):
{{
  "mood_score": <1-10 where 1=severely depressed, 5=neutral, 10=extremely elevated — null if uninferable>,
  "energy_level": <1-10 where 1=barely functional, 5=normal, 10=racing/can't stop — null if uninferable>,
  "anxiety_level": <1-10 where 1=none, 5=moderate, 10=severe — null if uninferable>,
  "sleep_hours_implied": <hours of sleep mentioned or implied — null if not mentioned>,
  "thought_coherence": <"fragmented"|"normal"|"racing" — null if uninferable>,
  "temporal_focus": <"past"|"present"|"future"|"mixed" — null if uninferable>,
  "emotional_valence": <"negative"|"neutral"|"positive"|"mixed" — null if uninferable>,
  "ideation_pressure": <true if pressured/fast/unstoppable thinking, false, or null>,
  "state_confidence": <0.0-1.0 — short/casual messages = 0.1, rich emotional content = 0.7+>,
  "notes": "<1 sentence of key reasoning — null if nothing notable>"
}}

Base your analysis ONLY on explicit linguistic evidence in the message. Never fabricate signals. Short task-focused messages should have state_confidence below 0.3."#,
        message.replace('"', "'")
    )
}

// ─── Goal progress extraction ─────────────────────────────────────────────────

/// Build a prompt to silently extract goal-relevant progress from a user message.
/// Only called when active goals exist. Returns JSON with goal_id + delta + note.
pub fn build_goal_extraction_prompt(message: &str, goals_json: &str) -> String {
    format!(
        r#"You are a silent goal progress tracker. The user does not know you are analyzing this message.

Active goals:
{goals_json}

Analyze the following message for ANY progress, setbacks, or updates related to these goals.
Return ONLY valid JSON — no markdown fences, no explanation.

Message: "{msg}"

Return exactly this JSON structure:
{{
  "updates": [
    {{
      "goal_id": "<id of the goal this update is about>",
      "delta": <numeric progress change — positive for progress, negative for setback, 0 for informational>,
      "note": "<1-sentence description of what happened>"
    }}
  ],
  "confidence": <0.0-1.0 — 0.0 if nothing goal-related, 0.7+ if explicit progress mentioned>
}}

Rules:
- Only include updates for goals that are CLEARLY referenced in the message.
- If the message mentions completing a task/assignment, match it to the most relevant goal.
- "I finished chapter 5" → delta = 1 for a reading goal.
- "I worked on my project for 2 hours" → delta = 2 if the goal tracks hours.
- If no goals are referenced, return {{"updates": [], "confidence": 0.0}}.
- Never fabricate progress. Only extract what is explicitly stated or strongly implied."#,
        goals_json = goals_json,
        msg = message.replace('"', "'")
    )
}

/// Apply extracted goal progress updates to the database.
pub async fn apply_goal_updates(
    pool: &SqlitePool,
    updates: &[GoalUpdate],
) {
    let now = chrono::Utc::now().to_rfc3339();
    for u in updates {
        if u.delta.abs() < f64::EPSILON && u.note.is_none() {
            continue;
        }
        let id = crate::db::ops::generate_id();
        let _ = sqlx::query(
            "INSERT INTO goal_progress (id, goal_id, delta, note, source, timestamp)
             VALUES (?, ?, ?, ?, 'llm', ?)",
        )
        .bind(&id)
        .bind(&u.goal_id)
        .bind(u.delta)
        .bind(&u.note)
        .bind(&now)
        .execute(pool)
        .await;

        if u.delta.abs() > f64::EPSILON {
            let _ = sqlx::query(
                "UPDATE goals SET current_value = current_value + ?, updated_at = ? WHERE id = ?",
            )
            .bind(u.delta)
            .bind(&now)
            .bind(&u.goal_id)
            .execute(pool)
            .await;
        }
    }
}

/// Fetch active goals as a compact JSON string for the extraction prompt.
pub async fn get_active_goals_for_extraction(pool: &SqlitePool) -> Option<String> {
    let rows: Vec<(String, String, Option<String>, String, Option<f64>, Option<String>, f64)> =
        sqlx::query_as(
            "SELECT id, title, description, category, target_value, target_unit, current_value
             FROM goals WHERE status = 'active'",
        )
        .fetch_all(pool)
        .await
        .unwrap_or_default();

    if rows.is_empty() {
        return None;
    }

    let entries: Vec<String> = rows.iter().map(|r| {
        let target_info = match (&r.4, &r.5) {
            (Some(tv), Some(tu)) => format!(", target: {} {}, current: {}", tv, tu, r.6),
            _ => String::new(),
        };
        format!("- [{}] {} ({}){}", r.0, r.1, r.3, target_info)
    }).collect();

    Some(entries.join("\n"))
}

#[derive(Debug, serde::Deserialize)]
pub struct GoalExtractionResult {
    pub updates: Vec<GoalUpdate>,
    pub confidence: f64,
}

#[derive(Debug, serde::Deserialize)]
pub struct GoalUpdate {
    pub goal_id: String,
    pub delta: f64,
    pub note: Option<String>,
}

// ─── Medication natural language parser ───────────────────────────────────────

/// Known medication aliases → canonical names.
const MEDICATIONS: &[(&str, &str)] = &[
    ("quetiapine", "quetiapine"),
    ("seroquel", "quetiapine"),
    ("lithium", "lithium"),
    ("lamotrigine", "lamotrigine"),
    ("lamictal", "lamotrigine"),
    ("aripiprazole", "aripiprazole"),
    ("abilify", "aripiprazole"),
    ("adderall", "adderall"),
    ("amphetamine salts", "adderall"),
    ("vyvanse", "vyvanse"),
    ("lisdexamfetamine", "vyvanse"),
    ("ritalin", "methylphenidate"),
    ("methylphenidate", "methylphenidate"),
    ("concerta", "methylphenidate"),
    ("valproate", "valproate"),
    ("depakote", "valproate"),
    ("valproic acid", "valproate"),
    ("olanzapine", "olanzapine"),
    ("zyprexa", "olanzapine"),
    ("clonazepam", "clonazepam"),
    ("klonopin", "clonazepam"),
    ("lorazepam", "lorazepam"),
    ("ativan", "lorazepam"),
    ("sertraline", "sertraline"),
    ("zoloft", "sertraline"),
    ("fluoxetine", "fluoxetine"),
    ("prozac", "fluoxetine"),
    ("bupropion", "bupropion"),
    ("wellbutrin", "bupropion"),
    ("modafinil", "modafinil"),
    ("provigil", "modafinil"),
    ("escitalopram", "escitalopram"),
    ("lexapro", "escitalopram"),
    ("buspirone", "buspirone"),
    ("buspar", "buspirone"),
];

/// Parse medication logging from a natural language message.
///
/// Detects patterns like:
/// - "took my quetiapine at 10pm"
/// - "just took lithium 300mg"
/// - "took adderall at 8:30"
///
/// Returns list of (canonical_med_name, dose_time_unix, dose_mg).
const MED_VERBS: &[&str] = &["took ", "taken my ", "just took", "taking my "];

fn has_med_verb(text: &str) -> bool {
    MED_VERBS.iter().any(|p| text.contains(p))
}

pub fn parse_medication_from_text(text: &str, now_unix: i64) -> Vec<(String, i64, Option<f64>)> {
    let lower = text.to_lowercase();

    if !has_med_verb(&lower) {
        return vec![];
    }

    let mut results = vec![];

    for (keyword, canonical) in MEDICATIONS {
        if !lower.contains(keyword) {
            continue;
        }
        let dose_time = parse_time_from_text(&lower, now_unix);
        let dose_mg = parse_dose_mg(&lower);
        results.push((canonical.to_string(), dose_time, dose_mg));
    }

    // Fallback: bare "meds" / "medication" / "my meds" with no specific drug name
    // Log as generic "medication" so the timestamp is at least captured.
    if results.is_empty()
        && (lower.contains(" meds") || lower.contains("my meds")
            || lower.contains(" medication") || lower.contains("my medication")
            || lower.contains(" pills") || lower.contains("my pills"))
    {
        let dose_time = parse_time_from_text(&lower, now_unix);
        let dose_mg = parse_dose_mg(&lower);
        results.push(("medication".to_string(), dose_time, dose_mg));
    }

    results
}

/// Parse "took my morning meds" / "took my evening meds" using the user's configured
/// med groups. Returns one entry per medication in the matched group.
/// PK calculations use individual med stats, not the group label.
pub fn parse_med_groups_from_text(
    text: &str,
    now_unix: i64,
    morning_meds: &[crate::db::models::MedGroupEntry],
    evening_meds: &[crate::db::models::MedGroupEntry],
) -> Vec<(String, i64, Option<f64>)> {
    let lower = text.to_lowercase();

    if !has_med_verb(&lower) {
        return vec![];
    }

    let dose_time = parse_time_from_text(&lower, now_unix);

    // Does the message mention meds at all (group or bare)?
    let mentions_meds = lower.contains("med") || lower.contains("pill") || lower.contains("dose");
    if !mentions_meds {
        return vec![];
    }

    let is_morning = ["morning med", "am med", "morning pill", "morning dose"]
        .iter().any(|kw| lower.contains(kw));
    let is_evening = ["evening med", "night med", "pm med", "evening pill",
        "night pill", "evening dose", "night dose", "last night", "tonight"]
        .iter().any(|kw| lower.contains(kw));

    // Infer from hour if no explicit label
    let inferred_evening = if !is_morning && !is_evening {
        let local_hour = chrono::Local::now().hour();
        local_hour >= 17 || local_hour < 4
    } else {
        false
    };

    let group: &[crate::db::models::MedGroupEntry] = if is_morning {
        morning_meds
    } else if is_evening || inferred_evening {
        evening_meds
    } else {
        morning_meds // daytime default
    };

    group
        .iter()
        .map(|entry| (entry.name.clone(), dose_time, entry.dose_mg))
        .collect()
}

/// Extract a unix timestamp from a time expression in text.
/// Falls back to now_unix if nothing is found.
fn scan_words_for_time(words: &[&str], date: chrono::NaiveDate) -> Option<i64> {
    for (i, word) in words.iter().enumerate() {
        if *word == "at" || *word == "@" {
            if let Some(next) = words.get(i + 1) {
                let suffix = words.get(i + 2).copied();
                if let Some(t) = try_parse_time_word(next, suffix) {
                    let naive_dt = date.and_time(t);
                    if let Some(local_dt) = Local.from_local_datetime(&naive_dt).single() {
                        return Some(local_dt.timestamp());
                    }
                }
            }
        }
    }
    None
}

fn parse_time_from_text(lower: &str, now_unix: i64) -> i64 {
    let now_dt = Utc
        .timestamp_opt(now_unix, 0)
        .single()
        .map(|d| d.with_timezone(&Local))
        .unwrap_or_else(Local::now);
    let today = now_dt.date_naive();

    let words: Vec<&str> = lower.split_whitespace().collect();
    if let Some(ts) = scan_words_for_time(&words, today) {
        return ts;
    }

    if lower.contains("just now") || lower.contains("right now") || lower.contains("a moment ago") {
        return now_unix;
    }
    if lower.contains("an hour ago") || lower.contains("1 hour ago") {
        return now_unix - 3600;
    }
    if lower.contains("30 min") || lower.contains("half an hour ago") {
        return now_unix - 1800;
    }

    // "last night" / "yesterday" — scan against yesterday's date
    if lower.contains("last night") || lower.contains("yesterday") {
        let yesterday = today - chrono::Duration::days(1);
        if let Some(ts) = scan_words_for_time(&words, yesterday) {
            return ts;
        }
        // No explicit time — default to 10pm yesterday for "last night"
        let naive_dt = yesterday.and_hms_opt(22, 0, 0).unwrap();
        if let Some(local_dt) = Local.from_local_datetime(&naive_dt).single() {
            return local_dt.timestamp();
        }
    }

    now_unix
}

fn try_parse_time_word(word: &str, next_word: Option<&str>) -> Option<NaiveTime> {
    let word = word.trim_end_matches([',', '.', ';']);
    let has_pm = word.ends_with("pm") || next_word == Some("pm");
    let has_am = word.ends_with("am") || next_word == Some("am");
    let time_str = word.trim_end_matches("pm").trim_end_matches("am");

    if let Ok(t) = NaiveTime::parse_from_str(time_str, "%H:%M") {
        let hour = t.hour();
        let (h, _) = if has_pm && hour < 12 {
            (hour + 12, 0u32)
        } else if has_am && hour == 12 {
            (0, 0u32)
        } else {
            (hour, 0)
        };
        return NaiveTime::from_hms_opt(h, t.minute(), 0);
    }

    if let Ok(h) = time_str.parse::<u32>() {
        if h <= 23 {
            let hour = if has_pm && h < 12 {
                h + 12
            } else if has_am && h == 12 {
                0
            } else {
                h
            };
            return NaiveTime::from_hms_opt(hour, 0, 0);
        }
    }

    None
}

fn parse_dose_mg(lower: &str) -> Option<f64> {
    for word in lower.split_whitespace() {
        if word.ends_with("mg") {
            let n_str = word.trim_end_matches("mg");
            if let Ok(n) = n_str.parse::<f64>() {
                return Some(n);
            }
        }
    }
    None
}

// ─── PK Medication Timing Model (TODO 1) ─────────────────────────────────────
//
// Each medication has a pharmacokinetic profile describing:
//   - onset_hours: when effects begin to be noticeable after dose
//   - peak_hours: duration of peak performance window after onset
//   - trough_hours: low/sedated window (H1 hangover for quetiapine, crash for stimulants)
//   - trough_relative_to: "dose" or "wake" (quetiapine hangover = relative to wake time)
//
// The planner calls `get_low_performance_hours_today` to get a set of local hours
// that should not be scheduled for high-demand cognitive work.

struct PkProfile {
    /// Hours after dose when trough/impairment begins
    trough_start_hours: f64,
    /// Duration of the trough/low window in hours
    trough_duration_hours: f64,
    /// Whether the trough is relative to dose time ("dose") or wake time ("wake")
    trough_anchor: &'static str,
    /// Hours after dose when peak performance begins
    peak_start_hours: f64,
    /// Duration of peak window in hours
    peak_duration_hours: f64,
}

fn pk_profile_for(medication: &str) -> Option<PkProfile> {
    match medication.to_lowercase().as_str() {
        // Quetiapine: H1-hangover in first 2-4h after waking regardless of dose time
        "quetiapine" => Some(PkProfile {
            trough_start_hours: 0.0,   // from wake
            trough_duration_hours: 3.0,
            trough_anchor: "wake",
            peak_start_hours: 3.0,     // from wake
            peak_duration_hours: 8.0,
        }),
        // Lithium: flat profile, no significant intra-day variation
        "lithium" | "valproate" | "lamotrigine" | "aripiprazole" | "buspirone" => None,
        // Adderall IR: crash at T+4-6h from dose
        "adderall" => Some(PkProfile {
            trough_start_hours: 4.0,
            trough_duration_hours: 2.5,
            trough_anchor: "dose",
            peak_start_hours: 1.0,
            peak_duration_hours: 2.5,
        }),
        // Vyvanse: smooth curve, longer peak, softer descent
        "vyvanse" => Some(PkProfile {
            trough_start_hours: 10.0,
            trough_duration_hours: 4.0,
            trough_anchor: "dose",
            peak_start_hours: 2.0,
            peak_duration_hours: 6.0,
        }),
        // Methylphenidate IR: quick crash at T+3-5h
        "methylphenidate" => Some(PkProfile {
            trough_start_hours: 3.0,
            trough_duration_hours: 2.5,
            trough_anchor: "dose",
            peak_start_hours: 1.0,
            peak_duration_hours: 1.5,
        }),
        // Stimulants with long half-life: modafinil
        "modafinil" => Some(PkProfile {
            trough_start_hours: 12.0,
            trough_duration_hours: 3.0,
            trough_anchor: "dose",
            peak_start_hours: 1.0,
            peak_duration_hours: 8.0,
        }),
        // Benzodiazepines: onset sedation within 1h, lasts 4-6h
        "clonazepam" | "lorazepam" => Some(PkProfile {
            trough_start_hours: 0.25,
            trough_duration_hours: 5.0,
            trough_anchor: "dose",
            peak_start_hours: 999.0, // no cognitive peak
            peak_duration_hours: 0.0,
        }),
        _ => None,
    }
}

/// A window in local clock hours (0–23) during which cognitive performance
/// is expected to be low or high, based on medications taken today.
#[derive(Debug, Clone, Serialize)]
pub struct PerformanceWindow {
    /// "low" or "peak"
    pub kind: String,
    pub start_hour: u32,
    pub end_hour: u32,
    pub medication: String,
}

/// Compute low and peak performance windows for today based on logged medications.
/// Returns a list of PerformanceWindow entries covering today's local clock.
pub async fn get_performance_windows_today(pool: &SqlitePool) -> Vec<PerformanceWindow> {
    let meds = get_recent_medications(pool).await;
    if meds.is_empty() {
        return vec![];
    }

    // We need wake time for "wake"-anchored troughs (quetiapine).
    // Use the first-message-of-day timestamp from daily_state if available,
    // otherwise fall back to 8:00 local.
    let today_str = Local::now().format("%Y-%m-%d").to_string();
    let wake_hour: u32 = sqlx::query_as::<_, (Option<String>,)>(
        "SELECT wake_time FROM daily_state WHERE date = ?",
    )
    .bind(&today_str)
    .fetch_optional(pool)
    .await
    .ok()
    .flatten()
    .and_then(|(wt,)| wt)
    .and_then(|s| NaiveTime::parse_from_str(&s, "%H:%M").ok())
    .map(|t| t.hour())
    .unwrap_or(8);

    let mut windows = vec![];

    for (med_name, dose_time_unix) in &meds {
        let Some(profile) = pk_profile_for(med_name) else {
            continue;
        };

        // Convert unix dose time to local hour
        let dose_local_hour = Utc
            .timestamp_opt(*dose_time_unix, 0)
            .single()
            .map(|d| d.with_timezone(&Local).hour())
            .unwrap_or(22); // default: evening dose

        let anchor_hour = if profile.trough_anchor == "wake" {
            wake_hour
        } else {
            dose_local_hour
        };

        // Trough window
        let trough_start = anchor_hour + profile.trough_start_hours as u32;
        let trough_end = trough_start + profile.trough_duration_hours as u32;
        if trough_end <= 24 {
            windows.push(PerformanceWindow {
                kind: "low".to_string(),
                start_hour: trough_start.min(23),
                end_hour: trough_end.min(24),
                medication: med_name.clone(),
            });
        }

        // Peak window (skip if no peak, e.g., benzos)
        if profile.peak_duration_hours > 0.0 {
            let peak_anchor = if profile.trough_anchor == "wake" {
                wake_hour
            } else {
                dose_local_hour
            };
            let peak_start = peak_anchor + profile.peak_start_hours as u32;
            let peak_end = peak_start + profile.peak_duration_hours as u32;
            if peak_end <= 24 {
                windows.push(PerformanceWindow {
                    kind: "peak".to_string(),
                    start_hour: peak_start.min(23),
                    end_hour: peak_end.min(24),
                    medication: med_name.clone(),
                });
            }
        }
    }

    windows
}

/// Returns the set of local hours today that are low-performance due to medication.
/// The planner calls this to avoid scheduling hard tasks in these hours.
pub async fn get_low_performance_hours_today(pool: &SqlitePool) -> Vec<u32> {
    let windows = get_performance_windows_today(pool).await;
    let mut hours = vec![];
    for w in windows {
        if w.kind == "low" {
            for h in w.start_hour..w.end_hour.min(24) {
                if !hours.contains(&h) {
                    hours.push(h);
                }
            }
        }
    }
    hours
}

// ─── Session Metadata Tracking (TODO 4) ───────────────────────────────────────
//
// Called on every incoming message from commands.rs.
// Tracks:
//   - first message of day → wake proxy (stored in daily_state.wake_time)
//   - output volume (cumulative chars typed today)
//   - session count (distinct activity sessions — gap > 30 min = new session)

/// Record session metadata for a message event.
/// `message_len` is the number of characters in the user's message.
/// This is intentionally lightweight — all DB writes are INSERT OR REPLACE.
pub async fn record_session_event(pool: &SqlitePool, message_len: usize) {
    let now = Local::now();
    let today = now.format("%Y-%m-%d").to_string();
    let time_str = now.format("%H:%M").to_string();
    let now_unix = Utc::now().timestamp();

    // Fetch existing row for today
    let existing: Option<(Option<String>, i64, i64)> = sqlx::query_as(
        "SELECT wake_time, output_volume, session_count FROM daily_state WHERE date = ?",
    )
    .bind(&today)
    .fetch_optional(pool)
    .await
    .ok()
    .flatten();

    let (wake_time, prev_volume, prev_sessions) = match existing {
        Some((wt, ov, sc)) => (wt, ov, sc),
        None => (None, 0, 0),
    };

    // First message of day → set wake_time
    let wake_time = wake_time.unwrap_or_else(|| time_str.clone());

    // Count as a new session if this is the first message of the day or
    // if there was a gap > 30 min since last recorded event.
    let last_event_ts: Option<i64> = sqlx::query_as::<_, (i64,)>(
        "SELECT MAX(timestamp) FROM factor_snapshots WHERE timestamp > ?",
    )
    .bind(now_unix - 3600) // look back 1h
    .fetch_optional(pool)
    .await
    .ok()
    .flatten()
    .map(|(t,)| t);

    let gap_minutes = last_event_ts
        .map(|t| (now_unix - t) / 60)
        .unwrap_or(999); // no recent events → treat as new session

    let new_sessions = if prev_sessions == 0 || gap_minutes > 30 {
        prev_sessions + 1
    } else {
        prev_sessions
    };

    let new_volume = prev_volume + message_len as i64;

    sqlx::query(
        "INSERT INTO daily_state (date, wake_time, output_volume, session_count)
         VALUES (?, ?, ?, ?)
         ON CONFLICT(date) DO UPDATE SET
           wake_time = COALESCE(daily_state.wake_time, excluded.wake_time),
           output_volume = excluded.output_volume,
           session_count = excluded.session_count",
    )
    .bind(&today)
    .bind(&wake_time)
    .bind(new_volume)
    .bind(new_sessions)
    .execute(pool)
    .await
    .ok();
}

// ─── Daily State Rollup (TODO 5) ─────────────────────────────────────────────
//
// Aggregates all factor_snapshots from today into the daily_state row.
// Also computes episode_risk and risk_confidence.
// Called once per day (or on-demand from sync_all).

pub async fn rollup_daily_state(pool: &SqlitePool) {
    let today = Local::now().format("%Y-%m-%d").to_string();
    let day_start = {
        let d = Local::now().date_naive();
        chrono::Local
            .from_local_datetime(
                &d.and_time(NaiveTime::from_hms_opt(0, 0, 0).unwrap()),
            )
            .single()
            .map(|dt| dt.with_timezone(&Utc).timestamp())
            .unwrap_or(Utc::now().timestamp() - 86400)
    };

    let result: Option<(Option<f64>, Option<f64>, Option<f64>, Option<f64>)> = sqlx::query_as(
        "SELECT AVG(energy_level), AVG(mood_score), AVG(anxiety_level), AVG(sleep_hours_implied)
         FROM factor_snapshots
         WHERE timestamp >= ? AND confidence >= 0.4",
    )
    .bind(day_start)
    .fetch_optional(pool)
    .await
    .ok()
    .flatten();

    let thought_pattern: Option<String> = sqlx::query_as::<_, (String, i64)>(
        "SELECT thought_coherence, COUNT(*) AS n FROM factor_snapshots
         WHERE timestamp >= ? AND thought_coherence IS NOT NULL
         GROUP BY thought_coherence ORDER BY n DESC LIMIT 1",
    )
    .bind(day_start)
    .fetch_optional(pool)
    .await
    .ok()
    .flatten()
    .map(|(tc, _)| tc);

    let (risk, confidence, _) = assess_episode_risk(pool).await;

    if let Some((avg_e, avg_m, avg_a, avg_sleep)) = result {
        sqlx::query(
            "INSERT INTO daily_state
               (date, avg_energy, avg_mood, avg_anxiety, sleep_hours, thought_pattern,
                episode_risk, risk_confidence)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?)
             ON CONFLICT(date) DO UPDATE SET
               avg_energy = excluded.avg_energy,
               avg_mood = excluded.avg_mood,
               avg_anxiety = excluded.avg_anxiety,
               sleep_hours = excluded.sleep_hours,
               thought_pattern = excluded.thought_pattern,
               episode_risk = excluded.episode_risk,
               risk_confidence = excluded.risk_confidence",
        )
        .bind(&today)
        .bind(avg_e)
        .bind(avg_m)
        .bind(avg_a)
        .bind(avg_sleep)
        .bind(thought_pattern.as_deref())
        .bind(risk.as_str())
        .bind(confidence)
        .execute(pool)
        .await
        .ok();
    }
}

// ─── JITAI — Just-In-Time Adaptive Intervention (TODO 3) ─────────────────────
//
// After each message CADEN sends, this function decides whether to append
// one naturalistic check-in question. Rules:
//   - Max 1 check-in per session (guarded by a session-level flag in daily_state)
//   - Only asks if passive signals show an anomaly worth confirming
//   - Framed conversationally — never sounds clinical
//   - Returns None if no check-in is warranted

/// How many check-ins have been delivered today?
#[allow(dead_code)]
async fn check_ins_today(pool: &SqlitePool) -> i64 {
    let today = Local::now().format("%Y-%m-%d").to_string();
    sqlx::query_as::<_, (Option<i64>,)>(
        "SELECT session_count FROM daily_state WHERE date = ?",
    )
    .bind(&today)
    .fetch_optional(pool)
    .await
    .ok()
    .flatten()
    .and_then(|(n,)| n)
    .unwrap_or(0)
    // We repurpose a lightweight heuristic: track check-ins via a settings key
    // to avoid adding yet another column. See `jitai_checkins_today` key.
    // This is fetched separately below.
}

/// Returns a naturalistic check-in sentence to append to CADEN's next response,
/// or None if no check-in is needed right now.
pub async fn get_jitai_prompt(pool: &SqlitePool) -> Option<String> {
    // Only deliver one check-in per calendar day
    let today = Local::now().format("%Y-%m-%d").to_string();
    let checkins_done: i64 = sqlx::query_as::<_, (Option<String>,)>(
        "SELECT value FROM settings WHERE key = 'jitai_checkin_date'",
    )
    .fetch_optional(pool)
    .await
    .ok()
    .flatten()
    .and_then(|(v,)| if v.as_deref() == Some(today.as_str()) { Some(1i64) } else { None })
    .unwrap_or(0);

    if checkins_done > 0 {
        return None;
    }

    // Only trigger if passive signals show something worth confirming
    let (risk, confidence, _) = assess_episode_risk(pool).await;
    let (avg_energy, avg_mood, _avg_anxiety) = get_rolling_averages(pool, 2).await;

    // Also check for rapid energy drop: compare last 4h average to 2-day rolling
    let (recent_energy, _, _) = get_rolling_averages(pool, 0).await; // today only
    let energy_dropping = match (recent_energy, avg_energy) {
        (Some(recent), Some(baseline)) => recent < baseline - 2.0, // dropped >2 points
        _ => false,
    };
    let mood_dropping = match (avg_mood, get_rolling_averages(pool, 5).await.1) {
        (Some(recent), Some(baseline)) => recent < baseline - 2.0,
        _ => false,
    };

    // Determine which question to ask based on what the signals show
    // Lower confidence threshold to 0.3 (was 0.4) — better to ask and be wrong
    // than to miss a real episode onset
    let question = match risk {
        EpisodeRisk::ElevatedManic if confidence > 0.3 => Some(
            "Quick gut check before I forget — how's your energy feeling right now, on a scale of 'running on fumes' to 'could start three companies'?"
        ),
        EpisodeRisk::ElevatedDepressive if confidence > 0.3 => Some(
            "How much brain do you actually have today? Like honestly — 'barely here' or 'functional human'?"
        ),
        EpisodeRisk::Mixed if confidence > 0.3 => Some(
            "You seem a bit wired-and-tired at the same time. Is that accurate or am I reading you wrong?"
        ),
        EpisodeRisk::Burnout if confidence > 0.3 => Some(
            "Real talk — are you running on fumes or do you actually have gas in the tank right now?"
        ),
        EpisodeRisk::Low if energy_dropping => Some(
            "Your energy seems like it's been dropping — you good, or is today more of a coast-it kind of day?"
        ),
        EpisodeRisk::Low if mood_dropping => Some(
            "Things feeling heavier than usual today? No judgment — just want to know if I should adjust the plan."
        ),
        EpisodeRisk::Low => {
            // Still ask if recent energy is very low or very high without a risk flag
            let e = avg_energy.unwrap_or(5.0);
            if e >= 8.0 {
                Some("Your energy's reading pretty high in what you're writing — riding that or does it feel a bit much?")
            } else if e <= 3.0 {
                Some("How'd you sleep last night? You're coming across a bit low-battery.")
            } else {
                None
            }
        }
        _ => None,
    };

    if let Some(q) = question {
        // Mark check-in as delivered for today
        sqlx::query(
            "INSERT INTO settings (key, value) VALUES ('jitai_checkin_date', ?)
             ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        )
        .bind(&today)
        .execute(pool)
        .await
        .ok();

        return Some(q.to_string());
    }

    None
}

