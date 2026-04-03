"""Thompson Sampling bandit for adaptive workflow selection.

Each task category has a pool of workflow variants (approach strategies).
The bandit samples Beta(α, β) for each arm and picks the highest — over time
it converges on the variant that succeeds most often for each task type.

Priors are stored in the same SQLite DB as episodic memory (episodes.db).
Alpha increments on success, beta on failure. Both start at 1 (uniform prior).
"""

import os
import sqlite3

import numpy as np

_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "episodes.db")

# ── Workflow variant definitions ───────────────────────────────────────────────
# Each variant has:
#   hint        — injected into the system prompt as the suggested approach
#   first_tools — the expected first tool call(s); logged if model deviates

VARIANTS: dict[str, dict[str, dict]] = {
    "edit": {
        "read_edit": {
            "hint": "SUGGESTED APPROACH: Call read_file on the target file first, then edit_file.",
            "first_tools": ["read_file"],
        },
        "search_read_edit": {
            "hint": "SUGGESTED APPROACH: Use search_code to find the relevant section first, then read_file, then edit_file.",
            "first_tools": ["search_code"],
        },
    },
    "debug": {
        "search_read_edit": {
            "hint": "SUGGESTED APPROACH: Search for the error pattern first, read the file, then fix it.",
            "first_tools": ["search_code"],
        },
        "read_run_edit": {
            "hint": "SUGGESTED APPROACH: Read the file first, run it to see the error output, then fix it.",
            "first_tools": ["read_file"],
        },
        "search_run_read_edit": {
            "hint": "SUGGESTED APPROACH: Search for the error, run the code, read the relevant file, then fix.",
            "first_tools": ["search_code"],
        },
    },
    "create": {
        "direct_write": {
            "hint": "SUGGESTED APPROACH: Write the new file directly.",
            "first_tools": ["write_file"],
        },
        "list_write": {
            "hint": "SUGGESTED APPROACH: List the directory structure first to understand context, then write the new file.",
            "first_tools": ["list_files"],
        },
    },
    "question": {
        "answer_direct": {
            "hint": "SUGGESTED APPROACH: Answer directly from the file tree and context — no tool calls needed.",
            "first_tools": [],
        },
        "read_answer": {
            "hint": "SUGGESTED APPROACH: Read the relevant file(s) first, then answer.",
            "first_tools": ["read_file"],
        },
        "search_answer": {
            "hint": "SUGGESTED APPROACH: Search the codebase for relevant patterns, then answer.",
            "first_tools": ["search_code"],
        },
    },
    "run": {
        "run_direct": {
            "hint": "SUGGESTED APPROACH: Run the command directly and report the output.",
            "first_tools": ["run_cmd"],
        },
        "read_run": {
            "hint": "SUGGESTED APPROACH: Read the relevant file first, then run the command.",
            "first_tools": ["read_file"],
        },
    },
}

# ── Task categorisation (deterministic keyword matching) ───────────────────────
_CATEGORY_KEYWORDS: list[tuple[str, list[str]]] = [
    ("debug",    ["fix", "bug", "error", "exception", "traceback", "debug",
                  "crash", "fail", "broken", "TypeError", "AttributeError",
                  "ImportError", "KeyError", "ValueError"]),
    ("create",   ["create", "new file", "write a new", "add a new", "generate",
                  "scaffold", "make a new", "add new"]),
    ("run",      ["run", "execute", "install", "build", "start", "launch",
                  "deploy", "compile", "test"]),
    ("question", ["what", "how", "why", "explain", "show me", "list",
                  "which", "where is", "what is", "describe"]),
    ("edit",     ["edit", "change", "update", "modify", "refactor", "rename",
                  "add", "remove", "replace", "implement", "add the",
                  "delete the"]),
]


def categorise(task: str) -> str:
    lower = task.lower()
    for category, keywords in _CATEGORY_KEYWORDS:
        if any(kw in lower for kw in keywords):
            return category
    return "edit"  # safe default


# ── Database helpers ───────────────────────────────────────────────────────────

def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_DB_PATH)
    c.execute("""
        CREATE TABLE IF NOT EXISTS bandit_arms (
            category   TEXT NOT NULL,
            variant_id TEXT NOT NULL,
            alpha      REAL NOT NULL DEFAULT 1.0,
            beta       REAL NOT NULL DEFAULT 1.0,
            PRIMARY KEY (category, variant_id)
        )
    """)
    c.commit()
    return c


def _ensure_arms(conn: sqlite3.Connection, category: str) -> None:
    """Insert rows for any variant that doesn't exist yet (uniform prior α=β=1)."""
    for vid in VARIANTS.get(category, {}):
        conn.execute(
            "INSERT OR IGNORE INTO bandit_arms (category, variant_id, alpha, beta) "
            "VALUES (?, ?, 1.0, 1.0)",
            (category, vid),
        )
    conn.commit()


# ── Public API ─────────────────────────────────────────────────────────────────

def select_variant(task: str) -> tuple[str, str, dict]:
    """Choose a workflow variant for this task using Thompson Sampling.

    Returns (category, variant_id, variant_def).
    """
    category = categorise(task)
    variants = VARIANTS.get(category, {})
    if not variants:
        return category, "default", {"hint": "", "first_tools": []}

    conn = _conn()
    _ensure_arms(conn, category)
    rows = conn.execute(
        "SELECT variant_id, alpha, beta FROM bandit_arms WHERE category = ?",
        (category,),
    ).fetchall()
    conn.close()

    # Thompson sampling: draw from Beta(α, β) for each arm
    rng = np.random.default_rng()
    best_vid, best_score = None, -1.0
    for vid, alpha, beta in rows:
        if vid not in variants:
            continue  # stale row from a removed variant
        score = float(rng.beta(alpha, beta))
        if score > best_score:
            best_score, best_vid = score, vid

    if best_vid is None:
        best_vid = next(iter(variants))

    return category, best_vid, variants[best_vid]


def update_bandit(category: str, variant_id: str, success: bool) -> None:
    """Update Beta priors after observing an outcome."""
    conn = _conn()
    _ensure_arms(conn, category)
    if success:
        conn.execute(
            "UPDATE bandit_arms SET alpha = alpha + 1 WHERE category = ? AND variant_id = ?",
            (category, variant_id),
        )
    else:
        conn.execute(
            "UPDATE bandit_arms SET beta = beta + 1 WHERE category = ? AND variant_id = ?",
            (category, variant_id),
        )
    conn.commit()
    conn.close()


def arm_stats() -> dict[str, list[dict]]:
    """Return current α/β for all arms (for diagnostics / /bandit command)."""
    try:
        conn = _conn()
        rows = conn.execute(
            "SELECT category, variant_id, alpha, beta FROM bandit_arms ORDER BY category, variant_id"
        ).fetchall()
        conn.close()
        stats: dict[str, list[dict]] = {}
        for cat, vid, alpha, beta in rows:
            stats.setdefault(cat, []).append({
                "variant": vid,
                "alpha": round(alpha, 1),
                "beta": round(beta, 1),
                "win_rate": round(alpha / (alpha + beta), 3),
            })
        return stats
    except Exception:
        return {}
