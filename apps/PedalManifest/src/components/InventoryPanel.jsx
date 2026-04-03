import { useState, useEffect, useCallback } from "react";

const TYPES = [
  "all", "resistor", "capacitor", "diode", "LED",
  "NPN_BJT", "PNP_BJT", "N_JFET", "P_JFET", "op_amp", "potentiometer", "switch",
];

// Types that have meaningful datasheet specs to look up
const ACTIVE_TYPES = new Set(["NPN_BJT", "PNP_BJT", "N_JFET", "P_JFET", "op_amp", "diode", "LED"]);

const EMPTY_FORM = {
  type: "resistor", value: "", unit: "ohm", tolerance: "5%",
  package: "through-hole", voltage_rating: "", quantity: 1,
  notes: "", buy_link: "", model: "", specs: {},
};

const UNIT_FOR_TYPE = {
  resistor: "ohm", capacitor: "F", potentiometer: "ohm",
};

function stockBadge(qty) {
  if (qty === 0) return <span className="px-1.5 py-0.5 rounded text-xs bg-red-900/60 text-red-300">OUT</span>;
  if (qty <= 2) return <span className="px-1.5 py-0.5 rounded text-xs bg-yellow-800/60 text-yellow-300">LOW</span>;
  return <span className="px-1.5 py-0.5 rounded text-xs bg-green-900/60 text-green-300">IN</span>;
}

function formatValue(item) {
  if (item.model && ACTIVE_TYPES.has(item.type)) return item.model;
  if (!item.value) return "—";
  const v = Number(item.value);
  if (item.unit === "ohm") {
    if (v >= 1e6) return `${v / 1e6}MΩ`;
    if (v >= 1e3) return `${v / 1e3}kΩ`;
    return `${v}Ω`;
  }
  if (item.unit === "F") {
    if (v >= 1e-3) return `${(v * 1e3).toPrecision(3)}mF`;
    if (v >= 1e-6) return `${(v * 1e6).toPrecision(3)}µF`;
    if (v >= 1e-9) return `${(v * 1e9).toPrecision(3)}nF`;
    return `${(v * 1e12).toPrecision(3)}pF`;
  }
  return `${v} ${item.unit || ""}`;
}

// Render the most useful spec fields for a given component type
function SpecBadges({ specs, type }) {
  if (!specs || Object.keys(specs).length === 0) return null;
  const badges = [];

  if (type === "NPN_BJT" || type === "PNP_BJT") {
    if (specs.hfe_typ) badges.push(`hFE ${specs.hfe_min ?? "?"}–${specs.hfe_max ?? "?"}`);
    if (specs.vceo_v) badges.push(`Vce ${Math.abs(specs.vceo_v)}V`);
    if (specs.ic_max_ma) badges.push(`Ic ${Math.abs(specs.ic_max_ma)}mA`);
    if (specs.material) badges.push(specs.material);
  } else if (type === "N_JFET" || type === "P_JFET") {
    if (specs.idss_min_ma != null) badges.push(`Idss ${specs.idss_min_ma}–${specs.idss_max_ma}mA`);
    if (specs.vgs_off_max_v) badges.push(`Vp ${specs.vgs_off_min_v}…${specs.vgs_off_max_v}V`);
    if (specs.vds_max_v) badges.push(`Vds ${specs.vds_max_v}V`);
  } else if (type === "op_amp") {
    if (specs.gbw_mhz) badges.push(`${specs.gbw_mhz}MHz`);
    if (specs.slew_rate_v_us) badges.push(`${specs.slew_rate_v_us}V/µs`);
    if (specs.channels) badges.push(`${specs.channels}ch`);
    if (specs.input_type) badges.push(specs.input_type);
  } else if (type === "diode" || type === "LED") {
    if (specs.vf_v) badges.push(`Vf ${specs.vf_v}V`);
    if (specs.vr_max_v) badges.push(`Vr ${specs.vr_max_v}V`);
    if (specs.material) badges.push(specs.material);
  }

  if (badges.length === 0) return null;
  return (
    <div className="flex gap-1 flex-wrap mt-0.5">
      {badges.map((b, i) => (
        <span key={i} className="text-[10px] px-1 py-0 rounded bg-surface-2 text-text-muted font-mono">{b}</span>
      ))}
    </div>
  );
}

