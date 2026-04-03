"""Codebase indexer for VibeCoder.

Builds and maintains a persistent SQLite index of file paths and top-level
symbols across the entire workspace.  Enables:

  - Symbol search: find functions/classes/types by name across all files
  - Relevance search: find files relevant to a query (keyword-based)
  - Doc-file discovery: find README/CHANGELOG/docs for update tracking
"""

import ast
import hashlib
import json
import os
import re
import sqlite3
from typing import Dict, List, Optional


# ── Config ────────────────────────────────────────────────────────────────────

_SKIP_DIRS = frozenset({
    '.git', '__pycache__', 'node_modules', '.venv', 'venv',
    'dist', 'build', '.pytest_cache', '.mypy_cache', '.tox',
    '.eggs', 'target', '.next', '.nuxt', 'coverage', '.ruff_cache',
})

_CODE_EXTENSIONS = frozenset({
    '.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.c', '.cpp', '.h', '.hpp',
    '.go', '.rs', '.rb', '.php', '.cs', '.swift', '.kt', '.scala',
    '.md', '.txt', '.yaml', '.yml', '.json', '.toml', '.cfg', '.ini',
    '.sh', '.bat', '.ps1', '.html', '.css', '.scss', '.less',
    '.vue', '.svelte',
})

_DOC_STEMS = frozenset({'readme', 'changelog', 'contributing', 'api', 'license'})

_MAX_INDEX_FILES = 10_000
_MAX_FILE_SIZE = 1_000_000  # 1 MB


# ── Database ──────────────────────────────────────────────────────────────────

def _index_dir() -> str:
    if os.name == 'nt':
        base = os.environ.get('LOCALAPPDATA', os.path.expanduser('~'))
    else:
        base = os.environ.get('XDG_CACHE_HOME',
                              os.path.join(os.path.expanduser('~'), '.cache'))
    d = os.path.join(base, 'vibecoder', 'index')
    os.makedirs(d, exist_ok=True)
    return d


def _db_path(workspace: str) -> str:
    ws_hash = hashlib.md5(os.path.realpath(workspace).encode()).hexdigest()[:12]
    return os.path.join(_index_dir(), f"{ws_hash}.db")


def _get_conn(workspace: str) -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(workspace))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS file_index (
            path      TEXT PRIMARY KEY,
            rel_path  TEXT NOT NULL,
            mtime     REAL NOT NULL,
            size      INTEGER NOT NULL,
            language  TEXT,
            symbols   TEXT
        )
    """)
    conn.commit()
    return conn


# ── Symbol extraction ─────────────────────────────────────────────────────────

def _extract_symbols_python(path: str) -> List[Dict]:
    """AST-based extraction of top-level functions, classes, methods, constants."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            src = f.read()
        tree = ast.parse(src, filename=path)
    except Exception:
        return []

    symbols: List[Dict] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = [a.arg for a in node.args.args]
            symbols.append({
                "name": node.name, "kind": "function",
                "line": node.lineno,
                "end_line": node.end_lineno or node.lineno,
                "sig": f"{node.name}({', '.join(args)})",
            })
        elif isinstance(node, ast.ClassDef):
            symbols.append({
                "name": node.name, "kind": "class",
                "line": node.lineno,
                "end_line": node.end_lineno or node.lineno,
            })
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbols.append({
                        "name": f"{node.name}.{child.name}", "kind": "method",
                        "line": child.lineno,
                        "end_line": child.end_lineno or child.lineno,
                    })
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    symbols.append({
                        "name": target.id, "kind": "constant",
                        "line": node.lineno, "end_line": node.lineno,
                    })
    return symbols


