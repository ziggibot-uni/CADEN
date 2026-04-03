import { useState, useEffect, useCallback } from "react";
import { invoke } from "@tauri-apps/api/core";

interface Project {
  id: string;
  name: string;
  description: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

interface ProjectEntry {
  id: string;
  project_id: string;
  entry_type: string;
  content: string;
  tags: string | null;
  created_at: string;
}

const ENTRY_TYPES = [
  { value: "progress", label: "Progress" },
  { value: "decision", label: "Decision" },
  { value: "constraint", label: "Constraint" },
  { value: "idea", label: "Idea" },
  { value: "note", label: "Note" },
  { value: "reference", label: "Reference" },
];

const ENTRY_TYPE_COLORS: Record<string, string> = {
  progress: "text-cat-progress",
  decision: "text-cat-decision",
  constraint: "text-cat-constraint",
  idea: "text-cat-idea",
  note: "text-cat-note",
  reference: "text-cat-reference",
};

const STATUS_OPTIONS = ["active", "paused", "completed", "archived"];

interface Props {}

export function ProjectsPanel({}: Props) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [entries, setEntries] = useState<ProjectEntry[]>([]);
  const [loadingEntries, setLoadingEntries] = useState(false);

  // Add-project form
  const [showAddProject, setShowAddProject] = useState(false);
  const [newProjectName, setNewProjectName] = useState("");
  const [newProjectDesc, setNewProjectDesc] = useState("");
  const [savingProject, setSavingProject] = useState(false);

  // Add-entry form
  const [entryType, setEntryType] = useState("progress");
  const [entryContent, setEntryContent] = useState("");
  const [savingEntry, setSavingEntry] = useState(false);

  // Edit project name/desc/status inline
  const [editingProject, setEditingProject] = useState(false);
  const [editName, setEditName] = useState("");
  const [editDesc, setEditDesc] = useState("");
  const [editStatus, setEditStatus] = useState("active");

  const loadProjects = useCallback(async () => {
    try {
      const p = await invoke<Project[]>("list_projects");
      setProjects(p);
      if (p.length > 0 && selectedId === null) {
        setSelectedId(p[0].id);
      }
    } catch {}
  }, [selectedId]);

