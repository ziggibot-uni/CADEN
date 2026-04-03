/** Per-element color overrides stored in localStorage */

interface ColorOverrides {
  [selector: string]: { text?: string; bg?: string };
}

const STORAGE_KEY = "caden-color-overrides";

export function loadColorOverrides(): ColorOverrides {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

export function applyColorOverrides(overrides: ColorOverrides) {
  for (const [selector, colors] of Object.entries(overrides)) {
    const el = document.querySelector(selector) as HTMLElement | null;
    if (!el) continue;
    if (colors.text) el.style.color = colors.text;
    if (colors.bg) el.style.backgroundColor = colors.bg;
  }
}
