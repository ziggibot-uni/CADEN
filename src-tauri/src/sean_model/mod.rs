/// The Sean Model — a non-LLM behavioral model that learns who Sean is
/// and surfaces exactly the right context for CADEN's LLM at any given moment.
///
/// Instead of sending the LLM a long system prompt and hoping it infers Sean's
/// current state, this module computes that state directly from data and
/// delivers a tight, factual briefing. The LLM punches way above its weight
/// class because it never has to guess.
///
/// Components:
///   - `circadian`  — 24×7 energy grid trained on task completions
///   - `profile`    — behavioral patterns: avoidances, preferences, momentum, flow
///   - `retrieval`  — cosine similarity search over thought dump + chat history
pub mod circadian;
pub mod profile;
pub mod retrieval;

use chrono::{Datelike, Local, Timelike, Weekday};
use sqlx::SqlitePool;

/// Persist a user chat message to the chat log.
/// Called on every outbound message so the Sean Model can learn from conversations.
/// Soft-fail — never blocks or panics.
pub async fn log_chat_message(pool: &SqlitePool, content: &str, embedding: Option<Vec<f32>>) {
    let id = crate::db::ops::generate_id();
    let ts = chrono::Utc::now().to_rfc3339();

    let embedding_bytes: Option<Vec<u8>> = embedding.map(|v| {
        v.iter().flat_map(|f| f.to_le_bytes()).collect()
    });

    let _ = sqlx::query(
        "INSERT INTO chat_log (id, content, embedding, timestamp) VALUES (?, ?, ?, ?)",
    )
    .bind(&id)
    .bind(content)
    .bind(&embedding_bytes)
    .bind(&ts)
    .execute(pool)
    .await;
}

/// Backfill embeddings for any chat_log rows (and thought dump entries) that
/// were saved before nomic-embed-text was installed. Runs once at startup in
/// a background task — soft-fail on every row.
pub async fn backfill_embeddings(pool: &SqlitePool) {
    // 1. Chat log rows without embeddings
    let chat_rows: Vec<(String, String)> = sqlx::query_as(
        "SELECT id, content FROM chat_log WHERE embedding IS NULL ORDER BY timestamp DESC LIMIT 500",
    )
    .fetch_all(pool)
    .await
    .unwrap_or_default();

    for (id, content) in &chat_rows {
        if let Ok(emb) = crate::ollama::embed(content).await {
            let bytes: Vec<u8> = emb.iter().flat_map(|f| f.to_le_bytes()).collect();
            let _ = sqlx::query("UPDATE chat_log SET embedding = ? WHERE id = ?")
                .bind(&bytes)
                .bind(id)
                .execute(pool)
                .await;
        }
    }

    // 2. Thought dump entries without embeddings
    let thought_rows: Vec<(String, String)> = sqlx::query_as(
        "SELECT pe.id, pe.content
         FROM project_entries pe
         JOIN projects p ON p.id = pe.project_id
         WHERE p.name = '__thoughts__' AND pe.embedding IS NULL
         ORDER BY pe.created_at DESC LIMIT 500",
    )
    .fetch_all(pool)
    .await
    .unwrap_or_default();

    for (id, content) in &thought_rows {
        if let Ok(emb) = crate::ollama::embed(content).await {
            let bytes: Vec<u8> = emb.iter().flat_map(|f| f.to_le_bytes()).collect();
            let _ = sqlx::query("UPDATE project_entries SET embedding = ? WHERE id = ?")
                .bind(&bytes)
                .bind(id)
                .execute(pool)
                .await;
        }
    }

    log::info!(
        "Embedding backfill complete: {} chat messages, {} thought entries",
        chat_rows.len(),
        thought_rows.len()
    );
}

