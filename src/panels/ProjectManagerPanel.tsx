import { useState, useEffect, useCallback, useRef } from "react";
import { invoke } from "@tauri-apps/api/core";

interface Project {
  id: string;
  name: string;
  description: string | null;
  status: string;
  folder_path: string | null;
  parent_id: string | null;
  created_at: string;
  updated_at: string;
  educat_course_id: string | null;
  educat_course_name: string | null;
  spec_path: string | null;
}

interface MoodleCourse {
  id: string;
  name: string;
}

interface ProjectEntry {
  id: string;
  project_id: string;
  entry_type: string;
  content: string;
  tags: string | null;
  completed: boolean;
  created_at: string;
  parent_id: string | null;
  google_task_id: string | null;
}

const ENTRY_TYPES = [
  {
    value: "todo",
    label: "Todo",
    text: "text-status-star",
    pill: "bg-status-star/15 text-status-star border-status-star/30",
    placeholder: "Something that needs to be done…",
  },
  {
    value: "update",
    label: "Update",
    text: "text-cat-progress",
    pill: "bg-cat-progress/20 text-cat-progress border-cat-progress/30",
    placeholder: "What happened, where we left off…",
  },
  {
    value: "decision",
    label: "Decision",
    text: "text-cat-decision",
    pill: "bg-cat-decision/20 text-cat-decision border-cat-decision/30",
    placeholder: "We decided to use X because Y…",
  },
  {
    value: "idea",
    label: "Idea",
    text: "text-cat-reference",
    pill: "bg-cat-reference/20 text-cat-reference border-cat-reference/30",
    placeholder: "What if we tried…",
  },
  {
    value: "blocker",
    label: "Blocker",
    text: "text-cat-constraint",
    pill: "bg-cat-constraint/20 text-cat-constraint border-cat-constraint/30",
    placeholder: "Blocked on X until Y happens…",
  },
  {
    value: "reference",
    label: "Reference",
    text: "text-cat-note",
    pill: "bg-cat-note/15 text-cat-note border-cat-note/30",
    placeholder: "Datasheet, link, or source…",
  },
] as const;

type EntryTypeValue = (typeof ENTRY_TYPES)[number]["value"];

const TYPE_META = Object.fromEntries(ENTRY_TYPES.map((t) => [t.value, t])) as Record<
  string,
  (typeof ENTRY_TYPES)[number]
>;

const STATUS_OPTIONS = ["active", "paused", "completed", "archived"];

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 7) return `${d}d ago`;
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function folderName(path: string): string {
  return path.replace(/\\/g, "/").split("/").filter(Boolean).pop() ?? path;
}

