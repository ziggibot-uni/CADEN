import { useState, useEffect, useCallback } from "react";
import { useSettings } from "../context/SettingsContext";
import ChatPanel from "./pedalmanifest/ChatPanel";
import AudioPanel from "./pedalmanifest/AudioPanel";
import FrequencyResponse from "./pedalmanifest/FrequencyResponse";
import ControlPanel from "./pedalmanifest/ControlPanel";
import KeeperPanel from "./pedalmanifest/KeeperPanel";
import InventoryPanel from "./pedalmanifest/InventoryPanel";
import { fetchStatus, getCurrentDesign } from "./pedalmanifest/api";

interface FreqPoint {
  frequency: number;
  magnitude: number;
}

interface Pot {
  stage_index?: number;
  param_name?: string;
  name?: string;
  label?: string;
  value?: number;
  default?: number;
  min?: number;
  max?: number;
  step?: number;
}

interface Design {
  stages?: unknown[];
  pots?: Pot[];
  controls?: Pot[];
  frequency_response?: FreqPoint[];
  freq_response?: FreqPoint[];
  schematic?: string;
  schematic_svg?: string;
}

interface AudioStatus {
  waveform?: number[];
}

export default function PedalManifestPanel() {
  const { active_model } = useSettings();
  const [ollamaStatus, setOllamaStatus] = useState<"online" | "offline">("offline");
  const [audioStatus, setAudioStatus] = useState<"online" | "offline">("offline");
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);
  const [design, setDesign] = useState<Design | null>(null);
  const [bypassed, setBypassed] = useState(false);
  const [activeTab, setActiveTab] = useState<"schematic" | "inventory" | "keepers">("schematic");
  const [waveformData, setWaveformData] = useState<number[]>([]);

  // Poll backend status
  useEffect(() => {
    const checkStatus = async () => {
      try {
        const status = await fetchStatus() as Record<string, unknown>;
        setBackendOnline(true);
        setOllamaStatus(status.ollama_available ? "online" : "offline");
        setAudioStatus(status.audio_running ? "online" : "offline");
      } catch {
        setBackendOnline(false);
        setOllamaStatus("offline");
        setAudioStatus("offline");
      }
    };
    checkStatus();
    const interval = setInterval(checkStatus, 5000);
    return () => clearInterval(interval);
  }, []);

  // Load current design
  useEffect(() => {
    if (!backendOnline) return;
    getCurrentDesign()
      .then((data) => {
        const d = data as Design;
        if (d && (d.stages || d.pots || d.frequency_response)) setDesign(d);
      })
      .catch(() => {});
  }, [backendOnline]);

  const handleDesignUpdate = useCallback((data: unknown) => {
    if (data) setDesign(data as Design);
  }, []);

  const handleKeeperLoad = useCallback((data: unknown) => {
    const d = data as Record<string, unknown>;
    if (d?.design || d?.circuit) {
      setDesign((d.design || d.circuit || d) as Design);
    }
  }, []);

  const handleAudioStatus = useCallback((status: AudioStatus) => {
    if (status.waveform) setWaveformData(status.waveform);
  }, []);

  const pots: Pot[] = design?.pots || design?.controls || [];
  const freqData: FreqPoint[] = design?.frequency_response || design?.freq_response || [];
  const schematicSvg: string = design?.schematic || design?.schematic_svg || "";

  // Offline state
  if (backendOnline === false) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3 text-text-dim">
        <div className="text-2xl opacity-30">⚡</div>
        <div className="text-sm">PedalManifest backend offline</div>
        <div className="text-xs opacity-50">Start the Python server at localhost:8000</div>
      </div>
    );
  }

  if (backendOnline === null) {
    return (
      <div className="flex items-center justify-center h-full text-text-dim text-xs animate-pulse">
        connecting...
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full bg-surface text-sm select-text overflow-hidden">
      {/* Top bar */}
      <div className="flex items-center gap-4 px-4 py-2 border-b border-surface-2 flex-shrink-0">
        <span className="text-xs font-bold tracking-widest text-accent-DEFAULT opacity-80">PEDALMANIFEST</span>
        <div className="flex items-center gap-3">
          <StatusDot label="Ollama" status={ollamaStatus} />
          <StatusDot label="Audio" status={audioStatus} />
        </div>
        <div className="ml-auto">
          <AudioPanel onStatusChange={handleAudioStatus} />
        </div>
      </div>

      {/* Main content */}
      <div className="flex flex-1 min-h-0">
        {/* Left: Chat */}
        <div className="w-72 flex-shrink-0 border-r border-surface-2 flex flex-col min-h-0">
          <ChatPanel onDesignUpdate={handleDesignUpdate} model={active_model} />
        </div>

        {/* Right: Viz + controls + tabs */}
        <div className="flex-1 flex flex-col min-w-0 min-h-0">
          {/* Frequency + Waveform */}
          <div className="flex gap-2 px-4 pt-3 pb-2 flex-shrink-0">
            <div className="flex-1 min-w-0">
              <FrequencyResponse data={freqData} />
            </div>
            <div className="w-44 flex-shrink-0">
              <svg viewBox="0 0 300 120" preserveAspectRatio="xMidYMid meet" className="w-full">
                <line x1="0" y1="60" x2="300" y2="60" stroke="rgb(var(--c-surface-2))" strokeWidth="0.5" />
                <line x1="0" y1="30" x2="300" y2="30" stroke="rgb(var(--c-surface-2))" strokeWidth="0.5" />
                <line x1="0" y1="90" x2="300" y2="90" stroke="rgb(var(--c-surface-2))" strokeWidth="0.5" />
                {waveformData.length > 0 ? (
                  <polyline
                    fill="none"
                    stroke="rgb(var(--c-accent))"
                    strokeWidth="1.5"
                    points={waveformData.map((v, i) => `${(i / waveformData.length) * 300},${60 - v * 55}`).join(" ")}
                  />
                ) : (
                  <text x="150" y="64" textAnchor="middle" fill="rgb(var(--c-text-dim))" fontSize="11" opacity="0.4">
                    No signal
                  </text>
                )}
              </svg>
              <div className="text-[10px] text-text-dim opacity-40 text-center mt-0.5">Waveform</div>
            </div>
          </div>

          {/* Controls */}
          <div className="px-4 py-2 border-t border-surface-2 flex-shrink-0">
            <ControlPanel pots={pots} bypassed={bypassed} onBypassChange={setBypassed} />
          </div>

          {/* Tabs */}
          <div className="flex-1 flex flex-col min-h-0 border-t border-surface-2">
            <div className="flex border-b border-surface-2 flex-shrink-0">
              {(["schematic", "inventory", "keepers"] as const).map((tab) => (
                <button
                  key={tab}
                  onClick={() => setActiveTab(tab)}
                  className={`px-4 py-2 text-xs font-medium transition-colors ${
                    activeTab === tab
                      ? "text-accent-DEFAULT border-b-2 border-accent-DEFAULT"
                      : "text-text-dim hover:text-text"
                  }`}
                >
                  {tab.charAt(0).toUpperCase() + tab.slice(1)}
                </button>
              ))}
            </div>
            <div className="flex-1 overflow-hidden">
              {activeTab === "schematic" && (
                <div className="h-full overflow-y-auto p-4">
                  {schematicSvg ? (
                    <div dangerouslySetInnerHTML={{ __html: schematicSvg }} />
                  ) : (
                    <div className="text-text-dim text-xs opacity-40 text-center pt-10">
                      No schematic yet. Use chat to design a circuit.
                    </div>
                  )}
                </div>
              )}
              {activeTab === "inventory" && (
                <div className="h-full overflow-hidden">
                  <InventoryPanel />
                </div>
              )}
              {activeTab === "keepers" && (
                <div className="h-full overflow-hidden">
                  <KeeperPanel onLoad={handleKeeperLoad} />
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function StatusDot({ label, status }: { label: string; status: "online" | "offline" }) {
  return (
    <div className="flex items-center gap-1.5 text-[10px] text-text-dim">
      <span
        className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
          status === "online" ? "bg-status-success" : "bg-surface-3"
        }`}
      />
      {label}
    </div>
  );
}
