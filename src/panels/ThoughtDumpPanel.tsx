import { useState, useEffect, useRef, useCallback } from "react";
import { invoke } from "@tauri-apps/api/core";

interface Project {
  id: string;
  name: string;
}

interface ProjectEntry {
  id: string;
  project_id: string;
  entry_type: string;
  content: string;
  created_at: string;
}

const THOUGHTS_PROJECT_NAME = "__thoughts__";

export default function ThoughtDumpPanel() {
  const [projectId, setProjectId] = useState<string | null>(null);
  const [thoughts, setThoughts] = useState<ProjectEntry[]>([]);
  const [input, setInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<ProjectEntry[] | null>(null);
  const [searching, setSearching] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);
  const searchTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [privacyMode, setPrivacyMode] = useState(false);

  const initRan = useRef(false);

  useEffect(() => {
    if (initRan.current) return;
    initRan.current = true;

    async function init() {
      try {
        const projects = await invoke<Project[]>("list_projects");
        let proj = projects.find((p) => p.name === THOUGHTS_PROJECT_NAME);
        if (!proj) {
          proj = await invoke<Project>("add_project", {
            name: THOUGHTS_PROJECT_NAME,
            description: "thought dump",
          });
        }
        setProjectId(proj.id);
        const entries = await invoke<ProjectEntry[]>("get_project_entries", {
          projectId: proj.id,
        });
        setThoughts(entries);
      } catch (e) {
        setError(String(e));
      }
    }
    init();
  }, []);

  useEffect(() => {
    if (projectId) textareaRef.current?.focus();
  }, [projectId]);

  useEffect(() => {
    const focus = () => textareaRef.current?.focus();
    window.addEventListener("focus", focus);
    return () => window.removeEventListener("focus", focus);
  }, []);

  useEffect(() => {
    function handleGlobalKey(e: KeyboardEvent) {
      if (e.metaKey || e.ctrlKey || e.altKey || e.key.length > 1) return;
      const ta = textareaRef.current;
      if (!ta) return;
      if (document.activeElement === ta || document.activeElement === searchRef.current) return;
      ta.focus();
    }
    document.addEventListener("keydown", handleGlobalKey);
    return () => document.removeEventListener("keydown", handleGlobalKey);
  }, []);

  const handleSearchChange = useCallback(
    (q: string) => {
      setSearchQuery(q);
      if (searchTimeout.current) clearTimeout(searchTimeout.current);
      if (!q.trim()) {
        setSearchResults(null);
        setSearching(false);
        return;
      }
      setSearching(true);
      searchTimeout.current = setTimeout(async () => {
        if (!projectId) return;
        try {
          const results = await invoke<ProjectEntry[]>("search_project_entries", {
            projectId,
            query: q.trim(),
            limit: 20,
          });
          setSearchResults(results);
        } catch {
          setSearchResults([]);
        } finally {
          setSearching(false);
        }
      }, 400);
    },
    [projectId],
  );

  function clearSearch() {
    setSearchQuery("");
    setSearchResults(null);
    setSearching(false);
    textareaRef.current?.focus();
  }

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [thoughts]);

  const submit = useCallback(async () => {
    const content = input.trim();
    if (!content || !projectId || saving) return;
    setInput("");
    setSaving(true);
    setError(null);
    try {
      const entry = await invoke<ProjectEntry>("add_project_entry", {
        projectId,
        entryType: "thought",
        content,
        tags: null,
      });
      setThoughts((prev) => [...prev, entry]);
    } catch (e) {
      setError(String(e));
      setInput(content);
    } finally {
      setSaving(false);
      textareaRef.current?.focus();
    }
  }, [input, projectId, saving]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  const handleInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    const el = e.target;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  };

  const displayThoughts = searchResults !== null ? searchResults : thoughts;

  function scrambleText(text: string): string {
    const cipher = "xkqmvzbnjdwpgtshrfeiacylou";
    return text
      .split("")
      .map((ch) => {
        const lower = ch.toLowerCase();
        if (lower >= "a" && lower <= "z") {
          const idx = lower.charCodeAt(0) - 97;
          return ch === lower ? cipher[idx] : cipher[idx].toUpperCase();
        }
        if (ch >= "0" && ch <= "9") {
          return String((parseInt(ch) + 7) % 10);
        }
        return ch;
      })
      .join("");
  }

  return (
    <div className="flex flex-col h-full bg-surface text-sm select-text">
      {/* Search bar */}
      <div className="px-8 pt-4 pb-0">
        <div className="flex items-center justify-end mb-1">
          <button
            onClick={() => setPrivacyMode((p) => !p)}
            className={`text-[10px] transition-colors duration-150 cursor-pointer ${privacyMode ? "text-accent-DEFAULT" : "text-text-dim hover:text-text"}`}
            title={privacyMode ? "disable privacy mode" : "enable privacy mode"}
          >
            {privacyMode ? "// showing cipher" : "// hide"}
          </button>
        </div>
        <div className="relative">
          <input
            ref={searchRef}
            type="text"
            value={searchQuery}
            onChange={(e) => handleSearchChange(e.target.value)}
            placeholder="// search thoughts…"
            style={{ filter: privacyMode ? "blur(5px)" : undefined }}
            className="w-full bg-surface-1 border border-surface-2 rounded px-3 py-2 text-sm text-text placeholder:text-text-dim focus:outline-none focus:border-accent-DEFAULT"
          />
          {searching && (
            <span className="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] text-text-dim animate-pulse">
              searching…
            </span>
          )}
          {searchResults !== null && !searching && (
            <button
              onClick={clearSearch}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-text-dim hover:text-text text-xs"
            >
              ✕
            </button>
          )}
        </div>
        {searchResults !== null && (
          <div className="text-[10px] text-text-dim mt-1 opacity-60">
            {searchResults.length} result{searchResults.length !== 1 ? "s" : ""} for "{searchQuery}"
          </div>
        )}
      </div>

      {/* Feed */}
      <div className="flex-1 overflow-y-auto px-8 pt-4 pb-2">
        {!projectId && !error && (
          <span className="text-text-dim text-xs animate-pulse">initializing...</span>
        )}
        {displayThoughts.length === 0 && projectId && searchResults === null && (
          <div className="text-text-dim text-xs opacity-40">// begin</div>
        )}
        {displayThoughts.length === 0 && searchResults !== null && (
          <div className="text-text-dim text-xs opacity-40">// no matching thoughts</div>
        )}
        <div className="space-y-5">
          {displayThoughts.map((t) => (
            <div key={t.id}>
              <div className="text-[10px] text-text-dim mb-1">{formatTime(t.created_at)}</div>
              <div className="text-text whitespace-pre-wrap leading-relaxed">
                {privacyMode ? scrambleText(t.content) : t.content}
              </div>
            </div>
          ))}
        </div>
        {saving && (
          <div className="mt-5 text-text-dim text-xs opacity-40 animate-pulse">embedding...</div>
        )}
        <div ref={bottomRef} className="h-4" />
      </div>

      {error && (
        <div className="mx-8 mb-2 text-xs text-urgency-high opacity-80 truncate">{error}</div>
      )}

      {/* Input */}
      <div className="border-t border-surface-2 px-8 py-4">
        <textarea
          ref={textareaRef}
          value={input}
          onChange={handleInput}
          onKeyDown={handleKeyDown}
          disabled={!projectId || saving}
          placeholder="// type into the abyss"
          rows={1}
          style={{ resize: "none", overflow: "hidden", filter: privacyMode ? "blur(5px)" : undefined }}
          className="w-full bg-transparent text-text placeholder:text-text-dim focus:outline-none leading-relaxed disabled:opacity-30"
        />
        <div className="text-[10px] text-text-dim opacity-30 mt-1">
          enter to save · shift+enter for newline
        </div>
      </div>
    </div>
  );
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
    });
  } catch {
    return iso;
  }
}
