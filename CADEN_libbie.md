# Libbie (Post-v0)

**Status:** `draft`

**Purpose:** Plan Libbie's capabilities beyond what v0 delivers. v0 gives
her a single sqlite+sqlite-vec DB, an `events` table with embeddings, and
basic top-k retrieval fed into prompts. This doc plans everything else she
becomes.

**Depends on:** `CADEN.md`, `CADEN_index.md`, `CADEN_v0.md`. Some sections
interact with `CADEN_learning.md` (retrieval weight learning, decay,
phase-change); those mechanics live there, this doc only describes how
Libbie exposes and uses them.

---

## Locked Constraints (from `CADEN.md`)

- No hand-written heuristics. Not one.
- No fallbacks. Loud failure only.
- Python only.
- Local-first. Private.
- Declared objective: track mood, energy, productivity; balance all three.
- One central mechanism: Predict, Observe, Correct.

Libbie-specific constraints from the spec:

- **One DB for everything.** Memory must not be fragmented. Every app in
  CADEN stores through Libbie or not at all. No sibling tables with
  parallel embeddings. No per-app vector stores.
- **Sean never speaks to Libbie directly.** She is CADEN's memory. Her
  interface is internal; her influence surfaces only through CADEN's
  responses and behavior.
- **Metadata is mandatory.** Every memory records when and why it was
  captured and (when applicable) what triggered the capture.

---

## Scope

In scope for this doc:

- Libbie's internal API (how other CADEN components read and write
  memory)
- Metadata schema beyond v0's minimum
- Proactive surfacing (how Libbie volunteers memories, not just answers
  queries)
- Self-knowledge memories about Sean (the category that feeds the rater)
- SearXNG integration for public web lookup, with results captured as
  memories
- Project Manager integration (same DB, no fragmentation)
- How Libbie participates in Predict, Observe, Correct (retrieval as an
  estimator that emits predictions and earns residuals)

Out of scope for this doc (belong in `CADEN_learning.md`):

- The math of retrieval weight learning
- The math of decay and consolidation
- Phase-change detection
- Schema growth (LLM-proposed fields)
- Active optimization of mood/energy/productivity

Out of scope entirely:

- Code. This is planning.
- v0 material. If it's in `CADEN_v0.md`, don't repeat the plan here.

---

## What v0 Already Gives Libbie

Restated so this doc is self-contained:

- One sqlite DB with sqlite-vec.
- A raw `events` log that acts as immutable provenance.
- A curated `memories` layer that acts as the CADEN-facing reasoning unit.
- Typed sibling tables (`ratings`, `predictions`, `residuals`, `tasks`,
  `task_events`) for structured access; their rows are also recorded as
  events and may also yield curated memory rows when appropriate.
- Libbie-owned chat-context packaging that returns compact recalled-memory
  context rather than raw event dumps.
- Embedding via `nomic-embed-text`.

Everything below assumes this substrate exists.

---

## Ligands And Memory Frames In The Current Design

The design in this repo already has the right ownership boundary for the
new architecture:

- CADEN reasons.
- Libbie stores, canonicalizes, retrieves, filters, and packages.
- sqlite-vec does similarity only.
- A small ranking model can sit inside Libbie's retrieval pipeline
  without leaking its logic into CADEN.

The key design move is the unit of retrieval. CADEN receives compressed
recall packets derived from structured memory frames rather than raw event
rows. That requires splitting **capture-log storage** from **reasoning
memory**.

The committed shape for this repo is:

- Keep `events` as the immutable system log. Every chat, residual,
  prediction, task update, SearXNG fetch, and schema-growth action still
  lands there first.
- Add a Libbie-owned `memories` table for curated recall units. Each row
  stores the `@mem` fields (`id`, `type`, `domain`, `tags`, `context`,
  `outcome`, `hooks`, `embedding_text`) plus provenance back to the
  originating `event_id` when one exists.
- Move CADEN-facing retrieval off raw `events` and onto `memories`.
  The vector index should embed `embedding_text` only, exactly as the
  proposed design requires.
