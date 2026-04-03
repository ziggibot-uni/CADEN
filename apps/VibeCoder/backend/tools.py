import os
import re
import subprocess
import shlex

# --- Workspace safety ---
_workspace_root: list[str | None] = [None]


def set_workspace(path: str) -> None:
    """Restrict all file operations to this directory tree."""
    _workspace_root[0] = os.path.realpath(path)


def get_workspace() -> str | None:
    return _workspace_root[0]


from typing import Optional, Tuple


def _safe_path(path: str) -> Tuple[str, Optional[str]]:
    root = _workspace_root[0]
    if not isinstance(path, str) or not path:
        return path, "Error: invalid path"
    if root is None:
        return path, None
    resolved = os.path.realpath(
        os.path.join(root, path) if not os.path.isabs(path) else path
    )
    if not (resolved == root or resolved.startswith(root + os.sep)):
        return "", (
            f"Error: '{path}' is outside the workspace. "
            f"Only files within '{root}' may be accessed."
        )
    return resolved, None


# --- Edit helpers ---

def _strip_line_numbers(text):
    if not text:
        return text
    lines = text.splitlines()
    stripped = []
    matched = 0
    for line in lines:
        m = re.match(r'^\s{0,6}\d{1,4}\s*\|\s?(.*)', line)
        if m:
            stripped.append(m.group(1))
            matched += 1
        else:
            stripped.append(line)
    if matched >= max(1, len(lines) // 2):
        return '\n'.join(stripped)
    return text


def _closest_match_hint(content, old_text):
    first_line = old_text.strip().splitlines()[0].strip() if old_text.strip() else ""
    if len(first_line) < 4:
        return ""
    key = first_line[:40].lower()
    for i, line in enumerate(content.splitlines()):
        if key in line.lower():
            lines = content.splitlines()
            start, end = max(0, i - 1), min(len(lines), i + 4)
            snippet = "\n".join(f"  {lines[j]}" for j in range(start, end))
            return f"\nNearest match found near line {i + 1}:\n{snippet}"
    return ""


def list_files(path="."):
    path, err = _safe_path(path)
    if err:
        return err
    try:
        entries = sorted(os.listdir(path))
        result = []
        for e in entries:
            full = os.path.join(path, e)
            if os.path.isdir(full):
                result.append(f"  {e}/")
            else:
                result.append(f"  {e}")
        return "\n".join(result) if result else "(empty directory)"
    except Exception as e:
        return f"Error listing files: {e}"


def read_file(path):
    path, err = _safe_path(path)
    if err:
        return err
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        if len(lines) > 500:
            # Structural schema for orientation
            try:
                from validator import analyse_file
                schema = analyse_file(path)
            except Exception:
                schema = ""
            # Head: first 80 lines (imports, docstrings, top declarations)
            head = [f"{i+1:4d} | {line.rstrip()}" for i, line in enumerate(lines[:80])]
            # Tail: last 20 lines (exports, __main__, closing code)
            tail_start = len(lines) - 20
            tail = [f"{i+1:4d} | {line.rstrip()}"
                    for i, line in enumerate(lines[tail_start:], tail_start)]
            omitted = len(lines) - 100
            gap = (
                f"\n... ({omitted} lines omitted — "
                f"use read_symbol to jump to a specific function/class, "
                f"or search_code to find text)\n"
            )
            parts = []
            if schema:
                parts.append(schema)
            parts.append("\n".join(head))
            parts.append(gap)
            parts.append("\n".join(tail))
            return "\n".join(parts)
        numbered = [f"{i+1:4d} | {line.rstrip()}" for i, line in enumerate(lines)]
        return "\n".join(numbered)
    except FileNotFoundError:
        return f"Error: file not found: {path}"
    except Exception as e:
        return f"Error reading file: {e}"


def edit_file(path, old_text, new_text):
    path, err = _safe_path(path)
    if err:
        return err
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        return f"Error: file not found: {path}"
    except Exception as e:
        return f"Error reading file: {e}"

    if old_text in content:
        effective_old, effective_new = old_text, new_text
    else:
        stripped_old = _strip_line_numbers(old_text)
        stripped_new = _strip_line_numbers(new_text)
        if stripped_old != old_text and stripped_old in content:
            effective_old, effective_new = stripped_old, stripped_new
        else:
            def _rstrip_lines(t):
                return '\n'.join(l.rstrip() for l in t.splitlines())
            rstripped_old = _rstrip_lines(old_text)
            rstripped_content = _rstrip_lines(content)
            if rstripped_old in rstripped_content:
                idx = rstripped_content.index(rstripped_old)
                effective_old = content[idx: idx + len(rstripped_old)]
                effective_new = new_text
            else:
                hint = _closest_match_hint(content, old_text)
                return (
                    f"Error: exact text not found in {path}. "
                    f"Read the file first and copy old_text character-for-character.{hint}"
                )

    count = content.count(effective_old)
    new_content = content.replace(effective_old, effective_new, 1)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
    except Exception as e:
        return f"Error writing file: {e}"

    msg = f"Successfully edited {path}"
    if count > 1:
        msg += f" (replaced first of {count} occurrences)"
    return msg


def write_file(path, content):
    path, err = _safe_path(path)
    if err:
        return err
    try:
        parent = os.path.dirname(path)
        if parent and not os.path.exists(parent):
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Successfully wrote {path}"
    except Exception as e:
        return f"Error writing file: {e}"


def search_code(query, path="."):
    if not isinstance(query, str) or not query:
        return "Error: invalid query"
    path, err = _safe_path(path)
    if err:
        return err
    results = []
    code_extensions = {'.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.c', '.cpp', '.h',
                       '.go', '.rs', '.rb', '.php', '.cs', '.md', '.txt', '.yaml', '.yml',
                       '.json', '.toml', '.cfg', '.ini', '.sh', '.bat', '.ps1', '.html', '.css'}
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in
                   {'__pycache__', 'node_modules', '.git', 'venv', '.venv', 'dist', 'build'}]
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in code_extensions:
                continue
            fpath = os.path.join(root, fname)
            if query.lower() in fname.lower():
                results.append(f"  {fpath} [filename match]")
                if len(results) >= 50:
                    results.append(f"\n... (search truncated at 50 results)")
                    return "\n".join(results)
            try:
                with open(fpath, encoding="utf-8", errors="replace") as f:
                    for i, line in enumerate(f, 1):
                        if query.lower() in line.lower():
                            results.append(f"  {fpath}:{i}: {line.rstrip()}")
                            if len(results) >= 50:
                                results.append(f"\n... (search truncated at 50 results)")
                                return "\n".join(results)
            except Exception:
                continue
    return "\n".join(results) if results else f"No results found for '{query}'"


