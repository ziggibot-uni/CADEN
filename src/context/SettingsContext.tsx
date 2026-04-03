import { createContext, useContext } from "react";
import type { AppSettings } from "../types";

const defaults: AppSettings = {
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
};

export const SettingsContext = createContext<AppSettings>(defaults);

export function useSettings(): AppSettings {
  return useContext(SettingsContext);
}
