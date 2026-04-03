import React, { useState, useEffect, useCallback } from 'react';
import ChatPanel from './components/ChatPanel';
import FrequencyResponse from './components/FrequencyResponse';
import ControlPanel from './components/ControlPanel';
import AudioPanel from './components/AudioPanel';
import InventoryPanel from './components/InventoryPanel';
import KeeperPanel from './components/KeeperPanel';
import { fetchStatus, getCurrentDesign } from './utils/api';

export default function App() {
  const [ollamaStatus, setOllamaStatus] = useState('offline');
  const [audioStatus, setAudioStatus] = useState('offline');
  const [design, setDesign] = useState(null);
  const [bypassed, setBypassed] = useState(false);
  const [activeTab, setActiveTab] = useState('schematic');
  const [waveformData, setWaveformData] = useState([]);

  // Apply theme from parent CADEN window
  useEffect(() => {
    const handler = (e) => {
      if (e.data?.type === 'caden-font-scale')
        document.documentElement.style.setProperty('--font-scale', String(e.data.scale));
      if (e.data?.type === 'caden-contrast')
        document.documentElement.style.setProperty('--contrast', String(e.data.contrast));
      if (e.data?.type === 'caden-theme-colors' && e.data.colors) {
        for (const [key, val] of Object.entries(e.data.colors)) {
          document.documentElement.style.setProperty(key, val);
        }
      }
    };
    window.addEventListener('message', handler);
    return () => window.removeEventListener('message', handler);
  }, []);

  // Poll backend status
  useEffect(() => {
    const checkStatus = async () => {
      try {
        const status = await fetchStatus();
        setOllamaStatus(status.ollama_available ? 'online' : 'offline');
        setAudioStatus(status.audio_running ? 'online' : 'offline');
      } catch {
        setOllamaStatus('offline');
        setAudioStatus('offline');
      }
    };
    checkStatus();
    const interval = setInterval(checkStatus, 5000);
    return () => clearInterval(interval);
  }, []);

  // Load current design on mount
  useEffect(() => {
    getCurrentDesign()
      .then((data) => {
        if (data && (data.stages || data.pots || data.frequency_response)) {
          setDesign(data);
        }
      })
      .catch(() => {});
  }, []);

  const handleDesignUpdate = useCallback((data) => {
    if (data) setDesign(data);
  }, []);

  const handleKeeperLoad = useCallback((data) => {
    if (data?.design || data?.circuit) {
      setDesign(data.design || data.circuit || data);
    }
  }, []);

  const handleAudioStatus = useCallback((status) => {
    if (status.waveform) setWaveformData(status.waveform);
  }, []);

  const pots = design?.pots || design?.controls || [];
  const freqData = design?.frequency_response || design?.freq_response || [];
  const schematicSvg = design?.schematic || design?.schematic_svg || '';

  return (
    <div className="app">
      {/* Top Bar */}
      <div className="top-bar">
        <div className="top-bar-left">
          <span className="app-title">PEDALFORGE</span>
          <div className="status-indicators">
            <div className="status-dot">
              <span className={`dot ${ollamaStatus}`} />
              <span>Ollama</span>
            </div>
            <div className="status-dot">
              <span className={`dot ${audioStatus}`} />
              <span>Audio</span>
            </div>
          </div>
        </div>
        <div className="top-bar-right">
          <AudioPanel onStatusChange={handleAudioStatus} />
        </div>
      </div>

      {/* Main Content */}
      <div className="main-content">
        {/* Left Panel - Chat */}
        <div className="left-panel">
          <ChatPanel onDesignUpdate={handleDesignUpdate} />
        </div>

        {/* Right Panel */}
        <div className="right-panel">
          {/* Visualization */}
          <div className="visualization-area">
            <div>
              <FrequencyResponse data={freqData} />
            </div>
            <div className="waveform-display">
              <svg viewBox="0 0 300 120" preserveAspectRatio="xMidYMid meet">
                {/* Grid */}
                <line x1="0" y1="60" x2="300" y2="60" stroke="rgb(var(--c-surface-2))" strokeWidth="0.5" />
                <line x1="0" y1="30" x2="300" y2="30" stroke="rgb(var(--c-surface-1))" strokeWidth="0.5" />
                <line x1="0" y1="90" x2="300" y2="90" stroke="rgb(var(--c-surface-1))" strokeWidth="0.5" />

                {/* Waveform */}
                {waveformData.length > 0 ? (
                  <polyline
                    fill="none"
                    stroke="rgb(var(--c-status-star))"
                    strokeWidth="1.5"
                    points={waveformData
                      .map((v, i) => `${(i / waveformData.length) * 300},${60 - v * 55}`)
                      .join(' ')}
                  />
                ) : (
                  <text x="150" y="64" textAnchor="middle" fill="rgb(var(--c-text-dim))" fontSize="12">
                    No audio signal
                  </text>
                )}
              </svg>
              <div className="waveform-label">Waveform</div>
            </div>
          </div>

          {/* Controls */}
          <div className="controls-area">
            <ControlPanel
              pots={pots}
              bypassed={bypassed}
              onBypassChange={setBypassed}
            />
          </div>

          {/* Tabs */}
          <div className="tab-area">
            <div className="tab-header">
              {['schematic', 'inventory', 'keepers'].map((tab) => (
                <button
                  key={tab}
                  className={`tab-btn ${activeTab === tab ? 'active' : ''}`}
                  onClick={() => setActiveTab(tab)}
                >
                  {tab.charAt(0).toUpperCase() + tab.slice(1)}
                </button>
              ))}
            </div>
            <div className="tab-content">
              {activeTab === 'schematic' && (
                <div>
                  {schematicSvg ? (
                    <div dangerouslySetInnerHTML={{ __html: schematicSvg }} />
                  ) : (
                    <div className="empty-state">
                      No schematic yet. Use the chat to design a circuit.
                    </div>
                  )}
                </div>
              )}
              {activeTab === 'inventory' && <InventoryPanel />}
              {activeTab === 'keepers' && <KeeperPanel onLoad={handleKeeperLoad} />}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