def run_cmd(cmd, timeout=15):
    if not isinstance(cmd, str) or not cmd:
        return "Error: invalid command"
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, stdin=subprocess.DEVNULL
        )
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += ("\n" if output else "") + result.stderr
        if result.returncode != 0:
            output += f"\n(exit code: {result.returncode})"
        return output if output else "(no output)"
    except subprocess.TimeoutExpired as e:
        partial = ""
        if e.stdout:
            partial += e.stdout if isinstance(e.stdout, str) else e.stdout.decode("utf-8", errors="replace")  # type: ignore[union-attr]
        if e.stderr:
            partial += e.stderr if isinstance(e.stderr, str) else e.stderr.decode("utf-8", errors="replace")  # type: ignore[union-attr]
        if not partial.strip():
            return (
                f"[Interactive] The program started but appears to be waiting for user input "
                f"(it did not exit within {timeout}s)."
            )
        return (
            f"[Timeout] Command ran for {timeout}s and was stopped. Partial output:\n{partial.strip()}"
        )
    except Exception as e:
        return f"Error running command: {e}"


def run_interactive(cmd):
    if not isinstance(cmd, str) or not cmd:
        return "Error: invalid command"
    try:
        subprocess.Popen(f'start cmd /k {cmd}', shell=True)
        return f"[Launched] Opened '{cmd}' in a new terminal window."
    except Exception as e:
        return f"Error launching interactive command: {e}"


def run_tests(path="."):
    try:
        result = subprocess.run(
            "pytest --tb=short -q", cwd=path, shell=True,
            capture_output=True, text=True, timeout=120
        )
        return result.stdout + (result.stderr if result.stderr else "")
    except subprocess.TimeoutExpired:
        return "Tests timed out after 120 seconds"
    except Exception:
        return "pytest not found or failed to run"


def apply_patch(path, patch):
    path, err = _safe_path(path)
    if err:
        return err
    from patch_apply import apply_patch_to_file
    return apply_patch_to_file(path, patch)


def read_symbol(path, name):
    """Read a specific function, class, or method by name using AST."""
    path, err = _safe_path(path)
    if err:
        return err
    try:
        from validator import extract_symbol_range
    except ImportError:
        return "Error: validator module not available"
    rng = extract_symbol_range(path, name)
    if rng is None:
        return (
            f"Error: symbol '{name}' not found in {path}. "
            f"Use search_symbols to find it across the codebase."
        )
    start, end = rng
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        ctx_start = max(0, start - 2)
        ctx_end = min(len(lines), end + 1)
        numbered = [f"{i+1:4d} | {line.rstrip()}"
                    for i, line in enumerate(lines[ctx_start:ctx_end], ctx_start)]
        basename = os.path.basename(path)
        header = f"[{name} in {basename}, lines {ctx_start+1}\u2013{ctx_end}]"
        return header + "\n" + "\n".join(numbered)
    except FileNotFoundError:
        return f"Error: file not found: {path}"
    except Exception as e:
        return f"Error reading file: {e}"


