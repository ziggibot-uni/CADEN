"""Episodic memory for VibeCoder.

Enhanced version of CodingCLI's memory with:
  - Same episode recording + retrieval
  - Integration with CADEN's lessons system
  - Lesson extraction after each task (fills out the JSON form)
"""

import json
import os
import re
import sqlite3
import struct
import time
from typing import List, Optional

import numpy as np

# ── Config ────────────────────────────────────────────────────────────────────
_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "episodes.db")
_EMBED_MODEL = "nomic-embed-text"
_EMBED_URL = "http://localhost:11434/api/embed"
_TOP_K = 3
_MIN_SIMILARITY = 0.30
_MAX_EPISODES_INJECTED = 3

# ── Database ──────────────────────────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS episodes (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            task          TEXT    NOT NULL,
            tool_sequence TEXT    NOT NULL,
            outcome       TEXT    NOT NULL,
            embedding     BLOB,
            timestamp     REAL    NOT NULL
        )
    """)
    conn.commit()
    return conn


# ── Embedding ─────────────────────────────────────────────────────────────────

_embed_available: Optional[bool] = None
_embed_fail_time: float = 0.0
_EMBED_RETRY_INTERVAL = 120.0  # retry Ollama every 2 minutes

def _try_embed(text: str) -> Optional[np.ndarray]:
    global _embed_available, _embed_fail_time
    if _embed_available is False:
        if time.time() - _embed_fail_time < _EMBED_RETRY_INTERVAL:
            return None
        _embed_available = None  # allow retry
    try:
        import requests
        res = requests.post(
            _EMBED_URL,
            json={"model": _EMBED_MODEL, "input": text},
            timeout=10,
        )
        res.raise_for_status()
        vec = res.json().get("embeddings", [[]])[0]
        if not vec:
            _embed_available = False
            return None
        _embed_available = True
        return np.array(vec, dtype=np.float32)
    except Exception:
        _embed_available = False
        _embed_fail_time = time.time()
        return None


def _bow_embed(text: str, vocab: List[str]) -> np.ndarray:
    tokens = set(re.split(r"\W+", text.lower()))
    vec = np.array([1.0 if w in tokens else 0.0 for w in vocab], dtype=np.float32)
    norm = np.linalg.norm(vec)
    return vec / norm if norm > 0 else vec


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def _pack(arr: np.ndarray) -> bytes:
    return struct.pack(f"{len(arr)}f", *arr.tolist())


def _unpack(blob: bytes) -> np.ndarray:
    n = len(blob) // 4
    return np.array(struct.unpack(f"{n}f", blob), dtype=np.float32)


# ── Public API ────────────────────────────────────────────────────────────────

def record_episode(task: str, tool_sequence: list, outcome: str) -> None:
    vec = _try_embed(task)
    blob = _pack(vec) if vec is not None else None

    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO episodes (task, tool_sequence, outcome, embedding, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            (task, json.dumps(tool_sequence), outcome, blob, time.time()),
        )
        conn.commit()
    finally:
        conn.close()


def record_episode_with_lessons(task: str, tool_sequence: list, outcome: str) -> None:
    """Record episode AND extract + store structured lessons."""
    record_episode(task, tool_sequence, outcome)

    # Extract lessons via model self-reflection
    try:
        from model import extract_lessons
        from caden_bridge import record_lesson

        steps_summary = ", ".join(
            f"{s.get('tool', '?')}({s.get('args_summary', '')})"
            for s in tool_sequence[:10]
        )
        lessons = extract_lessons(task, outcome, steps_summary)

        record_lesson(
            task=task,
            outcome=outcome,
            mistakes=lessons.get("mistakes", []),
            what_worked=lessons.get("what_worked", []),
            key_facts=lessons.get("key_facts", []),
            context=steps_summary,
        )
    except Exception:
        pass  # never crash the agent over lesson extraction


def retrieve_similar(task: str) -> List[dict]:
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT task, tool_sequence, embedding FROM episodes WHERE outcome = 'success'"
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return []

    query_vec = _try_embed(task)
    use_semantic = query_vec is not None

    vocab: list = []
    if not use_semantic:
        all_texts = [task] + [r[0] for r in rows]
        vocab[:] = sorted(set(
            w for t in all_texts for w in re.split(r"\W+", t.lower()) if len(w) > 2
        ))
        query_vec = _bow_embed(task, vocab)

    scored = []
    for row_task, row_seq_json, row_blob in rows:
        if use_semantic and row_blob:
            row_vec = _unpack(row_blob)
        elif use_semantic:
            continue
        else:
            row_vec = _bow_embed(row_task, vocab)

        sim = _cosine(query_vec, row_vec)
        if sim >= _MIN_SIMILARITY:
            scored.append((sim, row_task, json.loads(row_seq_json)))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        {"task": t, "tool_sequence": seq, "similarity": round(sim, 3)}
        for sim, t, seq in scored[:_TOP_K]
    ]


def format_few_shot(episodes: List[dict]) -> str:
    if not episodes:
        return ""
    lines = ["─── Similar past tasks (for reference) ───────────────────────"]
    for i, ep in enumerate(episodes[:_MAX_EPISODES_INJECTED], 1):
        lines.append(f"Example {i} (similarity {ep['similarity']:.2f}):")
        lines.append(f"  Task: {ep['task'][:120]}")
        lines.append("  Steps that worked:")
        for j, step in enumerate(ep["tool_sequence"][:8], 1):
            lines.append(f"    {j}. {step.get('tool', '?')}({step.get('args_summary', '')})")
        lines.append("")
    lines.append("──────────────────────────────────────────────────────────")
    return "\n".join(lines)


def episode_count() -> int:
    try:
        conn = _get_conn()
        try:
            n = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
        finally:
            conn.close()
        return n
    except Exception:
        return 0
