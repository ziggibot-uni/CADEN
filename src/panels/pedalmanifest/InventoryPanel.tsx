import { useState, useEffect, useCallback, useRef } from "react";
import { getInventory, addInventoryItem, updateInventoryItem, deleteInventoryItem, adjustQuantity } from "./api";

const TYPE_LIST = [
  "resistor", "capacitor", "inductor", "diode", "transistor",
  "op_amp", "potentiometer", "switch", "jack", "led", "ic", "other",
];

const TYPE_LABELS: Record<string, string> = {
  resistor: "R", capacitor: "C", inductor: "L", diode: "D", transistor: "Q",
  op_amp: "IC", potentiometer: "POT", switch: "SW", jack: "J", led: "LED",
  ic: "IC", other: "?",
};

// Map component types to existing CADEN CSS vars
const TYPE_COLORS: Record<string, string> = {
  resistor: "rgb(var(--c-status-star))",
  capacitor: "rgb(var(--c-cat-progress))",
  inductor: "rgb(var(--c-cat-decision))",
  diode: "rgb(var(--c-urgency-med))",
  transistor: "rgb(var(--c-status-success))",
  op_amp: "rgb(var(--c-cat-reference))",
  potentiometer: "rgb(var(--c-cat-idea))",
  switch: "rgb(var(--c-accent))",
  jack: "rgb(var(--c-text-dim))",
  led: "rgb(var(--c-status-success))",
  ic: "rgb(var(--c-cat-reference))",
  other: "rgb(var(--c-text-dim))",
};

const PACKAGES = [
  "through-hole", "SMD 0402", "SMD 0603", "SMD 0805", "SMD 1206",
  "TO-92", "TO-220", "DIP-8", "SOIC-8", "other",
];

interface StockStatus {
  label: "OUT" | "LOW" | "IN";
  colorClass: string;
}

function stockStatus(qty: number): StockStatus {
  if (qty === 0) return { label: "OUT", colorClass: "text-urgency-high bg-urgency-high/10" };
  if (qty <= 2) return { label: "LOW", colorClass: "text-urgency-med bg-urgency-med/10" };
  return { label: "IN", colorClass: "text-status-success bg-status-success/10" };
}

interface InventoryItem {
  id: string;
  type: string;
  value_display?: string;
  model?: string;
  package?: string;
  notes?: string;
  quantity: number;
  buy_link?: string;
}

const EMPTY_FORM = {
  type: "resistor", value_display: "", quantity: 1,
  package: "through-hole", model: "", notes: "", buy_link: "",
};

