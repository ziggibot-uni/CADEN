import { useState, useRef, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-shell";
import type { UpcomingItem, UrgencyLevel } from "../types";
import { urgencyFromScore } from "../types";
import { ProjectLinkMenu } from "./ProjectLinkMenu";

interface Props {
  items: UpcomingItem[];
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function daysUntilNum(iso: string | null): number {
  if (!iso) return 999;
  const now = new Date();
  now.setHours(0, 0, 0, 0);
  const due = new Date(iso);
  due.setHours(0, 0, 0, 0);
  return Math.round((due.getTime() - now.getTime()) / 86400000);
}

function formatTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", hour12: true });
}

function formatDayLabel(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
}

function isoToLocalDate(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function localToIso(date: string, time: string): string | null {
  if (!date) return null;
  return new Date(`${date}T${time || "00:00"}:00`).toISOString();
}

// ── Sub-components ────────────────────────────────────────────────────────────

function UrgencyDot({ level }: { level: UrgencyLevel }) {
  const cls =
    level === "high"
      ? "urgency-dot urgency-high"
      : level === "med"
        ? "urgency-dot urgency-med"
        : "urgency-dot urgency-low";
  return <span className={cls} />;
}

function SourceTag({ source }: { source: string }) {
  const cls =
    source === "calendar"
      ? "source-tag-calendar"
      : source === "tasks"
        ? "source-tag-tasks"
        : "source-tag-moodle";
  const label =
    source === "calendar" ? "Cal" : source === "tasks" ? "Task" : "Moodle";
  return <span className={`source-tag ${cls}`}>{label}</span>;
}

// ── Promote modal ─────────────────────────────────────────────────────────────

function UpcomingPromoteModal({
  item,
  onClose,
  onPromoted,
}: {
  item: UpcomingItem;
  onClose: () => void;
  onPromoted: (googleTaskId: string) => void;
}) {
  const [date, setDate] = useState(isoToLocalDate(item.due_date));
  const [time, setTime] = useState("");
  const [promoting, setPromoting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSchedule() {
    if (promoting) return;
    setPromoting(true);
    setError(null);
    try {
      const gid = await invoke<string>("promote_upcoming_to_google_task", {
        taskId: item.id,
        title: item.title,
        dueRfc3339: localToIso(date, time),
      });
      onPromoted(gid);
    } catch (e) {
      setError(String(e));
      setPromoting(false);
    }
  }

  return (
    <div
      className="absolute right-0 bottom-full mb-1 z-50 bg-surface-1 border border-surface-2 rounded shadow-lg p-3 min-w-[220px]"
      onMouseDown={(e) => e.stopPropagation()}
      onClick={(e) => e.stopPropagation()}
    >
      <div className="text-[10px] font-mono uppercase tracking-widest text-text-dim mb-2">
        Add to Google Tasks
      </div>
      <div className="flex flex-col gap-1.5">
        <input
          type="date"
          value={date}
          onChange={(e) => setDate(e.target.value)}
          className="w-full bg-surface border border-surface-2 rounded px-2 py-1 text-xs text-text outline-none focus:border-accent-DEFAULT"
        />
        <input
          type="time"
          value={time}
          onChange={(e) => setTime(e.target.value)}
          className="w-full bg-surface border border-surface-2 rounded px-2 py-1 text-xs text-text outline-none focus:border-accent-DEFAULT"
        />
        {error && (
          <div className="text-[10px] text-urgency-high truncate">{error}</div>
        )}
        <div className="flex gap-1.5 mt-0.5">
          <button
            onClick={handleSchedule}
            disabled={promoting}
            className="flex-1 text-xs bg-accent-DEFAULT text-surface rounded px-2 py-1.5 font-medium disabled:opacity-40 cursor-pointer"
          >
            {promoting ? "…" : "Save to Tasks"}
          </button>
          <button
            onClick={onClose}
            className="text-xs text-text-dim hover:text-text px-2 py-1 cursor-pointer"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Row (mirrors TodayPanel's PlanRow style) ─────────────────────────────────

function UpcomingRow({ item, onPromoted, onLinked }: { item: UpcomingItem; onPromoted: (id: string, gid: string) => void; onLinked: (id: string, projectId: string | null, projectName: string | null) => void }) {
  const [showPromote, setShowPromote] = useState(false);
  const [linkMenu, setLinkMenu] = useState<{ x: number; y: number } | null>(null);
  const rowRef = useRef<HTMLDivElement>(null);

  const urgency = urgencyFromScore(item.urgency_score);
  const diff = daysUntilNum(item.due_date);

  useEffect(() => {
    if (!showPromote) return;
    function handler(e: MouseEvent) {
      if (rowRef.current && !rowRef.current.contains(e.target as Node)) {
        setShowPromote(false);
      }
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [showPromote]);

  function handleContextMenu(e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    e.nativeEvent.stopPropagation();
    e.nativeEvent.stopImmediatePropagation();
    setLinkMenu({ x: e.clientX, y: e.clientY });
  }

  async function handleLinkProject(projectId: string | null, projectName: string | null) {
    try {
      await invoke("link_task_to_project", { taskId: item.id, projectId });
      onLinked(item.id, projectId, projectName);
    } catch (err) {
      console.error("Failed to link project:", err);
    }
  }

  return (
    <div
      ref={rowRef}
      onContextMenu={handleContextMenu}
      className="group relative flex items-start gap-2.5 px-4 py-3 border-b border-surface-2
        select-none transition-colors duration-150 msg-appear hover:bg-surface-1"
    >
      {/* Urgency dot */}
      <div className="mt-1.5 flex-shrink-0">
        <UrgencyDot level={urgency} />
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        {/* Title */}
        <div className="text-sm leading-snug text-text">
          {item.title}
        </div>

        {/* Course name */}
        {item.course_name && (
          <div className="text-[10px] text-text-dim font-mono mt-0.5">
            {item.course_name}
          </div>
        )}

        {/* Time + tags */}
        <div className="flex items-center gap-2 mt-1 flex-wrap">
          <span className="text-[10px] font-mono text-text-dim uppercase tracking-wide opacity-70">due</span>
          <span className="text-text-dim font-mono text-[11px]">
            {formatTime(item.due_date)}
          </span>
          <span className="text-text-dim font-mono text-[10px] opacity-60">
            {formatDayLabel(item.due_date)}
            {diff === 1 ? " (tomorrow)" : ` (in ${diff}d)`}
          </span>
          <SourceTag source={item.source} />
          {item.google_task_id && (
            <span className="source-tag source-tag-tasks">GTask</span>
          )}
          {item.linked_project_name && (
            <span
              className="inline-flex items-center gap-0.5 text-[10px] px-1 py-0.5 rounded bg-surface-3 text-text-muted border border-surface-3 cursor-default"
              title={`Linked to project: ${item.linked_project_name}`}
            >
              <span className="text-[9px]">📁</span> {item.linked_project_name}
            </span>
          )}
        </div>
      </div>

      {/* Action buttons */}
      <div className="flex-shrink-0 self-center flex items-center gap-1.5">
        {/* Promote to Google Task — moodle only, not yet promoted */}
        {item.source === "moodle" && !item.google_task_id && (
          <div className="relative">
            <button
              onClick={(e) => { e.stopPropagation(); setShowPromote((v) => !v); }}
              title="Add to Google Tasks"
              className="w-5 h-5 rounded border border-surface-3
                hover:border-status-success hover:bg-status-success/10 transition-colors duration-150
                flex items-center justify-center opacity-0 group-hover:opacity-100
                text-text-dim hover:text-status-success cursor-pointer"
            >
              <svg width="9" height="9" viewBox="0 0 9 9" fill="none" stroke="currentColor" strokeWidth="1.5">
                <circle cx="4.5" cy="4.5" r="3.5"/>
                <path d="M4.5 2.5v4M2.5 4.5h4"/>
              </svg>
            </button>
            {showPromote && (
              <UpcomingPromoteModal
                item={item}
                onClose={() => setShowPromote(false)}
                onPromoted={(gid) => {
                  setShowPromote(false);
                  onPromoted(item.id, gid);
                }}
              />
            )}
          </div>
        )}

        {/* Open in browser — Moodle only */}
        {item.source === "moodle" && item.url && (
          <button
            onClick={(e) => { e.stopPropagation(); open(item.url!); }}
            title="Open in browser"
            className="w-5 h-5 rounded border border-surface-3
              hover:border-accent hover:bg-accent/10 transition-colors duration-150
              flex items-center justify-center opacity-0 group-hover:opacity-100
              text-text-dim hover:text-accent cursor-pointer"
          >
            <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M4 2H2a1 1 0 0 0-1 1v5a1 1 0 0 0 1 1h5a1 1 0 0 0 1-1V6"/>
              <path d="M6 1h3v3"/>
              <path d="M9 1 5 5"/>
            </svg>
          </button>
        )}
      </div>
      {linkMenu && (
        <ProjectLinkMenu
          x={linkMenu.x}
          y={linkMenu.y}
          currentProjectId={item.linked_project_id}
          onSelect={handleLinkProject}
          onClose={() => setLinkMenu(null)}
        />
      )}
    </div>
  );
}

// ── Day group header ─────────────────────────────────────────────────────────

function DayHeader({ date, count }: { date: Date; count: number }) {
  const label = date.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" });
  return (
    <div className="px-4 pt-3 pb-1 flex items-center justify-between">
      <span className="text-[10px] font-mono uppercase tracking-widest text-text-dim">
        {label}
      </span>
      <span className="text-[10px] font-mono text-text-dim opacity-50">{count}</span>
    </div>
  );
}

// ── UpcomingPanel ─────────────────────────────────────────────────────────────

export function UpcomingPanel({ items }: Props) {
  const [localItems, setLocalItems] = useState(items);

  useEffect(() => { setLocalItems(items); }, [items]);

  function handlePromoted(id: string, gid: string) {
    setLocalItems((prev) =>
      prev.map((it) => (it.id === id ? { ...it, google_task_id: gid } : it))
    );
  }

  function handleLinked(id: string, projectId: string | null, projectName: string | null) {
    setLocalItems((prev) =>
      prev.map((it) => (it.id === id ? { ...it, linked_project_id: projectId, linked_project_name: projectName } : it))
    );
  }

  // Filter: tomorrow through 7 days from now (exclude today and beyond 7 days)
  const filtered = localItems.filter((item) => {
    const diff = daysUntilNum(item.due_date);
    return diff >= 1 && diff <= 7;
  });

  // Group by day
  const dayGroups: { date: Date; items: UpcomingItem[] }[] = [];
  const dayMap = new Map<string, UpcomingItem[]>();

  for (const item of filtered) {
    if (!item.due_date) continue;
    const d = new Date(item.due_date);
    const key = `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
    if (!dayMap.has(key)) dayMap.set(key, []);
    dayMap.get(key)!.push(item);
  }

  for (const [, groupItems] of dayMap) {
    if (groupItems.length > 0 && groupItems[0].due_date) {
      dayGroups.push({ date: new Date(groupItems[0].due_date), items: groupItems });
    }
  }
  dayGroups.sort((a, b) => a.date.getTime() - b.date.getTime());

  // Date range label
  const tomorrow = new Date();
  tomorrow.setDate(tomorrow.getDate() + 1);
  const weekEnd = new Date();
  weekEnd.setDate(weekEnd.getDate() + 7);

  return (
    <div className="flex flex-col h-full panel-divider">
      {/* Header — mirrors TodayPanel */}
      <div className="px-4 py-3 border-b border-surface-2 flex items-start justify-between">
        <div>
          <div className="text-[11px] font-mono uppercase tracking-widest text-text-dim">
            Next 7 Days
          </div>
          <div className="text-base font-light text-text mt-0.5">
            {tomorrow.toLocaleDateString([], { month: "short", day: "numeric" })} – {weekEnd.toLocaleDateString([], { month: "short", day: "numeric" })}
          </div>
        </div>
        <div className="flex items-center gap-2 mt-1">
          {filtered.length > 0 && (
            <div className="text-[11px] font-mono text-text-dim text-right">
              {filtered.length}
              <span className="block text-[10px] opacity-60">items</span>
            </div>
          )}
          <button
            onClick={() => open("https://calendar.google.com")}
            title="Open Google Calendar"
            className="text-[10px] font-mono uppercase tracking-widest text-text-dim hover:text-accent-DEFAULT transition-colors px-2 py-1 rounded hover:bg-surface-2"
          >
            cal ↗
          </button>
        </div>
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto">
        {filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center px-6 gap-2">
            <div className="text-text-dim text-sm">Nothing coming up.</div>
            <div className="text-text-dim text-xs">
              The next 7 days are clear.
            </div>
          </div>
        ) : (
          <>
            {dayGroups.map((group) => (
              <div key={group.date.toISOString()}>
                <DayHeader date={group.date} count={group.items.length} />
                {group.items.map((item) => (
                  <UpcomingRow key={item.id} item={item} onPromoted={handlePromoted} onLinked={handleLinked} />
                ))}
              </div>
            ))}
          </>
        )}
      </div>
    </div>
  );
}