export default function InventoryPanel() {
  const [items, setItems] = useState([]);
  const [typeFilter, setTypeFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [editingId, setEditingId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [lookupState, setLookupState] = useState(null); // null | 'loading' | 'found' | 'notfound'
  const [expandedSpecs, setExpandedSpecs] = useState(null); // item id

  const load = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (typeFilter !== "all") params.set("type", typeFilter);
      if (search) params.set("search", search);
      const r = await fetch(`/api/inventory?${params}`);
      if (r.ok) setItems((await r.json()).items ?? []);
    } catch {}
    setLoading(false);
  }, [typeFilter, search]);

  useEffect(() => { load(); }, [load]);

  async function lookupPart() {
    const part = form.model?.trim();
    if (!part) return;
    setLookupState("loading");
    try {
      const r = await fetch(`/api/physics/lookup/${encodeURIComponent(part)}`);
      if (!r.ok) { setLookupState("notfound"); return; }
      const data = await r.json();
      if (data.found) {
        // Auto-fill form fields from specs
        const updates = { specs: data };
        if (data.package && !form.package) updates.package = data.package;
        if (data.type) updates.type = data.type;
        if (data.description) updates.notes = data.description.slice(0, 80);
        // For diodes/transistors, clear numeric value (part number is the identifier)
        if (ACTIVE_TYPES.has(data.type)) updates.value = "";
        setForm(f => ({ ...f, ...updates }));
        setLookupState("found");
      } else {
        setLookupState("notfound");
      }
    } catch {
      setLookupState("notfound");
    }
  }

  async function saveItem() {
    const body = {
      ...form,
      value: form.value !== "" ? Number(form.value) : null,
      voltage_rating: Number(form.voltage_rating) || 0,
      quantity: Number(form.quantity),
      specs: form.specs || {},
    };
    if (editingId) {
      await fetch(`/api/inventory/${editingId}`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    } else {
      await fetch("/api/inventory", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    }
    setShowForm(false); setEditingId(null); setForm(EMPTY_FORM); setLookupState(null);
    load();
  }

  async function deleteItem(id) {
    await fetch(`/api/inventory/${id}`, { method: "DELETE" });
    load();
  }

  async function adjustQty(id, delta) {
    await fetch(`/api/inventory/${id}/quantity?delta=${delta}`, { method: "PATCH" });
    setItems(prev => prev.map(i => i.id === id ? { ...i, quantity: Math.max(0, i.quantity + delta) } : i));
  }

  function startEdit(item) {
    setForm({ ...EMPTY_FORM, ...item, specs: item.specs || {} });
    setEditingId(item.id);
    setShowForm(true);
    setLookupState(null);
  }

  function handleTypeChange(t) {
    setForm(f => ({ ...f, type: t, unit: UNIT_FOR_TYPE[t] || f.unit }));
  }

  const lowStock = items.filter(i => i.quantity <= 2 && i.quantity > 0).length;
  const outOfStock = items.filter(i => i.quantity === 0).length;
  const isActive = ACTIVE_TYPES.has(form.type);

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-3 py-2 bg-surface-1 border-b border-surface-2 shrink-0 flex-wrap gap-y-1">
        <input
          className="bg-surface-2 rounded px-2 py-1 text-sm w-40 placeholder:text-text-dim"
          placeholder="Search…"
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
        <div className="flex gap-1 flex-wrap">
          {TYPES.map(t => (
            <button
              key={t}
              onClick={() => setTypeFilter(t)}
              className={`px-2 py-0.5 rounded text-xs transition-colors ${
                typeFilter === t ? "bg-accent text-surface" : "bg-surface-2 text-text-muted hover:text-text"
              }`}
            >
              {t}
            </button>
          ))}
        </div>
        <div className="flex-1" />
        {lowStock > 0 && <span className="text-xs text-yellow-300">{lowStock} low</span>}
        {outOfStock > 0 && <span className="text-xs text-red-300">{outOfStock} out</span>}
        <button
          onClick={() => { setShowForm(true); setEditingId(null); setForm(EMPTY_FORM); setLookupState(null); }}
          className="px-3 py-1 rounded bg-accent text-surface text-sm font-medium hover:bg-accent-dim transition-colors"
        >
          + Add
        </button>
      </div>

      {/* Add/Edit Form */}
      {showForm && (
        <div className="bg-surface-1 border-b border-surface-2 px-3 py-3 shrink-0">
          <div className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
            {/* Type */}
            <div className="flex flex-col gap-1">
              <label className="text-text-muted text-xs">Type</label>
              <select
                className="bg-surface-2 rounded px-2 py-1"
                value={form.type}
                onChange={e => handleTypeChange(e.target.value)}
              >
                {TYPES.filter(t => t !== "all").map(t => <option key={t}>{t}</option>)}
              </select>
            </div>

            {/* Part number + lookup (only for active components) */}
            {isActive ? (
              <div className="flex flex-col gap-1 col-span-2">
                <label className="text-text-muted text-xs">Part Number</label>
                <div className="flex gap-1.5">
                  <input
                    className="flex-1 bg-surface-2 rounded px-2 py-1"
                    placeholder="e.g. 2N3904, TL072, 1N4148"
                    value={form.model}
                    onChange={e => { setForm(f => ({ ...f, model: e.target.value })); setLookupState(null); }}
                    onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); lookupPart(); } }}
                  />
                  <button
                    onClick={lookupPart}
                    disabled={lookupState === "loading" || !form.model?.trim()}
                    className="px-2.5 py-1 rounded text-xs font-medium transition-colors disabled:opacity-40 bg-surface-2 hover:bg-surface-3 text-text-muted"
                  >
                    {lookupState === "loading" ? "…" : "Lookup"}
                  </button>
                  {lookupState === "found" && (
                    <span className="text-xs text-green-400 self-center">✓ specs loaded</span>
                  )}
                  {lookupState === "notfound" && (
                    <span className="text-xs text-text-dim self-center">not found — fill manually</span>
                  )}
                </div>
                {form.specs?.description && (
                  <p className="text-[10px] text-text-dim mt-0.5">{form.specs.description}</p>
                )}
                {form.specs?.pedal_notes && (
                  <p className="text-[10px] text-text-muted mt-0.5 italic">{form.specs.pedal_notes}</p>
                )}
              </div>
            ) : (
              <>
                <div className="flex flex-col gap-1">
                  <label className="text-text-muted text-xs">Value</label>
                  <input className="bg-surface-2 rounded px-2 py-1" placeholder="10000" value={form.value} onChange={e => setForm(f => ({ ...f, value: e.target.value }))} />
                </div>
                <div className="flex flex-col gap-1">
                  <label className="text-text-muted text-xs">Unit</label>
                  <input className="bg-surface-2 rounded px-2 py-1" placeholder="ohm / F" value={form.unit} onChange={e => setForm(f => ({ ...f, unit: e.target.value }))} />
                </div>
              </>
            )}

            <div className="flex flex-col gap-1">
              <label className="text-text-muted text-xs">Qty</label>
              <input className="bg-surface-2 rounded px-2 py-1" type="number" min="0" value={form.quantity} onChange={e => setForm(f => ({ ...f, quantity: e.target.value }))} />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-text-muted text-xs">Tolerance</label>
              <input className="bg-surface-2 rounded px-2 py-1" placeholder="5%" value={form.tolerance} onChange={e => setForm(f => ({ ...f, tolerance: e.target.value }))} />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-text-muted text-xs">Package</label>
              <input className="bg-surface-2 rounded px-2 py-1" placeholder="through-hole" value={form.package} onChange={e => setForm(f => ({ ...f, package: e.target.value }))} />
            </div>
            {!isActive && (
              <div className="flex flex-col gap-1">
                <label className="text-text-muted text-xs">Voltage rating</label>
                <input className="bg-surface-2 rounded px-2 py-1" type="number" min="0" placeholder="50" value={form.voltage_rating} onChange={e => setForm(f => ({ ...f, voltage_rating: e.target.value }))} />
              </div>
            )}
            <div className="flex flex-col gap-1">
              <label className="text-text-muted text-xs">Notes</label>
              <input className="bg-surface-2 rounded px-2 py-1" placeholder="1/4W carbon film" value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))} />
            </div>
            <div className="flex flex-col gap-1 col-span-2">
              <label className="text-text-muted text-xs">Buy link</label>
              <input className="bg-surface-2 rounded px-2 py-1" placeholder="https://…" value={form.buy_link} onChange={e => setForm(f => ({ ...f, buy_link: e.target.value }))} />
            </div>
          </div>
          <div className="flex gap-2 mt-2">
            <button onClick={saveItem} className="px-3 py-1 rounded bg-accent text-surface text-sm font-medium hover:bg-accent-dim">Save</button>
            <button onClick={() => { setShowForm(false); setEditingId(null); setLookupState(null); }} className="px-3 py-1 rounded bg-surface-2 text-sm hover:bg-surface-3">Cancel</button>
          </div>
        </div>
      )}

      {/* Table */}
      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <div className="p-4 text-text-muted text-sm">Loading…</div>
        ) : items.length === 0 ? (
          <div className="p-4 text-text-muted text-sm">No components. Add some above.</div>
        ) : (
          <table className="w-full text-sm border-collapse">
            <thead className="sticky top-0 bg-surface-1 text-text-muted text-xs">
              <tr>
                <th className="text-left px-3 py-2">Type</th>
                <th className="text-left px-3 py-2">Part / Value</th>
                <th className="text-left px-3 py-2">Specs</th>
                <th className="text-left px-3 py-2">Pkg</th>
                <th className="text-left px-3 py-2">Notes</th>
                <th className="text-center px-3 py-2">Qty</th>
                <th className="text-center px-3 py-2">Stock</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <>
                  <tr key={item.id} className="border-t border-surface-2 hover:bg-surface-1/50">
                    <td className="px-3 py-1.5 text-text-muted">{item.type}</td>
                    <td className="px-3 py-1.5 font-mono">
                      {formatValue(item)}
                      {item.buy_link && (
                        <a href={item.buy_link} target="_blank" rel="noreferrer"
                          className="ml-2 text-accent text-xs hover:underline" title={item.buy_link}>
                          buy
                        </a>
                      )}
                    </td>
                    <td className="px-3 py-1.5">
                      {item.specs && Object.keys(item.specs).length > 0 ? (
                        <button
                          onClick={() => setExpandedSpecs(expandedSpecs === item.id ? null : item.id)}
                          className="text-left"
                        >
                          <SpecBadges specs={item.specs} type={item.type} />
                        </button>
                      ) : (
                        <span className="text-text-dim text-xs">—</span>
                      )}
                    </td>
                    <td className="px-3 py-1.5 text-text-muted">{item.package || "—"}</td>
                    <td className="px-3 py-1.5 text-text-muted max-w-[120px] truncate">{item.notes}</td>
                    <td className="px-3 py-1.5">
                      <div className="flex items-center justify-center gap-1">
                        <button onClick={() => adjustQty(item.id, -1)} className="w-5 h-5 rounded bg-surface-2 hover:bg-surface-3 flex items-center justify-center leading-none">−</button>
                        <span className="w-6 text-center">{item.quantity}</span>
                        <button onClick={() => adjustQty(item.id, 1)} className="w-5 h-5 rounded bg-surface-2 hover:bg-surface-3 flex items-center justify-center leading-none">+</button>
                      </div>
                    </td>
                    <td className="px-3 py-1.5 text-center">{stockBadge(item.quantity)}</td>
                    <td className="px-3 py-1.5">
                      <div className="flex gap-1 justify-end">
                        <button onClick={() => startEdit(item)} className="px-2 py-0.5 rounded text-xs bg-surface-2 hover:bg-surface-3">edit</button>
                        <button onClick={() => deleteItem(item.id)} className="px-2 py-0.5 rounded text-xs bg-surface-2 hover:bg-red-900/50 text-red-400">del</button>
                      </div>
                    </td>
                  </tr>
                  {expandedSpecs === item.id && item.specs && Object.keys(item.specs).length > 0 && (
                    <tr key={`${item.id}-specs`} className="border-t border-surface-2/30 bg-surface-1/20">
                      <td colSpan={8} className="px-4 py-2">
                        <SpecsPanel specs={item.specs} type={item.type} />
                      </td>
                    </tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Footer */}
      <div className="px-3 py-1.5 bg-surface-1 border-t border-surface-2 text-xs text-text-muted shrink-0">
        {items.length} component{items.length !== 1 ? "s" : ""} · {items.reduce((s, i) => s + i.quantity, 0)} total parts
      </div>
    </div>
  );
}

