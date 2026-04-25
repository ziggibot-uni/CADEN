# CADEN v0 Build Brief

**Status:** `locked`

**Audience:** the build agent (a coding LLM building CADEN v0). If that's
you, **read this file in full before reading anything else**, and then
read only the files this brief tells you to read.

---

## Build Agent Rules (non-negotiable)

1. **You are building v0 only.** Do not implement anything from
   `CADEN_learning.md`, `CADEN_dashboard.md`, `CADEN_project_manager.md`,
   `CADEN_thought_dump.md`, `CADEN_sprocket.md`, `CADEN_libbie.md`'s
   post-v0 sections, or `CADEN_intake.md`. Those are post-v0. Do not
   read them while building v0.
2. **Do not invent values.** Every parameter, threshold, default, and
   constant in v0 either comes from `CADEN_v0.md`'s Implementation
   Contracts section or this brief. If a value seems to be missing,
   halt and ask Sean. Do not guess.
3. **Do not write fallbacks.** No silent recovery. No "try this and
   if it fails do that." Catch only to re-raise as a `CadenError`
   subclass with context, or at the top-level UI handler.
4. **Do not write hand-written rules about Sean.** No "if it's morning
   then..." No "weekends are different." No "category X means Y." Only
   generic mechanisms over data. If you find yourself writing such a
   rule, halt and ask Sean.
5. **Do not pollute the schema.** v0 schema is fully specified in
   Implementation Contracts. Do not add fields. Schema growth is a
   post-v0 mechanism with its own gating.
6. **No unit-test sprawl.** v0 ships with one end-to-end smoke test
   per milestone, exercising the happy path only. Do not write
   defensive tests for edge cases the design rejects (e.g., do not
   test "what if the LLM is unreachable and we want to fall back" —
   the answer is loud failure, the test is "loud failure happens").
7. **If you are stuck, halt and ask Sean.** Do not paper over
   confusion with a guess. Sean can write code. Sean cannot read your
   mind. The honest stop is the cheap stop.

---

## Reading Order for the Build

In this exact order. Read each fully before moving on.

1. `CADEN.md` — the spec. Locked. Do not edit.
2. `CADEN_v0.md` — the v0 plan and the Implementation Contracts. This
   is your primary reference for the entire build.
3. This file (`CADEN_build_brief.md`) — file-by-file responsibilities,
   function signatures, prompt templates, test strategy.

That is all you read while building v0. The other docs exist for
post-v0 work and will mislead you if you read them now.

---

## File-by-File Shopping List

These are the files you create. Each is small and focused. Imports
are `from caden.<subpackage>.<module> import <thing>`.

### `caden/__init__.py`
Empty.

### `caden/main.py`
Entry point. Runs the boot sequence in `CADEN_v0.md` and launches the
Textual app. Catches `CadenError` at the top level and prints the
banner before exiting.

### `caden/config.py`
- Reads `~/.config/caden/settings.toml` via `tomllib`.
- Exposes a `Settings` pydantic model with all fields typed.
- Defines all `BOOTSTRAP_*` constants listed in Implementation
  Contracts.