export default function InventoryPanel() {
  const [items, setItems] = useState<InventoryItem[]>([]);
  const [filterType, setFilterType] = useState("");
  const [filterStock, setFilterStock] = useState("");
  const [search, setSearch] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [editLink, setEditLink] = useState<string | null>(null);
  const [linkDraft, setLinkDraft] = useState("");
  const [hovered, setHovered] = useState<string | null>(null);
  const linkInputRef = useRef<HTMLInputElement>(null);

  const fetchItems = useCallback(async () => {
    try {
      const data = await getInventory(filterType || undefined, search || undefined) as { items?: InventoryItem[] } | InventoryItem[];
      setItems((Array.isArray(data) ? data : (data as { items?: InventoryItem[] }).items) || []);
    } catch (err) {
      console.error("Failed to fetch inventory:", err);
    }
  }, [filterType, search]);

  useEffect(() => { fetchItems(); }, [fetchItems]);

  useEffect(() => {
    if (editLink && linkInputRef.current) linkInputRef.current.focus();
  }, [editLink]);

  const handleAdd = async () => {
    if (!form.value_display.trim()) return;
    setSaving(true);
    try {
      await addInventoryItem({ ...form, quantity: Number(form.quantity) || 1 });
      setForm(EMPTY_FORM);
      setShowAdd(false);
      fetchItems();
    } catch (err) {
      console.error("Failed to add item:", err);
    } finally {
      setSaving(false);
    }
  };

  const handleQty = async (id: string, delta: number) => {
    setItems((prev) => prev.map((it) => it.id === id ? { ...it, quantity: Math.max(0, it.quantity + delta) } : it));
    try {
      await adjustQuantity(id, delta);
    } catch {
      fetchItems();
    }
  };

  const handleDelete = async (id: string) => {
    setItems((prev) => prev.filter((it) => it.id !== id));
    try {
      await deleteInventoryItem(id);
    } catch {
      fetchItems();
    }
  };

  const handleSaveLink = async (id: string) => {
    const url = linkDraft.trim();
    setItems((prev) => prev.map((it) => it.id === id ? { ...it, buy_link: url } : it));
    setEditLink(null);
    try {
      await updateInventoryItem(id, { buy_link: url });
    } catch {
      fetchItems();
    }
  };

  const openLink = (url: string) => {
    if (url) window.open(url, "_blank", "noopener,noreferrer");
  };

  const displayed = items.filter((it) => {
    if (!filterStock) return true;
    const s = stockStatus(it.quantity).label;
    if (filterStock === "in") return s === "IN";
    if (filterStock === "low") return s === "LOW";
    if (filterStock === "out") return s === "OUT";
    return true;
  });

  const typeCount = (t: string) => items.filter((it) => it.type === t).length;

  const inputCls = "bg-surface-1 border border-surface-2 rounded px-2 py-1.5 text-sm text-text placeholder:text-text-dim focus:outline-none focus:border-accent-DEFAULT";

  return (
    <div className="flex flex-col h-full text-sm">

      {/* Top bar */}
      <div className="flex gap-2 items-center px-3 py-2 border-b border-surface-2">
        <input
          className={`${inputCls} flex-1`}
          placeholder="Search value, model, notes…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <button
          onClick={() => setShowAdd((v) => !v)}
          className={`px-3 py-1.5 rounded text-xs font-semibold whitespace-nowrap transition-colors ${
            showAdd ? "bg-surface-2 text-text-dim" : "bg-accent-DEFAULT text-surface"
          }`}
        >
          {showAdd ? "✕ Cancel" : "+ Add Part"}
        </button>
      </div>

      {/* Add form */}
      {showAdd && (
        <div className="px-3 py-2 border-b border-surface-2 bg-surface-1 flex flex-col gap-2">
          <div className="flex gap-2 flex-wrap">
            <select
              value={form.type}
              onChange={(e) => setForm((f) => ({ ...f, type: e.target.value }))}
              className={inputCls}
            >
              {TYPE_LIST.map((t) => <option key={t} value={t}>{t.replace("_", " ")}</option>)}
            </select>
            <input
              autoFocus
              placeholder="Value — e.g. 10kΩ, 100nF, 2N3904"
              value={form.value_display}
              onChange={(e) => setForm((f) => ({ ...f, value_display: e.target.value }))}
              onKeyDown={(e) => e.key === "Enter" && handleAdd()}
              className={`${inputCls} flex-1 min-w-36`}
            />
            <input
              placeholder="Model"
              value={form.model}
              onChange={(e) => setForm((f) => ({ ...f, model: e.target.value }))}
              className={`${inputCls} w-24`}
            />
            <select
              value={form.package}
              onChange={(e) => setForm((f) => ({ ...f, package: e.target.value }))}
              className={inputCls}
            >
              {PACKAGES.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
            <input
              type="number"
              placeholder="Qty"
              value={form.quantity}
              onChange={(e) => setForm((f) => ({ ...f, quantity: Number(e.target.value) }))}
              min={0}
              className={`${inputCls} w-14`}
            />
          </div>
          <div className="flex gap-2 flex-wrap">
            <input
              placeholder="Buy link (URL)"
              value={form.buy_link}
              onChange={(e) => setForm((f) => ({ ...f, buy_link: e.target.value }))}
              className={`${inputCls} flex-1 min-w-40`}
            />
            <input
              placeholder="Notes"
              value={form.notes}
              onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))}
              className={`${inputCls} flex-1 min-w-24`}
            />
            <button
              onClick={handleAdd}
              disabled={saving || !form.value_display.trim()}
              className="px-4 py-1.5 bg-accent-DEFAULT text-surface rounded text-xs font-semibold disabled:opacity-30"
            >
              {saving ? "…" : "Add"}
            </button>
          </div>
        </div>
      )}

      {/* Type filter pills */}
      <div className="flex gap-1.5 px-3 py-2 overflow-x-auto border-b border-surface-2 flex-shrink-0">
        <TypePill label="All" count={items.length} active={filterType === ""} color="rgb(var(--c-text-dim))" onClick={() => setFilterType("")} />
        {TYPE_LIST.filter((t) => typeCount(t) > 0).map((t) => (
          <TypePill
            key={t}
            label={TYPE_LABELS[t] || t}
            count={typeCount(t)}
            active={filterType === t}
            color={TYPE_COLORS[t] || "rgb(var(--c-text-dim))"}
            onClick={() => setFilterType(filterType === t ? "" : t)}
          />
        ))}
        <div className="ml-auto flex gap-1 flex-shrink-0">
          {([["", "All"], ["in", "In Stock"], ["low", "Low"], ["out", "Out"]] as [string, string][]).map(([val, lbl]) => (
            <button
              key={val}
              onClick={() => setFilterStock(filterStock === val ? "" : val)}
              className={`px-2 py-0.5 rounded-full border text-[10px] transition-all ${
                filterStock === val
                  ? val === "in" ? "border-status-success text-status-success bg-status-success/10"
                    : val === "low" ? "border-urgency-med text-urgency-med bg-urgency-med/10"
                    : val === "out" ? "border-urgency-high text-urgency-high bg-urgency-high/10"
                    : "border-accent-DEFAULT text-accent-DEFAULT bg-accent-DEFAULT/10"
                  : "border-surface-2 text-text-dim"
              }`}
            >
              {lbl}
            </button>
          ))}
        </div>
      </div>

      {/* Item list */}
      <div className="flex-1 overflow-y-auto">
        {displayed.length === 0 ? (
          <div className="text-center py-10 text-text-dim text-xs opacity-40">
            {items.length === 0 ? "No parts yet — add your first component above" : "No parts match this filter"}
          </div>
        ) : (
          displayed.map((item) => (
            <ItemRow
              key={item.id}
              item={item}
              hovered={hovered === item.id}
              editLink={editLink === item.id}
              linkDraft={linkDraft}
              linkInputRef={linkInputRef}
              onHover={setHovered}
              onQty={handleQty}
              onDelete={handleDelete}
              onOpenLink={openLink}
              onEditLink={(it) => { setEditLink(it.id); setLinkDraft(it.buy_link || ""); }}
              onLinkDraftChange={setLinkDraft}
              onSaveLink={handleSaveLink}
              onCancelLink={() => setEditLink(null)}
            />
          ))
        )}
      </div>

      {/* Footer */}
      <div className="flex gap-4 px-3 py-1.5 border-t border-surface-2 text-[10px] text-text-dim">
        <span>{displayed.length} part{displayed.length !== 1 ? "s" : ""}</span>
        <span className="text-status-success">{items.filter((i) => stockStatus(i.quantity).label === "IN").length} in stock</span>
        <span className="text-urgency-med">{items.filter((i) => stockStatus(i.quantity).label === "LOW").length} low</span>
        <span className="text-urgency-high">{items.filter((i) => stockStatus(i.quantity).label === "OUT").length} out</span>
      </div>
    </div>
  );
}

