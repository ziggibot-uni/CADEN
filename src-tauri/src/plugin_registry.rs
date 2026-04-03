use anyhow::{Context, Result, anyhow};
use serde::{Deserialize, Serialize};
use sqlx::SqlitePool;
use std::path::Path;

// ─── Data types ───────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize, sqlx::FromRow)]
pub struct PluginRecord {
    pub id: String,
    pub name: String,
    pub folder_path: String,
    /// Relative entry path for static plugins; empty for dev-server plugins.
    pub entry: String,
    /// Live URL (e.g. "http://localhost:5173") for dev-server plugins.
    pub dev_url: Option<String>,
    pub sort_order: i64,
    pub created_at: String,
}

pub struct RunningProcess {
    pub plugin_id: String,
    pub child: tokio::process::Child,
}

pub struct PluginRegistry {
    /// Std RwLock so it can be read from the synchronous plugin:// URI handler.
    pub plugins: std::sync::RwLock<Vec<PluginRecord>>,
    /// Tokio Mutex — only accessed from async command handlers.
    pub processes: tokio::sync::Mutex<Vec<RunningProcess>>,
}

impl PluginRegistry {
    pub fn new(plugins: Vec<PluginRecord>) -> Self {
        Self {
            plugins: std::sync::RwLock::new(plugins),
            processes: tokio::sync::Mutex::new(Vec::new()),
        }
    }
}

// ─── Plugin kind ─────────────────────────────────────────────────────────────

pub enum PluginKind {
    DevServer {
        install_cmd: Option<String>,
        dev_cmd: String,
        port: u16,
    },
    Static {
        entry: String,
    },
}

/// Read `caden-plugin.json` and determine how to run the plugin.
///
/// The manifest format:
/// ```json
/// { "name": "My App", "dev_command": "npm run dev", "install_command": "npm install", "port": 5173 }
/// { "name": "My App", "entry": "dist/index.html" }
/// ```
pub fn detect_kind(folder: &Path) -> Result<(String, PluginKind)> {
    let folder_name = folder
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("Plugin")
        .to_string();

    let manifest_path = folder.join("caden-plugin.json");

    if manifest_path.exists() {
        let content = std::fs::read_to_string(&manifest_path)
            .context("Failed to read caden-plugin.json")?;
        let json: serde_json::Value =
            serde_json::from_str(&content).context("caden-plugin.json is not valid JSON")?;

        let name = json["name"]
            .as_str()
            .unwrap_or(&folder_name)
            .to_string();

        // Dev-server plugin: must have dev_command + port
        if let (Some(dev_cmd), Some(port)) = (
            json["dev_command"].as_str(),
            json["port"].as_u64(),
        ) {
            return Ok((
                name,
                PluginKind::DevServer {
                    install_cmd: json["install_command"].as_str().map(String::from),
                    dev_cmd: dev_cmd.to_string(),
                    port: port as u16,
                },
            ));
        }

        // Static plugin: must have entry
        if let Some(entry) = json["entry"].as_str() {
            return Ok((name, PluginKind::Static { entry: entry.to_string() }));
        }

        return Err(anyhow!(
            "caden-plugin.json must specify either:\n\
             • \"dev_command\" + \"port\"  (for a live dev server)\n\
             • \"entry\"                   (for a pre-built static app)"
        ));
    }

    // No manifest — fall back to a pre-built static app if we can find one
    if folder.join("dist").join("index.html").exists() {
        return Ok((folder_name, PluginKind::Static {
            entry: "dist/index.html".to_string(),
        }));
    }

    Err(anyhow!(
        "No caden-plugin.json found in this folder.\n\
         Add one to tell CADEN how to run your app."
    ))
}

// ─── Dev server launch ────────────────────────────────────────────────────────

/// CREATE_NO_WINDOW — prevents a console window from flashing on Windows.
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x08000000;

/// Run a shell command synchronously and fail if it exits non-zero.
async fn run_command(folder: &Path, cmd: &str) -> Result<()> {
    let status = if cfg!(windows) {
        let mut c = tokio::process::Command::new("cmd");
        c.args(["/c", cmd]).current_dir(folder);
        #[cfg(windows)]
        c.creation_flags(CREATE_NO_WINDOW);
        c.status().await
    } else {
        let mut parts = cmd.split_whitespace();
        let prog = parts.next().unwrap_or("sh");
        tokio::process::Command::new(prog)
            .args(parts)
            .current_dir(folder)
            .status()
            .await
    }
    .with_context(|| format!("Failed to run: {}", cmd))?;

    if !status.success() {
        anyhow::bail!("Command failed (exit {}): {}", status, cmd);
    }
    Ok(())
}

/// Poll a TCP port until something answers, then return Ok.
async fn wait_for_port(port: u16, timeout_secs: u64) -> Result<()> {
    let addr = format!("127.0.0.1:{}", port);
    let deadline =
        std::time::Instant::now() + std::time::Duration::from_secs(timeout_secs);

    while std::time::Instant::now() < deadline {
        if tokio::net::TcpStream::connect(&addr).await.is_ok() {
            return Ok(());
        }
        tokio::time::sleep(std::time::Duration::from_millis(250)).await;
    }

    Err(anyhow!(
        "Port {} did not become available within {} seconds",
        port,
        timeout_secs
    ))
}

