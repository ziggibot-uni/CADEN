import React, { useState, useEffect, useCallback, useRef } from 'react';
import { getInventory, addInventoryItem, updateInventoryItem, deleteInventoryItem, adjustQuantity } from '../utils/api';

const TYPE_LIST = [
  'resistor', 'capacitor', 'inductor', 'diode', 'transistor',
  'op_amp', 'potentiometer', 'switch', 'jack', 'led', 'ic', 'other',
];

const TYPE_LABELS = {
  resistor: 'R', capacitor: 'C', inductor: 'L', diode: 'D', transistor: 'Q',
  op_amp: 'IC', potentiometer: 'POT', switch: 'SW', jack: 'J', led: 'LED',
  ic: 'IC', other: '?',
};

const TYPE_COLORS = {
  resistor: '#e8c060', capacitor: 'rgb(var(--c-urgency-low))', inductor: '#7a9fd4', diode: '#c87040',
  transistor: '#50c8a0', op_amp: '#a070c0', potentiometer: '#70a0d0', switch: 'rgb(var(--c-text-muted))',
  jack: 'rgb(var(--c-text-dim))', led: 'rgb(var(--c-status-success))', ic: '#c0a0e0', other: 'rgb(var(--c-text-dim))',
};

const PACKAGES = [
  'through-hole', 'SMD 0402', 'SMD 0603', 'SMD 0805', 'SMD 1206',
  'TO-92', 'TO-220', 'DIP-8', 'SOIC-8', 'other',
];

function stockStatus(qty) {
  if (qty === 0) return { label: 'OUT', color: 'rgb(var(--c-urgency-high))', bg: 'rgb(var(--c-urgency-high) / 0.13)' };
  if (qty <= 2)  return { label: 'LOW', color: 'rgb(var(--c-urgency-med))', bg: 'rgb(var(--c-urgency-med) / 0.13)' };
  return { label: 'IN',  color: 'rgb(var(--c-status-success))', bg: 'rgb(var(--c-status-success) / 0.09)' };
}

const EMPTY_FORM = {
  type: 'resistor', value_display: '', quantity: 1,
  package: 'through-hole', model: '', notes: '', buy_link: '',
};

