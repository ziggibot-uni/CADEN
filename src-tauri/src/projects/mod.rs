use anyhow::Result;
use chrono::Utc;
use serde::{Deserialize, Serialize};
use sqlx::SqlitePool;

use crate::db::ops::generate_id;

#[derive(Debug, Clone, Serialize, Deserialize, sqlx::FromRow)]
pub struct Project {
    pub id: String,
    pub name: String,
    pub description: Option<String>,
    pub status: String,
    pub folder_path: Option<String>,
    pub parent_id: Option<String>,
    pub created_at: String,
    pub updated_at: String,
    pub educat_course_id: Option<String>,
    pub educat_course_name: Option<String>,
    pub spec_path: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, sqlx::FromRow)]
pub struct ProjectEntry {
    pub id: String,
    pub project_id: String,
    pub entry_type: String,
    pub content: String,
    pub tags: Option<String>,
    pub completed: bool,
    pub created_at: String,
    pub parent_id: Option<String>,
    pub google_task_id: Option<String>,
}

// ─── Vector helpers ───────────────────────────────────────────────────────────

fn vec_to_bytes(v: &[f32]) -> Vec<u8> {
    v.iter().flat_map(|f| f.to_le_bytes()).collect()
}

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

// ─── Project CRUD ─────────────────────────────────────────────────────────────

pub async fn list_projects(pool: &SqlitePool) -> Result<Vec<Project>> {
    let rows = sqlx::query_as::<_, Project>(
        "SELECT * FROM projects ORDER BY updated_at DESC",
    )
    .fetch_all(pool)
    .await?;
    Ok(rows)
}

pub async fn add_project(
    pool: &SqlitePool,
    name: String,
    description: Option<String>,
    parent_id: Option<String>,
) -> Result<Project> {
    let now = Utc::now().to_rfc3339();
    let id = generate_id();
    sqlx::query(
        "INSERT INTO projects (id, name, description, status, parent_id, created_at, updated_at)
         VALUES (?, ?, ?, 'active', ?, ?, ?)",
    )
    .bind(&id)
    .bind(&name)
    .bind(&description)
    .bind(&parent_id)
    .bind(&now)
    .bind(&now)
    .execute(pool)
    .await?;

    Ok(Project {
        id,
        name,
        description,
        status: "active".to_string(),
        folder_path: None,
        parent_id,
        created_at: now.clone(),
        updated_at: now,
        educat_course_id: None,
        educat_course_name: None,
        spec_path: None,
    })
}

pub async fn set_project_educat_course(
    pool: &SqlitePool,
    project_id: String,
    course_id: Option<String>,
    course_name: Option<String>,
) -> Result<()> {
    sqlx::query("UPDATE projects SET educat_course_id = ?, educat_course_name = ? WHERE id = ?")
        .bind(&course_id)
        .bind(&course_name)
        .bind(&project_id)
        .execute(pool)
        .await?;
    Ok(())
}

pub async fn set_project_spec_path(
    pool: &SqlitePool,
    project_id: String,
    spec_path: Option<String>,
) -> Result<()> {
    sqlx::query("UPDATE projects SET spec_path = ? WHERE id = ?")
        .bind(&spec_path)
        .bind(&project_id)
        .execute(pool)
        .await?;
    Ok(())
}

pub async fn set_project_parent(
    pool: &SqlitePool,
    id: String,
    parent_id: Option<String>,
) -> Result<()> {
    sqlx::query("UPDATE projects SET parent_id = ? WHERE id = ?")
        .bind(&parent_id)
        .bind(&id)
        .execute(pool)
        .await?;
    Ok(())
}

pub async fn set_project_folder(
    pool: &SqlitePool,
    project_id: String,
    folder_path: Option<String>,
) -> Result<()> {
    sqlx::query("UPDATE projects SET folder_path = ? WHERE id = ?")
        .bind(&folder_path)
        .bind(&project_id)
        .execute(pool)
        .await?;
    Ok(())
}

