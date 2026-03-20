import { useState, useRef } from "react";
import { invoke } from "@tauri-apps/api/core";
import type { PlanItem, UrgencyLevel } from "../types";
import { urgencyFromScore } from "../types";

interface Props {
  items: PlanItem[];
  onItemCompleted: (id: string) => void;
  onReorder: (newOrder: PlanItem[]) => void;
}

function formatTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
}

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

function PlanRow({
  item,
  onComplete,
  onDragStart,
  onDragOver,
  onDrop,
  onDragEnd,
  isDragOver,
}: {
  item: PlanItem;
  onComplete: (id: string) => void;
  onDragStart: (e: React.DragEvent) => void;
  onDragOver: (e: React.DragEvent) => void;
  onDrop: (e: React.DragEvent) => void;
  onDragEnd: () => void;
  isDragOver: boolean;
}) {
  const [completing, setCompleting] = useState(false);
  const urgency = urgencyFromScore(item.urgency_score);

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

  return (
    <div
      draggable={!item.completed}
      onDragStart={onDragStart}
      onDragOver={onDragOver}
      onDrop={onDrop}
      onDragEnd={onDragEnd}
      className={`group flex items-start gap-2.5 px-4 py-3 border-b border-surface-2
        select-none transition-colors duration-150 msg-appear
        ${item.completed ? "opacity-35" : "hover:bg-surface-1"}
        ${isDragOver ? "border-t-2 border-t-accent" : ""}
        ${!item.completed ? "cursor-grab active:cursor-grabbing" : ""}`}
    >
      {/* Drag handle indicator */}
      {!item.completed && (
        <div className="mt-2 flex-shrink-0 opacity-0 group-hover:opacity-30 transition-opacity">
          <svg width="8" height="12" viewBox="0 0 8 12" fill="currentColor" className="text-text-dim">
            <circle cx="2" cy="2" r="1.2"/><circle cx="6" cy="2" r="1.2"/>
            <circle cx="2" cy="6" r="1.2"/><circle cx="6" cy="6" r="1.2"/>
            <circle cx="2" cy="10" r="1.2"/><circle cx="6" cy="10" r="1.2"/>
          </svg>
        </div>
      )}

      {/* Urgency dot */}
      <div className="mt-1.5 flex-shrink-0">
        <UrgencyDot level={urgency} />
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <div
          className={`text-sm leading-snug ${
            item.completed ? "line-through text-text-dim" : "text-text"
          }`}
        >
          {item.title}
        </div>
        <div className="flex items-center gap-2 mt-1">
          <span className="text-text-dim font-mono text-[11px]">
            {formatTime(item.scheduled_start)}
            {item.scheduled_end ? ` – ${formatTime(item.scheduled_end)}` : ""}
          </span>
          <SourceTag source={item.source} />
        </div>
      </div>

      {/* Complete button or done label */}
      {item.completed ? (
        <span className="text-[10px] text-text-dim self-center flex-shrink-0">
          done
        </span>
      ) : (
        <button
          onClick={handleComplete}
          disabled={completing}
          title="Mark as done"
          className="flex-shrink-0 self-center w-5 h-5 rounded border border-surface-3
            hover:border-accent hover:bg-accent/10 transition-colors duration-150
            flex items-center justify-center opacity-0 group-hover:opacity-100
            text-text-dim hover:text-accent text-[10px] cursor-pointer"
        >
          {completing ? "…" : "✓"}
        </button>
      )}
    </div>
  );
}

export function TodayPanel({ items, onItemCompleted, onReorder }: Props) {
  const pending = items.filter((i) => !i.completed);
  const done = items.filter((i) => i.completed);

  const dragIndex = useRef<number | null>(null);
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null);

  function handleDragStart(e: React.DragEvent, index: number) {
    dragIndex.current = index;
    e.dataTransfer.effectAllowed = "move";
  }

  function handleDragOver(e: React.DragEvent, index: number) {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    setDragOverIndex(index);
  }

  function handleDrop(e: React.DragEvent, dropIdx: number) {
    e.preventDefault();
    const fromIdx = dragIndex.current;
    if (fromIdx === null || fromIdx === dropIdx) return;

    const newPending = [...pending];
    const [moved] = newPending.splice(fromIdx, 1);
    newPending.splice(dropIdx, 0, moved);

    const newOrder = [...newPending, ...done];
    onReorder(newOrder);

    // Record the reorder as a correction for CADEN to learn from
    invoke("record_correction", {
      correctionType: "task_reorder",
      description: `User moved "${moved.title}" from position ${fromIdx + 1} to ${dropIdx + 1}`,
      data: JSON.stringify(newPending.map((i) => i.id)),
    }).catch(() => {});

    dragIndex.current = null;
    setDragOverIndex(null);
  }

  function handleDragEnd() {
    dragIndex.current = null;
    setDragOverIndex(null);
  }

  return (
    <div className="flex flex-col h-full panel-divider">
      {/* Header */}
      <div className="px-4 py-3 border-b border-surface-2">
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

      {/* Task list */}
      <div className="flex-1 overflow-y-auto">
        {items.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center px-6 gap-2">
            <div className="text-text-dim text-sm">Nothing scheduled.</div>
            <div className="text-text-dim text-xs">
              Sync your calendar and tasks to get started.
            </div>
          </div>
        ) : (
          <>
            {pending.map((item, idx) => (
              <PlanRow
                key={item.id}
                item={item}
                onComplete={onItemCompleted}
                onDragStart={(e) => handleDragStart(e, idx)}
                onDragOver={(e) => handleDragOver(e, idx)}
                onDrop={(e) => handleDrop(e, idx)}
                onDragEnd={handleDragEnd}
                isDragOver={dragOverIndex === idx}
              />
            ))}
            {done.length > 0 && pending.length > 0 && (
              <div className="px-4 pt-4 pb-1">
                <span className="text-[10px] font-mono uppercase tracking-widest text-text-dim">
                  Completed
                </span>
              </div>
            )}
            {done.map((item) => (
              <PlanRow
                key={item.id}
                item={item}
                onComplete={onItemCompleted}
                onDragStart={() => {}}
                onDragOver={(e) => e.preventDefault()}
                onDrop={() => {}}
                onDragEnd={() => {}}
                isDragOver={false}
              />
            ))}
          </>
        )}
      </div>
    </div>
  );
}
