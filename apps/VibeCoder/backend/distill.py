"""Distillation logger for VibeCoder.

Every response from the teacher model (Llama-3.3-70B-Instruct) is recorded
so it can be used to fine-tune a smaller student model (Qwen2.5-7B + QLoRA).

Two storage backends:
  1. CADEN's SQLite DB (training_data table) — integrates with existing pipeline
  2. Local JSONL fallback — when the DB isn't accessible (standalone CLI mode)

The distillation data uses the same ShareGPT format as CADEN's training system:
  {"conversations": [{"from": "system/human/gpt", "value": "..."}], "type": "vibecoder_*"}
"""

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Optional


# ── Locate CADEN DB ──────────────────────────────────────────────────────────

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
_FALLBACK_JSONL = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "distill_log.jsonl"
)

# ── Ensure training_data table exists ─────────────────────────────────────────

def _ensure_table(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS training_data (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            ex_type      TEXT NOT NULL,
            system_prompt TEXT,
            user_prompt  TEXT NOT NULL,
            completion   TEXT NOT NULL,
            model        TEXT NOT NULL DEFAULT '',
            created_at   TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    # Add conversations_json column for multi-turn chains (idempotent)
    try:
        conn.execute("ALTER TABLE training_data ADD COLUMN conversations_json TEXT")
    except sqlite3.OperationalError:
        pass  # column already exists
    conn.commit()


# ── Public API ────────────────────────────────────────────────────────────────

def log_distillation(
    ex_type: str,
    system_prompt: Optional[str],
    user_prompt: str,
    completion: str,
    model: str = "llama3.3:70b-instruct",
):
    """Record a teacher model output for future fine-tuning.

    ex_type should be one of:
      vibecoder_orchestrate, vibecoder_plan, vibecoder_code, vibecoder_critic
    """
    if not completion or not user_prompt:
        return

    # Try CADEN's DB first
    if _CADEN_DB and _CADEN_DB.exists():
        try:
            conn = sqlite3.connect(str(_CADEN_DB))
            _ensure_table(conn)
            conn.execute(
                "INSERT INTO training_data (ex_type, system_prompt, user_prompt, completion, model) "
                "VALUES (?, ?, ?, ?, ?)",
                (ex_type, system_prompt or "", user_prompt, completion, model),
            )
            conn.commit()
            conn.close()
            return
        except Exception:
            pass  # fall through to JSONL

    # Fallback: append to local JSONL
    conversations = []
    if system_prompt:
        conversations.append({"from": "system", "value": system_prompt})
    conversations.append({"from": "human", "value": user_prompt})
    conversations.append({"from": "gpt", "value": completion})

    record = {
        "conversations": conversations,
        "type": ex_type,
        "model": model,
        "timestamp": time.time(),
    }
    try:
        with open(_FALLBACK_JSONL, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass  # never crash the agent over logging


def log_distillation_multiturn(
    ex_type: str,
    conversations: list,
    model: str = "llama3.3:70b-instruct",
):
    """Record a multi-turn conversation chain for fine-tuning.

    conversations: list of {"from": "system"|"human"|"gpt", "value": "...", ...}
    Used by the coder loop to capture the full tool-use chain so the student
    model learns how to sequence tool calls, not just isolated turns.
    """
    if not conversations:
        return

    conv_json = json.dumps(conversations, ensure_ascii=False)

    # Try CADEN's DB first
    if _CADEN_DB and _CADEN_DB.exists():
        try:
            conn = sqlite3.connect(str(_CADEN_DB))
            _ensure_table(conn)
            conn.execute(
                "INSERT INTO training_data "
                "(ex_type, system_prompt, user_prompt, completion, model, conversations_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (ex_type, "", "", "", model, conv_json),
            )
            conn.commit()
            conn.close()
            return
        except Exception:
            pass  # fall through to JSONL

    # Fallback: append to local JSONL
    record = {
        "conversations": conversations,
        "type": ex_type,
        "model": model,
        "timestamp": time.time(),
    }
    try:
        with open(_FALLBACK_JSONL, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def distill_stats() -> dict:
    """Return counts of distillation examples by type."""
    counts = {}

    # Check CADEN DB
    if _CADEN_DB and _CADEN_DB.exists():
        try:
            conn = sqlite3.connect(str(_CADEN_DB))
            _ensure_table(conn)
            rows = conn.execute(
                "SELECT ex_type, COUNT(*) FROM training_data "
                "WHERE ex_type LIKE 'vibecoder_%' GROUP BY ex_type"
            ).fetchall()
            conn.close()
            for ex_type, count in rows:
                counts[ex_type] = count
        except Exception:
            pass

    # Also check local JSONL
    if os.path.exists(_FALLBACK_JSONL):
        try:
            with open(_FALLBACK_JSONL, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        rec = json.loads(line)
                        t = rec.get("type", "unknown")
                        counts[t] = counts.get(t, 0) + 1
        except Exception:
            pass

    return counts
