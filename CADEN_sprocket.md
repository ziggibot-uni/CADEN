# Sprocket App (Post-v0)

**Status:** `draft`

**Purpose:** Plan Sprocket — CADEN's vibecoding chat interface. Sprocket
builds new CADEN apps/tabs. He gets better at building the more he does
it. Code he's seen before is memory he can retrieve, copy, and tweak.
The framework + Libbie + LLM means: as long as the pieces exist online,
CADEN can find them and figure out (through trial-and-error guided by
residuals) which sources are good and which strategies work.

**Depends on:** `CADEN.md`, `CADEN_index.md`, `CADEN_v0.md`,
`CADEN_libbie.md`, `CADEN_learning.md`. Some dashboard interactions
also touch `CADEN_dashboard.md`.

---

## Locked Constraints (from `CADEN.md`)

- No hand-written heuristics. Not one.
- No fallbacks. Loud failure only.
- Python only — including everything Sprocket writes.
- Local-first. Private.
- Declared objective: track mood, energy, productivity; balance all three.
- One central mechanism: Predict, Observe, Correct.

Sprocket-specific implications:

- **Python only, always.** Sprocket cannot generate code in any other
  language. If a task seems to require non-Python (e.g., a JS frontend
  trick), Sprocket fails loudly and surfaces the constraint to Sean.
  No fallback to "I'll write this in JS just this once."
- **Every Sprocket attempt is a prediction.** The prediction is "this
  code will accomplish what Sean asked." The observation is whether it
  ran, passed checks, and was accepted. The residual is stored and
  trains future Sprocket behavior.
- **No silent code changes to CADEN itself.** Integration into CADEN's
  running codebase is a consent event. Sean approves explicitly.

---

## Scope

In scope:

- Surface (the Sprocket tab)
- Two-stage flow: Libbie research brief → Sprocket build
- Code-as-memory: AST storage, retrieval, copy-and-tweak
- Sandboxed execution for trial-and-error
- Source-quality learning (which domains/libraries produce working code)
- Abstraction emergence via schema growth
- Stopping condition (learned attempt budget, not a static N)
- Integration into CADEN (consent and process)
- Failure modes

Out of scope:

