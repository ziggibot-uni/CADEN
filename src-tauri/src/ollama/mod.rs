use anyhow::{anyhow, Result};
use futures::StreamExt;
use reqwest::Client;
use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter};

pub const DEFAULT_SYSTEM_PROMPT: &str = r#"You are CADEN — Sean's homie who happens to keep him from falling apart. Friend first. Executive function backup second.

WHO SEAN IS:
Sean Kellogg is a biology student at Northern Michigan University. ADHD, bipolar disorder, autism — the full chaos combo. Brilliant, creative as hell, and profoundly defiant when bored. His brain is a Chaos Cannon: constantly firing ideas, visions, stories — which makes tedious-but-necessary work feel physically impossible. He smokes weed and functions best when he's had enough creative time first. His self-worth is built on what he makes, not grades, so academic work has to feel real and concrete before it lands.

THE ACTUAL MISSION — read this carefully:
Sean's goal is to graduate NMU without burning out and to have as much fun as possible doing it. That means:
1. Prevent burnout above all else. Burnout ends everything. A day he enjoyed > a day he was productive.
2. Maximize creative time and fun. This is load-bearing, not optional. His definition of fun, not yours.
3. Get school done when needed — but school only gets airtime when he brings it up or it's actually urgent.

WHAT "PRODUCTIVE" LOOKS LIKE FOR SEAN:
- Days where he worked on something he loved + handled one necessary thing = a win.
- Days where he only did schoolwork = burnout risk.
- Idle time is not a problem. It's often recovery. Don't fill it with tasks.

YOUR JOB (in priority order):
1. Be present. Hang out. Actually get to know him — his taste, his projects, what he's into, what he finds funny.
2. When he brings up something stressful, acknowledge it fully before anything else. He needs to feel heard, not coached.
3. When he's idle and there's genuinely nothing urgent, ask him about himself. What's he working on? What's he excited about? What did he do yesterday? Curiosity > productivity.
4. When he asks for help organizing or getting something done, THEN be his executive function.
5. When something is actually urgent (deadline today, important thing tomorrow), bring it up once — not repeatedly.
6. When he asks you to create tasks or events, just do it. No narrating, no asking for confirmation — act.

HARD RULES — never break these:
- NEVER suggest tasks or ask 'what do you want to tackle?' unless he specifically asks for a plan or task list.
- NEVER invent urgency. If the briefing doesn't show something as urgent, don't treat it like it is.
- NEVER push school when he's chilling. Not even gently. It ruins the vibe and he'll shut down.
- If he says there's nothing going on, believe him. Don't contradict him with task lists.
- Idle time is allowed. Just talk to him.

YOUR TOOLS — use them proactively, don't wait to be asked:
- search_web: Look up anything Sean needs. Documentation, facts, how-tos. Results get saved and cited.
- recall_web: Find something you looked up before. Your web memory.
- search_memory: Search ALL of Sean's history — thought dumps, past chats, project entries. This is your long-term memory. Use it when he references something from before, or when you need context.
- list_projects / get_project_entries: See Sean's projects and everything he's written in them.
- list_project_files / read_project_file: Read actual code and files in project folders.
- add_task: Creates a task, syncs to Google Tasks, and triggers a replan automatically.
- get_today_tasks: See today's schedule.
You can chain tools: list_projects → get_project_entries → read_project_file → search_web → add_task. Go as deep as needed. You have up to 6 tool calls per response.

GROUNDING RULES — non-negotiable:
- You only know what's explicitly in the context or retrieved via tools. Full stop.
- Do NOT invent people, emails, events, tasks, or commitments that aren't listed verbatim.
- If it's not in the context and you can't look it up with a tool, it doesn't exist.
- When you use information from search_memory or search_web, cite where it came from.

TIME-OF-DAY RULES:
- Read the current time in the briefing every single time.
- After ~10 PM, don't touch schoolwork or productivity unless he brings it up.
- Late night is valid creative time. Back him fully.

VOICE:
- Friend first. Match his energy exactly — if he's chill, be chill; if he's hype, be hype; if he's venting, just listen.
- Always acknowledge what he said before doing anything else. Feel first, assist second.
- Casual as hell. Swear if it fits. No professionalism theater.
- Skip all filler: no 'Great question', 'Certainly', 'I'd be happy to', 'What do you want to tackle?', 'How about we...'.
- Short by default. Don't over-explain. Don't pad.
- Humor is good. Sarcasm when it lands. Real talk always.
- Never close with a task prompt unless he asked for one."#;

const OLLAMA_BASE: &str = "http://localhost:11434";
const GITHUB_MODELS_BASE: &str = "https://models.github.ai/inference";
const GROQ_BASE: &str = "https://api.groq.com/openai/v1";
const GROQ_BACKGROUND_MODEL: &str = "llama-3.3-70b-versatile";

/// Round-robin index for Groq key rotation.
static GROQ_KEY_IDX: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);

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

/// Full context trace emitted to the frontend before streaming begins.
/// Gives the UI everything it needs to show a comprehensive "what happened" view.
#[derive(Debug, Serialize, Clone)]
struct TracePayload {
    model: String,
    intent: String,
    one_line: String,
    needs_project_context: bool,
    needs_schedule_context: bool,
    classification_raw: String,
    analysis: String,
    situational_briefing: String,
    project_context: String,
    date: String,
    plan_items: serde_json::Value,
    upcoming_deadlines: serde_json::Value,
}

#[derive(Debug, Serialize, Clone)]
struct OllamaOptions {
    num_gpu: i32,
}

#[derive(Debug, Serialize, Clone)]
struct OllamaChatRequest {
    model: String,
    messages: Vec<ChatMessage>,
    stream: bool,
    think: bool,
    keep_alive: i64,
    options: OllamaOptions,
    #[serde(skip_serializing_if = "Option::is_none")]
    tools: Option<Vec<OllamaTool>>,
}

#[derive(Debug, Serialize, Clone)]
struct OllamaTool {
    #[serde(rename = "type")]
    kind: String,
    function: OllamaToolFunction,
}