pub async fn update_project(
    pool: &SqlitePool,
    id: String,
    name: String,
    description: Option<String>,
    status: String,
) -> Result<()> {
    let now = Utc::now().to_rfc3339();
    sqlx::query(
        "UPDATE projects SET name = ?, description = ?, status = ?, updated_at = ? WHERE id = ?",
    )
    .bind(&name)
    .bind(&description)
    .bind(&status)
    .bind(&now)
    .bind(&id)
    .execute(pool)
    .await?;
    Ok(())
}

pub async fn delete_project(pool: &SqlitePool, id: String) -> Result<()> {
    // Promote children to root before deleting the parent
    sqlx::query("UPDATE projects SET parent_id = NULL WHERE parent_id = ?")
        .bind(&id)
        .execute(pool)
        .await?;
    sqlx::query("DELETE FROM projects WHERE id = ?")
        .bind(&id)
        .execute(pool)
        .await?;
    Ok(())
}

// ─── Entry CRUD ───────────────────────────────────────────────────────────────

pub async fn get_project_entries(
    pool: &SqlitePool,
    project_id: &str,
) -> Result<Vec<ProjectEntry>> {
    let rows = sqlx::query_as::<_, ProjectEntry>(
        "SELECT id, project_id, entry_type, content, tags, completed, created_at, parent_id, google_task_id
         FROM project_entries WHERE project_id = ? ORDER BY created_at DESC",
    )
    .bind(project_id)
    .fetch_all(pool)
    .await?;
    Ok(rows)
}

