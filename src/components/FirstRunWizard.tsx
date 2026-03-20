import { useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import type { WizardStep } from "../types";

interface Props {
  onComplete: () => void;
}

export function FirstRunWizard({ onComplete }: Props) {
  const [step, setStep] = useState<WizardStep>("ollama_check");
  const [checking, setChecking] = useState(false);
  const [pulling, setPulling] = useState(false);
  const [pullProgress, setPullProgress] = useState("");
  const [moodleUrl, setMoodleUrl] = useState("");
  const [moodleToken, setMoodleToken] = useState("");
  const [moodleTesting, setMoodleTesting] = useState(false);
  const [moodleError, setMoodleError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function checkOllama() {
    setChecking(true);
    setError(null);
    try {
      const ok = await invoke<boolean>("check_ollama");
      if (ok) {
        setStep("ollama_pull");
      } else {
        setError("Ollama not detected. Install it and try again.");
      }
    } catch {
      setError("Could not reach Ollama.");
    } finally {
      setChecking(false);
    }
  }

  async function pullModel() {
    setPulling(true);
    setPullProgress("Starting…");
    setError(null);
    try {
      await invoke("pull_ollama_model", { model: "llama3.1:8b" });
      setStep("google_auth");
    } catch (err) {
      setError(`Pull failed: ${err}`);
    } finally {
      setPulling(false);
      setPullProgress("");
    }
  }

  async function connectGoogle() {
    try {
      await invoke("start_google_oauth");
      // OAuth callback will resolve — move on
      setStep("moodle_setup");
    } catch (err) {
      setError("Google auth failed. You can skip this and connect later.");
    }
  }

  function skipGoogle() {
    setStep("moodle_setup");
  }

  async function testMoodle() {
    setMoodleTesting(true);
    setMoodleError(null);
    try {
      await invoke("test_moodle_connection", {
        url: moodleUrl,
        token: moodleToken,
      });
      await invoke("save_moodle_credentials", {
        url: moodleUrl,
        token: moodleToken,
      });
      setStep("done");
    } catch {
      setMoodleError("Connection failed. Double-check URL and token.");
    } finally {
      setMoodleTesting(false);
    }
  }

  function skipMoodle() {
    setStep("done");
  }

  async function finish() {
    await invoke("mark_setup_complete");
    onComplete();
  }

  return (
    <div className="fixed inset-0 bg-surface flex items-center justify-center">
      <div className="w-[480px] flex flex-col gap-6">
        {/* Step indicator */}
        <div className="flex items-center gap-2">
          {(["ollama_check", "ollama_pull", "google_auth", "moodle_setup", "done"] as WizardStep[]).map(
            (s, i) => (
              <div key={s} className="flex items-center gap-2">
                <div
                  className={`w-1.5 h-1.5 rounded-full ${
                    s === step
                      ? "bg-accent-DEFAULT"
                      : i < ["ollama_check", "ollama_pull", "google_auth", "moodle_setup", "done"].indexOf(step)
                        ? "bg-accent-dim"
                        : "bg-surface-3"
                  }`}
                />
                {i < 4 && <div className="w-6 h-px bg-surface-3" />}
              </div>
            )
          )}
        </div>

        {/* Step content */}
        {step === "ollama_check" && (
          <WizardStep
            title="First, let's check for Ollama"
            body="CADEN's brain runs locally via Ollama. We need it installed before we can do anything else."
            extra={
              <div className="bg-surface-2 rounded p-3 font-mono text-xs text-text-muted leading-relaxed">
                curl -fsSL https://ollama.com/install.sh | sh
                <CopyButton text="curl -fsSL https://ollama.com/install.sh | sh" />
              </div>
            }
            primaryLabel={checking ? "Checking…" : "I've installed it — check"}
            onPrimary={checkOllama}
            primaryDisabled={checking}
            error={error}
          />
        )}

        {step === "ollama_pull" && (
          <WizardStep
            title="Pulling the model"
            body="Downloading llama3.1:8b (~4.7GB). This only happens once."
            extra={
              pullProgress ? (
                <div className="text-xs text-text-muted font-mono">{pullProgress}</div>
              ) : null
            }
            primaryLabel={pulling ? "Pulling…" : "Download llama3.1:8b"}
            onPrimary={pullModel}
            primaryDisabled={pulling}
            error={error}
          />
        )}

        {step === "google_auth" && (
          <WizardStep
            title="Connect your Google account"
            body="This lets CADEN see your Calendar and Tasks. Your browser will open for Google's login page."
            primaryLabel="Connect Google"
            onPrimary={connectGoogle}
            secondaryLabel="Skip for now"
            onSecondary={skipGoogle}
            error={error}
          />
        )}

        {step === "moodle_setup" && (
          <WizardStep
            title="Connect Edvance"
            body="Enter your Moodle URL and security token. Find the token in your Moodle profile under Security keys."
            extra={
              <div className="flex flex-col gap-2">
                <input
                  className="input-field text-sm"
                  placeholder="https://edvance.nmu.ac.za"
                  value={moodleUrl}
                  onChange={(e) => setMoodleUrl(e.target.value)}
                />
                <input
                  type="password"
                  className="input-field text-sm font-mono"
                  placeholder="Your Moodle security token"
                  value={moodleToken}
                  onChange={(e) => setMoodleToken(e.target.value)}
                />
                {moodleError && (
                  <div className="text-[#c0392b] text-xs">{moodleError}</div>
                )}
              </div>
            }
            primaryLabel={moodleTesting ? "Testing…" : "Connect Edvance"}
            onPrimary={testMoodle}
            primaryDisabled={moodleTesting || !moodleUrl || !moodleToken}
            secondaryLabel="Skip for now"
            onSecondary={skipMoodle}
            error={error}
          />
        )}

        {step === "done" && (
          <WizardStep
            title="You're set up."
            body="CADEN is ready. Your plan will be generated now."
            primaryLabel="Open CADEN"
            onPrimary={finish}
          />
        )}
      </div>
    </div>
  );
}

// ─── Reusable step layout ────────────────────────────────────────────────────

interface WizardStepProps {
  title: string;
  body: string;
  extra?: React.ReactNode;
  primaryLabel: string;
  onPrimary: () => void;
  primaryDisabled?: boolean;
  secondaryLabel?: string;
  onSecondary?: () => void;
  error?: string | null;
}

function WizardStep({
  title,
  body,
  extra,
  primaryLabel,
  onPrimary,
  primaryDisabled,
  secondaryLabel,
  onSecondary,
  error,
}: WizardStepProps) {
  return (
    <div className="flex flex-col gap-5 animate-fade-in">
      <div>
        <div className="text-[11px] font-mono uppercase tracking-widest text-text-dim mb-2">
          CADEN Setup
        </div>
        <h2 className="text-xl font-light text-text leading-snug">{title}</h2>
        <p className="text-sm text-text-muted mt-2 leading-relaxed">{body}</p>
      </div>
      {extra}
      {error && <div className="text-[#c0392b] text-sm">{error}</div>}
      <div className="flex items-center gap-3">
        <button
          className="btn-primary text-sm"
          onClick={onPrimary}
          disabled={primaryDisabled}
        >
          {primaryLabel}
        </button>
        {secondaryLabel && onSecondary && (
          <button className="btn-ghost text-sm" onClick={onSecondary}>
            {secondaryLabel}
          </button>
        )}
      </div>
    </div>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <button
      onClick={copy}
      className="ml-2 text-text-dim hover:text-text transition-colors"
      title="Copy"
    >
      {copied ? "copied" : "copy"}
    </button>
  );
}
