import { useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import type { AppSettings } from "../types";

interface Props {
  settings: AppSettings;
  onClose: () => void;
  onSettingsChange: (settings: AppSettings) => void;
}

const DEFAULT_SYSTEM_PROMPT = `You are CADEN — Chaos Aiming and Distress Evasion Navigator. You are a personal executive function assistant for a user with ADHD, bipolar disorder, and autism. Your job is to cut through cognitive chaos and give clear, direct, actionable output.

Rules:
- Never use filler phrases like 'Great question' or 'Certainly'
- Be honest even when the answer is uncomfortable
- Prioritize ruthlessly — not everything is urgent, say so
- Keep responses short unless detail is specifically needed
- When the user is overwhelmed, help them pick ONE thing to do next
- You have access to their calendar, tasks, and assignments. Reference them by name.
- Speak like a calm, competent friend who actually gets it — not a therapist, not a robot`;

export function SettingsPanel({ settings, onClose, onSettingsChange }: Props) {
  const [form, setForm] = useState<AppSettings>(settings);
  const [googleClientId, setGoogleClientId] = useState("");
  const [googleClientSecret, setGoogleClientSecret] = useState("");
  const [saving, setSaving] = useState(false);
  const [testingMoodle, setTestingMoodle] = useState(false);
  const [moodleResult, setMoodleResult] = useState<string | null>(null);

  // Load existing Google credentials on mount
  useState(() => {
    invoke<string | null>("get_setting_value", { key: "google_client_id" })
      .then((v) => { if (v) setGoogleClientId(v); })
      .catch(() => {});
    invoke<string | null>("get_setting_value", { key: "google_client_secret" })
      .then((v) => { if (v) setGoogleClientSecret(v); })
      .catch(() => {});
  });

  async function handleSave() {
    setSaving(true);
    try {
      await invoke("save_settings", { settings: form });
      // Save Google credentials separately (not in the main AppSettings struct)
      if (googleClientId)
        await invoke("set_setting_value", { key: "google_client_id", value: googleClientId });
      if (googleClientSecret)
        await invoke("set_setting_value", { key: "google_client_secret", value: googleClientSecret });
      onSettingsChange(form);
      onClose();
    } catch (err) {
      console.error("Save failed:", err);
    } finally {
      setSaving(false);
    }
  }

  async function handleGoogleConnect() {
    try {
      await invoke("start_google_oauth");
    } catch (err) {
      console.error("Google OAuth failed:", err);
    }
  }

  async function handleMoodleTest() {
    setTestingMoodle(true);
    setMoodleResult(null);
    try {
      await invoke("test_moodle_connection", {
        url: form.moodle_url,
        token: form.moodle_token,
      });
      setMoodleResult("Connected.");
    } catch (err) {
      setMoodleResult("Connection failed. Check URL and token.");
    } finally {
      setTestingMoodle(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 animate-fade-in">
      <div className="bg-surface-1 border border-surface-3 rounded-lg w-[600px] max-h-[80vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-surface-2">
          <div className="text-text font-light">Settings</div>
          <button onClick={onClose} className="text-text-dim hover:text-text transition-colors">
            ✕
          </button>
        </div>

        <div className="px-6 py-5 flex flex-col gap-6">
          {/* Ollama */}
          <section>
            <div className="text-[11px] font-mono uppercase tracking-widest text-text-dim mb-3">
              Ollama
            </div>
            <div className="flex flex-col gap-3">
              <label className="flex flex-col gap-1">
                <span className="text-xs text-text-muted">Model</span>
                <input
                  className="input-field"
                  value={form.ollama_model}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, ollama_model: e.target.value }))
                  }
                  placeholder="llama3.1:8b"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs text-text-muted">System prompt</span>
                <textarea
                  className="input-field font-mono text-xs min-h-[120px] resize-y"
                  value={form.system_prompt}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, system_prompt: e.target.value }))
                  }
                />
                <button
                  className="text-[11px] text-text-dim hover:text-text text-left"
                  onClick={() =>
                    setForm((f) => ({ ...f, system_prompt: DEFAULT_SYSTEM_PROMPT }))
                  }
                >
                  Reset to default
                </button>
              </label>
            </div>
          </section>

          {/* Google */}
          <section>
            <div className="text-[11px] font-mono uppercase tracking-widest text-text-dim mb-3">
              Google Account
            </div>
            <div className="flex flex-col gap-3">
              <label className="flex flex-col gap-1">
                <span className="text-xs text-text-muted">
                  OAuth Client ID{" "}
                  <a
                    className="text-accent-DEFAULT underline"
                    href="https://console.cloud.google.com/apis/credentials"
                    target="_blank"
                    rel="noreferrer"
                  >
                    (Google Cloud Console)
                  </a>
                </span>
                <input
                  className="input-field font-mono text-xs"
                  value={googleClientId}
                  onChange={(e) => setGoogleClientId(e.target.value)}
                  placeholder="123456789-abc.apps.googleusercontent.com"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs text-text-muted">OAuth Client Secret</span>
                <input
                  type="password"
                  className="input-field font-mono text-xs"
                  value={googleClientSecret}
                  onChange={(e) => setGoogleClientSecret(e.target.value)}
                  placeholder="GOCSPX-••••••••••••"
                />
              </label>
              <div className="text-[10px] text-text-dim leading-relaxed">
                Enable Calendar API and Tasks API in your Google Cloud project.
                Set the redirect URI to{" "}
                <span className="font-mono">http://localhost:42813/callback</span>
              </div>
              <div className="flex items-center gap-3">
                <span
                  className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                    settings.google_connected ? "bg-[#2d6b61]" : "bg-[#4a4a4a]"
                  }`}
                />
                <span className="text-xs text-text-muted">
                  {settings.google_connected ? "Connected" : "Not connected"}
                </span>
                <button className="btn-ghost text-xs ml-auto" onClick={handleGoogleConnect}>
                  {settings.google_connected ? "Reconnect" : "Connect"}
                </button>
              </div>
            </div>
          </section>

          {/* Moodle */}
          <section>
            <div className="text-[11px] font-mono uppercase tracking-widest text-text-dim mb-3">
              Edvance / Moodle
            </div>
            <div className="flex flex-col gap-3">
              <label className="flex flex-col gap-1">
                <span className="text-xs text-text-muted">Moodle URL</span>
                <input
                  className="input-field font-mono text-xs"
                  value={form.moodle_url ?? ""}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, moodle_url: e.target.value || null }))
                  }
                  placeholder="https://edvance.nmu.ac.za"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs text-text-muted">
                  Token (from Profile › Security keys)
                </span>
                <input
                  type="password"
                  className="input-field font-mono text-xs"
                  value={form.moodle_token ?? ""}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, moodle_token: e.target.value || null }))
                  }
                  placeholder="••••••••••••"
                />
              </label>
              <div className="flex items-center gap-3">
                <button
                  className="btn-ghost text-xs"
                  onClick={handleMoodleTest}
                  disabled={testingMoodle || !form.moodle_url || !form.moodle_token}
                >
                  {testingMoodle ? "Testing…" : "Test connection"}
                </button>
                {moodleResult && (
                  <span
                    className={`text-xs ${
                      moodleResult === "Connected." ? "text-[#4a9b8e]" : "text-[#c0392b]"
                    }`}
                  >
                    {moodleResult}
                  </span>
                )}
              </div>
            </div>
          </section>

          {/* Display */}
          <section>
            <div className="text-[11px] font-mono uppercase tracking-widest text-text-dim mb-3">
              Display
            </div>
            <label className="flex flex-col gap-2">
              <div className="flex items-center justify-between">
                <span className="text-xs text-text-muted">Text size</span>
                <span className="text-xs font-mono text-text-dim">
                  {Math.round((form.font_scale ?? 1.0) * 100)}%
                </span>
              </div>
              <input
                type="range"
                min={0.8}
                max={1.6}
                step={0.05}
                className="w-full accent-accent"
                value={form.font_scale ?? 1.0}
                onChange={(e) => {
                  const scale = parseFloat(e.target.value);
                  setForm((f) => ({ ...f, font_scale: scale }));
                  // Live preview
                  document.documentElement.style.setProperty("--font-scale", String(scale));
                }}
              />
              <div className="flex justify-between text-[10px] text-text-dim font-mono">
                <span>80%</span>
                <span>100%</span>
                <span>160%</span>
              </div>
            </label>
          </section>

          {/* Planner */}
          <section>
            <div className="text-[11px] font-mono uppercase tracking-widest text-text-dim mb-3">
              Planner
            </div>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-text-muted">
                Default task duration (minutes)
              </span>
              <input
                type="number"
                min={15}
                max={120}
                step={5}
                className="input-field w-32"
                value={form.task_duration_minutes}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    task_duration_minutes: parseInt(e.target.value) || 45,
                  }))
                }
              />
            </label>
          </section>
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-2 px-6 py-4 border-t border-surface-2">
          <button className="btn-ghost text-sm" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn-primary text-sm"
            onClick={handleSave}
            disabled={saving}
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