#[derive(Debug, Serialize, Clone)]
struct OllamaToolFunction {
    name: String,
    description: String,
    parameters: serde_json::Value,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
struct ChatMessage {
    role: String,
    content: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    tool_calls: Option<Vec<ToolCall>>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
struct ToolCall {
    function: ToolCallFunction,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
struct ToolCallFunction {
    name: String,
    arguments: serde_json::Value,
}

#[derive(Debug, Deserialize)]
struct OllamaChatChunk {
    message: Option<ChunkMessage>,
    done: Option<bool>,
}

#[derive(Debug, Deserialize)]
struct ChunkMessage {
    content: String,
    #[serde(default)]
    tool_calls: Vec<ToolCall>,
}

/// The tools CADEN can invoke directly during a streamed response.
fn caden_tools() -> Vec<OllamaTool> {
    vec![
        OllamaTool {
            kind: "function".to_string(),
            function: OllamaToolFunction {
                name: "add_task".to_string(),
                description: "Add a task to Sean's local task list. Use when he asks you to add, create, or remember a task, todo, or to-do item.".to_string(),
                parameters: serde_json::json!({
                    "type": "object",
                    "required": ["title"],
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Short task title (the thing to do)"
                        },
                        "due_date": {
                            "type": "string",
                            "description": "ISO date YYYY-MM-DD, or omit for today"
                        },
                        "estimated_minutes": {
                            "type": "integer",
                            "description": "How many minutes this will take, if known"
                        },
                        "task_type": {
                            "type": "string",
                            "description": "One of: creative, academic, health, errand, social, general"
                        }
                    }
                }),
            },
        },
        OllamaTool {
            kind: "function".to_string(),
            function: OllamaToolFunction {
                name: "get_today_tasks".to_string(),
                description: "Get today's task list and plan items so you can accurately report what's on the schedule.".to_string(),
                parameters: serde_json::json!({
                    "type": "object",
                    "properties": {}
                }),
            },
        },
        OllamaTool {
            kind: "function".to_string(),
            function: OllamaToolFunction {
                name: "search_web".to_string(),
                description: "Search the web for current information via local SearXNG. Use when the user asks about something that needs up-to-date facts, documentation, news, or anything not in your training data. Results are saved and citable.".to_string(),
                parameters: serde_json::json!({
                    "type": "object",
                    "required": ["query"],
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query — be specific for better results"
                        }
                    }
                }),
            },
        },
        OllamaTool {
            kind: "function".to_string(),
            function: OllamaToolFunction {
                name: "recall_web".to_string(),
                description: "Recall previously cached web search results using semantic similarity. Use when the user references something you may have looked up before, or to find a URL you saved earlier.".to_string(),
                parameters: serde_json::json!({
                    "type": "object",
                    "required": ["query"],
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "What to search for in past web lookups"
                        }
                    }
                }),
            },
        },
        OllamaTool {
            kind: "function".to_string(),
            function: OllamaToolFunction {
                name: "list_projects".to_string(),
                description: "List Sean's active projects and their linked folder paths. Use this first to see what projects exist and which have code/files you can read.".to_string(),
                parameters: serde_json::json!({
                    "type": "object",
                    "properties": {}
                }),
            },
        },
        OllamaTool {
            kind: "function".to_string(),
            function: OllamaToolFunction {
                name: "list_project_files".to_string(),
                description: "List the files inside a project's linked folder. Use this to explore what code or docs a project contains before reading specific files.".to_string(),
                parameters: serde_json::json!({
                    "type": "object",
                    "required": ["project"],
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Project name or ID (from list_projects)"
                        }
                    }
                }),
            },
        },
        OllamaTool {
            kind: "function".to_string(),
            function: OllamaToolFunction {
                name: "read_project_file".to_string(),
                description: "Read the contents of a specific file inside a project's folder. Use after list_project_files to get the actual code or documentation.".to_string(),
                parameters: serde_json::json!({
                    "type": "object",
                    "required": ["project", "path"],
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Project name or ID"
                        },
                        "path": {
                            "type": "string",
                            "description": "File path relative to project folder (e.g. 'src/main.rs' or 'README.md')"
                        }
                    }
                }),
            },
        },
        OllamaTool {
            kind: "function".to_string(),
            function: OllamaToolFunction {
                name: "get_project_entries".to_string(),
                description: "Read a project's entries grouped by type. Open TODOs are always shown first with [ ] markers; completed todos show [x]. Use this to check what work is still pending in a project.".to_string(),
                parameters: serde_json::json!({
                    "type": "object",
                    "required": ["project"],
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Project name or ID"
                        }
                    }
                }),
            },
        },
        OllamaTool {
            kind: "function".to_string(),
            function: OllamaToolFunction {
                name: "search_memory".to_string(),
                description: "Search across ALL of Sean's memories — thought dump entries, past chat messages, and project entries — using semantic similarity. Use when Sean references something he said/thought before, or when you need context from his history. This is your long-term memory.".to_string(),
                parameters: serde_json::json!({
                    "type": "object",
                    "required": ["query"],
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "What to search for in Sean's memory (thoughts, chats, project entries)"
                        }
                    }
                }),
            },
        },
    ]
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
                let model = names.first().map(|s| s.to_string());
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

/// Check whether a specific model name is present in Ollama's installed list.
pub async fn model_is_installed(model: &str) -> bool {
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
                body.models.iter().any(|m| m.name == model || m.name.starts_with(model))
            } else {
                false
            }
        }
        _ => false,
    }
}

/// Send a no-op request to load the model into VRAM so the first real message
/// isn't delayed by model loading. Fire-and-forget — errors are silently ignored.
pub async fn warm_model(model: &str) {
    let client = Client::builder()
        .timeout(std::time::Duration::from_secs(120))
        .build()
        .unwrap_or_default();
    let req = OllamaChatRequest {
        model: model.to_string(),
        messages: vec![ChatMessage {
            role: "user".to_string(),
            content: "hi".to_string(),
            tool_calls: None,
        }],
        stream: false,
        think: false,
        keep_alive: -1,
        options: OllamaOptions { num_gpu: 99 },
        tools: None,
    };
    let _ = client
        .post(format!("{}/api/chat", OLLAMA_BASE))
        .json(&req)
        .send()
        .await;
}

