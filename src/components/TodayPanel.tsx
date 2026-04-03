import { useState, useRef, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-shell";
import type { PlanItem, UrgencyLevel } from "../types";
import { urgencyFromScore } from "../types";
import { ProjectLinkMenu } from "./ProjectLinkMenu";

interface Props {
  items: PlanItem[];
  onItemCompleted: (id: string) => void;
  onItemUncompleted: (id: string) => void;
  onReorder: (newOrder: PlanItem[]) => void;
  onClearCompleted: () => void;
  onItemUpdated: (id: string, updates: Partial<PlanItem>) => void;
  onItemDeleted: (id: string) => void;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", hour12: true });
}

function isoToLocalDate(iso: string | null): string {
  if (!iso) return "";
  // YYYY-MM-DD in local time
  const d = new Date(iso);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function isoToLocalTime(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function localToIso(date: string, time: string): string | null {
  if (!date) return null;
  const t = time || "00:00";
  return new Date(`${date}T${t}:00`).toISOString();
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

function SourceTag({ source }: { source: PlanItem["source"] }) {
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

// ── PromoteModal ─────────────────────────────────────────────────────────────

function PromoteModal({
  item,
  onClose,
  onPromoted,
}: {
  item: PlanItem;
  onClose: () => void;
  onPromoted: (googleTaskId: string) => void;
}) {
  const [date, setDate] = useState(isoToLocalDate(item.scheduled_start));
  const [time, setTime] = useState(isoToLocalTime(item.scheduled_start));
  const [promoting, setPromoting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handlePromote() {
    if (promoting) return;
    setPromoting(true);
    setError(null);
    const due = localToIso(date, time);
    try {
      const googleTaskId = await invoke<string>("promote_moodle_to_task", {
        planId: item.id,
        title: item.title,
        dueRfc3339: due,
      });
      onPromoted(googleTaskId);
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
            onClick={handlePromote}
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

// ── PlanRow ───────────────────────────────────────────────────────────────────

function PlanRow({
  item,
  onComplete,
  onUpdate,
  onDelete,
  onDragStart,
  onDragOver,
  onDrop,
  onDragEnd,
  isDragOver,
}: {
  item: PlanItem;
  onComplete: (id: string) => void;
  onUpdate: (id: string, updates: Partial<PlanItem>) => void;
  onDelete: (id: string) => void;
  onDragStart: (e: React.DragEvent) => void;
  onDragOver: (e: React.DragEvent) => void;
  onDrop: (e: React.DragEvent) => void;
  onDragEnd: () => void;
  isDragOver: boolean;
}) {
  const [completing, setCompleting] = useState(false);
  const [deleting, setDeleting] = useState(false);

  // Inline edit state
  const [editingTitle, setEditingTitle] = useState(false);
  const [editTitle, setEditTitle] = useState(item.title);
  const [editingTime, setEditingTime] = useState(false);
  const [editDate, setEditDate] = useState(isoToLocalDate(item.scheduled_start));
  const [editStartTime, setEditStartTime] = useState(isoToLocalTime(item.scheduled_start));
  const [editEndTime, setEditEndTime] = useState(isoToLocalTime(item.scheduled_end));
  const [saving, setSaving] = useState(false);

  // Promote modal
  const [showPromote, setShowPromote] = useState(false);

  // Project link context menu
  const [linkMenu, setLinkMenu] = useState<{ x: number; y: number } | null>(null);

  const rowRef = useRef<HTMLDivElement>(null);
  const isEditing = editingTitle || editingTime;

  // Cancel any active edit/modal when clicking outside the row
  useEffect(() => {
    if (!isEditing && !showPromote) return;
    function handleOutside(e: MouseEvent) {
      if (rowRef.current && !rowRef.current.contains(e.target as Node)) {
        setEditingTitle(false);
        setEditTitle(item.title);
        setEditingTime(false);
        setShowPromote(false);
      }
    }
    document.addEventListener("mousedown", handleOutside);
    return () => document.removeEventListener("mousedown", handleOutside);
  }, [isEditing, showPromote, item.title]);

  const urgency = urgencyFromScore(item.urgency_score);

  function handleContextMenu(e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    e.nativeEvent.stopPropagation();
    e.nativeEvent.stopImmediatePropagation();
    setLinkMenu({ x: e.clientX, y: e.clientY });
  }

  async function handleLinkProject(projectId: string | null, projectName: string | null) {
    try {
      await invoke("link_plan_item_to_project", { planId: item.id, projectId });
      onUpdate(item.id, { linked_project_id: projectId, linked_project_name: projectName });
    } catch (err) {
      console.error("Failed to link project:", err);
    }
  }

  async function handleComplete(e: React.MouseEvent) {
    e.stopPropagation();
    if (item.completed || completing) return;
    setCompleting(true);
    try {
      await invoke("mark_plan_item_complete", { planId: item.id });
      onComplete(item.id);
    } catch (err) {
      console.error("Failed to complete:", err);
    } finally {
      setCompleting(false);
    }
  }

  async function handleDelete(e: React.MouseEvent) {
    e.stopPropagation();
    if (deleting) return;
    setDeleting(true);
    try {
      await invoke("delete_plan_item", { planId: item.id });
      onDelete(item.id);
    } catch (err) {
      console.error("Failed to delete:", err);
    } finally {
      setDeleting(false);
    }
  }

  async function saveTitle() {
    const t = editTitle.trim();
    if (!t || t === item.title) { setEditingTitle(false); return; }
    setSaving(true);
    try {
      await invoke("update_plan_item", {
        planId: item.id,
        title: t,
        scheduledStart: item.scheduled_start,
        scheduledEnd: item.scheduled_end,
      });
      onUpdate(item.id, { title: t });
    } catch (err) {
      console.error("Failed to update title:", err);
      setEditTitle(item.title);
    } finally {
      setSaving(false);
      setEditingTitle(false);
    }
  }

  async function saveTime() {
    const newStart = localToIso(editDate, editStartTime);
    const newEnd = editEndTime ? localToIso(editDate, editEndTime) : null;
    setSaving(true);
    try {
      await invoke("update_plan_item", {
        planId: item.id,
        title: item.title,
        scheduledStart: newStart,
        scheduledEnd: newEnd,
      });
      onUpdate(item.id, { scheduled_start: newStart, scheduled_end: newEnd });
    } catch (err) {
      console.error("Failed to update time:", err);
    } finally {
      setSaving(false);
      setEditingTime(false);
    }
  }

  return (
    <div
      ref={rowRef}
      draggable={!item.completed && item.source !== "calendar" && !editingTitle && !editingTime}
      onDragStart={onDragStart}
      onDragOver={onDragOver}
      onDrop={onDrop}
      onDragEnd={onDragEnd}
      onContextMenu={handleContextMenu}
      className={`group relative flex items-start gap-2.5 px-4 py-3 border-b border-surface-2
        select-none transition-colors duration-150 msg-appear
        hover:bg-surface-1
        ${isDragOver ? "border-t-2 border-t-accent" : ""}
        cursor-grab active:cursor-grabbing`}
    >
      {/* Drag handle */}
      <div className="mt-2 flex-shrink-0 opacity-0 group-hover:opacity-30 transition-opacity">
        <svg width="8" height="12" viewBox="0 0 8 12" fill="currentColor" className="text-text-dim">
          <circle cx="2" cy="2" r="1.2"/><circle cx="6" cy="2" r="1.2"/>
          <circle cx="2" cy="6" r="1.2"/><circle cx="6" cy="6" r="1.2"/>
          <circle cx="2" cy="10" r="1.2"/><circle cx="6" cy="10" r="1.2"/>
        </svg>
      </div>

      {/* Urgency dot */}
      <div className="mt-1.5 flex-shrink-0">
        <UrgencyDot level={urgency} />
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        {/* Title */}
        {editingTitle ? (
          <input
            autoFocus
            value={editTitle}
            onChange={(e) => setEditTitle(e.target.value)}
            onBlur={saveTitle}
            onKeyDown={(e) => {
              if (e.key === "Enter") { e.preventDefault(); saveTitle(); }
              if (e.key === "Escape") { setEditTitle(item.title); setEditingTitle(false); }
            }}
            onClick={(e) => e.stopPropagation()}
            onMouseDown={(e) => e.stopPropagation()}
            disabled={saving}
            className="w-full bg-surface border border-accent-DEFAULT rounded px-1.5 py-0.5 text-sm text-text outline-none cursor-text select-text"
          />
        ) : (
          <div
            className="text-sm leading-snug text-text cursor-text hover:text-accent transition-colors"
            onClick={(e) => { e.stopPropagation(); if (!item.completed) setEditingTitle(true); }}
            onMouseDown={(e) => e.stopPropagation()}
            title="Click to edit"
          >
            {item.title}
          </div>
        )}

        {/* Time + tags */}
        <div className="flex items-center gap-2 mt-1 flex-wrap">
          {editingTime ? (
            <div
              className="flex flex-col gap-1 w-full"
              onMouseDown={(e) => e.stopPropagation()}
              onClick={(e) => e.stopPropagation()}
            >
              <input
                type="date"
                value={editDate}
                onChange={(e) => setEditDate(e.target.value)}
                className="w-full bg-surface border border-accent-DEFAULT rounded px-1 py-0.5 text-[11px] text-text outline-none"
              />
              <div className="flex items-center gap-1">
                <input
                  type="time"
                  value={editStartTime}
                  onChange={(e) => setEditStartTime(e.target.value)}
                  className="flex-1 min-w-0 bg-surface border border-accent-DEFAULT rounded px-1 py-0.5 text-[11px] text-text outline-none"
                />
                <span className="text-text-dim text-[11px] flex-shrink-0">–</span>
                <input
                  type="time"
                  value={editEndTime}
                  onChange={(e) => setEditEndTime(e.target.value)}
                  className="flex-1 min-w-0 bg-surface border border-surface-2 rounded px-1 py-0.5 text-[11px] text-text outline-none"
                />
                <button
                  onClick={saveTime}
                  disabled={saving}
                  className="flex-shrink-0 text-sm font-medium text-accent hover:text-text px-2 py-0.5 rounded hover:bg-accent/10 transition-colors cursor-pointer"
                >
                  {saving ? "…" : "✓"}
                </button>
              </div>
            </div>
          ) : (
            <span
              className="text-text-dim font-mono text-[11px] cursor-text hover:text-accent transition-colors"
              onClick={(e) => {
                e.stopPropagation();
                if (!item.completed) {
                  setEditDate(isoToLocalDate(item.scheduled_start));
                  setEditStartTime(isoToLocalTime(item.scheduled_start));
                  setEditEndTime(isoToLocalTime(item.scheduled_end));
                  setEditingTime(true);
                }
              }}
              onMouseDown={(e) => e.stopPropagation()}
              title="Click to edit time"
            >
              {formatTime(item.scheduled_start)}
              {item.scheduled_end ? ` – ${formatTime(item.scheduled_end)}` : ""}
            </span>
          )}
          {/* Due date — shown when different from the scheduled day */}
          {item.due_date && item.source !== "calendar" && (() => {
            const scheduledDay = item.scheduled_start
              ? new Date(item.scheduled_start).toLocaleDateString([], { month: "short", day: "numeric" })
              : null;
            const dueDay = new Date(item.due_date).toLocaleDateString([], { month: "short", day: "numeric" });
            if (scheduledDay === dueDay) return null;
            return (
              <span className="text-[10px] font-mono text-urgency-med" title="Due date">
                due {dueDay}
              </span>
            );
          })()}
          {/* GCal time block indicator */}
          {item.cal_event_id && (
            <span
              className="inline-flex items-center gap-0.5 text-[10px] font-mono text-accent-DEFAULT"
              title="Time block in Google Calendar"
            >
              <svg width="9" height="9" viewBox="0 0 9 9" fill="none" stroke="currentColor" strokeWidth="1.3">
                <rect x="1" y="1.5" width="7" height="6.5" rx="1"/>
                <path d="M3 1v1M6 1v1"/>
                <path d="M1 4h7"/>
              </svg>
              GCal
            </span>
          )}
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

      {/* Action buttons — hidden while any edit is active */}
      {!isEditing && <div className="flex-shrink-0 self-center flex items-center gap-1.5">
        {/* Promote to Google Task — moodle only, not yet promoted */}
        {item.source === "moodle" && !item.google_task_id && !item.completed && (
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
              <PromoteModal
                item={item}
                onClose={() => setShowPromote(false)}
                onPromoted={(gid) => {
                  setShowPromote(false);
                  onUpdate(item.id, { google_task_id: gid });
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

        {/* Complete button */}
        {item.source !== "calendar" && (
          <button
            onClick={handleComplete}
            disabled={completing}
            title="Mark as done"
            className="w-5 h-5 rounded border border-surface-3
              hover:border-accent hover:bg-accent/10 transition-colors duration-150
              flex items-center justify-center opacity-0 group-hover:opacity-100
              text-text-dim hover:text-accent text-[10px] cursor-pointer"
          >
            {completing ? "…" : "✓"}
          </button>
        )}

        {/* Delete button */}
        <button
          onClick={handleDelete}
          disabled={deleting}
          title="Delete"
          className="w-5 h-5 rounded border border-surface-3
            hover:border-urgency-high hover:bg-urgency-high/10 transition-colors duration-150
            flex items-center justify-center opacity-0 group-hover:opacity-100
            text-text-dim hover:text-urgency-high text-[10px] cursor-pointer"
        >
          {deleting ? "…" : "✕"}
        </button>
      </div>}
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

// ── DoneRow ───────────────────────────────────────────────────────────────────

function DoneRow({ item, onUncomplete }: { item: PlanItem; onUncomplete: (id: string) => void }) {
  const [uncompleting, setUncompleting] = useState(false);

  async function handleUncomplete(e: React.MouseEvent) {
    e.stopPropagation();
    if (uncompleting) return;
    setUncompleting(true);
    try {
      await invoke("unmark_plan_item_complete", { planId: item.id });
      onUncomplete(item.id);
    } catch (err) {
      console.error("Failed to uncomplete:", err);
    } finally {
      setUncompleting(false);
    }
  }

  return (
    <div className="group flex items-center gap-2.5 px-4 py-2 border-b border-surface-2 opacity-50 hover:opacity-70 transition-opacity">
      <span className="text-accent text-xs flex-shrink-0">✓</span>
      <span className="text-sm text-text-dim line-through truncate flex-1 min-w-0">
        {item.title}
      </span>
      <span className="text-[10px] font-mono text-text-dim flex-shrink-0">
        {item.completed_at
          ? new Date(item.completed_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit", hour12: true })
          : ""}
      </span>
      <button
        onClick={handleUncomplete}
        disabled={uncompleting}
        title="Mark as not done"
        className="flex-shrink-0 w-5 h-5 rounded border border-surface-3
          hover:border-urgency-high hover:bg-urgency-high/10 transition-colors duration-150
          flex items-center justify-center opacity-0 group-hover:opacity-100
          text-text-dim hover:text-urgency-high text-[10px] cursor-pointer"
      >
        {uncompleting ? "…" : "↩"}
      </button>
    </div>
  );
}

// ── TodayPanel ────────────────────────────────────────────────────────────────

export function TodayPanel({ items, onItemCompleted, onItemUncompleted, onReorder, onClearCompleted, onItemUpdated, onItemDeleted }: Props) {
  const pending = items.filter((i) => !i.completed);
  const done = items.filter((i) => i.completed);

  const [doneExpanded, setDoneExpanded] = useState(false);

  const dragId = useRef<string | null>(null);
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null);
  const [isDragging, setIsDragging] = useState(false);

  function handleDragStart(e: React.DragEvent, item: PlanItem) {
    dragId.current = item.id;
    setIsDragging(true);
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", item.id);
  }

  function handleDragOver(e: React.DragEvent, index: number) {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    setDragOverIndex(index);
  }

  function handleDrop(e: React.DragEvent, dropIdx: number) {
    e.preventDefault();
    const id = dragId.current;
    dragId.current = null;
    setDragOverIndex(null);
    setIsDragging(false);

    if (!id) return;

    const fromIdx = pending.findIndex((i) => i.id === id);
    if (fromIdx === -1 || fromIdx === dropIdx) return;

    const newPending = [...pending];
    const [moved] = newPending.splice(fromIdx, 1);
    if (!moved) return;
    newPending.splice(dropIdx, 0, moved);

    onReorder([...newPending, ...done]);

    invoke("record_correction", {
      correctionType: "task_reorder",
      description: `User moved "${moved.title}" from position ${fromIdx + 1} to ${dropIdx + 1}`,
      data: JSON.stringify(newPending.map((i) => i.id)),
    }).catch(() => {});
  }

  function handleDragEnd() {
    dragId.current = null;
    setDragOverIndex(null);
    setIsDragging(false);
  }

  return (
    <div className="flex flex-col h-full panel-divider">
      {/* Header */}
      <div className="px-4 py-3 border-b border-surface-2 flex items-start justify-between">
        <div>
          <div className="text-[11px] font-mono uppercase tracking-widest text-text-dim">
            Today
          </div>
          <div className="text-base font-light text-text mt-0.5">
            {new Date().toLocaleDateString([], {
              weekday: "long",
              month: "long",
              day: "numeric",
            })}
          </div>
        </div>
        {items.length > 0 && (
          <div className="text-[11px] font-mono text-text-dim mt-1 text-right">
            {done.length}/{items.length}
            <span className="block text-[10px] opacity-60">done</span>
          </div>
        )}
      </div>

      {/* Task list */}
      <div className="flex-1 overflow-y-auto">
        {pending.length === 0 && done.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center px-6 gap-2">
            <div className="text-text-dim text-sm">Nothing scheduled.</div>
            <div className="text-text-dim text-xs">
              Sync your calendar and tasks to get started.
            </div>
          </div>
        ) : (
          <>
            {pending.length === 0 ? (
              <div className="px-4 py-4 text-sm text-text-dim text-center">
                All tasks done for today.
              </div>
            ) : (
              <>
                {pending.map((item, idx) => (
                  <PlanRow
                    key={item.id}
                    item={item}
                    onComplete={onItemCompleted}
                    onUpdate={onItemUpdated}
                    onDelete={onItemDeleted}
                    onDragStart={(e) => handleDragStart(e, item)}
                    onDragOver={(e) => handleDragOver(e, idx)}
                    onDrop={(e) => handleDrop(e, idx)}
                    onDragEnd={handleDragEnd}
                    isDragOver={dragOverIndex === idx}
                  />
                ))}
                {isDragging && (
                  <div
                    className={`h-10 mx-4 my-1 border-2 border-dashed rounded transition-colors ${
                      dragOverIndex === pending.length
                        ? "border-accent bg-accent/5"
                        : "border-surface-3"
                    }`}
                    onDragOver={(e) => { e.preventDefault(); setDragOverIndex(pending.length); }}
                    onDrop={(e) => handleDrop(e, pending.length)}
                  />
                )}
              </>
            )}

            {done.length > 0 && (
              <div className="border-t border-surface-2 mt-1">
                <button
                  onClick={() => setDoneExpanded((v) => !v)}
                  className="w-full px-4 py-2 flex items-center justify-between hover:bg-surface-1 transition-colors cursor-pointer"
                >
                  <span className="text-[10px] font-mono uppercase tracking-widest text-text-dim">
                    Done · {done.length}
                  </span>
                  <div className="flex items-center gap-3">
                    <span className="text-[10px] font-mono text-text-dim">
                      {doneExpanded ? "▲" : "▼"}
                    </span>
                  </div>
                </button>

                {doneExpanded && (
                  <>
                    {done.map((item) => (
                      <DoneRow key={item.id} item={item} onUncomplete={onItemUncompleted} />
                    ))}
                    <div className="px-4 py-2 flex justify-end border-t border-surface-2">
                      <button
                        onClick={onClearCompleted}
                        className="text-[10px] font-mono text-text-dim hover:text-accent transition-colors cursor-pointer"
                      >
                        clear all
                      </button>
                    </div>
                  </>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
