"""Static analysis for the coding agent.

Two layers, both deterministic — no LLM involved:

  1. analyse_file(path)  — pre-read structural schema extraction.
     Returns a compact summary of top-level symbols (classes, functions,
     imports) suitable for injection alongside raw file content.
     Supports: .py (AST), .ts/.tsx/.js/.jsx (regex), .json (parse).

  2. validate_edit(path) — post-edit correctness check.
     Runs language-appropriate validation after every edit.
     Supports: .py (ast + ruff/pyflakes), .js/.ts/.jsx/.tsx (node --check),
               .json (json.loads), .rs (rustc --edition 2021).
     Returns (ok: bool, errors: list[str]).
"""

import ast
import json
import os
import re
import subprocess
import sys
from typing import Optional


# ── Tool availability cache ───────────────────────────────────────────────────
def _cmd_available(cmd: str) -> bool:
    try:
        subprocess.run([cmd, "--version"], capture_output=True, timeout=5)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def _find_linter() -> Optional[str]:
    for cmd in ("ruff", "pyflakes"):
        if _cmd_available(cmd):
            return cmd
    return None


_LINTER: Optional[str] = _find_linter()
_HAS_NODE: bool = _cmd_available("node")
_HAS_RUSTC: bool = _cmd_available("rustc")


# ── Post-edit validation ───────────────────────────────────────────────────────

def validate_edit(path: str) -> tuple[bool, list[str]]:
    """Check a file after an edit.

    Returns (ok, errors) where errors is a list of human-readable strings.
    Returns (True, []) for file types with no available validator.
    """
    ext = os.path.splitext(path)[1].lower()

    if ext == ".py":
        return _validate_python(path)
    if ext in (".js", ".ts", ".jsx", ".tsx") and _HAS_NODE:
        return _validate_js(path)
    if ext == ".json":
        return _validate_json(path)
    if ext == ".rs" and _HAS_RUSTC:
        return _validate_rust(path)
    return True, []


def _validate_python(path: str) -> tuple[bool, list[str]]:
    """Python: ast.parse + ruff/pyflakes."""

    errors: list[str] = []

    # Layer 1: ast.parse — catches syntax errors instantly, zero deps
    try:
        src = open(path, encoding="utf-8").read()
        ast.parse(src, filename=path)
    except SyntaxError as e:
        errors.append(f"SyntaxError: {e.msg} (line {e.lineno})")
        # Don't bother with linter if it won't parse
        return False, errors
    except Exception as e:
        errors.append(f"Read error: {e}")
        return False, errors

    # Layer 2: linter — catches undefined names, unused imports, etc.
    if _LINTER:
        try:
            cmd = (
                ["ruff", "check", "--select=E,F", "--no-fix", path]
                if _LINTER == "ruff"
                else ["pyflakes", path]
            )
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=15,
            )
            output = (result.stdout + result.stderr).strip()
            if result.returncode != 0 and output:
                for line in output.splitlines():
                    # Skip ruff/pyflakes summary lines like "Found N errors."
                    if line and not line.startswith("Found ") and not line.startswith("error:"):
                        errors.append(line)
        except subprocess.TimeoutExpired:
            pass  # linter took too long — skip silently
        except Exception:
            pass

    return len(errors) == 0, errors


def _validate_js(path: str) -> tuple[bool, list[str]]:
    """JS/TS/JSX/TSX: node --check (syntax only, zero config, works everywhere)."""
    try:
        result = subprocess.run(
            ["node", "--check", path],
            capture_output=True, text=True, timeout=15,
        )
        output = (result.stdout + result.stderr).strip()
        if result.returncode != 0 and output:
            # Filter node's own noise; keep lines mentioning the file or line numbers
            errors = [
                ln for ln in output.splitlines()
                if ln.strip()
                and not ln.startswith("SyntaxError" + " is not")
            ]
            return False, errors or [output[:300]]
        return True, []
    except subprocess.TimeoutExpired:
        return True, []  # can't validate; don't block
    except Exception as e:
        return True, []


def _validate_json(path: str) -> tuple[bool, list[str]]:
    """JSON: stdlib json.loads."""
    try:
        src = open(path, encoding="utf-8").read()
        json.loads(src)
        return True, []
    except json.JSONDecodeError as e:
        return False, [f"JSONDecodeError: {e.msg} (line {e.lineno} col {e.colno})"]
    except Exception as e:
        return True, []  # can't read; don't block


