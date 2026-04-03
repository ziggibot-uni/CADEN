/// search/mod.rs — Web search via local SearXNG + project file reading for CADEN.
///
/// Two capability groups:
///
/// 1. Web search — query local SearXNG, fetch page content, embed and store in
///    SQLite so every result is citable and semantically recallable later.
///
/// 2. Project file tools — list and read files inside a project's linked folder
///    so CADEN can act as a Jarvis-style code/doc reader.

use anyhow::{anyhow, Result};
use reqwest::Client;
use serde::{Deserialize, Serialize};

const SEARXNG_BASE: &str = "http://localhost:8888";
/// Max results to pull from SearXNG per query.
const MAX_RESULTS: usize = 5;
/// Max chars of page content to store and feed to CADEN.
const MAX_CONTENT_CHARS: usize = 4000;
/// Max chars of a single file to return to CADEN.
const MAX_FILE_CHARS: usize = 8000;

// ── SearXNG API types ─────────────────────────────────────────────────────────

#[derive(Debug, Deserialize)]
struct SearxResult {
    url: String,
    title: String,
    #[serde(default)]
    content: String,
}

#[derive(Debug, Deserialize)]
struct SearxResponse {
    #[serde(default)]
    results: Vec<SearxResult>,
}

// ── Public result type returned to callers ────────────────────────────────────

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct WebCitation {
    pub id: String,
    pub query: String,
    pub url: String,
    pub title: String,
    pub snippet: String,
    pub searched_at: String,
}

// ── Core web search pipeline ──────────────────────────────────────────────────

/// Query SearXNG and return raw results. Returns an error string if SearXNG is
/// unreachable so CADEN can tell Sean to start the container.
async fn query_searxng(query: &str) -> Result<Vec<SearxResult>> {
    let client = Client::builder()
        .timeout(std::time::Duration::from_secs(10))
        .build()?;

    let resp = client
        .get(format!("{}/search", SEARXNG_BASE))
        .query(&[("q", query), ("format", "json")])
        .send()
        .await
        .map_err(|e| anyhow!("SearXNG unreachable ({}). Start it with: cd CADEN/searxng && docker compose up -d", e))?;

    if !resp.status().is_success() {
        return Err(anyhow!("SearXNG returned HTTP {}", resp.status()));
    }

    let body: SearxResponse = resp
        .json()
        .await
        .map_err(|e| anyhow!("SearXNG parse error: {}", e))?;

    Ok(body.results.into_iter().take(MAX_RESULTS).collect())
}

/// Fetch a URL and return readable text. Best-effort — returns empty on failure.
async fn fetch_page_text(url: &str) -> String {
    let client = match Client::builder()
        .timeout(std::time::Duration::from_secs(10))
        .user_agent("Mozilla/5.0 (compatible; CADEN/1.0; +https://github.com/your/caden)")
        .build()
    {
        Ok(c) => c,
        Err(_) => return String::new(),
    };

    let resp = match client.get(url).send().await {
        Ok(r) if r.status().is_success() => r,
        _ => return String::new(),
    };

    let html = match resp.text().await {
        Ok(t) => t,
        Err(_) => return String::new(),
    };

    let text = strip_html_tags(&html);
    text.chars().take(MAX_CONTENT_CHARS).collect()
}