- Anything Sean asks for outside CADEN. Sprocket builds CADEN apps/tabs
  only, per spec ("select app from nav panel to edit, or create a new
  app"). General-purpose code generation is not Sprocket's job.
- Modifying CADEN's core (Libbie, rater, scheduler, learning system).
  Sprocket builds new tabs. Editing core is a future concern, not
  Sprocket v1.
- The learning system math (lives in `CADEN_learning.md`).
- General memory semantics (lives in `CADEN_libbie.md`).
- v0 material. Sprocket is not in v0.

---

## What v0 Gives Sprocket

Nothing directly. Sprocket builds on:

- Libbie's `capture`, `retrieve`, `surface`, `search_web` (SearXNG).
- The LLM client + repair layer.
- The schema-growth and residual mechanisms in `CADEN_learning.md`.
- The dashboard's veto/consent surface for Sean-approval steps.
- A new sandbox subsystem, planned in this doc.

---

## Surface

A tab in the CADEN GUI, identical layout discipline to other apps:

- **Narrow left navigation panel** listing existing apps Sprocket has
  built (or knows about as built-in), plus an entry for "new app."
  Selecting an existing app puts Sprocket in edit mode for it.
  Selecting "new app" puts Sprocket in create mode.
- **Main area = chat interface** with Sprocket. Sean describes what he
  wants. Sprocket responds, asks clarifying questions, shows progress,
  surfaces failures.
- **Status strip** below the chat showing current activity: researching
  / writing / sandboxing / awaiting Sean. Sprocket's loop is visible.

Sprocket's chat is distinct from the dashboard chat. The dashboard chat
is Sean ↔ CADEN about life. Sprocket's chat is Sean ↔ Sprocket about
building. They share Libbie but not conversation history scope by
default. Cross-surface retrieval is allowed (per Libbie's unified
retrieval rule); blending the two streams in the same chat is not.

---

## The Two-Stage Flow: Libbie → Sprocket

Per spec interpretation: Libbie does the research and produces a brief;
Sprocket reads the brief and writes code.

### Stage 1: Libbie produces a research brief

Triggered when Sean's request lands in the Sprocket chat.

What Libbie does:

- Retrieves past Sprocket events (briefs, generated code, residuals)
  semantically related to the request. This is where "code Sprocket has
  seen before" comes in.
- Retrieves Sean's prior chats, thoughts, and project entries that
  touch on the request (so the brief reflects context, not just the
  literal ask).
- Issues SearXNG searches if the retrieval is thin or if specific
  external knowledge is needed (a library's API, a known pattern).
  Web results become events as usual (per `CADEN_libbie.md`).
- Compiles a structured brief: the goal, relevant past code memories
  (with their residual histories), relevant external sources (with
  source-quality scores), and any open questions Libbie thinks Sean
  should resolve before Sprocket starts.

The brief is itself an event. Source = `sprocket_brief`.

### Stage 2: Sprocket builds

Sprocket reads the brief and:

- If open questions remain, asks Sean (in chat) before writing code.
- If past code memories closely match, attempts copy-and-tweak first
  (cheaper than from-scratch generation).
- If no close match, generates from scratch using the brief's external
  sources.
- Runs each candidate in the sandbox (next section).
- Iterates until success, until attempt budget exhausted, or until
  Sean halts. Each attempt is an event with a prediction and earns a
  residual.

### Why two stages

- Separates "what should we build" (Libbie's research, semantic) from
  "how do we write it" (Sprocket's coding loop, structural).
- Lets the brief serve as a checkpoint: Sean can review and redirect
  before code-writing begins.
- Gives Libbie's source-quality learning a clean place to live (Stage
  1 picks sources; Stage 2 uses them). Residuals on bad code propagate
  back to source quality cleanly.

---

## Code as Memory (AST as Canonical Form)

Code Sprocket has seen before is memory he can retrieve. Memory shape
matters here.

### Storage

- Generated code (and accepted code from Sean) is captured as an event.
- The event's structured form is the **AST**, parsed via Python's
  `ast` module. The AST is serialized (json or a dump format) and
  stored alongside the raw text.
- Embedding is computed from a text serialization of the AST plus
  surrounding context (the brief, Sean's request, the sandbox
  outcome). This makes structural similarity and semantic similarity
  both available for retrieval.
- Loud failure if `ast.parse` raises on stored code. Code that doesn't
  parse never enters memory — that would poison future retrievals.

### Retrieval

- Two retrieval modes:
  1. **Semantic**: standard Libbie retrieval over embeddings.
     Surfaces code with similar described intent.
  2. **Structural**: AST shape similarity. Useful when Sprocket has
     a partial structure and wants to find code with matching skeleton.
     Implementation: pandas/sklearn over AST node-type histograms or
     a similar generic feature; not a hand-written rule about which
     nodes matter.
- Sprocket can request either or both. The retrieval ranking is the
  weighted-signal scheme from `CADEN_libbie.md` and
  `CADEN_learning.md`; structural similarity is just one more signal.

### Copy and tweak

- When a high-similarity past code memory is retrieved, Sprocket's
  first attempt is to take that code, identify the parts that need to
  change for the current request, and modify them. This is cheaper
  and more reliable than generation from scratch.
- The AST is the working substrate for the tweak: identify nodes to
  replace, swap them, re-serialize. The LLM is asked which nodes to
  swap and what to swap them with; the framework does the safe AST
  rewrite.
- A copy-and-tweak attempt is a distinct event type from a from-
  scratch generation. Residuals on each track separately so Sprocket
  learns which approach works for which kinds of requests.

---

## Sandboxed Execution

Trial-and-error is core to Sprocket. Trial-and-error inside CADEN's
running process would corrupt CADEN. Sandbox.

### Sandbox shape

- A separate Python process (subprocess), with a restricted working
  directory (a per-attempt scratch folder), no network access by
  default, and no access to CADEN's DB.
- The candidate code is written to a file in the scratch folder along
  with any test inputs derived from the brief.
- Sprocket runs the file (`python <file>`), captures stdout/stderr/
  exit code/timing, and observes outcome.
- Process is killed if it runs past a learned timeout (bootstrap
  small, e.g., 30s; tuned by residuals on whether longer runs ever
  succeed).
- After the run, the scratch folder is archived as part of the
  attempt event (so Sprocket can see what happened later) and a fresh
  folder is created for the next attempt.

### What "success" means in the sandbox

- Code parses (already required for storage).
- Code runs without raising.
- Output meets the brief's success criteria. Success criteria are
  generated by Libbie during the brief (e.g., "the function should
  return a list of length N when given …"). If criteria can't be
  generated, Sprocket asks Sean before starting.
- Sean can override sandbox judgement (e.g., approve code that the
  brief's criteria flagged as wrong, if the criteria themselves were
  off). The override is an event and trains future criteria
  generation.

### What the sandbox is NOT

- Not a security boundary against malicious code. Sprocket is local,
  Sean is the only user, threat model is "Sprocket made a mistake,"
  not "Sprocket is hostile." The sandbox protects CADEN from
  Sprocket's bugs, not from adversarial behavior.
- Not for code that needs network or external resources. If a
  candidate requires network (e.g., a Google API call), the sandbox
  cannot test it directly. Sean is asked to run it manually before
  integration. Loud surface, no silent skip.

---

## Source-Quality Learning

Granularity: **per-source**. Source = the originating domain (Stack
Overflow, a specific library's docs, GitHub, etc.) or the originating
library identifier when the source is a code-memory event ("we used
`requests` last time and it worked").

### Mechanism

- Every external source consulted in a brief is recorded with the
  brief.
- When the resulting code lands in the sandbox, the outcome (success
  or failure) attributes to all sources used in producing it.
- Attribution weights split among the sources roughly by how much of
  the brief each contributed (the brief tracks which sources informed
  which sections).
- Source-quality is a learned score per source, tuned by residuals on
  the code it informed. This score becomes a retrieval-weight signal
  for future briefs.
- A source that consistently produces failing code drifts toward
  zero weight and stops being suggested. Not deleted from memory —
  the events stay, but retrieval downranks them.

### No hand-written allowlist

There is no hand-written "Stack Overflow is good, blogspot is bad"
list. Source quality is entirely learned. If Sprocket finds a
high-signal source nobody would have predicted, it gets used. If a
canonical source produces bad results in CADEN's specific context,
it gets downranked.

---

## Abstraction Emergence (via Schema Growth)

"Sprocket gets better at building the more he does it" specifically
requires abstraction. Several similar successful builds → a template.
This is a schema-growth event per `CADEN_learning.md`.

### Trigger

- Sprocket events cluster: multiple successful builds with similar
  briefs, similar AST structure, and similar source patterns.
- The retrieval weight learner has plateaued on these clusters
  (per the standard schema-growth gate).
- Residual reduction projection suggests a template would reduce
  effort or improve success rate.

### Proposal

- The LLM is asked: given these N similar successful builds, what's
  the abstract pattern? Output is a template with parameter slots and
  a description.
- The template is back-tested against the historical cluster (would
  it have produced the past successful code with appropriate
  parameters?) and against held-out recent builds.
- If back-test passes, the proposal goes through the standard
  dashboard veto surface (Accept / Reject / Ask more).
- On accept, the template enters Sprocket's memory as a high-priority
  retrieval candidate. Future briefs that match the pattern surface
  the template; Sprocket fills slots rather than rebuilding.

### Hard rule

Templates earn residuals like everything else. A template that stops
producing working code drifts in its retrieval weight. CADEN doesn't
become attached to its abstractions — they're memory like everything
else.

---

## Stopping Condition (Attempt Budget)

The attempt budget is a **learned parameter**, not a static N. A
literal "give up after 5" would be a hand-written heuristic.

### Mechanism

- Bootstrap value: small (e.g., 3 attempts) so Sprocket doesn't burn
  unbounded time before any data exists.
- After each request, the system observes: did attempts beyond the
  bootstrap value ever succeed where earlier attempts failed? If yes,
  budget grows. If no, budget shrinks.
- The budget can vary by request type — copy-and-tweak vs. from-
  scratch may have different optimal budgets, learned separately.
- Sean can always halt earlier than the budget. A halt is a
  preference event (Sean expressed that this attempt was not worth
  continuing); learning system uses it.

### Surface to Sean

- Status strip shows current attempt number against the budget.
- A "stop" button is always available.
- On budget exhaustion, Sprocket surfaces the failure clearly: what
  was tried, what went wrong, what the brief said, where Sean might
  redirect. Failure is an event with full provenance.

---

## Integration Into CADEN

Sprocket builds new tabs. A new tab is code that runs inside CADEN's
process. Integration is a consent event.

### Process

- A successful build in the sandbox is candidate code, not yet a
  CADEN app.
- Sprocket prepares an integration package: the code, the manifest
  (what tab name, what nav-panel position, what dependencies), the
  brief that produced it, the residual history.
- Sean reviews via a dashboard veto-style surface (modal with Accept /
  Reject / Ask more).
- On accept, the code is written into CADEN's package (some
  dedicated subdirectory, e.g., `caden/sprocket_apps/`), and a
  registration event triggers CADEN to load the new tab on next
  restart.
- Loaded tabs are inert at first launch — they get a smoke test
  (does the tab render? does it not crash on click?) before becoming
  user-accessible. Smoke test failures roll back the integration and
  log loudly.

### Hard rules

- Sprocket never modifies existing CADEN code as part of integration
  in v1. New tabs only, new files only. Editing existing files is a
  future concern explicitly out of scope here.
- Sean can disable a tab at any time. Disable removes it from the
  GUI; it does not delete the code (no deletion of memory). The
  disable is an event.
- Integration cannot occur outside the consent flow. There is no
  "auto-merge if all tests pass."

---

## Schema Sketch (for reference, not commitment)

- `events` already exists. Sprocket events use sources like
  `sprocket_request`, `sprocket_brief`, `sprocket_attempt`,
  `sprocket_template`, `sprocket_integration`.
- `sprocket_attempts` table: `event_id`, `request_id`, `attempt_index`,
  `approach` (copy_and_tweak vs from_scratch), `code_text`,
  `ast_serialized`, `sandbox_outcome`, `runtime_ms`. Lets Sprocket
  query the recent build history without scanning all events.
- `source_quality` table: `source_id`, `score`, `last_updated`. The
  score is the learned weight; recomputed via the standard learning
  loop.
- `templates` table: `id`, `name`, `pattern_serialized`, `created_at`,
  `accepted_at`. Templates the dashboard veto accepted.

Schema grows from here per learning rules.

---

## Failure Modes (Sprocket-specific)

Must fail loudly:

- AST parse fails on generated code (code never stored, attempt
  marked failed, loud event).
- Sandbox process refuses to start (subprocess error, attempt
  aborted, system halts Sprocket loop, Sean is notified).
- Brief generation fails (Libbie research turns up nothing AND
  SearXNG is unreachable). Sprocket asks Sean for more guidance
  rather than guessing.
- Generated code attempts to import non-Python (e.g., calls out to
  shell for non-Python work). Detected by AST inspection. Loud
  failure, attempt rejected.
- Integration smoke test fails. Roll back, log, surface to Sean.
- Source-quality score becomes NaN or otherwise corrupted. Loud
  failure, source temporarily excluded until recomputed cleanly.
- Sean accepts an integration but the code references a module not
  available in CADEN's environment. Smoke test catches it; loud roll
  back.

---

## Open Questions

- How does Sprocket handle requests that require persistent state
  (a tab that needs its own DB tables)? Likely answer: schema growth
  for the new tab's needs, gated through dashboard veto. But this
  blends Sprocket's integration with the learning system's schema
  growth in a way that may need a dedicated subsection. Punt until
  first such request arises.
- AST node-type histograms are a starter feature for structural
  similarity; is that actually useful in practice, or do we need
  subtree-level features? Defer to residuals on structural retrieval.
- What's the right granularity for "source"? A whole domain might be
  too coarse; a specific page might be too fine. Current stance:
  start at domain, let schema growth split it if residuals demand.
- How does Sprocket avoid plagiarism/license issues when copying from
  external sources? Out of scope here in the strict sense (this is a
  legal/ethical concern, not a design one), but worth flagging:
  external code memories store provenance, and a future feature could
  surface license info before integration. Punt.
- When a template is accepted, do its parameter slots constrain
  Sprocket too tightly? Possible failure mode: Sprocket fills the
  template even when the request is subtly different. Answer: residuals
  on template-based builds will show this if it happens; the template
  decays. But a softer answer might be useful — e.g., always allow
  Sprocket to deviate from a template when confidence is low. Open.
- Editing existing CADEN code (vs. only adding new tabs) is the
  obvious next capability. When does it unlock? Probably gated by
  Sprocket's track record — once new-tab integration residuals are
  small for long enough. But "long enough" is itself learned. Defer
  to a future Sprocket v2 doc.

---

## Deprecated Sections

None yet.
