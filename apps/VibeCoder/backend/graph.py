"""Deterministic dependency graph and impact analysis for VibeCoder.

All operations are AST/regex-based — zero LLM calls. This module handles:

  1. Import graph  — who imports whom, across the entire workspace
  2. Reference scan — where is a given symbol used (deterministic grep+parse)
  3. Impact zone   — given a set of edited files, what else might break
  4. Smart context — select the minimal set of files/symbols for a task
  5. Cross-file validation — check that imports still resolve after edits
"""

import ast
import os
import re
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

# ── Config ────────────────────────────────────────────────────────────────────

_SKIP_DIRS: FrozenSet[str] = frozenset({
    '.git', '__pycache__', 'node_modules', '.venv', 'venv',
    'dist', 'build', '.pytest_cache', '.mypy_cache', '.tox',
    '.eggs', 'target', '.next', '.nuxt', 'coverage',
})

_SOURCE_EXTENSIONS: FrozenSet[str] = frozenset({
    '.py', '.js', '.ts', '.jsx', '.tsx',
})

_MAX_SCAN_FILES = 5_000


# ══════════════════════════════════════════════════════════════════════════════
# 1. IMPORT GRAPH — deterministic, AST for Python, regex for JS/TS
# ══════════════════════════════════════════════════════════════════════════════

class ImportGraph:
    """Directed graph of import relationships across a workspace.

    Edges:  imports[A] = {B, C}      means A imports from B and C
            importers[B] = {A, D}    means B is imported by A and D

    Built once per agent_converse() call (< 200ms for 5K files).
    """

    __slots__ = ('imports', 'importers', 'workspace', '_file_modules')

    def __init__(self, workspace: str):
        self.workspace: str = os.path.realpath(workspace)
        self.imports: Dict[str, Set[str]] = {}      # file → {files it imports}
        self.importers: Dict[str, Set[str]] = {}     # file → {files that import it}
        self._file_modules: Dict[str, str] = {}      # module name → abs path

    def build(self) -> 'ImportGraph':
        """Walk workspace, parse imports, resolve to file paths."""
        # Phase 1: collect all source files and build module→path map
        all_files: List[str] = []
        for root, dirs, files in os.walk(self.workspace):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS
                       and not d.startswith('.')]
            for fname in files:
                ext = os.path.splitext(fname)[1].lower()
                if ext not in _SOURCE_EXTENSIONS:
                    continue
                fpath = os.path.join(root, fname)
                all_files.append(fpath)
                if len(all_files) >= _MAX_SCAN_FILES:
                    break
            if len(all_files) >= _MAX_SCAN_FILES:
                break

        # Build module → path map for Python
        for fpath in all_files:
            if fpath.endswith('.py'):
                rel = os.path.relpath(fpath, self.workspace)
                # e.g. "backend/model.py" → "backend.model"
                mod = rel.replace(os.sep, '.').replace('/', '.')
                if mod.endswith('.py'):
                    mod = mod[:-3]
                if mod.endswith('.__init__'):
                    mod = mod[:-9]
                self._file_modules[mod] = fpath
                # Also map just the filename stem for relative imports
                stem = os.path.splitext(os.path.basename(fpath))[0]
                if stem not in self._file_modules:
                    self._file_modules[stem] = fpath

        # Phase 2: parse each file's imports and resolve to paths
        for fpath in all_files:
            ext = os.path.splitext(fpath)[1].lower()
            if ext == '.py':
                imported_modules = _extract_python_imports(fpath)
            elif ext in ('.js', '.ts', '.jsx', '.tsx'):
                imported_modules = _extract_js_imports(fpath, self.workspace)
            else:
                continue

            resolved: Set[str] = set()
            for mod in imported_modules:
                target = self._resolve(mod, fpath)
                if target and target != fpath:
                    resolved.add(target)

            if resolved:
                self.imports[fpath] = resolved
                for target in resolved:
                    self.importers.setdefault(target, set()).add(fpath)

        return self

    def _resolve(self, module: str, from_file: str) -> Optional[str]:
        """Resolve a module name to an absolute file path."""
        # Direct match in module map
        if module in self._file_modules:
            return self._file_modules[module]

        # Try relative from the importing file's directory
        from_dir = os.path.dirname(from_file)
        for ext in ('.py', '.js', '.ts', '.jsx', '.tsx'):
            candidate = os.path.join(from_dir, module.replace('.', os.sep) + ext)
            if os.path.isfile(candidate):
                return os.path.realpath(candidate)

        # Try relative with index
        for idx in ('__init__.py', 'index.js', 'index.ts', 'index.tsx'):
            candidate = os.path.join(from_dir, module.replace('.', os.sep), idx)
            if os.path.isfile(candidate):
                return os.path.realpath(candidate)

        # Try workspace-relative
        parts = module.split('.')
        for ext in ('.py', '.js', '.ts', '.jsx', '.tsx'):
            candidate = os.path.join(self.workspace, *parts[:-1],
                                     parts[-1] + ext) if parts else ''
            if candidate and os.path.isfile(candidate):
                return os.path.realpath(candidate)

        return None

    def dependents(self, path: str, depth: int = 1) -> Set[str]:
        """Files that import *path*, transitively up to *depth* hops."""
        path = os.path.realpath(path)
        visited: Set[str] = set()
        frontier: Set[str] = {path}
        for _ in range(depth):
            next_frontier: Set[str] = set()
            for f in frontier:
                for imp in self.importers.get(f, set()):
                    if imp not in visited and imp != path:
                        visited.add(imp)
                        next_frontier.add(imp)
            frontier = next_frontier
            if not frontier:
                break
        return visited

    def dependencies(self, path: str, depth: int = 1) -> Set[str]:
        """Files that *path* imports, transitively up to *depth* hops."""
        path = os.path.realpath(path)
        visited: Set[str] = set()
        frontier: Set[str] = {path}
        for _ in range(depth):
            next_frontier: Set[str] = set()
            for f in frontier:
                for dep in self.imports.get(f, set()):
                    if dep not in visited and dep != path:
                        visited.add(dep)
                        next_frontier.add(dep)
            frontier = next_frontier
            if not frontier:
                break
        return visited

    def impact_zone(self, edited_files: List[str], depth: int = 2) -> Set[str]:
        """All files within *depth* import hops of any edited file.

        Combines both directions: if I edited A, return everything that
        imports A (might break) AND everything A imports (A depends on).
        Prioritizes importers (breakage direction).
        """
        zone: Set[str] = set()
        for f in edited_files:
            zone |= self.dependents(f, depth=depth)
            zone |= self.dependencies(f, depth=1)  # only 1 hop for deps
        zone -= set(os.path.realpath(f) for f in edited_files)
        return zone


