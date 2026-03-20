use anyhow::{anyhow, Result};
use futures::StreamExt;
use reqwest::Client;
use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter};

pub const DEFAULT_SYSTEM_PROMPT: &str = r#"You are CADEN — Chaos Aiming and Distress Evasion Navigator. You are a personal executive function assistant for a user with ADHD, bipolar disorder, and autism. Your job is to cut through cognitive chaos and give clear, direct, actionable output.

Rules:
- Never use filler phrases like 'Great question' or 'Certainly'
- Be honest even when the answer is uncomfortable
- Prioritize ruthlessly — not everything is urgent, say so
- Keep responses short unless detail is specifically needed
- When the user is overwhelmed, help them pick ONE thing to do next
- You have access to their calendar, tasks, and assignments. Reference them by name.
- Speak like a calm, competent friend who actually gets it — not a therapist, not a robot"#;

const OLLAMA_BASE: &str = "http://localhost:11434";
const MODEL_PRIMARY: &str = "llama3.1:8b";
const MODEL_FALLBACK: &str = "mistral:7b";

#[derive(Debug, Serialize, Deserialize)]
pub struct OllamaStatus {
    pub online: bool,
    pub model: Option<String>,
}

#[derive(Debug, Serialize, Deserialize)]
struct OllamaModel {
    name: String,
}

#[derive(Debug, Serialize, Deserialize)]
struct OllamaModelsResponse {
    models: Vec<OllamaModel>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct ChatHistoryItem {
    pub role: String,
    pub content: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct PlannerContext {
    pub date: String,
    pub plan_items: serde_json::Value,
    pub upcoming_deadlines: serde_json::Value,
    pub recent_completions: serde_json::Value,
}

#[derive(Debug, Serialize)]
struct OllamaChatRequest {
    model: String,
    messages: Vec<ChatMessage>,
    stream: bool,
}

#[derive(Debug, Serialize)]
struct ChatMessage {
    role: String,
    content: String,
}

#[derive(Debug, Deserialize)]
struct OllamaChatChunk {
    message: Option<ChunkMessage>,
    done: Option<bool>,
}

#[derive(Debug, Deserialize)]
struct ChunkMessage {
    content: String,
}

/// Ping Ollama and detect available model.
pub async fn check_status() -> OllamaStatus {
    let client = Client::builder()
        .timeout(std::time::Duration::from_secs(3))
        .build()
        .unwrap_or_default();

    let resp = client
        .get(format!("{}/api/tags", OLLAMA_BASE))
        .send()
        .await;

    match resp {
        Ok(r) if r.status().is_success() => {
            let body: Result<OllamaModelsResponse, _> = r.json().await;
            if let Ok(body) = body {
                let names: Vec<&str> = body.models.iter().map(|m| m.name.as_str()).collect();
                let model = if names.iter().any(|n| n.starts_with(MODEL_PRIMARY)) {
                    Some(MODEL_PRIMARY.to_string())
                } else if names.iter().any(|n| n.starts_with(MODEL_FALLBACK)) {
                    Some(MODEL_FALLBACK.to_string())
                } else {
                    names.first().map(|s| s.to_string())
                };
                OllamaStatus {
                    online: true,
                    model,
                }
            } else {
                OllamaStatus {
                    online: true,
                    model: None,
                }
            }
        }
        _ => OllamaStatus {
            online: false,
            model: None,
        },
    }
}

/// Send a chat message with streaming response.
/// Emits events: "ollama-token", "ollama-done", "ollama-error"
pub async fn chat_streaming(
    app: AppHandle,
    message: String,
    history: Vec<ChatHistoryItem>,
    context: PlannerContext,
    model: String,
    system_prompt: String,
) -> Result<()> {
    let client = Client::builder()
        .timeout(std::time::Duration::from_secs(120))
        .build()?;

    // Build context suffix for system message
    let context_str = format!(
        "\n\n---\nCurrent date/time: {}\nToday's plan: {}\nNext 3 deadlines: {}\nRecent completions: {}",
        context.date,
        serde_json::to_string_pretty(&context.plan_items).unwrap_or_default(),
        serde_json::to_string_pretty(&context.upcoming_deadlines).unwrap_or_default(),
        serde_json::to_string_pretty(&context.recent_completions).unwrap_or_default(),
    );

    // Build messages array
    let mut messages: Vec<ChatMessage> = Vec::new();
    messages.push(ChatMessage {
        role: "system".to_string(),
        content: format!("{}{}", system_prompt, context_str),
    });

    for h in history {
        messages.push(ChatMessage {
            role: h.role,
            content: h.content,
        });
    }

    messages.push(ChatMessage {
        role: "user".to_string(),
        content: message,
    });

    let req = OllamaChatRequest {
        model,
        messages,
        stream: true,
    };

    let response = client
        .post(format!("{}/api/chat", OLLAMA_BASE))
        .json(&req)
        .send()
        .await
        .map_err(|e| anyhow!("Failed to reach Ollama: {}", e))?;

    if !response.status().is_success() {
        let _ = app.emit("ollama-error", "Ollama returned an error. Is the model loaded?");
        return Ok(());
    }

    let mut stream = response.bytes_stream();

    while let Some(chunk) = stream.next().await {
        match chunk {
            Ok(bytes) => {
                // Each line is a JSON object
                let text = String::from_utf8_lossy(&bytes);
                for line in text.lines() {
                    let line = line.trim();
                    if line.is_empty() {
                        continue;
                    }
                    if let Ok(parsed) = serde_json::from_str::<OllamaChatChunk>(line) {
                        if let Some(msg) = &parsed.message {
                            if !msg.content.is_empty() {
                                let _ = app.emit("ollama-token", &msg.content);
                            }
                        }
                        if parsed.done == Some(true) {
                            let _ = app.emit("ollama-done", ());
                            return Ok(());
                        }
                    }
                }
            }
            Err(e) => {
                let _ = app.emit("ollama-error", format!("Stream error: {}", e));
                return Ok(());
            }
        }
    }

    let _ = app.emit("ollama-done", ());
    Ok(())
}

/// Pull a model via Ollama API.
pub async fn pull_model(model: &str) -> Result<()> {
    let client = Client::builder()
        .timeout(std::time::Duration::from_secs(600))
        .build()?;

    let resp = client
        .post(format!("{}/api/pull", OLLAMA_BASE))
        .json(&serde_json::json!({ "name": model, "stream": false }))
        .send()
        .await?;

    if resp.status().is_success() {
        Ok(())
    } else {
        Err(anyhow!("Pull failed: {}", resp.status()))
    }
}