/// Very simple HTML → plain text. Strips tags, collapses whitespace.
fn strip_html_tags(html: &str) -> String {
    let mut result = String::new();
    let mut in_tag = false;
    let mut in_invisible = false; // inside <script> or <style>
    let mut tag_buf = String::new();

    for ch in html.chars() {
        if !in_tag {
            if ch == '<' {
                in_tag = true;
                tag_buf.clear();
                tag_buf.push(ch);
            } else if !in_invisible {
                if ch == '\n' || ch == '\r' {
                    if !result.ends_with('\n') {
                        result.push('\n');
                    }
                } else {
                    result.push(ch);
                }
            }
        } else {
            tag_buf.push(ch);
            if ch == '>' {
                let lower = tag_buf.to_lowercase();
                if lower.starts_with("<script") || lower.starts_with("<style") {
                    in_invisible = true;
                } else if lower.starts_with("</script") || lower.starts_with("</style") {
                    in_invisible = false;
                } else if !in_invisible {
                    // Block-level tags → newline
                    if lower.starts_with("<p")
                        || lower.starts_with("<div")
                        || lower.starts_with("<br")
                        || lower.starts_with("<h")
                        || lower.starts_with("<li")
                        || lower.starts_with("<tr")
                        || lower.starts_with("<section")
                        || lower.starts_with("<article")
                    {
                        if !result.ends_with('\n') {
                            result.push('\n');
                        }
                    }
                }
                in_tag = false;
                tag_buf.clear();
            }
        }
    }

    // Collapse multiple blank lines
    let mut cleaned = String::new();
    let mut newlines = 0usize;
    let mut last_space = false;
    for ch in result.chars() {
        match ch {
            '\n' => {
                newlines += 1;
                last_space = false;
                if newlines <= 2 {
                    cleaned.push('\n');
                }
            }
            ' ' | '\t' => {
                if !last_space && newlines == 0 {
                    cleaned.push(' ');
                    last_space = true;
                }
            }
            _ => {
                newlines = 0;
                last_space = false;
                cleaned.push(ch);
            }
        }
    }

    cleaned.trim().to_string()
}

/// Store one search result in the DB with an embedding.
async fn store_result(
    pool: &sqlx::SqlitePool,
    query: &str,
    url: &str,
    title: &str,
    snippet: &str,
    content: &str,
) -> Result<String> {
    let id = crate::db::ops::generate_id();
    let now = chrono::Utc::now().to_rfc3339();

    // Embed: title + snippet + first 500 chars of content
    let embed_input = format!(
        "{} {} {}",
        title,
        snippet,
        content.chars().take(500).collect::<String>()
    );
    let embedding_bytes: Option<Vec<u8>> = crate::ollama::embed(&embed_input)
        .await
        .ok()
        .map(|v| v.iter().flat_map(|f| f.to_le_bytes()).collect());

    sqlx::query(
        "INSERT INTO web_search_cache (id, query, url, title, snippet, content, embedding, searched_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(&id)
    .bind(query)
    .bind(url)
    .bind(title)
    .bind(snippet)
    .bind(content)
    .bind(&embedding_bytes)
    .bind(&now)
    .execute(pool)
    .await
    .map_err(|e| anyhow!("DB insert failed: {}", e))?;

    Ok(id)
}

/// Full pipeline: query SearXNG → fetch pages → embed → store → return formatted
/// string that CADEN feeds into the conversation.
pub async fn search_and_store(pool: &sqlx::SqlitePool, query: &str) -> String {
    let results = match query_searxng(query).await {
        Ok(r) if !r.is_empty() => r,
        Ok(_) => return format!("No web results found for: \"{}\"", query),
        Err(e) => return e.to_string(),
    };

    let mut formatted = format!("Web search results for \"{}\":\n\n", query);

    for (i, result) in results.iter().enumerate() {
        let content = fetch_page_text(&result.url).await;
        let _ = store_result(pool, query, &result.url, &result.title, &result.content, &content).await;

        formatted.push_str(&format!(
            "[{}] {}\n    URL: {}\n",
            i + 1,
            result.title,
            result.url
        ));

        if !result.content.is_empty() {
            formatted.push_str(&format!("    Summary: {}\n", result.content));
        }

        if !content.is_empty() {
            let excerpt: String = content.chars().take(350).collect();
            formatted.push_str(&format!("    Excerpt: {}…\n", excerpt.trim_end()));
        }

        formatted.push('\n');
    }

    formatted.push_str("These results are saved — use recall_web to find them again semantically.");
    formatted
}

/// Semantic recall: embed the query and rank cached results by cosine similarity.
pub async fn recall_similar(pool: &sqlx::SqlitePool, query: &str) -> String {
    let query_vec = match crate::ollama::embed(query).await {
        Ok(v) => v,
        Err(_) => return "Embedding unavailable — cannot search web cache.".to_string(),
    };

    let rows = sqlx::query(
        "SELECT url, title, snippet, query, embedding
         FROM web_search_cache
         WHERE embedding IS NOT NULL
         ORDER BY searched_at DESC
         LIMIT 200",
    )
    .fetch_all(pool)
    .await;

    let rows = match rows {
        Ok(r) if !r.is_empty() => r,
        _ => return "No cached web results found — try a fresh search.".to_string(),
    };

    use sqlx::Row as _;
    let mut scored: Vec<(f32, String, String, String, String)> = rows
        .iter()
        .filter_map(|row| {
            let bytes: Option<Vec<u8>> = row.try_get("embedding").ok().flatten();
            let bytes = bytes?;
            let vec: Vec<f32> = bytes
                .chunks_exact(4)
                .map(|b| f32::from_le_bytes([b[0], b[1], b[2], b[3]]))
                .collect();
            let sim = cosine_similarity(&query_vec, &vec);
            let url: String = row.try_get("url").unwrap_or_default();
            let title: String = row.try_get("title").unwrap_or_default();
            let snippet: String = row.try_get::<Option<String>, _>("snippet").unwrap_or_default().unwrap_or_default();
            let orig_query: String = row.try_get("query").unwrap_or_default();
            Some((sim, url, title, snippet, orig_query))
        })
        .collect();

    scored.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(std::cmp::Ordering::Equal));

    let top: Vec<_> = scored.into_iter().take(3).collect();

    if top.is_empty() || top[0].0 < 0.25 {
        return "No relevant cached results found. Try a fresh search.".to_string();
    }

    let mut out = format!("Cached web results relevant to \"{}\":\n\n", query);
    for (i, (sim, url, title, snippet, orig_query)) in top.iter().enumerate() {
        out.push_str(&format!(
            "[{}] {} ({:.0}% match)\n    URL: {}\n    Original search: \"{}\"\n    {}\n\n",
            i + 1,
            title,
            sim * 100.0,
            url,
            orig_query,
            snippet
        ));
    }
    out
}

