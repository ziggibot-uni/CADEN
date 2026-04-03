import { useState, useEffect, useCallback } from "react";
import InventoryPanel from "./components/InventoryPanel";
import WorkspacePanel from "./components/WorkspacePanel";
import DesignHistory from "./components/DesignHistory";

const TABS = [
  { id: "workspace", label: "Design" },
  { id: "inventory", label: "Inventory" },
  { id: "history", label: "History" },
];

export default function App() {
  const [tab, setTab] = useState("workspace");
  const [status, setStatus] = useState(null);

  useEffect(() => {
    const handler = (e) => {
      if (e.data?.type === "caden-font-scale")
        document.documentElement.style.setProperty("--font-scale", String(e.data.scale));
      if (e.data?.type === "caden-contrast")
        document.documentElement.style.setProperty("--contrast", String(e.data.contrast));
      if (e.data?.type === "caden-theme-colors" && e.data.colors) {
        for (const [key, val] of Object.entries(e.data.colors)) {
          document.documentElement.style.setProperty(key, val);
        }
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, []);

  const fetchStatus = useCallback(async () => {
    try {
      const r = await fetch("/api/status");
      setStatus(r.ok ? await r.json() : null);
    } catch {
      setStatus(null);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    const id = setInterval(fetchStatus, 6000);
    return () => clearInterval(id);
  }, [fetchStatus]);

  const online = status !== null;

  return (
    <div className="flex flex-col h-full bg-surface text-text overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-2 bg-surface-1 border-b border-surface-2 shrink-0">
        <span className="font-semibold tracking-wide text-accent text-sm">PedalManifest</span>
        <div className="w-px h-4 bg-surface-3" />
        <div className="flex gap-0.5">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`px-3 py-1 rounded text-sm transition-colors ${
                tab === t.id
                  ? "bg-surface-2 text-text"
                  : "text-text-muted hover:text-text hover:bg-surface-2/50"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
        <div className="flex-1" />
        <StatusDot status={status} online={online} />
      </div>

      <div className="flex-1 overflow-hidden">
        {tab === "workspace" && <WorkspacePanel status={status} online={online} />}
        {tab === "inventory" && <InventoryPanel />}
        {tab === "history" && <DesignHistory />}
      </div>
    </div>
  );
}

function StatusDot({ status, online }) {
  if (!online) return (
    <div className="flex items-center gap-1.5 text-xs text-text-muted">
      <span className="w-2 h-2 rounded-full bg-red-400 animate-pulse" />
      <span>backend offline</span>
    </div>
  );
  const items = [];
  if (status.ollama_available) items.push("AI");
  if (status.audio_running) items.push("audio");
  return (
    <div className="flex items-center gap-1.5 text-xs text-text-muted">
      <span className="w-2 h-2 rounded-full bg-green-400" />
      <span>{items.length ? items.join(" · ") : "online"}</span>
    </div>
  );
}