# ── Import extraction (deterministic) ────────────────────────────────────────

def _extract_python_imports(path: str) -> List[str]:
    """AST-based extraction of imported module names from a Python file."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            src = f.read()
        tree = ast.parse(src, filename=path)
    except Exception:
        return []

    modules: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.append(alias.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.append(node.module.split('.')[0])
    return modules


def _extract_js_imports(path: str, workspace: str) -> List[str]:
    """Regex-based extraction of imported module paths from JS/TS files."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            src = f.read()
    except Exception:
        return []

    modules: List[str] = []
    # import ... from 'path'  or  require('path')
    for m in re.finditer(
        r"""(?:from|require\()\s*['"]([^'"]+)['"]""", src
    ):
        mod = m.group(1)
        # Only resolve relative imports (skip npm packages)
        if mod.startswith('.'):
            # Strip leading ./ or ../
            clean = mod.lstrip('.').lstrip('/')
            if clean:
                modules.append(clean)
    return modules


# ══════════════════════════════════════════════════════════════════════════════
# 2. REFERENCE SCAN — deterministic grep+parse for symbol usage
# ══════════════════════════════════════════════════════════════════════════════

def find_references(symbol: str, workspace: str,
                    limit: int = 30) -> List[Dict]:
    """Find all files/lines where *symbol* appears as an identifier.

    Does NOT check if it's the same symbol (no type system) — returns
    textual matches filtered to word boundaries. Fast O(n) scan.

    Returns list of ``{file, rel_path, line, text}``.
    """
    if not symbol or len(symbol) < 2:
        return []

    pattern = re.compile(r'\b' + re.escape(symbol) + r'\b')
    results: List[Dict] = []
    count = 0

    for root, dirs, files in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS
                   and not d.startswith('.')]
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in _SOURCE_EXTENSIONS:
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, encoding="utf-8", errors="replace") as f:
                    for i, line in enumerate(f, 1):
                        if pattern.search(line):
                            results.append({
                                "file": fpath,
                                "rel_path": os.path.relpath(fpath, workspace),
                                "line": i,
                                "text": line.rstrip()[:120],
                            })
                            count += 1
                            if count >= limit:
                                return results
            except Exception:
                continue

    return results


