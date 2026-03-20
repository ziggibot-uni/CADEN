import { useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import type { PlanItem, UrgencyLevel } from "../types";
import { urgencyFromScore } from "../types";

interface Props {
  items: PlanItem[];
  onItemCompleted: (id: string) => void;
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
}: {
  item: PlanItem;
  onComplete: (id: string) => void;
}) {
  const [completing, setCompleting] = useState(false);
  const urgency = urgencyFromScore(item.urgency_score);

  async function handleComplete() {
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
      className={`group flex items-start gap-2.5 px-4 py-3 border-b border-surface-2
        cursor-pointer select-none transition-colors duration-150 msg-appear
        ${item.completed ? "opacity-35" : "hover:bg-surface-1"}`}
      onClick={handleComplete}
      title={item.completed ? "Completed" : "Click to mark done"}
    >
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

      {/* Done indicator */}
      {item.completed && (
        <span className="text-[10px] text-text-dim self-center flex-shrink-0">
          done
        </span>
      )}
    </div>
  );
}

export function TodayPanel({ items, onItemCompleted }: Props) {
  const pending = items.filter((i) => !i.completed);
  const done = items.filter((i) => i.completed);

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
            {pending.map((item) => (
              <PlanRow key={item.id} item={item} onComplete={onItemCompleted} />
            ))}
            {done.length > 0 && pending.length > 0 && (
              <div className="px-4 pt-4 pb-1">
                <span className="text-[10px] font-mono uppercase tracking-widest text-text-dim">
                  Completed
                </span>
              </div>
            )}
            {done.map((item) => (
              <PlanRow key={item.id} item={item} onComplete={onItemCompleted} />
            ))}
          </>
        )}
      </div>
    </div>
  );
}
