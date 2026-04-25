# CADEN V0

This file is for exploration, drafting, and testing ideas.

The canonical spec remains in `CADEN.md` and is not to be edited here.

## Locked Constraints From the Main Spec
- local-first and privacy-first
- Python-only implementation
- deterministic framework plus local LLM, not either one alone
- no silent fallbacks; failures should be loud and diagnosable
- one central vector-capable sqlite memory store managed by Libbie
- CADEN must keep learning as Sean changes over time
- no hand-written heuristics; all behavior is learned. Improve mechanisms, not
  rules. One bespoke rule is pollution; the "just one more rule" trap is fatal.
- "bootstrapping" or pre-decided limits/thresholds (e.g. max K, truncate chars, max events) are forbidden if they bypass LLM decision-making. The LLM must make the calls using advice/experience, even if it makes bad calls initially, so that a residual is generated to learn from.
- it is acceptable for CADEN to suck for a while during cold start; that is
  cheaper than permanent pollution

## Declared Objective (from CADEN.md)
CADEN tracks three axes and balances them: maximize each without tanking the
others.
- mood
- energy
- productivity

This is the objective function, not a heuristic. The spec is allowed to define
what CADEN is optimizing; heuristics are forbidden rules about *how* to
achieve it. How mood / energy / productivity are estimated, what events move
them, and what responses help are all learned, not designed.

Rules that follow from this:
- CADEN does not get hand-written feature lists for any axis (no valence-as-
  mood-proxy, no keystrokes-as-energy-proxy, no task-count-as-productivity).
- each axis is a scalar CADEN learns to estimate from the event stream.
- estimators start as "I don't know" and earn predictions by accumulating
  observations.
- a move is "good" if mood, energy, or productivity improved without the
  other two tanking. This is the shape of every outcome judgement.

### How rating happens (no hand-written features)
The LLM rates every incoming event on mood / energy / productivity. That is
the estimator. The prompt contains:
- the event itself
- relevant past events and their ratings, retrieved by Libbie
- relevant self-knowledge from Sean (things he has said about himself in chat,
  thought dump, or project manager entries), retrieved by Libbie the same way
  any other memory is retrieved

Rating improves over time purely through better retrieval, not through rules.
Sean never codes his patterns into CADEN; he just tells CADEN about himself
the same way he tells CADEN anything, and those statements become first-class
memories that resurface whenever the rating LLM needs them.

Output is three numbers plus the LLM's short rationale. Rationale is stored
so future ratings can retrieve and learn from it.

### Rater self-correction
Old ratings are immutable. They are snapshots of past Sean, not drafts to be
corrected. Rewriting history would destroy the very signal CADEN needs to
detect that Sean has changed, because phase-change detection depends on
rising residuals against old-pattern predictions.

The rater improves on its own over time: every new rating benefits from more
accumulated self-knowledge and more past ratings in retrieval. No back-fill,
no overwrite.

Rater quality is measured two ways, neither of which touches stored history:
- observed residual: predicted mood / energy / productivity trajectory vs.
  what later ratings on new events actually show. This is the primary signal.
- optional short-window stability check: re-rate a handful of very recent
  events (last 24h at most) and compare to the original ratings. The re-rated
  values are never stored; they exist only for the comparison, then are
  discarded. This is a diagnostic on present rater consistency only.

If the rater is noisy, the fix is never "rewrite the past." The fix is to
surface more self-knowledge from Sean or, if the mechanism itself is
underspecified, improve the mechanism.

## Reset Note (supersedes everything below this section)
Earlier drafts in this file sketched primitive sets (valence/arousal/clarity),
derived signals (burnout_proximity, momentum, mood_drift), case-based reasoning
with a four-component fingerprint, situation-type taxonomies, anticipation
physics, escalation thresholds, and a staged experiment plan. All of that was
hand-written structure imposed on Sean before CADEN had any data.

That violates the no-heuristics rule. It is all deprecated. The sections below
are kept only as a history of rejected ideas, not as design.

## Organizing Principle: Predict, Observe, Correct
CADEN has one central mechanism. Everything else is a consequence of it.

1. Predict: given what Libbie retrieves and what the LLM reasons, CADEN
   produces a response or action, and projects the short-horizon trajectory
   of mood / energy / productivity that this move is expected to produce.
2. Observe: the next events Libbie stores are the ground truth. CADEN's
   learned estimators read those events and emit actual mood / energy /
   productivity values over the same horizon.
3. Correct: the residual between predicted and actual trajectories is the
   training signal CADEN uses. Retrieval weights, estimator parameters,
   schema decisions, and decay rates all move in response to residuals.

That is the whole loop. Works over any schema, at any scale, without any
hand-written rules about Sean.

