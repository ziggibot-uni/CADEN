"""Bridge to CADEN's knowledge systems.

Provides VibeCoder access to:
  - Past project entries (decisions, blockers, updates)
  - Thought dump entries (brain dumps, reflections)
  - Lessons learned (structured mistake/success records)
  - Training data statistics

All data is read from CADEN's SQLite DB. If the DB isn't available
(standalone CLI mode), gracefully returns empty results.
"""

import json
import os
import sqlite3
import struct
import time
from pathlib import Path
from typing import List, Optional

import numpy as np


# ── DB connection ─────────────────────────────────────────────────────────────

def _find_caden_db() -> Optional[Path]:
    candidates = [
        Path(os.environ.get("APPDATA", "")) / "com.caden.app" / "caden.db",
        Path(os.environ.get("LOCALAPPDATA", "")) / "com.caden.app" / "caden.db",
        Path.home() / "AppData" / "Roaming" / "com.caden.app" / "caden.db",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


_CADEN_DB: Optional[Path] = _find_caden_db()

# Local lessons DB (always available, even without CADEN)
_LESSONS_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lessons.db")


def _caden_conn() -> Optional[sqlite3.Connection]:
    if _CADEN_DB and _CADEN_DB.exists():
        try:
            return sqlite3.connect(str(_CADEN_DB))
        except Exception:
            return None
    return None


def _lessons_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_LESSONS_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS lessons (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            task        TEXT NOT NULL,
            outcome     TEXT NOT NULL,
            mistakes    TEXT NOT NULL DEFAULT '[]',
            what_worked TEXT NOT NULL DEFAULT '[]',
            key_facts   TEXT NOT NULL DEFAULT '[]',
            context     TEXT NOT NULL DEFAULT '',
            embedding   BLOB,
            created_at  REAL NOT NULL
        )
    """)
    conn.commit()
    return conn


# ── Embedding helpers ─────────────────────────────────────────────────────────

_embed_available: Optional[bool] = None
_embed_fail_time: float = 0.0
_EMBED_RETRY_INTERVAL = 120.0  # retry Ollama every 2 minutes


def _try_embed(text: str) -> Optional[np.ndarray]:
    global _embed_available, _embed_fail_time
    if _embed_available is False:
        import time as _t
        if _t.time() - _embed_fail_time < _EMBED_RETRY_INTERVAL:
            return None
        _embed_available = None  # allow retry
    try:
        import requests
        res = requests.post(
            "http://localhost:11434/api/embed",
            json={"model": "nomic-embed-text", "input": text},
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
        import time as _t
        _embed_available = False
        _embed_fail_time = _t.time()
        return None


def _pack(arr: np.ndarray) -> bytes:
    return struct.pack(f"{len(arr)}f", *arr.tolist())


def _unpack(blob: bytes) -> np.ndarray:
    n = len(blob) // 4
    return np.array(struct.unpack(f"{n}f", blob), dtype=np.float32)


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


# ── Lessons: record and retrieve ──────────────────────────────────────────────

def record_lesson(
    task: str,
    outcome: str,
    mistakes: list,
    what_worked: list,
    key_facts: list,
    context: str = "",
):
    """Record a structured lesson after a task completes.

    This is the 'JSON form' that CADEN fills out after each coding task:
      - mistakes:    things that went wrong
      - what_worked: approaches that succeeded
      - key_facts:   small discoveries (API quirks, config gotchas, etc.)
    """
    vec = _try_embed(task)
    blob = _pack(vec) if vec is not None else None

    conn = _lessons_conn()
    try:
        conn.execute(
            "INSERT INTO lessons (task, outcome, mistakes, what_worked, key_facts, context, embedding, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                task, outcome,
                json.dumps(mistakes), json.dumps(what_worked), json.dumps(key_facts),
                context, blob, time.time(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def retrieve_lessons(task: str, top_k: int = 5, min_sim: float = 0.25) -> List[dict]:
    """Vector search for lessons relevant to the current task.

    Returns lessons with:
      - things to avoid (past mistakes)
      - things to be inspired by (past successes)
      - key facts that might help
    """
    conn = _lessons_conn()
    try:
        rows = conn.execute(
            "SELECT task, outcome, mistakes, what_worked, key_facts, embedding "
            "FROM lessons ORDER BY created_at DESC"
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return []

    query_vec = _try_embed(task)
    use_semantic = query_vec is not None

    vocab: list = []

    def _bow(text: str):
        import re as _re
        tokens = set(_re.split(r"\W+", text.lower()))
        vec = np.array([1.0 if w in tokens else 0.0 for w in vocab], dtype=np.float32)
        norm = np.linalg.norm(vec)
        return vec / norm if norm > 0 else vec

    if not use_semantic:
        # BOW fallback
        import re
        all_texts = [task] + [r[0] for r in rows]
        vocab[:] = sorted(set(
            w for t in all_texts for w in re.split(r"\W+", t.lower()) if len(w) > 2
        ))
        query_vec = _bow(task)

    scored = []
    for row_task, outcome, mistakes_json, worked_json, facts_json, blob in rows:
        if use_semantic and blob:
            row_vec = _unpack(blob)
        elif use_semantic:
            continue
        else:
            row_vec = _bow(row_task)

        sim = _cosine(query_vec, row_vec)
        if sim >= min_sim:
            scored.append({
                "task": row_task,
                "outcome": outcome,
                "mistakes": json.loads(mistakes_json) if mistakes_json else [],
                "what_worked": json.loads(worked_json) if worked_json else [],
                "key_facts": json.loads(facts_json) if facts_json else [],
                "similarity": round(sim, 3),
            })

    scored.sort(key=lambda x: x["similarity"], reverse=True)
    return scored[:top_k]


def format_lessons_context(lessons: List[dict]) -> str:
    """Format retrieved lessons as a context block for the agent prompt."""
    if not lessons:
        return ""

    lines = ["─── Lessons from past tasks ────────────────────────────────"]

    avoid_items = []
    inspire_items = []
    fact_items = []

    for lesson in lessons:
        sim = lesson["similarity"]
        task_preview = lesson["task"][:100]

        for mistake in lesson["mistakes"]:
            avoid_items.append(f"  ✗ ({sim:.2f}) {mistake}")

        for win in lesson["what_worked"]:
            inspire_items.append(f"  ✓ ({sim:.2f}) {win}")

        for fact in lesson["key_facts"]:
            fact_items.append(f"  • ({sim:.2f}) {fact}")

    if avoid_items:
        lines.append("\nTHINGS TO AVOID (past mistakes):")
        lines.extend(avoid_items[:8])

    if inspire_items:
        lines.append("\nAPPROACHES THAT WORKED:")
        lines.extend(inspire_items[:8])

    if fact_items:
        lines.append("\nKEY FACTS:")
        lines.extend(fact_items[:8])

    lines.append("──────────────────────────────────────────────────────────")
    return "\n".join(lines)


# ── Research cache ────────────────────────────────────────────────────────────
# Persistent knowledge library of web research findings with TTL-based staleness.
# Lives in the same local lessons.db so it's always available even without CADEN.

def _ensure_research_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS research_cache (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            topic       TEXT    NOT NULL,
            query_used  TEXT    NOT NULL,
            urls        TEXT    NOT NULL DEFAULT '[]',
            findings    TEXT    NOT NULL,
            embedding   BLOB,
            created_at  REAL    NOT NULL,
            verified_at REAL    NOT NULL,
            stale_days  INTEGER NOT NULL DEFAULT 7
        )
    """)
    conn.commit()


