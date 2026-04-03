/// Training data collection for fine-tuning qwen3:7b to replace cloud models.
///
/// DESIGN INTENT — what is / isn't included in training examples:
///
/// The large persona/system prompt ("You are CADEN — Sean's digital homie…")
/// is intentionally EXCLUDED from training data. After fine-tuning, the model
/// should embody CADEN's voice and habits naturally — not because it was
/// instructed to. This mirrors how you'd train a person: you want them to just
/// *be* a certain way, not recite rules to themselves before every sentence.
///
/// What the training system prompt DOES include:
///   - The analysis brief (Call 2 output — what's actually happening)
///   - The situational briefing (schedule, state, mood, tasks — pure data)
///
/// This teaches the fine-tuned model: "given this context data, here is the
/// right response." The persona gets baked into weights through repeated
/// exposure to CADEN's actual response patterns.
///
/// For inference on the fine-tuned model, the system prompt shrinks to:
///   <current analysis brief> + <current situational data>
/// No persona block required — the model just knows how CADEN talks.
///
/// Background call examples (classify, analyze, mood, goal, data_report)
/// have NO system prompt in training — just task prompt → JSON output.
/// These teach reliable structured extraction, independent of persona.
///
/// THRESHOLDS for qwen3:7b reliability:
///   response    1500  — hardest task: voice + context use + persona
///   analyze      800  — context synthesis, moderately complex
///   classify     500  — 6-class JSON, simple enough to learn fast
///   mood         400  — narrow JSON schema, predictable
///   goal         400  — narrow JSON schema, predictable  
///   data_report  300  — pure number extraction, simplest

use anyhow::Result;
use sqlx::SqlitePool;
use tauri::{AppHandle, Emitter};

// ── Minimum examples to reliably fine-tune qwen3:7b on CADEN's tasks ────────
//
// Reasoning:
//   - response (1500): CADEN's voice + context use is the hardest task.
//     Needs the most variety to distill tone, boundaries, and persona.
//   - analyze (800): Context synthesis briefs — moderately complex.
//   - classify (500): Simple JSON with 6 intent classes. 500 is generous.
//   - mood_extract / goal_extract (400 each): Narrow JSON schemas,
//     few fields, predictable patterns. 400 gives solid generalization.
//   - data_report (300): Pure number extraction, simplest task of all.
//
// Total: ~3900 examples. At ~5 messages/day this takes ~780 days.
// At higher usage (20 msgs/day) ~195 days. Progress shown in API Keys settings.

pub const THRESHOLD_RESPONSE: i64    = 1500;
pub const THRESHOLD_ANALYZE: i64     = 800;
pub const THRESHOLD_CLASSIFY: i64    = 500;
pub const THRESHOLD_MOOD: i64        = 400;
pub const THRESHOLD_GOAL: i64        = 400;
pub const THRESHOLD_DATA_REPORT: i64 = 300;

#[derive(serde::Serialize, serde::Deserialize, Clone, Debug)]
pub struct TrainingCounts {
    pub response:    i64,
    pub analyze:     i64,
    pub classify:    i64,
    pub mood:        i64,
    pub goal:        i64,
    pub data_report: i64,
    // thresholds sent alongside counts so the frontend can show progress bars
    pub threshold_response:    i64,
    pub threshold_analyze:     i64,
    pub threshold_classify:    i64,
    pub threshold_mood:        i64,
    pub threshold_goal:        i64,
    pub threshold_data_report: i64,
}

impl Default for TrainingCounts {
    fn default() -> Self {
        Self {
            response: 0, analyze: 0, classify: 0,
            mood: 0, goal: 0, data_report: 0,
            threshold_response:    THRESHOLD_RESPONSE,
            threshold_analyze:     THRESHOLD_ANALYZE,
            threshold_classify:    THRESHOLD_CLASSIFY,
            threshold_mood:        THRESHOLD_MOOD,
            threshold_goal:        THRESHOLD_GOAL,
            threshold_data_report: THRESHOLD_DATA_REPORT,
        }
    }
}

