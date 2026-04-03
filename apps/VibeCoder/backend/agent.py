"""VibeCoder agent — CADEN-integrated coding assistant.

Three-stage LLM pipeline:
  1. Orchestrator  — routes user input (chat / clarify / task)
  2. Planner       — decomposes task into numbered steps
  3. Coder loop    — executes plan with tools (max 20 rounds)

CADEN enhancements over standalone CodingCLI:
  - Lessons retrieval: vector search for past mistakes/successes before each task
  - Lesson recording: structured JSON form after each task completion
  - Distillation: every model response logged for QLoRA fine-tuning
  - CADEN bridge: access to projects, thoughts, and knowledge base
"""

import json
import os
import re
import sys
from model import coder_chat, orchestrator_chat, planner_chat, critic_chat, researcher_chat, classify_coder_output, get_active_model
from distill import log_distillation_multiturn
from tools import TOOL_REGISTRY
from memory import record_episode_with_lessons, retrieve_similar, format_few_shot
from bandit import select_variant, update_bandit
from validator import validate_edit, analyse_file
from caden_bridge import (
    retrieve_lessons, format_lessons_context,
    cache_research, lookup_research, get_stale_entries, format_research_context,
)

# --- Working Memory ---
working_memory = {
    "chat_history": [],
    "files_in_scope": [],
    "current_task": None,
    "current_plan": None,
    "caden_plugin_context": None,
    "trust_mode": True,  # auto-approve edits; only confirm destructive ops
}

# --- Session-defined skills ---
SKILLS = {}


def skill_create():
    print("[Skill] Interactive skill creation:")
    name = input("Skill name (snake_case): ").strip()
    if not name:
        print("[Skill] Aborted.")
        return
    if name in SKILLS:
        print(f"[Skill] '{name}' already exists.")
        return
    desc = input("Short description: ").strip()
    steps = []
    print("Workflow steps (blank to finish):")
    while True:
        step = input(f"  Step {len(steps)+1}: ").strip()
        if not step:
            break
        steps.append(step)

    def new_skill(*args, **kwargs):
        print(f"[Skill: {name}] {desc}")
        for i, s in enumerate(steps, 1):
            print(f"  {i}. {s}")
    SKILLS[name] = new_skill
    print(f"[Skill] Registered: {name}")


def skill_list():
    disk_skills = list(_load_skills().keys())
    session_skills = list(SKILLS.keys())
    if not disk_skills and not session_skills:
        print("[Skill] No skills found.")
        return
    if disk_skills:
        print("[Skills] Loaded from disk:")
        for name in disk_skills:
            summary = _load_skills()[name].get("summary", "")
            print(f"  - {name}: {summary}")
    if session_skills:
        print("[Skills] Session-defined:")
        for name in session_skills:
            print(f"  - {name}")


def skill_invoke(name, *args, **kwargs):
    if name in SKILLS:
        return SKILLS[name](*args, **kwargs)
    print(f"[Skill] '{name}' not found. Use /list-skills to see available skills.")


# ============================================================
# TOOL DEFINITIONS
# ============================================================

TOOL_DEFS = """TOOLS — respond with ONLY a JSON tool call, nothing else:

{"tool": "list_files", "args": {"path": "."}}
  List files in a directory.

{"tool": "read_file", "args": {"path": "filename.py"}}
  Read a file. Always do this before edit_file.

{"tool": "read_file_range", "args": {"path": "filename.py", "start_line": 50, "end_line": 100}}
  Read specific line range (1-indexed). Ideal for focused reading in large files.

{"tool": "read_symbol", "args": {"path": "filename.py", "name": "function_or_class"}}
  Read a specific function, class, or method by name. Ideal for large files.

{"tool": "edit_file", "args": {"path": "f.py", "old_text": "exact text", "new_text": "replacement"}}
  Edit a file by replacing old_text with new_text. old_text must be verbatim.

{"tool": "replace_body", "args": {"path": "f.py", "name": "function_name", "new_body": "def function_name(...):\\n    ..."}}
  Replace an entire function/class by name — framework locates it via AST.
  More reliable than edit_file for large functions. Include the full def line.

{"tool": "apply_patch", "args": {"path": "f.py", "patch": "@@ -N,M +N,M @@\\n-old\\n+new"}}
  Apply a unified diff patch. Use for multi-section changes instead of multiple edit_file calls.

{"tool": "write_file", "args": {"path": "f.py", "content": "full file content"}}
  Write or create a file with the given content.

{"tool": "search_code", "args": {"query": "def my_func", "path": "."}}
  Search for text patterns across files.

{"tool": "search_symbols", "args": {"query": "function_name"}}
  Find functions, classes, and types by name across the entire codebase.

{"tool": "find_refs", "args": {"name": "function_name"}}
  Find all references to a symbol across the codebase — every file and line where it appears.

{"tool": "show_dependents", "args": {"path": "model.py"}}
  Show all files that import this file (up to 2 hops). Use before editing to know impact.

{"tool": "show_dependencies", "args": {"path": "agent.py"}}
  Show all files this file imports (up to 2 hops).

{"tool": "run_cmd", "args": {"cmd": "python script.py"}}
  Run a shell command (non-interactive, output captured).

{"tool": "run_interactive", "args": {"cmd": "python main.py"}}
  Open in a NEW terminal window for user interaction.

{"tool": "web_search", "args": {"query": "react useEffect cleanup docs", "max_results": 5}}
  Search the web via DuckDuckGo. Use for finding documentation, API references, known
  issues, changelogs, or verifying that a solution matches current official guidance.

{"tool": "fetch_url", "args": {"url": "https://example.com/docs", "max_chars": 8000}}
  Fetch and extract readable text from a web page. Use after web_search to read the
  actual docs page, GitHub issue, or Stack Overflow answer in full."""


# ============================================================
# PROMPTS
# ============================================================

ORCHESTRATOR_PROMPT = """You are the entry point for a coding assistant. Your ONLY job is to classify
the user's message and decide how to proceed. Respond with ONLY a JSON object.

Choices:

  Chat / small talk / greetings (say something natural):
  {{"route": "chat", "message": "<your natural reply>"}}

  Ambiguous request (you genuinely cannot tell what they want without more info):
  {{"route": "clarify", "question": "<single focused question>"}}

  Clear actionable request (anything involving code, files, explanations, running commands,
  editing, creating, debugging, reading, searching, planning, or any other real task):
  {{"route": "task", "task": "<restate the request concisely in your own words>",
    "complexity": "simple" or "complex"}}

Use "complex" when the request involves:
- Refactoring or redesigning multiple components
- Why something is broken / root-cause analysis
- Multi-file changes or cross-cutting concerns
- Implementing a significant new feature
- Architecture or design decisions

Use "simple" for everything else (single file reads, small edits, questions, short tasks).

Be decisive. Default to "task" when unsure. NEVER output anything except the JSON object.

Current directory files:
{file_tree}"""


PLANNER_PROMPT = """You are a planning assistant for a coding agent. Your job is to produce
a clear, concise, numbered plan for the task below.

Rules:
- Each step must be one concrete action (read a file, search for X, edit Y, run Z).
- Keep the plan as short as possible while covering the full task.
- For simple tasks: 1-3 steps. For complex tasks: up to 8 steps.
- DO NOT write code. DO NOT call tools. Output ONLY the numbered plan followed by one
  blank line, then a line: "Files: <comma-separated list of files likely needed, or 'unknown'>".
- Be specific: name files, functions, or patterns where known from context.

Working directory: {cwd}
{file_tree}
{context_block}
Task: {task}"""


