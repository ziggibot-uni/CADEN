import type { OllamaStatus, SyncStatus } from "../types";
import { useSettings } from "../context/SettingsContext";

interface Props {
  ollamaStatus: OllamaStatus;
  syncStatus: SyncStatus;
  onSettingsClick: () => void;
  onRefreshClick: () => void;
}

function formatSyncTime(iso: string | null): string {
  if (!iso) return "never";
  const d = new Date(iso);
  const now = new Date();
  const diffMin = Math.floor((now.getTime() - d.getTime()) / 60000);
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", hour12: true });
}

export function BottomBar({
  ollamaStatus,
  syncStatus,
  onSettingsClick,
  onRefreshClick,
}: Props) {
  const { active_model } = useSettings();
  return (
    <div
      className="flex items-center justify-between px-4 py-2 border-t border-surface-2
        bg-surface text-[11px] text-text-dim font-mono"
    >
      {/* Left: refresh */}
      <button
        onClick={onRefreshClick}
        disabled={syncStatus.syncing}
        className="flex items-center gap-2 hover:text-text transition-colors duration-150 cursor-pointer"
        title="Refresh"
      >
        <span className={syncStatus.syncing ? "animate-spin" : ""}>
          <SyncIcon />
        </span>
        <span>
          {syncStatus.syncing
            ? "refreshing…"
            : syncStatus.gcal_error
              ? `⚠️ ${syncStatus.gcal_error}`
              : `synced ${formatSyncTime(syncStatus.last_sync)}`}
        </span>
      </button>

      {/* Center: model status */}
      <div className="flex items-center gap-1.5">
        <span
          className={`w-1.5 h-1.5 rounded-full ${
            ollamaStatus.checking
              ? "bg-urgency-med animate-pulse"
              : ollamaStatus.online
                ? "bg-status-success"
                : "bg-urgency-high"
          }`}
        />
        <span>
          {ollamaStatus.checking
            ? "checking…"
            : ollamaStatus.online
              ? active_model
              : "ollama offline"}
        </span>
      </div>

      {/* Right: settings */}
      <button
        onClick={onSettingsClick}
        className="hover:text-text transition-colors duration-150 cursor-pointer"
        aria-label="Settings"
      >
        <GearIcon />
      </button>
    </div>
  );
}

function SyncIcon() {
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 12 12"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
    >
      <path d="M10.5 2.5A5 5 0 1 0 11 6" />
      <path d="M10.5 2.5V5.5H7.5" />
    </svg>
  );
}

function GearIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 14 14"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <circle cx="7" cy="7" r="2" />
      <path d="M7 1v1M7 12v1M1 7h1M12 7h1M2.64 2.64l.71.71M10.65 10.65l.71.71M2.64 11.36l.71-.71M10.65 3.35l.71-.71" />
    </svg>
  );
}
