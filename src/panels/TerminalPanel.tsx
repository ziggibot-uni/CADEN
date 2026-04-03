import { useEffect, useRef, useState, useCallback } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";

// ── types ─────────────────────────────────────────────────────────────────────
interface PtyDataEvent { id: number; data: string; }
interface PtyExitEvent { id: number; code: number; }
interface AppEntry {
  name: string;
  folder: string;
  display: string;
  mtime: number;
  has_plugin_json: boolean;
}

const VIBECODER_BACKEND = "C:\\Users\\User\\CADEN\\CADEN\\apps\\VibeCoder\\backend";

function timeAgo(unix: number): string {
  if (!unix) return "";
  const d = Math.floor(Date.now() / 1000) - unix;
  if (d < 60) return "now";
  if (d < 3600) return `${Math.floor(d / 60)}m`;
  if (d < 86400) return `${Math.floor(d / 3600)}h`;
  return `${Math.floor(d / 86400)}d`;
}

// ── component ─────────────────────────────────────────────────────────────────
export default function TerminalPanel() {
  const containerRef = useRef<HTMLDivElement>(null);
  const termRef      = useRef<Terminal | null>(null);
  const fitAddonRef  = useRef<FitAddon | null>(null);
  const ptyIdRef     = useRef<number | null>(null);

  const [ptyId,      setPtyId]      = useState<number | null>(null);
  const [running,    setRunning]    = useState(false);
  const [exitCode,   setExitCode]   = useState<number | null>(null);
  const [workspace,  setWorkspace]  = useState<string | null>(null);

  // App list
  const [apps,       setApps]       = useState<AppEntry[]>([]);

  // ── load app list ────────────────────────────────────────────────────────────
  useEffect(() => {
    invoke<AppEntry[]>("ab_list_apps")
      .then(setApps)
      .catch(() => {});
  }, []);

  // ── initialise xterm ────────────────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current) return;
    const t = new Terminal({
      theme: {
        background:    "#1b3445",
        foreground:    "#e8f4fa",
        cursor:        "#1aabbc",
        cursorAccent:  "#1b3445",
        black:         "#244b5f",
        brightBlack:   "#2a556d",
        red:           "#e06c75",
        brightRed:     "#e06c75",
        green:         "#98c379",
        brightGreen:   "#98c379",
        yellow:        "#e5c07b",
        brightYellow:  "#e5c07b",
        blue:          "#61afef",
        brightBlue:    "#61afef",
        magenta:       "#c678dd",
        brightMagenta: "#c678dd",
        cyan:          "#1aabbc",
        brightCyan:    "#56b6c2",
        white:         "#e8f4fa",
        brightWhite:   "#ffffff",
      },
      fontFamily: "'Cascadia Mono', 'Fira Code', Consolas, monospace",
      fontSize:   13,
      lineHeight: 1.4,
      cursorBlink: true,
      scrollback: 5000,
    });
    const fit = new FitAddon();
    t.loadAddon(fit);
    t.open(containerRef.current);
    fit.fit();
    termRef.current     = t;
    fitAddonRef.current = fit;
    const ro = new ResizeObserver(() => { try { fit.fit(); } catch (_) {} });
    ro.observe(containerRef.current);
    t.writeln("\x1b[2m  Select an app on the left to start coding.\x1b[0m");
    return () => { ro.disconnect(); t.dispose(); termRef.current = null; };
  }, []);

  // ── PTY events ───────────────────────────────────────────────────────────────
  useEffect(() => {
    if (ptyId === null) return;
    ptyIdRef.current = ptyId;
    const unsubs: (() => void)[] = [];

    listen<PtyDataEvent>("pty-data", ev => {
      if (ev.payload.id === ptyId && termRef.current)
        termRef.current.write(ev.payload.data);
    }).then(u => unsubs.push(u));

    listen<PtyExitEvent>("pty-exit", ev => {
      if (ev.payload.id !== ptyId) return;
      termRef.current?.write(`\r\n\x1b[2m[exited ${ev.payload.code}]\x1b[0m\r\n`);
      setRunning(false);
      setExitCode(ev.payload.code);
      ptyIdRef.current = null;
      setPtyId(null);
    }).then(u => unsubs.push(u));

    const dataDispose   = termRef.current?.onData(d => invoke("pty_write", { id: ptyId, data: d }).catch(() => {}));
    const resizeDispose = termRef.current?.onResize(({ cols, rows }) => invoke("pty_resize", { id: ptyId, cols, rows }).catch(() => {}));

    return () => { unsubs.forEach(u => u()); dataDispose?.dispose(); resizeDispose?.dispose(); };
  }, [ptyId]);

  // ── launch helpers ───────────────────────────────────────────────────────────
  const launchVibeCoder = useCallback(async (appFolder: string) => {
    const t = termRef.current;
    if (!t) return;
    if (ptyIdRef.current !== null)
      await invoke("pty_kill", { id: ptyIdRef.current }).catch(() => {});
    t.clear();
    setExitCode(null);
    setRunning(true);
    setWorkspace(appFolder);
    try {
      const id = await invoke<number>("pty_spawn", {
        cmd:  "python",
        args: ["main.py", "--workspace", appFolder],
        cwd:  VIBECODER_BACKEND,
        cols: t.cols,
        rows: t.rows,
      });
      setPtyId(id);
    } catch (err) {
      t.writeln(`\r\n\x1b[31m[spawn error] ${err}\x1b[0m\r\n`);
      setRunning(false);
    }
  }, []);

  const killSession = useCallback(async () => {
    if (ptyIdRef.current === null) return;
    await invoke("pty_kill", { id: ptyIdRef.current }).catch(() => {});
    setRunning(false);
  }, []);

  // ── external launch event ────────────────────────────────────────────────────
  useEffect(() => {
    const pending = (window as unknown as Record<string, unknown>)._pendingTerminalLaunch as
      { workspace?: string } | undefined;
    if (pending?.workspace) {
      delete (window as unknown as Record<string, unknown>)._pendingTerminalLaunch;
      launchVibeCoder(pending.workspace);
    }
    function onLaunch(e: Event) {
      const detail = (e as CustomEvent).detail as { workspace?: string; cmd?: string; args?: string[]; cwd?: string };
      if (detail.workspace) launchVibeCoder(detail.workspace);
    }
    window.addEventListener("terminal-launch", onLaunch);
    return () => window.removeEventListener("terminal-launch", onLaunch);
  }, [launchVibeCoder]);

  // ── render ───────────────────────────────────────────────────────────────────
  const appName = workspace ? workspace.split(/[/\\]/).pop() : null;

  return (
    <div className="flex h-full bg-[#1b3445] text-text overflow-hidden">

      {/* ── App sidebar ──────────────────────────────────────────────────── */}
      <div className="w-48 flex-shrink-0 flex flex-col border-r border-surface-2 bg-surface-1 overflow-hidden">
        <div className="px-3 py-2 border-b border-surface-2 flex-shrink-0">
          <span className="text-xs font-semibold text-text-muted uppercase tracking-wide">Apps</span>
        </div>
        <div className="flex-1 overflow-y-auto py-1">
          {apps.length === 0 && (
            <p className="text-xs text-text-dim italic px-3 py-2">No apps found</p>
          )}
          {apps.map(app => {
            const isActive = workspace?.replace(/[/\\]+$/, "").toLowerCase() ===
                             app.folder.replace(/[/\\]+$/, "").toLowerCase();
            return (
              <button
                key={app.folder}
                onClick={() => launchVibeCoder(app.folder)}
                className={`w-full text-left px-3 py-2 text-xs transition-colors flex items-center gap-2 ${
                  isActive
                    ? "bg-accent/15 text-accent font-semibold border-l-2 border-accent"
                    : "text-text hover:bg-surface-2 border-l-2 border-transparent"
                }`}
              >
                <span
                  className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${app.has_plugin_json ? "bg-green-500" : "bg-surface-2"}`}
                  title={app.has_plugin_json ? "caden-plugin.json present" : "no plugin config"}
                />
                <span className="truncate flex-1">{app.display}</span>
                <span className="text-text-dim flex-shrink-0 text-[10px]">{timeAgo(app.mtime)}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* ── Terminal area ─────────────────────────────────────────────────── */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">

        {/* header bar */}
        <div className="flex items-center gap-2 px-3 py-1.5 border-b border-surface-2 bg-surface-1/50 flex-shrink-0">
          <span className="text-xs font-mono text-text-muted truncate flex-1">
            {appName
              ? <><span className="text-accent font-semibold">{appName}</span></>
              : <span className="text-text-dim italic">no workspace selected</span>}
          </span>
          {exitCode !== null && !running && (
            <span className={`text-[10px] px-1.5 py-0.5 rounded ${exitCode === 0 ? "text-green-400 bg-green-500/10" : "text-red-400 bg-red-500/10"}`}>
              exit {exitCode}
            </span>
          )}
          {running && (
            <>
              <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse flex-shrink-0" />
              <button
                onClick={killSession}
                className="text-[10px] px-2 py-0.5 rounded text-red-400 bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 transition-colors flex-shrink-0"
              >
                Kill
              </button>
            </>
          )}
          {!running && workspace && (
            <button
              onClick={() => launchVibeCoder(workspace)}
              title="Restart VibeCoder"
              className="text-[10px] px-2 py-0.5 rounded text-accent bg-accent/10 hover:bg-accent/20 border border-accent/20 transition-colors flex-shrink-0"
            >
              Restart
            </button>
          )}
        </div>

        {/* xterm viewport */}
        <div ref={containerRef} className="flex-1 overflow-hidden p-1" />
      </div>
    </div>
  );
}