export default function ProjectManagerPanel() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(
    () => localStorage.getItem("caden-pm-last-project")
  );
  const [entries, setEntries] = useState<ProjectEntry[]>([]);
  const [loadingEntries, setLoadingEntries] = useState(false);
  const [filterText, setFilterText] = useState("");

  const [showAddProject, setShowAddProject] = useState(false);
  const [newProjectName, setNewProjectName] = useState("");
  const [newProjectDesc, setNewProjectDesc] = useState("");
  const [savingProject, setSavingProject] = useState(false);

  const [entryType, setEntryType] = useState<EntryTypeValue>("update");
  const [entryContent, setEntryContent] = useState("");
  const [savingEntry, setSavingEntry] = useState(false);

  const [editingProject, setEditingProject] = useState(false);
  const [editName, setEditName] = useState("");
  const [editDesc, setEditDesc] = useState("");
  const [editStatus, setEditStatus] = useState("active");

  const [editingEntryId, setEditingEntryId] = useState<string | null>(null);
  const [editingEntryContent, setEditingEntryContent] = useState("");
  const [savingEntryEdit, setSavingEntryEdit] = useState(false);

  const [totalTime, setTotalTime] = useState<number>(0);

  const [moodleCourses, setMoodleCourses] = useState<MoodleCourse[]>([]);
  const [showCourseSelector, setShowCourseSelector] = useState(false);
  const [loadingCourses, setLoadingCourses] = useState(false);
  const [courseError, setCourseError] = useState<string | null>(null);

  const entryInputRef = useRef<HTMLTextAreaElement>(null);
  const sidebarRef = useRef<HTMLDivElement>(null);

  const [collapsedParents, setCollapsedParents] = useState<Set<string>>(new Set());
  const [dragProjectId, setDragProjectId] = useState<string | null>(null);
  const [dragOverId, setDragOverId] = useState<string | null>(null);
  const [dragOverRoot, setDragOverRoot] = useState(false);

  // Context menu
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; projectId: string } | null>(null);
  const [contextCourseOpen, setContextCourseOpen] = useState(false);

  const loadProjects = useCallback(async () => {
    try {
      const p = await invoke<Project[]>("list_projects");
      const visible = p.filter((proj) => !proj.name.startsWith("__"));
      setProjects(visible);
      setSelectedId((prev) => {
        if (prev && visible.find((proj) => proj.id === prev)) return prev;
        return visible[0]?.id ?? null;
      });
    } catch {}
  }, []);

  useEffect(() => { loadProjects(); }, []);

  useEffect(() => {
    if (!selectedId) { setEntries([]); return; }
    setFilterText("");
    setEditingEntryId(null);
    setLoadingEntries(true);
    invoke<ProjectEntry[]>("get_project_entries", { projectId: selectedId })
      .then(setEntries)
      .catch(() => setEntries([]))
      .finally(() => setLoadingEntries(false));
  }, [selectedId]);

  useEffect(() => {
    if (selectedId) localStorage.setItem("caden-pm-last-project", selectedId);
  }, [selectedId]);

  useEffect(() => {
    if (selectedId) setTimeout(() => entryInputRef.current?.focus(), 50);
  }, [selectedId]);

  useEffect(() => {
    if (!showCourseSelector) return;
    function handle() { setShowCourseSelector(false); }
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [showCourseSelector]);

  useEffect(() => {
    if (!contextMenu) return;
    function handle(e: MouseEvent) {
      const el = document.getElementById("project-context-menu");
      if (el && !el.contains(e.target as Node)) {
        setContextMenu(null);
        setContextCourseOpen(false);
      }
    }
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [contextMenu]);

  useEffect(() => {
    if (!selectedId) { setTotalTime(0); return; }
    invoke<number>("get_project_total_time", { projectId: selectedId })
      .then(setTotalTime)
      .catch(() => setTotalTime(0));
  }, [selectedId]);

  const selectedProject = projects.find((p) => p.id === selectedId) ?? null;

  const childrenByParent = projects.reduce<Record<string, Project[]>>((acc, p) => {
    if (p.parent_id) {
      if (!acc[p.parent_id]) acc[p.parent_id] = [];
      acc[p.parent_id].push(p);
    }
    return acc;
  }, {});

  const rootProjects = projects.filter(
    (p) => !p.parent_id || !projects.find((o) => o.id === p.parent_id)
  );

  function getDescendants(id: string): Set<string> {
    const result = new Set<string>();
    function collect(pid: string) {
      for (const child of childrenByParent[pid] ?? []) {
        result.add(child.id);
        collect(child.id);
      }
    }
    collect(id);
    return result;
  }

  const topLevelEntries = entries.filter((e) => !e.parent_id);
  const subtasksByParent = entries
    .filter((e) => !!e.parent_id)
    .reduce<Record<string, ProjectEntry[]>>((acc, e) => {
      const pid = e.parent_id!;
      if (!acc[pid]) acc[pid] = [];
      acc[pid].push(e);
      return acc;
    }, {});

  const displayedEntries = filterText
    ? topLevelEntries.filter((e) =>
        e.content.toLowerCase().includes(filterText.toLowerCase()) ||
        (subtasksByParent[e.id] ?? []).some((s) =>
          s.content.toLowerCase().includes(filterText.toLowerCase())
        )
      )
    : topLevelEntries;

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
            ? { ...p, name: editName.trim(), description: editDesc.trim() || null, status: editStatus }
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

  async function handleDeleteProject(id: string) {
    const proj = projects.find((p) => p.id === id);
    if (!window.confirm(`Delete "${proj?.name ?? "this project"}"? This cannot be undone.`)) return;
    try {
      await invoke("delete_project", { id });
      const remaining = projects
        .filter((p) => p.id !== id)
        .map((p) => p.parent_id === id ? { ...p, parent_id: null } : p);
      setProjects(remaining);
      if (selectedId === id) setSelectedId(remaining[0]?.id ?? null);
    } catch {}
  }

  async function handleSetParent(projectId: string, parentId: string | null) {
    try {
      await invoke("set_project_parent", { id: projectId, parentId });
      setProjects((prev) =>
        prev.map((p) => p.id === projectId ? { ...p, parent_id: parentId } : p)
      );
    } catch (e) { console.error(e); }
  }

  async function handlePickFolder() {
    if (!selectedProject) return;
    try {
      const path = await invoke<string | null>("pick_project_folder", {
        projectId: selectedProject.id,
      });
      if (path) {
        setProjects((prev) =>
          prev.map((p) => p.id === selectedProject.id ? { ...p, folder_path: path } : p)
        );
      }
    } catch (e) { console.error(e); }
  }

  async function handleOpenFolder() {
    if (!selectedProject?.folder_path) return;
    try {
      await invoke("open_project_folder", { folderPath: selectedProject.folder_path });
    } catch (e) { console.error(e); }
  }

  async function handleShowCourseSelector() {
    if (!selectedProject) return;
    setShowCourseSelector(true);
    setLoadingCourses(true);
    setCourseError(null);
    try {
      const courses = await invoke<MoodleCourse[]>("get_moodle_courses");
      setMoodleCourses(courses);
    } catch (e) {
      setCourseError(String(e));
    } finally {
      setLoadingCourses(false);
    }
  }

  async function handleContextMenuCourse(projectId: string) {
    setContextCourseOpen(true);
    setLoadingCourses(true);
    setCourseError(null);
    try {
      const courses = await invoke<MoodleCourse[]>("get_moodle_courses");
      setMoodleCourses(courses);
    } catch (e) {
      setCourseError(String(e));
    } finally {
      setLoadingCourses(false);
    }
  }

  async function handleContextSetEducatCourse(course: MoodleCourse | null) {
    if (!contextMenu) return;
    const projectId = contextMenu.projectId;
    try {
      await invoke("set_project_educat_course", {
        projectId,
        courseId: course?.id ?? null,
        courseName: course?.name ?? null,
      });
      setProjects((prev) =>
        prev.map((p) =>
          p.id === projectId
            ? { ...p, educat_course_id: course?.id ?? null, educat_course_name: course?.name ?? null }
            : p
        )
      );
    } catch (e) { console.error(e); }
    setContextMenu(null);
    setContextCourseOpen(false);
  }

  async function handleSetEducatCourse(course: MoodleCourse | null) {
    if (!selectedProject) return;
    try {
      await invoke("set_project_educat_course", {
        projectId: selectedProject.id,
        courseId: course?.id ?? null,
        courseName: course?.name ?? null,
      });
      setProjects((prev) =>
        prev.map((p) =>
          p.id === selectedProject.id
            ? { ...p, educat_course_id: course?.id ?? null, educat_course_name: course?.name ?? null }
            : p
        )
      );
    } catch (e) { console.error(e); }
    setShowCourseSelector(false);
  }

  async function handlePickSpec() {
    if (!selectedProject) return;
    try {
      const path = await invoke<string | null>("pick_project_spec", { projectId: selectedProject.id });
      if (path) {
        setProjects((prev) =>
          prev.map((p) => p.id === selectedProject.id ? { ...p, spec_path: path } : p)
        );
      }
    } catch (e) { console.error(e); }
  }

  async function handleOpenSpec() {
    if (!selectedProject?.spec_path) return;
    try {
      await invoke("open_spec_file", { specPath: selectedProject.spec_path });
    } catch (e) { console.error(e); }
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
        parentId: null,
      });
      setEntries((prev) => [e, ...prev]);
      setEntryContent("");
      setProjects((prev) =>
        prev.map((p) => p.id === selectedId ? { ...p, updated_at: e.created_at } : p)
      );
    } catch (e) { console.error(e); } finally {
      setSavingEntry(false);
      entryInputRef.current?.focus();
    }
  }

  async function handleToggleComplete(id: string) {
    try {
      const updated = await invoke<ProjectEntry>("toggle_project_entry_complete", { id });
      setEntries((prev) => prev.map((e) => (e.id === id ? updated : e)));
    } catch {}
  }

  async function handleSaveEntryEdit() {
    if (!editingEntryId || !editingEntryContent.trim()) return;
    setSavingEntryEdit(true);
    try {
      const updated = await invoke<ProjectEntry>("update_project_entry", {
        id: editingEntryId,
        content: editingEntryContent.trim(),
      });
      setEntries((prev) => prev.map((e) => (e.id === updated.id ? updated : e)));
      setEditingEntryId(null);
    } catch (e) { console.error(e); } finally {
      setSavingEntryEdit(false);
    }
  }

  async function handleDeleteEntry(id: string) {
    try {
      await invoke("delete_project_entry", { id });
      setEntries((prev) => prev.filter((e) => e.id !== id));
    } catch {}
  }

  async function handleAddSubtask(parentId: string, content: string) {
    if (!content.trim() || !selectedId) return;
    try {
      const e = await invoke<ProjectEntry>("add_project_entry", {
        projectId: selectedId,
        entryType: "todo",
        content: content.trim(),
        tags: null,
        parentId,
      });
      setEntries((prev) => [...prev, e]);
    } catch (e) { console.error(e); }
  }

  async function handleEditSubtask(id: string, content: string) {
    const updated = await invoke<ProjectEntry>("update_project_entry", { id, content });
    setEntries((prev) => prev.map((e) => (e.id === updated.id ? updated : e)));
  }

  async function handlePromoteEntry(entryId: string, title: string, dueRfc3339: string | null): Promise<void> {
    const googleTaskId = await invoke<string>("promote_entry_to_google_task", {
      entryId, title, dueRfc3339,
    });
    setEntries((prev) =>
      prev.map((e) => (e.id === entryId ? { ...e, google_task_id: googleTaskId } : e))
    );
  }

  function startEditEntry(entry: ProjectEntry) {
    setEditingEntryId(entry.id);
    setEditingEntryContent(entry.content);
  }

  function handleSidebarKeyDown(e: React.KeyboardEvent) {
    if (!projects.length) return;
    const idx = projects.findIndex((p) => p.id === selectedId);
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedId(projects[Math.min(idx + 1, projects.length - 1)].id);
      setEditingProject(false);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedId(projects[Math.max(idx - 1, 0)].id);
      setEditingProject(false);
    }
  }

  function renderProjectTree(projs: Project[], depth: number): React.ReactNode {
    return projs.map((p) => {
      const children = childrenByParent[p.id] ?? [];
      const isCollapsed = collapsedParents.has(p.id);
      const isSelected = p.id === selectedId;
      const isDragOver = dragOverId === p.id;

      return (
        <div key={p.id}>
          <div
            draggable
            onDragStart={(e) => { e.stopPropagation(); setDragProjectId(p.id); e.dataTransfer.effectAllowed = "move"; }}
            onDragEnd={() => { setDragProjectId(null); setDragOverId(null); setDragOverRoot(false); }}
            onDragOver={(e) => {
              e.preventDefault(); e.stopPropagation();
              if (dragProjectId && dragProjectId !== p.id) {
                const descendants = getDescendants(dragProjectId);
                if (!descendants.has(p.id)) { setDragOverId(p.id); setDragOverRoot(false); }
              }
            }}
            onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setDragOverId(null); }}
            onDrop={(e) => {
              e.preventDefault(); e.stopPropagation();
              if (dragProjectId && dragProjectId !== p.id) {
                const descendants = getDescendants(dragProjectId);
                if (!descendants.has(p.id)) handleSetParent(dragProjectId, p.id);
              }
              setDragProjectId(null); setDragOverId(null); setDragOverRoot(false);
            }}
            onClick={() => { setSelectedId(p.id); setEditingProject(false); }}
            onContextMenu={(e) => {
              e.preventDefault();
              setContextMenu({ x: e.clientX, y: e.clientY, projectId: p.id });
              setContextCourseOpen(false);
            }}
            className={`flex items-center w-full border-b border-surface-2/40 transition-colors cursor-pointer select-none ${
              isSelected ? "bg-surface-3 text-text" : "hover:bg-surface-2 text-text"
            } ${isDragOver ? "ring-1 ring-inset ring-accent-DEFAULT" : ""}`}
            style={{ paddingLeft: `${depth * 12}px` }}
          >
            <div
              className="w-8 flex-shrink-0 flex items-center justify-center self-stretch"
              onClick={(e) => {
                if (children.length > 0) {
                  e.stopPropagation();
                  setCollapsedParents((prev) => {
                    const next = new Set(prev);
                    if (next.has(p.id)) next.delete(p.id); else next.add(p.id);
                    return next;
                  });
                }
              }}
            >
              {children.length > 0 ? (
                <span className="text-text-dim text-[8px]">{isCollapsed ? "▶" : "▼"}</span>
              ) : depth > 0 ? (
                <span className="text-text-dim/40 text-[8px]">·</span>
              ) : null}
            </div>
            <div className="flex-1 min-w-0 py-3 pr-4">
              <div className="text-xs font-medium truncate">{p.name}</div>
              <div className="flex items-center gap-1.5 mt-0.5">
                <StatusDot status={p.status} />
                <span className="text-[10px] text-text-muted">{timeAgo(p.updated_at)}</span>
              </div>
            </div>
          </div>
          {!isCollapsed && children.length > 0 && renderProjectTree(children, depth + 1)}
        </div>
      );
    });
  }

  return (
    <div className="flex h-full overflow-hidden bg-surface text-text">
      {/* Sidebar */}
      <div
        ref={sidebarRef}
        tabIndex={0}
        onKeyDown={handleSidebarKeyDown}
        className="w-60 bg-surface border-r border-surface-2 flex flex-col flex-shrink-0 focus:outline-none"
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-surface-2">
          <span className="text-[11px] font-mono uppercase tracking-widest text-text-muted">Projects</span>
          <button
            onClick={() => setShowAddProject((v) => !v)}
            className="text-text-muted hover:text-text transition-colors text-lg leading-none"
            title="New project"
          >+</button>
        </div>

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
              placeholder="Description (optional)"
              value={newProjectDesc}
              onChange={(e) => setNewProjectDesc(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleAddProject()}
            />
            <div className="flex gap-2">
              <button className="btn-primary text-xs flex-1" onClick={handleAddProject} disabled={savingProject || !newProjectName.trim()}>
                {savingProject ? "Adding…" : "Add"}
              </button>
              <button className="btn-ghost text-xs" onClick={() => setShowAddProject(false)}>Cancel</button>
            </div>
          </div>
        )}

        <div className="flex-1 overflow-y-auto">
          {projects.length === 0 ? (
            <div className="px-4 py-6 text-xs text-text-muted text-center">No projects yet.<br />Click + to add one.</div>
          ) : (
            <div>
              {renderProjectTree(rootProjects, 0)}
              {dragProjectId && (
                <div
                  onDragOver={(e) => { e.preventDefault(); setDragOverRoot(true); setDragOverId(null); }}
                  onDragLeave={() => setDragOverRoot(false)}
                  onDrop={(e) => {
                    e.preventDefault();
                    if (dragProjectId) handleSetParent(dragProjectId, null);
                    setDragProjectId(null); setDragOverId(null); setDragOverRoot(false);
                  }}
                  className={`mx-3 my-2 rounded border border-dashed text-[10px] text-center py-1.5 transition-colors ${
                    dragOverRoot ? "border-accent-DEFAULT text-accent bg-accent/10" : "border-surface-3 text-text-dim"
                  }`}
                >
                  drop here to move to root
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Detail panel */}
      <div className="flex-1 flex flex-col overflow-hidden min-w-0">
        <div className="px-6 py-3 border-b border-surface-2 flex-shrink-0">
          {selectedProject && !editingProject ? (
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-text font-medium text-sm">{selectedProject.name}</span>
                  <StatusDot status={selectedProject.status} />
                  <span className="text-[10px] text-text-muted">{selectedProject.status}</span>
                </div>
                {selectedProject.description && (
                  <div className="text-[11px] text-text-muted mt-0.5 truncate">{selectedProject.description}</div>
                )}
                {totalTime > 0 && (
                  <div className="text-[10px] text-text-dim mt-0.5 font-mono">
                    {totalTime >= 60
                      ? `${Math.floor(totalTime / 60)}h ${Math.round(totalTime % 60)}m logged`
                      : `${Math.round(totalTime)}m logged`}
                  </div>
                )}
              </div>
              <div className="flex items-center gap-3 flex-shrink-0 pt-0.5">
                {selectedProject.folder_path ? (
                  <button onClick={handleOpenFolder} title={selectedProject.folder_path}
                    className="flex items-center gap-1 text-[11px] text-text-muted hover:text-text transition-colors">
                    <FolderIcon />
                    <span className="max-w-[120px] truncate">{folderName(selectedProject.folder_path)}</span>
                  </button>
                ) : (
                  <button onClick={handlePickFolder} className="text-[11px] text-text-dim hover:text-text-muted transition-colors" title="Link a folder">
                    + folder
                  </button>
                )}

                {/* Educat course */}
                <div className="relative">
                  {selectedProject.educat_course_name ? (
                    <button onClick={handleShowCourseSelector} onMouseDown={(e) => e.stopPropagation()}
                      className="flex items-center gap-1 text-[11px] text-cat-progress hover:text-text transition-colors"
                      title="Change Educat class">
                      <span className="max-w-[100px] truncate">{selectedProject.educat_course_name}</span>
                    </button>
                  ) : (
                    <button onClick={handleShowCourseSelector} onMouseDown={(e) => e.stopPropagation()}
                      className="text-[11px] text-text-dim hover:text-text-muted transition-colors">
                      + educat
                    </button>
                  )}
                  {showCourseSelector && selectedProject && (
                    <div data-course-selector onMouseDown={(e) => e.stopPropagation()} className="absolute right-0 top-full mt-1 z-50 bg-surface-1 border border-surface-2 rounded shadow-lg min-w-[220px] max-h-60 overflow-y-auto">
                      <div className="px-3 py-2 text-[10px] font-mono uppercase tracking-widest text-text-dim border-b border-surface-2 flex justify-between">
                        <span>Educat Class</span>
                        <button onClick={() => setShowCourseSelector(false)} className="hover:text-text">✕</button>
                      </div>
                      {loadingCourses ? (
                        <div className="px-3 py-2 text-xs text-text-muted">Loading…</div>
                      ) : courseError ? (
                        <div className="px-3 py-2 text-xs text-urgency-high">{courseError}</div>
                      ) : moodleCourses.length === 0 ? (
                        <div className="px-3 py-2 text-xs text-text-muted">No courses found</div>
                      ) : (
                        <>
                          {selectedProject.educat_course_id && (
                            <button onClick={() => handleSetEducatCourse(null)}
                              className="w-full text-left px-3 py-1.5 text-xs text-urgency-high hover:bg-surface-2 transition-colors">
                              Remove link
                            </button>
                          )}
                          {moodleCourses.map((c) => (
                            <button key={c.id} onClick={() => handleSetEducatCourse(c)}
                              className={`w-full text-left px-3 py-1.5 text-xs hover:bg-surface-2 transition-colors ${
                                c.id === selectedProject.educat_course_id ? "text-cat-progress font-medium" : "text-text"
                              }`}>
                              {c.name}
                            </button>
                          ))}
                        </>
                      )}
                    </div>
                  )}
                </div>

                {/* Spec file */}
                {selectedProject.spec_path ? (
                  <button onClick={handleOpenSpec} title={selectedProject.spec_path}
                    className="flex items-center gap-1 text-[11px] text-cat-reference hover:text-text transition-colors">
                    <span className="max-w-[100px] truncate">{selectedProject.spec_path.replace(/\\/g, "/").split("/").pop()}</span>
                    <span className="text-[9px]">↗</span>
                  </button>
                ) : (
                  <button onClick={handlePickSpec} className="text-[11px] text-text-dim hover:text-text-muted transition-colors">
                    + spec
                  </button>
                )}

                <button onClick={startEditProject} className="text-[11px] text-text-muted hover:text-text transition-colors">edit</button>
                <button onClick={() => handleDeleteProject(selectedProject.id)} className="text-[11px] text-text-muted hover:text-urgency-high transition-colors">delete</button>
              </div>
            </div>
          ) : editingProject && selectedProject ? (
            <div className="flex items-center gap-2 flex-wrap">
              <input className="input-field text-xs flex-1 min-w-[120px]" value={editName}
                onChange={(e) => setEditName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && handleSaveProjectEdit()} autoFocus />
              <input className="input-field text-xs flex-1 min-w-[120px]" placeholder="Description"
                value={editDesc} onChange={(e) => setEditDesc(e.target.value)} />
              <select className="input-field text-xs w-28" value={editStatus} onChange={(e) => setEditStatus(e.target.value)}>
                {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
              {selectedProject.folder_path && (
                <button onClick={handlePickFolder} className="text-[11px] text-text-muted hover:text-text transition-colors flex items-center gap-1">
                  <FolderIcon /> change folder
                </button>
              )}
              <button className="btn-primary text-xs" onClick={handleSaveProjectEdit}>Save</button>
              <button className="btn-ghost text-xs" onClick={() => setEditingProject(false)}>Cancel</button>
            </div>
          ) : (
            <div className="text-text-muted text-xs">Select a project</div>
          )}
        </div>

        {selectedProject ? (
          <>
            <div className="px-6 pt-4 pb-3 border-b border-surface-2 flex-shrink-0">
              <div className="flex gap-1.5 flex-wrap mb-2">
                {ENTRY_TYPES.map((t) => (
                  <button key={t.value} onClick={() => setEntryType(t.value)}
                    className={`px-2 py-0.5 rounded text-[10px] font-mono border transition-colors cursor-pointer ${
                      entryType === t.value ? t.pill : "bg-transparent text-text-muted border-surface-3 hover:text-text"
                    }`}
                  >{t.label}</button>
                ))}
              </div>
              <div className="flex gap-2 items-end">
                <textarea
                  ref={entryInputRef}
                  className="input-field text-xs flex-1 min-h-[52px] resize-none"
                  placeholder={TYPE_META[entryType]?.placeholder ?? "Add an entry…"}
                  value={entryContent}
                  onChange={(e) => setEntryContent(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); handleAddEntry(); } }}
                />
                <button className="btn-primary text-xs self-end flex-shrink-0" onClick={handleAddEntry} disabled={savingEntry || !entryContent.trim()}>
                  {savingEntry ? "…" : "Add"}
                </button>
              </div>
              <div className="text-[10px] text-text-dim mt-1">Ctrl+Enter to add</div>
            </div>

            <div className="px-6 py-2 border-b border-surface-2/50 flex-shrink-0">
              <input className="w-full bg-transparent text-xs text-text placeholder:text-text-dim focus:outline-none"
                placeholder="Filter entries…" value={filterText} onChange={(e) => setFilterText(e.target.value)} />
            </div>

            <div className="flex-1 overflow-y-auto px-6 py-4">
              {loadingEntries ? (
                <div className="text-xs text-text-muted">Loading…</div>
              ) : displayedEntries.length === 0 ? (
                <div className="text-xs text-text-muted">
                  {filterText ? "No entries match that filter." : "No entries yet. Add your first one above."}
                </div>
              ) : (
                <div className="flex flex-col gap-3">
                  {displayedEntries.map((entry) => (
                    <EntryRow
                      key={entry.id}
                      entry={entry}
                      subtasks={subtasksByParent[entry.id] ?? []}
                      isEditing={editingEntryId === entry.id}
                      editContent={editingEntryContent}
                      savingEdit={savingEntryEdit}
                      onEditContentChange={setEditingEntryContent}
                      onStartEdit={() => startEditEntry(entry)}
                      onSaveEdit={handleSaveEntryEdit}
                      onCancelEdit={() => setEditingEntryId(null)}
                      onToggleComplete={() => handleToggleComplete(entry.id)}
                      onDelete={() => handleDeleteEntry(entry.id)}
                      onAddSubtask={(content) => handleAddSubtask(entry.id, content)}
                      onSubtaskToggle={(id) => handleToggleComplete(id)}
                      onSubtaskDelete={(id) => handleDeleteEntry(id)}
                      onSubtaskEdit={handleEditSubtask}
                      onPromote={(title, due) => handlePromoteEntry(entry.id, title, due)}
                    />
                  ))}
                </div>
              )}
            </div>
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center text-text-muted text-sm">
            Select a project from the left, or create a new one.
          </div>
        )}
      </div>

      {/* Right-click context menu */}
      {contextMenu && (() => {
        const proj = projects.find((p) => p.id === contextMenu.projectId);
        return (
          <div
            id="project-context-menu"
            className="fixed z-[200] bg-surface-1 border border-surface-2 rounded shadow-lg min-w-[200px] text-xs"
            style={{ top: contextMenu.y, left: contextMenu.x }}
          >
            <div className="px-3 py-1.5 text-[10px] font-mono uppercase tracking-widest text-text-dim border-b border-surface-2 truncate">
              {proj?.name ?? "Project"}
            </div>

            {!contextCourseOpen ? (
              <button
                className="w-full text-left px-3 py-2 hover:bg-surface-2 transition-colors flex items-center justify-between"
                onClick={() => handleContextMenuCourse(contextMenu.projectId)}
              >
                <span>
                  {proj?.educat_course_name
                    ? <><span className="text-text-muted">📚</span> <span className="text-cat-progress">{proj.educat_course_name}</span></>
                    : "📚 Assign Educat course"}
                </span>
                <span className="text-text-dim">›</span>
              </button>
            ) : (
              <div>
                <div className="px-3 py-1.5 text-[10px] text-text-dim border-b border-surface-2 flex justify-between items-center">
                  <span>Educat Course</span>
                  <button onClick={() => setContextCourseOpen(false)} className="hover:text-text">‹ back</button>
                </div>
                {loadingCourses ? (
                  <div className="px-3 py-2 text-text-muted">Loading…</div>
                ) : courseError ? (
                  <div className="px-3 py-2 text-urgency-high">{courseError}</div>
                ) : moodleCourses.length === 0 ? (
                  <div className="px-3 py-2 text-text-muted">No courses found</div>
                ) : (
                  <div className="max-h-56 overflow-y-auto">
                    {proj?.educat_course_id && (
                      <button
                        onClick={() => handleContextSetEducatCourse(null)}
                        className="w-full text-left px-3 py-1.5 text-urgency-high hover:bg-surface-2 transition-colors"
                      >
                        Remove link
                      </button>
                    )}
                    {moodleCourses.map((c) => (
                      <button
                        key={c.id}
                        onClick={() => handleContextSetEducatCourse(c)}
                        className={`w-full text-left px-3 py-1.5 hover:bg-surface-2 transition-colors ${
                          c.id === proj?.educat_course_id ? "text-cat-progress font-medium" : "text-text"
                        }`}
                      >
                        {c.name}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })()}
    </div>
  );
}

function StatusDot({ status }: { status: string }) {
  const color =
    status === "active"    ? "bg-accent-DEFAULT" :
    status === "paused"    ? "bg-urgency-med" :
    status === "completed" ? "bg-cat-decision" :
                             "bg-text-dim";
  return <span className={`inline-block w-1.5 h-1.5 rounded-full flex-shrink-0 ${color}`} />;
}

function FolderIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M1 4a1 1 0 011-1h4l2 2h6a1 1 0 011 1v7a1 1 0 01-1 1H2a1 1 0 01-1-1V4z" />
    </svg>
  );
}

function isoToLocalDate(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function localToIso(date: string, time: string): string | null {
  if (!date) return null;
  return new Date(`${date}T${time || "00:00"}:00`).toISOString();
}

interface EntryRowProps {
  entry: ProjectEntry;
  subtasks: ProjectEntry[];
  isEditing: boolean;
  editContent: string;
  savingEdit: boolean;
  onEditContentChange: (v: string) => void;
  onStartEdit: () => void;
  onSaveEdit: () => void;
  onCancelEdit: () => void;
  onToggleComplete: () => void;
  onDelete: () => void;
  onAddSubtask: (content: string) => void;
  onSubtaskToggle: (id: string) => void;
  onSubtaskDelete: (id: string) => void;
  onSubtaskEdit: (id: string, content: string) => Promise<void>;
  onPromote: (title: string, due: string | null) => Promise<void>;
}

function EntryRow({
  entry, subtasks, isEditing, editContent, savingEdit,
  onEditContentChange, onStartEdit, onSaveEdit, onCancelEdit,
  onToggleComplete, onDelete, onAddSubtask, onSubtaskToggle, onSubtaskDelete, onSubtaskEdit, onPromote,
}: EntryRowProps) {
  const meta = TYPE_META[entry.entry_type];
  const isTodo = entry.entry_type === "todo";

  const [showPromote, setShowPromote] = useState(false);
  const [promoteDate, setPromoteDate] = useState(isoToLocalDate(null));
  const [promoteTime, setPromoteTime] = useState("");
  const [promoting, setPromoting] = useState(false);
  const [promoteError, setPromoteError] = useState<string | null>(null);
  const [showAddSubtask, setShowAddSubtask] = useState(false);
  const [subtaskContent, setSubtaskContent] = useState("");
  const [addingSubtask, setAddingSubtask] = useState(false);
  const [editingSubtaskId, setEditingSubtaskId] = useState<string | null>(null);
  const [editingSubtaskContent, setEditingSubtaskContent] = useState("");
  const [savingSubtaskEdit, setSavingSubtaskEdit] = useState(false);
  const cardRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!showPromote) return;
    function handle(e: MouseEvent) {
      if (cardRef.current && !cardRef.current.contains(e.target as Node)) setShowPromote(false);
    }
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [showPromote]);

  async function handlePromote() {
    if (promoting) return;
    setPromoting(true);
    setPromoteError(null);
    try {
      await onPromote(entry.content.split("\n")[0].slice(0, 100), localToIso(promoteDate, promoteTime));
      setShowPromote(false);
    } catch (e) {
      setPromoteError(String(e));
    } finally {
      setPromoting(false);
    }
  }

  async function handleAddSubtaskInner() {
    if (!subtaskContent.trim() || addingSubtask) return;
    setAddingSubtask(true);
    try {
      await onAddSubtask(subtaskContent.trim());
      setSubtaskContent("");
      setShowAddSubtask(false);
    } finally {
      setAddingSubtask(false);
    }
  }

  async function handleSaveSubtaskEdit() {
    if (!editingSubtaskId || !editingSubtaskContent.trim() || savingSubtaskEdit) return;
    setSavingSubtaskEdit(true);
    try {
      await onSubtaskEdit(editingSubtaskId, editingSubtaskContent.trim());
      setEditingSubtaskId(null);
    } finally {
      setSavingSubtaskEdit(false);
    }
  }

  return (
    <div className="group flex gap-2 items-start">
      {!isEditing && (
        <button onClick={onDelete} className="text-[10px] text-text-dim opacity-0 group-hover:opacity-100 hover:text-urgency-high transition-all flex-shrink-0 mt-3 w-3">✕</button>
      )}
      {isEditing && <div className="w-3 flex-shrink-0" />}

      <div ref={cardRef} className="flex-1 min-w-0 bg-surface-2 rounded px-3 py-2.5 flex flex-col gap-2">
        <div className="flex gap-2.5 items-start">
          {isTodo ? (
            <button onClick={onToggleComplete}
              className={`mt-0.5 flex-shrink-0 w-4 h-4 rounded border-2 transition-colors ${
                entry.completed ? "bg-status-star/40 border-status-star" : "bg-surface-3 border-text-muted hover:border-status-star"
              }`}
              title={entry.completed ? "Mark incomplete" : "Mark complete"}
            >
              {entry.completed && (
                <svg viewBox="0 0 10 10" fill="none" className="w-full h-full p-0.5">
                  <polyline points="1.5,5 4,7.5 8.5,2" stroke="var(--c-status-star)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              )}
            </button>
          ) : (
            <span className={`mt-0.5 flex-shrink-0 px-1.5 py-0.5 rounded text-[9px] font-mono border ${meta?.pill ?? "bg-surface-3 text-text-dim border-surface-3"}`}>
              {meta?.label ?? entry.entry_type}
            </span>
          )}

          <div className="flex-1 min-w-0">
            {isEditing ? (
              <div className="flex flex-col gap-1">
                <textarea
                  className="input-field text-xs w-full resize-none min-h-[60px]"
                  value={editContent}
                  onChange={(e) => onEditContentChange(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); onSaveEdit(); }
                    if (e.key === "Escape") onCancelEdit();
                  }}
                  autoFocus
                />
                <div className="flex gap-2">
                  <button className="btn-primary text-[10px]" onClick={onSaveEdit} disabled={savingEdit || !editContent.trim()}>
                    {savingEdit ? "saving…" : "save"}
                  </button>
                  <button className="btn-ghost text-[10px]" onClick={onCancelEdit}>cancel</button>
                </div>
              </div>
            ) : (
              <div
                className={`text-xs leading-relaxed whitespace-pre-wrap cursor-text ${isTodo && entry.completed ? "line-through text-text-dim" : "text-text"}`}
                onClick={onStartEdit} title="Click to edit"
              >{entry.content}</div>
            )}
            {!isEditing && (
              <div className="flex items-center gap-2 mt-0.5">
                <span className="text-[10px] text-text-dim">{timeAgo(entry.created_at)}</span>
                {entry.google_task_id && (
                  <span className="text-[9px] font-mono px-1.5 py-0.5 rounded border bg-accent/15 text-accent-DEFAULT border-accent/30">GTask</span>
                )}
              </div>
            )}
          </div>

          {!isEditing && !entry.google_task_id && (
            <div className="relative flex-shrink-0">
              <button
                onClick={() => { setShowPromote((v) => !v); setPromoteError(null); }}
                title="Add to Google Tasks"
                className="opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-1.5 px-2.5 py-1.5 rounded border border-accent/40 bg-accent/10 hover:bg-accent/20 hover:border-accent-DEFAULT text-accent-DEFAULT text-[11px] font-mono cursor-pointer"
              >
                <svg width="10" height="10" viewBox="0 0 9 9" fill="none" stroke="currentColor" strokeWidth="1.5">
                  <circle cx="4.5" cy="4.5" r="3.5"/><path d="M4.5 2.5v4M2.5 4.5h4"/>
                </svg>
                GTask
              </button>
              {showPromote && (
                <div className="absolute right-0 top-full mt-1 z-50 bg-surface-1 border border-surface-2 rounded shadow-lg p-3 min-w-[200px]" onMouseDown={(e) => e.stopPropagation()}>
                  <div className="text-[10px] font-mono uppercase tracking-widest text-text-dim mb-2">Add to Google Tasks</div>
                  <div className="flex flex-col gap-1.5">
                    <input type="date" value={promoteDate} onChange={(e) => setPromoteDate(e.target.value)}
                      className="w-full bg-surface border border-surface-2 rounded px-2 py-1 text-xs text-text outline-none focus:border-accent-DEFAULT" />
                    <input type="time" value={promoteTime} onChange={(e) => setPromoteTime(e.target.value)}
                      className="w-full bg-surface border border-surface-2 rounded px-2 py-1 text-xs text-text outline-none focus:border-accent-DEFAULT" />
                    {promoteError && <div className="text-[10px] text-urgency-high truncate">{promoteError}</div>}
                    <button onClick={handlePromote} disabled={promoting}
                      className="w-full text-xs bg-accent-DEFAULT text-surface rounded px-2 py-1 disabled:opacity-40 cursor-pointer hover:opacity-90">
                      {promoting ? "…" : "Add"}
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {isTodo && !isEditing && (
          <div className="ml-6 flex flex-col gap-1">
            {subtasks.map((sub) => (
              <div key={sub.id} className="group/sub flex items-center gap-2">
                <button onClick={() => onSubtaskToggle(sub.id)}
                  className={`flex-shrink-0 w-3.5 h-3.5 rounded border-2 transition-colors ${
                    sub.completed ? "bg-status-star/40 border-status-star" : "bg-surface-3 border-text-muted hover:border-status-star"
                  }`}
                >
                  {sub.completed && (
                    <svg viewBox="0 0 10 10" fill="none" className="w-full h-full p-0.5">
                      <polyline points="1.5,5 4,7.5 8.5,2" stroke="var(--c-status-star)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  )}
                </button>
                {editingSubtaskId === sub.id ? (
                  <input
                    autoFocus
                    value={editingSubtaskContent}
                    onChange={(e) => setEditingSubtaskContent(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") { e.preventDefault(); handleSaveSubtaskEdit(); }
                      if (e.key === "Escape") setEditingSubtaskId(null);
                    }}
                    onBlur={handleSaveSubtaskEdit}
                    disabled={savingSubtaskEdit}
                    className="flex-1 min-w-0 bg-surface border border-surface-2 rounded px-2 py-0.5 text-xs text-text outline-none focus:border-status-star"
                  />
                ) : (
                  <span
                    className={`text-xs flex-1 min-w-0 cursor-text ${sub.completed ? "line-through text-text-dim" : "text-text-muted"}`}
                    onClick={() => { setEditingSubtaskId(sub.id); setEditingSubtaskContent(sub.content); }}
                    title="Click to edit"
                  >{sub.content}</span>
                )}
                {editingSubtaskId !== sub.id && (
                  <button onClick={() => onSubtaskDelete(sub.id)} className="opacity-0 group-hover/sub:opacity-100 text-[9px] text-text-dim hover:text-urgency-high transition-all flex-shrink-0">✕</button>
                )}
              </div>
            ))}
            {showAddSubtask ? (
              <div className="flex items-center gap-1.5 mt-0.5">
                <input
                  autoFocus value={subtaskContent} onChange={(e) => setSubtaskContent(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") { e.preventDefault(); handleAddSubtaskInner(); }
                    if (e.key === "Escape") { setShowAddSubtask(false); setSubtaskContent(""); }
                  }}
                  placeholder="Subtask…"
                  className="flex-1 min-w-0 bg-surface border border-surface-2 rounded px-2 py-0.5 text-xs text-text placeholder:text-text-dim outline-none focus:border-status-star"
                  disabled={addingSubtask}
                />
                <button onClick={handleAddSubtaskInner} disabled={addingSubtask || !subtaskContent.trim()}
                  className="text-[10px] text-status-star hover:text-text disabled:opacity-40 cursor-pointer">
                  {addingSubtask ? "…" : "✓"}
                </button>
                <button onClick={() => { setShowAddSubtask(false); setSubtaskContent(""); }}
                  className="text-[10px] text-text-dim hover:text-text cursor-pointer">✕</button>
              </div>
            ) : (
              <button onClick={() => setShowAddSubtask(true)}
                className="text-[10px] text-text-dim hover:text-text-muted transition-colors text-left opacity-0 group-hover:opacity-100">
                + subtask
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
