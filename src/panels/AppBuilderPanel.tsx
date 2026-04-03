/**
 * AppBuilder — workspace + app management panel.
 *
 * Stripped-down from the old WebSocket IDE approach.
 * Manages workspaces and apps; launches VibeCoder via the Terminal panel.
 */

import { useState, useCallback, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";

const CADEN_DEFAULT_WORKSPACE = "C:\\Users\\User\\CADEN\\CADEN";
const APPS_DIR = "C:\\Users\\User\\CADEN\\CADEN\\apps";

interface AppEntry {
  name: string;
  folder: string;
  display: string;
  mtime: number;
  has_plugin_json: boolean;
}

function timeAgo(unixSecs: number): string {
  if (!unixSecs) return "";
  const diff = Math.floor(Date.now() / 1000) - unixSecs;
  if (diff < 60) return "now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
  if (diff < 604800) return `${Math.floor(diff / 86400)}d`;
  return `${Math.floor(diff / 604800)}w`;
}

// ── Component ─────────────────────────────────────────────────────────────────
export default function AppBuilderPanel() {
  const [workspace, setWorkspace] = useState<string>(() =>
    localStorage.getItem("caden-appbuilder-workspace") ?? CADEN_DEFAULT_WORKSPACE
  );

  // ── App drawer ────────────────────────────────────────────────────────────
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [apps, setApps] = useState<AppEntry[]>([]);
  const [newAppName, setNewAppName] = useState("");
  const [creatingApp, setCreatingApp] = useState(false);

  const loadApps = useCallback(async () => {
    try {
      const list = await invoke<AppEntry[]>("ab_list_apps");
      setApps(list);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { if (drawerOpen) loadApps(); }, [drawerOpen, loadApps]);

  function selectWorkspace(folder: string) {
    setWorkspace(folder);
    localStorage.setItem("caden-appbuilder-workspace", folder);
    setDrawerOpen(false);
  }

  async function handleNewApp() {
    const name = newAppName.trim();
    if (!name || creatingApp) return;
    const folderName = name.replace(/[^a-zA-Z0-9_-]/g, "");
    if (!folderName) return;
    const folder = `${APPS_DIR}\\${folderName}`;
    setCreatingApp(true);
    try {
      await invoke("ab_write_file", {
        path: "caden-plugin.json",
        content: JSON.stringify({
          name,
          install_command: "npm install",
          dev_command: "npm run dev",
          port: 5181,
        }, null, 2),
        workspace: folder,
      });
      setNewAppName("");
      selectWorkspace(folder);
    } catch (e) {
      alert(`Failed to create app: ${e}`);
    } finally {
      setCreatingApp(false);
    }
  }

  // ── Actions ───────────────────────────────────────────────────────────────
  async function handlePickWorkspace() {
    try {
      const folder = await invoke<string | null>("ab_pick_workspace");
      if (folder) selectWorkspace(folder);
    } catch { /* ignore */ }
  }

  const [registering, setRegistering] = useState(false);
  const [registerMsg, setRegisterMsg] = useState<string | null>(null);

  async function handleRegister() {
    setRegistering(true);
    setRegisterMsg(null);
    try {
      const plugin = await invoke("register_plugin_folder", { folderPath: workspace });
      window.dispatchEvent(new CustomEvent("caden-plugin-registered", { detail: plugin }));
      setRegisterMsg(`\u2713 Registered "${workspace.split(/[/\\]/).pop()}"`);
    } catch (e) {
      setRegisterMsg(`\u26a0 ${e}`);
    } finally {
      setRegistering(false);
    }
  }

  function openVibeCoder() {
    window.dispatchEvent(
      new CustomEvent("caden-open-terminal", {
        detail: { workspace },
      })
    );
  }

  // ── Render ────────────────────────────────────────────────────────────────
  const appName = workspace.split(/[/\\]/).pop() ?? workspace;

  return (
    <div className="flex flex-col h-full bg-surface overflow-hidden">

      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-surface-2 bg-surface-1 flex-shrink-0">
        <button
          onClick={() => setDrawerOpen(d => !d)}
          className="text-xs font-semibold text-accent hover:text-text transition-colors flex-shrink-0"
        >
          {drawerOpen ? "\u25be Apps" : "\u25b8 Apps"}
        </button>

        <span className="text-xs text-text-muted truncate flex-1 font-mono" title={workspace}>
          {appName}
        </span>

        <button
          onClick={handlePickWorkspace}
          className="text-xs text-text-muted hover:text-text px-2 py-1 rounded hover:bg-surface-2 transition-colors flex-shrink-0"
        >
          Folder
        </button>

        <button
          onClick={handleRegister}
          disabled={registering}
          title="Register this folder as a CADEN plugin tab"
          className="text-xs text-accent hover:text-text px-2 py-1 rounded hover:bg-accent/10 border border-accent/30 transition-colors flex-shrink-0 disabled:opacity-40"
        >
          {registering ? "Registering\u2026" : "Register"}
        </button>
      </div>

      {/* App drawer */}
      {drawerOpen && (
        <div className="border-b border-surface-2 bg-surface-1 px-4 py-2.5 flex-shrink-0 max-h-64 overflow-y-auto">
          <div className="flex gap-2 mb-2">
            <input
              value={newAppName}
              onChange={e => setNewAppName(e.target.value)}
              onKeyDown={e => e.key === "Enter" && handleNewApp()}
              placeholder="New app name\u2026"
              className="flex-1 bg-surface border border-surface-2 rounded px-2 py-1 text-xs text-text placeholder-text-dim outline-none focus:border-accent/50 transition-colors"
            />
            <button
              onClick={handleNewApp}
              disabled={!newAppName.trim() || creatingApp}
              className="text-xs px-3 py-1 bg-accent text-surface font-semibold rounded disabled:opacity-40 hover:bg-accent/80 transition-colors flex-shrink-0"
            >
              + New
            </button>
          </div>

          {apps.length === 0 ? (
            <p className="text-xs text-text-muted italic">No apps found</p>
          ) : (
            <div className="space-y-0.5">
              {apps.map(app => {
                const isActive =
                  workspace.replace(/[/\\]+$/, "").toLowerCase() ===
                  app.folder.replace(/[/\\]+$/, "").toLowerCase();
                return (
                  <button
                    key={app.folder}
                    onClick={() => !isActive && selectWorkspace(app.folder)}
                    className={`w-full text-left flex items-center gap-2 px-2 py-1.5 rounded text-xs transition-colors ${
                      isActive
                        ? "bg-accent/10 text-accent font-semibold"
                        : "hover:bg-surface-2 text-text"
                    }`}
                  >
                    <span
                      className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${app.has_plugin_json ? "bg-green-500" : "bg-surface-2"}`}
                      title={app.has_plugin_json ? "Has caden-plugin.json" : "No plugin config"}
                    />
                    <span className="truncate flex-1 font-medium">{app.display}</span>
                    <span className="text-text-dim flex-shrink-0">{timeAgo(app.mtime)}</span>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* Main body */}
      <div className="flex-1 flex flex-col items-center justify-center gap-6 px-8 text-center">
        <div className="space-y-1">
          <p className="text-sm font-semibold text-text">{appName}</p>
          <p className="text-xs text-text-muted font-mono break-all">{workspace}</p>
        </div>

        <button
          onClick={openVibeCoder}
          className="flex items-center gap-3 px-6 py-3 bg-accent text-surface font-semibold text-sm rounded-xl hover:bg-accent/80 transition-colors shadow-lg"
        >
          <span className="text-xl">\u2328</span>
          Open VibeCoder
        </button>

        <p className="text-xs text-text-dim max-w-xs">
          Opens the VibeCoder CLI in the Terminal panel. The agent will code, read files,
          run commands, and research docs in your workspace.
        </p>

        {registerMsg && (
          <p className={`text-xs px-3 py-1 rounded ${registerMsg.startsWith("\u2713") ? "text-green-400 bg-green-500/10" : "text-red-400 bg-red-500/10"}`}>
            {registerMsg}
          </p>
        )}
      </div>
    </div>
  );
}