def _extract_symbols_js(path: str) -> List[Dict]:
    """Regex-based extraction for JS/TS/JSX/TSX files."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            src = f.read()
    except Exception:
        return []

    symbols: List[Dict] = []
    patterns = [
        (r'(?:export\s+)?(?:async\s+)?function\s+(\w+)', 'function'),
        (r'(?:export\s+)?class\s+(\w+)', 'class'),
        (r'(?:export\s+)?interface\s+(\w+)', 'interface'),
        (r'(?:export\s+)?type\s+(\w+)\s*[=<]', 'type'),
        (r'(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s+)?\(', 'function'),
        (r'(?:export\s+)?const\s+([A-Z_][A-Z0-9_]*)\s*=', 'constant'),
    ]
    seen: set = set()
    for pattern, kind in patterns:
        for m in re.finditer(pattern, src):
            name = m.group(1)
            if name in seen:
                continue
            seen.add(name)
            line = src[:m.start()].count('\n') + 1
            symbols.append({
                "name": name, "kind": kind,
                "line": line, "end_line": line,
            })
    return symbols


def _extract_symbols(path: str) -> List[Dict]:
    ext = os.path.splitext(path)[1].lower()
    if ext == '.py':
        return _extract_symbols_python(path)
    if ext in ('.js', '.ts', '.jsx', '.tsx', '.vue', '.svelte'):
        return _extract_symbols_js(path)
    return []


def _detect_language(path: str) -> str:
    ext_map = {
        '.py': 'python', '.js': 'javascript', '.ts': 'typescript',
        '.jsx': 'javascript', '.tsx': 'typescript', '.java': 'java',
        '.c': 'c', '.cpp': 'cpp', '.h': 'c', '.hpp': 'cpp',
        '.go': 'go', '.rs': 'rust', '.rb': 'ruby', '.php': 'php',
        '.cs': 'csharp', '.md': 'markdown', '.json': 'json',
        '.yaml': 'yaml', '.yml': 'yaml', '.toml': 'toml',
        '.html': 'html', '.css': 'css', '.scss': 'scss',
        '.sh': 'bash', '.bat': 'batch', '.ps1': 'powershell',
        '.vue': 'vue', '.svelte': 'svelte',
    }
    return ext_map.get(os.path.splitext(path)[1].lower(), 'unknown')


# ── Index operations ──────────────────────────────────────────────────────────

def refresh_index(workspace: str, console=None) -> int:
    """Walk workspace, index new/changed files, prune deleted ones.

    Returns count of files indexed or updated.
    """
    conn = _get_conn(workspace)

    existing: Dict[str, float] = {}
    for row in conn.execute("SELECT path, mtime FROM file_index"):
        existing[row[0]] = row[1]

    seen: set = set()
    updated = 0
    file_count = 0

    for root, dirs, files in os.walk(workspace):
        dirs[:] = [d for d in dirs
                   if d not in _SKIP_DIRS and not d.startswith('.')]
        for fname in files:
            if file_count >= _MAX_INDEX_FILES:
                break
            ext = os.path.splitext(fname)[1].lower()
            if ext not in _CODE_EXTENSIONS:
                continue
            fpath = os.path.join(root, fname)
            rel = os.path.relpath(fpath, workspace)
            seen.add(fpath)
            file_count += 1

            try:
                stat = os.stat(fpath)
            except OSError:
                continue
            if stat.st_size > _MAX_FILE_SIZE:
                continue
            # Skip unchanged
            if fpath in existing and abs(existing[fpath] - stat.st_mtime) < 0.01:
                continue

            symbols = _extract_symbols(fpath)
            lang = _detect_language(fpath)
            conn.execute("""
                INSERT OR REPLACE INTO file_index
                    (path, rel_path, mtime, size, language, symbols)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (fpath, rel, stat.st_mtime, stat.st_size, lang,
                  json.dumps(symbols) if symbols else None))
            updated += 1
        if file_count >= _MAX_INDEX_FILES:
            break

    # Prune deleted files
    deleted = set(existing.keys()) - seen
    if deleted:
        conn.executemany("DELETE FROM file_index WHERE path = ?",
                         [(p,) for p in deleted])
    conn.commit()
    conn.close()

    if console and (updated or deleted):
        console.print(
            f"[dim]  ◈ index: {updated} updated, {len(deleted)} removed "
            f"({file_count} files)[/dim]"
        )
    return updated