/// Add an entry and immediately embed it.
pub async fn add_project_entry(
    pool: &SqlitePool,
    project_id: String,
    entry_type: String,
    content: String,
    tags: Option<String>,
    parent_id: Option<String>,
) -> Result<ProjectEntry> {
    let now = Utc::now().to_rfc3339();
    let id = generate_id();

    // Embed the content — soft fail if nomic-embed-text is unavailable
    let embedding_bytes = crate::ollama::embed(&content)
        .await
        .ok()
        .map(|v| vec_to_bytes(&v));

    sqlx::query(
        "INSERT INTO project_entries
         (id, project_id, entry_type, content, tags, parent_id, created_at, embedding)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(&id)
    .bind(&project_id)
    .bind(&entry_type)
    .bind(&content)
    .bind(&tags)
    .bind(&parent_id)
    .bind(&now)
    .bind(&embedding_bytes)
    .execute(pool)
    .await?;

    sqlx::query("UPDATE projects SET updated_at = ? WHERE id = ?")
        .bind(&now)
        .bind(&project_id)
        .execute(pool)
        .await?;

    Ok(ProjectEntry {
        id,
        project_id,
        entry_type,
        content,
        tags,
        completed: false,
        created_at: now,
        parent_id,
        google_task_id: None,
    })
}

pub async fn toggle_project_entry_complete(
    pool: &SqlitePool,
    id: String,
) -> Result<ProjectEntry> {
    sqlx::query(
        "UPDATE project_entries SET completed = NOT completed WHERE id = ?",
    )
    .bind(&id)
    .execute(pool)
    .await?;

    let entry = sqlx::query_as::<_, ProjectEntry>(
        "SELECT id, project_id, entry_type, content, tags, completed, created_at, parent_id, google_task_id
         FROM project_entries WHERE id = ?",
    )
    .bind(&id)
    .fetch_one(pool)
    .await?;

    Ok(entry)
}

pub async fn delete_project_entry(pool: &SqlitePool, id: String) -> Result<()> {
    sqlx::query("DELETE FROM project_entries WHERE id = ?")
        .bind(&id)
        .execute(pool)
        .await?;
    Ok(())
}

pub async fn update_project_entry(
    pool: &SqlitePool,
    id: String,
    content: String,
) -> Result<ProjectEntry> {
    // Re-embed the updated content — soft fail if nomic-embed-text is unavailable
    let embedding_bytes = crate::ollama::embed(&content)
        .await
        .ok()
        .map(|v| vec_to_bytes(&v));

    sqlx::query(
        "UPDATE project_entries SET content = ?, embedding = ? WHERE id = ?",
    )
    .bind(&content)
    .bind(&embedding_bytes)
    .bind(&id)
    .execute(pool)
    .await?;

    let entry = sqlx::query_as::<_, ProjectEntry>(
        "SELECT id, project_id, entry_type, content, tags, completed, created_at, parent_id, google_task_id
         FROM project_entries WHERE id = ?",
    )
    .bind(&id)
    .fetch_one(pool)
    .await?;

    Ok(entry)
}

// ─── Internal: entries with embeddings ───────────────────────────────────────

#[derive(sqlx::FromRow)]
struct EntryWithEmbed {
    id: String,
    project_id: String,
    entry_type: String,
    content: String,
    tags: Option<String>,
    completed: bool,
    created_at: String,
    parent_id: Option<String>,
    google_task_id: Option<String>,
    embedding: Option<Vec<u8>>,
}

/// Fetch entries along with their stored embedding vectors.
/// Pass `project_id = Some(id)` to scope to one project, or `None` for all.
pub async fn get_entries_with_vecs(
    pool: &SqlitePool,
    project_id: Option<&str>,
) -> Result<Vec<(ProjectEntry, Option<Vec<f32>>)>> {
    let rows: Vec<EntryWithEmbed> = if let Some(pid) = project_id {
        sqlx::query_as(
            "SELECT id, project_id, entry_type, content, tags, completed, created_at,
                    parent_id, google_task_id, embedding
             FROM project_entries WHERE project_id = ? ORDER BY created_at DESC",
        )
        .bind(pid)
        .fetch_all(pool)
        .await?
    } else {
        sqlx::query_as(
            "SELECT id, project_id, entry_type, content, tags, completed, created_at,
                    parent_id, google_task_id, embedding
             FROM project_entries ORDER BY created_at DESC",
        )
        .fetch_all(pool)
        .await?
    };

    Ok(rows
        .into_iter()
        .map(|r| {
            let vec = r.embedding.map(|b| bytes_to_vec(&b));
            let entry = ProjectEntry {
                id: r.id,
                project_id: r.project_id,
                entry_type: r.entry_type,
                content: r.content,
                tags: r.tags,
                completed: r.completed,
                created_at: r.created_at,
                parent_id: r.parent_id,
                google_task_id: r.google_task_id,
            };
            (entry, vec)
        })
        .collect())
}

// ─── RAG context builder ──────────────────────────────────────────────────────

/// Return up to `limit` project entries (excluding __thoughts__) most semantically
/// similar to `query_embedding`. Returns `(project_name, entry_type, excerpt)` tuples.
/// Used by the Sean Model briefing to passively inject relevant project knowledge.
pub async fn get_relevant_project_entries(
    pool: &SqlitePool,
    query_embedding: Vec<f32>,
    limit: usize,
) -> Vec<(String, String, String)> {
    use sqlx::Row as _;
    let rows = sqlx::query(
        "SELECT pe.content, pe.entry_type, pe.created_at, pe.embedding, p.name as project_name
         FROM project_entries pe
         JOIN projects p ON p.id = pe.project_id
         WHERE p.name != '__thoughts__'
           AND p.status != 'archived'
           AND pe.embedding IS NOT NULL
         ORDER BY pe.created_at DESC
         LIMIT 300",
    )
    .fetch_all(pool)
    .await
    .unwrap_or_default();

    let mut scored: Vec<(f32, String, String, String)> = rows
        .into_iter()
        .filter_map(|row| {
            let content: String = row.try_get("content").ok()?;
            let entry_type: String = row.try_get("entry_type").ok()?;
            let proj: String = row.try_get("project_name").ok()?;
            let emb_bytes: Vec<u8> = row.try_get::<Option<Vec<u8>>, _>("embedding").ok().flatten()?;
            let vec = bytes_to_vec(&emb_bytes);
            let sim = cosine_similarity(&query_embedding, &vec);
            if sim < 0.35 {
                return None;
            }
            let excerpt: String = content.chars().take(150).collect();
            Some((sim, proj, entry_type, excerpt))
        })
        .collect();

    scored.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(std::cmp::Ordering::Equal));
    scored.into_iter().take(limit).map(|(_, proj, etype, excerpt)| (proj, etype, excerpt)).collect()
}

