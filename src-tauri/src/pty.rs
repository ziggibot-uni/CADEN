/// PTY management for CADEN's built-in terminal panel.
///
/// Uses `portable-pty` for cross-platform PTY (ConPTY on Windows, openpty on Unix).
/// Each session is keyed by a u32 id.  Output from the PTY is emitted as
/// `pty-data` events { id, data: string }.  EOF / exit emits `pty-exit` { id, code }.
use std::collections::HashMap;
use std::io::{Read, Write};
use std::sync::{Arc, Mutex};

use portable_pty::{native_pty_system, CommandBuilder, PtySize};
use tauri::{AppHandle, Emitter};

// ── Per-session state ─────────────────────────────────────────────────────────
pub struct Session {
    writer: Arc<Mutex<Box<dyn Write + Send>>>,
    child:  Arc<Mutex<Box<dyn portable_pty::Child + Send + Sync>>>,
    master: Arc<Mutex<Box<dyn portable_pty::MasterPty + Send>>>,
}

pub type PtyState = Arc<Mutex<HashMap<u32, Session>>>;

pub fn new_pty_state() -> PtyState {
    Arc::new(Mutex::new(HashMap::new()))
}

static SESSION_ID: std::sync::atomic::AtomicU32 = std::sync::atomic::AtomicU32::new(1);

// ── Commands ──────────────────────────────────────────────────────────────────

/// Spawn a new PTY process.  Returns the session id.
/// Emits `pty-data`  { id: u32, data: String }  for each chunk of output.
/// Emits `pty-exit`  { id: u32, code: u32 }     when the process exits.
#[tauri::command]
pub fn pty_spawn(
    app:       AppHandle,
    pty_state: tauri::State<'_, PtyState>,
    cmd:       String,
    args:      Vec<String>,
    cwd:       Option<String>,
    cols:      u16,
    rows:      u16,
) -> Result<u32, String> {
    let id = SESSION_ID.fetch_add(1, std::sync::atomic::Ordering::SeqCst);

    let pty_system = native_pty_system();
    let pair = pty_system
        .openpty(PtySize { rows, cols, pixel_width: 0, pixel_height: 0 })
        .map_err(|e| format!("PTY open: {e}"))?;

    let mut builder = CommandBuilder::new(&cmd);
    for a in &args { builder.arg(a); }
    if let Some(ref dir) = cwd { builder.cwd(dir); }

    // Force ANSI colours and unbuffered Python output.
    builder.env("TERM",            "xterm-256color");
    builder.env("FORCE_COLOR",     "1");
    builder.env("PYTHONUNBUFFERED","1");
    builder.env("COLORTERM",       "truecolor");

    let child = pair.slave
        .spawn_command(builder)
        .map_err(|e| format!("spawn: {e}"))?;
    let child: Arc<Mutex<Box<dyn portable_pty::Child + Send + Sync>>> =
        Arc::new(Mutex::new(child));

    // Reader spawned in a background thread — emits chunks as UTF-8 lossy strings.
    let mut reader = pair.master
        .try_clone_reader()
        .map_err(|e| format!("reader: {e}"))?;

    let writer = pair.master
        .take_writer()
        .map_err(|e| format!("writer: {e}"))?;
    let writer = Arc::new(Mutex::new(writer));

    let master = Arc::new(Mutex::new(pair.master));

    {
        let app   = app.clone();
        let child = child.clone();
        std::thread::spawn(move || {
            let mut buf = [0u8; 4096];
            loop {
                match reader.read(&mut buf) {
                    Ok(0) | Err(_) => break,
                    Ok(n) => {
                        let data = String::from_utf8_lossy(&buf[..n]).to_string();
                        let _ = app.emit("pty-data", serde_json::json!({ "id": id, "data": data }));
                    }
                }
            }
            // Harvest exit code.
            let code = child.lock().unwrap()
                .wait()
                .map(|s| s.exit_code())
                .unwrap_or(0);
            let _ = app.emit("pty-exit", serde_json::json!({ "id": id, "code": code }));
        });
    }

    pty_state.lock().unwrap().insert(id, Session { writer, child, master });
    Ok(id)
}

/// Write data (stdin) to a running PTY session.
#[tauri::command]
pub fn pty_write(
    pty_state: tauri::State<'_, PtyState>,
    id:        u32,
    data:      String,
) -> Result<(), String> {
    let writer = {
        let sessions = pty_state.lock().unwrap();
        let s = sessions.get(&id).ok_or("PTY session not found")?;
        s.writer.clone()
    };
    let result = writer.lock().unwrap()
        .write_all(data.as_bytes())
        .map_err(|e| e.to_string());
    result
}

/// Notify the PTY that the terminal was resized.
#[tauri::command]
pub fn pty_resize(
    pty_state: tauri::State<'_, PtyState>,
    id:        u32,
    cols:      u16,
    rows:      u16,
) -> Result<(), String> {
    let master = {
        let sessions = pty_state.lock().unwrap();
        let s = sessions.get(&id).ok_or("PTY session not found")?;
        s.master.clone()
    };
    let result = master.lock().unwrap()
        .resize(PtySize { rows, cols, pixel_width: 0, pixel_height: 0 })
        .map_err(|e| e.to_string());
    result
}

/// Kill a PTY session and remove it.
#[tauri::command]
pub fn pty_kill(
    pty_state: tauri::State<'_, PtyState>,
    id:        u32,
) -> Result<(), String> {
    let mut sessions = pty_state.lock().unwrap();
    if let Some(s) = sessions.remove(&id) {
        let _ = s.child.lock().unwrap().kill();
    }
    Ok(())
}