- Keep the raw event log available for audit, replay, residual analysis,
  and future re-canonicalization. CADEN should not read from it directly.

This preserves the current "one DB for everything" rule while stopping raw
event text from becoming the long-term reasoning unit.

### Canonical DSL meanings

These terms are now fixed across the docs:

- **MemoryFrame**: Libbie's canonical structured representation of a useful
  remembered unit. It is produced from raw provenance, stored in `memories`,
  and carries the fields that support meaning-preserving retrieval.
- **RecallPacket**: the compressed packet Libbie returns to CADEN for the
  current task. It is derived from retrieved memory frames and is shaped for
  immediate model use rather than full provenance display.
- **Ligand**: transient Libbie-only retrieval steering state built from the
  current task and context. It influences retrieval and ranking for one pass,
  is not stored as memory, and is not exposed as a public CADEN object.

### Where ligands belong

Ligands are a Libbie-only retrieval steering object. They are constructed
inside `libbie.retrieve(...)` from the current task/context, not in the chat
widget and not in CADEN's prompt code.

Concrete placement in this repo:

- `caden/ui/chat.py` passes only the current task text and recent
  ephemeral conversation to Libbie.
- `caden/libbie/curate.py` asks Libbie retrieval for a CADEN-ready
  context object, not assemble raw memory lines itself.
- `caden/learning/schema.py` is the right home for the stable typed DSL:
  `Ligand`, `MemoryFrame`, `RecallPacket`, `CadenContext`,
  `KnowledgePacket`, `Evaluation`.
- `caden/libbie/retrieve.py` owns ligand construction,
  vector-query preparation, deterministic filtering, optional judge-model
  ranking, and final recall-packet selection.

The ligand is not stored as memory. It exists for one retrieval pass,
influences the vector query and deterministic filters, then disappears.
If CADEN needs a hint of the current cognitive intent, Libbie can expose
that as a compressed line in the packaged context, but CADEN should not
see the full ligand object or perform any ligand logic.

### Capture and canonicalization pipeline

The current pipeline maps cleanly onto the write path this repo is adopting:

1. `store.write_event(...)` remains the capture-log entry point.
2. A new Libbie canonicalization step turns a raw event or web finding
   into one or more `MemoryFrame` objects.
3. Libbie generates `embedding_text` deterministically from the memory
   frame plus the current ligand-alignment terms.
4. Only that `embedding_text` is embedded into the vector table keyed to
   the memory row, not the raw event row.

This is the important separation:

- raw event text is for provenance and reconstruction
- memory frame fields are for meaning
- `embedding_text` is for vector similarity

v0 now adopts that separation as the memory contract. Post-v0 work deepens
the ranking, surfacing, and learning that operate on top of it.

Current status of canonicalization in this repo:

- the existence of a deterministic raw-event -> `MemoryFrame` step is part of
  the current v0 contract
- the exact transitional shaping rules now in code (token extraction,
  source-to-type mapping, synthetic hooks, summary shortening) are tolerated
  scaffolding, not frozen architecture
- the invariants that *are* committed are: provenance is preserved, required
  frame fields are populated, `embedding_text` is derived from the frame's
  meaning-bearing content, and CADEN consumes the resulting recall packets
  rather than raw events

This means future code may replace the current string-shaping details as long
as those invariants hold and the change moves toward a cleaner canonicalizer
rather than toward hand-written heuristics about Sean.

### Retrieval pipeline

For this repo, the retrieval flow is:

1. Build a ligand from current task + recent context.
2. Build a query string/object from task, ligand, candidate tags, and
   natural-language hooks.
3. Run vector search over memory `embedding_text`.
4. Apply deterministic Libbie-side filtering on domain, tags, hooks,
   provenance, any learned recency term, and a length penalty that favors
   shorter otherwise-similar memories.
5. Optionally send the surviving candidates plus the ligand to a small
   judge model for ranking.