export default function InventoryPanel() {
  const [items, setItems]           = useState([]);
  const [filterType, setFilterType] = useState('');
  const [filterStock, setFilterStock] = useState('');  // '', 'in', 'low', 'out'
  const [search, setSearch]         = useState('');
  const [showAdd, setShowAdd]       = useState(false);
  const [form, setForm]             = useState(EMPTY_FORM);
  const [saving, setSaving]         = useState(false);
  const [editLink, setEditLink]     = useState(null);   // item id being link-edited
  const [linkDraft, setLinkDraft]   = useState('');
  const [hovered, setHovered]       = useState(null);
  const searchRef = useRef(null);
  const linkInputRef = useRef(null);

  const fetchItems = useCallback(async () => {
    try {
      const data = await getInventory(filterType || undefined, search || undefined);
      setItems(data.items || data || []);
    } catch (err) {
      console.error('Failed to fetch inventory:', err);
    }
  }, [filterType, search]);

  useEffect(() => { fetchItems(); }, [fetchItems]);

  // Focus link input when editing
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
      console.error('Failed to add item:', err);
    } finally {
      setSaving(false);
    }
  };

  const handleQty = async (id, delta) => {
    // Optimistic update
    setItems(prev => prev.map(it =>
      it.id === id ? { ...it, quantity: Math.max(0, it.quantity + delta) } : it
    ));
    try {
      await adjustQuantity(id, delta);
    } catch {
      fetchItems(); // revert on error
    }
  };

  const handleDelete = async (id) => {
    setItems(prev => prev.filter(it => it.id !== id));
    try {
      await deleteInventoryItem(id);
    } catch {
      fetchItems();
    }
  };

  const handleSaveLink = async (id) => {
    const url = linkDraft.trim();
    setItems(prev => prev.map(it => it.id === id ? { ...it, buy_link: url } : it));
    setEditLink(null);
    try {
      await updateInventoryItem(id, { buy_link: url });
    } catch {
      fetchItems();
    }
  };

  const openLink = (url) => {
    if (url) window.open(url, '_blank', 'noopener,noreferrer');
  };

  // Client-side stock filter
  const displayed = items.filter(it => {
    if (!filterStock) return true;
    const s = stockStatus(it.quantity).label;
    if (filterStock === 'in')  return s === 'IN';
    if (filterStock === 'low') return s === 'LOW';
    if (filterStock === 'out') return s === 'OUT';
    return true;
  });

  const typeCount = (t) => items.filter(it => it.type === t).length;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 0 }}>

      {/* Ã¢â€â‚¬Ã¢â€â‚¬ Top bar: search + add Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬ */}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '10px 14px 8px', borderBottom: '1px solid #1c3848' }}>
        <input
          ref={searchRef}
          className="inv-search"
          placeholder="Search value, model, notesÃ¢â‚¬Â¦"
          value={search}
          onChange={e => setSearch(e.target.value)}
          style={{
            flex: 1, background: '#1a3344', border: '1px solid #264855', borderRadius: 5,
            padding: '6px 10px', color: 'rgb(var(--c-text))', fontSize: 13, outline: 'none',
          }}
          onFocus={e => e.target.style.borderColor = 'rgb(var(--c-accent))'}
          onBlur={e => e.target.style.borderColor = '#264855'}
        />
        <button
          onClick={() => { setShowAdd(v => !v); }}
          style={{
            padding: '6px 14px', background: showAdd ? '#264855' : 'rgb(var(--c-accent-dim))',
            color: 'rgb(var(--c-text))', border: 'none', borderRadius: 5, cursor: 'pointer',
            fontSize: 12, fontWeight: 600, whiteSpace: 'nowrap',
            transition: 'background 0.15s',
          }}
        >
          {showAdd ? 'Ã¢Å“â€¢ Cancel' : '+ Add Part'}
        </button>
      </div>

      {/* Ã¢â€â‚¬Ã¢â€â‚¬ Add form Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬ */}
      {showAdd && (
        <div style={{
          padding: '12px 14px', borderBottom: '1px solid #1c3848',
          background: '#162e3a', display: 'flex', flexDirection: 'column', gap: 8,
        }}>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            <select
              value={form.type}
              onChange={e => setForm(f => ({ ...f, type: e.target.value }))}
              style={selectStyle}
            >
              {TYPE_LIST.map(t => <option key={t} value={t}>{t.replace('_', ' ')}</option>)}
            </select>
            <input
              autoFocus
              placeholder="Value Ã¢â‚¬â€ e.g. 10kÃŽÂ©, 100nF, 2N3904"
              value={form.value_display}
              onChange={e => setForm(f => ({ ...f, value_display: e.target.value }))}
              onKeyDown={e => e.key === 'Enter' && handleAdd()}
              style={{ ...inputStyle, flex: 2, minWidth: 160 }}
            />
            <input
              placeholder="Model"
              value={form.model}
              onChange={e => setForm(f => ({ ...f, model: e.target.value }))}
              style={{ ...inputStyle, width: 90 }}
            />
            <select
              value={form.package}
              onChange={e => setForm(f => ({ ...f, package: e.target.value }))}
              style={selectStyle}
            >
              {PACKAGES.map(p => <option key={p} value={p}>{p}</option>)}
            </select>
            <input
              type="number"
              placeholder="Qty"
              value={form.quantity}
              onChange={e => setForm(f => ({ ...f, quantity: e.target.value }))}
              min={0}
              style={{ ...inputStyle, width: 56 }}
            />
          </div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            <input
              placeholder="Buy link (URL)"
              value={form.buy_link}
              onChange={e => setForm(f => ({ ...f, buy_link: e.target.value }))}
              style={{ ...inputStyle, flex: 3, minWidth: 200 }}
            />
            <input
              placeholder="Notes"
              value={form.notes}
              onChange={e => setForm(f => ({ ...f, notes: e.target.value }))}
              style={{ ...inputStyle, flex: 2, minWidth: 120 }}
            />
            <button
              onClick={handleAdd}
              disabled={saving || !form.value_display.trim()}
              style={{
                padding: '5px 16px', background: 'rgb(var(--c-accent-dim))', color: 'rgb(var(--c-text))',
                border: 'none', borderRadius: 4, cursor: 'pointer', fontWeight: 600,
                fontSize: 12, opacity: saving ? 0.6 : 1,
              }}
            >
              {saving ? 'Ã¢â‚¬Â¦' : 'Add'}
            </button>
          </div>
        </div>
      )}

      {/* Ã¢â€â‚¬Ã¢â€â‚¬ Type filter tabs Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬ */}
      <div style={{
        display: 'flex', gap: 4, padding: '8px 14px 6px', overflowX: 'auto',
        borderBottom: '1px solid #1c3848', flexShrink: 0,
      }}>
        <TypePill label="All" count={items.length} active={filterType === ''} color="rgb(var(--c-text-muted))"
          onClick={() => setFilterType('')} />
        {TYPE_LIST.filter(t => typeCount(t) > 0).map(t => (
          <TypePill key={t} label={TYPE_LABELS[t] || t} count={typeCount(t)}
            active={filterType === t} color={TYPE_COLORS[t] || 'rgb(var(--c-text-muted))'}
            onClick={() => setFilterType(filterType === t ? '' : t)} />
        ))}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 4, flexShrink: 0 }}>
          {[['', 'All'], ['in', 'In Stock'], ['low', 'Low'], ['out', 'Out']].map(([val, lbl]) => (
            <button key={val}
              onClick={() => setFilterStock(filterStock === val ? '' : val)}
              style={{
                padding: '2px 8px', borderRadius: 10, border: '1px solid',
                fontSize: 10, cursor: 'pointer', transition: 'all 0.12s',
                background: filterStock === val ? (val === 'in' ? 'rgb(var(--c-status-success) / 0.19)' : val === 'low' ? 'rgb(var(--c-urgency-med) / 0.19)' : val === 'out' ? 'rgb(var(--c-urgency-high) / 0.19)' : 'rgb(var(--c-accent) / 0.19)') : 'transparent',
                borderColor: filterStock === val ? (val === 'in' ? 'rgb(var(--c-status-success))' : val === 'low' ? 'rgb(var(--c-urgency-med))' : val === 'out' ? 'rgb(var(--c-urgency-high))' : 'rgb(var(--c-accent))') : '#264855',
                color: filterStock === val ? (val === 'in' ? 'rgb(var(--c-status-success))' : val === 'low' ? 'rgb(var(--c-urgency-med))' : val === 'out' ? 'rgb(var(--c-urgency-high))' : 'rgb(var(--c-accent))') : 'rgb(var(--c-text-dim))',
              }}
            >{lbl}</button>
          ))}
        </div>
      </div>

      {/* Ã¢â€â‚¬Ã¢â€â‚¬ Item list Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬ */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '4px 0' }}>
        {displayed.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '40px 20px', color: 'rgb(var(--c-text-dim))', fontSize: 13 }}>
            {items.length === 0 ? 'No parts yet Ã¢â‚¬â€ add your first component above' : 'No parts match this filter'}
          </div>
        ) : (
          displayed.map(item => (
            <ItemRow
              key={item.id}
              item={item}
              hovered={hovered === item.id}
              editLink={editLink === item.id}
              linkDraft={linkDraft}
              linkInputRef={linkInputRef}
              onHover={id => setHovered(id)}
              onQty={handleQty}
              onDelete={handleDelete}
              onOpenLink={openLink}
              onEditLink={item => { setEditLink(item.id); setLinkDraft(item.buy_link || ''); }}
              onLinkDraftChange={setLinkDraft}
              onSaveLink={handleSaveLink}
              onCancelLink={() => setEditLink(null)}
            />
          ))
        )}
      </div>

      {/* Ã¢â€â‚¬Ã¢â€â‚¬ Footer count Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬ */}
      <div style={{
        padding: '5px 14px', borderTop: '1px solid #1c3848',
        fontSize: 11, color: 'rgb(var(--c-text-dim))', display: 'flex', gap: 16,
      }}>
        <span>{displayed.length} part{displayed.length !== 1 ? 's' : ''}</span>
        <span style={{ color: 'rgb(var(--c-status-success))' }}>{items.filter(i => stockStatus(i.quantity).label === 'IN').length} in stock</span>
        <span style={{ color: 'rgb(var(--c-urgency-med))' }}>{items.filter(i => stockStatus(i.quantity).label === 'LOW').length} low</span>
        <span style={{ color: 'rgb(var(--c-urgency-high))' }}>{items.filter(i => stockStatus(i.quantity).label === 'OUT').length} out</span>
      </div>
    </div>
  );
}