def cache_research(
    topic: str,
    query_used: str,
    urls: list,
    findings: str,
    stale_days: int = 7,
) -> None:
    """Store a research finding in the knowledge library."""
    vec = _try_embed(topic)
    blob = _pack(vec) if vec is not None else None
    now = time.time()
    conn = _lessons_conn()
    try:
        _ensure_research_table(conn)
        conn.execute(
            "INSERT INTO research_cache (topic, query_used, urls, findings, embedding, created_at, verified_at, stale_days) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (topic, query_used, json.dumps(urls), findings, blob, now, now, stale_days),
        )
        conn.commit()
    finally:
        conn.close()


def _score_research_rows(task: str, rows: list) -> list:
    """Score research_cache rows by cosine similarity to task. Returns list of (sim, row) tuples."""
    query_vec = _try_embed(task)
    use_semantic = query_vec is not None

    vocab: list = []
    if not use_semantic:
        import re
        all_texts = [task] + [r[0] for r in rows]
        vocab[:] = sorted(set(
            w for t in all_texts for w in re.split(r"\W+", t.lower()) if len(w) > 2
        ))

    def _bow_local(text: str) -> np.ndarray:
        import re as _re
        tokens = set(_re.split(r"\W+", text.lower()))
        vec = np.array([1.0 if w in tokens else 0.0 for w in vocab], dtype=np.float32)
        norm = np.linalg.norm(vec)
        return vec / norm if norm > 0 else vec

    if not use_semantic:
        query_vec = _bow_local(task)

    scored = []
    for row in rows:
        topic_text, query_used, urls_json, findings, blob, created_at, verified_at, stale_days = row
        if use_semantic and blob:
            row_vec = _unpack(blob)
        elif use_semantic:
            continue
        else:
            row_vec = _bow_local(topic_text)

        sim = _cosine(query_vec, row_vec)
        scored.append((sim, {
            "topic": topic_text,
            "query_used": query_used,
            "urls": json.loads(urls_json) if urls_json else [],
            "findings": findings,
            "created_at": created_at,
            "verified_at": verified_at,
            "stale_days": stale_days,
            "similarity": round(sim, 3),
        }))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored


