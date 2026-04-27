# CADEN v0

Local-first, privacy-first personal AI for Sean. Python-only, deterministic
framework plus local LLM. Spec lives in [CADEN.md](CADEN.md) and is the source
of truth; this README is an operating manual only.

Priority note: [CADEN.md](CADEN.md) and [CADEN_v0.md](CADEN_v0.md) take
precedence over this README, the milestone tests, and any other summary docs.
If this file disagrees with either spec file, treat this README as stale and
follow the spec files.

## What is built

Milestones from the spec:

- **M1 — Skeleton that stores.** Textual app with a dashboard: today | chat
  | next-7-days panels. **Only Sean's messages** are embedded and written
  to Libbie — CADEN's replies are displayed but never persisted as events
  (spec: "keeps memory pristine to Sean's signal"). sqlite-vec verified at
  boot.
- **M2 — LLM round trip.** Ollama chat with retrieval-augmented context
  and tolerant JSON repair between the LLM and every caller. CADEN's last
  few replies are passed as ephemeral in-session context, never stored.
  Chat retrieval now runs through Libbie's curated-memory layer: raw
  events remain the provenance log, but CADEN sees compact recall
  packets built from `memories` rows rather than raw event dumps. Libbie's
  retrieval ranking also penalizes overly long memories so concise memories
  win when similarity is otherwise close.
- **M3 — Google sync read-only.** Today and 7-day panels render real
  Calendar events when Google OAuth is configured. The dashboard's "today"
  window is anchored to a 5 AM local day boundary rather than midnight.
- **M4 — Add-task button + write-back.** `a` key or the "+ add task" button
  opens a modal. Submitting creates a Google Task + paired Calendar
  event(s), stores the scheduler plan, and emits a prediction bundle.
  The README does not define fixed confidence floors; consult the priority
  specs for scheduling behavior.
- **M5 — Completion and residuals.** `caden.google_sync.poll.poll_once`
  runs automatically every 60 seconds while CADEN is running. It detects
  completed Google Tasks, truncates the paired event, computes and stores
  duration + state residuals.
- **M6 — Rater live.** Every new Sean event triggers a rater LLM call with
  Libbie retrieval. Structural sources (predictions, residuals,
  bootstrap logs) are skipped. Ratings are immutable. The rater is
  instructed to return `null` when retrieval is too thin — it never fakes
  a number.

GUI continuity note: the v0 today | chat | next-7-days interface is not a
throwaway prototype. When CADEN expands past v0, this exact surface becomes
the `Dashboard` tab inside the larger multi-tab GUI.

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

1. Install the platform/runtime required by the priority specs, plus
  `ollama` (https://ollama.com).
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

4. Follow the current filesystem, config, and Google OAuth contract in
  `CADEN_v0.md` rather than this README. Those details are intentionally
  not duplicated here so they cannot drift.

Optional local web enrichment:

Add `searxng_url = "http://127.0.0.1:8080"` to `settings.toml` if you
have a local SearXNG instance running. Libbie uses it only when chat
recall/enrichment needs external grounding on the Libbie side, captures the
results as memory input, and then re-runs curated memory retrieval.

## Run

```
caden
```

Keys: `a` add task · `r` refresh · `q` quit.

## Failure modes (all loud, by design)

Every one of these exits CADEN with a clear `CadenError`:

- missing or malformed config
- sqlite cannot load the `sqlite-vec` extension
- ollama unreachable or the configured model not pulled
- embedding model missing, or its configured dimension disagrees with the
  active contract
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
- cross-device sync, broad user-facing web-research workflows beyond Libbie's
  narrow local SearXNG enrichment path