/// Return recent citations (for the UI).
pub async fn get_recent_citations(
    pool: &sqlx::SqlitePool,
    limit: i64,
) -> Result<Vec<WebCitation>> {
    use sqlx::Row as _;

    let rows = sqlx::query(
        "SELECT id, query, url, title, snippet, searched_at
         FROM web_search_cache
         ORDER BY searched_at DESC
         LIMIT ?",
    )
    .bind(limit)
    .fetch_all(pool)
    .await?;

    Ok(rows
        .iter()
        .map(|r| WebCitation {
            id: r.try_get("id").unwrap_or_default(),
            query: r.try_get("query").unwrap_or_default(),
            url: r.try_get("url").unwrap_or_default(),
            title: r.try_get("title").unwrap_or_default(),
            snippet: r.try_get::<Option<String>, _>("snippet").unwrap_or_default().unwrap_or_default(),
            searched_at: r.try_get("searched_at").unwrap_or_default(),
        })
        .collect())
}

pub fn cosine_similarity(a: &[f32], b: &[f32]) -> f32 {
    if a.len() != b.len() || a.is_empty() {
        return 0.0;
    }
    let dot: f32 = a.iter().zip(b.iter()).map(|(x, y)| x * y).sum();
    let norm_a: f32 = a.iter().map(|x| x * x).sum::<f32>().sqrt();
    let norm_b: f32 = b.iter().map(|x| x * x).sum::<f32>().sqrt();
    if norm_a == 0.0 || norm_b == 0.0 {
        0.0
    } else {
        dot / (norm_a * norm_b)
    }
}

// ── Project file tools ────────────────────────────────────────────────────────

