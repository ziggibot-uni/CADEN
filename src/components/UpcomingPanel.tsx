import type { UpcomingItem } from "../types";
import { urgencyFromScore } from "../types";

interface Props {
  items: UpcomingItem[];
}

function daysUntilNum(iso: string | null): number {
  if (!iso) return 999;
  const now = new Date();
  now.setHours(0, 0, 0, 0);
  const due = new Date(iso);
  due.setHours(0, 0, 0, 0);
  return Math.round((due.getTime() - now.getTime()) / 86400000);
}

function formatDueDate(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

function daysLabel(diff: number): string {
  if (diff < 0) return "overdue";
  if (diff === 0) return "today";
  if (diff === 1) return "tomorrow";
  return `in ${diff}d`;
}

function UpcomingRow({ item }: { item: UpcomingItem }) {
  const urgency = urgencyFromScore(item.urgency_score);
  const borderColor =
    urgency === "high"
      ? "border-l-[#c0392b]"
      : urgency === "med"
        ? "border-l-[#b5842a]"
        : "border-l-[#2d6b61]";

  const diff = daysUntilNum(item.due_date);
  const label = daysLabel(diff);
  const isOverdue = diff < 0;

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
          {label}
        </span>
      </div>
    </div>
  );
}

function SectionHeader({ label, count }: { label: string; count: number }) {
  return (
    <div className="px-3 py-1.5 flex items-center justify-between border-b border-surface-2 bg-surface-1">
      <span className="text-[10px] font-mono uppercase tracking-widest text-text-dim">
        {label}
      </span>
      <span className="text-[10px] font-mono text-text-dim">{count}</span>
    </div>
  );
}

function groupItems(items: UpcomingItem[]): {
  overdue: UpcomingItem[];
  today: UpcomingItem[];
  tomorrow: UpcomingItem[];
  week: UpcomingItem[];
} {
  const overdue: UpcomingItem[] = [];
  const today: UpcomingItem[] = [];
  const tomorrow: UpcomingItem[] = [];
  const week: UpcomingItem[] = [];

  for (const item of items) {
    const diff = daysUntilNum(item.due_date);
    if (diff < 0) overdue.push(item);
    else if (diff === 0) today.push(item);
    else if (diff === 1) tomorrow.push(item);
    else week.push(item);
  }

  return { overdue, today, tomorrow, week };
}

export function UpcomingPanel({ items }: Props) {
  const { overdue, today, tomorrow, week } = groupItems(items);

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-3 py-3 border-b border-surface-2 flex items-start justify-between">
        <div>
          <div className="text-[11px] font-mono uppercase tracking-widest text-text-dim">
            Upcoming
          </div>
          <div className="text-base font-light text-text mt-0.5">Next 7 days</div>
        </div>
        {items.length > 0 && (
          <div className="text-[11px] font-mono text-text-dim mt-1">
            {items.length}
            <span className="block text-[10px] opacity-60 text-right">items</span>
          </div>
        )}
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
          <>
            {overdue.length > 0 && (
              <>
                <SectionHeader label="Overdue" count={overdue.length} />
                {overdue.map((item) => <UpcomingRow key={item.id} item={item} />)}
              </>
            )}
            {today.length > 0 && (
              <>
                <SectionHeader label="Today" count={today.length} />
                {today.map((item) => <UpcomingRow key={item.id} item={item} />)}
              </>
            )}
            {tomorrow.length > 0 && (
              <>
                <SectionHeader label="Tomorrow" count={tomorrow.length} />
                {tomorrow.map((item) => <UpcomingRow key={item.id} item={item} />)}
              </>
            )}
            {week.length > 0 && (
              <>
                <SectionHeader label="This week" count={week.length} />
                {week.map((item) => <UpcomingRow key={item.id} item={item} />)}
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}