/// Three-call intelligence pipeline.
///
/// Call 1 — Classify (fast, non-streaming):
///   Determines intent and which context blocks are actually needed.
///
/// Call 2 — Analyze (non-streaming):
///   Receives full relevant context. Synthesizes a plain-text briefing for the
///   response agent. This is where all the "thinking" happens.
///
/// Call 3 — Respond (streaming to UI):
///   Receives the briefing + original message. Minimal context — the thinking
///   is already done. Just communicates.
pub async fn chat_pipeline(
    app: AppHandle,
    message: String,
    history: Vec<ChatHistoryItem>,
    context: PlannerContext,
    model: String,
    github_pat: Option<String>,
    groq_keys: Vec<String>,
    system_prompt: String,
    project_context: String,
    situational_briefing: String,
    pool: sqlx::SqlitePool,
    morning_meds: Vec<crate::db::models::MedGroupEntry>,
    evening_meds: Vec<crate::db::models::MedGroupEntry>,
) -> Result<()> {
    let _ = app.emit("caden-phase", "classifying");

    // ── Call 1: Classify ─────────────────────────────────────────────────────
    let classify_prompt = format!(
        "Classify this message. Respond with ONLY a raw JSON object — no markdown, \
         no explanation, no extra text.\n\n\
         Message: \"{}\"\n\n\
         {{\"intent\":\"project_work|task_planning|calendar_query|emotional|question|general\",\
         \"needs_project_context\":true|false,\
         \"needs_schedule_context\":true|false,\
         \"needs_data_report\":true|false,\
         \"one_line\":\"what they want in 5 words\"}}\n\n\
         Set needs_data_report=true ONLY when the user is explicitly asking for specific \
         numerical values or history (e.g. energy levels, mood scores, medication logs, \
         completion rates, rolling averages). Set it false for action requests, general chat, \
         or emotional support.",
        message.replace('"', "'")
    );

    let classify_raw = match llm_oneshot(&model, &classify_prompt, &github_pat, &groq_keys).await {
        Ok(r) => r,
        Err(_) => {
            // Classify failed — use safe defaults (include all context)
            String::from("{\"intent\":\"general\",\"needs_project_context\":true,\"needs_schedule_context\":true,\"needs_data_report\":false,\"one_line\":\"user request\"}")
        }
    };

    // Strip markdown fences — small models often wrap JSON anyway
    let classify_clean = classify_raw
        .trim()
        .trim_start_matches("```json")
        .trim_start_matches("```")
        .trim_end_matches("```")
        .trim();

    let classification: serde_json::Value = serde_json::from_str(classify_clean)
        .unwrap_or_else(|_| {
            serde_json::json!({
                "intent": "general",
                "needs_project_context": !project_context.is_empty(),
                "needs_schedule_context": true,
                "needs_data_report": false,
                "one_line": "user request"
            })
        });

    // Log classify training example — only when using a cloud model
    if serde_json::from_str::<serde_json::Value>(classify_clean).is_ok()
        && should_log_training(&groq_keys, &github_pat)
    {
        let bg_m = bg_model_name(&model, &groq_keys);
        let _ = crate::training::log_example(&pool, "classify", None, &classify_prompt, classify_clean, &bg_m).await;
    }

    let intent = classification["intent"].as_str().unwrap_or("general");
    let one_line = classification["one_line"].as_str().unwrap_or("user request");

    // Safety net: override context flags when intent clearly requires them.
    // Prevents classify misfires from silently dropping critical context.
    let schedule_intents = ["task_planning", "calendar_query"];
    let project_intents = ["project_work"];

    let needs_project = classification["needs_project_context"]
        .as_bool()
        .unwrap_or(!project_context.is_empty())
        || project_intents.contains(&intent);
    let needs_schedule = classification["needs_schedule_context"]
        .as_bool()
        .unwrap_or(true)
        || schedule_intents.contains(&intent);

    // Also catch user messages that mention schedule keywords even if classify missed it
    let msg_lower = message.to_lowercase();
    let schedule_keywords = ["schedule", "today", "plan", "task", "deadline", "due", "calendar", "event"];
    let needs_schedule = needs_schedule || schedule_keywords.iter().any(|kw| msg_lower.contains(kw));

    let needs_data_report = classification["needs_data_report"]
        .as_bool()
        .unwrap_or(false);

    let _ = app.emit("caden-phase", "analyzing");

    // ── Call 2: Analyze ───────────────────────────────────────────────────────
    let mut analysis_ctx = format!(
        "User message: \"{}\"\nIntent: {} — {}\n",
        message, intent, one_line
    );

    if !situational_briefing.is_empty() {
        analysis_ctx.push_str(&format!(
            "\n=== CURRENT STATE (complete — nothing omitted) ===\n{}\n=== END CURRENT STATE ===\n",
            situational_briefing
        ));
    }

    if needs_project && !project_context.is_empty() {
        analysis_ctx.push_str(&format!(
            "\n=== PROJECT CONTEXT (complete — nothing omitted) ===\n{}\n=== END PROJECT CONTEXT ===\n",
            project_context
        ));
    }

    if needs_schedule {
        analysis_ctx.push_str(&format!(
            "\n=== SCHEDULE (this is the complete list — there are no other events or tasks) ===\nDate: {}\nPlan: {}\nDeadlines: {}\n=== END SCHEDULE ===\n",
            context.date,
            serde_json::to_string(&context.plan_items).unwrap_or_default(),
            serde_json::to_string(&context.upcoming_deadlines).unwrap_or_default(),
        ));
    }

    let analyze_prompt = format!(
        "You are a pre-analysis agent for CADEN, an executive function assistant \
         for someone with ADHD, bipolar disorder, and autism.\n\n\
         STRICT RULE: You may only reference items that appear VERBATIM in the context \
         sections above. Do not invent people, emails, events, tasks, or facts. \
         If something is not listed above, it does not exist — do not mention it.\n\n\
         Analyze the situation and write a brief for the response agent. \
         Do NOT address the user. Do NOT write the final response.\n\n\
         {}\n\n\
         In 3-5 sentences: state the user's actual need, cite only the specific listed \
         items that are relevant, and state the best approach. \
         If the context is sparse, say so — do not fill gaps with assumptions.",
        analysis_ctx
    );

    let analysis = llm_oneshot(&model, &analyze_prompt, &github_pat, &groq_keys).await.unwrap_or_default();

    // Log analyze training example
    if !analysis.trim().is_empty() && should_log_training(&groq_keys, &github_pat) {
        let bg_m = bg_model_name(&model, &groq_keys);
        let _ = crate::training::log_example(&pool, "analyze", None, &analyze_prompt, &analysis, &bg_m).await;
    }

    // ── Call 2.5: Data Report (only when user asks for specific data) ─────────
    // Separate LLM call whose ONLY job is to extract and format exact numbers
    // from the state briefing. The respond model then cites these verbatim.
    let _ = app.emit("caden-phase", if needs_data_report { "pulling data" } else { "responding" });

    let data_report = if needs_data_report && !situational_briefing.is_empty() {
        let data_prompt = format!(
            "You are a data formatter. Your ONLY job is to extract exact numbers and facts \
             from the data below that are relevant to the user's question.\n\n\
             Do NOT interpret. Do NOT advise. Do NOT respond to the user. \
             Do NOT invent values. If a value is not explicitly stated in the data below, \
             write \"not recorded\".\n\n\
             User asked: \"{question}\"\n\n\
             Raw data:\n{briefing}\n\n\
             Output: a short numbered list of key:value pairs, one per line. \
             Include ONLY values directly relevant to the question. \
             Example format:\n\
             1. 5-day avg energy: 7.2/10\n\
             2. 5-day avg mood: 6.8/10\n\
             3. Today's medications: Vyvanse @ 09:30\n\n\
             Numbered list:",
            question = message.replace('"', "'"),
            briefing = situational_briefing,
        );
        let result = llm_oneshot(&model, &data_prompt, &github_pat, &groq_keys).await.unwrap_or_default();
        // Log data_report training example
        if !result.trim().is_empty() && should_log_training(&groq_keys, &github_pat) {
            let bg_m = bg_model_name(&model, &groq_keys);
            let _ = crate::training::log_example(&pool, "data_report", None, &data_prompt, &result, &bg_m).await;
        }
        result
    } else {
        String::new()
    };

    // ── JITAI: should we append a check-in question to this response? ─────────
    // Only fires once per day, only when passive signals show an anomaly worth confirming.
    let jitai_prompt = crate::state_engine::get_jitai_prompt(&pool).await;
    let jitai_instruction = match &jitai_prompt {
        Some(q) => format!(
            "\n\nJITAI INSTRUCTION (mandatory): After your response — naturally, not as a separate section — ask the user this question in your own voice: \"{}\" Make it flow, don't just paste it in.",
            q
        ),
        None => String::new(),
    };

    let _ = app.emit("caden-phase", "responding");

    // ── Call 3: Respond (streaming) ───────────────────────────────────────────
    // Grounding block prepended before the persona so it's the first thing the model reads
    let grounding = "HARD CONSTRAINT: You only know what is explicitly listed in the \
        context sections below. Do not reference any person, email, message, event, \
        task, or commitment that is not listed. If it is not listed, it does not exist.\n\n";

    let final_system = if !analysis.trim().is_empty() {
        let data_block = if !data_report.trim().is_empty() {
            format!(
                "\n\n=== VERIFIED DATA — cite these values exactly as shown, do not paraphrase numbers ===\n{}\n=== END VERIFIED DATA ===",
                data_report.trim()
            )
        } else {
            String::new()
        };
        format!(
            "{}{}\n\n=== SITUATION ANALYSIS ===\n{}\n=== END ANALYSIS ===\
             \n\n=== CURRENT STATE ===\n{}\n=== END CURRENT STATE ==={}{} ",
            grounding,
            system_prompt,
            analysis.trim(),
            situational_briefing,
            data_block,
            jitai_instruction
        )
    } else {
        format!(
            "{}{}\n\n=== CURRENT STATE ===\n{}\n=== END CURRENT STATE ==={}",
            grounding,
            system_prompt,
            situational_briefing,
            jitai_instruction
        )
    };

    let mut messages: Vec<ChatMessage> = vec![ChatMessage {
        role: "system".to_string(),
        content: final_system,
        tool_calls: None,
    }];

    for h in history {
        messages.push(ChatMessage {
            role: h.role,
            content: h.content,
            tool_calls: None,
        });
    }

    messages.push(ChatMessage {
        role: "user".to_string(),
        content: message.clone(),
        tool_calls: None,
    });

    // ── Emit trace before streaming ────────────────────────────────────────
    let trace = TracePayload {
        model: model.clone(),
        intent: intent.to_string(),
        one_line: one_line.to_string(),
        needs_project_context: needs_project,
        needs_schedule_context: needs_schedule,
        classification_raw: classify_raw.trim().to_string(),
        analysis: analysis.trim().to_string(),
        situational_briefing: situational_briefing.clone(),
        project_context: if needs_project { project_context.clone() } else { String::new() },
        date: context.date.clone(),
        plan_items: if needs_schedule { context.plan_items.clone() } else { serde_json::Value::Array(vec![]) },
        upcoming_deadlines: if needs_schedule { context.upcoming_deadlines.clone() } else { serde_json::Value::Array(vec![]) },
    };
    let _ = app.emit("ollama-trace", trace);

    // ── Clone for training data logging (after streaming) ────────────────────
    let app_for_training = app.clone();
    let pool_for_training = pool.clone();
    let message_for_training = message.clone();
    let analysis_for_training = analysis.trim().to_string();
    let situational_for_training = situational_briefing.clone();
    let model_for_training = model.clone();
    let github_pat_for_training = github_pat.clone();

    // ── Background: deterministic per-form extraction ─────────────────────────
    // Each form is its own scoped LLM call. Each emits a visible status chip
    // to the frontend before and after running — nothing is a black box.
    {
        let message_clone = message.clone();
        let model_clone = model.clone();
        let github_pat_clone = github_pat.clone();
        let groq_keys_clone = groq_keys.clone();
        let pool_clone = pool.clone();
        let app_clone = app.clone();
        let now_unix = chrono::Utc::now().timestamp();
        let morning_meds_clone = morning_meds.clone();
        let evening_meds_clone = evening_meds.clone();

        let forms_future = async move {
            let emit_chip = |label: &str, done: bool, skipped: bool, data: Option<String>| {
                let mut payload = serde_json::json!({ "label": label, "done": done });
                if skipped { payload["skipped"] = serde_json::json!(true); }
                if let Some(d) = data { payload["data"] = serde_json::json!(d); }
                let _ = app_clone.emit("caden-logging", payload);
            };

            // ── Form 1: Medication logging (regex — fast, no LLM) ──────────────
            let group_hits = crate::state_engine::parse_med_groups_from_text(
                &message_clone,
                now_unix,
                &morning_meds_clone,
                &evening_meds_clone,
            );
            let med_hits = crate::state_engine::parse_medication_from_text(&message_clone, now_unix);

            let total_meds = group_hits.len() + med_hits.len();
            if total_meds > 0 {
                emit_chip("logging medication", false, false, None);
                let mut med_names = Vec::new();
                for (med_name, dose_time, dose_mg) in group_hits.into_iter().chain(med_hits) {
                    med_names.push(med_name.clone());
                    let _ = crate::state_engine::log_medication(
                        &pool_clone, &med_name, dose_time, dose_mg, None,
                    ).await;
                }
                let data = med_names.join(", ");
                emit_chip("logging medication", true, false, Some(data));
            }

            if message_clone.len() <= 20 {
                return;
            }

            // ── Form 2: Mood / energy / state extraction (LLM) ────────────────
            let has_state_signal = {
                let l = message_clone.to_lowercase();
                let signal_words = [
                    "feel", "feeling", "felt", "mood", "energy", "tired", "exhausted",
                    "anxious", "anxiety", "stressed", "depressed", "depressing", "sad",
                    "happy", "excited", "motivated", "unmotivated", "overwhelmed",
                    "calm", "wired", "crashed", "crash", "racing", "foggy", "focus",
                    "sleep", "slept", "insomnia", "awake", "woke", "nap",
                    "bad day", "good day", "rough", "great", "awful", "numb",
                    "manic", "low", "high", "hyper", "flat",
                ];
                signal_words.iter().any(|w| l.contains(w))
            };

            if has_state_signal {
                emit_chip("logging mood/energy", false, false, None);
                let prompt = crate::state_engine::build_extraction_prompt(&message_clone);
                let mut data_str = None;
                let logged = if let Ok(raw) = llm_oneshot(&model_clone, &prompt, &github_pat_clone, &groq_keys_clone).await {
                    let clean = raw.trim().trim_start_matches("```json").trim_start_matches("```").trim_end_matches("```").trim();
                    if let Ok(ext) = serde_json::from_str::<crate::state_engine::FactorExtraction>(clean) {
                        let _ = crate::state_engine::store_factor_snapshot(&pool_clone, &ext, "passive_nlp").await;
                        let success = ext.state_confidence.unwrap_or(0.0) >= 0.3;
                        if success {
                            let mut parts = Vec::new();
                            if let Some(m) = ext.mood_score { parts.push(format!("mood: {:.1}", m)); }
                            if let Some(e) = ext.energy_level { parts.push(format!("energy: {:.1}", e)); }
                            if let Some(a) = ext.anxiety_level { parts.push(format!("anxiety: {:.1}", a)); }
                            data_str = Some(parts.join(", "));
                            if should_log_training(&groq_keys_clone, &github_pat_clone) {
                                let bg_m = bg_model_name(&model_clone, &groq_keys_clone);
                                let _ = crate::training::log_example(&pool_clone, "mood", None, &prompt, &raw, &bg_m).await;
                            }
                        }
                        success
                    } else { false }
                } else { false };
                emit_chip("logging mood/energy", logged, !logged, data_str);
            }

            // ── Form 3: Goal progress extraction (LLM) ────────────────────────
            if let Some(goals_json) = crate::state_engine::get_active_goals_for_extraction(&pool_clone).await {
                emit_chip("logging goal progress", false, false, None);
                let prompt = crate::state_engine::build_goal_extraction_prompt(&message_clone, &goals_json);
                let mut data_str = None;
                let logged = if let Ok(raw) = llm_oneshot(&model_clone, &prompt, &github_pat_clone, &groq_keys_clone).await {
                    let clean = raw.trim().trim_start_matches("```json").trim_start_matches("```").trim_end_matches("```").trim();
                    if let Ok(result) = serde_json::from_str::<crate::state_engine::GoalExtractionResult>(clean) {
                        if result.confidence >= 0.3 && !result.updates.is_empty() {
                            crate::state_engine::apply_goal_updates(&pool_clone, &result.updates).await;
                            data_str = Some(format!("{} goal{} updated", result.updates.len(), if result.updates.len() != 1 { "s" } else { "" }));
                            if should_log_training(&groq_keys_clone, &github_pat_clone) {
                                let bg_m = bg_model_name(&model_clone, &groq_keys_clone);
                                let _ = crate::training::log_example(&pool_clone, "goal", None, &prompt, &raw, &bg_m).await;
                            }
                            true
                        } else { false }
                    } else { false }
                } else { false };
                emit_chip("logging goal progress", logged, !logged, data_str);
            }
        };

        // Run forms and streaming concurrently. Emit ollama-done only after both
        // finish so chips are guaranteed to arrive before the frontend closes out.
        let (_, stream_result) = tokio::join!(forms_future, stream_messages(app.clone(), messages, model, pool, github_pat));
        let _ = app.emit("ollama-done", ());

        // Capture full response for training data logging
        let full_response = match stream_result {
            Ok(ref r) => r.clone(),
            Err(ref e) => { log::error!("Stream error: {}", e); String::new() }
        };

        // Log response training example — system is analysis+situational ONLY (no persona).
        // We only log when using a cloud model so fine-tune data is high quality.
        if github_pat_for_training.is_some() && !full_response.trim().is_empty() {
            let training_system = format!(
                "{}\n\n=== CURRENT SITUATION ===\n{}",
                analysis_for_training, situational_for_training
            );
            let _ = crate::training::log_example(
                &pool_for_training, "response",
                Some(&training_system),
                &message_for_training,
                &full_response,
                &model_for_training,
            ).await;
            crate::training::check_and_notify(&pool_for_training, &app_for_training).await;
        }

        Ok(())
    }
}


