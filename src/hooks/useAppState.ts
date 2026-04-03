import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { hexToRgb } from "../../caden-colors.js";
import type {
  AppSettings,
  OllamaStatus,
  PlanItem,
  PlannerContext,
  Plugin,
  SyncOutcome,
  SyncStatus,
  UpcomingItem,
} from "../types";

const DEFAULT_SETTINGS: AppSettings = {
  google_connected: false,
  moodle_url: null,
  moodle_token: null,
  active_model: "qwen3:14b",
  github_pat: "",
  groq_keys: [],
  openrouter_key: "",
  system_prompt: "",
  task_duration_minutes: 45,
  creative_time_minutes: 120,
  font_scale: 1.0,
  contrast: 1.0,
  setup_complete: false,
  work_hours: { mon: { start: 8, end: 22 }, tue: { start: 8, end: 22 }, wed: { start: 8, end: 22 }, thu: { start: 8, end: 22 }, fri: { start: 8, end: 22 }, sat: null, sun: null },
  morning_meds: [],
  evening_meds: [],
};

export function useAppState() {
  const [settings, setSettings] = useState<AppSettings>(DEFAULT_SETTINGS);
  const [planItems, setPlanItems] = useState<PlanItem[]>([]);
  const [upcomingItems, setUpcomingItems] = useState<UpcomingItem[]>([]);
  const [plugins, setPlugins] = useState<Plugin[]>([]);
  const [ollamaStatus, setOllamaStatus] = useState<OllamaStatus>({
    online: false,
    model: null,
    checking: true,
  });
  const [syncStatus, setSyncStatus] = useState<SyncStatus>({
    last_sync: null,
    syncing: false,
    gcal_error: null,
  });
  const [initialized, setInitialized] = useState(false);

  // Load initial state
  useEffect(() => {
    async function init() {
      try {
        const s = await invoke<AppSettings>("get_settings");
        setSettings(s);
      } catch {
        // Use defaults
      }
      try {
        const p = await invoke<Plugin[]>("list_plugins");
        setPlugins(p);
      } catch {
        // No plugins yet
      }
      // Load saved theme colors
      try {
        const raw = await invoke<string | null>("get_setting_value", { key: "theme_colors" });
        if (raw) {
          const colors: Record<string, string> = JSON.parse(raw);
          for (const [key, val] of Object.entries(colors)) {
            // Saved colors are hex — CSS vars need "R G B" format
            const rgb = val.startsWith("#") ? hexToRgb(val) : val;
            document.documentElement.style.setProperty(key, rgb);
          }
        }
      } catch {
        // Use CSS defaults
      }
      setInitialized(true);
    }
    init();
  }, []);

  // Check Ollama status
  const checkOllama = useCallback(async () => {
    setOllamaStatus((prev) => ({ ...prev, checking: true }));
    try {
      const result = await invoke<{ online: boolean; model: string | null }>(
        "get_ollama_status"
      );
      setOllamaStatus({ ...result, checking: false });
    } catch {
      setOllamaStatus({ online: false, model: null, checking: false });
    }
  }, []);

  // Load today's plan
  const loadPlan = useCallback(async () => {
    try {
      const items = await invoke<PlanItem[]>("get_today_plan");
      setPlanItems(items);
    } catch {
      // Keep existing
    }
  }, []);

  // Load upcoming items
  const loadUpcoming = useCallback(async () => {
    try {
      const items = await invoke<UpcomingItem[]>("get_upcoming_items");
      setUpcomingItems(items);
    } catch {
      // Keep existing
    }
  }, []);

  const syncingRef = useRef(false);

  // Full sync — returns outcome with replanned flag and any GCal error
  const sync = useCallback(async () => {
    if (syncingRef.current) return;
    syncingRef.current = true;
    setSyncStatus((prev) => ({ ...prev, syncing: true, gcal_error: null }));
    let outcome: SyncOutcome = { replanned: false, events_changed: false, gcal_error: null };
    try {
      outcome = await invoke<SyncOutcome>("sync_all");
    } catch (e) {
      console.error("sync_all failed:", e);
    } finally {
      if (outcome.replanned || outcome.events_changed) {
        await Promise.all([loadPlan(), loadUpcoming()]);
      }
      setSyncStatus((prev) => ({
        last_sync: outcome.gcal_error ? prev.last_sync : new Date().toISOString(),
        syncing: false,
        gcal_error: outcome.gcal_error,
      }));
      syncingRef.current = false;
    }
  }, [loadPlan, loadUpcoming]);

  // On startup: load whatever is in the DB immediately so the UI isn't blank,
  // then always fire a full sync. The backend fingerprint gate ensures we only
  // replan when data has actually changed, so this is safe to do every launch.
  useEffect(() => {
    if (!initialized) return;
    checkOllama();
    loadPlan();
    loadUpcoming();
    sync();
  }, [initialized]); // eslint-disable-line react-hooks/exhaustive-deps

  // Background poll for Ollama status only — sync is driven by the backend
  // tokio loop (every 15 min) which emits "caden-sync-complete". This keeps
  // sync alive even when the webview is frozen or minimised.
  useEffect(() => {
    const ollamaTimer = setInterval(checkOllama, 30_000);
    return () => { clearInterval(ollamaTimer); };
  }, [checkOllama]);

  // Listen for backend-driven sync completions and refresh the UI.
  useEffect(() => {
    const unlisten = listen<SyncOutcome>("caden-sync-complete", async (event) => {
      const outcome = event.payload;
      if (outcome.replanned || outcome.events_changed) {
        await Promise.all([loadPlan(), loadUpcoming()]);
      }
      setSyncStatus((prev) => ({
        last_sync: outcome.gcal_error ? prev.last_sync : new Date().toISOString(),
        syncing: false,
        gcal_error: outcome.gcal_error,
      }));
    });
    return () => { unlisten.then((f) => f()); };
  }, [loadPlan, loadUpcoming]);

  function markItemComplete(id: string) {
    setPlanItems((prev) =>
      prev.map((item) =>
        item.id === id
          ? { ...item, completed: true, completed_at: new Date().toISOString() }
          : item
      )
    );
  }

  function unmarkItemComplete(id: string) {
    setPlanItems((prev) =>
      prev.map((item) =>
        item.id === id ? { ...item, completed: false, completed_at: null } : item
      )
    );
  }

  function reorderItems(newOrder: PlanItem[]) {
    setPlanItems(newOrder);
  }

  function updatePlanItem(id: string, updates: Partial<PlanItem>) {
    setPlanItems((prev) =>
      prev.map((item) => (item.id === id ? { ...item, ...updates } : item))
    );
  }

  const clearCompleted = useCallback(async () => {
    try {
      await invoke("clear_completed_plan_items");
      await loadPlan();
    } catch {
      // ignore
    }
  }, [loadPlan]);

  function addPlugin(plugin: Plugin) {
    setPlugins((prev) => [...prev, plugin]);
  }

  function removePlugin(id: string) {
    setPlugins((prev) => prev.filter((p) => p.id !== id));
  }

  function deleteItem(id: string) {
    setPlanItems((prev) => prev.filter((item) => item.id !== id));
  }

  const plannerContext: PlannerContext = useMemo(() => ({
    date: new Date().toISOString(),
    plan_items: planItems.filter((i) => !i.completed),
    upcoming_deadlines: upcomingItems.slice(0, 3),
    recent_completions: planItems.filter((i) => i.completed).slice(-3),
  }), [planItems, upcomingItems]);

  return {
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
  };
}