def search_symbols_tool(query):
    """Search for functions, classes, and types across the codebase."""
    workspace = get_workspace()
    if not workspace:
        return "Error: no workspace set"
    try:
        from indexer import search_symbols as idx_search
    except ImportError:
        return "Error: indexer module not available"
    results = idx_search(workspace, query)
    if not results:
        return f"No symbols matching '{query}' found in the codebase"
    lines = []
    for r in results:
        lines.append(f"  {r['rel_path']}:{r['line']} \u2014 {r['kind']} {r['name']}")
    return "\n".join(lines)


def read_file_range(path, start_line, end_line=None):
    """Read a specific line range from a file (1-indexed, inclusive)."""
    path, err = _safe_path(path)
    if err:
        return err
    try:
        start_line = int(start_line)
    except (TypeError, ValueError):
        return "Error: start_line must be an integer"
    if end_line is not None:
        try:
            end_line = int(end_line)
        except (TypeError, ValueError):
            return "Error: end_line must be an integer"
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        total = len(lines)
        s = max(1, start_line) - 1  # 0-indexed
        e = min(total, end_line) if end_line else min(total, s + 100)
        if s >= total:
            return f"Error: start_line {start_line} beyond file length ({total} lines)"
        numbered = [f"{i+1:4d} | {line.rstrip()}"
                    for i, line in enumerate(lines[s:e], s)]
        header = f"[{os.path.basename(path)}, lines {s+1}\u2013{e} of {total}]"
        return header + "\n" + "\n".join(numbered)
    except FileNotFoundError:
        return f"Error: file not found: {path}"
    except Exception as ex:
        return f"Error reading file: {ex}"


