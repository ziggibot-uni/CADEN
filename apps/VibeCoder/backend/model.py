"""Model interface for VibeCoder.

Uses Llama-3.3-70B-Instruct via cloud providers.
Every call is wrapped with distillation logging so outputs can be used
to fine-tune a smaller QLoRA adapter.

Providers:
  1. OpenRouter — meta-llama/llama-3.3-70b-instruct:free (primary for coder/planner/critic)
  2. Groq  — llama-3.3-70b-versatile  (fast, used for orchestration + fallback)
  3. GitHub Models — meta/llama-3.3-70b-instruct  (PAT auth, fallback)

Ollama is NOT used for LLM inference — only for nomic-embed-text embeddings
in caden_bridge.py.
"""

import json
import os
import sqlite3
from pathlib import Path
from typing import Optional

import requests

from distill import log_distillation


# ── Configuration ─────────────────────────────────────────────────────────────

# Cloud model identifiers
_GROQ_URL   = "https://api.groq.com/openai/v1/chat/completions"
_GROQ_MODEL = "llama-3.3-70b-versatile"

_GITHUB_URL   = "https://models.github.ai/inference/chat/completions"
_GITHUB_MODEL = "meta/llama-3.3-70b-instruct"

_OPENROUTER_URL   = "https://openrouter.ai/api/v1/chat/completions"
_OPENROUTER_MODEL = "meta-llama/llama-3.3-70b-instruct:free"

_TIMEOUT = 120

# Context windows
# Groq is fast but its free tier chokes on large payloads (400 errors).
# Route small calls (<= threshold) to Groq, larger ones to OpenRouter/GitHub.
_GROQ_TOKEN_LIMIT = 6000   # ~6k tokens — safe for Groq free tier
_LARGE_CTX_LIMIT  = 30000  # OpenRouter / GitHub can handle much more

# Round-robin call counter — used when multiple large-ctx providers are available.
_call_counter = [0]
_groq_key_idx = [0]  # round-robin index for multiple Groq keys


# ── Key retrieval from CADEN DB ───────────────────────────────────────────────