def _validate_rust(path: str) -> tuple[bool, list[str]]:
    """Rust: rustc syntax check only (no linking)."""
    try:
        result = subprocess.run(
            ["rustc", "--edition", "2021", "--crate-type", "lib",
             "-Z", "no-codegen", path],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            errors = [
                ln for ln in (result.stdout + result.stderr).splitlines()
                if ln.strip() and ("error" in ln.lower() or "warning" in ln.lower())
            ]
            return False, errors[:10] or ["rustc reported errors"]
        return True, []
    except subprocess.TimeoutExpired:
        return True, []
    except Exception:
        return True, []


# ── Pre-read structural analysis ──────────────────────────────────────────────

def analyse_file(path: str) -> str:
    """Extract a compact structural schema from a source file.

    Returns a string injected alongside raw file content so the model
    can orient itself before reading line-by-line.

    Supports: .py (AST), .ts/.tsx/.js/.jsx (regex), .json (keys).
    Returns empty string for unsupported types or parse failures.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext == ".py":
        return _analyse_python(path)
    if ext in (".ts", ".tsx", ".js", ".jsx"):
        return _analyse_js(path)
    if ext == ".json":
        return _analyse_json(path)
    return ""


def _schema_block(parts: list[str]) -> str:
    if not parts:
        return ""
    return "[Schema]\n" + "\n".join(f"  {p}" for p in parts)


def _analyse_python(path: str) -> str:
    """AST-based structural schema for Python files."""
    try:
        src = open(path, encoding="utf-8").read()
        tree = ast.parse(src, filename=path)
    except Exception:
        return ""

    imports: list[str] = []
    classes: list[str] = []
    functions: list[str] = []
    constants: list[str] = []

    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for alias in node.names:
                imports.append(f"{mod}.{alias.asname or alias.name}")
        elif isinstance(node, ast.ClassDef):
            bases = ", ".join(
                (b.id if isinstance(b, ast.Name) else ast.unparse(b))
                for b in node.bases
            )
            classes.append(f"{node.name}({bases})" if bases else node.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = [a.arg for a in node.args.args]
            functions.append(f"{node.name}({', '.join(args)})")
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    constants.append(target.id)

    parts = []
    if imports:
        parts.append(f"imports: {', '.join(imports[:12])}" + (" ..." if len(imports) > 12 else ""))
    if classes:
        parts.append(f"classes: {', '.join(classes)}")
    if functions:
        parts.append(f"functions: {', '.join(functions[:16])}" + (" ..." if len(functions) > 16 else ""))
    if constants:
        parts.append(f"constants: {', '.join(constants[:8])}")
    return _schema_block(parts)


def _analyse_js(path: str) -> str:
    """Regex-based structural schema for JS/TS/JSX/TSX files.

    Extracts: imports, exports, top-level function/class/interface/type names.
    Not a full parser — good enough for orientation, never fails on exotic syntax.
    """
    try:
        src = open(path, encoding="utf-8", errors="replace").read()
    except Exception:
        return ""

    imports: list[str] = []
    exports: list[str] = []
    functions: list[str] = []
    classes: list[str] = []
    interfaces: list[str] = []
    types: list[str] = []

    for m in re.finditer(
        r"""^import\s+(?:type\s+)?(?:\{([^}]+)\}|(\w+)|\*\s+as\s+(\w+))\s+from\s+['"]([^'"]+)['"]""",
        src, re.MULTILINE,
    ):
        named, default, star, source = m.group(1), m.group(2), m.group(3), m.group(4)
        if default:
            imports.append(f"{default} from '{source}'")
        elif star:
            imports.append(f"* as {star} from '{source}'")
        elif named:
            names = [n.strip().split(" as ")[-1] for n in named.split(",") if n.strip()]
            imports.append(f"{{{', '.join(names[:4])}}} from '{source}'")

    for m in re.finditer(
        r"""^export\s+(?:default\s+)?(?:async\s+)?(?:function|class|const|let|var|type|interface)\s+(\w+)""",
        src, re.MULTILINE,
    ):
        exports.append(m.group(1))

    for m in re.finditer(
        r"""^(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(""",
        src, re.MULTILINE,
    ):
        functions.append(m.group(1))

    for m in re.finditer(
        r"""^(?:export\s+)?(?:abstract\s+)?class\s+(\w+)""",
        src, re.MULTILINE,
    ):
        classes.append(m.group(1))

    for m in re.finditer(
        r"""^(?:export\s+)?interface\s+(\w+)""",
        src, re.MULTILINE,
    ):
        interfaces.append(m.group(1))

    for m in re.finditer(
        r"""^(?:export\s+)?type\s+(\w+)\s*=""",
        src, re.MULTILINE,
    ):
        types.append(m.group(1))

    parts = []
    if imports:
        parts.append(f"imports: {'; '.join(imports[:6])}" + (" ..." if len(imports) > 6 else ""))
    if exports:
        parts.append(f"exports: {', '.join(exports[:12])}" + (" ..." if len(exports) > 12 else ""))
    if functions:
        parts.append(f"functions: {', '.join(functions[:12])}" + (" ..." if len(functions) > 12 else ""))
    if classes:
        parts.append(f"classes: {', '.join(classes)}")
    if interfaces:
        parts.append(f"interfaces: {', '.join(interfaces[:10])}")
    if types:
        parts.append(f"types: {', '.join(types[:10])}")
    return _schema_block(parts)


def _analyse_json(path: str) -> str:
    """Top-level key listing for JSON files."""
    try:
        src = open(path, encoding="utf-8").read()
        data = json.loads(src)
        if isinstance(data, dict):
            keys = list(data.keys())
            parts = [f"top-level keys: {', '.join(keys[:20])}" + (" ..." if len(keys) > 20 else "")]
            return _schema_block(parts)
        if isinstance(data, list):
            return _schema_block([f"JSON array, {len(data)} items"])
    except Exception:
        pass
    return ""


# ── Symbol range extraction (for read_symbol tool) ────────────────────────────

def extract_symbol_range(path: str, name: str) -> Optional[tuple[int, int]]:
    """Find the line range of a named symbol in a source file.

    Returns ``(start_line_0indexed, end_line_0indexed)`` or ``None``.
    Supports Python (AST) and JS/TS (brace-counting heuristic).
    """
    ext = os.path.splitext(path)[1].lower()
    if ext == ".py":
        return _extract_symbol_python(path, name)
    if ext in (".js", ".ts", ".jsx", ".tsx"):
        return _extract_symbol_js(path, name)
    return None


def _extract_symbol_python(path: str, name: str) -> Optional[tuple[int, int]]:
    try:
        src = open(path, encoding="utf-8").read()
        tree = ast.parse(src, filename=path)
    except Exception:
        return None

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name == name:
                return (node.lineno - 1, (node.end_lineno or node.lineno) - 1)
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if child.name == name or f"{node.name}.{child.name}" == name:
                        return (child.lineno - 1,
                                (child.end_lineno or child.lineno) - 1)
    return None


def _extract_symbol_js(path: str, name: str) -> Optional[tuple[int, int]]:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            src = f.read()
    except Exception:
        return None

    patterns = [
        rf'(?:export\s+)?(?:async\s+)?function\s+{re.escape(name)}\s*\(',
        rf'(?:export\s+)?class\s+{re.escape(name)}\b',
        rf'(?:export\s+)?(?:const|let|var)\s+{re.escape(name)}\s*=',
        rf'(?:export\s+)?interface\s+{re.escape(name)}\b',
        rf'(?:export\s+)?type\s+{re.escape(name)}\s*=',
    ]

    for pattern in patterns:
        m = re.search(pattern, src)
        if not m:
            continue
        start_line = src[:m.start()].count('\n')
        # Find end by brace counting
        rest = src[m.start():]
        depth = 0
        started = False
        for i, ch in enumerate(rest):
            if ch == '{':
                depth += 1
                started = True
            elif ch == '}':
                depth -= 1
                if started and depth == 0:
                    end_line = src[:m.start() + i].count('\n')
                    return (start_line, end_line)
        # No braces — single-line declaration
        semi = rest.find(';')
        if semi >= 0:
            end_line = src[:m.start() + semi].count('\n')
            return (start_line, end_line)
        return (start_line, start_line)

    return None


# ── Proactive review ──────────────────────────────────────────────────────────

def review_file(path: str) -> list[str]:
    """Proactive advisory checks beyond syntax validation.

    Returns a list of human-readable advisory strings (not errors — these
    are suggestions the developer can choose to act on or ignore).
    """
    ext = os.path.splitext(path)[1].lower()
    advisories: list[str] = []

    if ext == ".py":
        advisories.extend(_review_python(path))

    advisories.extend(_review_todos(path))
    return advisories


def _review_python(path: str) -> list[str]:
    advisories: list[str] = []
    try:
        src = open(path, encoding="utf-8").read()
        tree = ast.parse(src, filename=path)
    except Exception:
        return advisories

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.lineno
            end = node.end_lineno or start
            func_len = end - start + 1
            if func_len > 80:
                advisories.append(
                    f"{path}:{start}: '{node.name}' is {func_len} lines — "
                    f"consider breaking it up"
                )
            n_args = len(node.args.args)
            if n_args > 7:
                advisories.append(
                    f"{path}:{start}: '{node.name}' has {n_args} params — "
                    f"consider a config object"
                )
        elif isinstance(node, ast.ExceptHandler):
            if node.type is None:
                advisories.append(
                    f"{path}:{node.lineno}: bare 'except:' — "
                    f"catch specific exceptions"
                )
    return advisories


def _review_todos(path: str) -> list[str]:
    advisories: list[str] = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f, 1):
                for tag in ("TODO", "FIXME", "HACK", "XXX"):
                    if tag in line:
                        clean = line.strip()[:80]
                        advisories.append(f"{path}:{i}: {clean}")
                        break
    except Exception:
        pass
    return advisories
