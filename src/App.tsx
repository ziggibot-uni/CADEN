import { useState, useEffect, useCallback, useRef, useLayoutEffect, Suspense } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { open, save } from "@tauri-apps/plugin-dialog";
import { TodayPanel } from "./components/TodayPanel";
import { ChatPanel } from "./components/ChatPanel";
import { UpcomingPanel } from "./components/UpcomingPanel";
import { BottomBar } from "./components/BottomBar";
import { SettingsPanel } from "./components/SettingsPanel";
import { FirstRunWizard } from "./components/FirstRunWizard";
import { ColorContextMenu } from "./components/ColorContextMenu";
import { CatchUpModal } from "./components/CatchUpModal";
import { ResurfacedThoughts } from "./components/ResurfacedThoughts";
import { COLOR_OVERRIDE_SCRIPT } from "./colorOverrideScript";
import { useAppState } from "./hooks/useAppState";
import { SettingsContext } from "./context/SettingsContext";
import { cadenColorDefaults } from "../caden-colors.js";
import { BUILT_IN_PANELS } from "./panels/index";
import type { Plugin } from "./types";
import type { CatchUpSummary } from "./types";

// Built-in tabs are fixed strings; plugin tabs are "plugin:<id>"; panel tabs are "panel:<id>"
type Tab = "dashboard" | string;