/// Kill any process currently listening on `port`.
/// On Windows, `cmd.exe /c node.exe` grandchildren survive `kill_on_drop`,
/// so we force-kill the whole process tree via netstat + taskkill.
async fn free_port(port: u16) {
    #[cfg(windows)]
    {
        // netstat -ano prints "  TCP  0.0.0.0:5173  ...  LISTENING  <pid>"
        let script = format!(
            "for /f \"tokens=5\" %a in \
             ('netstat -ano ^| findstr :{} ^| findstr LISTENING') \
             do taskkill /F /T /PID %a",
            port
        );
        let _ = tokio::process::Command::new("cmd")
            .args(["/c", &script])
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .creation_flags(CREATE_NO_WINDOW)
            .status()
            .await;
    }
    #[cfg(not(windows))]
    {
        let _ = tokio::process::Command::new("sh")
            .args(["-c", &format!("fuser -k {}/tcp 2>/dev/null || true", port)])
            .status()
            .await;
    }
    // Give the OS a moment to release the port
    tokio::time::sleep(std::time::Duration::from_millis(300)).await;
}

/// Run the install command (if needed), spawn the dev server, wait for the
/// port to be ready, and return the child process handle.
pub async fn start_dev_server(
    folder: &Path,
    install_cmd: Option<&str>,
    dev_cmd: &str,
    port: u16,
) -> Result<tokio::process::Child> {
    // Kill any orphaned process on this port before starting a fresh server.
    // This handles the Windows case where a previous cmd.exe child was killed
    // but the node.exe grandchild kept the port alive.
    free_port(port).await;

    // Install dependencies if needed
    if let Some(cmd) = install_cmd {
        if !folder.join("node_modules").exists() {
            log::info!("Running install command in {:?}: {}", folder, cmd);
            run_command(folder, cmd).await?;
        }
    }

    // Spawn the dev server
    log::info!("Starting dev server in {:?}: {}", folder, dev_cmd);
    let child = if cfg!(windows) {
        let mut c = tokio::process::Command::new("cmd");
        c.args(["/c", dev_cmd])
            .current_dir(folder)
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .kill_on_drop(true);
        #[cfg(windows)]
        c.creation_flags(CREATE_NO_WINDOW);
        c.spawn()
            .with_context(|| format!("Failed to spawn: {}", dev_cmd))?
    } else {
        let mut parts = dev_cmd.split_whitespace();
        let prog = parts.next().unwrap_or("sh");
        tokio::process::Command::new(prog)
            .args(parts)
            .current_dir(folder)
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .kill_on_drop(true)
            .spawn()
            .with_context(|| format!("Failed to spawn: {}", dev_cmd))?
    };

    // Wait for the server to be ready
    wait_for_port(port, 60).await?;

    Ok(child)
}

// ─── Database operations ──────────────────────────────────────────────────────

pub async fn load_plugins(pool: &SqlitePool) -> Result<Vec<PluginRecord>> {
    let rows = sqlx::query_as::<_, PluginRecord>(
        "SELECT id, name, folder_path, entry, dev_url, sort_order, created_at
         FROM plugins ORDER BY sort_order ASC, created_at ASC",
    )
    .fetch_all(pool)
    .await?;
    Ok(rows)
}

pub async fn save_plugin(pool: &SqlitePool, plugin: &PluginRecord) -> Result<()> {
    sqlx::query(
        "INSERT INTO plugins (id, name, folder_path, entry, dev_url, sort_order, created_at)
         VALUES (?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(&plugin.id)
    .bind(&plugin.name)
    .bind(&plugin.folder_path)
    .bind(&plugin.entry)
    .bind(&plugin.dev_url)
    .bind(plugin.sort_order)
    .bind(&plugin.created_at)
    .execute(pool)
    .await?;
    Ok(())
}

pub async fn update_plugin_dev_url(
    pool: &SqlitePool,
    id: &str,
    dev_url: Option<&str>,
) -> Result<()> {
    sqlx::query("UPDATE plugins SET dev_url = ? WHERE id = ?")
        .bind(dev_url)
        .bind(id)
        .execute(pool)
        .await?;
    Ok(())
}

pub async fn delete_plugin(pool: &SqlitePool, id: &str) -> Result<()> {
    sqlx::query("DELETE FROM plugins WHERE id = ?")
        .bind(id)
        .execute(pool)
        .await?;
    Ok(())
}

// ─── Static file serving (plugin:// URI scheme) ───────────────────────────────

pub fn mime_for_path(path: &Path) -> &'static str {
    match path
        .extension()
        .and_then(|e| e.to_str())
        .unwrap_or("")
        .to_lowercase()
        .as_str()
    {
        "html" | "htm" => "text/html",
        "js" | "mjs" => "application/javascript",
        "css" => "text/css",
        "svg" => "image/svg+xml",
        "png" => "image/png",
        "jpg" | "jpeg" => "image/jpeg",
        "gif" => "image/gif",
        "ico" => "image/x-icon",
        "woff" => "font/woff",
        "woff2" => "font/woff2",
        "ttf" => "font/ttf",
        "json" => "application/json",
        "webp" => "image/webp",
        "map" => "application/json",
        _ => "application/octet-stream",
    }
}
