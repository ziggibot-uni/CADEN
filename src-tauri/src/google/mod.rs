use anyhow::{anyhow, Result};
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use reqwest::Client;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use tauri::AppHandle;
use tauri_plugin_opener::OpenerExt;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::net::TcpListener;

const REDIRECT_PORT: u16 = 42813;
const REDIRECT_URI: &str = "http://localhost:42813/callback";

const SCOPES: &[&str] = &[
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/tasks",
];

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GoogleTokens {
    pub access_token: String,
    pub refresh_token: Option<String>,
    pub expires_at: i64,
}

#[derive(Debug, Serialize, Deserialize)]
struct TokenResponse {
    access_token: String,
    refresh_token: Option<String>,
    expires_in: i64,
    #[allow(dead_code)]
    token_type: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CalendarEvent {
    pub id: String,
    pub title: String,
    pub start_time: String,
    pub end_time: String,
    pub all_day: bool,
    pub calendar_name: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GoogleTask {
    pub id: String,
    pub title: String,
    pub due_date: Option<String>,
    pub completed: bool,
    pub notes: Option<String>,
    pub list_name: String,
}

// ─── OAuth flow ───────────────────────────────────────────────────────────────

pub async fn start_oauth(
    app: &AppHandle,
    client_id: &str,
    client_secret: &str,
) -> Result<GoogleTokens> {
    let verifier = generate_code_verifier();
    let challenge = generate_code_challenge(&verifier);

    let scope = SCOPES.join(" ");
    let auth_url = format!(
        "https://accounts.google.com/o/oauth2/v2/auth\
         ?client_id={}&redirect_uri={}&response_type=code\
         &scope={}&code_challenge={}&code_challenge_method=S256\
         &access_type=offline&prompt=consent",
        urlencoding::encode(client_id),
        urlencoding::encode(REDIRECT_URI),
        urlencoding::encode(&scope),
        challenge,
    );

    app.opener()
        .open_url(&auth_url, None::<&str>)
        .map_err(|e| anyhow!("Failed to open browser: {}", e))?;

    let code = await_oauth_callback().await?;
    exchange_code(&code, &verifier, client_id, client_secret).await
}

async fn await_oauth_callback() -> Result<String> {
    let listener = TcpListener::bind(format!("127.0.0.1:{}", REDIRECT_PORT)).await?;
    let (stream, _) = listener.accept().await?;
    let (read_half, mut write_half) = stream.into_split();
    let mut reader = BufReader::new(read_half);
    let mut request_line = String::new();
    reader.read_line(&mut request_line).await?;

    // Parse: "GET /callback?code=xxx HTTP/1.1"
    let code = request_line
        .split_whitespace()
        .nth(1)
        .and_then(|path| {
            path.split('?')
                .nth(1)?
                .split('&')
                .find(|p| p.starts_with("code="))
                .map(|p| p.trim_start_matches("code=").to_string())
        })
        .ok_or_else(|| anyhow!("No code in OAuth callback"))?;

    let response = b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n\
        <html><body style='font-family:monospace;background:#0f0f0f;color:#c8c8c8;\
        display:flex;align-items:center;justify-content:center;height:100vh'>\
        <div>Connected. You can close this tab.</div></body></html>";
    write_half.write_all(response).await?;

    Ok(code)
}

async fn exchange_code(
    code: &str,
    verifier: &str,
    client_id: &str,
    client_secret: &str,
) -> Result<GoogleTokens> {
    let client = Client::new();
    let params = [
        ("code", code),
        ("client_id", client_id),
        ("client_secret", client_secret),
        ("redirect_uri", REDIRECT_URI),
        ("grant_type", "authorization_code"),
        ("code_verifier", verifier),
    ];

    let resp = client
        .post("https://oauth2.googleapis.com/token")
        .form(&params)
        .send()
        .await?;

    if !resp.status().is_success() {
        let err = resp.text().await.unwrap_or_default();
        return Err(anyhow!("Token exchange failed: {}", err));
    }

    let token_resp: TokenResponse = resp.json().await?;
    let expires_at = chrono::Utc::now().timestamp() + token_resp.expires_in;

    Ok(GoogleTokens {
        access_token: token_resp.access_token,
        refresh_token: token_resp.refresh_token,
        expires_at,
    })
}

pub async fn refresh_access_token(
    refresh_token: &str,
    client_id: &str,
    client_secret: &str,
) -> Result<GoogleTokens> {
    let client = Client::new();
    let params = [
        ("refresh_token", refresh_token),
        ("client_id", client_id),
        ("client_secret", client_secret),
        ("grant_type", "refresh_token"),
    ];

    let resp = client
        .post("https://oauth2.googleapis.com/token")
        .form(&params)
        .send()
        .await?;

    let token_resp: TokenResponse = resp.json().await?;
    let expires_at = chrono::Utc::now().timestamp() + token_resp.expires_in;

    Ok(GoogleTokens {
        access_token: token_resp.access_token,
        refresh_token: Some(refresh_token.to_string()),
        expires_at,
    })
}

// ─── Calendar API ─────────────────────────────────────────────────────────────

pub async fn fetch_calendar_events(access_token: &str) -> Result<Vec<CalendarEvent>> {
    let client = Client::new();

    let cals_resp = client
        .get("https://www.googleapis.com/calendar/v3/users/me/calendarList")
        .bearer_auth(access_token)
        .query(&[("maxResults", "20")])
        .send()
        .await?
        .json::<serde_json::Value>()
        .await?;

    let calendars = cals_resp["items"].as_array().cloned().unwrap_or_default();
    let now = chrono::Utc::now().to_rfc3339();
    let week = (chrono::Utc::now() + chrono::Duration::days(8)).to_rfc3339();

    let mut events: Vec<CalendarEvent> = Vec::new();

    for cal in &calendars {
        let cal_id = cal["id"].as_str().unwrap_or_default();
        let cal_name = cal["summary"].as_str().unwrap_or("Calendar").to_string();

        let resp = client
            .get(format!(
                "https://www.googleapis.com/calendar/v3/calendars/{}/events",
                urlencoding::encode(cal_id)
            ))
            .bearer_auth(access_token)
            .query(&[
                ("timeMin", now.as_str()),
                ("timeMax", week.as_str()),
                ("singleEvents", "true"),
                ("orderBy", "startTime"),
                ("maxResults", "50"),
            ])
            .send()
            .await?
            .json::<serde_json::Value>()
            .await?;

        if let Some(items) = resp["items"].as_array() {
            for item in items {
                let id = item["id"].as_str().unwrap_or_default().to_string();
                let title = item["summary"].as_str().unwrap_or("(no title)").to_string();
                let all_day = item["start"]["date"].is_string();

                let start_time = if all_day {
                    format!(
                        "{}T00:00:00Z",
                        item["start"]["date"].as_str().unwrap_or_default()
                    )
                } else {
                    item["start"]["dateTime"]
                        .as_str()
                        .unwrap_or_default()
                        .to_string()
                };
                let end_time = if all_day {
                    format!(
                        "{}T00:00:00Z",
                        item["end"]["date"].as_str().unwrap_or_default()
                    )
                } else {
                    item["end"]["dateTime"]
                        .as_str()
                        .unwrap_or_default()
                        .to_string()
                };

                events.push(CalendarEvent {
                    id,
                    title,
                    start_time,
                    end_time,
                    all_day,
                    calendar_name: cal_name.clone(),
                });
            }
        }
    }

    Ok(events)
}

// ─── Tasks API ────────────────────────────────────────────────────────────────

pub async fn fetch_tasks(access_token: &str) -> Result<Vec<GoogleTask>> {
    let client = Client::new();

    let lists_resp = client
        .get("https://www.googleapis.com/tasks/v1/users/@me/lists")
        .bearer_auth(access_token)
        .send()
        .await?
        .json::<serde_json::Value>()
        .await?;

    let lists = lists_resp["items"].as_array().cloned().unwrap_or_default();
    let mut tasks: Vec<GoogleTask> = Vec::new();

    for list in &lists {
        let list_id = list["id"].as_str().unwrap_or_default();
        let list_name = list["title"].as_str().unwrap_or("Tasks").to_string();

        let resp = client
            .get(format!(
                "https://www.googleapis.com/tasks/v1/lists/{}/tasks",
                urlencoding::encode(list_id)
            ))
            .bearer_auth(access_token)
            .query(&[("showCompleted", "false"), ("maxResults", "100")])
            .send()
            .await?
            .json::<serde_json::Value>()
            .await?;

        if let Some(items) = resp["items"].as_array() {
            for item in items {
                tasks.push(GoogleTask {
                    id: item["id"].as_str().unwrap_or_default().to_string(),
                    title: item["title"].as_str().unwrap_or("").to_string(),
                    due_date: item["due"].as_str().map(|s| s.to_string()),
                    completed: item["status"].as_str() == Some("completed"),
                    notes: item["notes"].as_str().map(|s| s.to_string()),
                    list_name: list_name.clone(),
                });
            }
        }
    }

    Ok(tasks)
}

// ─── Calendar write API ───────────────────────────────────────────────────────

pub async fn list_calendars(access_token: &str) -> Result<Vec<(String, String)>> {
    let client = Client::new();
    let resp = client
        .get("https://www.googleapis.com/calendar/v3/users/me/calendarList")
        .bearer_auth(access_token)
        .query(&[("maxResults", "10")])
        .send()
        .await?
        .json::<serde_json::Value>()
        .await?;

    let items = resp["items"].as_array().cloned().unwrap_or_default();
    Ok(items
        .into_iter()
        .map(|c| {
            let id = c["id"].as_str().unwrap_or("primary").to_string();
            let name = c["summary"].as_str().unwrap_or("Calendar").to_string();
            (id, name)
        })
        .collect())
}

pub async fn create_calendar_event(
    access_token: &str,
    calendar_id: &str,
    title: &str,
    start_iso: &str,
    end_iso: &str,
    description: Option<&str>,
) -> Result<String> {
    let client = Client::new();
    let mut body = serde_json::json!({
        "summary": title,
        "start": { "dateTime": start_iso },
        "end": { "dateTime": end_iso },
    });
    if let Some(desc) = description {
        body["description"] = serde_json::Value::String(desc.to_string());
    }

    let resp = client
        .post(format!(
            "https://www.googleapis.com/calendar/v3/calendars/{}/events",
            urlencoding::encode(calendar_id)
        ))
        .bearer_auth(access_token)
        .json(&body)
        .send()
        .await?;

    if !resp.status().is_success() {
        let err = resp.text().await.unwrap_or_default();
        return Err(anyhow!("Create event failed: {}", err));
    }

    let result: serde_json::Value = resp.json().await?;
    Ok(result["id"].as_str().unwrap_or("").to_string())
}

pub async fn delete_calendar_event(
    access_token: &str,
    calendar_id: &str,
    event_id: &str,
) -> Result<()> {
    let client = Client::new();
    let resp = client
        .delete(format!(
            "https://www.googleapis.com/calendar/v3/calendars/{}/events/{}",
            urlencoding::encode(calendar_id),
            urlencoding::encode(event_id)
        ))
        .bearer_auth(access_token)
        .send()
        .await?;

    if !resp.status().is_success() && resp.status().as_u16() != 204 {
        let err = resp.text().await.unwrap_or_default();
        return Err(anyhow!("Delete event failed: {}", err));
    }
    Ok(())
}

// ─── Tasks write API ──────────────────────────────────────────────────────────

pub async fn get_task_lists(access_token: &str) -> Result<Vec<(String, String)>> {
    let client = Client::new();
    let resp = client
        .get("https://www.googleapis.com/tasks/v1/users/@me/lists")
        .bearer_auth(access_token)
        .send()
        .await?
        .json::<serde_json::Value>()
        .await?;

    let items = resp["items"].as_array().cloned().unwrap_or_default();
    Ok(items
        .into_iter()
        .map(|l| {
            let id = l["id"].as_str().unwrap_or("@default").to_string();
            let name = l["title"].as_str().unwrap_or("Tasks").to_string();
            (id, name)
        })
        .collect())
}

pub async fn create_task(
    access_token: &str,
    list_id: &str,
    title: &str,
    due_rfc3339: Option<&str>,
    notes: Option<&str>,
) -> Result<String> {
    let client = Client::new();
    let mut body = serde_json::json!({ "title": title });
    if let Some(due) = due_rfc3339 {
        body["due"] = serde_json::Value::String(due.to_string());
    }
    if let Some(n) = notes {
        body["notes"] = serde_json::Value::String(n.to_string());
    }

    let resp = client
        .post(format!(
            "https://www.googleapis.com/tasks/v1/lists/{}/tasks",
            urlencoding::encode(list_id)
        ))
        .bearer_auth(access_token)
        .json(&body)
        .send()
        .await?;

    if !resp.status().is_success() {
        let err = resp.text().await.unwrap_or_default();
        return Err(anyhow!("Create task failed: {}", err));
    }

    let result: serde_json::Value = resp.json().await?;
    Ok(result["id"].as_str().unwrap_or("").to_string())
}

// ─── PKCE helpers ─────────────────────────────────────────────────────────────

fn generate_code_verifier() -> String {
    use rand::Rng;
    let bytes: Vec<u8> = (0..32).map(|_| rand::thread_rng().gen::<u8>()).collect();
    URL_SAFE_NO_PAD.encode(&bytes)
}

fn generate_code_challenge(verifier: &str) -> String {
    let hash = Sha256::digest(verifier.as_bytes());
    URL_SAFE_NO_PAD.encode(hash.as_slice())
}

// Suppress unused import warning for HashMap
#[allow(unused_imports)]
use HashMap as _HashMap;
