from __future__ import annotations

import ast
from pathlib import Path


BANNED_TERMS = (
    "valence",
    "arousal",
    "clarity",
    "burnout_proximity",
    "mood_drift",
    "case_based",
    "fingerprint",
    "situation_type",
)


def test_runtime_code_avoids_deprecated_hand_written_psychology_features():
    repo_root = Path(__file__).resolve().parents[1]
    runtime_py = sorted((repo_root / "caden").rglob("*.py"))

    violations: list[str] = []
    for path in runtime_py:
        text = path.read_text(encoding="utf-8").lower()
        for term in BANNED_TERMS:
            if term in text:
                violations.append(f"{path.relative_to(repo_root)} contains banned term: {term}")

    assert not violations, "\n".join(violations)


def test_cmd_021_runtime_codebase_avoids_non_python_language_sources():
    repo_root = Path(__file__).resolve().parents[1]
    runtime_root = repo_root / "caden"
    disallowed = {".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs", ".cpp", ".c", ".cs", ".swift", ".kt", ".php", ".rb"}

    violations: list[str] = []
    for path in runtime_root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() in disallowed:
            violations.append(str(path.relative_to(repo_root)))

    assert not violations, "\n".join(violations)


def test_cmd_016_generic_operational_policy_helpers_are_sean_agnostic():
    repo_root = Path(__file__).resolve().parents[1]
    targets = {
        repo_root / "caden" / "ui" / "dashboard.py": "day_window_utc",
        repo_root / "caden" / "libbie" / "retrieve.py": "_length_penalty",
    }

    banned_terms = (
        "sean",
        "mood",
        "energy",
        "productivity",
        "burnout",
        "phase",
    )

    violations: list[str] = []
    for path, fn_name in targets.items():
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        fn_nodes = [
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == fn_name
        ]
        if not fn_nodes:
            violations.append(f"missing function {fn_name} in {path.relative_to(repo_root)}")
            continue

        fn_source = (ast.get_source_segment(source, fn_nodes[0]) or "").lower()
        for term in banned_terms:
            if term in fn_source:
                violations.append(
                    f"{path.relative_to(repo_root)}::{fn_name} contains non-generic term: {term}"
                )

    assert not violations, "\n".join(violations)