def lookup_research(task: str, top_k: int = 5, min_sim: float = 0.35) -> List[dict]:
    """Vector search for fresh (non-stale) research relevant to the task."""
    conn = _lessons_conn()
    try:
        _ensure_research_table(conn)
        rows = conn.execute(
            "SELECT topic, query_used, urls, findings, embedding, created_at, verified_at, stale_days "
            "FROM research_cache ORDER BY verified_at DESC"
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return []

    now = time.time()
    scored = _score_research_rows(task, rows)
    fresh = [
        entry for sim, entry in scored
        if sim >= min_sim and (now - entry["verified_at"]) < entry["stale_days"] * 86400
    ]
    return fresh[:top_k]


def get_stale_entries(task: str, top_k: int = 5, min_sim: float = 0.35) -> List[dict]:
    """Return research entries that match the task but have exceeded their TTL."""
    conn = _lessons_conn()
    try:
        _ensure_research_table(conn)
        rows = conn.execute(
            "SELECT topic, query_used, urls, findings, embedding, created_at, verified_at, stale_days "
            "FROM research_cache ORDER BY verified_at DESC"
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return []

    now = time.time()
    scored = _score_research_rows(task, rows)
    stale = [
        entry for sim, entry in scored
        if sim >= min_sim and (now - entry["verified_at"]) >= entry["stale_days"] * 86400
    ]
    return stale[:top_k]


def format_research_context(entries: List[dict]) -> str:
    """Format research cache entries for injection into the coder's context block."""
    if not entries:
        return ""
    lines = ["─── Verified research findings ─────────────────────────────"]
    for entry in entries:
        age_hours = int((time.time() - entry["verified_at"]) / 3600)
        age_str = f"{age_hours}h ago" if age_hours < 48 else f"{age_hours // 24}d ago"
        lines.append(f"\n• {entry['topic']} (verified {age_str}, sim={entry['similarity']:.2f})")
        lines.append(f"  {entry['findings']}")
        if entry.get("urls"):
            for url in entry["urls"][:2]:
                lines.append(f"  Source: {url}")
    lines.append("\n──────────────────────────────────────────────────────────")
    return "\n".join(lines)


# ── CADEN project/thought access ─────────────────────────────────────────────

def get_relevant_projects(query: str, limit: int = 3) -> List[dict]:
    """Search CADEN's projects for relevant context."""
    conn = _caden_conn()
    if not conn:
        return []

    try:
        # Get projects with recent entries
        projects = conn.execute(
            "SELECT id, name, description FROM projects ORDER BY updated_at DESC LIMIT 20"
        ).fetchall()

        results = []
        query_lower = query.lower()
        for pid, name, desc in projects:
            if query_lower in (name or "").lower() or query_lower in (desc or "").lower():
                entries = conn.execute(
                    "SELECT entry_type, content FROM project_entries "
                    "WHERE project_id = ? ORDER BY created_at DESC LIMIT 5",
                    (pid,),
                ).fetchall()
                results.append({
                    "name": name,
                    "description": desc,
                    "entries": [{"type": t, "content": c[:200]} for t, c in entries],
                })
                if len(results) >= limit:
                    break
        return results
    except Exception:
        return []
    finally:
        conn.close()


def search_thoughts(query: str, limit: int = 5) -> List[str]:
    """Search CADEN's thought dump for relevant entries.

    Uses the embeddings in chat_log if available, otherwise falls back
    to simple text matching.
    """
    conn = _caden_conn()
    if not conn:
        return []

    try:
        # Simple keyword search (embedding search would need the vector)
        rows = conn.execute(
            "SELECT content FROM chat_log WHERE role = 'user' "
            "AND content LIKE ? ORDER BY created_at DESC LIMIT ?",
            (f"%{query}%", limit),
        ).fetchall()
        return [r[0] for r in rows if r[0]]
    except Exception:
        return []
    finally:
        conn.close()


def lesson_count() -> int:
    try:
        conn = _lessons_conn()
        n = conn.execute("SELECT COUNT(*) FROM lessons").fetchone()[0]
        conn.close()
        return n
    except Exception:
        return 0


# ── CADEN chat_log + factor_snapshots integration ────────────────────────────
# Mirrors the Rust dashboard pipeline so AppBuilder chats flow into the same
# tables — chat_log (with embedding), factor_snapshots (mood/energy/anxiety),
# and daily_state (session tracking).

import uuid as _uuid
from datetime import datetime as _dt, timezone as _tz

_MOOD_SIGNAL_WORDS = [
    "feel", "feeling", "felt", "mood", "energy", "tired", "exhausted",
    "anxious", "anxiety", "stressed", "depressed", "depressing", "sad",
    "happy", "excited", "motivated", "unmotivated", "overwhelmed",
    "calm", "wired", "crashed", "crash", "racing", "foggy", "focus",
    "sleep", "slept", "insomnia", "awake", "woke", "nap",
    "bad day", "good day", "rough", "great", "awful", "numb",
    "manic", "low", "high", "hyper", "flat",
]


def log_chat_to_caden(content: str) -> None:
    """Write a user message + its embedding into CADEN's chat_log table.

    Same schema the Rust backend uses so the Sean Model sees AppBuilder
    conversations too.
    """
    conn = _caden_conn()
    if not conn:
        return
    try:
        row_id = str(_uuid.uuid4())
        ts = _dt.now(_tz.utc).isoformat()
        vec = _try_embed(content)
        blob = _pack(vec) if vec is not None else None
        conn.execute(
            "INSERT OR IGNORE INTO chat_log (id, content, embedding, timestamp) "
            "VALUES (?, ?, ?, ?)",
            (row_id, content, blob, ts),
        )
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def extract_and_store_mood(content: str) -> None:
    """Run the same mood/energy extraction the dashboard uses and write
    to factor_snapshots.  Only fires when the message contains signal words.

    Uses the same extraction prompt and schema as state_engine/mod.rs so
    the Insights panel picks up AppBuilder mood data automatically.
    """
    lower = content.lower()
    if not any(w in lower for w in _MOOD_SIGNAL_WORDS):
        return

    conn = _caden_conn()
    if not conn:
        return

    # Build the same prompt the Rust state_engine uses
    safe_msg = content.replace('"', "'")
    prompt = (
        "You are a silent clinical state analyst. The user does not know you "
        "are analyzing this message and will never see your output.\n\n"
        "Analyze the following message for behavioral and mood signals. "
        "Return ONLY a valid JSON object — no markdown fences, no explanation, "
        "no extra text.\n\n"
        f'Message: "{safe_msg}"\n\n'
        "Return exactly this JSON structure (use null for fields with "
        "insufficient evidence):\n"
        "{\n"
        '  "mood_score": <1-10 where 1=severely depressed, 5=neutral, '
        "10=extremely elevated — null if uninferable>,\n"
        '  "energy_level": <1-10 where 1=barely functional, 5=normal, '
        "10=racing/can't stop — null if uninferable>,\n"
        '  "anxiety_level": <1-10 where 1=none, 5=moderate, 10=severe '
        "— null if uninferable>,\n"
        '  "sleep_hours_implied": <hours of sleep mentioned or implied '
        "— null if not mentioned>,\n"
        '  "thought_coherence": <"fragmented"|"normal"|"racing" '
        "— null if uninferable>,\n"
        '  "temporal_focus": <"past"|"present"|"future"|"mixed" '
        "— null if uninferable>,\n"
        '  "emotional_valence": <"negative"|"neutral"|"positive"|"mixed" '
        "— null if uninferable>,\n"
        '  "ideation_pressure": <true if pressured/fast/unstoppable thinking, '
        "false, or null>,\n"
        '  "state_confidence": <0.0-1.0 — short/casual messages = 0.1, '
        "rich emotional content = 0.7+>,\n"
        '  "notes": "<1 sentence of key reasoning — null if nothing notable>"\n'
        "}\n\n"
        "Base your analysis ONLY on explicit linguistic evidence in the message. "
        "Never fabricate signals. Short task-focused messages should have "
        "state_confidence below 0.3."
    )

    try:
        from model import _call
        resp = _call(
            [{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=256,
            ex_type=None,
        )
        raw = resp.get("content", "")
        clean = raw.strip().strip("`").lstrip("json").strip()
        ext = json.loads(clean)
    except Exception:
        conn.close()
        return

    confidence = ext.get("state_confidence") or 0.0
    if confidence < 0.3:
        conn.close()
        return

    try:
        row_id = str(_uuid.uuid4())
        now_ts = int(time.time())
        conn.execute(
            "INSERT INTO factor_snapshots "
            "(id, timestamp, source, mood_score, energy_level, anxiety_level, "
            "thought_coherence, temporal_focus, valence, sleep_hours_implied, "
            "confidence, raw_notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row_id,
                now_ts,
                "appbuilder_nlp",
                ext.get("mood_score"),
                ext.get("energy_level"),
                ext.get("anxiety_level"),
                ext.get("thought_coherence"),
                ext.get("temporal_focus"),
                ext.get("emotional_valence"),
                ext.get("sleep_hours_implied"),
                confidence,
                ext.get("notes"),
            ),
        )
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def record_appbuilder_session(message_len: int) -> None:
    """Update daily_state exactly like the Rust record_session_event does."""
    conn = _caden_conn()
    if not conn:
        return
    try:
        today = _dt.now().strftime("%Y-%m-%d")
        wake_time = _dt.now().strftime("%H:%M")
        now_ts = int(time.time())

        row = conn.execute(
            "SELECT wake_time, output_volume, session_count FROM daily_state "
            "WHERE date = ?",
            (today,),
        ).fetchone()
        prev_wake, prev_vol, prev_sess = row if row else (None, 0, 0)

        wt = prev_wake or wake_time
        new_vol = prev_vol + message_len

        # Check if >30 min gap since last factor snapshot → new session
        last_ts_row = conn.execute(
            "SELECT MAX(timestamp) FROM factor_snapshots WHERE timestamp > ?",
            (now_ts - 3600,),
        ).fetchone()
        gap = (now_ts - (last_ts_row[0] or 0)) // 60 if last_ts_row and last_ts_row[0] else 999
        new_sess = prev_sess + 1 if prev_sess == 0 or gap > 30 else prev_sess

        conn.execute(
            "INSERT INTO daily_state (date, wake_time, output_volume, session_count) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(date) DO UPDATE SET "
            "  wake_time = COALESCE(daily_state.wake_time, excluded.wake_time), "
            "  output_volume = excluded.output_volume, "
            "  session_count = excluded.session_count",
            (today, wt, new_vol, new_sess),
        )
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()
