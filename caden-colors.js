/**
 * CADEN central color palette
 *
 * ALL colors used anywhere in the GUI and apps MUST come from this file.
 *
 * CSS vars store space-separated R G B channels (e.g. "36 75 95") so that
 * Tailwind v3 opacity modifiers (bg-accent/50, text-urgency-high/20, etc.)
 * work correctly. The Tailwind color definitions use the <alpha-value>
 * placeholder which Tailwind replaces with the appropriate opacity.
 *
 * Default values are set in index.css :root block.
 */

/** Helper: wrap a CSS var in rgb() with Tailwind's alpha placeholder */
function withAlpha(varName) {
  return `rgb(var(${varName}) / <alpha-value>)`;
}

export const cadenColors = {
  surface: {
    DEFAULT: withAlpha("--c-surface"),
    1: withAlpha("--c-surface-1"),
    2: withAlpha("--c-surface-2"),
    3: withAlpha("--c-surface-3"),
  },
  accent: {
    DEFAULT: withAlpha("--c-accent"),
    dim: withAlpha("--c-accent-dim"),
    muted: withAlpha("--c-accent-muted"),
  },
  text: {
    DEFAULT: withAlpha("--c-text"),
    muted: withAlpha("--c-text-muted"),
    dim: withAlpha("--c-text-dim"),
  },
  urgency: {
    high: withAlpha("--c-urgency-high"),
    med: withAlpha("--c-urgency-med"),
    low: withAlpha("--c-urgency-low"),
  },
  status: {
    success: withAlpha("--c-status-success"),
    star: withAlpha("--c-status-star"),
  },
  cat: {
    progress: withAlpha("--c-cat-progress"),
    decision: withAlpha("--c-cat-decision"),
    constraint: withAlpha("--c-cat-constraint"),
    idea: withAlpha("--c-cat-idea"),
    reference: withAlpha("--c-cat-reference"),
    note: withAlpha("--c-cat-note"),
  },
  chat: {
    response: withAlpha("--c-chat-response"),
  },
  source: {
    moodle: withAlpha("--c-source-moodle"),
    "moodle-bg": withAlpha("--c-source-moodle-bg"),
  },
};

/**
 * Default hex values — used by the Settings theme editor.
 * The hex is converted to "R G B" when applied to CSS vars.
 */
export const cadenColorDefaults = {
  "--c-surface":      "#244b5f",
  "--c-surface-1":    "#2a556d",
  "--c-surface-2":    "#305972",
  "--c-surface-3":    "#366678",
  "--c-accent":       "#1aabbc",
  "--c-accent-dim":   "#148a9a",
  "--c-accent-muted": "#0d3848",
  "--c-text":         "#e8f4fa",
  "--c-text-muted":   "#9abfcc",
  "--c-text-dim":     "#6898a8",
  "--c-urgency-high": "#e05050",
  "--c-urgency-med":  "#d4a030",
  "--c-urgency-low":  "#45b8c8",
  "--c-status-success": "#3dba72",
  "--c-status-star":    "#e8c060",
  "--c-cat-progress":   "#45b8c8",
  "--c-cat-decision":   "#7a9fd4",
  "--c-cat-constraint": "#e05050",
  "--c-cat-idea":       "#d4a030",
  "--c-cat-reference":  "#9870d4",
  "--c-cat-note":       "#6a9aaa",
  "--c-chat-response":  "#8abcd4",
  "--c-source-moodle":    "#8060c0",
  "--c-source-moodle-bg": "#33375a",
};

/** Convert hex (#rrggbb) to "R G B" space-separated string */
export function hexToRgb(hex) {
  const h = hex.replace("#", "");
  return `${parseInt(h.substring(0, 2), 16)} ${parseInt(h.substring(2, 4), 16)} ${parseInt(h.substring(4, 6), 16)}`;
}

/** Convert "R G B" back to hex for color pickers */
export function rgbToHex(rgb) {
  const parts = rgb.trim().split(/\s+/).map(Number);
  if (parts.length !== 3 || parts.some(isNaN)) return rgb; // pass through if not RGB
  return "#" + parts.map(n => n.toString(16).padStart(2, "0")).join("");
}

/** Get the default RGB values (for :root initialization) */
export function getDefaultsAsRgb() {
  const result = {};
  for (const [key, hex] of Object.entries(cadenColorDefaults)) {
    result[key] = hexToRgb(hex);
  }
  return result;
}

/** Color groups for the settings UI. */
export const cadenColorGroups = [
  {
    name: "Surface",
    description: "Backgrounds and panels",
    keys: ["--c-surface", "--c-surface-1", "--c-surface-2", "--c-surface-3"],
    labels: ["Main BG", "Panel BG", "Elevated", "Active/Borders"],
  },
  {
    name: "Accent",
    description: "Interactive elements",
    keys: ["--c-accent", "--c-accent-dim", "--c-accent-muted"],
    labels: ["Primary", "Hover", "Subtle fill"],
  },
  {
    name: "Text",
    description: "Text and labels",
    keys: ["--c-text", "--c-text-muted", "--c-text-dim"],
    labels: ["Primary", "Secondary", "Placeholder"],
  },
  {
    name: "Urgency",
    description: "Semantic status colors",
    keys: ["--c-urgency-high", "--c-urgency-med", "--c-urgency-low"],
    labels: ["High / Danger", "Medium / Warning", "Low / On-track"],
  },
  {
    name: "Status",
    description: "Success and highlights",
    keys: ["--c-status-success", "--c-status-star"],
    labels: ["Success / Connected", "Star / Highlight"],
  },
  {
    name: "Categories",
    description: "Entry type colors",
    keys: ["--c-cat-progress", "--c-cat-decision", "--c-cat-constraint", "--c-cat-idea", "--c-cat-reference", "--c-cat-note"],
    labels: ["Progress", "Decision", "Constraint", "Idea", "Reference", "Note"],
  },
  {
    name: "Chat",
    description: "Chat panel colors",
    keys: ["--c-chat-response"],
    labels: ["AI response text"],
  },
  {
    name: "Sources",
    description: "Data source tags",
    keys: ["--c-source-moodle", "--c-source-moodle-bg"],
    labels: ["Moodle text", "Moodle background"],
  },
];