- On first launch, writes a default `settings.toml` if one does not
  exist (this is not a fallback; it's an installer step).

### `caden/errors.py`
- `class CadenError(Exception)` plus subclasses: `LibbieError`,
  `LLMError`, `RaterError`, `SchedulerError`, `GoogleSyncError`,
  `UIError`. (No `SprocketError` in v0.)
- All accept a message and optional `original` exception that is
  chained via `raise ... from`.

### `caden/libbie/db.py`
- `async def open_db() -> aiosqlite.Connection` — opens the DB at
  the configured path, loads sqlite-vec, sets WAL mode, applies
  Alembic migrations on connect, returns the connection.
- `async def health_check(conn) -> None` — verifies sqlite-vec is
  loaded and the schema version matches; raises `LibbieError`
  otherwise.

### `caden/libbie/store.py`
The single async write queue lives here. Public API:
- `async def capture_event(source: str, raw_text: str, ts_utc: datetime,
  metadata: dict[str, str] | None = None) -> int`
  — writes one row to `events`, computes embedding (synchronously
  awaits `embed.embed_text`), inserts metadata rows, returns event id.
  Schedules a `why`-rationale background task.
- `async def write_rating(event_id: int, mood: float|None,
  energy: float|None, productivity: float|None, conf_mood: float|None,
  conf_energy: float|None, conf_productivity: float|None,
  rationale: str) -> int`
- `async def write_prediction(...) -> int` — full signature matches
  the `predictions` columns in Implementation Contracts.
- `async def write_residual(prediction_id: int, **kwargs) -> int`
- `async def write_task(...) -> int` and
  `async def write_task_event(...) -> int`
- All writes go through one `asyncio.Queue`; one consumer coroutine
  serializes them.

### `caden/libbie/retrieve.py`
- `async def retrieve(query_text: str, top_k: int = 20,
  filter_sources: list[str] | None = None,
  exclude_sources: list[str] | None = None) -> list[Memory]`
  — embeds the query, runs sqlite-vec KNN, applies optional source
  filters, returns ranked memories.
- `class Memory` — pydantic model with `id`, `ts_utc`, `source`,
  `raw_text`, `metadata: dict[str, str]`, `score: float`.
- `def truncate_for_prompt(memories: list[Memory], char_budget: int =
  500) -> list[Memory]` — returns memories with `raw_text` clipped.

### `caden/libbie/why_worker.py`
Background coroutine that pulls events lacking a `why` metadata row,
calls `llm.client.complete` with the why-rationale prompt template,
writes the metadata row. Failures log loudly but do not raise.

### `caden/llm/client.py`
- `async def complete(prompt: str, schema: type[BaseModel] | None
  = None, max_tokens: int = 1000) -> str | BaseModel`
  — calls ollama HTTP API, runs result through `repair.parse` if
  `schema` is given, returns either the raw string or a typed
  pydantic instance. Raises `LLMError` on failure.
- Reads model name from settings (`llm.model`).

### `caden/llm/repair.py`
- `def parse(raw: str, schema: type[BaseModel]) -> BaseModel`
  — strips code fences, runs `json_repair.loads`, validates with
  pydantic, raises `LLMError` if validation fails after repair.

### `caden/llm/embed.py`
- `async def embed_text(text: str) -> bytes`
  — calls ollama's embedding endpoint with `nomic-embed-text`,
  returns bytes formatted for sqlite-vec storage. Raises `LLMError`
  on failure.

### `caden/rater/rate.py`
- `async def rate_event(event_id: int) -> int | None`
  — fetches event, retrieves relevant past events + ratings + Sean's
  self-knowledge memories, builds rater prompt (template below),
  calls LLM with the `RatingResponse` pydantic schema, writes a
  `ratings` row, returns its id. If `event.source` is in the rater's
  skip-list (intake sources), returns `None` and writes nothing.
- Triggered by a background coroutine that subscribes to capture
  events.

### `caden/scheduler/predict.py`
- `async def emit_prediction(task_id: int, google_event_id: str,
  predicted_duration_min: int) -> int`
  — builds prediction prompt with retrieval, calls LLM with the
  `PredictionResponse` pydantic schema, writes `predictions` row,
  returns its id.

### `caden/scheduler/schedule.py`
- `async def schedule_task(description: str, deadline_utc: datetime)
  -> tuple[int, str]`
  — creates a Google Task, picks a Calendar slot via the schedule
  prompt (template below), creates the paired Calendar event,
  writes `tasks` and `task_events` rows, returns
  `(task_id, google_event_id)`.

### `caden/scheduler/residual.py`
- `async def on_task_completed(task_id: int, completed_at_utc:
  datetime) -> None`
  — applies the completion-handling rules from Implementation
  Contracts (edit event end, or shift if early), computes residuals
  from nearby ratings, writes `residuals` row.

### `caden/google_sync/auth.py`
- `def get_credentials() -> Credentials` — handles the OAuth flow,
  caches token in `~/.config/caden/google_token.json`, refreshes
  as needed.

### `caden/google_sync/calendar.py`
- `async def list_events(calendar_id: str, time_min: datetime,
  time_max: datetime) -> list[CalendarEvent]`
- `async def create_event(...) -> str` — returns google_event_id.
- `async def update_event_times(google_event_id: str,
  start: datetime, end: datetime) -> None`

### `caden/google_sync/tasks.py`
- `async def list_tasks(tasklist_id: str) -> list[GoogleTask]`
- `async def create_task(...) -> str`
- `async def find_completions_since(tasklist_id: str,
  since: datetime) -> list[GoogleTask]`

### `caden/google_sync/poller.py`
- Background coroutine that runs every
  `BOOTSTRAP_COMPLETION_POLL_SECONDS` seconds, finds completed
  tasks, dispatches `scheduler.residual.on_task_completed`.

### `caden/ui/app.py`
- `class CadenApp(textual.app.App)` — the main app, single tab in v0.

### `caden/ui/dashboard.py`
- Three-panel layout using Textual's `Horizontal` containing three
  `Vertical` widgets. Left = today list, middle = chat, right =
  7-day list. Width ratios roughly 1:2:1.

### `caden/ui/chat.py`
- `class ChatPanel(Widget)` — input box at bottom, scrolling history
  above, calls `capture_event` on submit, calls `llm.client.complete`
  for response, displays response.

### `caden/ui/add_task.py`
- `class AddTaskModal(ModalScreen)` — description + deadline form,
  submits to `scheduler.schedule.schedule_task`.

### `caden/libbie/migrations/`
Alembic migrations directory. Versioned schema as defined in
Implementation Contracts. Migration `0001` creates all tables.

### `tests/`
One smoke test per milestone (see Test Strategy below).

---

## Prompt Templates

These are the canonical prompts. Do not deviate in style. All prompts
ask for JSON output and pair with a pydantic schema for repair-layer
validation.

### Rater prompt

```
You are CADEN's internal rater. Your job is to estimate Sean's mood,
energy, and productivity at the moment of this event, on a scale of
0.0 (lowest) to 1.0 (highest). Confidences are also 0.0 to 1.0.

If you cannot reasonably estimate any axis given the context, return
null for that axis's score AND null for its confidence. Do not guess.

EVENT:
ts_utc: {ts_utc}
source: {source}
text: {raw_text}

RELEVANT PAST EVENTS WITH RATINGS (most relevant first):
{past_events_block}

RELEVANT THINGS SEAN HAS SAID ABOUT HIMSELF:
{self_knowledge_block}

Return JSON exactly matching this schema:
{
  "mood": float|null,
  "energy": float|null,
  "productivity": float|null,
  "conf_mood": float|null,
  "conf_energy": float|null,
  "conf_productivity": float|null,
  "rationale": string
}
```

Pydantic schema: `RatingResponse` in `caden/rater/rate.py`.

### Why-rationale prompt

```
A new memory was just captured in CADEN's database. In one short
sentence, state why this memory might be worth retrieving later.
Do not summarize. Do not editorialize. State the retrieval-relevance.

MEMORY:
ts_utc: {ts_utc}
source: {source}
text: {raw_text}

Return JSON:
{ "why": "<one short sentence>" }
```

Pydantic schema: `WhyResponse`.

### Schedule prompt (v0 first-time)

```
You are CADEN's scheduler. Sean has just added a task. Choose when
to schedule it.

TASK:
description: {description}
deadline_utc: {deadline_utc}

PREDICTED DURATION (default v0): 60 minutes.

OPEN BLOCKS (>= 60 minutes) on Sean's enabled calendars between now
and the deadline, sorted by start time:
{open_blocks_block}

RECENT RELEVANT EVENTS:
{retrieval_block}

Pick one block. If none of the listed blocks fit comfortably, pick
the earliest one and lower your confidence.

Return JSON:
{
  "chosen_block_index": int,
  "confidence": float,
  "reasoning": string
}
```

Pydantic schema: `ScheduleResponse`. Confidence here informs the
prediction bundle's confidences (all axes get
`min(BOOTSTRAP_FIRST_SCHEDULE_CONFIDENCE, this.confidence)`).