def replace_body(path, name, new_body):
    """Replace a function/class body by symbol name using AST location.

    More reliable than edit_file for large files — the framework finds the
    exact symbol boundaries deterministically, so old_text matching issues
    are eliminated.
    """
    path, err = _safe_path(path)
    if err:
        return err
    try:
        from validator import extract_symbol_range
    except ImportError:
        return "Error: validator module not available"
    rng = extract_symbol_range(path, name)
    if rng is None:
        return f"Error: symbol '{name}' not found in {path}"
    start_line, end_line = rng  # 1-indexed, inclusive
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except FileNotFoundError:
        return f"Error: file not found: {path}"

    # Preserve the original for rollback
    original = "".join(lines)

    # Replace lines start_line through end_line (1-indexed)
    new_lines = new_body.splitlines(keepends=True)
    if new_lines and not new_lines[-1].endswith("\n"):
        new_lines[-1] += "\n"
    result_lines = lines[:start_line - 1] + new_lines + lines[end_line:]
    new_content = "".join(result_lines)

    # Validate before writing
    from validator import validate_edit
    import tempfile
    tmp_dir = os.path.dirname(path)
    fd, tmp_path = tempfile.mkstemp(suffix=os.path.splitext(path)[1], dir=tmp_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(new_content)
        valid, errors = validate_edit(tmp_path)
        if not valid:
            os.unlink(tmp_path)
            error_block = "; ".join(errors[:3])
            return f"Error: replacement would cause syntax errors: {error_block}"
        os.replace(tmp_path, path)
    except Exception as ex:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        return f"Error: {ex}"

    return f"Successfully replaced '{name}' in {os.path.basename(path)} (lines {start_line}\u2013{end_line} \u2192 {len(new_lines)} lines)"


def find_refs(name):
    """Find all references to a symbol name across the codebase."""
    workspace = get_workspace()
    if not workspace:
        return "Error: no workspace set"
    try:
        from graph import find_references
    except ImportError:
        return "Error: graph module not available"
    refs = find_references(name, workspace, limit=30)
    if not refs:
        return f"No references to '{name}' found in the codebase"
    lines = []
    for r in refs:
        lines.append(f"  {r['rel_path']}:{r['line']}: {r['text']}")
    return "\n".join(lines)


def show_dependents(path):
    """Show files that import/depend on the given file."""
    path, err = _safe_path(path)
    if err:
        return err
    workspace = get_workspace()
    if not workspace:
        return "Error: no workspace set"
    try:
        from graph import ImportGraph
    except ImportError:
        return "Error: graph module not available"
    g = ImportGraph(workspace).build()
    deps = g.dependents(path, depth=2)
    if not deps:
        return f"No files depend on {os.path.relpath(path, workspace)}"
    lines = [f"Files that import {os.path.relpath(path, workspace)} (up to 2 hops):"]
    for d in sorted(deps):
        lines.append(f"  {os.path.relpath(d, workspace)}")
    return "\n".join(lines)


def show_dependencies(path):
    """Show files that the given file imports/depends on."""
    path, err = _safe_path(path)
    if err:
        return err
    workspace = get_workspace()
    if not workspace:
        return "Error: no workspace set"
    try:
        from graph import ImportGraph
    except ImportError:
        return "Error: graph module not available"
    g = ImportGraph(workspace).build()
    deps = g.dependencies(path, depth=2)
    if not deps:
        return f"{os.path.relpath(path, workspace)} has no resolved local imports"
    lines = [f"Dependencies of {os.path.relpath(path, workspace)} (up to 2 hops):"]
    for d in sorted(deps):
        lines.append(f"  {os.path.relpath(d, workspace)}")
    return "\n".join(lines)


def web_search(query, max_results=5):
    if not isinstance(query, str) or not query:
        return "Error: invalid query"
    try:
        from duckduckgo_search import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append(
                    f"Title: {r.get('title', '')}\n"
                    f"URL:   {r.get('href', '')}\n"
                    f"Snippet: {r.get('body', '')}"
                )
        return "\n---\n".join(results) if results else f"No results found for '{query}'"
    except ImportError:
        return "Error: duckduckgo-search is not installed. Run: pip install duckduckgo-search"
    except Exception as e:
        return f"Web search error: {e}"


def fetch_url(url, max_chars=5000):
    if not isinstance(url, str) or not url.startswith("http"):
        return "Error: url must start with http:// or https://"
    try:
        import requests as _req
        headers = {"User-Agent": "Mozilla/5.0 (compatible; VibeCoder/1.0)"}
        res = _req.get(url, timeout=15, headers=headers)
        res.raise_for_status()
        html = res.text
        html = re.sub(r'<(script|style|nav|footer|header)[^>]*>.*?</\1>', ' ', html,
                      flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<[^>]+>', ' ', html)
        text = text.replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
        text = text.replace('&quot;', '"').replace('&#39;', "'").replace('&nbsp;', ' ')
        text = re.sub(r'[ \t]+', ' ', text)
        text = re.sub(r'\n{3,}', '\n\n', text).strip()
        if len(text) > max_chars:
            return text[:max_chars] + f"\n... (truncated — {len(text) - max_chars} more chars)"
        return text if text else "No readable content found at that URL."
    except Exception as e:
        return f"Error fetching {url}: {e}"


TOOL_REGISTRY = {
    "list_files": {"fn": list_files, "args": {"path": "directory path (default: '.')"}},
    "read_file":  {"fn": read_file,  "args": {"path": "file path to read"}},
    "read_file_range": {"fn": read_file_range, "args": {"path": "file path", "start_line": "first line (1-indexed)", "end_line": "last line (optional)"}},
    "read_symbol": {"fn": read_symbol, "args": {"path": "file path", "name": "function, class, or method name"}},
    "replace_body": {"fn": replace_body, "args": {"path": "file path", "name": "function/class name to replace", "new_body": "complete replacement code"}},
    "edit_file":  {"fn": edit_file,  "args": {"path": "file path", "old_text": "exact text to replace", "new_text": "replacement text"}},
    "write_file": {"fn": write_file, "args": {"path": "file path", "content": "full file content"}},
    "search_code": {"fn": search_code, "args": {"query": "search string", "path": "directory (default: '.')"}},
    "search_symbols": {"fn": search_symbols_tool, "args": {"query": "symbol name to find"}},
    "find_refs":  {"fn": find_refs,  "args": {"name": "symbol name to find references for"}},
    "show_dependents": {"fn": show_dependents, "args": {"path": "file to check dependents of"}},
    "show_dependencies": {"fn": show_dependencies, "args": {"path": "file to check dependencies of"}},
    "run_cmd":    {"fn": run_cmd,    "args": {"cmd": "shell command string"}},
    "run_interactive": {"fn": run_interactive, "args": {"cmd": "shell command to launch in a new terminal"}},
    "run_tests":  {"fn": run_tests,  "args": {"path": "directory (default: '.')"}},
    "web_search": {"fn": web_search, "args": {"query": "search query", "max_results": "number of results (default: 5)"}},
    "fetch_url":  {"fn": fetch_url,  "args": {"url": "full URL to fetch", "max_chars": "max characters to return (default: 5000)"}},
    "apply_patch": {"fn": apply_patch, "args": {"path": "file path", "patch": "unified diff string"}},
}

TOOLS = {name: info["fn"] for name, info in TOOL_REGISTRY.items()}
TOOLS["list"] = list_files
TOOLS["read"] = read_file
TOOLS["write"] = write_file
TOOLS["search"] = search_code
TOOLS["run"] = run_cmd
TOOLS["edit"] = edit_file
