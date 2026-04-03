import { useState, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";

export function ResurfacedThoughts() {
  const [thoughts, setThoughts] = useState<string[]>([]);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    invoke<string[]>("get_resurfaced_thoughts")
      .then((t) => setThoughts(t))
      .catch(() => {});
  }, []);

  if (dismissed || thoughts.length === 0) return null;

  return (
    <div className="mx-2 mb-2 bg-surface-1 border border-accent-DEFAULT/20 rounded-lg px-3 py-2">
      <div className="flex items-center justify-between mb-1">
        <span className="text-[10px] font-medium text-accent-DEFAULT">
          From your thought dump
        </span>
        <button
          onClick={() => setDismissed(true)}
          className="text-text-dim hover:text-text text-xs leading-none cursor-pointer"
          aria-label="Dismiss"
        >
          ✕
        </button>
      </div>
      <div className="space-y-1">
        {thoughts.map((thought, i) => (
          <div key={i} className="text-[10px] text-text-dim leading-relaxed">
            • {thought}
          </div>
        ))}
      </div>
    </div>
  );
}