/// Build the full Sean Model briefing to inject into CADEN's context.
///
/// `query_embedding` is the embedding of the current user message.
/// When provided, the thought retrieval is semantic (most relevant).
/// When `None`, falls back to most recent thoughts.
///
/// This function never panics and always returns a useful string, even
/// if the database is empty or embeddings are unavailable.
pub async fn build_sean_briefing(
    pool: &SqlitePool,
    query_embedding: Option<Vec<f32>>,
) -> String {
    let now = Local::now();
    let hour = now.hour();
    let dow = circadian::weekday_to_index(now.weekday());
    let day_name = weekday_name(now.weekday());

    let mut lines: Vec<String> = vec!["=== SEAN MODEL ===".to_string()];

    // ── Circadian energy ──────────────────────────────────────────────────────
    let energy = circadian::get_energy_level(pool, hour, dow).await;
    let peak_hours = circadian::get_peak_hours_today(pool, dow).await;

    let energy_label = if energy >= 0.65 {
        "HIGH"
    } else if energy >= 0.42 {
        "MEDIUM"
    } else {
        "LOW"
    };

    let hour_ampm = {
        let h12 = match hour % 12 { 0 => 12, x => x };
        let sfx = if hour < 12 { "AM" } else { "PM" };
        format!("{}:00 {}", h12, sfx)
    };
    lines.push(format!(
        "Energy level: {} (historical productivity {:.0}% for {} on {})",
        energy_label,
        energy * 100.0,
        hour_ampm,
        day_name
    ));

    if !peak_hours.is_empty() {
        let peak_str: Vec<String> = peak_hours.iter().map(|h| {
            let h12 = match h % 12 { 0 => 12, x => x };
            let sfx = if *h < 12 { "AM" } else { "PM" };
            format!("{}:00 {}", h12, sfx)
        }).collect();
        lines.push(format!(
            "Historically productive today: {}",
            peak_str.join(", ")
        ));
    }

    // ── Behavioral profile ────────────────────────────────────────────────────
    let prof = profile::compute_profile(pool).await;

    if !prof.task_preference_note.is_empty() {
        lines.push(prof.task_preference_note.clone());
    }

    if !prof.chronic_avoidances.is_empty() {
        lines.push(format!(
            "Chronic avoidances (3+ skips, zero completions): {}",
            prof.chronic_avoidances.join("; ")
        ));
    }

    if !prof.momentum_note.is_empty() {
        lines.push(prof.momentum_note.clone());
    }

    if !prof.flow_windows.is_empty() {
        lines.push(format!(
            "Historical flow windows: {}",
            prof.flow_windows.join(", ")
        ));
    }

    // ── Spike signals ─────────────────────────────────────────────────────────
    if !prof.spikes.is_empty() {
        lines.push(String::new());
        lines.push("Pattern signals:".to_string());
        for spike in &prof.spikes {
            lines.push(format!("  {}", spike));
        }
    }

    // ── Relevant context: thought dump + chat history + project entries ──────────
    // With an embedding: semantic search over all three sources, merged.
    // Without: recency fallback for thoughts only.
    let (thoughts, past_chat, project_hits) = match query_embedding {
        Some(ref emb) => {
            let t = retrieval::get_relevant_thoughts(pool, emb.clone(), 3).await;
            let c = retrieval::get_relevant_from_chat(pool, emb.clone(), 5).await;
            let p = crate::projects::get_relevant_project_entries(pool, emb.clone(), 3).await;
            (t, c, p)
        }
        None => (retrieval::get_recent_thought_excerpts(pool, 3).await, vec![], vec![]),
    };

    if !thoughts.is_empty() || !past_chat.is_empty() || !project_hits.is_empty() {
        lines.push(String::new());
        lines.push("Relevant context from Sean's memory:".to_string());
        for t in &thoughts {
            lines.push(format!("  • [thought] {}", t));
        }
        for c in &past_chat {
            lines.push(format!("  • {}", c));
        }
        for (proj, etype, excerpt) in &project_hits {
            lines.push(format!("  • [project:{}/{}] {}", proj, etype, excerpt));
        }
    }

    // ── Active concern tokens ─────────────────────────────────────────────────
    let concerns = retrieval::get_active_concerns(pool, 5).await;
    if !concerns.is_empty() {
        lines.push(format!(
            "Recurring themes: {}",
            concerns.join(", ")
        ));
    }

    // ── Explicit user corrections ─────────────────────────────────────────────
    // These are the highest-priority signals: when Sean tells CADEN something
    // directly, that overrides any inference from behavioral data.
    let corrections = crate::db::ops::get_recent_corrections(pool, 8).await.unwrap_or_default();
    if !corrections.is_empty() {
        lines.push(String::new());
        lines.push("Sean's explicit corrections and preferences (highest priority — follow these):".to_string());
        for (ctype, desc, _data) in &corrections {
            lines.push(format!("  [{ctype}] {desc}"));
        }
    }

    // ── Behavioral state engine ───────────────────────────────────────────────
    // Rolling mood/energy/anxiety averages + episode risk from silent NLP extraction.
    let state_briefing = crate::state_engine::build_state_briefing(pool).await;
    lines.push(String::new());
    lines.push(state_briefing);

    lines.push("=== END SEAN MODEL ===".to_string());
    lines.join("\n")
}

fn weekday_name(w: Weekday) -> &'static str {
    match w {
        Weekday::Mon => "Mon",
        Weekday::Tue => "Tue",
        Weekday::Wed => "Wed",
        Weekday::Thu => "Thu",
        Weekday::Fri => "Fri",
        Weekday::Sat => "Sat",
        Weekday::Sun => "Sun",
    }
}