  useEffect(() => {
    loadProjects();
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setEntries([]);
      return;
    }
    setLoadingEntries(true);
    invoke<ProjectEntry[]>("get_project_entries", { projectId: selectedId })
      .then(setEntries)
      .catch(() => setEntries([]))
      .finally(() => setLoadingEntries(false));
  }, [selectedId]);

  const selectedProject = projects.find((p) => p.id === selectedId) ?? null;

  async function handleAddProject() {
    if (!newProjectName.trim()) return;
    setSavingProject(true);
    try {
      const p = await invoke<Project>("add_project", {
        name: newProjectName.trim(),
        description: newProjectDesc.trim() || null,
      });
      setProjects((prev) => [p, ...prev]);
      setSelectedId(p.id);
      setNewProjectName("");
      setNewProjectDesc("");
      setShowAddProject(false);
    } catch (e) {
      console.error(e);
    } finally {
      setSavingProject(false);
    }
  }

  async function handleAddEntry() {
    if (!entryContent.trim() || !selectedId) return;
    setSavingEntry(true);
    try {
      const e = await invoke<ProjectEntry>("add_project_entry", {
        projectId: selectedId,
        entryType,
        content: entryContent.trim(),
        tags: null,
      });
      setEntries((prev) => [e, ...prev]);
      setEntryContent("");
      // Bump project updated_at locally
      setProjects((prev) =>
        prev.map((p) =>
          p.id === selectedId ? { ...p, updated_at: e.created_at } : p
        )
      );
    } catch (e) {
      console.error(e);
    } finally {
      setSavingEntry(false);
    }
  }

  async function handleDeleteEntry(id: string) {
    try {
      await invoke("delete_project_entry", { id });
      setEntries((prev) => prev.filter((e) => e.id !== id));
    } catch {}
  }

  async function handleDeleteProject(id: string) {
    try {
      await invoke("delete_project", { id });
      const remaining = projects.filter((p) => p.id !== id);
      setProjects(remaining);
      setSelectedId(remaining[0]?.id ?? null);
    } catch {}
  }

  async function handleSaveProjectEdit() {
    if (!selectedProject || !editName.trim()) return;
    try {
      await invoke("update_project", {
        id: selectedProject.id,
        name: editName.trim(),
        description: editDesc.trim() || null,
        status: editStatus,
      });
      setProjects((prev) =>
        prev.map((p) =>
          p.id === selectedProject.id
            ? {
                ...p,
                name: editName.trim(),
                description: editDesc.trim() || null,
                status: editStatus,
              }
            : p
        )
      );
      setEditingProject(false);
    } catch {}
  }

  function startEditProject() {
    if (!selectedProject) return;
    setEditName(selectedProject.name);
    setEditDesc(selectedProject.description ?? "");
    setEditStatus(selectedProject.status);
    setEditingProject(true);
  }

  // Group entries by type for display
  const grouped = ENTRY_TYPES.map(({ value, label }) => ({
    type: value,
    label,
    entries: entries.filter((e) => e.entry_type === value),
  })).filter((g) => g.entries.length > 0);

  return (
    <div className="flex flex-1 overflow-hidden">
      {/* Left sidebar — project list */}
      <div className="w-64 bg-surface-1 border-r border-surface-2 flex flex-col flex-shrink-0">
        <div className="flex items-center justify-between px-4 py-3 border-b border-surface-2">
          <span className="text-[11px] font-mono uppercase tracking-widest text-text-dim">
            Projects
          </span>
          <button
            onClick={() => setShowAddProject((v) => !v)}
            className="text-text-dim hover:text-text transition-colors text-lg leading-none"
            title="New project"
          >
            +
          </button>
        </div>

        {/* New project form */}
        {showAddProject && (
          <div className="px-3 py-3 border-b border-surface-2 flex flex-col gap-2">
            <input
              className="input-field text-xs"
              placeholder="Project name"
              value={newProjectName}
              onChange={(e) => setNewProjectName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleAddProject()}
              autoFocus
            />
            <input
              className="input-field text-xs"
              placeholder="Short description (optional)"
              value={newProjectDesc}
              onChange={(e) => setNewProjectDesc(e.target.value)}
            />
            <div className="flex gap-2">
              <button
                className="btn-primary text-xs flex-1"
                onClick={handleAddProject}
                disabled={savingProject || !newProjectName.trim()}
              >
                {savingProject ? "Adding…" : "Add"}
              </button>
              <button
                className="btn-ghost text-xs"
                onClick={() => setShowAddProject(false)}
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {/* Project list */}
        <div className="flex-1 overflow-y-auto">
          {projects.length === 0 ? (
            <div className="px-4 py-6 text-xs text-text-dim text-center">
              No projects yet.
              <br />
              Click + to add one.
            </div>
          ) : (
            projects.map((p) => (
              <button
                key={p.id}
                onClick={() => {
                  setSelectedId(p.id);
                  setEditingProject(false);
                }}
                className={`w-full text-left px-4 py-2.5 border-b border-surface-2/50 transition-colors ${
                  p.id === selectedId
                    ? "bg-surface-3 text-text"
                    : "hover:bg-surface-2 text-text-muted"
                }`}
              >
                <div className="text-xs font-medium truncate">{p.name}</div>
                <div
                  className={`text-[10px] font-mono mt-0.5 ${
                    p.status === "active"
                      ? "text-cat-progress"
                      : p.status === "paused"
                        ? "text-cat-idea"
                        : "text-text-dim"
                  }`}
                >
                  {p.status}
                </div>
              </button>
            ))
          )}
        </div>
      </div>

      {/* Right — detail panel */}
      <div className="flex-1 flex flex-col bg-surface overflow-hidden min-w-0">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-3 border-b border-surface-2">
          {selectedProject && !editingProject ? (
            <div className="flex items-center gap-3 min-w-0">
              <div className="min-w-0">
                <div className="text-text font-light text-sm truncate">
                  {selectedProject.name}
                </div>
                {selectedProject.description && (
                  <div className="text-[11px] text-text-dim truncate">
                    {selectedProject.description}
                  </div>
                )}
              </div>
              <button
                onClick={startEditProject}
                className="text-[11px] text-text-dim hover:text-text transition-colors flex-shrink-0"
              >
                edit
              </button>
              <button
                onClick={() => handleDeleteProject(selectedProject.id)}
                className="text-[11px] text-text-dim hover:text-urgency-high transition-colors flex-shrink-0"
              >
                delete
              </button>
            </div>
          ) : editingProject && selectedProject ? (
            <div className="flex items-center gap-2 flex-1 mr-4">
              <input
                className="input-field text-xs flex-1"
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
              />
              <input
                className="input-field text-xs flex-1"
                placeholder="Description"
                value={editDesc}
                onChange={(e) => setEditDesc(e.target.value)}
              />
              <select
                className="input-field text-xs w-28"
                value={editStatus}
                onChange={(e) => setEditStatus(e.target.value)}
              >
                {STATUS_OPTIONS.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
              <button
                className="btn-primary text-xs"
                onClick={handleSaveProjectEdit}
              >
                Save
              </button>
              <button
                className="btn-ghost text-xs"
                onClick={() => setEditingProject(false)}
              >
                Cancel
              </button>
            </div>
          ) : (
            <div className="text-text-dim text-xs">Select a project</div>
          )}
        </div>

        {selectedProject ? (
          <div className="flex-1 overflow-y-auto px-6 py-4 flex flex-col gap-5">
            {/* Add entry form */}
            <div className="flex gap-2 items-start">
              <select
                className="input-field text-xs w-32 flex-shrink-0"
                value={entryType}
                onChange={(e) => setEntryType(e.target.value)}
              >
                {ENTRY_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
              <textarea
                className="input-field text-xs flex-1 min-h-[60px] resize-none"
                placeholder={entryPlaceholder(entryType)}
                value={entryContent}
                onChange={(e) => setEntryContent(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                    handleAddEntry();
                  }
                }}
              />
              <button
                className="btn-primary text-xs self-end flex-shrink-0"
                onClick={handleAddEntry}
                disabled={savingEntry || !entryContent.trim()}
              >
                {savingEntry ? "…" : "Add"}
              </button>
            </div>

            {/* Entry groups */}
            {loadingEntries ? (
              <div className="text-xs text-text-dim">Loading…</div>
            ) : grouped.length === 0 ? (
              <div className="text-xs text-text-dim">
                No entries yet. Add your first one above.
              </div>
            ) : (
              grouped.map(({ type, label, entries: groupEntries }) => (
                <div key={type}>
                  <div
                    className={`text-[11px] font-mono uppercase tracking-widest mb-2 ${ENTRY_TYPE_COLORS[type] ?? "text-text-dim"}`}
                  >
                    {label}
                  </div>
                  <div className="flex flex-col gap-1.5">
                    {groupEntries.map((entry) => (
                      <div
                        key={entry.id}
                        className="flex items-start gap-2 group"
                      >
                        <div className="flex-1 text-xs text-text-muted leading-relaxed">
                          {entry.content}
                        </div>
                        <button
                          onClick={() => handleDeleteEntry(entry.id)}
                          className="text-[10px] text-text-dim opacity-0 group-hover:opacity-100 hover:text-urgency-high transition-all flex-shrink-0 mt-0.5"
                        >
                          ✕
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              ))
            )}
          </div>
        ) : (
          <div className="flex-1 flex items-center justify-center text-text-dim text-sm">
            Select a project from the left, or create a new one.
          </div>
        )}
      </div>
    </div>
  );
}

function entryPlaceholder(type: string): string {
  switch (type) {
    case "progress":
      return "What we did last session, where we left off…";
    case "decision":
      return "We decided to use X because Y…";
    case "constraint":
      return "Must fit within X, can't use Y because…";
    case "idea":
      return "What if we tried…";
    case "reference":
      return "Datasheet, link, or source…";
    default:
      return "Add a note…";
  }
}