6. Return top-k `RecallPacket`s.
7. Package those packets into `@context` for CADEN.

This is the stricter separation the docs now commit to, and it is the right
direction for keeping a 9B model focused on immediately usable memory.

The length penalty is intentional. Libbie should prefer concise memories when
semantic similarity is otherwise close, because shorter notes reduce prompt
bloat and exert pressure toward denser memory writing over time.

One caution: the proposed fixed score

`embedding_similarity * 0.5 + hook_match * 0.3 + tag_overlap * 0.2`

is acceptable as a temporary adapter, but it should not become a
permanent hand-tuned policy because the top-level spec forbids that kind
of bespoke heuristic. In this repo, treat those constants as initial
weights that later migrate under `CADEN_learning.md`'s residual-driven
weight learning.

### SearXNG's role

SearXNG should not be a general runtime dependency of CADEN's reasoning
loop. It is a Libbie enrichment tool.

Use it in three places only:

- when canonicalization detects a factual gap while forming a memory
  candidate
- when retrieval is thin and Libbie decides external grounding is worth
  creating as a new memory candidate
- when ligand refinement needs better domain terms to improve retrieval

The output should first become `@knowledge`, then either:

- be folded into a new `MemoryFrame`, or
- refine the current ligand before the ranking pass

Do not pass raw SearXNG results straight to CADEN. Keep CADEN consuming
only the same high-signal compressed memory context.

### Current boundary versus post-v0 work

What is already current-scope truth:

- raw events remain provenance
- curated memories are the CADEN-facing recall layer
- ligand ownership belongs to Libbie
- vector search should be over memory `embedding_text`
- SearXNG, when present, belongs on the Libbie side rather than being a
  direct answer surface for CADEN

What remains post-v0:

- learned retrieval weighting replacing temporary fixed scoring adapters
- richer proactive surfacing mechanisms
- schema-growth decisions triggered from residuals
- broader app integration beyond the v0 Dashboard surface

---

## Post-v0: Libbie's Internal API

Libbie is consumed by every other CADEN component. The API is the only
legal way to touch memory. No component opens the DB directly.

Conceptual surface (planning-level, not code):

- **capture(event)** — write an event. Embedding happens here, loudly
  failing if the embedder is unreachable. Metadata is required.
- **retrieve(query, context)** — return memories relevant to the query.
  The "context" argument lets callers pass the current situation
  (timestamp, active task, recent events) so retrieval can be
  conditioned on more than the query string alone. How that
  conditioning is weighted is learned, not written.
- **surface(context)** — query-less retrieval. Libbie proposes memories
  that seem relevant to the current moment without being asked. This is
  how proactive resurfacing happens. See the dedicated section below.
- **annotate(event_id, metadata_patch)** — append metadata. Never
  overwrite. Annotation history is itself memory.
- **link(event_id_a, event_id_b, relation)** — record a relationship.
  Which relations exist is not pre-decided; they emerge as the system
  learns it needs them (see schema growth in `CADEN_learning.md`).

Hard rules for this surface:

- Callers never see raw rows. They see memory objects with stable
  fields. If the underlying schema grows, the API absorbs the change.
- Writes are append-only where possible. Ratings are immutable (already
  decided in v0). Metadata annotations accumulate.
- No caller may store embeddings outside Libbie. If a caller needs a
  semantic search, it goes through `retrieve` or `surface`.
- CADEN's own chat responses are NOT captured as events (see
  Implementation Contracts in `CADEN_v0.md`). Only Sean's inputs and
  external observations enter memory.
- Structural or non-experiential events may bypass the rater per the
  current Implementation Contracts. Retrieval policy is defined by the
  active source contract rather than by any one-off capture mode.

---

## Metadata Schema (beyond v0 minimum)

Metadata lives in a separate `event_metadata` table per the
Implementation Contracts in `CADEN_v0.md` (key/value rows, append-only,
linked to events by event_id). v0 already provisions this table, so
"post-v0" here means "new keys added over time," not "new schema."