function TypePill({ label, count, active, color, onClick }: {
  label: string; count: number; active: boolean; color: string; onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="px-2 py-0.5 rounded-full border text-[10px] whitespace-nowrap transition-all"
      style={{
        borderColor: active ? color : "rgb(var(--c-surface-2))",
        color: active ? color : "rgb(var(--c-text-dim))",
        background: active ? "color-mix(in srgb, " + color + " 15%, transparent)" : "transparent",
      }}
    >
      {label} <span className="opacity-60">{count}</span>
    </button>
  );
}

function ItemRow({ item, hovered, editLink, linkDraft, linkInputRef,
  onHover, onQty, onDelete, onOpenLink, onEditLink, onLinkDraftChange, onSaveLink, onCancelLink }: {
  item: InventoryItem;
  hovered: boolean;
  editLink: boolean;
  linkDraft: string;
  linkInputRef: React.MutableRefObject<HTMLInputElement | null>;
  onHover: (id: string | null) => void;
  onQty: (id: string, delta: number) => void;
  onDelete: (id: string) => void;
  onOpenLink: (url: string) => void;
  onEditLink: (item: InventoryItem) => void;
  onLinkDraftChange: (v: string) => void;
  onSaveLink: (id: string) => void;
  onCancelLink: () => void;
}) {
  const s = stockStatus(item.quantity);
  const color = TYPE_COLORS[item.type] || "rgb(var(--c-text-dim))";
  const abbr = TYPE_LABELS[item.type] || "?";

  const inputCls = "bg-surface-1 border border-surface-2 rounded px-2 py-1 text-xs text-text placeholder:text-text-dim focus:outline-none focus:border-accent-DEFAULT";

  return (
    <div
      onMouseEnter={() => onHover(item.id)}
      onMouseLeave={() => onHover(null)}
      className={`flex items-center gap-2 px-3 py-1.5 border-b border-surface-2/30 transition-colors min-h-[38px] ${hovered ? "bg-surface-1" : ""}`}
    >
      {/* Type badge */}
      <span
        className="text-[9px] font-bold tracking-wider px-1.5 py-0.5 rounded flex-shrink-0 text-center min-w-[28px]"
        style={{ color, background: "color-mix(in srgb, " + color + " 15%, transparent)" }}
      >
        {abbr}
      </span>

      {/* Value + model */}
      <div className="flex-1 min-w-0 truncate">
        <span className="font-mono text-sm text-text">
          {item.value_display || item.model || item.type}
        </span>
        {item.model && item.value_display && (
          <span className="text-xs text-text-dim ml-1.5">{item.model}</span>
        )}
        {item.package && item.package !== "through-hole" && (
          <span className="text-[10px] text-text-dim ml-1.5">{item.package}</span>
        )}
        {item.notes && (
          <span className="text-[10px] text-text-dim ml-1.5 italic">— {item.notes}</span>
        )}
      </div>

      {/* Stock badge */}
      <span className={`text-[9px] font-bold tracking-wider px-1.5 py-0.5 rounded flex-shrink-0 ${s.colorClass}`}>
        {s.label}
      </span>

      {/* Qty stepper */}
      <div className="flex items-center gap-1 flex-shrink-0">
        <button
          onClick={() => onQty(item.id, -1)}
          className="w-5 h-5 rounded border border-surface-2 bg-surface-1 text-text text-xs flex items-center justify-center hover:bg-surface-2 transition-colors"
        >−</button>
        <span className="font-mono text-xs text-text min-w-[20px] text-center">{item.quantity}</span>
        <button
          onClick={() => onQty(item.id, 1)}
          className="w-5 h-5 rounded border border-surface-2 bg-surface-1 text-text text-xs flex items-center justify-center hover:bg-surface-2 transition-colors"
        >+</button>
      </div>

      {/* Buy link */}
      {editLink ? (
        <div className="flex gap-1 items-center">
          <input
            ref={linkInputRef}
            value={linkDraft}
            onChange={(e) => onLinkDraftChange(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") onSaveLink(item.id); if (e.key === "Escape") onCancelLink(); }}
            placeholder="https://..."
            className={`${inputCls} w-36`}
          />
          <button onClick={() => onSaveLink(item.id)} className="w-5 h-5 rounded bg-accent-DEFAULT text-surface text-xs flex items-center justify-center">✓</button>
          <button onClick={onCancelLink} className="w-5 h-5 rounded bg-surface-2 text-text-dim text-xs flex items-center justify-center">✕</button>
        </div>
      ) : (
        <button
          onClick={() => item.buy_link ? onOpenLink(item.buy_link) : onEditLink(item)}
          title={item.buy_link ? `Buy: ${item.buy_link}` : "Add buy link"}
          onContextMenu={(e) => { e.preventDefault(); onEditLink(item); }}
          className={`text-[10px] px-1.5 py-0.5 rounded border flex-shrink-0 transition-all ${
            item.buy_link
              ? "border-accent-DEFAULT/40 text-accent-DEFAULT"
              : hovered
              ? "border-surface-2 text-text-dim"
              : "border-transparent text-transparent"
          }`}
        >
          {item.buy_link ? "Buy" : "+ link"}
        </button>
      )}

      {/* Delete */}
      <button
        onClick={() => onDelete(item.id)}
        className={`text-urgency-high text-sm px-1 rounded flex-shrink-0 transition-opacity hover:opacity-100 ${hovered ? "opacity-60" : "opacity-0"}`}
      >
        ×
      </button>
    </div>
  );
}