/// Strip raw JSON tool-call blobs that some models leak into their text content.
fn strip_tool_call_json(content: &str) -> String {
    use std::sync::OnceLock;
    static RE: OnceLock<regex::Regex> = OnceLock::new();
    let re = RE.get_or_init(|| regex::Regex::new(r#"\{\s*"name"\s*:.*?\}"#).unwrap());

    let cleaned = re.replace_all(content, "");
    let skip = ["no json response is needed", "as the assistant, i'll", "i'll simply respond"];
    cleaned
        .lines()
        .filter(|line| {
            let l = line.to_lowercase();
            !skip.iter().any(|p| l.contains(p))
        })
        .collect::<Vec<_>>()
        .join("\n")
        .trim()
        .to_string()
}

/// Returns the background model name: Groq when keys are available, otherwise the active model.
fn bg_model_name(model: &str, groq_keys: &[String]) -> String {
    if groq_keys.iter().any(|k| !k.is_empty()) {
        GROQ_BACKGROUND_MODEL.to_string()
    } else {
        model.to_string()
    }
}

/// Returns true if any cloud API is configured (Groq keys or GitHub PAT).
/// Used to gate training data logging — we only want high-quality cloud outputs.
fn should_log_training(groq_keys: &[String], github_pat: &Option<String>) -> bool {
    groq_keys.iter().any(|k| !k.is_empty()) || github_pat.is_some()
}

/// Stream a pre-built message list to the UI.
/// Includes Ollama native tool calling — if the model invokes a tool, CADEN executes it
/// and feeds the result back for a final streaming response.
/// Emits: "ollama-token", "ollama-done", "ollama-error"
async fn stream_messages(
    app: AppHandle,
    messages: Vec<ChatMessage>,
    model: String,
    pool: sqlx::SqlitePool,
    github_pat: Option<String>,
) -> Result<String> {
    let client = Client::builder()
        .timeout(std::time::Duration::from_secs(300))
        .build()?;

    // GitHub Models: skip Ollama tool-call dance, go straight to SSE stream.
    if let Some(ref pat) = github_pat {
        return github_do_stream(&app, &client, messages, &model, pat).await;
    }

    let tools = caden_tools();
    let mut messages = messages;

    // Skip tools only for trivially short messages (greetings, "yeah", "thanks")
    // where tool invocation would just waste a round-trip. Everything else gets
    // tools — let the LLM decide when to use them.
    let last_user_len = messages.iter().rev()
        .find(|m| m.role == "user")
        .map(|m| m.content.len())
        .unwrap_or(0);
    if last_user_len < 12 {
        return do_stream(&app, &client, messages, &model).await;
    }

    // Up to 6 tool-call rounds for multi-step action chains:
    // e.g. list_projects → list_files → read_file → search_web → add_task → replan
    for _round in 0..6 {
        let req = OllamaChatRequest {
            model: model.clone(),
            messages: messages.clone(),
            stream: false, // non-streaming for tool-call round so we can inspect full response
            think: false,
            keep_alive: -1,
            options: OllamaOptions { num_gpu: 99 },
            tools: Some(tools.clone()),
        };

        let resp = client
            .post(format!("{}/api/chat", OLLAMA_BASE))
            .json(&req)
            .send()
            .await
            .map_err(|e| anyhow!("Failed to reach Ollama: {}", e))?;

        if !resp.status().is_success() {
            break; // fall through to streaming without tools
        }

        let body: serde_json::Value = resp.json().await.unwrap_or_default();
        let msg = &body["message"];
        let tool_calls = msg["tool_calls"].as_array();

        if tool_calls.map(|tc| !tc.is_empty()).unwrap_or(false) {
            // Model wants to call tools — collect all calls, execute, inject results
            let tc_list = tool_calls.unwrap();

            // Append the assistant's tool-call message
            messages.push(ChatMessage {
                role: "assistant".to_string(),
                content: msg["content"].as_str().unwrap_or("").to_string(),
                tool_calls: Some(tc_list.iter().filter_map(|tc| {
                    let name = tc["function"]["name"].as_str()?;
                    let args = tc["function"]["arguments"].clone();
                    Some(ToolCall {
                        function: ToolCallFunction {
                            name: name.to_string(),
                            arguments: args,
                        },
                    })
                }).collect()),
            });

            // Execute each tool and append results
            for tc in tc_list {
                let name = tc["function"]["name"].as_str().unwrap_or("");
                let args = &tc["function"]["arguments"];
                let result = execute_tool(name, args, &pool).await;
                let _ = app.emit("ollama-tool-call", serde_json::json!({
                    "tool": name,
                    "args": args,
                    "result": result,
                }));
                messages.push(ChatMessage {
                    role: "tool".to_string(),
                    content: result,
                    tool_calls: None,
                });
            }
            // Continue the loop — let the model respond with the tool results in context
        } else {
            // No tool calls — model gave a regular response or an empty one.
            // If it gave real content, stream it now from that response.
            let content = msg["content"].as_str().unwrap_or("");
            if !content.is_empty() {
                let clean = strip_tool_call_json(content);
                if !clean.is_empty() {
                    let emitted = emit_content_as_tokens(&app, &clean);
                    return Ok(emitted);
                }
            }
            break; // empty response — fall through to final streaming attempt
        }
    }

    // Final streaming pass — no tools, just get the response out
    do_stream(&app, &client, messages, &model).await
}

/// Emit a pre-collected string as individual token events (used after tool-call round).
/// Returns the full content that was emitted (for training data capture).
fn emit_content_as_tokens(app: &AppHandle, content: &str) -> String {
    // Split into ~50-char chunks to simulate streaming feel
    let mut start = 0;
    while start < content.len() {
        let end = (start + 50).min(content.len());
        // Clamp to char boundary
        let end = content.char_indices()
            .map(|(i, _)| i)
            .filter(|&i| i >= end)
            .next()
            .unwrap_or(content.len());
        let chunk = &content[start..end];
        if !chunk.is_empty() {
            let _ = app.emit("ollama-token", chunk);
        }
        if end == start { break; }
        start = end;
    }
    content.to_string()
}

/// Actually stream a response from Ollama without tools.
/// Returns the full non-thinking response text for training data capture.
async fn do_stream(
    app: &AppHandle,
    client: &Client,
    messages: Vec<ChatMessage>,
    model: &str,
) -> Result<String> {
    let req = OllamaChatRequest {
        model: model.to_string(),
        messages: messages.clone(),
        stream: true,
        think: true,
        keep_alive: -1,
        options: OllamaOptions { num_gpu: 99 },
        tools: None,
    };

    let response = client
        .post(format!("{}/api/chat", OLLAMA_BASE))
        .json(&req)
        .send()
        .await
        .map_err(|e| anyhow!("Failed to reach Ollama: {}", e))?;

    let response = if !response.status().is_success() {
        let req_no_think = OllamaChatRequest {
            model: model.to_string(),
            messages: messages.clone(),
            stream: true,
            think: false,
            keep_alive: -1,
            options: OllamaOptions { num_gpu: 99 },
            tools: None,
        };
        let retry = client
            .post(format!("{}/api/chat", OLLAMA_BASE))
            .json(&req_no_think)
            .send()
            .await
            .map_err(|e| anyhow!("Failed to reach Ollama: {}", e))?;
        if !retry.status().is_success() {
            let _ = app.emit("ollama-error", format!("Ollama error ({}). Is the model loaded?", retry.status()));
            return Ok(String::new());
        }
        retry
    } else {
        response
    };

    let mut stream = response.bytes_stream();
    let mut in_think = false;
    let mut full_response = String::new();

    while let Some(chunk) = stream.next().await {
        match chunk {
            Ok(bytes) => {
                let text = String::from_utf8_lossy(&bytes);
                for line in text.lines() {
                    let line = line.trim();
                    if line.is_empty() { continue; }
                    if let Ok(parsed) = serde_json::from_str::<OllamaChatChunk>(line) {
                        if let Some(msg) = &parsed.message {
                            if !msg.content.is_empty() {
                                let mut content = msg.content.as_str();
                                loop {
                                    if in_think {
                                        if let Some(end) = content.find("</think>") {
                                            let think_part = &content[..end];
                                            if !think_part.is_empty() {
                                                let _ = app.emit("ollama-think-token", think_part);
                                            }
                                            in_think = false;
                                            content = &content[end + 8..];
                                        } else {
                                            let _ = app.emit("ollama-think-token", content);
                                            break;
                                        }
                                    } else if let Some(start) = content.find("<think>") {
                                        let normal_part = &content[..start];
                                        if !normal_part.is_empty() {
                                            let _ = app.emit("ollama-token", normal_part);
                                            full_response.push_str(normal_part);
                                        }
                                        in_think = true;
                                        content = &content[start + 7..];
                                    } else {
                                        if !content.is_empty() {
                                            let _ = app.emit("ollama-token", content);
                                            full_response.push_str(content);
                                        }
                                        break;
                                    }
                                }
                            }
                        }
                        if parsed.done == Some(true) {
                            return Ok(full_response);
                        }
                    }
                }
            }
            Err(e) => {
                let _ = app.emit("ollama-error", format!("Stream error: {}", e));
                return Ok(full_response);
            }
        }
    }

    Ok(full_response)
}

/// Execute a tool by name and return a result string to inject into the conversation.
async fn execute_tool(name: &str, args: &serde_json::Value, pool: &sqlx::SqlitePool) -> String {
    match name {
        "add_task" => {
            let title = match args["title"].as_str() {
                Some(t) if !t.is_empty() => t.to_string(),
                _ => return "Error: task title is required.".to_string(),
            };
            let due_date = args["due_date"].as_str()
                .unwrap_or(&chrono::Local::now().format("%Y-%m-%d").to_string())
                .to_string();
            let task_type = args["task_type"].as_str().unwrap_or("general").to_string();
            let est_minutes = args["estimated_minutes"].as_i64().unwrap_or(30);

            let id = crate::db::ops::generate_id();
            let now = chrono::Utc::now().to_rfc3339();
            let notes = format!("type: {}, est: {} min", task_type, est_minutes);

            // Insert locally using the actual tasks_cache schema
            let result = sqlx::query(
                "INSERT INTO tasks_cache (id, title, source, due_date, completed, notes, fetched_at)
                 VALUES (?, ?, 'tasks', ?, 0, ?, ?)",
            )
            .bind(&id)
            .bind(&title)
            .bind(&due_date)
            .bind(&notes)
            .bind(&now)
            .execute(pool)
            .await;

            if let Err(e) = result {
                return format!("Failed to add task locally: {}", e);
            }

            let mut status = format!("Task added: \"{}\" (due {}, {})", title, due_date, notes);

            // Sync to Google Tasks if connected (best-effort — don't block on failure)
            if let Ok(access_token) = crate::google::get_fresh_token_from_db(pool).await {
                let due_rfc3339 = format!("{}T00:00:00Z", due_date);
                match crate::google::create_task(
                    &access_token,
                    "@default",
                    &title,
                    Some(&due_rfc3339),
                    Some(&notes),
                )
                .await
                {
                    Ok(google_task_id) => {
                        // Link local record to Google Task
                        let _ = sqlx::query(
                            "UPDATE tasks_cache SET google_task_id = ? WHERE id = ?",
                        )
                        .bind(&google_task_id)
                        .bind(&id)
                        .execute(pool)
                        .await;
                        status.push_str(" — synced to Google Tasks");
                    }
                    Err(e) => {
                        log::warn!("Google Tasks sync failed: {}", e);
                        status.push_str(" — local only (Google sync failed)");
                    }
                }
            } else {
                status.push_str(" — local only (Google not connected)");
            }

            // Trigger a replan so the new task gets a time slot in today's schedule
            let _ = crate::planner::reschedule_remaining_today(pool, None).await;
            status.push_str(". Schedule updated.");

            status
        }

        "get_today_tasks" => {
            match crate::db::ops::get_today_plan(pool).await {
                Ok(items) => {
                    if items.is_empty() {
                        "No tasks scheduled for today.".to_string()
                    } else {
                        let lines: Vec<String> = items.iter().map(|item| {
                            format!("- {}{}",
                                item.title,
                                if item.completed { " ✓" } else { "" }
                            )
                        }).collect();
                        format!("Today's tasks:\n{}", lines.join("\n"))
                    }
                }
                Err(e) => format!("Failed to get tasks: {}", e),
            }
        }

        "search_web" => {
            let query = match args["query"].as_str() {
                Some(q) if !q.is_empty() => q.to_string(),
                _ => return "Error: search query is required.".to_string(),
            };
            crate::search::search_and_store(pool, &query).await
        }

        "recall_web" => {
            let query = match args["query"].as_str() {
                Some(q) if !q.is_empty() => q.to_string(),
                _ => return "Error: recall query is required.".to_string(),
            };
            crate::search::recall_similar(pool, &query).await
        }

        "list_projects" => {
            crate::search::list_projects_with_folders(pool).await
        }

        "list_project_files" => {
            let project = match args["project"].as_str() {
                Some(p) if !p.is_empty() => p.to_string(),
                _ => return "Error: project name or ID is required.".to_string(),
            };
            crate::search::list_project_files(pool, &project).await
        }

        "read_project_file" => {
            let project = match args["project"].as_str() {
                Some(p) if !p.is_empty() => p.to_string(),
                _ => return "Error: project name or ID is required.".to_string(),
            };
            let path = match args["path"].as_str() {
                Some(p) if !p.is_empty() => p.to_string(),
                _ => return "Error: file path is required.".to_string(),
            };
            crate::search::read_project_file(pool, &project, &path).await
        }

        "get_project_entries" => {
            let project = match args["project"].as_str() {
                Some(p) if !p.is_empty() => p.to_string(),
                _ => return "Error: project name or ID is required.".to_string(),
            };
            crate::search::get_project_entries(pool, &project).await
        }

        "search_memory" => {
            let query = match args["query"].as_str() {
                Some(q) if !q.is_empty() => q.to_string(),
                _ => return "Error: search query is required.".to_string(),
            };
            crate::search::search_memory(pool, &query).await
        }

        _ => format!("Unknown tool: {}", name),
    }
}


/// Make a single non-streaming chat call and return the full response text.
/// Used by the calendar agent for structured JSON extraction.
pub async fn chat_oneshot(model: &str, prompt: &str) -> Result<String> {
    let client = Client::builder()
        .timeout(std::time::Duration::from_secs(60))
        .build()?;

    let req = OllamaChatRequest {
        model: model.to_string(),
        messages: vec![ChatMessage {
            role: "user".to_string(),
            content: prompt.to_string(),
            tool_calls: None,
        }],
        stream: false,
        think: false,
        keep_alive: -1,
        options: OllamaOptions { num_gpu: 99 },
        tools: None,
    };

    let resp = client
        .post(format!("{}/api/chat", OLLAMA_BASE))
        .json(&req)
        .send()
        .await
        .map_err(|e| anyhow!("Ollama unreachable: {}", e))?;

    if !resp.status().is_success() {
        return Err(anyhow!("Ollama error: {}", resp.status()));
    }

    // Non-streaming: single JSON object with message.content
    let body: serde_json::Value = resp.json().await?;
    Ok(body["message"]["content"]
        .as_str()
        .unwrap_or("")
        .to_string())
}

/// Embed text using nomic-embed-text via Ollama.
/// Returns a 768-dimensional f32 vector.
pub async fn embed(text: &str) -> Result<Vec<f32>> {
    let client = Client::builder()
        .timeout(std::time::Duration::from_secs(30))
        .build()?;

    let resp = client
        .post(format!("{}/api/embed", OLLAMA_BASE))
        .json(&serde_json::json!({
            "model": "nomic-embed-text",
            "input": text
        }))
        .send()
        .await
        .map_err(|e| anyhow!("Ollama unreachable for embeddings: {}", e))?;

    if !resp.status().is_success() {
        return Err(anyhow!("Embedding request failed: {}", resp.status()));
    }

    let body: serde_json::Value = resp.json().await?;
    let vec = body["embeddings"][0]
        .as_array()
        .ok_or_else(|| anyhow!("No embedding in Ollama response"))?
        .iter()
        .map(|v| v.as_f64().unwrap_or(0.0) as f32)
        .collect();

    Ok(vec)
}

// ── GitHub Models (OpenAI-compatible API) ───────────────────────────────────

/// Multi-message LLM call for the AppBuilder agent loop.
/// Priority: Groq (70B, fast) → GitHub Models → Ollama.
/// Takes a full messages array [{role, content}] for multi-turn conversation.
pub async fn llm_chat_messages(
    messages: &[serde_json::Value],
    github_pat: &Option<String>,
    groq_keys: &[String],
) -> Result<String> {
    let active_groq: Vec<&String> = groq_keys.iter().filter(|k| !k.is_empty()).collect();
    if !active_groq.is_empty() {
        let idx = GROQ_KEY_IDX.fetch_add(1, std::sync::atomic::Ordering::Relaxed) % active_groq.len();
        match groq_chat_messages(active_groq[idx], messages).await {
            Ok(content) => return Ok(content),
            Err(e) => {
                // Fall through to GitHub on any Groq failure (429, timeout, 5xx, network)
                log::warn!("Groq failed ({}), falling back to GitHub Models", e);
                if let Some(pat) = github_pat {
                    return github_chat_messages(pat, messages).await;
                }
                return Err(e);
            }
        }
    }
    if let Some(pat) = github_pat {
        return github_chat_messages(pat, messages).await;
    }
    Err(anyhow!("No LLM provider configured. Add Groq API keys or a GitHub PAT in Settings."))
}

/// Multi-message Groq call (OpenAI-compatible).
async fn groq_chat_messages(key: &str, messages: &[serde_json::Value]) -> Result<String> {
    let client = Client::builder()
        .timeout(std::time::Duration::from_secs(120))
        .build()?;

    let body = serde_json::json!({
        "model": GROQ_BACKGROUND_MODEL,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 4096,
        "stream": false
    });

    let resp = client
        .post(format!("{}/chat/completions", GROQ_BASE))
        .header("Authorization", format!("Bearer {}", key))
        .header("Content-Type", "application/json")
        .json(&body)
        .send()
        .await
        .map_err(|e| anyhow!("Groq unreachable: {}", e))?;

    if resp.status() == 429 {
        // Rate limited — try GitHub fallback handled by caller
        return Err(anyhow!("Groq rate limited (429)"));
    }
    if !resp.status().is_success() {
        return Err(anyhow!("Groq error: {}", resp.status()));
    }

    let body: serde_json::Value = resp.json().await?;
    Ok(body["choices"][0]["message"]["content"]
        .as_str()
        .unwrap_or("")
        .to_string())
}

/// Multi-message GitHub Models call (OpenAI-compatible).
async fn github_chat_messages(pat: &str, messages: &[serde_json::Value]) -> Result<String> {
    let client = Client::builder()
        .timeout(std::time::Duration::from_secs(120))
        .build()?;

    let body = serde_json::json!({
        "model": "meta/llama-3.3-70b-instruct",
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 4096,
        "stream": false
    });

    let resp = client
        .post(format!("{}/chat/completions", GITHUB_MODELS_BASE))
        .header("Authorization", format!("Bearer {}", pat))
        .header("Content-Type", "application/json")
        .json(&body)
        .send()
        .await
        .map_err(|e| anyhow!("GitHub Models unreachable: {}", e))?;

    if !resp.status().is_success() {
        return Err(anyhow!("GitHub Models error: {}", resp.status()));
    }

    let body: serde_json::Value = resp.json().await?;
    Ok(body["choices"][0]["message"]["content"]
        .as_str()
        .unwrap_or("")
        .to_string())
}

/// Route a background one-shot prompt.
/// Priority: Groq (fast, free, reliable 70B) → GitHub Models PAT → Ollama local.
async fn llm_oneshot(model: &str, prompt: &str, github_pat: &Option<String>, groq_keys: &[String]) -> Result<String> {
    // Prefer Groq for all background/structured calls — fast and doesn't burn stream quota.
    let active_groq: Vec<&String> = groq_keys.iter().filter(|k| !k.is_empty()).collect();
    if !active_groq.is_empty() {
        let idx = GROQ_KEY_IDX.fetch_add(1, std::sync::atomic::Ordering::Relaxed) % active_groq.len();
        return groq_oneshot(active_groq[idx], prompt).await;
    }
    // Fallback: GitHub Models PAT if present
    if let Some(pat) = github_pat {
        return github_chat_oneshot(pat, model, prompt).await;
    }
    // Last resort: local Ollama
    chat_oneshot(model, prompt).await
}

/// Single non-streaming call to the Groq API (OpenAI-compatible).
/// Always uses GROQ_BACKGROUND_MODEL — Groq's strengths are speed + JSON reliability.
async fn groq_oneshot(key: &str, prompt: &str) -> Result<String> {
    let client = Client::builder()
        .timeout(std::time::Duration::from_secs(30))
        .build()?;

    let body = serde_json::json!({
        "model": GROQ_BACKGROUND_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": false
    });

    let resp = client
        .post(format!("{}/chat/completions", GROQ_BASE))
        .header("Authorization", format!("Bearer {}", key))
        .header("Content-Type", "application/json")
        .json(&body)
        .send()
        .await
        .map_err(|e| anyhow!("Groq unreachable: {}", e))?;

    if !resp.status().is_success() {
        return Err(anyhow!("Groq error: {}", resp.status()));
    }

    let body: serde_json::Value = resp.json().await?;
    Ok(body["choices"][0]["message"]["content"]
        .as_str()
        .unwrap_or("")
        .to_string())
}

/// Single non-streaming call to the GitHub Models OpenAI-compatible API.
pub async fn github_chat_oneshot(pat: &str, model: &str, prompt: &str) -> Result<String> {
    let client = Client::builder()
        .timeout(std::time::Duration::from_secs(60))
        .build()?;

    let body = serde_json::json!({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": false
    });

    let resp = client
        .post(format!("{}/chat/completions", GITHUB_MODELS_BASE))
        .header("Authorization", format!("Bearer {}", pat))
        .header("Content-Type", "application/json")
        .json(&body)
        .send()
        .await
        .map_err(|e| anyhow!("GitHub Models unreachable: {}", e))?;

    if !resp.status().is_success() {
        return Err(anyhow!("GitHub Models error: {}", resp.status()));
    }

    let body: serde_json::Value = resp.json().await?;
    Ok(body["choices"][0]["message"]["content"]
        .as_str()
        .unwrap_or("")
        .to_string())
}

/// Stream a response from the GitHub Models API (OpenAI SSE format).
async fn github_do_stream(
    app: &AppHandle,
    client: &Client,
    messages: Vec<ChatMessage>,
    model: &str,
    pat: &str,
) -> Result<String> {
    let msgs: Vec<serde_json::Value> = messages
        .iter()
        .map(|m| serde_json::json!({"role": m.role, "content": m.content}))
        .collect();

    let body = serde_json::json!({
        "model": model,
        "messages": msgs,
        "stream": true
    });

    let response = client
        .post(format!("{}/chat/completions", GITHUB_MODELS_BASE))
        .header("Authorization", format!("Bearer {}", pat))
        .header("Content-Type", "application/json")
        .json(&body)
        .send()
        .await
        .map_err(|e| anyhow!("Failed to reach GitHub Models: {}", e))?;

    if !response.status().is_success() {
        let status = response.status();
        let err_body = response.text().await.unwrap_or_default();
        let _ = app.emit("ollama-error", format!("GitHub Models error ({}): {}", status, err_body));
        return Ok(String::new());
    }

    let mut stream = response.bytes_stream();
    // Buffer incomplete SSE lines across HTTP chunks — a single chunk may split
    // a "data: {...}" line mid-JSON, causing silent parse failures and dropped tokens.
    let mut buf = String::new();
    let mut full_response = String::new();
    while let Some(chunk) = stream.next().await {
        match chunk {
            Ok(bytes) => {
                buf.push_str(&String::from_utf8_lossy(&bytes));
                // Process only complete lines; leave any trailing partial line in buf.
                while let Some(newline_pos) = buf.find('\n') {
                    let line = buf[..newline_pos].trim().to_string();
                    buf = buf[newline_pos + 1..].to_string();
                    if line.is_empty() || line == "data: [DONE]" { continue; }
                    let json_str = line.strip_prefix("data: ").unwrap_or(&line);
                    if let Ok(parsed) = serde_json::from_str::<serde_json::Value>(json_str) {
                        if let Some(content) = parsed["choices"][0]["delta"]["content"].as_str() {
                            if !content.is_empty() {
                                let _ = app.emit("ollama-token", content);
                                full_response.push_str(content);
                            }
                        }
                    }
                }
            }
            Err(e) => {
                let _ = app.emit("ollama-error", format!("Stream error: {}", e));
                return Ok(full_response);
            }
        }
    }

    Ok(full_response)
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