CODER_PROMPT = """You are an expert coding assistant — autonomous, precise, and direct. You work live inside the user's codebase.

{tool_defs}

Working directory: {cwd}
{file_tree}
{context_block}
{lessons_block}
── HOW TO WORK ──────────────────────────────────────────────
Think step by step. Read before acting. Be concise in final answers.

Editing files:
  - Always read_file before edit_file — the framework enforces this and will
    force a read automatically if you skip it, so do it yourself first.
  - old_text must be copied CHARACTER-FOR-CHARACTER from the file. One missed
    space will break it. Copy verbatim.
  - For changes across multiple hunks, prefer apply_patch over multiple
    edit_file calls — it's atomic and cleaner.
  - After an edit the framework auto-verifies and shows you the result.
    Confirm it's correct, or fix it. Don't say "done" until it's verified.

Navigating large codebases:
  - For large files (500+ lines), read_file shows a structural schema + head/tail.
    Use read_symbol to jump directly to a specific function or class by name.
  - Use read_file_range to read specific line ranges when you know the location.
  - Use search_symbols to find where a function, class, or type is defined
    across the entire codebase — faster than search_code for symbol lookups.
  - Use find_refs to see every file/line that references a given symbol —
    essential before renaming or changing a function's signature.
  - Use show_dependents before editing a file to see what else imports it
    (those files might need changes too).
  - Use show_dependencies to understand a file's imports and structure.
  - The file tree may list relevant indexed files when applicable.
  - The framework pre-loads smart context based on dependency analysis.
    Check the "Pre-loaded file context" block — it may already contain
    the files you need.

Editing strategies for reliability:
  - For replacing an entire function: prefer replace_body over edit_file.
    replace_body uses AST to find the exact function boundaries — no text
    matching needed. Include the full def/class line in new_body.
  - For small, precise changes: use edit_file with old_text copied verbatim.
  - For multi-hunk changes: use apply_patch — it's atomic and cleaner.
  - After any edit, use find_refs to check if callers need updating.

Answering questions / explaining code:
  - If the file tree or pre-loaded context already answers it, reply immediately.
  - Otherwise read the relevant file(s) first, then answer.
  - Use search_code to find things across the codebase.

Researching and verifying solutions with documentation:
  - When implementing an API, library, or framework feature you are not 100% certain
    about, use web_search to find the official docs first.
  - Use web_search + fetch_url when:
      * Installing or configuring a dependency (check current version / install flags)
      * Using a third-party API (endpoint format, auth, parameters may have changed)
      * Diagnosing an error message (search the exact error + library name)
      * Choosing between approaches (search for known gotchas or deprecations)
      * The CADEN plugin context mentions a convention you want to verify
  - After fetching a doc page, check for conflicts with what you planned to write:
      * Deprecated APIs or renamed functions
      * Changed default behaviour between versions
      * Required config that the docs list but you omitted
  - Prefer official sources: docs.python.org, react.dev, vitejs.dev, npmjs.com,
    pkg.go.dev, the library's own GitHub README / CHANGELOG.
  - If docs conflict with your plan, update the plan before writing any code.
  - Do not fetch random blogs or forums as primary sources — use them only to
    identify what official doc page to read next.

Documentation awareness:
  - After making changes, check if README or other docs reference the modified
    files. If they do, update them to stay in sync.

Running commands:
  - run_cmd for non-interactive commands. Report and interpret the output.
  - run_interactive to open something in a new terminal window.

LEARNING FROM EXPERIENCE:
  - Check the "Lessons from past tasks" block above — avoid listed mistakes.
  - Use approaches that worked well in similar past tasks.
  - If you discover something new (API quirk, config gotcha), note it.

{plan_block}
──────────────────────────────────────────────────────────────

LAWS — the framework enforces these at runtime, you cannot bypass them:
1. Each response is ONE JSON tool call OR plain-text — never both.
2. Never call edit_file or apply_patch without a prior read_file this session.
3. Never write or edit files unless the user explicitly asked for a change.
   — Any request to "fix", "create", "add", "update", "build", or "resolve" something
     IS explicit permission. Do not ask again — just do it.
4. old_text in edit_file must be verbatim — every space, tab, and newline.
5. Be concise. Skip preambles. Skip "I have completed" summaries. Just deliver.
6. NEVER describe a code fix in prose and stop. If something needs to be written
   or changed, call write_file / edit_file / apply_patch to actually do it.
   Showing a code block in a text reply is NOT making the change. The user does
   not want instructions — they want the file updated."""


# ============================================================
# SKILL LOADING
# ============================================================

_skills_cache = None


def _load_skills():
    global _skills_cache
    if _skills_cache is not None:
        return _skills_cache
    skills = {}
    skills_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".github", "skills")
    if not os.path.isdir(skills_dir):
        _skills_cache = {}
        return skills
    for entry in os.listdir(skills_dir):
        skill_md = os.path.join(skills_dir, entry, "SKILL.md")
        if not os.path.isfile(skill_md):
            continue
        try:
            with open(skill_md, encoding="utf-8") as f:
                content = f.read()
            summary = ""
            m = re.search(r'summary:\s*>\s*\n\s+(.+)', content)
            if m:
                summary = m.group(1).strip()
            skills[entry] = {"content": content, "summary": summary}
        except Exception:
            pass
    _skills_cache = skills
    return skills


def _get_skill_content(name):
    return _load_skills().get(name, {}).get("content", "")


# ============================================================
# FILE TREE
# ============================================================

def _get_file_tree(path=".", max_depth=4, max_entries=120):
    entries = []
    skip_dirs = {'.git', '__pycache__', 'node_modules', '.venv', 'venv',
                 'dist', 'build', '.pytest_cache', '.mypy_cache', '.github'}

    def _walk(current, prefix, depth):
        if depth > max_depth or len(entries) >= max_entries:
            return
        try:
            items = sorted(os.listdir(current))
        except PermissionError:
            return
        dirs = [i for i in items if os.path.isdir(os.path.join(current, i))
                and i not in skip_dirs and not i.startswith('.')]
        files = [i for i in items if os.path.isfile(os.path.join(current, i))]
        for f in files:
            if len(entries) >= max_entries:
                entries.append(f"{prefix}... (truncated)")
                return
            entries.append(f"{prefix}{f}")
        for d in dirs:
            if len(entries) >= max_entries:
                entries.append(f"{prefix}... (truncated)")
                return
            entries.append(f"{prefix}{d}/")
            _walk(os.path.join(current, d), prefix + "  ", depth + 1)

    _walk(path, "  ", 0)
    if not entries:
        return "Files:\n  (empty directory)"
    return "Files:\n" + "\n".join(entries)


# ============================================================
# AUTO CONTEXT (graph-powered smart context)
# ============================================================

# Cached import graph — rebuilt once per agent_converse() call
_import_graph = None


def _build_graph(workspace):
    """Build (or return cached) import graph for the workspace."""
    global _import_graph
    try:
        from graph import ImportGraph
        _import_graph = ImportGraph(workspace).build()
    except Exception:
        _import_graph = None
    return _import_graph


def _auto_read_context(user_input, cwd):
    """Graph-powered smart context selection.

    Deterministic pipeline (no LLM):
      1. Extract file mentions from user input (regex)
      2. Walk the import graph to find neighbors of mentioned files
      3. Extract code identifiers from the task and find files containing them
      4. Build focused excerpts (AST-guided for Python, schema+head for others)
      5. Budget: max 10000 chars total, prioritized by relevance
    """
    from tools import get_workspace
    workspace = get_workspace()

    # ── Phase 1: Detect mentioned files ──────────────────────────────────────
    file_pattern = re.compile(
        r'[\w./\\-]+\.(?:py|js|ts|jsx|tsx|java|c|cpp|h|go|rs|rb|md|txt|json|yaml|yml|toml|html|css|sh|bat)\b'
    )
    mentioned = file_pattern.findall(user_input)
    for word in user_input.split():
        clean = word.strip('.,!?:;"\'()[]{}')
        if clean and not clean.startswith('/') and os.path.isfile(os.path.join(cwd, clean)):
            mentioned.append(clean)

    # Resolve to absolute paths, sandbox to workspace
    mentioned_abs = []
    seen = set()
    for fname in mentioned:
        fpath = os.path.join(cwd, fname) if not os.path.isabs(fname) else fname
        resolved = os.path.realpath(fpath)
        if workspace and not (resolved == workspace or resolved.startswith(workspace + os.sep)):
            continue
        if resolved not in seen and os.path.isfile(resolved):
            seen.add(resolved)
            mentioned_abs.append(resolved)

    # ── Phase 2: Graph-powered context selection ─────────────────────────────
    if _import_graph and mentioned_abs:
        try:
            from graph import select_context
            ctx_items = select_context(
                user_input, mentioned_abs, _import_graph,
                workspace or cwd, max_files=10, max_chars=10000
            )
            if ctx_items:
                parts = []
                for item in ctx_items:
                    parts.append(f"[{item['rel_path']}]\n{item['excerpt']}")
                return "\n\n".join(parts)
        except Exception:
            pass

    # ── Phase 3: Fallback — direct file reading (original logic) ─────────────
    context_parts = []
    total_chars = 0
    max_context_chars = 8000
    for fpath in mentioned_abs:
        if total_chars >= max_context_chars:
            break
        try:
            # Skip binary files
            with open(fpath, 'rb') as fb:
                chunk = fb.read(512)
            if b'\x00' in chunk:
                continue
            with open(fpath, encoding="utf-8", errors="replace") as f:
                content = f.read()
            if total_chars + len(content) > max_context_chars:
                remaining = max_context_chars - total_chars
                if remaining > 200:
                    lines = content.splitlines()[:50]
                    content = "\n".join(lines) + "\n... (truncated)"
                else:
                    continue
            numbered = "\n".join(
                f"{i+1:4d} | {line}" for i, line in enumerate(content.splitlines())
            )
            rel = os.path.relpath(fpath, cwd)
            context_parts.append(f"[{rel}]\n{numbered}")
            total_chars += len(content)
        except Exception:
            continue
    return "\n\n".join(context_parts)


