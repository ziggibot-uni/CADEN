import { useState, useEffect, useRef } from "react";
import { getAudioDevices, configureAudio, startAudio, stopAudio, getAudioStatus } from "./api";

interface Device {
  id?: string | number;
  index?: number;
  name?: string;
  label?: string;
}

interface AudioStatus {
  input_level?: number;
  inputLevel?: number;
  output_level?: number;
  outputLevel?: number;
  waveform?: number[];
}

interface AudioPanelProps {
  onStatusChange?: (status: AudioStatus) => void;
}

export default function AudioPanel({ onStatusChange }: AudioPanelProps) {
  const [devices, setDevices] = useState<{ input: Device[]; output: Device[] }>({ input: [], output: [] });
  const [inputDevice, setInputDevice] = useState("");
  const [outputDevice, setOutputDevice] = useState("");
  const [bufferSize, setBufferSize] = useState(256);
  const [running, setRunning] = useState(false);
  const [levels, setLevels] = useState({ input: 0, output: 0 });
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    getAudioDevices()
      .then((data) => {
        const d = data as Record<string, Device[]>;
        const devs = d.devices || d;
        setDevices({
          input: (devs as unknown as { input?: Device[]; inputs?: Device[] }).input || (devs as unknown as { inputs?: Device[] }).inputs || [],
          output: (devs as unknown as { output?: Device[]; outputs?: Device[] }).output || (devs as unknown as { outputs?: Device[] }).outputs || [],
        });
      })
      .catch(() => {});
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  useEffect(() => {
    if (running) {
      pollRef.current = setInterval(async () => {
        try {
          const status = await getAudioStatus() as AudioStatus;
          setLevels({
            input: status.input_level ?? status.inputLevel ?? 0,
            output: status.output_level ?? status.outputLevel ?? 0,
          });
          onStatusChange?.(status);
        } catch {
          // ignore poll errors
        }
      }, 100);
    } else {
      if (pollRef.current) clearInterval(pollRef.current);
      setLevels({ input: 0, output: 0 });
    }
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [running, onStatusChange]);

  const handleStart = async () => {
    try {
      await configureAudio({ input_device: inputDevice, output_device: outputDevice, buffer_size: bufferSize });
      await startAudio();
      setRunning(true);
    } catch (err) {
      console.error("Audio start failed:", err);
    }
  };

  const handleStop = async () => {
    try {
      await stopAudio();
      setRunning(false);
    } catch (err) {
      console.error("Audio stop failed:", err);
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-2 text-xs">
      <label className="text-text-dim">In:</label>
      <select
        value={inputDevice}
        onChange={(e) => setInputDevice(e.target.value)}
        className="bg-surface-1 border border-surface-2 rounded px-2 py-1 text-text text-xs focus:outline-none focus:border-accent-DEFAULT"
      >
        <option value="">Default</option>
        {devices.input.map((d, i) => (
          <option key={i} value={String(d.id ?? d.index ?? d.name ?? "")}>
            {d.name || d.label || `Device ${i}`}
          </option>
        ))}
      </select>

      <label className="text-text-dim">Out:</label>
      <select
        value={outputDevice}
        onChange={(e) => setOutputDevice(e.target.value)}
        className="bg-surface-1 border border-surface-2 rounded px-2 py-1 text-text text-xs focus:outline-none focus:border-accent-DEFAULT"
      >
        <option value="">Default</option>
        {devices.output.map((d, i) => (
          <option key={i} value={String(d.id ?? d.index ?? d.name ?? "")}>
            {d.name || d.label || `Device ${i}`}
          </option>
        ))}
      </select>

      <label className="text-text-dim">Buf:</label>
      <select
        value={bufferSize}
        onChange={(e) => setBufferSize(Number(e.target.value))}
        className="bg-surface-1 border border-surface-2 rounded px-2 py-1 text-text text-xs focus:outline-none focus:border-accent-DEFAULT"
      >
        {[64, 128, 256, 512].map((s) => (
          <option key={s} value={s}>{s}</option>
        ))}
      </select>

      {!running ? (
        <button
          onClick={handleStart}
          className="px-3 py-1 bg-status-success text-surface rounded text-xs font-semibold hover:opacity-80 transition-opacity"
        >
          Start
        </button>
      ) : (
        <button
          onClick={handleStop}
          className="px-3 py-1 bg-urgency-high text-surface rounded text-xs font-semibold hover:opacity-80 transition-opacity"
        >
          Stop
        </button>
      )}

      <div className="flex items-center gap-1">
        <span className="text-text-dim opacity-60">IN</span>
        <div className="w-16 h-1.5 bg-surface-2 rounded-full overflow-hidden">
          <div
            className="h-full bg-accent-DEFAULT rounded-full transition-all duration-75"
            style={{ width: `${Math.min(100, levels.input * 100)}%` }}
          />
        </div>
      </div>

      <div className="flex items-center gap-1">
        <span className="text-text-dim opacity-60">OUT</span>
        <div className="w-16 h-1.5 bg-surface-2 rounded-full overflow-hidden">
          <div
            className="h-full bg-accent-DEFAULT rounded-full transition-all duration-75"
            style={{ width: `${Math.min(100, levels.output * 100)}%` }}
          />
        </div>
      </div>
    </div>
  );
}
