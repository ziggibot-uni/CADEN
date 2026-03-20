import { useState, useEffect } from "react";
import { TodayPanel } from "./components/TodayPanel";
import { ChatPanel } from "./components/ChatPanel";
import { UpcomingPanel } from "./components/UpcomingPanel";
import { BottomBar } from "./components/BottomBar";
import { SettingsPanel } from "./components/SettingsPanel";
import { FirstRunWizard } from "./components/FirstRunWizard";
import { useAppState } from "./hooks/useAppState";

export default function App() {
  const {
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
    reorderItems,
  } = useAppState();

  // Apply font scale to root element whenever it changes
  useEffect(() => {
    document.documentElement.style.setProperty(
      "--font-scale",
      String(settings.font_scale ?? 1.0)
    );
  }, [settings.font_scale]);

  const [showSettings, setShowSettings] = useState(false);

  // Show first-run wizard if not set up
  if (initialized && !settings.setup_complete) {
    return (
      <FirstRunWizard
        onComplete={() => setSettings((s) => ({ ...s, setup_complete: true }))}
      />
    );
  }

  return (
    <div className="flex flex-col h-screen bg-surface overflow-hidden">
      {/* Main layout: three panels */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left — Today's Plan (30%) */}
        <div className="w-[30%] flex flex-col overflow-hidden">
          <TodayPanel items={planItems} onItemCompleted={markItemComplete} onReorder={reorderItems} />
        </div>

        {/* Center — CADEN Chat (50%) */}
        <div className="w-[50%] flex flex-col overflow-hidden border-l border-surface-2">
          <ChatPanel
            ollamaStatus={ollamaStatus}
            context={plannerContext}
            onRetryOllama={checkOllama}
          />
        </div>

        {/* Right — Upcoming (20%) */}
        <div className="w-[20%] flex flex-col overflow-hidden border-l border-surface-2">
          <UpcomingPanel items={upcomingItems} />
        </div>
      </div>

      {/* Bottom bar */}
      <BottomBar
        ollamaStatus={ollamaStatus}
        syncStatus={syncStatus}
        onSettingsClick={() => setShowSettings(true)}
        onSyncClick={sync}
      />

      {/* Settings overlay */}
      {showSettings && (
        <SettingsPanel
          settings={settings}
          onClose={() => setShowSettings(false)}
          onSettingsChange={setSettings}
        />
      )}
    </div>
  );
}
