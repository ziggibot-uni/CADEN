import React, { useState, useEffect, useRef } from 'react';
import { getAudioDevices, configureAudio, startAudio, stopAudio, getAudioStatus } from '../utils/api';

export default function AudioPanel({ onStatusChange }) {
  const [devices, setDevices] = useState({ input: [], output: [] });
  const [inputDevice, setInputDevice] = useState('');
  const [outputDevice, setOutputDevice] = useState('');
  const [bufferSize, setBufferSize] = useState(256);
  const [running, setRunning] = useState(false);
  const [levels, setLevels] = useState({ input: 0, output: 0 });
  const pollRef = useRef(null);

  useEffect(() => {
    getAudioDevices()
      .then((data) => {
        const devs = data.devices || data;
        setDevices({
          input: devs.input || devs.inputs || [],
          output: devs.output || devs.outputs || [],
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
          const status = await getAudioStatus();
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
      await configureAudio({
        input_device: inputDevice,
        output_device: outputDevice,
        buffer_size: bufferSize,
      });
      await startAudio();
      setRunning(true);
    } catch (err) {
      console.error('Audio start failed:', err);
    }
  };

  const handleStop = async () => {
    try {
      await stopAudio();
      setRunning(false);
    } catch (err) {
      console.error('Audio stop failed:', err);
    }
  };

  return (
    <div className="audio-panel">
      <label>In:</label>
      <select value={inputDevice} onChange={(e) => setInputDevice(e.target.value)}>
        <option value="">Default</option>
        {devices.input.map((d, i) => (
          <option key={i} value={d.id ?? d.index ?? d.name}>
            {d.name || d.label || `Device ${i}`}
          </option>
        ))}
      </select>

      <label>Out:</label>
      <select value={outputDevice} onChange={(e) => setOutputDevice(e.target.value)}>
        <option value="">Default</option>
        {devices.output.map((d, i) => (
          <option key={i} value={d.id ?? d.index ?? d.name}>
            {d.name || d.label || `Device ${i}`}
          </option>
        ))}
      </select>

      <label>Buf:</label>
      <select value={bufferSize} onChange={(e) => setBufferSize(Number(e.target.value))}>
        {[64, 128, 256, 512].map((s) => (
          <option key={s} value={s}>{s}</option>
        ))}
      </select>

      {!running ? (
        <button className="audio-btn-start" onClick={handleStart}>Start</button>
      ) : (
        <button className="audio-btn-stop" onClick={handleStop}>Stop</button>
      )}

      <div className="level-meter">
        <span className="level-meter-label">IN</span>
        <div className="level-meter-bar">
          <div className="level-meter-fill" style={{ width: `${Math.min(100, levels.input * 100)}%` }} />
        </div>
      </div>

      <div className="level-meter">
        <span className="level-meter-label">OUT</span>
        <div className="level-meter-bar">
          <div className="level-meter-fill" style={{ width: `${Math.min(100, levels.output * 100)}%` }} />
        </div>
      </div>
    </div>
  );
}