### Prediction prompt (state pre/post)

```
A task is about to be scheduled. Predict Sean's mood, energy, and
productivity just before and just after the scheduled block, on
0.0-1.0 scales. If you cannot reasonably estimate, return null and
null confidence.

TASK:
description: {description}
scheduled_start_utc: {start_utc}
scheduled_end_utc: {end_utc}

RELEVANT PAST EVENTS WITH RATINGS:
{past_events_block}

RELEVANT THINGS SEAN HAS SAID ABOUT HIMSELF:
{self_knowledge_block}

Return JSON:
{
  "pre_mood": float|null, "pre_energy": float|null,
  "pre_productivity": float|null,
  "post_mood": float|null, "post_energy": float|null,
  "post_productivity": float|null,
  "conf_pre_mood": float|null, "conf_pre_energy": float|null,
  "conf_pre_productivity": float|null,
  "conf_post_mood": float|null, "conf_post_energy": float|null,
  "conf_post_productivity": float|null,
  "rationale": string
}
```

Pydantic schema: `PredictionResponse`.

### Chat prompt (Milestone 2 onward)

```
You are CADEN, Sean's executive-function assistant. Sean has ADHD,
autism, bipolar, and synesthesia. CADEN is local, private, and not
cloud-backed.

Sean said:
{sean_message}

Relevant memories Libbie surfaced:
{retrieval_block}

Recent conversation in this session (NOT stored in memory; just
context):
{recent_turns_block}

Reply to Sean. Be direct, do not pad, do not compliment, do not
add disclaimers.
```

