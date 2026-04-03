import { useState, useEffect, useRef } from "react";
import { invoke } from "@tauri-apps/api/core";

interface Project {
  id: string;
  name: string;
  status: string;
  parent_id: string | null;
}

interface Props {
  x: number;
  y: number;
  currentProjectId: string | null;
  onSelect: (projectId: string | null, projectName: string | null) => void;
  onClose: () => void;
}

export function ProjectLinkMenu({ x, y, currentProjectId, onSelect, onClose }: Props) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [pos, setPos] = useState({ left: x, top: y });
  const menuRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    invoke<Project[]>("list_projects")
      .then((p) => setProjects(p.filter((proj) => !proj.name.startsWith("__"))))
      .catch(() => setProjects([]))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    setTimeout(() => inputRef.current?.focus(), 50);
  }, []);

  // After the menu renders, clamp it so it stays fully inside the viewport
  useEffect(() => {
    const el = menuRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const MARGIN = 8;
    let left = x;
    let top = y;
    if (left + rect.width + MARGIN > vw) left = vw - rect.width - MARGIN;
    if (left < MARGIN) left = MARGIN;
    if (top + rect.height + MARGIN > vh) top = vh - rect.height - MARGIN;
    if (top < MARGIN) top = MARGIN;
    setPos({ left, top });
  }, [x, y, loading]); // re-run when loading finishes and content height changes

  useEffect(() => {
    function handleOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        onClose();
      }
    }
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("mousedown", handleOutside);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handleOutside);
      document.removeEventListener("keydown", handleKey);
    };
  }, [onClose]);

  const filtered = projects.filter((p) =>
    p.name.toLowerCase().includes(filter.toLowerCase())
  );

  return (
    <div
      ref={menuRef}
      style={{ position: "fixed", zIndex: 1000, left: pos.left, top: pos.top, maxHeight: "280px" }}
      className="bg-surface-1 border border-surface-2 rounded shadow-lg min-w-[200px] flex flex-col overflow-hidden"
      onMouseDown={(e) => e.stopPropagation()}
      onClick={(e) => e.stopPropagation()}
    >
      <div className="px-3 pt-2.5 pb-1.5 border-b border-surface-2 flex-shrink-0">
        <div className="text-[10px] font-mono uppercase tracking-widest text-text-dim mb-1.5">
          Link to project
        </div>
        <input
          ref={inputRef}
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Search projects…"
          className="w-full bg-surface border border-surface-2 rounded px-2 py-1 text-xs text-text placeholder-text-dim outline-none focus:border-accent-DEFAULT"
        />
      </div>
      <div className="overflow-y-auto flex-1">
        {loading ? (
          <div className="px-3 py-2 text-xs text-text-dim animate-pulse">Loading…</div>
        ) : (
          <>
            {currentProjectId && (
              <button
                onClick={() => { onSelect(null, null); onClose(); }}
                className="w-full text-left px-3 py-1.5 text-xs text-urgency-med hover:bg-surface-2 transition-colors"
              >
                ✕ Remove link
              </button>
            )}
            {filtered.length === 0 ? (
              <div className="px-3 py-2 text-xs text-text-dim">No projects found</div>
            ) : (
              filtered.map((p) => (
                <button
                  key={p.id}
                  onClick={() => { onSelect(p.id, p.name); onClose(); }}
                  className={`w-full text-left px-3 py-1.5 text-xs transition-colors hover:bg-surface-2 ${
                    p.id === currentProjectId ? "text-accent-DEFAULT" : "text-text"
                  }`}
                >
                  {p.id === currentProjectId && "✓ "}
                  {p.name}
                </button>
              ))
            )}
          </>
        )}
      </div>
    </div>
  );
}
