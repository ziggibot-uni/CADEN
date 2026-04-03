import { useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import type { CatchUpSummary, CatchUpTask, TriageAction } from "../types";

interface Props {
  summary: CatchUpSummary;
  onClose: () => void;
  onTriageComplete: () => void;
}

function formatDueDate(iso: string | null): string {
  if (!iso) return "no due date";
  const d = new Date(iso);
  const now = new Date();
  const diffDays = Math.floor((now.getTime() - d.getTime()) / 86400000);
  if (diffDays === 0) return "due today";
  if (diffDays === 1) return "1 day overdue";
  if (diffDays > 1) return `${diffDays} days overdue`;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function formatHours(hours: number): string {
  if (hours < 1) return `${Math.round(hours * 60)}m`;
  if (hours < 24) return `${Math.round(hours)}h`;
  const days = Math.floor(hours / 24);
  return days === 1 ? "1 day" : `${days} days`;
}

function OverdueRow({
  task,
  decision,
  deferDate,
  onDecision,
  onDeferDate,
}: {
  task: CatchUpTask;
  decision: string;
  deferDate: string;
  onDecision: (action: string) => void;
  onDeferDate: (date: string) => void;
}) {
  return (
    <div className="flex items-center gap-2 py-1.5 border-b border-surface-2 last:border-0">
      <div className="flex-1 min-w-0">
        <div className="text-xs text-text truncate">{task.title}</div>
        <div className="text-[10px] text-text-dim">
          {task.course_name && <span>{task.course_name} · </span>}
          {formatDueDate(task.due_date)}
        </div>
      </div>
      <div className="flex items-center gap-1 flex-shrink-0">
        <button
          onClick={() => onDecision("today")}
          className={`px-2 py-0.5 text-[10px] rounded cursor-pointer transition-colors ${decision === "today" ? "bg-accent-DEFAULT text-surface" : "bg-surface-2 text-text-dim hover:text-text"}`}
        >
          Today
        </button>
        <button
          onClick={() => onDecision("defer")}
          className={`px-2 py-0.5 text-[10px] rounded cursor-pointer transition-colors ${decision === "defer" ? "bg-accent-DEFAULT text-surface" : "bg-surface-2 text-text-dim hover:text-text"}`}
        >
          Defer
        </button>
        <button
          onClick={() => onDecision("drop")}
          className={`px-2 py-0.5 text-[10px] rounded cursor-pointer transition-colors ${decision === "drop" ? "bg-urgency-high text-surface" : "bg-surface-2 text-text-dim hover:text-text"}`}
        >
          Drop
        </button>
      </div>
      {decision === "defer" && (
        <input
          type="date"
          className="bg-surface border border-surface-2 rounded px-1.5 py-0.5 text-[10px] text-text outline-none"
          value={deferDate}
          onChange={(e) => onDeferDate(e.target.value)}
        />
      )}
    </div>
  );
}

export function CatchUpModal({ summary, onClose, onTriageComplete }: Props) {
  const [decisions, setDecisions] = useState<Record<string, string>>(() => {
    const d: Record<string, string> = {};
    for (const t of summary.overdue_tasks) d[t.id] = "today";
    return d;
  });
  const [deferDates, setDeferDates] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);

  const hasOverdue = summary.overdue_tasks.length > 0;
  const hasContent =
    summary.hours_since_last_sync > 2 ||
    hasOverdue ||
    summary.resurfaced_thoughts.length > 0 ||
    summary.low_energy_mode;

  if (!hasContent) return null;

  async function handleSubmit() {
    if (!hasOverdue) {
      onClose();
      return;
    }
    setSubmitting(true);
    const actions: TriageAction[] = summary.overdue_tasks.map((t) => ({
      task_id: t.id,
      action: (decisions[t.id] || "today") as TriageAction["action"],
      defer_to: decisions[t.id] === "defer" && deferDates[t.id]
        ? new Date(deferDates[t.id] + "T23:59:00").toISOString()
        : undefined,
    }));
    try {
      await invoke("triage_overdue_tasks", { actions });
      onTriageComplete();
    } catch (e) {
      console.error("Triage failed:", e);
    }
    setSubmitting(false);
    onClose();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-surface-1 border border-surface-2 rounded-xl shadow-xl px-6 py-5 max-w-lg w-full max-h-[80vh] overflow-y-auto">
        <h2 className="text-base font-semibold text-text mb-1">Welcome back</h2>
        <p className="text-xs text-text-dim mb-4">
          {summary.hours_since_last_sync > 2
            ? `It's been ${formatHours(summary.hours_since_last_sync)} since your last session.`
            : "Here's what's happening today."}
          {summary.completed_yesterday > 0 && (
            <span> You completed {summary.completed_yesterday} task{summary.completed_yesterday !== 1 ? "s" : ""} yesterday.</span>
          )}
          {summary.skipped_yesterday > 0 && (
            <span className="text-urgency-high"> {summary.skipped_yesterday} skipped.</span>
          )}
        </p>

        {/* Low energy warning */}
        {summary.low_energy_mode && (
          <div className="bg-surface rounded-lg px-3 py-2 mb-3 border border-accent-DEFAULT/30">
            <div className="text-xs text-text">
              <span className="font-medium">Low energy detected</span>
              {summary.current_energy != null && (
                <span className="text-text-dim"> ({summary.current_energy.toFixed(1)}/10)</span>
              )}
            </div>
            <div className="text-[10px] text-text-dim mt-0.5">
              Today's plan has been lightened — fewer tasks, more breathing room.
            </div>
          </div>
        )}

        {/* Overdue task triage */}
        {hasOverdue && (
          <div className="mb-3">
            <div className="text-xs font-medium text-text mb-1.5">
              Overdue tasks — what do you want to do?
            </div>
            <div className="bg-surface rounded-lg px-3 py-1">
              {summary.overdue_tasks.map((task) => (
                <OverdueRow
                  key={task.id}
                  task={task}
                  decision={decisions[task.id] || "today"}
                  deferDate={deferDates[task.id] || ""}
                  onDecision={(action) =>
                    setDecisions((d) => ({ ...d, [task.id]: action }))
                  }
                  onDeferDate={(date) =>
                    setDeferDates((d) => ({ ...d, [task.id]: date }))
                  }
                />
              ))}
            </div>
          </div>
        )}

        {/* Resurfaced thoughts */}
        {summary.resurfaced_thoughts.length > 0 && (
          <div className="mb-3">
            <div className="text-xs font-medium text-text mb-1.5">
              From your thought dump
            </div>
            <div className="bg-surface rounded-lg px-3 py-2 space-y-1">
              {summary.resurfaced_thoughts.map((thought, i) => (
                <div key={i} className="text-[10px] text-text-dim leading-relaxed">
                  • {thought}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* New Moodle assignments */}
        {summary.new_moodle_assignments.length > 0 && (
          <div className="mb-3">
            <div className="text-xs font-medium text-text mb-1.5">
              Moodle assignments ({summary.new_moodle_assignments.length})
            </div>
            <div className="bg-surface rounded-lg px-3 py-1">
              {summary.new_moodle_assignments.slice(0, 5).map((task) => (
                <div key={task.id} className="py-1 border-b border-surface-2 last:border-0">
                  <div className="text-xs text-text truncate">{task.title}</div>
                  <div className="text-[10px] text-text-dim">
                    {task.course_name && <span>{task.course_name} · </span>}
                    {task.due_date
                      ? new Date(task.due_date).toLocaleDateString(undefined, {
                          month: "short",
                          day: "numeric",
                        })
                      : "no due date"}
                  </div>
                </div>
              ))}
              {summary.new_moodle_assignments.length > 5 && (
                <div className="text-[10px] text-text-dim py-1">
                  +{summary.new_moodle_assignments.length - 5} more
                </div>
              )}
            </div>
          </div>
        )}

        {/* Actions */}
        <div className="flex gap-2 mt-4">
          <button
            onClick={handleSubmit}
            disabled={submitting}
            className="flex-1 py-2 rounded-lg bg-accent-DEFAULT text-surface text-sm font-medium hover:opacity-90 cursor-pointer disabled:opacity-40"
          >
            {submitting ? "Applying…" : hasOverdue ? "Apply & start day" : "Let's go"}
          </button>
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-lg bg-surface-2 text-text-dim text-sm hover:text-text cursor-pointer"
          >
            Skip
          </button>
        </div>
      </div>
    </div>
  );
}