/// Build context to inject into the system prompt for a given user message.
///
/// Strategy:
///   1. Embed the message with nomic-embed-text.
///   2. If the message explicitly names a project, retrieve ALL entries for that
///      project sorted by cosine similarity so the most relevant ones surface first.
///   3. Otherwise, do a global semantic search across all entries, return the
///      top matches above a similarity threshold.
///
/// `precomputed_vec` — pass the already-embedded query vector to avoid a
/// redundant embed call. If `None`, embeds `message` here (fallback).
pub async fn build_project_context(
    pool: &SqlitePool,
    message: &str,
    precomputed_vec: Option<Vec<f32>>,
) -> Result<String> {
    let projects = list_projects(pool).await?;
    if projects.is_empty() {
        return Ok(String::new());
    }

    let query_vec = match precomputed_vec {
        Some(v) => v,
        None => crate::ollama::embed(message).await?,
    };
    let msg_lower = message.to_lowercase();

    // 1. Explicit project name mention
    let named = projects.iter().find(|p| {
        let name_lower = p.name.to_lowercase();
        msg_lower.contains(&name_lower)
            || name_lower
                .split_whitespace()
                .any(|w| w.len() > 3 && msg_lower.contains(w))
    });

    if let Some(project) = named {
        let with_vecs = get_entries_with_vecs(pool, Some(&project.id)).await?;
        // Sort entries by similarity — most relevant first within each type group
        let mut scored: Vec<(ProjectEntry, f32)> = with_vecs
            .into_iter()
            .map(|(e, v)| {
                let sim = v
                    .as_ref()
                    .map(|vec| cosine_similarity(&query_vec, vec))
                    .unwrap_or(0.0);
                (e, sim)
            })
            .collect();
        scored.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
        let entries: Vec<ProjectEntry> = scored.into_iter().map(|(e, _)| e).collect();
        return Ok(format_project_context(project, &entries));
    }

    // 2. Global semantic search — skip archived projects
    let active_ids: std::collections::HashSet<&str> = projects
        .iter()
        .filter(|p| p.status != "archived")
        .map(|p| p.id.as_str())
        .collect();

    let all = get_entries_with_vecs(pool, None).await?;
    let mut scored: Vec<(ProjectEntry, f32)> = all
        .into_iter()
        .filter(|(e, v)| active_ids.contains(e.project_id.as_str()) && v.is_some())
        .map(|(e, v)| {
            let sim = cosine_similarity(&query_vec, v.as_ref().unwrap());
            (e, sim)
        })
        .collect();

    scored.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));

    // Only surface results above a meaningful similarity threshold
    let top: Vec<_> = scored
        .into_iter()
        .filter(|(_, sim)| *sim > 0.35)
        .take(6)
        .collect();

    if top.is_empty() {
        return Ok(String::new());
    }

    let mut out = String::from("## Relevant project context\n");
    for (entry, _) in &top {
        let proj_name = projects
            .iter()
            .find(|p| p.id == entry.project_id)
            .map(|p| p.name.as_str())
            .unwrap_or("Unknown");
        let type_label = if entry.entry_type == "todo" && entry.completed {
            "work completed".to_string()
        } else {
            entry.entry_type.clone()
        };
        out.push_str(&format!(
            "- [{}] {}: {}\n",
            proj_name, type_label, entry.content
        ));
    }
    Ok(out)
}

