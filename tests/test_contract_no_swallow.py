from __future__ import annotations

import ast
from pathlib import Path


def _exception_type_name(node: ast.expr | None) -> str:
    if node is None:
        return "<bare>"
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _exception_type_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Tuple):
        return "(" + ", ".join(_exception_type_name(elt) for elt in node.elts) + ")"
    return ast.unparse(node)


def _is_default_like_return(value: ast.expr | None) -> bool:
    if value is None:
        return True
    if isinstance(value, ast.Constant):
        return value.value in (None, "")
    if isinstance(value, (ast.List, ast.Tuple, ast.Set)):
        return len(value.elts) == 0
    if isinstance(value, ast.Dict):
        return len(value.keys) == 0
    return False


def _collect_silent_default_return_handlers(path: Path, tree: ast.AST) -> set[str]:
    found: set[str] = set()
    signal_calls = {
        "notify",
        "bell",
        "update",
        "set_body_text",
        "_set_status",
        "_append",
        "_set_rater_status",
        "error",
        "exception",
        "warning",
    }

    def walk(node: ast.AST, scope: list[str]) -> None:
        next_scope = scope
        if isinstance(node, ast.ClassDef):
            next_scope = [*scope, node.name]
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            next_scope = [*scope, node.name]

        if isinstance(node, ast.Try):
            for handler in node.handlers:
                has_raise = any(isinstance(n, ast.Raise) for n in ast.walk(handler))
                if has_raise:
                    continue
                has_default_return = any(
                    isinstance(n, ast.Return) and _is_default_like_return(n.value)
                    for n in ast.walk(handler)
                )
                if not has_default_return:
                    continue
                has_signal = False
                for n in ast.walk(handler):
                    if not isinstance(n, ast.Call):
                        continue
                    fn = n.func
                    name = None
                    if isinstance(fn, ast.Name):
                        name = fn.id
                    elif isinstance(fn, ast.Attribute):
                        name = fn.attr
                    if name in signal_calls:
                        has_signal = True
                        break
                if has_signal:
                    continue
                qualname = ".".join(next_scope) if next_scope else "<module>"
                key = f"{path.as_posix()}::{qualname}::{_exception_type_name(handler.type)}"
                found.add(key)

        for child in ast.iter_child_nodes(node):
            walk(child, next_scope)

    walk(tree, [])
    return found


def test_codebase_avoids_bare_except_and_except_pass_patterns():
    repo_root = Path(__file__).resolve().parents[1]
    py_files = sorted((repo_root / "caden").rglob("*.py"))

    violations: list[str] = []
    for path in py_files:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            if node.type is None:
                violations.append(f"{path.relative_to(repo_root)}:{node.lineno}: bare except")
            if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                violations.append(f"{path.relative_to(repo_root)}:{node.lineno}: except-pass")

    assert not violations, "\n".join(violations)


def test_cmd_022_023_silent_default_exception_fallbacks_are_explicitly_allowlisted():
    repo_root = Path(__file__).resolve().parents[1]
    py_files = sorted((repo_root / "caden").rglob("*.py"))

    # Exhaustive inventory of handlers that intentionally return a default
    # value from an exception path. Any new handler must be reviewed.
    allowed = {
        "caden/google_sync/calendar.py::_parse_time::ValueError",
        "caden/google_sync/tasks.py::_parse::ValueError",
        "caden/libbie/store.py::_safe_json::json.JSONDecodeError",
        "caden/log.py::make_libbie_event_sink._sink::Exception",
        "caden/ui/app.py::CadenApp._update_clock::NoMatches",
        "caden/ui/chat.py::ChatWidget._hide_thinking_box::NoMatches",
        "caden/ui/chat.py::ChatWidget._rater_consumer::asyncio.CancelledError",
        "caden/ui/chat.py::ChatWidget._show_thinking_box::NoMatches",
        "caden/ui/chat.py::ChatWidget._set_rater_status::NoMatches",
    }

    observed: set[str] = set()
    for path in py_files:
        rel = path.relative_to(repo_root)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        observed |= _collect_silent_default_return_handlers(rel, tree)

    unexpected = sorted(observed - allowed)
    missing = sorted(allowed - observed)
    details: list[str] = []
    if unexpected:
        details.append("Unexpected silent default-return handlers:")
        details.extend(unexpected)
    if missing:
        details.append("Allowlist entries not found (update stale expectations):")
        details.extend(missing)

    assert not details, "\n".join(details)