Free-text response; no schema validation needed.

---

## Test Strategy

One smoke test per milestone. Tests live in `tests/`. Each is a single
Python file with one async test function and the minimum fixture
plumbing.

- `tests/test_m1_skeleton.py` — launch app, send a chat message,
  assert event row exists with embedding length 768.
- `tests/test_m2_llm_roundtrip.py` — mock ollama with a fake server
  returning known JSON; assert the chat response goes through the
  repair layer cleanly; assert retrieval is fed into the prompt.
- `tests/test_m3_google_read.py` — mock Google API; assert today and
  7-day panels render fixture events.
- `tests/test_m4_addtask.py` — mock Google APIs; submit add-task
  modal; assert Google Task created, Calendar event created, tasks
  + task_events + predictions rows exist.
- `tests/test_m5_completion.py` — mark fixture task complete; assert
  event end edited, residuals row exists with duration_residual_min.
- `tests/test_m6_rater.py` — capture a chat event; assert ratings
  row created with all six fields; capture an `intake_self_knowledge`
  event; assert no ratings row created.

Do NOT write more tests than this for v0. Edge cases come later.

---

## Stop Conditions

When you complete each milestone, stop and tell Sean. Do not
continue to the next without confirmation. The milestones are gates,
not a chain.

When v0 is complete (Milestone 6 smoke test passes), stop. Do not
start post-v0 work without Sean reading the post-v0 docs himself
and directing you.

If you encounter any of the following, halt immediately and ask
Sean:
- a value seems missing from the contracts
- two contracts seem to contradict each other
- a milestone seems to require a feature not yet built
- a library on the install list does not exist or has been renamed
- the desired behavior is unclear

---

## Locked Constraints (one more time)

- No hand-written heuristics. Not one.
- No fallbacks. Loud failure only.
- Python only.
- Local-first. Private.
- Declared objective: track mood, energy, productivity; balance all three.
- One central mechanism: Predict, Observe, Correct.