# ============================================================
# JSON EXTRACTION
# ============================================================

def _extract_json(text):
    text = text.strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass
    m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except (json.JSONDecodeError, ValueError):
            pass
    start = text.find('{')
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        c = text[i]
        if escape:
            escape = False
            continue
        if c == '\\' and in_string:
            escape = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i+1])
                except (json.JSONDecodeError, ValueError):
                    pass
                break
    return None


def _extract_tool_call(text):
    obj = _extract_json(text)
    if obj and isinstance(obj, dict):
        # Native VibeCoder format: {"tool": ..., "args": ...}
        if "tool" in obj or "call" in obj:
            return _normalize_call(obj)
        # OpenAI function-call format: {"type":"function","name":...,"parameters":{...}}
        if obj.get("type") == "function" and "name" in obj:
            normalized = {
                "tool": obj["name"],
                "args": obj.get("parameters") or obj.get("arguments") or {},
            }
            return _normalize_call(normalized)
    cleaned = re.sub(r',\s*([}\]])', r'\1', text)
    if "'" in cleaned and '"tool"' not in cleaned:
        cleaned = cleaned.replace("'", '"')
    obj = _extract_json(cleaned)
    if obj and isinstance(obj, dict):
        if "tool" in obj or "call" in obj:
            return _normalize_call(obj)
        if obj.get("type") == "function" and "name" in obj:
            normalized = {
                "tool": obj["name"],
                "args": obj.get("parameters") or obj.get("arguments") or {},
            }
            return _normalize_call(normalized)
    return None


def _normalize_call(obj):
    if "call" in obj and "tool" not in obj:
        obj["tool"] = obj.pop("call")
    if "args" not in obj:
        obj["args"] = {}
    args = obj["args"]
    if "file_path" in args and "path" not in args:
        args["path"] = args.pop("file_path")
    if "filename" in args and "path" not in args:
        args["path"] = args.pop("filename")
    if "command" in args and "cmd" not in args:
        args["cmd"] = args.pop("command")
    if "search" in args and "query" not in args:
        args["query"] = args.pop("search")
    return obj


# ============================================================
# TOOL EXECUTION
# ============================================================

def _execute_tool(tool_name, tool_args):
    name = tool_name.lower().strip()
    alias_map = {
        "list": "list_files", "ls": "list_files", "dir": "list_files",
        "read": "read_file", "cat": "read_file",
        "read_range": "read_file_range", "range": "read_file_range",
        "read_sym": "read_symbol", "symbol": "read_symbol",
        "replace": "replace_body", "replace_fn": "replace_body",
        "edit": "edit_file", "modify": "edit_file",
        "write": "write_file", "create": "write_file",
        "search": "search_code", "grep": "search_code", "find": "search_code",
        "symbols": "search_symbols", "find_symbol": "search_symbols",
        "refs": "find_refs", "references": "find_refs", "find_references": "find_refs",
        "dependents": "show_dependents", "importers": "show_dependents",
        "dependencies": "show_dependencies", "imports": "show_dependencies",
        "run": "run_cmd", "exec": "run_cmd", "shell": "run_cmd",
        "interactive": "run_interactive", "launch": "run_interactive",
        "test": "run_tests", "tests": "run_tests",
    }
    resolved = alias_map.get(name, name)
    if resolved in TOOL_REGISTRY:
        fn = TOOL_REGISTRY[resolved]["fn"]
        try:
            result = fn(**tool_args)
            return str(result)
        except TypeError as e:
            return f"Error: wrong arguments for {resolved}: {e}"
        except Exception as e:
            return f"Error running {resolved}: {e}"
    return f"Unknown tool: {tool_name}. Available: {', '.join(TOOL_REGISTRY.keys())}"


# ============================================================
# CONTEXT MANAGEMENT
# ============================================================

def _compact_history(history, max_chars=12000):
    if not history:
        return history
    total = sum(len(str(m.get("content", ""))) for m in history)
    if total <= max_chars:
        return history
    kept_end = []
    running = 0
    for m in reversed(history):
        c = len(str(m.get("content", "")))
        if running + c > max_chars * 0.8:
            break
        kept_end.insert(0, m)
        running += c
    if len(kept_end) < len(history):
        dropped = len(history) - len(kept_end) - 1
        compacted = [history[0]]
        if dropped > 0:
            compacted.append({
                "role": "system",
                "content": f"[{dropped} earlier messages compacted]"
            })
        compacted.extend(kept_end)
        return compacted
    return history


def _context_gate(messages, max_chars=60000):
    total = sum(len(str(m.get("content", ""))) for m in messages)
    if total <= max_chars:
        return messages

    system = messages[0]
    rest = list(messages[1:])
    budget = max_chars - len(str(system.get("content", "")))
    kept = []
    running = 0
    for m in reversed(rest):
        c = len(str(m.get("content", "")))
        if running + c > budget:
            if not kept:
                m = dict(m)
                m["content"] = str(m["content"])[:2000] + "\n... (truncated for context budget)"
                kept.insert(0, m)
                running += 2000
            break
        kept.insert(0, m)
        running += c

    dropped = len(rest) - len(kept)
    result = [system]
    if dropped > 0:
        result.append({"role": "system", "content": f"[{dropped} earlier messages dropped — context budget]"})
    result.extend(kept)
    return result


# ============================================================
# COMPLEXITY HEURISTIC
# ============================================================

_COMPLEX_PATTERNS = re.compile(
    r"""
    \b(
      refactor | restructure | rewrite | redesign | migrate | overhaul
    | implement(?:\s+a|\s+the|\s+an)?
    | build(?:\s+a|\s+the|\s+an)?
    | add\s+(?:a\s+)?(?:new\s+)?(?:feature|system|module|support\s+for)
    | across\s+(?:all|every|multiple)
    | all\s+files | every\s+file | all\s+the\s+files
    | multi[- ]file
    | why\s+(?:is|does|isn'?t|doesn'?t|won'?t|are|aren'?t)
    | not\s+working | isn'?t\s+working | doesn'?t\s+work
    | broken | crash(?:ing|es)? | exception | traceback | stack\s+trace
    | debug(?:\s+this|\s+the|\s+why)?
    | deep\s+dive | walk\s+me\s+through
    | architecture | design\s+pattern
    | step[- ]by[- ]step
    | test\s+suite | unit\s+tests | integration\s+test
    | performance | benchmark | profile
    | security\s+audit | vulnerability | cve
    )""",
    re.VERBOSE | re.IGNORECASE,
)


def _is_complex(text):
    if len(text) > 180:
        return True
    if len(re.split(r'[.!?]+', text.strip())) - 1 >= 3:
        return True
    if bool(_COMPLEX_PATTERNS.search(text)):
        return True
    file_refs = re.findall(
        r'[\w./\\-]+\.(?:py|js|ts|jsx|tsx|java|c|cpp|h|go|rs|rb|md|json|yaml|yml|toml|html|css|sh|bat)\b',
        text,
    )
    return len(set(file_refs)) >= 3


# ============================================================
# CODER TOOL LOOP
# ============================================================

