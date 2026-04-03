/// Semantic thought retrieval — finds thought-dump entries most relevant to
/// the current context using cosine similarity over stored embeddings.
///
/// This is the "context lens" of the Sean Model: given what CADEN is currently
/// being asked, surface the thoughts Sean has already expressed that are most
/// relevant to that moment. No LLM needed — pure vector math.
use sqlx::SqlitePool;

// ─── Helpers (mirrors projects/mod.rs) ───────────────────────────────────────

fn bytes_to_vec(b: &[u8]) -> Vec<f32> {
    b.chunks_exact(4)
        .map(|c| f32::from_le_bytes([c[0], c[1], c[2], c[3]]))
        .collect()
}

fn cosine_similarity(a: &[f32], b: &[f32]) -> f32 {
    if a.len() != b.len() || a.is_empty() {
        return 0.0;
    }
    let dot: f32 = a.iter().zip(b).map(|(x, y)| x * y).sum();
    let norm_a: f32 = a.iter().map(|x| x * x).sum::<f32>().sqrt();
    let norm_b: f32 = b.iter().map(|x| x * x).sum::<f32>().sqrt();
    if norm_a == 0.0 || norm_b == 0.0 {
        0.0
    } else {
        dot / (norm_a * norm_b)
    }
}

// ─── Main retrieval ───────────────────────────────────────────────────────────

#[derive(sqlx::FromRow)]
struct ThoughtRow {
    content: String,
    created_at: String,
    embedding: Option<Vec<u8>>,
}

/// Return up to `limit` thought-dump excerpts most semantically similar
/// to `query_embedding`. Only thoughts with stored embeddings are searched.
/// Minimum similarity threshold: 0.30 (low — thoughts are often tangential).
pub async fn get_relevant_thoughts(
    pool: &SqlitePool,
    query_embedding: Vec<f32>,
    limit: usize,
) -> Vec<String> {
    let rows: Vec<ThoughtRow> = sqlx::query_as(
        "SELECT pe.content, pe.created_at, pe.embedding
         FROM project_entries pe
         JOIN projects p ON pe.project_id = p.id
         WHERE p.name = '__thoughts__'
           AND pe.embedding IS NOT NULL
         ORDER BY pe.created_at DESC
         LIMIT 200",
    )
    .fetch_all(pool)
    .await
    .unwrap_or_default();

    if rows.is_empty() {
        return vec![];
    }

    let now = chrono::Utc::now();
    let mut scored: Vec<(f32, String)> = rows
        .into_iter()
        .filter_map(|row| {
            let emb = bytes_to_vec(row.embedding.as_ref()?);
            let sim = cosine_similarity(&query_embedding, &emb);
            if sim < 0.30 {
                return None;
            }

            // Age penalty: thoughts > 30 days old get slightly lower priority
            let age_days = chrono::DateTime::parse_from_rfc3339(&row.created_at)
                .ok()
                .map(|dt| (now - dt.with_timezone(&chrono::Utc)).num_days())
                .unwrap_or(0);

            let age_factor = if age_days > 30 { 0.85 } else { 1.0 };
            let final_score = sim * age_factor;

            let age_label = if age_days == 0 {
                "today".to_string()
            } else if age_days == 1 {
                "yesterday".to_string()
            } else {
                format!("{}d ago", age_days)
            };

            let excerpt = truncate(&row.content, 140);
            Some((final_score, format!("[{}] {}", age_label, excerpt)))
        })
        .collect();

    scored.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(std::cmp::Ordering::Equal));
    scored.into_iter().take(limit).map(|(_, t)| t).collect()
}

/// Fallback: return the `limit` most recent thought-dump entries, truncated.
/// Used when nomic-embed-text is unavailable and no query embedding was produced.
pub async fn get_recent_thought_excerpts(pool: &SqlitePool, limit: usize) -> Vec<String> {
    let rows: Vec<(String, String)> = sqlx::query_as(
        "SELECT pe.content, pe.created_at
         FROM project_entries pe
         JOIN projects p ON pe.project_id = p.id
         WHERE p.name = '__thoughts__'
         ORDER BY pe.created_at DESC
         LIMIT ?",
    )
    .bind(limit as i64)
    .fetch_all(pool)
    .await
    .unwrap_or_default();

    let now = chrono::Utc::now();
    rows.into_iter()
        .map(|(content, created_at)| {
            let age_days = chrono::DateTime::parse_from_rfc3339(&created_at)
                .ok()
                .map(|dt| (now - dt.with_timezone(&chrono::Utc)).num_days())
                .unwrap_or(0);

            let label = if age_days == 0 {
                "today".to_string()
            } else if age_days == 1 {
                "yesterday".to_string()
            } else {
                format!("{}d ago", age_days)
            };

            format!("[{}] {}", label, truncate(&content, 140))
        })
        .collect()
}