The starting set below is justified by the spec line "keeps track of
metadata with each memory so that she can look at when and why something
was researched/found."

Starting metadata set:

- **captured_at** — system time of capture (distinct from `timestamp`,
  which may be the event's semantic time).
- **trigger** — what caused the capture. Examples: user chat,
  scheduled task completion, SearXNG query, Sprocket outcome,
  rating event, residual event. Source-like but finer: `source` says
  which surface, `trigger` says which action.
- **why** — a short LLM-generated rationale for why this memory was
  captured. Generated at capture time. Stored with the memory. Not
  retroactively rewritten.
- **linked_to** — optional event_id this memory is a direct response
  to (e.g. a rating points to the event it rated; a residual points
  to the prediction it closed).

Anything beyond this set is introduced by schema growth, not by this
doc. If Sean asks "shouldn't we also store X?", the answer is "only if
residuals show Libbie can't do her job without it."

---

## Proactive Surfacing

The spec says Libbie resurfaces memories "when CADEN needs them." That
is not reactive retrieval. Reactive retrieval is a caller asking. Proactive
surfacing is Libbie watching the current context and volunteering memories.

Design stance:

- Surfacing runs whenever the current context changes meaningfully. What
  counts as "meaningful change" is learned, not scheduled. (The learning
  mechanism lives in `CADEN_learning.md`.)
- Surfaced memories are attached to the current context as candidate
  retrievals. Downstream callers (the rater, the scheduler, the LLM
  chat loop) decide whether to consume them.
- Every surfacing act emits a prediction: Libbie predicts these memories
  will be useful. Usefulness is observed afterward (did the caller use
  them? did the downstream outcome match?). Residual is stored. This
  is how surfacing gets better without a hand-written rule.

No hand-written rule decides which memories get surfaced. No keyword
triggers, no tag triggers, no source-type triggers. The only inputs are
the current context and the residual-trained retrieval weights.

Failure modes:

- Surfacing returns nothing. Acceptable. Log the emptiness as an event
  (so residuals can see it).
- Surfacing returns garbage. Residuals catch this and retrieval weights
  adjust. No hand-written filter.

---

## Self-Knowledge Memories

A special category in practice, not in schema. These are memories about
Sean himself: preferences, patterns he's noticed, advice past-Sean wrote
to future-Sean, observations from Libbie about patterns in his events.

Why they need attention:

- The rater's prompt retrieves these to rate new events on mood, energy,
  productivity. They are the dominant influence on rating quality.
- If they're wrong, ratings are wrong, and the whole Predict-Observe-
  Correct loop is polluted at the source.

Design stance:

- Self-knowledge memories are not a separate table. They are events
  with a source that identifies them (e.g. `source = "sean_self_note"`
  for things Sean writes about himself; `source = "libbie_observation"`
  for patterns Libbie derives). The category is a query filter, not a
  schema split.
- Libbie-authored self-knowledge memories are predictions about Sean.
  Like every prediction, they earn residuals. If Libbie's observations
  about Sean keep producing bad ratings, the observations themselves
  get deprecated by the learning system, not by a hand-written purge.
- Sean-authored self-knowledge is immutable once captured, same rule
  as ratings. Sean can write a new note that contradicts an old one;
  both stay. Residuals decide which one retrieval weights favor.

Open question flagged, not answered: how does Libbie distinguish
self-knowledge from other events at retrieval time without hand-written
tagging? Candidate answer: she doesn't. Retrieval is unified. Self-
knowledge bubbles up because its embeddings cluster near the rater's
query. If that turns out to be insufficient, the learning system grows
a metadata field; a hand-written tag is never added.

---

## SearXNG Integration (Public Web Lookup)

Per spec: "uses a searxng docker container." Web searches return
results, results become memories.

Design stance:

- SearXNG runs as a local docker container on Sean's machine. Local-
  first is preserved because SearXNG itself is the privacy-preserving
  proxy; the queries leave the machine only to the extent SearXNG
  anonymizes them.
- CADEN decides when to search. Not a hand-written rule — the chat loop
  may request a search, the project manager may request one, or Libbie
  may surface "I don't have good memories for this" as a signal to the
  LLM which then chooses to search. All routes converge on one function:
  `libbie.search_web(query, context)`.
- Every search result is captured as an event. Source identifies it
  as a web result. Metadata records the query, the engine that returned
  it, the timestamp, and a `why` rationale generated at capture.
- Results are embedded and enter the same retrieval pool as every other
  memory. No separate web-results table.
- Loud failure if SearXNG container is unreachable. No fallback to a
  different engine, no cached-last-result shortcut, no silent skip.

Not decided here: rate limits, duplicate detection, freshness
preferences. These are learning problems and live in
`CADEN_learning.md`.

---

## Project Manager Integration

Per spec: Libbie "works out of the Project Manager as well."

Design stance:

- Project Manager entries (TODO, what-if, update, comment) are events.
  They go through `libbie.capture`. Same DB, same embeddings, same
  retrieval.
- The Project Manager app reads through Libbie's retrieval API to show
  related entries, related past projects, related thoughts from Thought
  Dump, related chats from the dashboard. No per-project memory silo.
- A project is not a first-class schema object yet. It's a queryable
  cluster of events that share a project reference. Whether project
  becomes a first-class field is a schema-growth question, not a
  pre-decision.

See `CADEN_projectManager.md` for the app itself. This doc only
asserts the memory discipline.

---

## Libbie Inside Predict, Observe, Correct

Every claim Libbie makes is a prediction and earns a residual.

Examples:

- `retrieve(query, context)` returns a ranked list. The ranking is
  a prediction that these memories will be useful to the caller. The
  caller's downstream success (e.g. rating matched observed outcome,
  scheduling matched actual duration) is the observation. Difference
  is the residual, stored against the retrieval act.