def _run_coder_loop(task, auto_context, file_tree, cwd, thinking, console,
                    history=None, plan_block=None,
                    bandit_category=None, bandit_variant_id=None, bandit_hint="",
                    max_rounds=20):
    # ── Build context block ───────────────────────────────────────────────────
    context_block = ""
    if auto_context:
        context_block = f"\nPre-loaded file context:\n{auto_context}\n"

    # ── Episodic memory retrieval ──────────────────────────────────────────────
    similar = retrieve_similar(task)
    few_shot_block = format_few_shot(similar)
    if few_shot_block and console:
        console.print(f"[dim]  ◈ {len(similar)} similar episode(s) recalled[/dim]")

    # ── Lessons retrieval (CADEN learning) ─────────────────────────────────────
    lessons = retrieve_lessons(task)
    lessons_block = format_lessons_context(lessons)
    if lessons and console:
        n_mistakes = sum(len(l.get("mistakes", [])) for l in lessons)
        n_wins = sum(len(l.get("what_worked", [])) for l in lessons)
        console.print(f"[dim]  ◈ {len(lessons)} lesson(s) recalled ({n_mistakes} avoid, {n_wins} inspire)[/dim]")

    # ── Build system prompt ───────────────────────────────────────────────────
    system = CODER_PROMPT.format(
        tool_defs=TOOL_DEFS,
        cwd=cwd,
        file_tree=file_tree,
        context_block=context_block,
        lessons_block=lessons_block,
        plan_block=plan_block or "",
    )
    prefix_parts = []
    if bandit_hint:
        prefix_parts.append(bandit_hint)
    if few_shot_block:
        prefix_parts.append(few_shot_block)
    # Inject CADEN plugin development context when building CADEN apps
    caden_ctx = working_memory.get("caden_plugin_context")
    if caden_ctx:
        prefix_parts.append(
            "## CADEN Plugin Development Reference\n"
            "You are building an app for CADEN. Follow these conventions exactly:\n\n"
            + caden_ctx
        )
    if prefix_parts:
        system = "\n\n".join(prefix_parts) + "\n\n" + system

    # ── Inject conversation history ───────────────────────────────────────────
    prior_turns = _compact_history(history or [], max_chars=6000)
    messages = [
        {"role": "system", "content": system},
        *prior_turns,
        {"role": "user", "content": task},
    ]
    recent_calls = []
    files_read = set()
    file_snapshots: dict = {}
    tool_sequence = []
    final_answer = "(no response)"
    outcome = "failure"

    truncation_retries = 0

    for _ in range(max_rounds):
        gated = _context_gate(messages)
        if console:
            console.print("[dim]  ...[/dim]", end="\r")
        response = coder_chat(gated, thinking=thinking)
        raw = response.get("content", "").strip()
        finish_reason = response.get("finish_reason", "stop")
        if console:
            sys.stdout.write("\r" + " " * 40 + "\r")

        if not raw:
            break
        if raw.startswith("[LLM Error:"):
            if console:
                console.print(f"[bold red]{raw}[/bold red]")
            final_answer = raw
            break

        tool_call = _extract_tool_call(raw)

        if not tool_call:
            # Detect truncated responses: finish_reason=="length" or
            # suspiciously short text (< 30 chars, no sentence-ending punct)
            looks_truncated = (
                finish_reason == "length"
                or (len(raw) < 30 and not raw.rstrip().endswith((".", "!", "?", ":", "```")))
            )
            if looks_truncated and truncation_retries < 2:
                truncation_retries += 1
                if console:
                    console.print(f"[dim]  ⚠ response truncated ({len(raw)} chars) — retrying...[/dim]")
                messages.append({"role": "assistant", "content": raw})
                messages.append({"role": "user", "content": "Your response was truncated. Please provide the complete answer."})
                continue

            if console:
                console.print(f"[bold yellow]Agent:[/bold yellow] {raw}")
            final_answer = raw
            outcome = "success"
            break

        tool_name = tool_call["tool"]
        tool_args = tool_call.get("args", {})
        resolved = tool_name.lower().strip()

        # ── Read-guard ─────────────────────────────────────────────────────────
        if resolved in ("edit_file", "edit", "apply_patch", "replace_body", "replace", "replace_fn"):
            edit_path = tool_args.get("path", "")
            norm_path = os.path.normpath(os.path.join(cwd, edit_path)) if edit_path else ""
            if norm_path and norm_path not in files_read:
                if console:
                    console.print(f"[dim]  ⚠ read-guard: must read '{edit_path}' before editing[/dim]")
                read_result = TOOL_REGISTRY["read_file"]["fn"](edit_path)
                files_read.add(norm_path)
                if norm_path not in file_snapshots and os.path.isfile(norm_path):
                    file_snapshots[norm_path] = open(norm_path, encoding="utf-8", errors="replace").read()
                schema = analyse_file(norm_path)
                augmented = (schema + "\n\n" + read_result) if schema else read_result
                messages.append({"role": "assistant", "content": raw})
                messages.append({
                    "role": "user",
                    "content": (
                        f"[Read-guard] You must read a file before editing it. "
                        f"Here is the current content of '{edit_path}':\n\n{augmented}\n\n"
                        "Now retry your edit with old_text copied verbatim from the content above."
                    ),
                })
                continue

        # ── Track reads ────────────────────────────────────────────────────────
        if resolved in ("read_file", "read", "cat"):
            read_path = tool_args.get("path", "")
            if read_path:
                norm = os.path.normpath(os.path.join(cwd, read_path))
                files_read.add(norm)
                if norm not in file_snapshots and os.path.isfile(norm):
                    file_snapshots[norm] = open(norm, encoding="utf-8", errors="replace").read()

        # ── Loop detection ─────────────────────────────────────────────────────
        call_sig = (tool_name, json.dumps(tool_args, sort_keys=True)[:120])
        recent_calls.append(call_sig)
        if len(recent_calls) > 6:
            recent_calls.pop(0)
        if recent_calls.count(call_sig) >= 3:
            if console:
                console.print("[dim]  (repeated call — stopping)[/dim]")
            break

        # ── Confirmation ───────────────────────────────────────────────────────
        if resolved in ("edit_file", "edit", "apply_patch", "write_file", "write", "create",
                        "replace_body", "replace", "replace_fn"):
            if not _confirm_edit(tool_name, tool_args, console):
                messages.append({"role": "assistant", "content": raw})
                messages.append({"role": "user", "content": "User declined this edit. The file was NOT changed."})
                continue

        if resolved in ("run_cmd", "run", "exec", "shell"):
            if not _confirm_run(tool_args, console):
                messages.append({"role": "assistant", "content": raw})
                messages.append({"role": "user", "content": "User declined the command."})
                continue

        # ── Show activity / server hooks ────────────────────────────────────
        prose = _extract_prose_before_json(raw)
        if prose and console:
            console.print(f"[dim]  {prose}[/dim]")
        if console and hasattr(console, 'on_tool_call'):
            console.on_tool_call(tool_name, tool_args)
        if console:
            console.print(f"[dim]  ▸ {tool_name}({_summarize_args(tool_args)})[/dim]")

        # Snapshot before edit
        _pre_edit_snapshot = None
        if resolved in ("edit_file", "edit", "apply_patch", "replace_body", "replace", "replace_fn"):
            _ep = tool_args.get("path", "")
            if _ep:
                _abs_ep = os.path.normpath(os.path.join(cwd, _ep))
                if os.path.isfile(_abs_ep):
                    _pre_edit_snapshot = open(_abs_ep, encoding="utf-8", errors="replace").read()

        result = _execute_tool(tool_name, tool_args)

        # ── Augment read results ───────────────────────────────────────────────
        if resolved in ("read_file", "read", "cat") and not result.startswith("Error"):
            read_path = tool_args.get("path", "")
            norm = os.path.normpath(os.path.join(cwd, read_path)) if read_path else ""
            if norm:
                if norm not in file_snapshots:
                    raw_content = open(norm, encoding="utf-8", errors="replace").read() if os.path.isfile(norm) else ""
                    file_snapshots[norm] = raw_content
                    schema = analyse_file(norm)
                    if schema:
                        result = schema + "\n\n" + result
                else:
                    try:
                        import difflib
                        old_lines = file_snapshots[norm].splitlines(keepends=True)
                        new_content = open(norm, encoding="utf-8", errors="replace").read()
                        new_lines = new_content.splitlines(keepends=True)
                        diff = list(difflib.unified_diff(old_lines, new_lines,
                            fromfile=f"{read_path} (before)", tofile=f"{read_path} (current)", n=3))
                        if diff:
                            diff_str = "".join(diff[:80])
                            result = f"[Diff from session start]:\n{diff_str}\n\n[Current content]:\n{result}"
                        file_snapshots[norm] = new_content
                    except Exception:
                        pass

        if console and hasattr(console, 'on_tool_result'):
            _st = 'err' if result.startswith('Error') else 'ok'
            console.on_tool_result(tool_name, result[:500], _st)
        if console:
            preview = result[:200] + "..." if len(result) > 200 else result
            console.print(f"[dim]  ◂ {preview}[/dim]")

        tool_sequence.append({
            "tool": tool_name,
            "args_summary": _summarize_args(tool_args),
        })

        messages.append({"role": "assistant", "content": raw})

        # ── Post-edit validation ───────────────────────────────────────────────
        result_msg = f"[Result]:\n{result}"
        _edit_tools = ("edit_file", "edit", "apply_patch", "replace_body", "replace", "replace_fn")
        if resolved in _edit_tools and not result.startswith("Error"):
            edit_path = tool_args.get("path", "")
            if edit_path:
                abs_edit = os.path.normpath(os.path.join(cwd, edit_path))
                valid, val_errors = validate_edit(abs_edit)
                verified = TOOL_REGISTRY["read_file"]["fn"](edit_path)
                files_read.add(abs_edit)

                if not valid:
                    snapshot = _pre_edit_snapshot
                    if snapshot is not None:
                        try:
                            open(abs_edit, "w", encoding="utf-8").write(snapshot)
                            restored_note = "File has been restored to its pre-edit state."
                        except Exception:
                            restored_note = "WARNING: could not restore file."
                    else:
                        restored_note = "No snapshot available."

                    error_block = "\n".join(f"  {e}" for e in val_errors)
                    result_msg = (
                        f"[Validation FAILED — edit rolled back]\n{restored_note}\n"
                        f"Errors:\n{error_block}\n\n"
                        f"[Pre-edit content]:\n{TOOL_REGISTRY['read_file']['fn'](edit_path)}\n\n"
                        "Fix these errors and retry."
                    )
                    if console:
                        console.print(f"[bold red]  ✗ validation failed — rolled back: {'; '.join(val_errors[:2])}[/bold red]")
                else:
                    if os.path.isfile(abs_edit):
                        file_snapshots[abs_edit] = open(abs_edit, encoding="utf-8", errors="replace").read()
                    result_msg = (
                        f"[Edit applied ✔] {result}\n\n"
                        f"[Current content]:\n{verified}\n\n"
                        "Confirm the change is correct."
                    )
                    if console:
                        console.print("[dim]  ✔ validation passed[/dim]")

        elif resolved in _edit_tools and result.startswith("Error"):
            edit_path = tool_args.get("path", "")
            fresh = TOOL_REGISTRY["read_file"]["fn"](edit_path) if edit_path else ""
            if fresh:
                norm = os.path.normpath(os.path.join(cwd, edit_path))
                files_read.add(norm)
            result_msg = (
                f"[Edit failed] {result}\n\n"
                + (f"Current file content:\n{fresh}\n\n" if fresh else "")
                + "Retry — copy old_text EXACTLY from the file above."
            )
        else:
            result_msg = f"[Result]:\n{result}"
            if resolved in ("write_file", "write", "create") and not result.startswith("Error"):
                write_path = tool_args.get("path", "")
                if write_path:
                    abs_write = os.path.normpath(os.path.join(cwd, write_path))
                    valid, val_errors = validate_edit(abs_write)
                    if not valid:
                        error_block = "\n".join(f"  {e}" for e in val_errors)
                        result_msg += f"\n\n[Validation FAILED]\n{error_block}\nFix and retry."
                        if console:
                            console.print(f"[bold red]  ✗ errors: {'; '.join(val_errors[:2])}[/bold red]")
                    else:
                        if console:
                            console.print("[dim]  ✔ validation passed[/dim]")
            read_tools = ("list_files", "list", "ls", "dir", "read_file", "read",
                          "cat", "search_code", "search", "grep", "find",
                          "read_symbol", "read_sym", "symbol",
                          "read_file_range", "read_range", "range",
                          "search_symbols", "symbols", "find_symbol",
                          "find_refs", "refs", "references", "find_references",
                          "show_dependents", "dependents", "importers",
                          "show_dependencies", "dependencies", "imports",
                          "web_search", "fetch_url")
            if resolved in read_tools:
                result_msg += "\n\nIf you now have enough information, respond in plain text."

        messages.append({"role": "user", "content": result_msg})

    # ── Record episode + lessons ───────────────────────────────────────────────
    if outcome == "failure" and tool_sequence and console:
        attempted = ", ".join(s["tool"] for s in tool_sequence[-4:])
        console.print(f"[bold yellow]Agent:[/bold yellow] I wasn't able to complete this. "
                      f"Last steps: {attempted}")

    if tool_sequence:
        try:
            record_episode_with_lessons(task, tool_sequence, outcome)
        except Exception:
            pass

    # ── Update bandit priors ───────────────────────────────────────────────────
    if bandit_category and bandit_variant_id:
        try:
            update_bandit(bandit_category, bandit_variant_id, outcome == "success")
        except Exception:
            pass

    # ── Log full coder chain for distillation ──────────────────────────────────
    # The 70B teacher's multi-turn chain is the most valuable training signal.
    # Each gpt turn is tagged with a sub-type so at export time we can train
    # specialized adapters (tool-picker, editor, answerer) from the same chain.
    if len(messages) > 2:  # at least system + user + one assistant turn
        sharegpt_chain = []
        for m in messages:
            role = m.get("role", "")
            content = m.get("content", "")
            if role == "system":
                sharegpt_chain.append({"from": "system", "value": content})
            elif role == "user":
                sharegpt_chain.append({"from": "human", "value": content})
            elif role == "assistant":
                sub = classify_coder_output(content)
                sharegpt_chain.append({"from": "gpt", "value": content, "sub_type": sub})
        try:
            log_distillation_multiturn("vibecoder_code_chain", sharegpt_chain, get_active_model())
        except Exception:
            pass

    # ── Detect edited files ────────────────────────────────────────────────────
    edited = []
    for p, initial in file_snapshots.items():
        if os.path.isfile(p):
            try:
                current = open(p, encoding="utf-8", errors="replace").read()
                if current != initial:
                    edited.append(p)
            except Exception:
                pass

    # ── Proactive review ───────────────────────────────────────────────────────
    if edited and console:
        try:
            from validator import review_file
            advisories = []
            for fp in edited:
                advisories.extend(review_file(fp))
            if advisories:
                if hasattr(console, 'on_advisory'):
                    console.on_advisory('review', advisories[:10])
                console.print("[dim]  ◈ Review advisories:[/dim]")
                for adv in advisories[:8]:
                    console.print(f"[dim]    {adv}[/dim]")
                if len(advisories) > 8:
                    console.print(f"[dim]    ... ({len(advisories) - 8} more)[/dim]")
        except Exception:
            pass

    return final_answer, edited, messages, tool_sequence