# ══════════════════════════════════════════════════════════════════════════════
# 3. SMART CONTEXT SELECTION — deterministic, no LLM
# ══════════════════════════════════════════════════════════════════════════════

def select_context(task: str, mentioned_files: List[str],
                   graph: ImportGraph, workspace: str,
                   max_files: int = 12, max_chars: int = 10000) -> List[Dict]:
    """Deterministically select the most relevant files + excerpts for a task.

    Strategy:
      1. Start with files explicitly mentioned by the user (highest priority)
      2. Add direct import neighbors (1 hop) of mentioned files
      3. Add files containing symbols mentioned in the task
      4. Budget: up to max_files files, max_chars total

    Returns list of ``{path, rel_path, priority, excerpt}``.
    """
    scored: Dict[str, float] = {}

    # Priority 1: mentioned files (score 3.0)
    for fp in mentioned_files:
        real = os.path.realpath(fp)
        if os.path.isfile(real):
            scored[real] = 3.0

    # Priority 2: import neighbors of mentioned files (score 2.0)
    for fp in mentioned_files:
        real = os.path.realpath(fp)
        # Files that the mentioned file imports
        for dep in graph.imports.get(real, set()):
            if dep not in scored:
                scored[dep] = 2.0
        # Files that import the mentioned file (might need updates)
        for imp in graph.importers.get(real, set()):
            if imp not in scored:
                scored[imp] = 1.5

    # Priority 3: files containing task keywords (score 1.0)
    task_identifiers = _extract_identifiers(task)
    if task_identifiers and len(scored) < max_files:
        for ident in list(task_identifiers)[:5]:
            refs = find_references(ident, workspace, limit=5)
            for ref in refs:
                real = os.path.realpath(ref["file"])
                if real not in scored:
                    scored[real] = 1.0

    # Sort by score, take top
    ranked = sorted(scored.items(), key=lambda x: x[1], reverse=True)[:max_files]

    # Build excerpts within char budget
    results: List[Dict] = []
    total = 0
    for path, priority in ranked:
        if total >= max_chars:
            break
        excerpt = _smart_excerpt(path, task_identifiers, max_chars - total)
        if not excerpt:
            continue
        results.append({
            "path": path,
            "rel_path": os.path.relpath(path, workspace),
            "priority": priority,
            "excerpt": excerpt,
        })
        total += len(excerpt)

    return results


def _extract_identifiers(text: str) -> List[str]:
    """Pull likely code identifiers from natural language text."""
    # Match snake_case, camelCase, PascalCase, and dotted names
    raw = re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_.]*[a-zA-Z0-9]\b', text)
    # Filter: keep names that look like code, not English
    code_like = []
    _english = frozenset({
        'the', 'and', 'for', 'that', 'this', 'with', 'from', 'have',
        'are', 'not', 'but', 'all', 'can', 'was', 'will', 'been',
        'into', 'about', 'would', 'could', 'should', 'there', 'their',
        'what', 'when', 'make', 'like', 'just', 'over', 'such', 'take',
        'than', 'them', 'very', 'after', 'also', 'did', 'some', 'other',
        'which', 'only', 'its', 'does', 'each', 'then', 'how', 'any',
        'these', 'need', 'file', 'code', 'function', 'class', 'method',
        'add', 'fix', 'change', 'update', 'remove', 'delete', 'create',
        'implement', 'refactor', 'move', 'rename', 'use', 'using',
    })
    for name in raw:
        lower = name.lower()
        if lower in _english:
            continue
        if len(name) < 3:
            continue
        # Has underscore, dot, or mixed case → likely code
        if '_' in name or '.' in name or (name[0].islower() and any(c.isupper() for c in name[1:])):
            code_like.append(name)
        # PascalCase
        elif name[0].isupper() and any(c.islower() for c in name):
            code_like.append(name)
    return code_like[:10]