def _get_caden_db() -> Optional[Path]:
    candidates = [
        Path(os.environ.get("APPDATA", "")) / "com.caden.app" / "caden.db",
        Path(os.environ.get("LOCALAPPDATA", "")) / "com.caden.app" / "caden.db",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _get_groq_keys() -> list:
    """Read Groq API keys from CADEN's settings DB (JSON array) or env."""
    db = _get_caden_db()
    if db:
        try:
            conn = sqlite3.connect(str(db))
            row = conn.execute(
                "SELECT value FROM settings WHERE key = 'groq_keys'"
            ).fetchone()
            conn.close()
            if row and row[0]:
                keys = json.loads(row[0])
                if isinstance(keys, list):
                    return [k for k in keys if k and k.strip()]
        except Exception:
            pass
    # Fallback to env
    env_key = os.environ.get("GROQ_API_KEY")
    return [env_key] if env_key else []


def _get_github_pat() -> Optional[str]:
    """Read GitHub PAT from CADEN's settings DB or env."""
    db = _get_caden_db()
    if db:
        try:
            conn = sqlite3.connect(str(db))
            row = conn.execute(
                "SELECT value FROM settings WHERE key = 'github_pat'"
            ).fetchone()
            conn.close()
            if row and row[0] and row[0].strip():
                return row[0].strip()
        except Exception:
            pass
    return os.environ.get("GITHUB_TOKEN")


def _get_openrouter_key() -> Optional[str]:
    """Read OpenRouter API key from CADEN's settings DB or env."""
    db = _get_caden_db()
    if db:
        try:
            conn = sqlite3.connect(str(db))
            row = conn.execute(
                "SELECT value FROM settings WHERE key = 'openrouter_key'"
            ).fetchone()
            conn.close()
            if row and row[0] and row[0].strip():
                return row[0].strip()
        except Exception:
            pass
    return os.environ.get("OPENROUTER_API_KEY")


def _next_groq_key() -> Optional[str]:
    """Get the next Groq key using round-robin rotation."""
    keys = _get_groq_keys()
    if not keys:
        return None
    idx = _groq_key_idx[0] % len(keys)
    _groq_key_idx[0] = idx + 1
    return keys[idx]


# ── Provider selection ───────────────────────────────────────────────────────

def _pick_provider(est_tokens: int) -> str:
    """Pick the best provider based on estimated token count.
    Small payloads → Groq (fastest).
    Large payloads → OpenRouter (reliable large context), then GitHub."""
    has_groq       = bool(_get_groq_keys())
    has_openrouter = bool(_get_openrouter_key())
    has_github     = bool(_get_github_pat())

    fits_groq = est_tokens <= _GROQ_TOKEN_LIMIT

    # Small payload — use Groq if available
    if fits_groq and has_groq:
        return "groq"

    # Large payload — prefer OpenRouter, then GitHub, then Groq as last resort
    if has_openrouter:
        return "openrouter"
    if has_github:
        return "github"
    if has_groq:
        return "groq"  # better than nothing

    raise RuntimeError(
        "No LLM provider configured. Set an OpenRouter key, Groq keys, or GitHub PAT in CADEN settings."
    )


def _fallback_provider(failed: str, est_tokens: int) -> Optional[str]:
    """Return one fallback provider that isn't the one that just failed.
    Still respects token size — won't send a huge payload to Groq."""
    fits_groq = est_tokens <= _GROQ_TOKEN_LIMIT
    candidates = []
    if failed != "openrouter" and _get_openrouter_key():
        candidates.append("openrouter")
    if failed != "github" and _get_github_pat():
        candidates.append("github")
    if failed != "groq" and _get_groq_keys() and fits_groq:
        candidates.append("groq")
    return candidates[0] if candidates else None


def get_active_model() -> str:
    has_openrouter = bool(_get_openrouter_key())
    has_groq   = bool(_get_groq_keys())
    has_github = bool(_get_github_pat())
    parts = []
    if has_groq:
        parts.append("groq")
    if has_openrouter:
        parts.append("openrouter")
    if has_github:
        parts.append("github")
    if not parts:
        return "none"
    return " + ".join(parts) + " (auto-routed)"


def set_active_model(model_name: str):
    """No-op — provider is now determined by context size, not a fixed setting."""
    pass


# ── Core call function ────────────────────────────────────────────────────────

def _estimate_tokens(messages):
    """Rough token estimate: ~4 chars per token."""
    return sum(len(str(m.get("content", ""))) for m in messages) // 4


def _trim_messages(messages, max_tokens=24000):
    """Drop oldest non-system messages until under token budget.
    Also truncates oversized system prompts."""
    # Cap system message if it alone is too large (>60% of budget)
    sys_limit = int(max_tokens * 0.6 * 4)  # chars
    trimmed_msgs = []
    for m in messages:
        if m.get("role") == "system" and len(str(m.get("content", ""))) > sys_limit:
            m = dict(m)
            m["content"] = str(m["content"])[:sys_limit] + "\n... (system prompt truncated to fit context)"
        trimmed_msgs.append(m)
    messages = trimmed_msgs

    if _estimate_tokens(messages) <= max_tokens:
        return messages
    system = [m for m in messages if m.get("role") == "system"]
    rest = [m for m in messages if m.get("role") != "system"]
    while rest and _estimate_tokens(system + rest) > max_tokens:
        rest.pop(0)
    if not rest:
        return system
    dropped = len([m for m in messages if m.get("role") != "system"]) - len(rest)
    trimmed = list(system)
    if dropped > 0:
        trimmed.append({"role": "system", "content": f"[{dropped} earlier messages trimmed to fit context window]"})
    trimmed.extend(rest)
    return trimmed


def _call(
    messages,
    temperature=0.1,
    max_tokens=4096,
    ex_type=None,
):
    """Auto-route to the best provider based on payload size. One fallback on failure."""
    messages = _trim_messages(messages)
    est = _estimate_tokens(messages) + max_tokens
    provider = _pick_provider(est)

    result = _dispatch(provider, messages, temperature, max_tokens, ex_type)
    if result["content"].startswith("[LLM Error:"):
        fb = _fallback_provider(provider, est)
        if fb:
            result = _dispatch(fb, messages, temperature, max_tokens, ex_type)
    return result


def _dispatch(provider, messages, temperature, max_tokens, ex_type):
    """Route to the correct provider function."""
    if provider == "openrouter":
        return _call_openrouter(messages, temperature, max_tokens, ex_type)
    if provider == "groq":
        return _call_groq(messages, temperature, max_tokens, ex_type)
    return _call_github(messages, temperature, max_tokens, ex_type)


def _call_openrouter(messages, temperature, max_tokens, ex_type):
    key = _get_openrouter_key()
    if not key:
        return {"content": "[LLM Error: No OpenRouter API key configured]"}

    try:
        res = requests.post(
            _OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={
                "model": _OPENROUTER_MODEL,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=_TIMEOUT,
        )
        res.raise_for_status()
        data = res.json()
        choices = data.get("choices") or []
        if not choices:
            err_msg = data.get("error", {}).get("message") or data.get("message") or "empty choices"
            return {"content": f"[LLM Error: OpenRouter: {err_msg}]"}
        choice = choices[0]
        content = choice.get("message", {}).get("content", "")
        finish = choice.get("finish_reason", "stop")

        if ex_type and content and not content.startswith("[LLM Error"):
            _log_call(ex_type, messages, content, f"openrouter:{_OPENROUTER_MODEL}")

        return {"content": content, "finish_reason": finish}

    except requests.exceptions.Timeout:
        return {"content": f"[LLM Error: OpenRouter request timed out after {_TIMEOUT}s]"}
    except requests.exceptions.HTTPError as e:
        return {"content": f"[LLM Error: OpenRouter: {e}]"}
    except (requests.exceptions.ConnectionError, OSError):
        return {"content": "[LLM Error: OpenRouter unreachable]"}
    except Exception as e:
        return {"content": f"[LLM Error: OpenRouter: {e}]"}


def _call_groq(messages, temperature, max_tokens, ex_type):
    key = _next_groq_key()
    if not key:
        return {"content": "[LLM Error: No Groq API keys configured]"}

    try:
        res = requests.post(
            _GROQ_URL,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={
                "model": _GROQ_MODEL,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=_TIMEOUT,
        )
        res.raise_for_status()
        data = res.json()
        choices = data.get("choices") or []
        if not choices:
            err_msg = data.get("error", {}).get("message") or data.get("message") or "empty choices"
            return {"content": f"[LLM Error: Groq: {err_msg}]"}
        choice = choices[0]
        content = choice.get("message", {}).get("content", "")
        finish = choice.get("finish_reason", "stop")

        if ex_type and content and not content.startswith("[LLM Error"):
            _log_call(ex_type, messages, content, f"groq:{_GROQ_MODEL}")

        return {"content": content, "finish_reason": finish}

    except requests.exceptions.Timeout:
        return {"content": f"[LLM Error: Groq request timed out after {_TIMEOUT}s]"}
    except requests.exceptions.HTTPError as e:
        body = ""
        try:
            body = e.response.text[:300] if e.response is not None else ""
        except Exception:
            pass
        return {"content": f"[LLM Error: Groq: {e} — {body}]"}
    except (requests.exceptions.ConnectionError, OSError):
        return {"content": "[LLM Error: Groq unreachable]"}
    except Exception as e:
        return {"content": f"[LLM Error: Groq: {e}]"}


def _call_github(messages, temperature, max_tokens, ex_type):
    pat = _get_github_pat()
    if not pat:
        return {"content": "[LLM Error: No GitHub PAT configured]"}

    try:
        res = requests.post(
            _GITHUB_URL,
            headers={
                "Authorization": f"Bearer {pat}",
                "Content-Type": "application/json",
            },
            json={
                "model": _GITHUB_MODEL,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=_TIMEOUT,
        )
        res.raise_for_status()
        data = res.json()
        choices = data.get("choices") or []
        if not choices:
            err_msg = data.get("error", {}).get("message") or data.get("message") or "empty choices"
            return {"content": f"[LLM Error: GitHub Models: {err_msg}]"}
        choice = choices[0]
        content = choice.get("message", {}).get("content", "")
        finish = choice.get("finish_reason", "stop")

        if ex_type and content and not content.startswith("[LLM Error"):
            _log_call(ex_type, messages, content, f"github:{_GITHUB_MODEL}")

        return {"content": content, "finish_reason": finish}

    except requests.exceptions.Timeout:
        return {"content": f"[LLM Error: GitHub Models request timed out after {_TIMEOUT}s]"}
    except requests.exceptions.HTTPError as e:
        return {"content": f"[LLM Error: GitHub Models: {e}]"}
    except Exception as e:
        return {"content": f"[LLM Error: GitHub Models: {e}]"}


def _log_call(ex_type, messages, completion, model):
    """Extract system/user prompts and log for distillation."""
    system_prompt = None
    user_prompt = ""
    for m in messages:
        if m.get("role") == "system" and not system_prompt:
            system_prompt = m["content"]
        elif m.get("role") == "user":
            user_prompt = m["content"]  # take the last user message

    log_distillation(
        ex_type=ex_type,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        completion=completion,
        model=model,
    )


# ── Stage-specific wrappers ──────────────────────────────────────────────────

def orchestrator_chat(messages):
    """LLM-driven routing. Small, fast call. Uses normal _call routing with fallback."""
    return _call(messages,
                 temperature=0.1, max_tokens=300,
                 ex_type="vibecoder_orchestrate")


def planner_chat(messages, thinking=False):
    """Plan decomposition. Logged as vibecoder_plan."""
    return _call(messages,
                 temperature=0.1, max_tokens=1024,
                 ex_type="vibecoder_plan")


def coder_chat(messages, thinking=False):
    """Coder tool loop. NOT auto-logged — the agent loop logs the full
    multi-turn chain at the end so the student model learns tool chaining."""
    return _call(messages,
                 temperature=0.1, max_tokens=4096,
                 ex_type=None)


def critic_chat(messages):
    """Post-hoc critic pass. Logged as vibecoder_critic."""
    return _call(messages,
                 temperature=0.0, max_tokens=256,
                 ex_type="vibecoder_critic")


def researcher_chat(messages):
    """Research and plan-validation pass. Logged as vibecoder_research."""
    return _call(messages,
                 temperature=0.1, max_tokens=2048,
                 ex_type="vibecoder_research")


def coder_chat_stream(messages, thinking=False):
    """Streaming coder chat. Auto-routes based on context size."""
    messages = _trim_messages(messages)
    est = _estimate_tokens(messages) + 4096
    provider = _pick_provider(est)

    # Resolve credentials
    if provider == "openrouter":
        url = _OPENROUTER_URL
        model = _OPENROUTER_MODEL
        headers = {"Authorization": f"Bearer {_get_openrouter_key()}", "Content-Type": "application/json"}
    elif provider == "groq":
        url = _GROQ_URL
        model = _GROQ_MODEL
        headers = {"Authorization": f"Bearer {_next_groq_key()}", "Content-Type": "application/json"}
    elif provider == "github":
        url = _GITHUB_URL
        model = _GITHUB_MODEL
        headers = {"Authorization": f"Bearer {_get_github_pat()}", "Content-Type": "application/json"}
    else:
        yield "[LLM Error: No provider configured]"
        return

    try:
        res = requests.post(
            url,
            headers=headers,
            json={
                "model": model,
                "messages": messages,
                "temperature": 0.1,
                "max_tokens": 4096,
                "stream": True,
            },
            timeout=_TIMEOUT,
            stream=True,
        )
        res.raise_for_status()
        full_content = []
        for line in res.iter_lines():
            if not line:
                continue
            text = line.decode("utf-8", errors="replace")
            if text.startswith("data: "):
                text = text[6:]
            if text.strip() == "[DONE]":
                break
            try:
                data = json.loads(text)
                delta = data.get("choices", [{}])[0].get("delta", {})
                chunk = delta.get("content", "")
                if chunk:
                    full_content.append(chunk)
                    yield chunk
            except json.JSONDecodeError:
                continue

        complete = "".join(full_content)
        if complete:
            pass  # Caller logs the full chain — no per-round logging

    except requests.exceptions.Timeout:
        yield "[LLM Error: Request timed out]"
    except Exception as e:
        yield f"[LLM Error: {e}]"


# ── Coder output classification ───────────────────────────────────────────────

def classify_coder_output(text: str) -> str:
    """Classify a coder round's output for distillation sub-typing.

    Returns one of:
      vibecoder_tool_call  — model issued a tool call (read/search/run/list)
      vibecoder_code_edit  — model issued a file-modifying tool call
      vibecoder_answer     — model gave a plain-text final answer
    """
    text = text.strip()
    if '{' in text:
        import re
        tool_match = re.search(r'"tool"\s*:\s*"(\w+)"', text)
        if tool_match:
            tool = tool_match.group(1).lower()
            if tool in ("edit_file", "edit", "apply_patch",
                        "write_file", "write", "create"):
                return "vibecoder_code_edit"
            return "vibecoder_tool_call"
    return "vibecoder_answer"


# ── Lesson extraction call ────────────────────────────────────────────────────

LESSON_PROMPT = """You just completed a coding task. Analyze what happened and fill out this JSON form.
Be specific and honest. If nothing went wrong, say so.

Task: {task}
Outcome: {outcome}
Steps taken: {steps}

Respond with ONLY this JSON:
{{
  "mistakes": ["list of things that went wrong or could have been better"],
  "what_worked": ["list of approaches that succeeded"],
  "key_facts": ["small discoveries — API quirks, config gotchas, patterns learned"]
}}"""


def extract_lessons(task: str, outcome: str, steps: str) -> dict:
    """Ask the model to self-reflect on what happened during a task."""
    messages = [
        {"role": "system", "content": "You are a coding assistant reviewing your own work. Be concise and specific."},
        {"role": "user", "content": LESSON_PROMPT.format(task=task, outcome=outcome, steps=steps)},
    ]
    result = _call(messages, temperature=0.1, max_tokens=512)
    raw = result.get("content", "").strip()
    try:
        import re
        m = re.search(r'\{[^{}]*\}', raw, re.DOTALL)
        if m:
            return json.loads(m.group())
    except Exception:
        pass
    return {"mistakes": [], "what_worked": [], "key_facts": []}


# Legacy shims
GATE_MODEL = _GROQ_MODEL
CODER_MODEL = get_active_model()


def get_selected_model():
    return get_active_model()


def set_selected_model(model_name):
    set_active_model(model_name)


def chat(messages, temperature=0.1, max_tokens=4096):
    return coder_chat(messages, thinking=False)