/// List active projects with their folder paths — so CADEN knows what to read.
pub async fn list_projects_with_folders(pool: &sqlx::SqlitePool) -> String {
    use sqlx::Row as _;

    let rows = sqlx::query(
        "SELECT id, name, folder_path FROM projects WHERE status = 'active' ORDER BY name",
    )
    .fetch_all(pool)
    .await;

    match rows {
        Ok(r) if !r.is_empty() => {
            let mut out = "Your active projects:\n".to_string();
            for row in &r {
                let id: String = row.try_get("id").unwrap_or_default();
                let name: String = row.try_get("name").unwrap_or_default();
                let folder: String = row
                    .try_get::<Option<String>, _>("folder_path")
                    .unwrap_or_default()
                    .unwrap_or_else(|| "(no folder linked)".to_string());
                out.push_str(&format!("  ID: {} | {} — {}\n", id, name, folder));
            }
            out.push_str(
                "\nUse list_project_files with the project name or ID to see files, \
                 then read_project_file to read one.",
            );
            out
        }
        _ => "No active projects found.".to_string(),
    }
}

/// List text/code files inside a project's folder (up to 2 directory levels).
pub async fn list_project_files(pool: &sqlx::SqlitePool, project_id_or_name: &str) -> String {
    let folder = match resolve_project_folder(pool, project_id_or_name).await {
        Some(f) => f,
        None => {
            return format!(
                "Project '{}' not found or has no linked folder. \
                 Link a folder in the Projects panel first.",
                project_id_or_name
            )
        }
    };

    match collect_text_files(std::path::Path::new(&folder), 0, 2) {
        Ok(files) if !files.is_empty() => {
            let mut out = format!("Files in project '{}' ({}):\n", project_id_or_name, folder);
            for f in &files {
                out.push_str(&format!("  {}\n", f));
            }
            out
        }
        Ok(_) => format!("Project folder is empty or has no readable files: {}", folder),
        Err(e) => format!("Failed to list project folder: {}", e),
    }
}

