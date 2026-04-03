import React, { useState, useEffect, useCallback } from 'react';
import { getKeepers, saveKeeper, loadKeeper, deleteKeeper } from '../utils/api';

export default function KeeperPanel({ onLoad }) {
  const [keepers, setKeepers] = useState([]);
  const [name, setName] = useState('');

  const fetchKeepers = useCallback(async () => {
    try {
      const data = await getKeepers();
      setKeepers(data.keepers || data || []);
    } catch (err) {
      console.error('Failed to fetch keepers:', err);
    }
  }, []);

  useEffect(() => {
    fetchKeepers();
  }, [fetchKeepers]);

  const handleSave = async () => {
    const trimmed = name.trim();
    if (!trimmed) return;
    try {
      await saveKeeper({ name: trimmed });
      setName('');
      fetchKeepers();
    } catch (err) {
      console.error('Failed to save keeper:', err);
    }
  };

  const handleLoad = async (id) => {
    try {
      const data = await loadKeeper(id);
      onLoad?.(data);
      fetchKeepers();
    } catch (err) {
      console.error('Failed to load keeper:', err);
    }
  };

  const handleDelete = async (id) => {
    try {
      await deleteKeeper(id);
      fetchKeepers();
    } catch (err) {
      console.error('Failed to delete keeper:', err);
    }
  };

  const formatDate = (ts) => {
    if (!ts) return '';
    try {
      const d = new Date(ts);
      return d.toLocaleString();
    } catch {
      return ts;
    }
  };

  return (
    <div className="keepers-panel">
      <div className="keeper-save-bar">
        <input
          placeholder="Design name..."
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSave()}
        />
        <button className="btn-save" onClick={handleSave} disabled={!name.trim()}>
          Save Current
        </button>
      </div>

      {keepers.length === 0 ? (
        <div className="empty-state">No saved designs yet</div>
      ) : (
        <div className="keeper-list">
          {keepers.map((k) => (
            <div key={k.id} className="keeper-card">
              <div className="keeper-info">
                <span className="keeper-name">{k.name}</span>
                {k.description && <span className="keeper-desc">{k.description}</span>}
                <span className="keeper-meta">
                  {formatDate(k.timestamp || k.created_at)}
                  {k.gain != null && ` | Gain: ${k.gain}dB`}
                  {k.freq_low != null && k.freq_high != null && ` | ${k.freq_low}Hz - ${k.freq_high}Hz`}
                  {k.summary && ` | ${k.summary}`}
                </span>
              </div>
              <div className="keeper-actions">
                <button className="btn-load" onClick={() => handleLoad(k.id)}>Load</button>
                <button className="btn-delete" onClick={() => handleDelete(k.id)}>Delete</button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
