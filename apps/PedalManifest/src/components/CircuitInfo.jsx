// Shows compiled circuit components with inventory status (BOM).

const TYPE_ABBR = {
  resistor: "R", capacitor: "C", diode: "D", LED: "LED",
  NPN_BJT: "Q", PNP_BJT: "Q", N_JFET: "J", P_JFET: "J",
  op_amp: "U", potentiometer: "RV", switch: "SW",
};

function formatValue(c) {
  if (c.value_display) return c.value_display;
  if (!c.value) return c.model || "?";
  return String(c.value);
}

export default function CircuitInfo({ circuit, simulation }) {
  if (!circuit) return null;

  const components = circuit.components ?? [];
  const inStock = components.filter(c => c.in_inventory);
  const missing = components.filter(c => !c.in_inventory);

  const current = simulation?.current_draw_ma;
  const allGood = missing.length === 0;

  return (
    <div className="bg-surface-1 rounded border border-surface-2 overflow-hidden">
      <div className="px-3 py-1.5 border-b border-surface-2 flex items-center justify-between">
        <span className="text-xs font-mono text-text-muted uppercase tracking-wide">BOM</span>
        <div className="flex items-center gap-2 text-xs">
          <span className={allGood ? "text-green-400" : "text-text-muted"}>
            {inStock.length}/{components.length} in stock
          </span>
          {current != null && (
            <span className="text-text-muted font-mono">{current.toFixed(1)}mA</span>
          )}
        </div>
      </div>

      <div className="max-h-40 overflow-y-auto">
        <table className="w-full text-xs">
          <tbody>
            {components.map((c, i) => (
              <tr key={i} className={`border-t border-surface-2/50 ${!c.in_inventory ? "bg-red-950/20" : ""}`}>
                <td className="px-2 py-1 text-text-muted font-mono w-8">
                  {TYPE_ABBR[c.type] ?? c.type[0]}{i + 1}
                </td>
                <td className="px-2 py-1 text-text-muted">{c.type}</td>
                <td className="px-2 py-1 font-mono text-text">{formatValue(c)}</td>
                <td className="px-2 py-1 text-text-muted text-[10px]">{c.role}</td>
                <td className="px-2 py-1 text-right">
                  {c.in_inventory
                    ? <span className="text-green-400">✓</span>
                    : <span className="text-red-400">✗</span>
                  }
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {missing.length > 0 && (
        <div className="px-3 py-2 border-t border-surface-2 bg-red-950/20 text-xs text-red-300">
          Missing: {missing.slice(0, 4).map(c => `${formatValue(c)} ${c.type}`).join(", ")}
          {missing.length > 4 && ` +${missing.length - 4} more`}
        </div>
      )}

      {allGood && components.length > 0 && (
        <div className="px-3 py-1.5 border-t border-surface-2 text-xs text-green-400">
          ✓ All components in stock — ready to build
        </div>
      )}
    </div>
  );
}