/// Read a file inside a project's folder. Path is relative to the project root.
pub async fn read_project_file(
    pool: &sqlx::SqlitePool,
    project_id_or_name: &str,
    relative_path: &str,
) -> String {
    let folder = match resolve_project_folder(pool, project_id_or_name).await {
        Some(f) => f,
        None => {
            return format!(
                "Project '{}' not found or has no linked folder.",
                project_id_or_name
            )
        }
    };

    let base = std::path::PathBuf::from(&folder);
    // Build path from slash-separated components — safe on both Windows and Unix
    let rel: std::path::PathBuf = relative_path.split('/').collect();
    let full = base.join(rel);

    let canonical_base = match base.canonicalize() {
        Ok(p) => p,
        Err(e) => return format!("Cannot resolve project folder: {}", e),
    };
    let canonical_file = match full.canonicalize() {
        Ok(p) => p,
        Err(e) => return format!("File not found: {} ({})", relative_path, e),
    };

    // Security: ensure file is inside project folder
    if !canonical_file.starts_with(&canonical_base) {
        return "Access denied: path escapes project folder.".to_string();
    }

    match std::fs::read_to_string(&canonical_file) {
        Ok(content) => {
            if content.chars().count() > MAX_FILE_CHARS {
                let truncated: String = content.chars().take(MAX_FILE_CHARS).collect();
                format!(
                    "{}\n\n[... truncated at {} chars — full file is {} chars ...]",
                    truncated,
                    MAX_FILE_CHARS,
                    content.len()
                )
            } else {
                content
            }
        }
        Err(e) => format!("Failed to read '{}': {}", relative_path, e),
    }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/// Resolve a project folder by exact ID first, then name substring match.
async fn resolve_project_folder(
    pool: &sqlx::SqlitePool,
    id_or_name: &str,
) -> Option<String> {
    // Try exact ID
    let by_id = sqlx::query_scalar::<_, Option<String>>(
        "SELECT folder_path FROM projects
         WHERE id = ? AND folder_path IS NOT NULL AND folder_path != ''",
    )
    .bind(id_or_name)
    .fetch_optional(pool)
    .await
    .ok()
    .flatten()
    .flatten();

    if by_id.is_some() {
        return by_id;
    }

    // Try name (case-insensitive substring)
    sqlx::query_scalar::<_, Option<String>>(
        "SELECT folder_path FROM projects
         WHERE lower(name) LIKE lower(?) AND folder_path IS NOT NULL AND folder_path != ''
         LIMIT 1",
    )
    .bind(format!("%{}%", id_or_name))
    .fetch_optional(pool)
    .await
    .ok()
    .flatten()
    .flatten()
}

// ── Project entry reading (all entries Sean has ever made) ─────────────────

/// Resolve a project ID from a name or ID string.
async fn resolve_project_id(pool: &sqlx::SqlitePool, id_or_name: &str) -> Option<String> {
    use sqlx::Row as _;

    // Try exact ID
    let by_id = sqlx::query("SELECT id FROM projects WHERE id = ?")
        .bind(id_or_name)
        .fetch_optional(pool)
        .await
        .ok()
        .flatten();
    if let Some(row) = by_id {
        return row.try_get("id").ok();
    }

    // Try name match
    let by_name = sqlx::query(
        "SELECT id FROM projects WHERE lower(name) LIKE lower(?) LIMIT 1",
    )
    .bind(format!("%{}%", id_or_name))
    .fetch_optional(pool)
    .await
    .ok()
    .flatten();
    if let Some(row) = by_name {
        return row.try_get("id").ok();
    }

    None
}

/// Get all entries (todos, updates, decisions, ideas, blockers, references) for a project.
/// This is how CADEN reads Sean's project history — every thought and decision.
pub async fn get_project_entries(pool: &sqlx::SqlitePool, project_id_or_name: &str) -> String {
    use sqlx::Row as _;

    let project_id = match resolve_project_id(pool, project_id_or_name).await {
        Some(id) => id,
        None => return format!("Project '{}' not found.", project_id_or_name),
    };

    // Fetch all entries; no LIMIT so open todos are never cut off
    let rows = sqlx::query(
        "SELECT entry_type, content, completed, created_at
         FROM project_entries
         WHERE project_id = ?
         ORDER BY created_at DESC",
    )
    .bind(&project_id)
    .fetch_all(pool)
    .await;

    let rows = match rows {
        Ok(r) if !r.is_empty() => r,
        _ => return format!("No entries found for project '{}'.", project_id_or_name),
    };

    // Bucket entries by type and completion
    let mut open_todos: Vec<String> = Vec::new();
    let mut done_todos: Vec<(String, String)> = Vec::new(); // (content, date)
    let mut updates: Vec<String> = Vec::new();
    let mut decisions: Vec<String> = Vec::new();
    let mut ideas: Vec<String> = Vec::new();
    let mut blockers: Vec<String> = Vec::new();
    let mut references: Vec<String> = Vec::new();

    for row in &rows {
        let entry_type: String = row.try_get("entry_type").unwrap_or_default();
        let content: String = row.try_get("content").unwrap_or_default();
        let completed: bool = row.try_get::<i32, _>("completed").unwrap_or(0) == 1;
        let created_at: String = row.try_get("created_at").unwrap_or_default();
        // Format date as YYYY-MM-DD for readability
        let date = created_at.get(..10).unwrap_or(&created_at).to_string();

        match entry_type.as_str() {
            "todo" => {
                if completed {
                    done_todos.push((content, date));
                } else {
                    open_todos.push(content);
                }
            }
            "update"    => updates.push(content),
            "decision"  => decisions.push(content),
            "idea"      => ideas.push(content),
            "blocker"   => blockers.push(content),
            "reference" => references.push(content),
            _           => {}
        }
    }

    let mut out = format!("## Project: {}\n\n", project_id_or_name);

    // Open todos always appear first and are clearly labelled
    if !open_todos.is_empty() {
        out.push_str(&format!("### Open TODOs ({} remaining)\n", open_todos.len()));
        for t in &open_todos {
            out.push_str(&format!("- [ ] {}\n", t));
        }
        out.push('\n');
    } else {
        out.push_str("### Open TODOs\nNone — all caught up!\n\n");
    }

    // Completed todos are a work log — show all of them with the date they were recorded
    if !done_todos.is_empty() {
        out.push_str(&format!(
            "### Work completed ({} tasks done)\n",
            done_todos.len()
        ));
        for (t, date) in &done_todos {
            out.push_str(&format!("- [x] {} ({})\n", t, date));
        }
        out.push('\n');
    }

    let sections = [
        ("Recent updates",   &updates,    10usize),
        ("Decisions made",   &decisions,   8),
        ("Ideas to explore", &ideas,       8),
        ("Current blockers", &blockers,    8),
        ("References",       &references,  8),
    ];
    for (label, items, limit) in &sections {
        if !items.is_empty() {
            out.push_str(&format!("### {}\n", label));
            for item in items.iter().take(*limit) {
                out.push_str(&format!("- {}\n", item));
            }
            if items.len() > *limit {
                out.push_str(&format!("  … and {} more\n", items.len() - limit));
            }
            out.push('\n');
        }
    }

    out
}

// ── Unified memory search (thoughts + chats + project entries) ────────────

/// Search across ALL of Sean's recorded thoughts, chat messages, and project entries
/// using semantic similarity. This is CADEN's memory — everything Sean has ever
/// said, dumped, or written in any project.
pub async fn search_memory(pool: &sqlx::SqlitePool, query: &str) -> String {
    let query_vec = match crate::ollama::embed(query).await {
        Ok(v) => v,
        Err(_) => return "Embedding unavailable — can't search memory.".to_string(),
    };

    use sqlx::Row as _;
    let mut scored: Vec<(f32, String, String, String)> = Vec::new(); // (sim, source, content, date)

    // 1. Thought dump entries (project_entries for __thoughts__ project)
    let thoughts = sqlx::query(
        "SELECT pe.content, pe.created_at, pe.embedding
         FROM project_entries pe
         JOIN projects p ON p.id = pe.project_id
         WHERE p.name = '__thoughts__' AND pe.embedding IS NOT NULL
         ORDER BY pe.created_at DESC
         LIMIT 200",
    )
    .fetch_all(pool)
    .await
    .unwrap_or_default();

    for row in &thoughts {
        if let (Ok(content), Ok(date), Ok(Some(emb))) = (
            row.try_get::<String, _>("content"),
            row.try_get::<String, _>("created_at"),
            row.try_get::<Option<Vec<u8>>, _>("embedding"),
        ) {
            let vec: Vec<f32> = emb
                .chunks_exact(4)
                .map(|b| f32::from_le_bytes([b[0], b[1], b[2], b[3]]))
                .collect();
            let sim = cosine_similarity(&query_vec, &vec);
            if sim > 0.25 {
                let excerpt: String = content.chars().take(200).collect();
                scored.push((sim, "thought".to_string(), excerpt, date));
            }
        }
    }

    // 2. Chat messages
    let chats = sqlx::query(
        "SELECT content, timestamp, embedding
         FROM chat_log
         WHERE embedding IS NOT NULL
         ORDER BY timestamp DESC
         LIMIT 300",
    )
    .fetch_all(pool)
    .await
    .unwrap_or_default();

    for row in &chats {
        if let (Ok(content), Ok(date), Ok(Some(emb))) = (
            row.try_get::<String, _>("content"),
            row.try_get::<String, _>("timestamp"),
            row.try_get::<Option<Vec<u8>>, _>("embedding"),
        ) {
            let vec: Vec<f32> = emb
                .chunks_exact(4)
                .map(|b| f32::from_le_bytes([b[0], b[1], b[2], b[3]]))
                .collect();
            let sim = cosine_similarity(&query_vec, &vec);
            if sim > 0.25 {
                let excerpt: String = content.chars().take(200).collect();
                scored.push((sim, "chat".to_string(), excerpt, date));
            }
        }
    }

    // 3. Project entries (all projects, not just __thoughts__)
    let entries = sqlx::query(
        "SELECT pe.content, pe.entry_type, pe.created_at, pe.embedding, p.name as project_name
         FROM project_entries pe
         JOIN projects p ON p.id = pe.project_id
         WHERE p.name != '__thoughts__' AND pe.embedding IS NOT NULL
         ORDER BY pe.created_at DESC
         LIMIT 200",
    )
    .fetch_all(pool)
    .await
    .unwrap_or_default();

    for row in &entries {
        if let (Ok(content), Ok(entry_type), Ok(date), Ok(Some(emb)), Ok(proj)) = (
            row.try_get::<String, _>("content"),
            row.try_get::<String, _>("entry_type"),
            row.try_get::<String, _>("created_at"),
            row.try_get::<Option<Vec<u8>>, _>("embedding"),
            row.try_get::<String, _>("project_name"),
        ) {
            let vec: Vec<f32> = emb
                .chunks_exact(4)
                .map(|b| f32::from_le_bytes([b[0], b[1], b[2], b[3]]))
                .collect();
            let sim = cosine_similarity(&query_vec, &vec);
            if sim > 0.25 {
                let excerpt: String = content.chars().take(200).collect();
                let source = format!("{}/{}", proj, entry_type);
                scored.push((sim, source, excerpt, date));
            }
        }
    }

    // Sort by similarity descending
    scored.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(std::cmp::Ordering::Equal));

    let top: Vec<_> = scored.into_iter().take(8).collect();

    if top.is_empty() {
        return format!("No memories found related to \"{}\".", query);
    }

    let mut out = format!("Memory search results for \"{}\":\n\n", query);
    for (i, (sim, source, content, date)) in top.iter().enumerate() {
        out.push_str(&format!(
            "[{}] ({}, {:.0}% match, {})\n    {}\n\n",
            i + 1,
            source,
            sim * 100.0,
            date,
            content
        ));
    }
    out
}