def search_symbols(workspace: str, query: str, limit: int = 20) -> List[Dict]:
    """Find symbols matching *query* across the indexed codebase.

    Returns list of ``{name, kind, file, rel_path, line, end_line}``.
    """
    conn = _get_conn(workspace)
    results: List[Dict] = []
    q = query.lower()

    for row in conn.execute(
        "SELECT path, rel_path, symbols FROM file_index WHERE symbols IS NOT NULL"
    ):
        path, rel_path, sym_json = row
        try:
            symbols = json.loads(sym_json)
        except (json.JSONDecodeError, TypeError):
            continue
        for s in symbols:
            name = s.get("name", "")
            if q in name.lower():
                results.append({
                    "name": name,
                    "kind": s.get("kind", "?"),
                    "file": path,
                    "rel_path": rel_path,
                    "line": s.get("line", 0),
                    "end_line": s.get("end_line", 0),
                })
    conn.close()

    def _sort(r: Dict) -> tuple:
        n = r["name"].lower()
        if n == q:
            return (0, n)
        if n.startswith(q):
            return (1, n)
        return (2, n)

    results.sort(key=_sort)
    return results[:limit]


def search_files(workspace: str, query: str, limit: int = 15) -> List[Dict]:
    """Find files relevant to *query* using keyword overlap.

    Returns list of ``{path, rel_path, score, symbols_summary}``.
    """
    conn = _get_conn(workspace)
    query_tokens = _tokenize(query)
    results: List[Dict] = []

    for row in conn.execute("SELECT path, rel_path, symbols FROM file_index"):
        path, rel_path, sym_json = row
        text = rel_path.lower()
        if sym_json:
            text += " " + sym_json.lower()
        file_tokens = _tokenize(text)
        overlap = len(query_tokens & file_tokens)
        if overlap:
            score = overlap / max(len(query_tokens), 1)
            results.append({
                "path": path,
                "rel_path": rel_path,
                "score": score,
                "symbols_summary": _summarize_symbols(sym_json),
            })

    conn.close()
    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:limit]


def _tokenize(text: str) -> set:
    """Split text into search tokens, handling snake_case and camelCase."""
    # Split on non-alphanumeric, then split snake_case and camelCase
    raw = re.split(r'[^a-zA-Z0-9]+', text.lower())
    tokens: set = set()
    for word in raw:
        if not word:
            continue
        tokens.add(word)
        # Split camelCase: "validateEdit" → "validate", "edit"
        parts = re.sub(r'([a-z])([A-Z])', r'\1_\2', word).lower().split('_')
        for p in parts:
            if p:
                tokens.add(p)
    return tokens - {''}


def _summarize_symbols(sym_json: Optional[str]) -> str:
    if not sym_json:
        return ""
    try:
        symbols = json.loads(sym_json)
    except Exception:
        return ""
    parts = []
    for s in symbols[:12]:
        parts.append(f"{s.get('kind', '?')}:{s.get('name', '?')}")
    trail = " ..." if len(symbols) > 12 else ""
    return ", ".join(parts) + trail


# ── Doc-file utilities ────────────────────────────────────────────────────────

def find_doc_files(workspace: str) -> List[str]:
    """Return absolute paths of documentation files in the workspace."""
    conn = _get_conn(workspace)
    docs: List[str] = []
    for row in conn.execute("SELECT path, rel_path FROM file_index"):
        path, rel_path = row
        rl = rel_path.lower().replace('\\', '/')
        stem = os.path.splitext(os.path.basename(rl))[0]
        if stem in _DOC_STEMS:
            docs.append(path)
        elif ('/docs/' in rl or '/doc/' in rl
              or rl.startswith('docs/') or rl.startswith('doc/')):
            docs.append(path)
    conn.close()
    return docs


def check_docs_stale(workspace: str, edited_files: List[str]) -> List[Dict]:
    """Check whether doc files mention any of the *edited_files*.

    Returns list of ``{doc_path, doc_rel, references}`` for docs that
    may need updating.
    """
    doc_files = find_doc_files(workspace)
    if not doc_files or not edited_files:
        return []

    identifiers: set = set()
    for fp in edited_files:
        identifiers.add(os.path.basename(fp))
        rel = os.path.relpath(fp, workspace).replace('\\', '/')
        identifiers.add(rel)
        identifiers.add(os.path.splitext(os.path.basename(fp))[0])
    # Drop very short identifiers that would match too broadly
    identifiers = {i for i in identifiers if len(i) > 2}

    hits: List[Dict] = []
    for dp in doc_files:
        try:
            content = open(dp, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        found = [i for i in identifiers if i in content]
        if found:
            hits.append({
                "doc_path": dp,
                "doc_rel": os.path.relpath(dp, workspace),
                "references": found,
            })
    return hits