// Expanded specs detail panel
function SpecsPanel({ specs, type }) {
  const rows = [];

  const add = (label, value, unit = "") => {
    if (value != null && value !== "") rows.push({ label, value, unit });
  };

  if (type === "NPN_BJT" || type === "PNP_BJT") {
    add("hFE (min/typ/max)", `${specs.hfe_min ?? "?"} / ${specs.hfe_typ ?? "?"} / ${specs.hfe_max ?? "?"}`);
    add("Vceo", Math.abs(specs.vceo_v ?? 0), "V");
    add("Ic max", Math.abs(specs.ic_max_ma ?? 0), "mA");
    add("Pd max", specs.pd_mw, "mW");
    add("Vbe", specs.vbe_v, "V");
    add("Vce(sat)", specs.vce_sat_v, "V");
    add("fT", specs.ft_mhz, "MHz");
    add("Icbo leakage", specs.leakage_icbo_ua, "µA");
    add("Material", specs.material);
  } else if (type === "N_JFET" || type === "P_JFET") {
    add("Idss (min/max)", `${specs.idss_min_ma ?? "?"}–${specs.idss_max_ma ?? "?"}`, "mA");
    add("Vgs(off) (min/max)", `${specs.vgs_off_min_v ?? "?"}…${specs.vgs_off_max_v ?? "?"}`, "V");
    add("Vds max", specs.vds_max_v, "V");
    add("fT", specs.ft_mhz, "MHz");
  } else if (type === "op_amp") {
    add("Channels", specs.channels);
    add("Input type", specs.input_type);
    add("Vcc (dual max)", specs.vcc_dual_max_v, "V per rail");
    add("GBW", specs.gbw_mhz, "MHz");
    add("Slew rate", specs.slew_rate_v_us, "V/µs");
    add("Input bias", specs.input_bias_pa != null ? (specs.input_bias_pa / 1e12 * 1e6).toPrecision(3) : null, "µA");
    add("Noise", specs.noise_nv_rtHz, "nV/√Hz");
    add("Output current", specs.output_current_ma, "mA");
    add("Is OTA", specs.is_ota ? "Yes" : null);
  } else if (type === "diode" || type === "LED") {
    add("Material", specs.material);
    add("Vf (at 10mA)", specs.vf_v, "V");
    add("Vf (at 1mA)", specs.vf_low_v, "V");
    add("Vr max", specs.vr_max_v, "V");
    add("If max", specs.if_max_ma, "mA");
    add("Reverse leakage", specs.is_ua, "µA");
    add("Recovery time", specs.trr_ns, "ns");
    if (specs.led_color) add("LED color", specs.led_color);
  }

  if (specs.pedal_notes) {
    rows.push({ label: "Notes", value: specs.pedal_notes, unit: "", isNote: true });
  }

  return (
    <div className="grid grid-cols-2 gap-x-6 gap-y-0.5 text-xs sm:grid-cols-3 lg:grid-cols-4">
      {rows.map((r, i) => (
        r.isNote ? (
          <div key={i} className="col-span-full text-text-dim italic mt-1">{r.value}</div>
        ) : (
          <div key={i} className="flex justify-between gap-2">
            <span className="text-text-dim shrink-0">{r.label}</span>
            <span className="text-text font-mono text-right">{r.value}{r.unit ? ` ${r.unit}` : ""}</span>
          </div>
        )
      ))}
    </div>
  );
}