// ─── Active concern detection ─────────────────────────────────────────────────
//
// Finds recurring themes in the thought dump by looking for the most
// commonly co-occurring word clusters in recent entries. Pure frequency
// analysis — no LLM needed.

pub async fn get_active_concerns(pool: &SqlitePool, limit: usize) -> Vec<String> {
    // Grab the 50 most recent thoughts
    let rows: Vec<(String,)> = sqlx::query_as(
        "SELECT pe.content
         FROM project_entries pe
         JOIN projects p ON pe.project_id = p.id
         WHERE p.name = '__thoughts__'
           AND pe.created_at > datetime('now', '-21 days')
         ORDER BY pe.created_at DESC
         LIMIT 50",
    )
    .fetch_all(pool)
    .await
    .unwrap_or_default();

    if rows.is_empty() {
        return vec![];
    }

    // Count word frequencies (lowercased, ignore stop words, min 4 chars)
    let stop_words = stop_word_set();
    let mut freq: std::collections::HashMap<String, usize> = std::collections::HashMap::new();

    for (content,) in &rows {
        let words: Vec<String> = content
            .split(|c: char| !c.is_alphabetic())
            .filter(|w| w.len() >= 4)
            .map(|w| w.to_lowercase())
            .filter(|w| !stop_words.contains(w.as_str()))
            .collect();

        for word in words {
            *freq.entry(word).or_insert(0) += 1;
        }
    }

    // Return top words that appear in ≥2 entries as "active concern" tokens
    let mut top: Vec<(usize, String)> = freq
        .into_iter()
        .filter(|(_, count)| *count >= 2)
        .map(|(word, count)| (count, word))
        .collect();

    top.sort_by(|a, b| b.0.cmp(&a.0));
    top.into_iter().take(limit).map(|(_, w)| w).collect()
}

// ─── Chat log retrieval ───────────────────────────────────────────────────────

#[derive(sqlx::FromRow)]
struct ChatRow {
    content: String,
    timestamp: String,
    embedding: Option<Vec<u8>>,
}

/// Return up to `limit` past chat messages most semantically similar to
/// `query_embedding`. Skips the most recent message (that's the current one).
/// Minimum similarity: 0.35 (higher than thought threshold — chat is denser).
pub async fn get_relevant_from_chat(
    pool: &SqlitePool,
    query_embedding: Vec<f32>,
    limit: usize,
) -> Vec<String> {
    let rows: Vec<ChatRow> = sqlx::query_as(
        "SELECT content, timestamp, embedding
         FROM chat_log
         WHERE embedding IS NOT NULL
         ORDER BY timestamp DESC
         LIMIT 300 OFFSET 1",
    )
    .fetch_all(pool)
    .await
    .unwrap_or_default();

    if rows.is_empty() {
        return vec![];
    }

    let now = chrono::Utc::now();
    let mut scored: Vec<(f32, String)> = rows
        .into_iter()
        .filter_map(|row| {
            let emb = bytes_to_vec(row.embedding.as_ref()?);
            let sim = cosine_similarity(&query_embedding, &emb);
            if sim < 0.25 {
                return None;
            }

            let age_days = chrono::DateTime::parse_from_rfc3339(&row.timestamp)
                .ok()
                .map(|dt| (now - dt.with_timezone(&chrono::Utc)).num_days())
                .unwrap_or(0);

            // Recent messages weighted slightly higher
            let recency_boost = if age_days < 3 { 1.05 } else { 1.0 };
            let final_score = sim * recency_boost;

            let label = if age_days == 0 {
                "today".to_string()
            } else if age_days == 1 {
                "yesterday".to_string()
            } else {
                format!("{}d ago", age_days)
            };

            Some((final_score, format!("[chat {}] {}", label, truncate(&row.content, 120))))
        })
        .collect();

    scored.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(std::cmp::Ordering::Equal));
    scored.into_iter().take(limit).map(|(_, t)| t).collect()
}

fn truncate(s: &str, max_chars: usize) -> String {
    let s = s.trim();
    if s.chars().count() <= max_chars {
        s.to_string()
    } else {
        let cut: String = s.chars().take(max_chars).collect();
        format!("{}…", cut.trim_end())
    }
}

fn stop_word_set() -> std::collections::HashSet<&'static str> {
    [
        "this", "that", "with", "have", "just", "from", "they", "will",
        "been", "when", "what", "about", "some", "more", "also", "like",
        "then", "than", "there", "their", "very", "your", "know", "want",
        "need", "think", "feel", "going", "really", "still", "dont",
        "cant", "isnt", "wasnt", "should", "would", "could", "maybe",
        "even", "much", "make", "take", "back", "time", "into", "over",
        "after", "before", "being", "does", "doing", "always", "never",
        "every", "because", "though", "through",
    ]
    .iter()
    .copied()
    .collect()
}