# ============================================================
# DISPLAY & CONFIRMATION HELPERS
# ============================================================

def _summarize_args(args):
    parts = []
    for k, v in args.items():
        s = str(v)
        if len(s) > 40:
            s = s[:37] + "..."
        parts.append(f'{k}="{s}"')
    return ", ".join(parts)


def _extract_prose_before_json(text):
    idx = text.find('{')
    if idx > 0:
        prose = text[:idx].strip()
        prose = re.sub(r'```(?:json)?\s*$', '', prose).strip()
        return prose if len(prose) > 3 else ""
    return ""


def _confirm_edit(tool_name, tool_args, console):
    # Server mode: delegate to callback (sends structured message to client)
    if console and hasattr(console, 'confirm_edit'):
        return console.confirm_edit(tool_args)

    # Trust mode: auto-approve surgical edits; confirm only full-file overwrites
    # of existing files (write_file/create to a file that already exists).
    if working_memory.get("trust_mode"):
        is_overwrite = (
            tool_name.lower().strip() in ("write_file", "write", "create")
            and os.path.isfile(os.path.join(os.getcwd(), tool_args.get("path", "")))
        )
        if not is_overwrite:
            path = tool_args.get("path", "?")
            if console:
                console.print(f"[dim]  \u2714 auto-approved: {tool_name}(path=\"{path}\")[/dim]")
            return True
        # Fall through to manual confirmation for overwrites

    if console:
        console.print("[bold cyan]\u256d\u2500 Proposed Change \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u256e[/bold cyan]")
        path = tool_args.get("path", "?")
        console.print(f"[bold cyan]\u2502[/bold cyan] File: [white]{path}[/white]")
        if "old_text" in tool_args:
            old_display = tool_args['old_text'].replace('\n', '\\n')
            new_display = tool_args['new_text'].replace('\n', '\\n')
            if len(old_display) > 60:
                old_display = old_display[:57] + "..."
            if len(new_display) > 60:
                new_display = new_display[:57] + "..."
            console.print(f"[bold cyan]\u2502[/bold cyan] [bold red]- {old_display}[/bold red]")
            console.print(f"[bold cyan]\u2502[/bold cyan] [bold green]+ {new_display}[/bold green]")
        elif "patch" in tool_args:
            patch_lines = tool_args["patch"].splitlines()[:20]
            for ln in patch_lines:
                colour = "green" if ln.startswith("+") else ("red" if ln.startswith("-") else "dim")
                display = ln if len(ln) <= 78 else ln[:75] + "..."
                console.print(f"[bold cyan]\u2502[/bold cyan] [{colour}]{display}[/{colour}]")
        elif "content" in tool_args:
            lines = tool_args["content"].splitlines()
            line_count = len(lines)
            for ln in lines[:15]:
                display = ln if len(ln) <= 80 else ln[:77] + "..."
                console.print(f"[bold cyan]\u2502[/bold cyan] [dim]  {display}[/dim]")
            if line_count > 15:
                console.print(f"[bold cyan]\u2502[/bold cyan] [dim]  ... ({line_count - 15} more lines)[/dim]")
        console.print("[bold cyan]\u2570\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u256f[/bold cyan]")
    try:
        answer = input("  Apply this change? (y/n): ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        return False
    return answer in ("y", "yes", "")


def _confirm_run(tool_args, console):
    # Server mode: delegate to callback
    if console and hasattr(console, 'confirm_run'):
        return console.confirm_run(tool_args)
    cmd = tool_args.get("cmd", "?")

    # Trust mode: auto-approve safe commands; always confirm destructive ones
    if working_memory.get("trust_mode"):
        if not _DESTRUCTIVE_CMD_RE.search(cmd):
            if console:
                console.print(f"[dim]  \u2714 auto-approved: run_cmd(cmd=\"{cmd[:60]}...\")[/dim]" if len(cmd) > 60
                              else f"[dim]  \u2714 auto-approved: run_cmd(cmd=\"{cmd}\")[/dim]")
            return True
        # Fall through to manual confirmation for destructive commands
        if console:
            console.print("[bold red]  ⚠ destructive command — confirmation required[/bold red]")

    if console:
        console.print("[bold red]\u256d\u2500 Run Command \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u256e[/bold red]")
        console.print(f"[bold red]\u2502[/bold red] [white]$ {cmd}[/white]")
        console.print("[bold red]\u2570\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u256f[/bold red]")
    try:
        answer = input("  Run this command? (y/n): ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        return False
    return answer in ("y", "yes", "")


# ============================================================
# HELPERS
# ============================================================

def _parse_planner_files(plan, cwd):
    for line in plan.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("files:"):
            raw = stripped.split(":", 1)[1].strip()
            if not raw or raw.lower() in ("unknown", "none", "n/a", "-"):
                return []
            names = [f.strip() for f in raw.split(",") if f.strip()]
            found = []
            for name in names:
                candidate = name if os.path.isabs(name) else os.path.join(cwd, name)
                if os.path.isfile(candidate):
                    found.append(candidate)
            return found
    return []


# ============================================================
# ORCHESTRATOR
# ============================================================

def _run_orchestrator(user_input, file_tree, history, console):
    prompt = ORCHESTRATOR_PROMPT.format(file_tree=file_tree)
    prior = _compact_history(history, max_chars=4000)
    messages = [
        {"role": "system", "content": prompt},
        *prior,
        {"role": "user", "content": user_input},
    ]
    if console:
        console.print("[dim]  ...[/dim]", end="\r")
    response = orchestrator_chat(messages)
    raw = response.get("content", "").strip()
    if console:
        sys.stdout.write("\r" + " " * 40 + "\r")

    obj = _extract_json(raw)
    if obj and isinstance(obj, dict) and "route" in obj:
        route = obj.get("route", "task")
        if route == "task":
            task_val = obj.get("task", "").strip()
            if not task_val or task_val.startswith("<"):
                obj["task"] = user_input
        return obj
    return {"route": "task", "task": user_input, "complexity": "simple"}


# ============================================================
# PLANNER
# ============================================================

def _run_planner(task, auto_context, file_tree, cwd, thinking, history, console):
    context_block = ""
    if auto_context:
        context_block = f"Pre-loaded context:\n{auto_context}\n"

    prompt = PLANNER_PROMPT.format(cwd=cwd, file_tree=file_tree,
                                   context_block=context_block, task=task)
    prior = _compact_history(history, max_chars=3000)
    messages = [
        {"role": "system", "content": prompt},
        *prior,
        {"role": "user", "content": task},
    ]
    if console:
        console.print("[dim]  planning...[/dim]", end="\r")
    response = planner_chat(messages, thinking=thinking)
    plan = response.get("content", "").strip()
    if console:
        sys.stdout.write("\r" + " " * 40 + "\r")
    if not plan or plan.startswith("[LLM Error"):
        return None
    return plan


# ============================================================
# CRITIC
# ============================================================

CRITIC_PROMPT = """\
You are a concise code-review assistant.

Given the original task, the tools the agent called, and the agent's final answer, \
decide if the answer is correct and complete.

Task: {task}

Tools called during this session:
{tool_log}

Agent answer:
{answer}

Rules:
- If the agent called tools (edit_file, write_file, apply_patch, run_cmd, etc.) \
  that address the task, that counts as DONE even if the final text answer is brief.
- Only mark ok=false if the agent genuinely failed to address the task — e.g. it \
  described a fix but never actually applied it, OR it answered a completely \
  different question.
- Reading files, listing directories, and searching code are INFORMATIONAL — they \
  count as completed work for informational tasks.
- When in doubt, mark ok=true. Do NOT reject work that was actually done.

Reply with EXACTLY one of:
  {{"ok": true}}
  {{"ok": false, "issue": "one sentence describing what is missing or wrong"}}

No other text."""


def _run_critic(task, answer, tool_sequence, console):
    tool_log = "(no tools called)"
    if tool_sequence:
        tool_log = "\n".join(
            f"  {i+1}. {t['tool']}({t.get('args_summary', '')})"
            for i, t in enumerate(tool_sequence[-10:])
        )
    messages = [
        {"role": "system", "content": CRITIC_PROMPT.format(
            task=task, answer=answer[:3000], tool_log=tool_log
        )},
    ]
    if console:
        console.print("[dim]  critic reviewing...[/dim]", end="\r")
    raw = critic_chat(messages).get("content", "").strip()
    if console:
        sys.stdout.write("\r" + " " * 40 + "\r")
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    try:
        m = re.search(r"\{[^{}]+\}", raw)
        if m:
            return json.loads(m.group())
    except Exception:
        pass
    return {"ok": True}


# ============================================================
# RESEARCHER
# ============================================================

RESEARCHER_PROMPT = """\
You are a research assistant for a coding agent. Your job is to validate a plan's
feasibility and gather facts that the coder will need before writing any code.

You have TWO tools available — respond with ONLY a JSON tool call, nothing else:

{{"tool": "web_search", "args": {{"query": "search query", "max_results": 5}}}}
  Search theweb for documentation, API references, changelogs, known issues.

{{"tool": "fetch_url", "args": {{"url": "https://docs.example.com/page", "max_chars": 8000}}}}
  Fetch the readable text from a documentation page.

When you have gathered enough information, respond in plain text with a JSON object:
{{
  "verified_facts": ["fact 1", "fact 2", ...],
  "conflicts": ["plan step X uses deprecated API Y — use Z instead", ...],
  "urls": ["https://source1", "https://source2"]
}}

Rules:
- Focus on facts the CODER will need: correct API names, import paths, version
  requirements, config formats, known gotchas.
- Only report conflicts if a plan step is definitively wrong or outdated.
- If everything looks fine, return verified_facts with what you confirmed and
  an empty conflicts list.
- Maximum 3 searches. Be efficient — one good fetch_url beats five web_searches.
- Prefer official docs over blogs/forums.
- NEVER write or edit files. Research only.

Task: {task}

Planner's proposed plan:
{plan}

{cache_block}"""


# Destructive shell command patterns — always confirm even in trust mode
_DESTRUCTIVE_CMD_RE = re.compile(
    r"""
    \b(
      rm\s+-[rf]  | rm\s+--recursive | rm\s+--force   # rm variants
    | del\s+/[sfq]                                     # Windows del /s /f /q
    | rd\s+/s                                          # Windows rmdir /s
    | drop\s+table | drop\s+database | truncate\s+table  # SQL destructive
    | git\s+push\s+--force | git\s+push\s+-f           # force push
    | git\s+reset\s+--hard                             # hard reset
    | format\b                                         # disk format
    | mkfs\b                                           # Linux format
    | shred\b                                          # secure delete
    )""",
    re.VERBOSE | re.IGNORECASE,
)


def _run_researcher(task: str, plan: str, console) -> dict:
    """Validate the plan against the knowledge library and fresh web research.

    Returns {"verified_facts": [...], "conflicts": [...], "urls": [...]}
    """
    # ── 1. Knowledge library lookup ───────────────────────────────────────────
    cached = lookup_research(task)
    stale = get_stale_entries(task)

    if console:
        if cached:
            console.print(f"[dim]  \U0001f50d {len(cached)} cached finding(s) found[/dim]")
        if stale:
            console.print(f"[dim]  \U0001f50d {len(stale)} stale finding(s) — will refresh[/dim]")

    # ── 2. Build cache context for prompt ─────────────────────────────────────
    cache_parts = []
    if cached:
        cache_parts.append("Cached research (fresh — use these, no need to re-search):")
        for e in cached:
            cache_parts.append(f"  • {e['topic']}: {e['findings'][:300]}")
    if stale:
        cache_parts.append("\nStale research (needs re-verification — these may be outdated):")
        for e in stale:
            cache_parts.append(f"  • {e['topic']}: {e['findings'][:200]}")
    cache_block = "\n".join(cache_parts) if cache_parts else ""

    # Skip researcher LLM call entirely if everything is already cached fresh
    # and there are no stale entries and plan is short (simple task)
    all_covered = cached and not stale and len(plan.splitlines()) <= 4
    if all_covered:
        if console:
            console.print(f"[dim]  \U0001f50d all topics cached — skipping web research[/dim]")
        # Build facts from cache
        facts = []
        for e in cached:
            facts.append(e["findings"][:200])
        return {"verified_facts": facts, "conflicts": [], "urls": []}

    # ── 3. Run researcher LLM loop (max 3 rounds) ─────────────────────────────
    if console:
        console.print("[dim]  \U0001f50d researching plan feasibility...[/dim]", end="\r")

    system = RESEARCHER_PROMPT.format(task=task, plan=plan, cache_block=cache_block)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": "Research the plan above and return your findings as JSON."},
    ]

    result = {"verified_facts": [], "conflicts": [], "urls": []}
    new_findings: list = []

    for _round in range(3):
        if console:
            sys.stdout.write("\r" + " " * 60 + "\r")
        response = researcher_chat(messages)
        raw = response.get("content", "").strip()
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

        if not raw or raw.startswith("[LLM Error:"):
            break

        tool_call = _extract_tool_call(raw)

        if not tool_call:
            # Plain-text result — try to parse as final JSON
            obj = _extract_json(raw)
            if obj and isinstance(obj, dict) and "verified_facts" in obj:
                result = obj
            break

        tool_name = tool_call["tool"]
        tool_args = tool_call.get("args", {})

        # Only allow research tools
        if tool_name not in ("web_search", "fetch_url"):
            break

        if console:
            console.print(f"[dim]  \U0001f50d \u25b8 {tool_name}({_summarize_args(tool_args)})[/dim]")

        tool_result = _execute_tool(tool_name, tool_args)

        if console:
            preview = tool_result[:120] + "..." if len(tool_result) > 120 else tool_result
            console.print(f"[dim]  \U0001f50d \u25c2 {preview}[/dim]")

        # Track URLs from web_search results
        if tool_name == "web_search":
            for line in tool_result.splitlines():
                if line.startswith("URL:"):
                    new_findings.append(line.replace("URL:", "").strip())

        messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user", "content": f"[Result]:\n{tool_result}\n\nContinue or return your JSON findings."})

    if console:
        sys.stdout.write("\r" + " " * 60 + "\r")

    # ── 4. Cache new findings ─────────────────────────────────────────────────
    if result.get("verified_facts"):
        findings_text = "; ".join(result["verified_facts"][:5])
        urls = result.get("urls", new_findings[:3])
        # Use the task as topic — concise enough to match future similar tasks
        topic = task[:120]
        try:
            cache_research(
                topic=topic,
                query_used=plan.splitlines()[0] if plan else task,
                urls=urls,
                findings=findings_text,
                stale_days=7,
            )
            if console:
                console.print(f"[dim]  \U0001f50d cached {len(result['verified_facts'])} finding(s) (TTL: 7 days)[/dim]")
        except Exception:
            pass

    n_cached_used = len(cached)
    n_fresh = 1 if result.get("verified_facts") and not all_covered else 0
    if console and (n_cached_used or n_fresh):
        console.print(f"[dim]  \u25c8 {n_cached_used + n_fresh} research finding(s) injected ({n_cached_used} cached, {n_fresh} fresh)[/dim]")

    return result


def _revise_plan(plan: str, conflicts: list, task: str, auto_context: str,
                 file_tree: str, cwd: str, thinking: bool, history: list,
                 console) -> str:
    """Ask the planner to revise the plan based on researcher-found conflicts.

    One round only — no loops.
    """
    if not conflicts:
        return plan

    conflict_block = "\n".join(f"  - {c}" for c in conflicts)
    revision_task = (
        f"{task}\n\n"
        f"[Researcher found issues with the original plan — revise accordingly:]\n"
        f"{conflict_block}"
    )
    context_block = f"Pre-loaded context:\n{auto_context}\n" if auto_context else ""
    prompt = PLANNER_PROMPT.format(
        cwd=cwd, file_tree=file_tree, context_block=context_block, task=revision_task
    )
    prior = _compact_history(history, max_chars=3000)
    messages = [
        {"role": "system", "content": prompt},
        *prior,
        {"role": "user", "content": revision_task},
    ]
    if console:
        console.print("[dim]  planning (revision)...[/dim]", end="\r")
    response = planner_chat(messages, thinking=thinking)
    revised = response.get("content", "").strip()
    if console:
        sys.stdout.write("\r" + " " * 60 + "\r")
    if not revised or revised.startswith("[LLM Error"):
        return plan  # keep original on failure

    conflict_summary = conflicts[0][:80] if conflicts else ""
    if console:
        console.print(f"[dim]  \u270e Plan revised \u2014 researcher found: {conflict_summary}[/dim]")
        console.print("[dim]  Revised plan:[/dim]")
        for line in revised.splitlines():
            if line.strip():
                console.print(f"[dim]    {line}[/dim]")
    return revised


# ============================================================
# MAIN ENTRY POINT
# ============================================================

def agent_converse(user_input, console=None):
    """Three-stage LLM pipeline with CADEN learning:
      1. Orchestrator  — routes: chat / clarify / task
      2. Planner       — decomposes task into a concrete plan
      3. Coder loop    — executes with tools + lessons from past

    CADEN enhancements:
      - Lessons are retrieved before each task (avoid/inspire)
      - Lessons are recorded after each task (mistakes/wins/facts)
      - All model outputs logged for distillation
    """
    cwd = os.getcwd()
    file_tree = _get_file_tree(cwd)

    # ── Refresh codebase index ─────────────────────────────────────────────────
    from tools import get_workspace
    workspace = get_workspace() or cwd
    try:
        from indexer import refresh_index
        refresh_index(workspace, console)
    except Exception:
        pass

    # ── Build import graph (deterministic, < 200ms) ───────────────────────────
    _build_graph(workspace)
    if _import_graph and console:
        n_files = len(_import_graph.imports) + len(set().union(*_import_graph.importers.values()) if _import_graph.importers else set())
        n_edges = sum(len(v) for v in _import_graph.imports.values())
        if n_edges:
            console.print(f"[dim]  ◈ import graph: {n_files} files, {n_edges} edges[/dim]")

    prior_history = list(working_memory["chat_history"])
    working_memory["chat_history"].append({"role": "user", "content": user_input})

    # ── Stage 1: Orchestrator ──────────────────────────────────────────────────
    orch = _run_orchestrator(user_input, file_tree, prior_history, console)
    route = orch.get("route", "task")

    if route == "chat":
        msg = orch.get("message", "")
        if console:
            console.print(f"[bold yellow]Agent:[/bold yellow] {msg}")
        working_memory["chat_history"].append({"role": "assistant", "content": msg})
        return msg

    if route == "clarify":
        question = orch.get("question", "Could you clarify what you need?")
        if console:
            console.print(f"[bold yellow]Agent:[/bold yellow] {question}")
        working_memory["chat_history"].append({"role": "assistant", "content": question})
        return question

    # route == "task"
    task = orch.get("task", user_input)
    thinking = orch.get("complexity", "simple") == "complex" or _is_complex(user_input)
    if console and thinking:
        console.print("[dim]  (complex — reasoning enabled)[/dim]")

    auto_context = _auto_read_context(user_input, cwd)

    # ── Enhance file tree with relevant indexed files ──────────────────────────
    try:
        from indexer import search_files as idx_search_files
        relevant = idx_search_files(workspace, task, limit=15)
        rel_lines = []
        for r in relevant:
            if r["score"] >= 0.2:
                line = f"  {r['rel_path']}"
                if r["symbols_summary"]:
                    line += f" \u2014 {r['symbols_summary']}"
                rel_lines.append(line)
        if rel_lines:
            file_tree += "\n\nRelevant indexed files:\n" + "\n".join(rel_lines)
    except Exception:
        pass

    # ── Stage 2: Planner ─────────────────────────────────────────────────────
    plan = _run_planner(task, auto_context, file_tree, cwd, thinking, prior_history, console)
    if plan and console:
        if hasattr(console, 'on_plan'):
            console.on_plan(plan)
        console.print(f"[dim]  Plan:[/dim]")
        for line in plan.splitlines():
            if line.strip():
                console.print(f"[dim]    {line}[/dim]")
    plan_block = f"PLAN:\n{plan}" if plan else ""

    if plan:
        planner_files = _parse_planner_files(plan, cwd)
        for fpath in planner_files:
            rel = os.path.relpath(fpath, cwd)
            if rel not in auto_context:
                try:
                    with open(fpath, "r", encoding="utf-8", errors="replace") as fh:
                        numbered = "\n".join(
                            f"{i+1:4d} | {line}" for i, line in enumerate(fh.read().splitlines())
                        )
                        auto_context += f"\n\n[{rel}]\n{numbered}"
                    if console:
                        console.print(f"[dim]  pre-loaded: {rel}[/dim]")
                except OSError:
                    pass

    # ── Stage 2.5: Researcher — validate plan, build knowledge library ────────
    research_context = ""
    if plan:
        try:
            research = _run_researcher(task, plan, console)
            # Revise plan if researcher found conflicts
            if research.get("conflicts"):
                plan = _revise_plan(
                    plan, research["conflicts"], task, auto_context,
                    file_tree, cwd, thinking, prior_history, console
                )
                plan_block = f"PLAN:\n{plan}" if plan else ""
            # Inject verified research facts into coder context
            if research.get("verified_facts"):
                facts_text = "\n".join(f"  • {f}" for f in research["verified_facts"][:8])
                urls_text = ""
                if research.get("urls"):
                    urls_text = "\nSources: " + ", ".join(research["urls"][:3])
                research_context = (
                    f"\nVerified research facts (confirmed before coding):\n"
                    f"{facts_text}{urls_text}\n"
                )
        except Exception:
            pass  # researcher errors never block execution

    # ── Stage 3: Coder loop ──────────────────────────────────────────────────
    b_cat, b_vid, b_def = select_variant(task)
    b_hint = b_def.get("hint", "")
    if console:
        console.print(f"[dim]  \u2698 [{b_cat}] {b_vid.replace('_', ' \u2192 ')}[/dim]")

    result, edited_files, loop_messages, tool_seq = _run_coder_loop(
        task, auto_context + research_context, file_tree, cwd, thinking, console,
        history=prior_history, plan_block=plan_block,
        bandit_category=b_cat, bandit_variant_id=b_vid, bandit_hint=b_hint,
    )

    # ── Critic pass ──────────────────────────────────────────────────────────
    # Skip critic entirely if the coder loop returned an LLM error — no point
    # retrying; the error will repeat and the critic will loop forever.
    if not result.startswith("[LLM Error"):
        critique = _run_critic(task, result, tool_seq, console)
        if not critique.get("ok", True):
            issue = critique.get("issue", "Answer incomplete or incorrect.")
            if console:
                console.print(f"[dim]  critic: {issue} \u2014 retrying...[/dim]")
            # Pass the completed loop's message history so the retry agent has
            # all prior reads / tool results in context (avoids re-reading files
            # it already saw and prevents the identical-call loop).
            retry_task = f"{task}\n\n[Critic note: {issue}]"
            # Convert loop_messages to the format _run_coder_loop expects as history
            # (strip the system message — it gets rebuilt — keep assistant/user turns)
            retry_history = [m for m in loop_messages if m["role"] != "system"]
            result, more_edited, _, _ = _run_coder_loop(
                retry_task, auto_context, file_tree, cwd, thinking, console,
                history=retry_history, plan_block=plan_block,
                bandit_category=b_cat, bandit_variant_id=b_vid, bandit_hint=b_hint,
            )
            edited_files.extend(more_edited)

    # ── Doc-tracking advisory ──────────────────────────────────────────────────
    if edited_files and console:
        try:
            from indexer import check_docs_stale
            stale = check_docs_stale(workspace, edited_files)
            if stale:
                if hasattr(console, 'on_advisory'):
                    console.on_advisory('docs', [f"{s['doc_rel']} references: {', '.join(s['references'][:3])}" for s in stale])
                console.print("[dim]  \u270d Documentation may need updating:[/dim]")
                for s in stale:
                    refs = ", ".join(s["references"][:3])
                    console.print(f"[dim]    {s['doc_rel']} references: {refs}[/dim]")
        except Exception:
            pass

    # ── Post-edit impact analysis (deterministic) ─────────────────────────────
    if edited_files and _import_graph and console:
        try:
            impact = _import_graph.impact_zone(edited_files, depth=2)
            if impact:
                if hasattr(console, 'on_advisory'):
                    console.on_advisory('impact', [os.path.relpath(fp, workspace) for fp in sorted(impact)[:10]])
                console.print(f"[dim]  \u26a0 Impact zone ({len(impact)} files may be affected):[/dim]")
                for fp in sorted(impact)[:8]:
                    console.print(f"[dim]    {os.path.relpath(fp, workspace)}[/dim]")
                if len(impact) > 8:
                    console.print(f"[dim]    ... ({len(impact) - 8} more)[/dim]")
        except Exception:
            pass

    # ── Cross-file import validation (deterministic) ──────────────────────────
    if edited_files and console:
        try:
            from graph import validate_imports, detect_signature_changes
            all_import_errors = []
            for fp in edited_files:
                errs = validate_imports(fp, workspace)
                all_import_errors.extend(errs)

            # Also check files that import the edited files
            if _import_graph:
                affected = set()
                for fp in edited_files:
                    affected |= _import_graph.dependents(fp, depth=1)
                for fp in affected:
                    errs = validate_imports(fp, workspace)
                    all_import_errors.extend(errs)

            if all_import_errors:
                if hasattr(console, 'on_advisory'):
                    console.on_advisory('import_error', all_import_errors[:10])
                console.print("[bold red]  \u2718 Import validation issues:[/bold red]")
                for err in all_import_errors[:6]:
                    console.print(f"[bold red]    {err}[/bold red]")
                if len(all_import_errors) > 6:
                    console.print(f"[bold red]    ... ({len(all_import_errors) - 6} more)[/bold red]")
        except Exception:
            pass

    working_memory["chat_history"].append({"role": "assistant", "content": result})
    if console:
        console.print()
    return result
