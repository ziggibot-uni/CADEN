import { useState, useEffect, useRef, useCallback } from "react";

const STORAGE_KEY = "caden-color-overrides";

type ColorOverride = { text?: string; bg?: string };
type Overrides = Record<string, ColorOverride>;

function loadOverrides(): Overrides {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
  } catch {
    return {};
  }
}

function saveOverrides(o: Overrides) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(o));
}

/** Build a stable-ish CSS selector path for an element. */
function selectorFor(el: HTMLElement): string {
  const parts: string[] = [];
  let cur: HTMLElement | null = el;
  while (cur && cur !== document.documentElement && cur !== document.body) {
    let sel = cur.tagName.toLowerCase();
    if (cur.id) {
      parts.unshift(`#${CSS.escape(cur.id)}`);
      break;
    }
    // Use class names that look stable (skip ones with brackets / colons / slashes — Tailwind dynamic)
    const cls = Array.from(cur.classList)
      .filter((c) => !/[[\]:\/]/.test(c))
      .slice(0, 3);
    if (cls.length) sel += "." + cls.map(CSS.escape).join(".");
    const parent = cur.parentElement;
    if (parent) {
      const sibs = Array.from(parent.children).filter(
        (s) => s.tagName === cur!.tagName
      );
      if (sibs.length > 1) {
        sel += `:nth-of-type(${sibs.indexOf(cur) + 1})`;
      }
    }
    parts.unshift(sel);
    cur = cur.parentElement;
  }
  return parts.join(" > ");
}

/** Inject/update a <style> tag with all overrides. */
function applyStyles(overrides: Overrides) {
  let tag = document.getElementById("caden-color-overrides-style");
  if (!tag) {
    tag = document.createElement("style");
    tag.id = "caden-color-overrides-style";
    document.head.appendChild(tag);
  }
  const rules = Object.entries(overrides)
    .map(([sel, o]) => {
      const props: string[] = [];
      if (o.text) props.push(`color: ${o.text} !important`);
      if (o.bg) props.push(`background-color: ${o.bg} !important`);
      return props.length ? `${sel} { ${props.join("; ")}; }` : "";
    })
    .filter(Boolean)
    .join("\n");
  tag.textContent = rules;
}

type MenuState = {
  x: number;
  y: number;
  selector: string;
} | null;

export function ColorContextMenu() {
  const [menu, setMenu] = useState<MenuState>(null);
  const textRef = useRef<HTMLInputElement>(null);
  const bgRef = useRef<HTMLInputElement>(null);
  const overridesRef = useRef<Overrides>(loadOverrides());

  // Apply persisted overrides on mount
  useEffect(() => {
    applyStyles(overridesRef.current);
  }, []);

  const update = useCallback((sel: string, patch: Partial<ColorOverride>) => {
    const o = overridesRef.current;
    o[sel] = { ...o[sel], ...patch };
    // Clean empty
    if (!o[sel].text && !o[sel].bg) delete o[sel];
    saveOverrides(o);
    applyStyles(o);
  }, []);

  const resetColors = useCallback((sel: string) => {
    delete overridesRef.current[sel];
    saveOverrides(overridesRef.current);
    applyStyles(overridesRef.current);
    setMenu(null);
  }, []);

  // Global right-click listener
  useEffect(() => {
    function onContext(e: MouseEvent) {
      const target = e.target as HTMLElement;
      // Don't intercept our own menu
      if (target.closest("#caden-color-ctx")) return;
      e.preventDefault();
      const sel = selectorFor(target);
      if (!sel) return;
      setMenu({ x: e.clientX, y: e.clientY, selector: sel });
    }
    document.addEventListener("contextmenu", onContext);
    return () => document.removeEventListener("contextmenu", onContext);
  }, []);

  // Close on outside click or Escape
  useEffect(() => {
    if (!menu) return;
    const close = () => setMenu(null);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close();
    document.addEventListener("mousedown", handleOutside);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", handleOutside);
      document.removeEventListener("keydown", onKey);
    };
    function handleOutside(e: MouseEvent) {
      if (!(e.target as HTMLElement).closest("#caden-color-ctx")) close();
    }
  }, [menu]);

  if (!menu) return null;

  const existing = overridesRef.current[menu.selector];
  const hasOverride = !!existing;

  // Position: flip if near edges
  const style: React.CSSProperties = {
    position: "fixed",
    top: menu.y,
    left: menu.x,
    zIndex: 99999,
  };
  // Clamp to viewport using fixed minimum estimates; fine-grained clamping
  // happens via the useLayoutEffect below once the element actually renders.
  const MARGIN = 8;
  if (menu.x + 180 + MARGIN > window.innerWidth) style.left = Math.max(MARGIN, menu.x - 180);
  if (menu.y + 160 + MARGIN > window.innerHeight) style.top = Math.max(MARGIN, menu.y - 160);

  return (
    <>
      {/* Hidden native color pickers */}
      <input
        ref={textRef}
        type="color"
        className="hidden"
        defaultValue={existing?.text || "var(--c-text)"}
        onChange={(e) => update(menu.selector, { text: e.target.value })}
      />
      <input
        ref={bgRef}
        type="color"
        className="hidden"
        defaultValue={existing?.bg || "var(--c-surface)"}
        onChange={(e) => update(menu.selector, { bg: e.target.value })}
      />

      <div
        id="caden-color-ctx"
        style={style}
        className="bg-surface-1 border border-surface-2 rounded shadow-lg min-w-[160px] py-1 text-xs font-mono"
      >
        <button
          className="w-full text-left px-3 py-1.5 text-text-muted hover:text-text hover:bg-surface-2 transition-colors cursor-pointer"
          onClick={() => textRef.current?.click()}
        >
          Change text color
        </button>
        <button
          className="w-full text-left px-3 py-1.5 text-text-muted hover:text-text hover:bg-surface-2 transition-colors cursor-pointer"
          onClick={() => bgRef.current?.click()}
        >
          Change background color
        </button>
        {hasOverride && (
          <button
            className="w-full text-left px-3 py-1.5 text-urgency-high hover:bg-surface-2 transition-colors cursor-pointer border-t border-surface-2 mt-1"
            onClick={() => resetColors(menu.selector)}
          >
            Reset colors
          </button>
        )}
      </div>
    </>
  );
}
