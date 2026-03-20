import type { UpcomingItem } from "../types";
import { urgencyFromScore } from "../types";

interface Props {
  items: UpcomingItem[];
}

function daysUntil(iso: string | null): string {
  if (!iso) return "no date";
  const now = new Date();
  now.setHours(0, 0, 0, 0);
  const due = new Date(iso);
  due.setHours(0, 0, 0, 0);
  const diff = Math.round((due.getTime() - now.getTime()) / 86400000);
  if (diff < 0) return "overdue";
  if (diff === 0) return "today";
  if (diff === 1) return "tomorrow";
  return `in ${diff}d`;
}

function formatDueDate(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

function UpcomingRow({ item }: { item: UpcomingItem }) {
  const urgency = urgencyFromScore(item.urgency_score);
  const borderColor =
    urgency === "high"
      ? "border-l-[#c0392b]"
      : urgency === "med"
        ? "border-l-[#b5842a]"
        : "border-l-[#2d6b61]";

  const daysLabel = daysUntil(item.due_date);
  const isOverdue = daysLabel === "overdue";

  return (
    <div
      className={`px-3 py-2.5 border-b border-surface-2 border-l-2 ${borderColor} msg-appear`}
    >
      <div className="text-sm text-text leading-snug truncate" title={item.title}>
        {item.title}
      </div>
      {item.course_name && (
        <div className="text-[10px] text-text-dim font-mono truncate mt-0.5">
          {item.course_name}
        </div>
      )}
      <div className="flex items-center justify-between mt-1">
        <span className="text-[10px] font-mono text-text-dim">
          {formatDueDate(item.due_date)}
        </span>
        <span
          className={`text-[10px] font-mono ${
            isOverdue ? "text-[#c0392b]" : "text-text-dim"
          }`}
        >
          {daysLabel}
        </span>
      </div>
    </div>
  );
}

export function UpcomingPanel({ items }: Props) {
  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-3 py-3 border-b border-surface-2">
        <div className="text-[11px] font-mono uppercase tracking-widest text-text-dim">
          Upcoming
        </div>
        <div className="text-base font-light text-text mt-0.5">Next 7 days</div>
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto">
        {items.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <span className="text-text-dim text-xs text-center px-4">
              Nothing coming up.
            </span>
          </div>
        ) : (
          items.map((item) => <UpcomingRow key={item.id} item={item} />)
        )}
      </div>
    </div>
  );
}
