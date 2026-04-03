import { lazy } from "react";
import type { ComponentType, LazyExoticComponent } from "react";

export interface PanelDef {
  id: string;
  name: string;
  component: LazyExoticComponent<ComponentType>;
}

/**
 * Built-in panels rendered directly inside CADEN's component tree.
 * They share the same document, CSS variables, and Tailwind styles as the
 * main dashboard — no iframes, no postMessage, no sandboxing.
 *
 * To add a new built-in panel:
 *   1. Create src/panels/YourPanel.tsx with a default export React component
 *   2. Add an entry here
 * That's it. No Rust changes required.
 */
export const BUILT_IN_PANELS: PanelDef[] = [
  {
    id: "project-manager",
    name: "Projects",
    component: lazy(() => import("./ProjectManagerPanel")),
  },
  {
    id: "thought-dump",
    name: "Thoughts",
    component: lazy(() => import("./ThoughtDumpPanel")),
  },
  {
    id: "pedal-manifest",
    name: "PedalManifest",
    component: lazy(() => import("./PedalManifestPanel")),
  },
  {
    id: "insights",
    name: "Insights",
    component: lazy(() => import("./InsightsPanel")),
  },
  {
    id: "terminal",
    name: "Terminal",
    component: lazy(() => import("./TerminalPanel")),
  },
];