### What a prediction looks like concretely
Predictions are emitted when CADEN schedules a task. Every task Sean adds is
immediately paired with a Google Calendar event created by CADEN; that event
is the scheduling decision.

At the moment CADEN creates the event, he emits a prediction bundle:
- duration (implicit in event length, and in whether the task was split into
  multiple chunks across days)
- Sean's mood / energy / productivity just before the event
- Sean's mood / energy / productivity just after the event
- a confidence number for each of the above

The prediction bundle is stored as a memory in Libbie just like any other
event. No separate prediction table in v0; it is source-tagged so it can be
retrieved later as prediction history.

### What a residual looks like concretely
When Sean marks a task complete, CADEN edits the paired calendar event's end
time to the moment of completion. That timestamp frees the rest of the block
and also becomes the ground truth for duration.

State residuals come from the normal rating stream: ratings of events
immediately before and after the task window are the observed state, which
is compared to the predicted state. Three state residuals per prediction
(mood, energy, productivity) plus one duration residual.

Residuals are stored as memories of their own, again source-tagged. CADEN
literally remembers when he was right and when he was wrong, the same way he
remembers anything else.

### Why this satisfies the spec
- deterministic framework + LLM union: residuals are deterministic math, the
  LLM does the reasoning
- learns from Sean without fine-tuning
- no hand-written heuristics; the only thing written by hand is the mechanism
- modular and simple: one loop, applied everywhere
- fails loudly: a prediction either matched or didn't; no hidden fallbacks
- counts on Sean changing: rising residuals are phase-change detection

## Starting Schema (minimum possible)
Libbie stores one table for all events. Fields that exist because they must:
- id
- timestamp
- source (which app or subsystem produced this event)
- raw text
- embedding

Nothing else. No primitives, no tags, no affect scores, no situation types,
no fingerprints, no derived signals. Those are all pollution until CADEN
discovers he needs them.

Estimator outputs (mood / energy / productivity) live alongside events but
are not event fields. They are computed from events by learned estimators
and stored separately so the raw event record stays pristine.

## Schema Growth (learned, not designed)
Schema growth is a consequence of Predict-Observe-Correct, not a separate rule.

When residuals stay stubbornly high in some region of situations, the system
asks itself (via the LLM) what about those situations is not captured by the
current schema. The LLM proposes a new field or tag. CADEN adds the column,
starts populating it on new events, and measures whether the new field reduces
residuals over time. If yes, it stays. If no, it is dropped.

Rules about schema growth:
- only triggered by persistent high residuals, never by a designer's guess
- the LLM proposes; the residual math decides
- old records are not retroactively rewritten unless the new field is cheap to
  backfill
- schema additions are logged loudly so Sean can see what CADEN decided to
  start tracking and why

## Retrieval (also learned)
Libbie's retrieval is not a fixed algorithm. It is a scoring function whose
weights update from residuals: memories whose resurfacing led to good
predictions gain weight; memories whose resurfacing led to bad predictions
lose weight. The form of retrieval (embedding similarity + metadata filters)
is the mechanism; the weights inside it are learned.

## Decay / Phase Change
Old evidence loses weight when residuals involving it start rising. This is
phase-change detection: CADEN notices Sean has shifted because predictions
grounded in old data stop working. Decay rate is not a fixed schedule; it
responds to residual trends.

## Failure Modes (must be loud)
Every one of these kills the process with a clear error, never a silent
fallback:
- LLM returns malformed output
- ollama is unreachable
- Libbie's DB is corrupted or missing
- embedding model is unavailable
- a learned parameter diverges (NaN, explosion, impossible value)
- Google Calendar / Tasks sync fails

## v0 Scope
- dashboard + chat + Libbie memory, as described in CADEN.md
- every Sean input and every CADEN response gets stored with the minimum schema
- LLM responds using retrieved context
- mood / energy / productivity estimators exist from day one but output
  "unknown" until they have enough data to predict. They never fake a number.
- CADEN owns scheduling. Sean only provides a task and a deadline; CADEN
  creates the paired Google Calendar event, chooses when it happens, and
  splits it into chunks if needed. Sean does not schedule anything himself.
- every task-event pair spawns a prediction bundle (duration + pre-state +
  post-state + confidences), stored as a memory.
- on task completion, the paired event's end time is edited to "now",
  freeing the rest of the block. Residuals are computed and stored.
- no hand-written features, no primitives, no cases, no fingerprints, no
  derived signals.
- v0 does not actively compare or optimize between alternative schedules.
  CADEN schedules, predicts, observes, corrects. Optimization is deferred
  until residuals are small enough that predictions are trustworthy.
- it will feel thin at first. Cold start is the price of purity.

## Scheduling Ownership
Sean is lazy. CADEN does all the scheduling work.
- Sean inputs: task description + deadline (via an explicit "add task"
  button/form on the dashboard, not parsed from casual chat)