function TypePill({ label, count, active, color, onClick }) {
  return (
    <button onClick={onClick} style={{
      padding: '2px 8px', borderRadius: 10, border: `1px solid`,
      fontSize: 10, cursor: 'pointer', whiteSpace: 'nowrap',
      transition: 'all 0.12s',
      background: active ? color + '28' : 'transparent',
      borderColor: active ? color : '#264855',
      color: active ? color : 'rgb(var(--c-text-dim))',
    }}>
      {label} <span style={{ opacity: 0.7 }}>{count}</span>
    </button>
  );
}

function ItemRow({ item, hovered, editLink, linkDraft, linkInputRef,
  onHover, onQty, onDelete, onOpenLink, onEditLink, onLinkDraftChange,
  onSaveLink, onCancelLink }) {
  const s = stockStatus(item.quantity);
  const color = TYPE_COLORS[item.type] || 'rgb(var(--c-text-muted))';
  const abbr = TYPE_LABELS[item.type] || '?';

  return (
    <div
      onMouseEnter={() => onHover(item.id)}
      onMouseLeave={() => onHover(null)}
      style={{
        display: 'flex', alignItems: 'center', gap: 8,
        padding: '6px 14px', borderBottom: '1px solid #1c384850',
        background: hovered ? '#1e3a4a' : 'transparent',
        transition: 'background 0.1s',
        minHeight: 38,
      }}
    >
      {/* Type badge */}
      <span style={{
        minWidth: 32, textAlign: 'center', fontSize: 9, fontWeight: 700,
        letterSpacing: '0.5px', padding: '2px 5px', borderRadius: 3,
        background: color + '22', color, flexShrink: 0,
      }}>{abbr}</span>

      {/* Value + model */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <span style={{ fontFamily: 'monospace', fontSize: 13, color: 'rgb(var(--c-text))' }}>
          {item.value_display || item.model || `${item.type}`}
        </span>
        {item.model && item.value_display && (
          <span style={{ fontSize: 11, color: 'rgb(var(--c-text-dim))', marginLeft: 6 }}>{item.model}</span>
        )}
        {item.package && item.package !== 'through-hole' && (
          <span style={{ fontSize: 10, color: 'rgb(var(--c-text-dim))', marginLeft: 6 }}>{item.package}</span>
        )}
        {item.notes && (
          <span style={{ fontSize: 10, color: 'rgb(var(--c-text-dim))', marginLeft: 6, fontStyle: 'italic' }}>Ã¢â‚¬â€ {item.notes}</span>
        )}
      </div>

      {/* Stock status */}
      <span style={{
        fontSize: 9, fontWeight: 700, letterSpacing: '0.5px',
        padding: '2px 6px', borderRadius: 3,
        background: s.bg, color: s.color, flexShrink: 0,
      }}>{s.label}</span>

      {/* Qty stepper */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexShrink: 0 }}>
        <button
          onClick={() => onQty(item.id, -1)}
          style={qtyBtnStyle}
        >Ã¢Ë†â€™</button>
        <span style={{ fontFamily: 'monospace', fontSize: 13, minWidth: 22, textAlign: 'center', color: 'rgb(var(--c-text))' }}>
          {item.quantity}
        </span>
        <button
          onClick={() => onQty(item.id, 1)}
          style={qtyBtnStyle}
        >+</button>
      </div>

      {/* Buy link */}
      {editLink ? (
        <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
          <input
            ref={linkInputRef}
            value={linkDraft}
            onChange={e => onLinkDraftChange(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') onSaveLink(item.id); if (e.key === 'Escape') onCancelLink(); }}
            placeholder="https://..."
            style={{
              ...inputStyle, width: 180, fontSize: 11, padding: '3px 7px',
            }}
          />
          <button onClick={() => onSaveLink(item.id)} style={{ ...miniBtn, background: 'rgb(var(--c-accent-dim))' }}>Ã¢Å“â€œ</button>
          <button onClick={onCancelLink} style={{ ...miniBtn }}>Ã¢Å“â€¢</button>
        </div>
      ) : (
        <button
          onClick={() => item.buy_link ? onOpenLink(item.buy_link) : onEditLink(item)}
          title={item.buy_link ? `Buy: ${item.buy_link}` : 'Add buy link'}
          style={{
            background: 'transparent', border: '1px solid',
            borderColor: item.buy_link ? 'rgb(var(--c-accent) / 0.33)' : (hovered ? '#264855' : 'transparent'),
            borderRadius: 4, padding: '2px 6px', cursor: 'pointer',
            color: item.buy_link ? 'rgb(var(--c-accent))' : 'rgb(var(--c-text-dim))',
            fontSize: 11, flexShrink: 0, transition: 'all 0.1s',
            opacity: (hovered || item.buy_link) ? 1 : 0,
          }}
          onContextMenu={e => { e.preventDefault(); onEditLink(item); }}
        >
          {item.buy_link ? 'Ã°Å¸â€â€” Buy' : '+ link'}
        </button>
      )}

      {/* Delete */}
      <button
        onClick={() => onDelete(item.id)}
        style={{
          background: 'transparent', border: 'none', cursor: 'pointer',
          color: 'rgb(var(--c-urgency-high))', fontSize: 14, padding: '2px 4px', borderRadius: 3,
          opacity: hovered ? 0.7 : 0, transition: 'opacity 0.1s',
          flexShrink: 0,
        }}
        onMouseEnter={e => e.currentTarget.style.opacity = 1}
        onMouseLeave={e => e.currentTarget.style.opacity = hovered ? 0.7 : 0}
      >Ãƒâ€”</button>
    </div>
  );
}

// Shared style objects
const inputStyle = {
  background: '#213d4e', color: 'rgb(var(--c-text))', border: '1px solid #264855',
  borderRadius: 4, padding: '5px 8px', fontSize: 12, outline: 'none',
};

const selectStyle = {
  ...inputStyle, cursor: 'pointer',
};

const qtyBtnStyle = {
  width: 22, height: 22, borderRadius: 3, border: '1px solid #264855',
  background: '#213d4e', color: 'rgb(var(--c-text))', cursor: 'pointer',
  fontSize: 14, display: 'flex', alignItems: 'center', justifyContent: 'center',
  lineHeight: 1,
};

const miniBtn = {
  background: '#264855', border: 'none', borderRadius: 3, color: 'rgb(var(--c-text))',
  padding: '3px 7px', cursor: 'pointer', fontSize: 11,
};
