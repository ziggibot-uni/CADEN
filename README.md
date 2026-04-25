# CADEN v0

Local-first, privacy-first personal AI for Sean. Python-only, deterministic
framework plus local LLM. Spec lives in [CADEN.md](CADEN.md) and is the source
of truth; this README is an operating manual only.

## What is built

Milestones from the spec:

- **M1 — Skeleton that stores.** Textual app with a dashboard: today | chat
  | next-7-days panels. **Only Sean's messages** are embedded and written
  to Libbie — CADEN's replies are displayed but never persisted as events
  (spec: "keeps memory pristine to Sean's signal"). sqlite-vec verified at
  boot.
- **M2 — LLM round trip.** Ollama chat with retrieval-augmented context
  (top-K = 20 memories, 500-char truncation per memory), tolerant JSON
  repair layer between the LLM and every caller. CADEN's last few replies
  are passed as ephemeral in-session context, never stored.
- **M3 — Google sync read-only.** Today and 7-day panels render real
  Calendar events when Google OAuth is configured.
- **M4 — Add-task button + write-back.** `a` key or the "+ add task" button
  opens a modal. Submitting creates a Google Task + paired Calendar
  event(s), stores the scheduler plan, and emits a prediction bundle.
  First-time schedules (no relevant history) get confidence floored at
  the bootstrap value of 0.1 across all axes.
- **M5 — Completion and residuals.** `caden.google_sync.poll.poll_once`
  runs automatically every 60 seconds while CADEN is running. It detects
  completed Google Tasks, truncates the paired event, computes and stores
  duration + state residuals.
- **M6 — Rater live.** Every new Sean event triggers a rater LLM call with
  Libbie retrieval. Intake sources (`intake_self_knowledge`,
  `intake_code_pattern`) and structural sources (predictions, residuals,
  bootstrap logs) are skipped. Ratings are immutable. The rater is
  instructed to return `null` when retrieval is too thin — it never fakes
  a number.

## Layout

```
caden/
  config.py, errors.py, main.py
  libbie/   (db.py, store.py, retrieve.py)
  llm/      (client.py, repair.py, embed.py)
  rater/    (rate.py)
  scheduler/(schedule.py, predict.py, residual.py)
  google_sync/(auth.py, calendar.py, tasks.py, poll.py)
  ui/       (app.py, dashboard.py, chat.py, add_task.py, services.py)
```

## One-time setup (Ubuntu)

1. Install Python ≥ 3.11 and `ollama` (https://ollama.com).
2. Pull models:

   ```
   ollama pull llama3.1:8b
   ollama pull nomic-embed-text
   ```

3. Create a venv and install CADEN:

   ```
   python -m venv .venv
   source .venv/bin/activate
   pip install -e .
   ```

4. Create `~/.caden/config.json`:

   ```json
   {
     "ollama_url": "http://127.0.0.1:11434",
     "ollama_model": "llama3.1:8b",
     "embed_model": "nomic-embed-text",
     "embed_dim": 768,
     "google_credentials_path": "~/.caden/google_credentials.json",
     "google_token_path": "~/.caden/google_token.json"
   }
   ```

   The DB lives at `~/.caden/caden.sqlite3` and is created on first run.
   Override the home directory via `CADEN_HOME`.

5. *(Optional for now — required for M3–M5.)* Download an OAuth 2.0 Client
   ID JSON from Google Cloud Console (Desktop app) with scopes
   `calendar` and `tasks`; save to `~/.caden/google_credentials.json`.
   First run will pop a browser and cache the token.

## Run

```
caden
```

Keys: `a` add task · `r` refresh · `q` quit.

## Failure modes (all loud, by design)

Every one of these exits CADEN with a clear `CadenError`:

- missing or malformed `config.json`
- sqlite cannot load the `sqlite-vec` extension
- ollama unreachable or the configured model not pulled
- embedding model missing, or its dim disagrees with `config.embed_dim`
- Google credentials present but token/refresh fails
- LLM output that cannot be repaired into the requested JSON shape
- completed task with no paired prediction/event row

This is on purpose. Silent fallbacks are the thing the spec forbids most.

## What is intentionally not built

- Project Manager, Thought Dump, Sprocket apps
- schema growth mechanism
- phase-change detection / decay tuning
- active schedule comparison / optimisation
- webhook-based completion detection (polling only in v0)
- cross-device sync, SearXNG research