- CADEN decides: when it happens, how long it should take, whether to split
  it across multiple chunks, how it fits around existing calendar/tasks load
- CADEN writes the resulting Google Task + paired Google Calendar event(s)
  via the Google API
- task and paired event(s) are linked in Libbie so completion of the task
  can find its event and rewrite its end time

Why a button instead of LLM-parsed chat:
- unambiguous surface, no misinterpretation of casual messages as tasks
- Sean's inputs go in with known structure, no recovery needed
- chat stays free of accidental task-creation land mines

Failure modes that must fail loudly:
- Google Calendar / Tasks API unreachable or token expired
- task submitted without a deadline (form enforces it; a bypass is a bug)
- task marked complete but no paired event found
- paired event edit fails

## LLM Output Handling
The LLM is allowed to be messy. The framework is responsible for cleaning up
formatting. Let the model focus on being right; the framework makes it tidy.

Expected tolerances:
- JSON wrapped in prose ("sure, here it is: {...}")
- JSON inside markdown code fences
- trailing commas, single quotes, slightly wrong field names
- fields in a different order than requested

What still fails loudly:
- content that is genuinely wrong or missing after repair (no filling in
  defaults, no guessing missing fields)
- repeated failure to return the required content even after repair attempts
- anything the framework cannot confidently recover

The repair layer lives between the LLM client and every caller. No caller
ever handles raw LLM output directly. Repairs are logged so we can see which
prompts consistently produce messy output and tighten them when it matters.

## Tech Stack Decisions
- target platform: Ubuntu (design happens on Windows, build and run on
  Ubuntu for AI tooling reasons)
- embedding model: nomic-embed-text
- statistics and rolling aggregations: pandas
- basic regression / weighted nearest neighbors / similar: scikit-learn or
  equivalent battle-tested library. Do not reimplement statistics from
  scratch.
