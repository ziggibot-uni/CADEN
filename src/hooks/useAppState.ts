import { useState, useEffect, useCallback } from "react";
import { invoke } from "@tauri-apps/api/core";
import type {
  AppSettings,
  OllamaStatus,
  PlanItem,
  PlannerContext,
  SyncStatus,
  UpcomingItem,
} from "../types";

const DEFAULT_SETTINGS: AppSettings = {
  google_connected: false,
  moodle_url: null,
  moodle_token: null,
  ollama_model: "llama3.1:8b",
  system_prompt: "",
  task_duration_minutes: 45,
  setup_complete: false,
};

export function useAppState() {
  const [settings, setSettings] = useState<AppSettings>(DEFAULT_SETTINGS);
  const [planItems, setPlanItems] = useState<PlanItem[]>([]);
  const [upcomingItems, setUpcomingItems] = useState<UpcomingItem[]>([]);
  const [ollamaStatus, setOllamaStatus] = useState<OllamaStatus>({
    online: false,
    model: null,
    checking: true,
  });
  const [syncStatus, setSyncStatus] = useState<SyncStatus>({
    last_sync: null,
    syncing: false,
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

  // Full sync
  const sync = useCallback(async () => {
    if (syncStatus.syncing) return;
    setSyncStatus((prev) => ({ ...prev, syncing: true }));
    try {
      await invoke("sync_all");
      await Promise.all([loadPlan(), loadUpcoming()]);
      setSyncStatus({ last_sync: new Date().toISOString(), syncing: false });
    } catch {
      setSyncStatus((prev) => ({ ...prev, syncing: false }));
    }
  }, [syncStatus.syncing, loadPlan, loadUpcoming]);

  // Initial load after initialization
  useEffect(() => {
    if (!initialized) return;
    checkOllama();
    loadPlan();
    loadUpcoming();
  }, [initialized, checkOllama, loadPlan, loadUpcoming]);

  // Periodic refresh: Ollama every 30s, sync every 15 min
  useEffect(() => {
    const ollamaTimer = setInterval(checkOllama, 30_000);
    const syncTimer = setInterval(sync, 15 * 60_000);
    return () => {
      clearInterval(ollamaTimer);
      clearInterval(syncTimer);
    };
  }, [checkOllama, sync]);

  function markItemComplete(id: string) {
    setPlanItems((prev) =>
      prev.map((item) =>
        item.id === id
          ? { ...item, completed: true, completed_at: new Date().toISOString() }
          : item
      )
    );
  }

  // Build context for Ollama
  const plannerContext: PlannerContext = {
    date: new Date().toISOString(),
    plan_items: planItems,
    upcoming_deadlines: upcomingItems.slice(0, 3),
    recent_completions: planItems
      .filter((i) => i.completed)
      .slice(-3),
  };

  return {
    settings,
    setSettings,
    planItems,
    upcomingItems,
    ollamaStatus,
    syncStatus,
    plannerContext,
    initialized,
    checkOllama,
    sync,
    markItemComplete,
  };
}