- `surface(context)` same thing, but unasked.
- `libbie_observation` events (Libbie-authored self-knowledge) are
  predictions about Sean. Ratings of future events are the observation.
- SearXNG results are predictions that the web answer is useful. If
  downstream CADEN behavior that used the result produces bad outcomes,
  the residual accrues against the web result.

This is the non-negotiable discipline: Libbie is not a dumb store. She
is an estimator like everything else in CADEN. She improves because her
residuals are tracked, not because a rule was added.

---

## Failure Modes (Libbie-specific)

Must fail loudly, never silently:

- DB unreachable or corrupted.
- sqlite-vec extension missing or wrong version.
- Embedder (`nomic-embed-text`) unreachable or returns non-finite values.
- SearXNG container unreachable when a web lookup was requested.
- A caller tries to write outside Libbie's API. (Enforced by not
  exposing raw DB handles. If someone imports sqlite3 directly, that's
  a code-review failure, not a runtime one.)
- A retrieval call returns results with corrupted embeddings or missing
  metadata.

No silent degradation. No default-on-missing. No "best effort" returns.

---

## Open Questions

- How does Libbie decide when context has changed "meaningfully" enough
  to trigger a `surface` pass? Answer must be learned, not scheduled.
- Should Libbie ever forget? v0 says no. Post-v0 might allow decay
  through retrieval weights trending toward zero, but actual deletion
  is a separate question. Current stance: never delete. Decay means
  "retrieved less," not "gone."
- Does Libbie need a concept of session / conversation boundaries, or
  is the unified timeline enough? Punt until residuals demand an answer.
- When Sean writes a self-knowledge note that contradicts an older one,
  should Libbie surface both or just the newer one? Current stance:
  surface both, let retrieval weights settle it. Revisit if this
  produces confused ratings.
- How does Libbie participate in phase-change detection without
  encoding a rule? Likely by exposing residual trends grouped by memory
  age to `CADEN_learning.md`, which owns the detection mechanism.

---

## Deprecated Sections

None yet. When ideas are rejected, they go here with a one-line reason
and stay forever.