export default function App() {
  const {
    settings,
    setSettings,
    planItems,
    upcomingItems,
    plugins,
    addPlugin,
    removePlugin,
    ollamaStatus,
    syncStatus,
    plannerContext,
    initialized,
    checkOllama,
    sync,
    markItemComplete,
    unmarkItemComplete,
    reorderItems,
    updatePlanItem,
    clearCompleted,
    deleteItem,
  } = useAppState();

  useEffect(() => {
    const scale = settings.font_scale ?? 1.0;
    document.documentElement.style.setProperty("--font-scale", String(scale));
    document.querySelectorAll("iframe").forEach((iframe) => {
      iframe.contentWindow?.postMessage({ type: "caden-font-scale", scale }, "*");
    });
  }, [settings.font_scale]);

  useEffect(() => {
    const contrast = settings.contrast ?? 1.0;
    document.documentElement.style.setProperty("--contrast", String(contrast));
    document.querySelectorAll("iframe").forEach((iframe) => {
      iframe.contentWindow?.postMessage({ type: "caden-contrast", contrast }, "*");
    });
  }, [settings.contrast]);

  // ── Panel widths ─────────────────────────────────────────────────────────
  const [panelWidths, setPanelWidths] = useState<{ left: number; right: number }>(() => {
    try {
      const saved = localStorage.getItem("caden-panel-widths");
      if (saved) return JSON.parse(saved);
    } catch {}
    return { left: 30, right: 20 };
  });

  useEffect(() => {
    localStorage.setItem("caden-panel-widths", JSON.stringify(panelWidths));
  }, [panelWidths]);

  const containerRef = useRef<HTMLDivElement>(null);

  const startDrag = useCallback((divider: "left" | "right") => {
    return (e: React.MouseEvent) => {
      e.preventDefault();
      const startX = e.clientX;
      const containerW = containerRef.current?.offsetWidth ?? window.innerWidth;
      const startWidths = { ...panelWidths };

      function onMove(ev: MouseEvent) {
        const dPct = ((ev.clientX - startX) / containerW) * 100;
        setPanelWidths((prev) => {
          const centerW = 100 - startWidths.left - startWidths.right;
          if (divider === "left") {
            const newLeft = Math.max(15, Math.min(55, startWidths.left + dPct));
            const newCenter = centerW - (newLeft - startWidths.left);
            if (newCenter < 15) return prev;
            return { ...prev, left: Math.round(newLeft * 10) / 10 };
          } else {
            const newRight = Math.max(10, Math.min(40, startWidths.right - dPct));
            const newCenter = centerW - (newRight - startWidths.right);
            if (newCenter < 15) return prev;
            return { ...prev, right: Math.round(newRight * 10) / 10 };
          }
        });
      }

      function onUp() {
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
      }

      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    };
  }, [panelWidths]);

  const centerWidth = 100 - panelWidths.left - panelWidths.right;

  // ── Tabs / UI ─────────────────────────────────────────────────────────────
  const [tab, setTab] = useState<Tab>("dashboard");
  const [showSettings, setShowSettings] = useState(false);
  const [addingPlugin, setAddingPlugin] = useState(false);
  const [pluginError, setPluginError] = useState<string | null>(null);
  const [showAddMenu, setShowAddMenu] = useState(false);
  const [addingWebTab, setAddingWebTab] = useState(false);
  const [webTabUrl, setWebTabUrl] = useState("");
  const [webTabName, setWebTabName] = useState("");
  const [pluginReloadKeys, setPluginReloadKeys] = useState<Record<string, number>>({});

  // ── Tab order (drag-to-reorder) ───────────────────────────────────────────
  const [tabOrder, setTabOrder] = useState<string[]>(() => {
    try {
      const saved = localStorage.getItem("caden-tab-order");
      if (saved) return JSON.parse(saved);
    } catch {}
    return [];
  });
  const tabDragId = useRef<string | null>(null);

  useEffect(() => {
    localStorage.setItem("caden-tab-order", JSON.stringify(tabOrder));
  }, [tabOrder]);

  // Build the current canonical tab ids from state, then sort by saved order
  function getSortedTabs(): { id: string; label: string }[] {
    const all: { id: string; label: string }[] = [
      { id: "dashboard", label: "Dashboard" },
      ...BUILT_IN_PANELS.map((p) => ({ id: `panel:${p.id}`, label: p.name })),
      ...plugins.map((p) => ({ id: `plugin:${p.id}`, label: p.name })),
    ];
    if (tabOrder.length === 0) return all;
    const ordered = tabOrder
      .map((oid) => all.find((t) => t.id === oid))
      .filter(Boolean) as { id: string; label: string }[];
    const unordered = all.filter((t) => !tabOrder.includes(t.id));
    return [...ordered, ...unordered];
  }

  function handleTabDragStart(id: string) {
    tabDragId.current = id;
  }

  function handleTabDrop(targetId: string) {
    const fromId = tabDragId.current;
    tabDragId.current = null;
    if (!fromId || fromId === targetId) return;
    const sorted = getSortedTabs().map((t) => t.id);
    const fromIdx = sorted.indexOf(fromId);
    const toIdx = sorted.indexOf(targetId);
    if (fromIdx === -1 || toIdx === -1) return;
    const next = [...sorted];
    next.splice(fromIdx, 1);
    next.splice(toIdx, 0, fromId);
    setTabOrder(next);
  }

  // ── Circadian nudge toast ─────────────────────────────────────────────────
  const [nudgeMessage, setNudgeMessage] = useState<string | null>(null);
  useEffect(() => {
    const unlisten = listen<string>("caden-nudge", (event) => {
      setNudgeMessage(event.payload);
    });
    return () => { unlisten.then((f) => f()); };
  }, []);

  // ── Catch-up modal (startup) ──────────────────────────────────────────────
  const [catchUpSummary, setCatchUpSummary] = useState<CatchUpSummary | null>(null);
  const catchUpFetched = useRef(false);
  useEffect(() => {
    if (!initialized || catchUpFetched.current) return;
    catchUpFetched.current = true;
    invoke<CatchUpSummary>("get_catchup_summary")
      .then((s) => {
        // Only show if there's something meaningful
        const hasContent =
          s.hours_since_last_sync > 2 ||
          s.overdue_tasks.length > 0 ||
          s.resurfaced_thoughts.length > 0 ||
          s.low_energy_mode;
        if (hasContent) setCatchUpSummary(s);
      })
      .catch(() => {});
  }, [initialized]);

  // ── Training-ready notification ───────────────────────────────────────────
  type TrainingCounts = {
    response: number; analyze: number; classify: number;
    mood: number; goal: number; data_report: number;
    threshold_response: number; threshold_analyze: number; threshold_classify: number;
    threshold_mood: number; threshold_goal: number; threshold_data_report: number;
  };
  const [trainingReady, setTrainingReady] = useState<TrainingCounts | null>(null);
  useEffect(() => {
    const unlisten = listen<TrainingCounts>("caden-training-ready", (event) => {
      setTrainingReady(event.payload);
    });
    return () => { unlisten.then((f) => f()); };
  }, []);

  // Close add-tab menu on outside click
  useEffect(() => {
    if (!showAddMenu) return;
    const handler = () => setShowAddMenu(false);
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [showAddMenu]);

  // Listen for plugin registration events (fired from anywhere a plugin is registered)
  useEffect(() => {
    function onPluginRegistered(e: Event) {
      const plugin = (e as CustomEvent).detail as Plugin;
      addPlugin(plugin);
      setTab(`plugin:${plugin.id}`);
    }
    window.addEventListener("caden-plugin-registered", onPluginRegistered);
    return () => window.removeEventListener("caden-plugin-registered", onPluginRegistered);
  }, [addPlugin]);

  // Listen for "open terminal" requests from any panel
  // Stores launch params on window, switches to Terminal tab, and emits
  // "terminal-launch" so an already-mounted TerminalPanel responds immediately.
  useEffect(() => {
    function onOpenTerminal(e: Event) {
      const detail = (e as CustomEvent).detail as { workspace?: string; cmd?: string; args?: string[]; cwd?: string };
      // Park the launch for when TerminalPanel mounts
      (window as unknown as Record<string, unknown>)._pendingTerminalLaunch = detail;
      setTab("panel:terminal");
      // Also fire to an already-mounted terminal
      window.dispatchEvent(new CustomEvent("terminal-launch", { detail }));
    }
    window.addEventListener("caden-open-terminal", onOpenTerminal);
    return () => window.removeEventListener("caden-open-terminal", onOpenTerminal);
  }, []);

  // If the active plugin tab is removed, fall back to dashboard
  useEffect(() => {
    if (tab.startsWith("plugin:")) {
      const id = tab.slice(7);
      if (!plugins.find((p) => p.id === id)) {
        setTab("dashboard");
      }
    }
  }, [plugins, tab]);

  async function handleAddPlugin() {
    setPluginError(null);
    const folder = await open({
      directory: true,
      multiple: false,
      title: "Select Plugin App Folder",
    });
    if (!folder) return;

    setAddingPlugin(true);
    try {
      const plugin = await invoke<Plugin>("register_plugin_folder", {
        folderPath: folder,
      });
      addPlugin(plugin);
      setTab(`plugin:${plugin.id}`);
    } catch (err) {
      setPluginError(String(err));
    } finally {
      setAddingPlugin(false);
    }
  }

  async function handleRemovePlugin(id: string) {
    try {
      await invoke("unregister_plugin", { id });
      removePlugin(id);
    } catch (err) {
      console.error("Failed to remove plugin:", err);
    }
  }

  async function handleRefresh() {
    if (tab === "dashboard") {
      sync();
      return;
    }
    if (tab.startsWith("panel:")) {
      // Built-in panels manage their own refresh state
      return;
    }
    if (tab.startsWith("plugin:")) {
      const id = tab.slice(7);
      const plugin = plugins.find((p) => p.id === id);
      if (!plugin) return;
      // Web tabs: reload the child webview directly
      if (!plugin.folder_path && !plugin.entry) {
        invoke("reload_web_tab_view", { label: `web-tab-${id}` });
      } else {
        // iframe plugins: bump their reload key to force a new src load
        setPluginReloadKeys((prev) => ({ ...prev, [id]: (prev[id] ?? 0) + 1 }));
      }
    }
  }

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key === "r") {
        e.preventDefault();
        handleRefresh();
      }
      if ((e.ctrlKey || e.metaKey) && e.key === "w") {
        e.preventDefault();
        getCurrentWindow().close();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  });

  async function handleAddWebTab() {
    const url = webTabUrl.trim();
    const name = webTabName.trim();
    if (!url || !name) return;
    const fullUrl = url.startsWith("http") ? url : `https://${url}`;
    setAddingWebTab(true);
    try {
      const plugin = await invoke<Plugin>("add_web_tab", { name, url: fullUrl });
      addPlugin(plugin);
      setTab(`plugin:${plugin.id}`);
      setWebTabUrl("");
      setWebTabName("");
      setShowAddMenu(false);
    } catch (err) {
      setPluginError(String(err));
    } finally {
      setAddingWebTab(false);
    }
  }

  if (initialized && !settings.setup_complete) {
    return (
      <FirstRunWizard
        onComplete={() => setSettings((s) => ({ ...s, setup_complete: true }))}
      />
    );
  }

  return (
    <SettingsContext.Provider value={settings}>
    <div className="flex flex-col h-screen bg-surface overflow-hidden">
      {/* Tab bar */}
      <div className="flex items-end gap-0 border-b border-surface-2 bg-surface-1 px-4 flex-shrink-0">
        {getSortedTabs().map(({ id, label }) => (
          <TabButton
            key={id}
            label={label}
            active={tab === id}
            onClick={() => setTab(id)}
            onDragStart={() => handleTabDragStart(id)}
            onDrop={() => handleTabDrop(id)}
          />
        ))}

        {/* Add tab menu */}
        <div className="relative ml-1 mb-[2px]">
          <button
            onClick={() => setShowAddMenu((v) => !v)}
            disabled={addingPlugin}
            title="Add tab"
            className="px-2.5 py-1.5 text-text-dim hover:text-text transition-colors text-base leading-none cursor-pointer disabled:opacity-40"
          >
            {addingPlugin ? "…" : "+"}
          </button>

          {showAddMenu && (
            <div className="absolute top-full left-0 mt-1 bg-surface-1 border border-surface-2 rounded shadow-lg z-50 min-w-[160px]" onMouseDown={(e) => e.stopPropagation()}>
              <button
                onClick={() => { setShowAddMenu(false); handleAddPlugin(); }}
                className="w-full text-left px-3 py-2 text-xs text-text-muted hover:text-text hover:bg-surface-2 transition-colors"
              >
                App folder
              </button>
              <button
                onClick={() => setShowAddMenu((v) => !v)}
                className="w-full text-left px-3 py-2 text-xs text-text-muted hover:text-text hover:bg-surface-2 transition-colors"
              >
                Web page
              </button>

              {/* Inline web-page form */}
              <div className="px-3 py-2 border-t border-surface-2 flex flex-col gap-1.5">
                <input
                  className="w-full bg-surface border border-surface-2 rounded px-2 py-1 text-xs text-text placeholder-text-dim outline-none focus:border-accent-DEFAULT"
                  placeholder="Tab name"
                  value={webTabName}
                  onChange={(e) => setWebTabName(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleAddWebTab()}
                />
                <input
                  className="w-full bg-surface border border-surface-2 rounded px-2 py-1 text-xs text-text placeholder-text-dim outline-none focus:border-accent-DEFAULT"
                  placeholder="https://..."
                  value={webTabUrl}
                  onChange={(e) => setWebTabUrl(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleAddWebTab()}
                />
                <button
                  onClick={handleAddWebTab}
                  disabled={addingWebTab || !webTabUrl.trim() || !webTabName.trim()}
                  className="w-full text-xs bg-accent-DEFAULT text-surface rounded px-2 py-1 disabled:opacity-40 cursor-pointer"
                >
                  {addingWebTab ? "…" : "Add"}
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Inline error dismissal */}
        {pluginError && (
          <div className="ml-3 mb-[3px] flex items-center gap-2">
            <span className="text-[10px] text-urgency-high font-mono max-w-[300px] truncate">
              {pluginError}
            </span>
            <button
              onClick={() => setPluginError(null)}
              className="text-text-dim hover:text-text text-xs"
            >
              ✕
            </button>
          </div>
        )}
      </div>

      {/* Main content */}
      <div className="flex flex-1 overflow-hidden">
        {/* Dashboard — hidden when a plugin tab is active */}
        <div
          ref={containerRef}
          className={`flex flex-1 overflow-hidden ${tab === "dashboard" ? "" : "hidden"}`}
        >
          {/* Left — Today's Plan */}
          <div className="flex flex-col overflow-hidden flex-shrink-0" style={{ width: `${panelWidths.left}%` }}>
            <ResurfacedThoughts />
            <TodayPanel
              items={planItems}
              onItemCompleted={markItemComplete}
              onItemUncompleted={unmarkItemComplete}
              onReorder={reorderItems}
              onClearCompleted={clearCompleted}
              onItemUpdated={updatePlanItem}
              onItemDeleted={deleteItem}
            />
          </div>

          {/* Divider — left/center */}
          <div
            onMouseDown={startDrag("left")}
            className="w-1 flex-shrink-0 bg-surface-2 hover:bg-accent-DEFAULT cursor-col-resize transition-colors duration-150 select-none"
          />

          {/* Center — CADEN Chat */}
          <div className="flex flex-col overflow-hidden flex-shrink-0" style={{ width: `${centerWidth}%` }}>
            <ChatPanel
              ollamaStatus={ollamaStatus}
              context={plannerContext}
              onRetryOllama={checkOllama}
            />
          </div>

          {/* Divider — center/right */}
          <div
            onMouseDown={startDrag("right")}
            className="w-1 flex-shrink-0 bg-surface-2 hover:bg-accent-DEFAULT cursor-col-resize transition-colors duration-150 select-none"
          />

          {/* Right — Upcoming */}
          <div className="flex flex-col overflow-hidden flex-shrink-0" style={{ width: `${panelWidths.right}%` }}>
            <UpcomingPanel items={upcomingItems} />
          </div>
        </div>

        {/* Built-in panel tabs — all kept mounted, only the active one is visible */}
        {BUILT_IN_PANELS.map((panel) => (
          <div
            key={panel.id}
            className={`flex-1 overflow-hidden ${tab === `panel:${panel.id}` ? "" : "hidden"}`}
          >
            <Suspense fallback={
              <div className="flex items-center justify-center h-full text-text-dim text-xs animate-pulse">
                loading...
              </div>
            }>
              <panel.component />
            </Suspense>
          </div>
        ))}

        {/* Plugin tabs — all kept mounted, only the active one is visible */}
        {plugins.map((plugin) => (
          <div
            key={plugin.id}
            className={`flex-1 overflow-hidden ${tab === `plugin:${plugin.id}` ? "" : "hidden"}`}
          >
            <PluginTab
              plugin={plugin}
              active={tab === `plugin:${plugin.id}`}
              reloadKey={pluginReloadKeys[plugin.id] ?? 0}
              fontScale={settings.font_scale ?? 1.0}
              contrast={settings.contrast ?? 1.0}
            />
          </div>
        ))}
      </div>

      {/* Bottom bar */}
      <BottomBar
        ollamaStatus={ollamaStatus}
        syncStatus={syncStatus}
        onSettingsClick={() => setShowSettings(true)}
        onRefreshClick={handleRefresh}
      />

      {/* Settings overlay */}
      <ColorContextMenu />

      {showSettings && (
        <SettingsPanel
          settings={settings}
          plugins={plugins}
          onClose={() => setShowSettings(false)}
          onSettingsChange={async (updated) => {
            const workHoursChanged = JSON.stringify(updated.work_hours) !== JSON.stringify(settings.work_hours);
            setSettings(updated);
            if (workHoursChanged) {
              await invoke("force_replan");
              sync();
            }
          }}
          onPluginRemoved={handleRemovePlugin}
        />
      )}

      {/* Circadian nudge toast */}
      {nudgeMessage && (
        <div className="fixed bottom-10 right-4 z-50 max-w-xs bg-surface-1 border border-accent-DEFAULT/40 rounded-lg shadow-lg px-4 py-3 flex items-start gap-3">
          <div className="flex-1 text-xs text-text leading-relaxed">{nudgeMessage}</div>
          <button
            onClick={() => setNudgeMessage(null)}
            className="text-text-dim hover:text-text text-base leading-none flex-shrink-0 mt-0.5 cursor-pointer"
            aria-label="Dismiss"
          >
            ✕
          </button>
        </div>
      )}

      {/* Startup catch-up modal */}
      {catchUpSummary && (
        <CatchUpModal
          summary={catchUpSummary}
          onClose={() => setCatchUpSummary(null)}
          onTriageComplete={() => {
            setCatchUpSummary(null);
            sync();
          }}
        />
      )}

      {/* Training-data ready modal */}
      {trainingReady && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-surface-1 border border-accent-DEFAULT/40 rounded-xl shadow-xl px-6 py-5 max-w-sm w-full">
            <h2 className="text-base font-semibold text-text mb-1">Ready to fine-tune ✓</h2>
            <p className="text-xs text-text-dim mb-4 leading-relaxed">
              CADEN has collected enough examples to fine-tune a local model.
              Export the JSONL, close CADEN, then run <span className="font-mono text-text">train.bat</span> in the <span className="font-mono text-text">CADEN-train</span> folder.
            </p>
            <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-text-dim mb-5">
              <span>Responses</span><span className="text-text">{trainingReady.response} / {trainingReady.threshold_response}</span>
              <span>Analyses</span><span className="text-text">{trainingReady.analyze} / {trainingReady.threshold_analyze}</span>
              <span>Classifications</span><span className="text-text">{trainingReady.classify} / {trainingReady.threshold_classify}</span>
              <span>Mood extractions</span><span className="text-text">{trainingReady.mood} / {trainingReady.threshold_mood}</span>
              <span>Goal extractions</span><span className="text-text">{trainingReady.goal} / {trainingReady.threshold_goal}</span>
              <span>Data reports</span><span className="text-text">{trainingReady.data_report} / {trainingReady.threshold_data_report}</span>
            </div>
            <div className="flex flex-col gap-2">
              <button
                onClick={async () => {
                  const dest = await save({
                    defaultPath: "caden_train.jsonl",
                    filters: [{ name: "JSONL", extensions: ["jsonl"] }],
                  });
                  if (!dest) return;
                  try {
                    await invoke("export_training_data", { path: dest });
                    setTrainingReady(null);
                  } catch (e) {
                    alert(`Export failed: ${e}`);
                  }
                }}
                className="w-full py-2 rounded-lg bg-accent-DEFAULT text-background text-sm font-medium hover:opacity-90 cursor-pointer"
              >
                Export JSONL
              </button>
              <button
                onClick={() => setTrainingReady(null)}
                className="w-full py-2 rounded-lg bg-surface-2 text-text-dim text-sm hover:text-text cursor-pointer"
              >
                Later
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
    </SettingsContext.Provider>
  );
}

// A web tab (folder_path="" and entry="") loads an external URL.
// External sites block iframes via X-Frame-Options, so we create a child
// Webview (a separate WebKit/WebView2 instance) that overlays the container.
//
// The child webview is created once on mount and kept alive for the lifetime
// of the component (i.e. as long as the plugin is registered).  When the tab
// is inactive we slide it off-screen so it stays loaded and the user's login
// session is never lost — both in-memory for the current session and on-disk
// between restarts (WebView2 persists cookies to the app data directory).
function WebTabFrame({ plugin, active }: { plugin: Plugin; active: boolean }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const label = `web-tab-${plugin.id}`;

  // Create the child webview once on mount; destroy it when the plugin is removed.
  useLayoutEffect(() => {
    if (!plugin.dev_url) return;
    // Start off-screen with a sensible default size so the page begins
    // loading immediately while the layout is not yet known.
    invoke("open_web_tab_view", {
      label,
      url: plugin.dev_url,
      x: -10000,
      y: -10000,
      width: 1280,
      height: 800,
    }).then(() => {
      // Give the page a moment to load, then inject color override script
      setTimeout(() => {
        invoke("eval_web_tab_script", { label, script: COLOR_OVERRIDE_SCRIPT });
      }, 2000);
    });
    return () => {
      invoke("close_web_tab_view", { label });
    };
  }, [label, plugin.dev_url]);

  // Reposition the webview whenever the active state or window size changes.
  useLayoutEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    if (!active) {
      // Slide off-screen without destroying it so the session stays alive.
      invoke("set_web_tab_bounds", {
        label,
        x: -10000,
        y: -10000,
        width: 1280,
        height: 800,
      });
      return;
    }

    const updateBounds = () => {
      const r = container.getBoundingClientRect();
      if (r.width > 0 && r.height > 0) {
        invoke("set_web_tab_bounds", {
          label,
          x: r.x,
          y: r.y,
          width: r.width,
          height: r.height,
        });
      }
    };

    updateBounds();
    const observer = new ResizeObserver(updateBounds);
    observer.observe(container);
    return () => observer.disconnect();
  }, [active, label]);

  return <div ref={containerRef} className="w-full h-full" />;
}

function PluginTab({ plugin, active, reloadKey, fontScale, contrast }: { plugin: Plugin; active: boolean; reloadKey: number; fontScale: number; contrast: number }) {
  // Web tabs: external URL stored as dev_url with empty folder_path/entry.
  // Use a child webview to bypass X-Frame-Options restrictions.
  if (!plugin.folder_path && !plugin.entry) {
    return <WebTabFrame plugin={plugin} active={active} />;
  }
  // Dev-server plugins: load the live localhost URL directly.
  // Static plugins: serve files through the custom plugin:// protocol.
  const src = plugin.dev_url ?? `plugin://${plugin.id}/${plugin.entry}`;
  const iframeRef = useRef<HTMLIFrameElement>(null);

  // When this tab becomes active, focus the iframe so its window.focus event
  // fires and the plugin can auto-focus its own input.
  useEffect(() => {
    if (active) iframeRef.current?.focus();
  }, [active]);

  return (
    <iframe
      key={reloadKey}
      ref={iframeRef}
      src={src}
      className="w-full h-full border-none"
      title={plugin.name}
      onLoad={() => {
        iframeRef.current?.contentWindow?.postMessage({ type: "caden-font-scale", scale: fontScale }, "*");
        iframeRef.current?.contentWindow?.postMessage({ type: "caden-contrast", contrast }, "*");
        // Send current theme colors
        const style = getComputedStyle(document.documentElement);
        const colors: Record<string, string> = {};
        for (const prop of Object.keys(cadenColorDefaults as Record<string, string>)) {
          colors[prop] = style.getPropertyValue(prop).trim();
        }
        iframeRef.current?.contentWindow?.postMessage({ type: "caden-theme-colors", colors }, "*");
        // Inject color override script into dev-server iframes
        try {
          const doc = iframeRef.current?.contentDocument;
          if (doc && !doc.getElementById("caden-color-override-script")) {
            const s = doc.createElement("script");
            s.id = "caden-color-override-script";
            s.textContent = COLOR_OVERRIDE_SCRIPT;
            doc.body.appendChild(s);
          }
        } catch (_) { /* cross-origin — static plugins handled by Rust injection */ }
      }}
    />
  );
}

function TabButton({
  label,
  active,
  onClick,
  onDragStart,
  onDrop,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
  onDragStart?: () => void;
  onDrop?: () => void;
}) {
  return (
    <button
      draggable={!!onDragStart}
      onClick={onClick}
      onDragStart={(e) => { e.dataTransfer.effectAllowed = "move"; onDragStart?.(); }}
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => { e.preventDefault(); onDrop?.(); }}
      className={`
        px-5 py-2.5 text-xs font-mono tracking-widest uppercase
        border-b-2 transition-colors duration-150 cursor-pointer select-none
        ${
          active
            ? "border-accent-DEFAULT text-text"
            : "border-transparent text-text-dim hover:text-text-muted"
        }
      `}
    >
      {label}
    </button>
  );
}