- local LLM: ollama (model chosen in CADEN's settings, per CADEN.md)
- storage: single sqlite database using the sqlite-vec extension for vector
  search. Chosen for active maintenance, zero-dependency pure C, clean
  install on Ubuntu, and right-sized for a personal memory store.
- GUI toolkit: Textual. Fits the "CLI in the middle panel" description of
  the dashboard, Python-native, modern, and cleanly supports multi-pane
  layouts across all CADEN apps.
- Google integration: google-api-python-client + google-auth

## Implementation Contracts
Concrete decisions a less-capable model can build against without dilemmas.
Every other doc that mentions one of these defers to this section.

### Platform
- Ubuntu 24.04 LTS
- Python 3.12
- dependency manager: uv (fast, lockfile, reproducible)
- single sudo step at install time (only to install firejail for Sprocket's
  sandbox; runtime is sudoless)

### Filesystem layout
- code: `~/caden-src/` (git repo)
- data: `~/.local/share/caden/` (sqlite DB, log files, sprocket-built apps,
  oauth token cache that needs writeability)
- config: `~/.config/caden/` (settings.toml, machine-stable choices)
- scratch: `~/.local/share/caden/scratch/` (Sprocket sandbox per-attempt
  folders; cleaned periodically)

### Errors and "loud failure" semantics
- one root error class `CadenError` in `caden/errors.py`, with subclasses
  per subsystem (`ConfigError`, `BootError`, `DBError`, `EmbedError`,
  `LLMError`, `LLMAborted`, `LLMRepairError`, `RaterError`,
  `SchedulerError`, `GoogleSyncError`, plus future `SprocketError`,
  `UIError`)
- "loud failure" means: raise the relevant `CadenError` subclass with a
  human-readable message and the original exception chained
- the Textual main loop catches `CadenError` at the top level, displays an
  error banner with the message + a "copy details" affordance, and halts
  the failing subsystem (its async tasks are cancelled). Other subsystems
  keep running.
- the error banner is implemented as a Textual modal screen in
  `caden/ui/_error.py`. Same widget is reused for boot-time and runtime
  failures.
- catastrophic failures (DB corruption, sqlite-vec missing) raise during
  boot and exit the process with a non-zero code and the same banner shown
  in the terminal Textual launched from
- there is no `try/except` that swallows. Every catch must either re-raise
  as a `CadenError` with context or be a top-level handler

### Concurrency
- single asyncio event loop (Textual's loop)
- all DB writes go through one async write queue served by a single
  coroutine; no two tasks ever hold a write transaction at once
- DB reads can be concurrent (sqlite WAL mode, multiple readers)
- LLM calls, embedding calls, Google API calls are all `await`ed. Slow
  ones run in `asyncio.to_thread` if the underlying lib is blocking.
- background workers (rater, completion-poller, why-rationale-filler) are
  asyncio tasks owned by the main app, cancelled on subsystem failure or
  shutdown

### Time and timezone
- all timestamps stored as ISO-8601 strings with explicit UTC offset
  (`...Z`)
- internal computation uses `datetime` aware-objects in UTC
- display layer converts to local timezone, read once at boot from the
  system locale and cached in `settings.toml` as `display_tz`
- Google Calendar items come back with their own tzinfo; CADEN converts to
  UTC on read, back to display tz only at render time
- display format is 12-hour AM/PM. Anywhere times are rendered to Sean
  (chat replies, dashboard panels, modal forms), 24-hour times are
  rewritten to 12-hour. Formatting helpers live in `caden/util/timefmt.py`
  so every surface uses the same conversion.

### Schema (v0) — concrete
Single sqlite DB at `~/.local/share/caden/caden.db`, sqlite-vec loaded as
extension. Migrations managed by Alembic with versions in
`caden/libbie/migrations/`.

Tables:
- `events`: id INTEGER PK, ts_utc TEXT NOT NULL, source TEXT NOT NULL,
  raw_text TEXT NOT NULL, embedding BLOB NOT NULL (sqlite-vec format,
  768 dims for nomic-embed-text)
- `event_metadata`: id INTEGER PK, event_id INTEGER NOT NULL FK→events,
  key TEXT NOT NULL, value TEXT NOT NULL, created_at TEXT NOT NULL
  (append-only; never UPDATE, never DELETE)
- `ratings`: id PK, event_id FK, mood REAL, energy REAL, productivity REAL,
  conf_mood REAL, conf_energy REAL, conf_productivity REAL, rationale TEXT,
  created_at TEXT. NULL on any score means "unknown."
- `predictions`: id PK, task_id FK→tasks, google_event_id TEXT,
  pred_duration_min INTEGER, pred_pre_mood REAL, pred_pre_energy REAL,
  pred_pre_productivity REAL, pred_post_mood REAL, pred_post_energy REAL,
  pred_post_productivity REAL, conf_pre_mood REAL, conf_pre_energy REAL,
  conf_pre_productivity REAL, conf_post_mood REAL, conf_post_energy REAL,
  conf_post_productivity REAL, conf_duration REAL, created_at TEXT
- `residuals`: id PK, prediction_id FK, duration_actual_min INTEGER NULL,
  duration_residual_min INTEGER NULL, pre_state_residual_mood REAL NULL,
  pre_state_residual_energy REAL NULL, pre_state_residual_productivity REAL
  NULL, post_state_residual_mood REAL NULL, post_state_residual_energy
  REAL NULL, post_state_residual_productivity REAL NULL, created_at TEXT
- `tasks`: id PK, google_task_id TEXT, description TEXT, deadline_utc TEXT,
  status TEXT, created_at TEXT, completed_at_utc TEXT NULL
- `task_events`: id PK, task_id FK, google_event_id TEXT, chunk_index
  INTEGER, chunk_count INTEGER

Each typed-table row also gets an `events` row with `source = "rating"` /
`"prediction"` / `"residual"` / `"task"` / `"task_event"` so unified
retrieval works (the `raw_text` is a serialized summary of the row; the
`event_metadata` row links back via key=`structured_id`, value=row id).

Embedding storage detail: the embedding is not a column on `events`. It
lives in a sibling table `event_embeddings (event_id FK, embedding BLOB)`
plus a `vec_events` sqlite-vec virtual table for ANN search. Functionally
equivalent to a column; the split keeps event-table scans cheap (no BLOB
bloat) and lets vec_events be rebuilt independently if its index format
changes.

v0_extras additions (one Alembic revision past initial): `predictions`
gains a `rationale TEXT` column (the LLM's short explanation for its
prediction, stored alongside the numbers). `task_events` gains
`planned_start TEXT`, `planned_end TEXT`, and `actual_end TEXT NULL` so
the residual loop can find the scheduled window and the realized end
without re-reading Google. These are not new mechanisms; they are
operational fields the residual computation needs.

### Confidence representation
- always REAL between 0.0 and 1.0
- NULL means "unknown" (estimator did not have enough data to predict)
- never store sentinel values like -1 or 999 to mean unknown

### Metadata key conventions (in `event_metadata` table)
The metadata table holds free-form key/value pairs; below are the keys
v0 uses. New keys can appear at any time without migration.
- `captured_at` — ISO-8601 UTC of when CADEN wrote the event (vs. `ts_utc`
  on events which is the event's semantic time)
- `trigger` — finer-grained than `source`; e.g. "chat_send",
  "thought_dump_commit", "google_task_completed", "scheduler_emitted"
- `why` — short LLM-generated rationale for capture (filled async)
- `linked_to` — event_id this memory directly responds to
- `project_id` — for PM-related events
- `entry_type` — for PM entries: "todo", "what_if", "update", "comment"
- `attempt_index`, `approach`, etc. — Sprocket-specific (see sprocket doc)

### `why` rationale generation
- async. Capture writes the event immediately with no `why` row. A
  background worker pulls events lacking `why` from a queue, calls the
  LLM with a tight prompt, and writes the `why` metadata row.
- worker uses the same single-write-queue. If it backs up, capture is
  unaffected.
- if generation fails, the event simply has no `why` (loud log, but no
  exception bubbled). This is the only "permitted partial success" in
  CADEN, and it's permitted because `why` is auxiliary; missing `why`
  doesn't break retrieval.

### LLM repair layer
- library: `json_repair` for repair, `pydantic` for schema validation
- repair pipeline: raw text → strip code fences → `json_repair.loads` →
  `pydantic` validate against expected model → return typed object, or
  raise `LLMRepairError` with original text + repair attempts attached
- callers never see raw LLM output. They get either a validated object
  or a `LLMError` / `LLMRepairError`.

### LLM client priority gate
- ollama serves one request at a time well; concurrent requests degrade
  latency. `caden/llm/client.py` owns a single-slot semaphore so only one
  call hits ollama at a time.
- the slot is priority-aware: foreground requests (chat reply, add-task
  scheduling) preempt background requests (rater, why-rationale worker).
  A background call in flight when a foreground request arrives is
  raised as `LLMAborted`; the background worker catches that specific
  class and re-queues itself.
- this is mechanism, not heuristic: it preserves the "chat is
  responsive" property without encoding any rule about Sean.

### LLM context budgeting
- top-K = 20 retrieved memories per prompt (combined-score ranked)
- each retrieved memory's raw_text truncated to 500 chars in the prompt
- total prompt budget configurable; default 6000 tokens
- if prompt would exceed budget, truncate retrieved memories from the
  bottom of the rank until it fits. If truncation drops below K=5,
  raise `LLMError` (loud) — that means context is too rich and we should
  be smarter about retrieval, not silently drop signal.

### Statistical methods (libraries and which to use where)
- residual aggregation and rolling stats: pandas
- residual fits / weight learning: scikit-learn `Ridge` regression by
  default
- nearest-neighbor retrieval scoring: scikit-learn `NearestNeighbors`
- trend detection (residual rising or falling over time): Mann-Kendall
  via `pymannkendall`
- bias detection (phase-change vs miscalibration): one-sample sign test
  via `scipy.stats.binomtest` over residual signs
- Pareto ranking (active optimization, post-v0): own thin implementation
  is acceptable here; it's two for-loops, not statistics

### Logging
- `structlog` setup lives in `caden/log.py`, writing JSON lines to
  `~/.local/share/caden/logs/caden.log`
- log lines also captured as low-priority events (source =
  `caden_log`) so CADEN can reason about its own behavior over time
- log level configurable; default INFO

### Diagnostic log (TUI escape hatch)
- `caden/diag.py` writes a parallel human-readable plain-text log to
  `~/.caden/diag.log`. Every LLM call, every scheduler outcome, every
  raised `CadenError` gets one line.
- rationale: Textual's TUI is hard to copy text out of mid-session.
  The diag log gives Sean (and any debugging LLM) a tail-able file with
  the same information the JSON log carries, in a form a human can read
  without `jq`.
- diag is auxiliary. If diag write fails, the original event is
  unaffected; the failure is logged through structlog and that's it.
  This is the second permitted partial success in CADEN, and like
  `why`, it's permitted because diag is purely diagnostic.

### Concrete v0 first-time scheduling rule
When a task arrives and there is no relevant history:
- CADEN reads existing Google Calendar items between now and the deadline
  across all CADEN-enabled calendars (see "Google scope" below)
- the LLM is given: the task description, the deadline, the calendar
  events in that window, and recent events from Libbie's retrieval
  (so it can see what Sean has been doing)
- the LLM picks a concrete start/end and emits its own duration and
  confidences. The framework imposes no default duration and no
  confidence floor. "Estimators never fake a number" applies to the
  framework, not to the LLM — the model is allowed to reason from
  whatever signal it has (including "none") and own the result.
- duration_min on the schedule block is `end - start` by definition;
  it is not an LLM field and not a fallback.
- if the LLM genuinely cannot estimate a state axis, it returns null
  for that axis and null confidence; the framework writes the nulls
  through verbatim. NULL means unknown.
- no chunking in v0 first-schedules. Chunking unlocks once duration
  predictions earn higher confidence.
- no working-hours constraint imposed by CADEN. Working-time preferences
  are something CADEN learns from residuals over time, not a setting.

### Task completion handling (edge cases)
On completion at time `T`:
- normal case (`T >= scheduled_start`): event end time edited to `T`,
  start unchanged. Duration residual = (T - scheduled_start) − predicted
  duration. State residuals computed from ratings near the window.
- early-completion case (`T < scheduled_start`): event shifted to
  `[T − predicted_duration, T]`. This preserves predicted duration on
  the calendar (your "started where it actually started" preference)
  but means no duration residual is computed for this attempt. State
  residuals still apply.
- bulk completion (Sean marks 5 done in 30 seconds): each is processed
  in arrival order, sequentially through the write queue. No batching
  shortcut.
- completion arriving for a task with no paired event: loud
  `SchedulerError`. This is a bug, not a graceful case.

### Task completion detection
- poll Google Tasks every 60 seconds while CADEN is running
- detect `status == 'completed'` transitions vs the last-seen state
  cached in `tasks` table
- 60-second cadence is a bootstrap value (see below); learned-tunable

### Google integration scope
- on first OAuth, CADEN enumerates available calendars and tasks lists
- a settings panel (in dashboard config, not a separate UI in v0;
  visible as a settings command from the chat) lets Sean check/uncheck
  which calendars and tasks lists CADEN may read and write
- CADEN never touches an unchecked calendar or list
- enabling/disabling a calendar is an event (so retrieval can see when
  scope changed)
- writes (new tasks, new events from add-task button) go to a Sean-
  designated default calendar and tasks list (chosen in the same
  settings panel; required before add-task button is usable)

### Chat events
- only Sean's messages are stored as events with embeddings
  (`source = 'sean_chat'`)
- CADEN's responses are NOT stored as events. They are visible in the
  chat panel during the session but ephemeral from a memory standpoint.
- conversation coherence within a session: CADEN's last few responses
  live in a process-local `deque` (cap 4) inside the chat widget and
  are passed as immediate context to the next LLM call. They are never
  persisted, never embedded, never retrieved. The deque empties on
  shutdown.
- retrieval explicitly excludes any `caden_chat` source as defense in
  depth, even though no such event should ever be written.
- this keeps memory pristine to Sean's signal and avoids CADEN
  retrieving its own old answers as if they were ground truth.

### Chat context packaging
- `caden/libbie/curate.py` owns a `package_chat_context()` function
  that assembles the user-prompt body for chat: Libbie retrieval +
  "live world" context (today's calendar, open tasks). Single place
  so the chat widget, add-task scheduler, and rater don't each
  reinvent context shape.
- this is mechanism, not policy: curate decides nothing about what
  matters; it just composes what retrieval and the live-world readers
  return.

### PM and chat
- dashboard chat events have `project_id = NULL` always
- Libbie's retrieval for the dashboard chat reads across all events
  including PM-tagged ones, so cross-pollination still works
- PM gets its own conversational surface in a future doc; until then,
  the dashboard chat is the only chat surface

### Intake and the rater
- intake events (`source IN ('intake_self_knowledge',
  'intake_code_pattern')`) are NOT rated by the rater
- the rater filters out intake sources before processing
- intake events still participate in retrieval normally
- this is the one event-class exception to "everything gets rated";
  rationale: intake is meta-content about Sean, not events Sean
  experienced

### Default LLM model
- configured in `~/.config/caden/settings.toml` as `llm.model`
- Sean's stated preference: `qwen3.5:9b` (verify exact ollama tag at
  install time; ollama tag list may vary)
- embedding model: `nomic-embed-text` (768 dims; matches schema's
  embedding column size)

### Sprocket sandbox
- `firejail --net=none --private=<scratch_folder> --quiet python <script>`
- timeout: bootstrap 30s, learned-tunable
- network can be enabled per-attempt only when the brief explicitly
  requires it AND Sean acknowledges; default is no-network

### Bootstrap values (the rules-vs-gates distinction)
Some numbers must exist before learning kicks in. To stay clear of
"hand-written heuristics," CADEN treats them as gates, not rules:
- all bootstrap values live in `caden/config.py` with `BOOTSTRAP_*`
  prefix and a comment explaining the gate they unlock
- on first use, each bootstrap value is logged as an event with source
  `bootstrap_value_used` and metadata describing it
- the learning system is required to override each bootstrap value
  within a defined number of relevant events (also a bootstrap value;
  it's bootstraps all the way down, but the chain is finite)
- Sean can see the current value of every bootstrap on the dashboard's
  audit surface (post-v0)

Concrete bootstrap values used in v0:
- `BOOTSTRAP_COMPLETION_POLL_SECONDS = 60`
- `BOOTSTRAP_PROMPT_TOKEN_BUDGET = 6000`
- `BOOTSTRAP_RETRIEVAL_TOP_K = 20`
- `BOOTSTRAP_RETRIEVAL_TRUNCATE_CHARS = 500`
- `BOOTSTRAP_RETRIEVAL_MIN_K = 5` (the floor below which prompt-budget
  truncation raises `LLMError` instead of silently dropping signal)
- `BOOTSTRAP_FOCAL_TEXT_TRUNCATE_CHARS = 2000` (cap on the focal event
  body itself when fed to the rater / chat prompt; complements the
  per-retrieved-memory truncate)
- `BOOTSTRAP_SCHEDULER_MAX_CALENDAR_EVENTS = 40` (cap on calendar items
  passed to the scheduler LLM when picking a block)
- `BOOTSTRAP_SCHEDULER_EVENT_SUMMARY_CHARS = 80` (per-calendar-event
  summary truncate at the same surface)
- `BOOTSTRAP_SANDBOX_TIMEOUT_SECONDS = 30` (Sprocket; not v0)
- `BOOTSTRAP_REFIT_MIN_RESIDUALS = 50` (learning system; not v0)
- `BOOTSTRAP_TEMPLATE_CLUSTER_MIN = 5` (Sprocket; not v0)

If any bootstrap value feels like it's about Sean specifically rather
than about "data must exist before math can run," it's actually a
heuristic and must be removed. Audit on every release.

## Open Questions (still honest, not pre-decided)
- what does "balance all three" mean mathematically once CADEN is ready
  to actually optimize? v0 punts on this by not comparing alternatives;
  the post-v0 design is in `CADEN_learning.md`.
- how does CADEN distinguish "this prediction was wrong because Sean
  changed" from "this prediction was wrong because the mechanism is
  miscalibrated"? See `CADEN_learning.md` Phase-Change section.
- how does the LLM propose new schema fields without that itself
  becoming a hand-written heuristic about what matters? See
  `CADEN_learning.md` Schema Growth section.

## v0 Implementation Plan

### Project layout
Single Python package. Modules are thin, each owns one concern.

```
caden/
  __init__.py
  main.py                # entry point: boot sequence + launch Textual app
  config.py              # loads settings (ollama model, paths, google creds)
  errors.py              # CadenError hierarchy; nothing is caught silently
  log.py                 # structlog setup (JSON log file)
  diag.py                # plain-text diagnostic log (TUI escape hatch)

  libbie/                # the memory layer; owns the DB
    __init__.py
    db.py                # sqlite + sqlite-vec connection, schema, migrations
    store.py             # write events, write ratings, write predictions
    retrieve.py          # embedding + metadata search
    curate.py            # package_chat_context(): retrieval + live world

  llm/
    __init__.py
    client.py            # ollama wrapper + priority-aware single-slot gate
    repair.py            # tolerant parsing layer between client and callers
    embed.py             # nomic-embed-text wrapper

  rater/
    __init__.py
    rate.py              # mood/energy/productivity rating per event

  scheduler/
    __init__.py
    schedule.py          # pick when a task runs; split into chunks
    predict.py           # emit prediction bundle at scheduling time
    residual.py          # compute + store residuals on task completion

  google_sync/
    __init__.py
    auth.py              # OAuth dance + token refresh
    calendar.py          # read + write calendar events
    tasks.py             # read + write tasks
    poll.py              # poll Google Tasks for completion transitions
                         # (webhook deferred; local desktop has no public URL)

  ui/
    __init__.py
    app.py               # Textual App; tab container
    dashboard.py         # today | chat | next 7 days
    chat.py              # middle panel widget
    add_task.py          # add-task button + modal form
    edit_task.py         # edit-task modal (description / deadline)
    _error.py            # error banner modal screen (boot + runtime)
    services.py          # DI bundle: config, db, llm, embedder for widgets

  util/
    __init__.py
    timefmt.py           # 12-hour AM/PM display helpers
```

### Boot sequence
Every step must fail loudly and stop if it cannot complete.
1. load config
2. open sqlite DB, apply schema / migrations, verify sqlite-vec loads
3. verify ollama is reachable and the configured model is present
4. verify nomic-embed-text is available
5. load Google OAuth credentials; refresh if needed
6. launch Textual app

If any of these fails, CADEN exits with a readable error. No partial startup.

Sole softening: step 5 is allowed to be absent. If the Google credentials
file is missing, CADEN still boots and runs chat-only; the dashboard
renders "Google not configured" in the today / 7-day panels. Once
credentials are present, all subsequent Google failures are loud as
specified. This single allowance exists because chat must work before
Google is wired up; every other failure mode remains loud.

### Schema (v0)
Single DB, multiple tables, all keyed by integer id + timestamp.

- events: id, timestamp, source, raw_text, embedding
- ratings: id, event_id, mood, energy, productivity, confidence_mood,
  confidence_energy, confidence_productivity, rationale, created_at
- predictions: id, task_id, google_event_id, predicted_duration_min,
  pred_pre_mood, pred_pre_energy, pred_pre_productivity, pred_post_mood,
  pred_post_energy, pred_post_productivity, confidences (one per axis),
  created_at
- residuals: id, prediction_id, duration_actual_min, duration_residual_min,
  pre_state_residuals (resolved later), post_state_residuals (resolved
  later), created_at
- tasks: id, google_task_id, description, deadline, status, created_at,
  completed_at
- task_events: id, task_id, google_event_id, chunk_index, chunk_count

Ratings, predictions, and residuals are all also stored as events (with the
right source tag) so Libbie can retrieve them through the same search as
everything else. The typed tables just give fast structured access; the
event table is the canonical memory.

### Milestones
Milestones are ordered. Each one is independently runnable.

Milestone 1 — Skeleton that stores.
- Textual app with one tab (dashboard), three panels
- middle panel is a chat widget; Sean types, CADEN echoes
- every message from Sean and every response from CADEN is written to events
  with embedding
- today and 7-day panels show placeholder text
- sqlite-vec verified working with nomic-embed-text vectors

Milestone 2 — LLM round trip.
- CADEN responds with an actual ollama call
- repair layer in place; caller gets clean JSON or a loud error
- response is stored in events like any other message
- simple retrieval: last N related events by embedding similarity, fed into
  the prompt

Milestone 3 — Google sync read-only.
- OAuth flow works
- today panel renders Google Calendar events for today
- 7-day panel renders the next 7 days
- Google Tasks rendered inline with events, ordered by start/due time

Milestone 4 — Add-task button and CADEN writes back.
- add-task modal form on dashboard; requires description + deadline
- submitting creates a Google Task + paired Google Calendar event via CADEN
- scheduling picks any reasonable block within the deadline (no learning yet;
  low confidence recorded)
- prediction bundle emitted at scheduling time and stored in predictions +
  events
- task and paired event linked in tasks / task_events

Milestone 5 — Completion and residuals.
- detect task completion (poll Google Tasks, or listen via push if feasible)
- on completion, edit paired event's end to now; duration residual computed
  and stored
- state residuals filled in from ratings of events near the task window

Milestone 6 — Rater live.
- every new event triggers a rating LLM call with Libbie retrieval
- ratings stored, immutable; they feed back into future retrievals
- estimators return \"unknown\" when retrieval is too thin; never fake numbers

After Milestone 6, v0 is complete.

### What is explicitly out of scope for v0
- Project Manager, Thought Dump, Sprocket apps
- active schedule comparison or optimization
- schema growth mechanism
- phase-change detection
- SearXNG web research
- cross-device sync

### Minimum residual-tracking machinery for day one
So learning can begin the moment data flows:
- predictions table populated from Milestone 4
- residuals table populated from Milestone 5
- a single view or query that aggregates residuals by mechanism so CADEN can
  see which piece is weakest. Aggregation uses pandas; no bespoke math.

## Deprecated Sections (history only, do not build from these)
Kept for record. These reflect earlier thinking that the no-heuristics rule
retired. Do not treat them as design.

### Deprecated: Somatic Primitives (valence / arousal / clarity)
Rejected because picking which dimensions matter is itself a heuristic about
Sean. If primitives earn their way back in, it will be because residuals
demanded them, not because we chose them.

### Deprecated: Derived Signals (burnout_proximity, momentum, mood_drift)
Same reason. Naming what matters before CADEN has data is pollution.

### Deprecated: Case-Based Reasoning with a Four-Component Fingerprint
The mechanism (store situations, match, reuse) is not inherently a heuristic,
but the four-component fingerprint (state / temporal / external / semantic) is
a designer's guess at what makes situations similar. Rejected. If case-like
behavior emerges, it will come from residuals selecting which retrieved events
produced good predictions, not from a fingerprint schema written in advance.

### Deprecated: Situation Type Taxonomy
Enumerating sean_chat / thought_dump / task_overdue / calendar_approaching /
time_tick / silence is a heuristic that pre-decides how CADEN should chunk the
world. Rejected. Source field is enough.

### Deprecated: Anticipation Physics for External Items
The idea that calendar events carry learned affective signatures is still
appealing, but writing the form of anticipation (recency-weighted mean of
similar items, etc.) is a designer's rule. Rejected as written. If anticipation
emerges, it emerges because Libbie's retrieval over past mentions of similar
items naturally surfaces them when a new instance approaches.

### Deprecated: Escalation Policy (reuse / adapt / fresh)
The thresholds and branches were a hand-written control flow. Rejected.

### Deprecated: Staged Experiment Plan
The staging was built around introducing primitives then CBR then learned
mappings. Since those ideas are retired, the staging is too.

## Scratchpad
- 

Every trigger type is its own partition for case matching. A calendar event
approaching is never the same situation as a thought dump, even if Sean's
state looks identical