def _smart_excerpt(path: str, identifiers: List[str],
                   budget: int) -> str:
    """Build a focused excerpt of a file prioritizing relevant sections.

    For Python files: uses AST to identify relevant functions/classes.
    For others: falls back to schema + head/tail.
    """
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            src = f.read()
    except Exception:
        return ""

    lines = src.splitlines()
    if not lines:
        return ""

    # Small files: return whole thing
    if len(src) <= budget:
        numbered = [f"{i+1:4d} | {line}" for i, line in enumerate(lines)]
        return "\n".join(numbered)

    ext = os.path.splitext(path)[1].lower()

    if ext == '.py' and identifiers:
        return _python_focused_excerpt(path, src, lines, identifiers, budget)

    # Fallback: schema + head
    try:
        from validator import analyse_file
        schema = analyse_file(path)
    except Exception:
        schema = ""

    head_lines = min(40, budget // 80)
    head = [f"{i+1:4d} | {line}" for i, line in enumerate(lines[:head_lines])]
    parts = []
    if schema:
        parts.append(schema)
    parts.append("\n".join(head))
    if len(lines) > head_lines:
        parts.append(f"... ({len(lines) - head_lines} more lines)")
    return "\n".join(parts)[:budget]


def _python_focused_excerpt(path: str, src: str, lines: List[str],
                            identifiers: List[str],
                            budget: int) -> str:
    """AST-guided excerpt: extract only the functions/classes that match identifiers."""
    try:
        tree = ast.parse(src, filename=path)
    except Exception:
        head = [f"{i+1:4d} | {line}" for i, line in enumerate(lines[:30])]
        return "\n".join(head)

    ident_lower = {i.lower() for i in identifiers}

    # Score each top-level node by relevance
    scored_ranges: List[Tuple[float, int, int, str]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = node.name
            start = node.lineno - 1
            end = (node.end_lineno or node.lineno) - 1
            # Score: exact match > substring match > no match
            score = 0.0
            if name.lower() in ident_lower:
                score = 3.0
            elif any(i.lower() in name.lower() or name.lower() in i.lower()
                     for i in ident_lower):
                score = 2.0
            else:
                # Check if any identifier appears in the function body
                body_text = "\n".join(lines[start:end + 1]).lower()
                matches = sum(1 for i in ident_lower if i in body_text)
                if matches:
                    score = 0.5 + matches * 0.3
            if score > 0:
                scored_ranges.append((score, start, end, name))

        # Also check class methods
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    name = f"{node.name}.{child.name}"
                    start = child.lineno - 1
                    end = (child.end_lineno or child.lineno) - 1
                    score = 0.0
                    if child.name.lower() in ident_lower:
                        score = 3.0
                    elif any(i.lower() in child.name.lower() for i in ident_lower):
                        score = 2.0
                    if score > 0:
                        scored_ranges.append((score, start, end, name))

    if not scored_ranges:
        # No relevant symbols found — return imports + head
        head = [f"{i+1:4d} | {line}" for i, line in enumerate(lines[:30])]
        return "\n".join(head)

    # Sort by score (descending), take best within budget
    scored_ranges.sort(key=lambda x: x[0], reverse=True)
    parts: List[str] = []
    total = 0

    # Always include imports (first ~20 lines or until first def/class)
    import_end = 0
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            import_end = node.end_lineno or node.lineno
        else:
            break
    if import_end:
        import_block = [f"{i+1:4d} | {line}" for i, line in enumerate(lines[:import_end])]
        block = "\n".join(import_block)
        parts.append(block)
        total += len(block)

    for score, start, end, name in scored_ranges:
        ctx_start = max(0, start - 1)
        ctx_end = min(len(lines), end + 2)
        block_lines = [f"{i+1:4d} | {line}"
                       for i, line in enumerate(lines[ctx_start:ctx_end], ctx_start)]
        block = f"\n[{name}]\n" + "\n".join(block_lines)
        if total + len(block) > budget:
            if not parts:  # at least one block
                parts.append(block[:budget])
            break
        parts.append(block)
        total += len(block)

    return "\n".join(parts)


# ══════════════════════════════════════════════════════════════════════════════
# 4. CROSS-FILE IMPORT VALIDATION — deterministic
# ══════════════════════════════════════════════════════════════════════════════

def validate_imports(path: str, workspace: str) -> List[str]:
    """Check that all imports in *path* resolve to existing files/modules.

    Returns list of error strings. Empty list = all imports resolve.
    Only validates local (relative/workspace) imports, not stdlib/pip packages.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext != '.py':
        return []  # only Python for now

    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            src = f.read()
        tree = ast.parse(src, filename=path)
    except Exception:
        return []

    errors: List[str] = []
    file_dir = os.path.dirname(os.path.realpath(path))

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if not node.module:
                continue
            mod = node.module

            # Skip stdlib and pip packages (heuristic: not in workspace)
            first_part = mod.split('.')[0]
            candidate = os.path.join(file_dir, first_part + '.py')
            candidate_pkg = os.path.join(file_dir, first_part, '__init__.py')
            ws_candidate = os.path.join(workspace, first_part + '.py')
            ws_candidate_pkg = os.path.join(workspace, first_part, '__init__.py')

            is_local = (os.path.isfile(candidate) or os.path.isdir(os.path.join(file_dir, first_part))
                        or os.path.isfile(ws_candidate) or os.path.isdir(os.path.join(workspace, first_part)))
            if not is_local:
                continue  # external package, skip

            # Check if the specific imported names exist
            resolved = None
            for base_dir in (file_dir, workspace):
                parts = mod.split('.')
                mod_file = os.path.join(base_dir, *parts) + '.py'
                mod_pkg = os.path.join(base_dir, *parts, '__init__.py')
                if os.path.isfile(mod_file):
                    resolved = mod_file
                    break
                if os.path.isfile(mod_pkg):
                    resolved = mod_pkg
                    break

            if not resolved:
                errors.append(
                    f"{os.path.relpath(path, workspace)}:{node.lineno}: "
                    f"cannot resolve 'from {mod} import ...' — "
                    f"no file found for module '{mod}'"
                )
                continue

            # Check if imported names exist in the resolved module
            if node.names:
                try:
                    with open(resolved, encoding="utf-8", errors="replace") as f:
                        target_src = f.read()
                    target_tree = ast.parse(target_src)
                    defined = _collect_defined_names(target_tree)
                    for alias in node.names:
                        name = alias.name
                        if name == '*':
                            continue
                        if name not in defined:
                            errors.append(
                                f"{os.path.relpath(path, workspace)}:{node.lineno}: "
                                f"'{name}' not found in '{mod}' — "
                                f"available: {', '.join(sorted(defined)[:10])}"
                            )
                except Exception:
                    pass

    return errors


def _collect_defined_names(tree: ast.Module) -> Set[str]:
    """Collect all top-level names defined in an AST."""
    names: Set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add(alias.asname or alias.name)
    return names


# ══════════════════════════════════════════════════════════════════════════════
# 5. SIGNATURE CHANGE DETECTION — deterministic
# ══════════════════════════════════════════════════════════════════════════════

def detect_signature_changes(old_src: str, new_src: str,
                             path: str) -> List[Dict]:
    """Compare old and new source of a file, find changed function signatures.

    Returns list of ``{name, old_sig, new_sig}`` for functions whose
    parameter lists changed. This helps the agent know which callers
    might need updating.
    """
    if os.path.splitext(path)[1].lower() != '.py':
        return []

    old_sigs = _extract_signatures(old_src)
    new_sigs = _extract_signatures(new_src)

    changes: List[Dict] = []
    for name, old_sig in old_sigs.items():
        if name in new_sigs and new_sigs[name] != old_sig:
            changes.append({
                "name": name,
                "old_sig": old_sig,
                "new_sig": new_sigs[name],
            })
    # Also detect removed functions
    for name in old_sigs:
        if name not in new_sigs:
            changes.append({
                "name": name,
                "old_sig": old_sigs[name],
                "new_sig": "(removed)",
            })
    return changes


def _extract_signatures(src: str) -> Dict[str, str]:
    """Extract function name → signature string map from Python source."""
    try:
        tree = ast.parse(src)
    except Exception:
        return {}
    sigs: Dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            params: List[str] = []
            for a in args.args:
                params.append(a.arg)
            if args.vararg:
                params.append(f"*{args.vararg.arg}")
            for a in args.kwonlyargs:
                params.append(a.arg)
            if args.kwarg:
                params.append(f"**{args.kwarg.arg}")
            sigs[node.name] = f"({', '.join(params)})"
    return sigs
