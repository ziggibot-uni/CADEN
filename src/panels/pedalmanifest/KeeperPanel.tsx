import { useState, useEffect, useCallback } from "react";
import { getKeepers, saveKeeper, loadKeeper, deleteKeeper } from "./api";

interface Keeper {
  id: string;
  name: string;
  description?: string;
  timestamp?: string;
  created_at?: string;
  gain?: number;
  freq_low?: number;
  freq_high?: number;
  summary?: string;
}

interface KeeperPanelProps {
  onLoad?: (data: unknown) => void;
}

export default function KeeperPanel({ onLoad }: KeeperPanelProps) {
  const [keepers, setKeepers] = useState<Keeper[]>([]);
  const [name, setName] = useState("");

  const fetchKeepers = useCallback(async () => {
    try {
      const data = await getKeepers() as { keepers?: Keeper[] } | Keeper[];
      setKeepers((Array.isArray(data) ? data : (data as { keepers?: Keeper[] }).keepers) || []);
    } catch (err) {
      console.error("Failed to fetch keepers:", err);
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
      setName("");
      fetchKeepers();
    } catch (err) {
      console.error("Failed to save keeper:", err);
    }
  };

  const handleLoad = async (id: string) => {
    try {
      const data = await loadKeeper(id);
      onLoad?.(data);
      fetchKeepers();
    } catch (err) {
      console.error("Failed to load keeper:", err);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await deleteKeeper(id);
      fetchKeepers();
    } catch (err) {
      console.error("Failed to delete keeper:", err);
    }
  };

  const formatDate = (ts?: string) => {
    if (!ts) return "";
    try {
      return new Date(ts).toLocaleString();
    } catch {
      return ts;
    }
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex gap-2 p-3 border-b border-surface-2">
        <input
          placeholder="Design name..."
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSave()}
          className="flex-1 bg-surface-1 border border-surface-2 rounded px-3 py-1.5 text-sm text-text placeholder:text-text-dim focus:outline-none focus:border-accent-DEFAULT"
        />
        <button
          onClick={handleSave}
          disabled={!name.trim()}
          className="px-3 py-1.5 bg-accent-DEFAULT text-surface rounded text-xs font-semibold disabled:opacity-30 hover:opacity-80 transition-opacity"
        >
          Save
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {keepers.length === 0 ? (
          <div className="text-text-dim text-xs opacity-40 text-center py-10">No saved designs yet</div>
        ) : (
          <div className="divide-y divide-surface-2">
            {keepers.map((k) => (
              <div key={k.id} className="flex items-start justify-between gap-3 px-3 py-2.5 hover:bg-surface-1 transition-colors">
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-text font-medium">{k.name}</div>
                  {k.description && (
                    <div className="text-xs text-text-dim mt-0.5">{k.description}</div>
                  )}
                  <div className="text-[10px] text-text-dim opacity-50 mt-0.5">
                    {formatDate(k.timestamp || k.created_at)}
                    {k.gain != null && ` · Gain: ${k.gain}dB`}
                    {k.freq_low != null && k.freq_high != null && ` · ${k.freq_low}Hz–${k.freq_high}Hz`}
                    {k.summary && ` · ${k.summary}`}
                  </div>
                </div>
                <div className="flex gap-1.5 flex-shrink-0">
                  <button
                    onClick={() => handleLoad(k.id)}
                    className="px-2.5 py-1 bg-surface-2 text-text rounded text-xs hover:bg-surface-3 transition-colors"
                  >
                    Load
                  </button>
                  <button
                    onClick={() => handleDelete(k.id)}
                    className="px-2.5 py-1 text-urgency-high rounded text-xs hover:bg-urgency-high hover:text-surface transition-colors"
                  >
                    Del
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