/// Recursively collect text/code file paths relative to `dir`, up to `max_depth`.
fn collect_text_files(dir: &std::path::Path, depth: usize, max_depth: usize) -> Result<Vec<String>> {
    if depth > max_depth {
        return Ok(vec![]);
    }

    const TEXT_EXTS: &[&str] = &[
        "rs", "ts", "tsx", "js", "jsx", "py", "md", "txt", "json", "toml", "yaml", "yml",
        "html", "css", "scss", "sql", "sh", "bat", "c", "cpp", "h", "go", "java", "rb",
        "php", "swift", "kt", "cs", "r", "scala", "lua", "ex", "exs", "zig", "v",
    ];
    const SKIP_DIRS: &[&str] = &[
        "node_modules", ".git", "target", "__pycache__", ".next", "dist", "build",
        ".cache", "coverage", ".turbo", "out",
    ];

    let mut files = Vec::new();

    let entries = std::fs::read_dir(dir).map_err(|e| anyhow!("read_dir: {}", e))?;
    let mut entries: Vec<_> = entries.filter_map(|e| e.ok()).collect();
    entries.sort_by_key(|e| e.file_name());

    for entry in entries {
        let path = entry.path();
        let name = path
            .file_name()
            .and_then(|n| n.to_str())
            .unwrap_or("")
            .to_string();

        if name.starts_with('.') {
            continue;
        }

        if path.is_dir() {
            if SKIP_DIRS.contains(&name.as_str()) {
                continue;
            }
            let sub = collect_text_files(&path, depth + 1, max_depth)?;
            for f in sub {
                files.push(format!("{}/{}", name, f));
            }
        } else if path.is_file() {
            let ext = path
                .extension()
                .and_then(|e| e.to_str())
                .unwrap_or("");
            if TEXT_EXTS.contains(&ext) {
                files.push(name);
            }
        }
    }

    Ok(files)
}