/// Save one (prompt → completion) example to the DB.
/// `ex_type`: "response" | "analyze" | "classify" | "mood" | "goal" | "data_report"
/// `system_prompt`:
///   - For "response": pass `Some("<analysis_brief>\n\n<situational_briefing>")` — NO persona.
///   - For all others: pass `None` — the task prompt already encodes the job.
/// Only logs when `completion` is non-empty and comes from a cloud model run
/// (caller is responsible for only calling this with quality output).
pub async fn log_example(
    pool: &SqlitePool,
    ex_type: &str,
    system_prompt: Option<&str>,
    user_prompt: &str,
    completion: &str,
    model: &str,
) -> Result<()> {
    if completion.trim().is_empty() || user_prompt.trim().is_empty() {
        return Ok(());
    }
    sqlx::query(
        "INSERT INTO training_data
         (id, ex_type, system_prompt, user_prompt, completion, model, created_at)
         VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
    )
    .bind(crate::db::ops::generate_id())
    .bind(ex_type)
    .bind(system_prompt)
    .bind(user_prompt)
    .bind(completion)
    .bind(model)
    .execute(pool)
    .await?;
    Ok(())
}

/// Count examples per type from the DB.
pub async fn get_counts(pool: &SqlitePool) -> TrainingCounts {
    let rows: Vec<(String, i64)> = sqlx::query_as(
        "SELECT ex_type, COUNT(*) FROM training_data GROUP BY ex_type",
    )
    .fetch_all(pool)
    .await
    .unwrap_or_default();

    let mut c = TrainingCounts::default();
    for (t, n) in rows {
        match t.as_str() {
            "response"    => c.response    = n,
            "analyze"     => c.analyze     = n,
            "classify"    => c.classify    = n,
            "mood"        => c.mood        = n,
            "goal"        => c.goal        = n,
            "data_report" => c.data_report = n,
            _ => {}
        }
    }
    c
}

pub fn is_ready(c: &TrainingCounts) -> bool {
    c.response    >= THRESHOLD_RESPONSE
        && c.analyze     >= THRESHOLD_ANALYZE
        && c.classify    >= THRESHOLD_CLASSIFY
        && c.mood        >= THRESHOLD_MOOD
        && c.goal        >= THRESHOLD_GOAL
        && c.data_report >= THRESHOLD_DATA_REPORT
}

/// After every log call, check whether all thresholds are newly crossed.
/// If so, emit `caden-training-ready` once and set a DB flag so it doesn't fire again.
pub async fn check_and_notify(pool: &SqlitePool, app: &AppHandle) {
    let counts = get_counts(pool).await;
    if !is_ready(&counts) { return; }

    let already = crate::db::get_setting(pool, "training_ready_notified")
        .await
        .unwrap_or_default()
        .unwrap_or_default();
    if already == "true" { return; }

    let _ = crate::db::set_setting(pool, "training_ready_notified", "true").await;
    let _ = app.emit("caden-training-ready", &counts);
}

/// Export all training data to a JSONL file in ShareGPT / unsloth format.
/// Returns the number of examples written.
pub async fn export_jsonl(pool: &SqlitePool, path: &str) -> Result<usize> {
    use std::io::Write;

    let rows: Vec<(String, Option<String>, String, String)> = sqlx::query_as(
        "SELECT ex_type, system_prompt, user_prompt, completion
         FROM training_data
         ORDER BY created_at ASC",
    )
    .fetch_all(pool)
    .await?;

    let mut file = std::fs::File::create(path)?;
    let mut count = 0;

    for (ex_type, sys, user, completion) in &rows {
        let conversations: Vec<serde_json::Value> = {
            let mut v = Vec::new();
            if let Some(s) = sys {
                if !s.trim().is_empty() {
                    v.push(serde_json::json!({"from": "system", "value": s}));
                }
            }
            v.push(serde_json::json!({"from": "human", "value": user}));
            v.push(serde_json::json!({"from": "gpt",   "value": completion}));
            v
        };
        let record = serde_json::json!({
            "conversations": conversations,
            "type": ex_type,
        });
        writeln!(file, "{}", serde_json::to_string(&record)?)?;
        count += 1;
    }

    Ok(count)
}