// ─── Formatting ───────────────────────────────────────────────────────────────

fn format_project_context(project: &Project, entries: &[ProjectEntry]) -> String {
    let mut out = format!("## Project: {}\n", project.name);
    if let Some(desc) = &project.description {
        out.push_str(&format!("Description: {}\n", desc));
    }
    out.push_str(&format!("Status: {}\n", project.status));

    // Open todos
    let open_todos: Vec<_> = entries
        .iter()
        .filter(|e| e.entry_type == "todo" && !e.completed)
        .collect();
    if !open_todos.is_empty() {
        out.push_str(&format!("\n### Open TODOs ({} remaining)\n", open_todos.len()));
        for e in open_todos.iter().take(10) {
            out.push_str(&format!("- [ ] {}\n", e.content));
        }
    } else {
        out.push_str("\n### Open TODOs\nNone — all caught up!\n");
    }

    // Completed todos as a work-log so the LLM knows what's been done
    let done_todos: Vec<_> = entries
        .iter()
        .filter(|e| e.entry_type == "todo" && e.completed)
        .collect();
    if !done_todos.is_empty() {
        out.push_str(&format!("\n### Work completed ({} tasks done)\n", done_todos.len()));
        for e in done_todos.iter().take(10) {
            let date = e.created_at.get(..10).unwrap_or(&e.created_at);
            out.push_str(&format!("- [x] {} ({})\n", e.content, date));
        }
        if done_todos.len() > 10 {
            out.push_str(&format!("  … and {} more completed\n", done_todos.len() - 10));
        }
    }

    for entry_type in &[
        "update",
        "decision",
        "idea",
        "blocker",
        "reference",
    ] {
        let typed: Vec<_> = entries
            .iter()
            .filter(|e| e.entry_type.as_str() == *entry_type)
            .collect();
        if typed.is_empty() {
            continue;
        }
        let label = match *entry_type {
            "update"    => "Recent updates",
            "decision"  => "Decisions made",
            "idea"      => "Ideas to explore",
            "blocker"   => "Current blockers",
            "reference" => "References",
            _ => entry_type,
        };
        out.push_str(&format!("\n### {}\n", label));
        // Within each type, entries are already sorted by similarity (most relevant first)
        for e in typed.iter().take(10) {
            out.push_str(&format!("- {}\n", e.content));
        }
    }
    out
}

// ─── Semantic search (exposed to frontend) ───────────────────────────────────

pub async fn search_entries_semantic(
    pool: &SqlitePool,
    project_id: &str,
    query: &str,
    limit: usize,
) -> Result<Vec<ProjectEntry>> {
    // Try embedding-based search first; fall back to substring search if unavailable
    let query_lower = query.to_lowercase();

    match crate::ollama::embed(query).await {
        Ok(query_vec) => {
            let with_vecs = get_entries_with_vecs(pool, Some(project_id)).await?;
            let mut scored: Vec<(ProjectEntry, f32)> = with_vecs
                .into_iter()
                .filter(|(_, v)| v.is_some())
                .map(|(e, v)| {
                    let sim = cosine_similarity(&query_vec, v.as_ref().unwrap());
                    (e, sim)
                })
                .collect();
            scored.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
            Ok(scored
                .into_iter()
                .filter(|(_, sim)| *sim > 0.25)
                .take(limit)
                .map(|(e, _)| e)
                .collect())
        }
        Err(_) => {
            // Fallback: simple case-insensitive substring match
            let all = sqlx::query_as::<_, ProjectEntry>(
                "SELECT id, project_id, entry_type, content, tags, completed, created_at, parent_id, google_task_id
                 FROM project_entries WHERE project_id = ?",
            )
            .bind(project_id)
            .fetch_all(pool)
            .await?;
            Ok(all
                .into_iter()
                .filter(|e| e.content.to_lowercase().contains(&query_lower))
                .take(limit)
                .collect())
        }
    }
}
