# CADEN Documentation Index

**Read this first.** Every other CADEN doc links back here. If you are an LLM
working on CADEN, load this file before touching anything else so you know
what already exists and what is already decided.

---

## Locked Constraints (repeated in every doc)

These come from `CADEN.md` (the spec) and are non-negotiable. Do not propose
changes to them; propose changes to the spec file only if Sean asks.

- **No hand-written heuristics.** Not a single rule about how Sean works,
  what matters, when things should happen, or how signals combine. If a rule
  is needed, CADEN learns it from residuals. Goals are not heuristics; rules
  about HOW are.
- **No fallbacks.** Failures are loud. Missing LLM, missing DB, missing
  embedding, missing Google API, NaN, malformed output after repair — all
  raise. Silent degradation is forbidden.
- **Python only.** No other languages in the runtime stack.
- **Local-first.** All compute and data live on Sean's machine. No cloud
  services for inference or storage. Google sync is the only external
  integration and it is scoped to Tasks + Calendar.
- **Private.** No telemetry, no analytics, no remote logging.
- **Declared objective.** Track mood, energy, productivity; balance all
  three. This is the goal, not a feature list. How to estimate or balance
  these is learned, never hand-written.
- **One central mechanism: Predict, Observe, Correct.** Every piece of
  CADEN that claims to know something must emit a prediction, have its
  prediction compared to observation, and store the residual. No component
  is exempt.

---

## Status Tags

Each doc carries one of these at the top:

- `locked` — decisions finalized; do not propose changes without Sean
  explicitly reopening the doc
- `draft` — actively being written or revised; propose freely
- `deprecated` — kept for history only; do not build from

---

## Doc Map

### Spec and foundations
- **`CADEN.md`** — `locked`. The immutable spec. Source of truth for
  purpose, apps, constraints, and Sean's stated needs. Never edited by
  CADEN tooling.
- **`CADEN_index.md`** — this file. `locked` in structure, `draft` in
  content as new docs get added.

### Build plan
- **`CADEN_v0.md`** — `locked`. The v0 implementation plan: tech stack,
  project layout, schema, boot sequence, six milestones, and the
  Implementation Contracts that resolve every concrete dilemma.
  Everything needed to start building the minimum viable CADEN. All
  decisions here are committed. Later docs assume v0 exists.
- **`CADEN_build_brief.md`** — `locked`. The build agent's manifest.
  File-by-file shopping list, function signatures, prompt templates,
  test strategy, stop conditions. **If a coding LLM is building v0,
  it reads this first.** Tightly scoped to v0; explicitly forbids
  reading post-v0 docs during the v0 build.

### Cross-cutting mechanisms (post-v0)
- **`CADEN_learning.md`** — `draft`. The learning system beyond v0.
  Covers: schema growth (LLM-proposed fields triggered by persistent
  residuals), phase-change detection (distinguishing "Sean changed" from
  "mechanism miscalibrated"), retrieval weight learning, decay, and
  active optimization (what "balance all three" means mathematically once
  CADEN has data). Cross-cuts every app. Depends on v0.

### Apps (post-v0)
- **`CADEN_libbie.md`** — `draft`. Libbie beyond v0. Self-knowledge
  accumulation, proactive memory surfacing, retrieval tuning specific to
  Libbie's role as the memory substrate. Depends on v0 and learning doc.
- **`CADEN_dashboard.md`** — `draft`. Dashboard beyond v0. The active
  optimization surface where "balance all three" becomes visible action.
  Depends on v0 and learning doc.
- **`CADEN_project_manager.md`** — `draft`. The Project Manager app.
  Multi-step goals, dependencies, progress tracking. Depends on v0 and
  learning doc.
- **`CADEN_thought_dump.md`** — `draft`. The Thought Dump app. Freeform
  capture with eventual structure emerging from retrieval and rating.
  Depends on v0 and learning doc.
- **`CADEN_sprocket.md`** — `draft`. Sprocket. The vibecoding chat
  interface: builds new CADEN apps/tabs through trial-and-error,
  guided by Libbie research briefs and learns which sources and
  strategies produce working code. Python only. Depends on v0,
  learning doc, dashboard doc.

### Cold-start mitigation
- **`CADEN_intake.md`** — `draft`. One-time first-launch flow where
  Sean seeds CADEN with self-knowledge notes and trusted Python code
  patterns. Pure data ingestion, no rules. Skippable. Never re-offered.
  This is the only concession to cold-start pain — nothing further is
  added in this direction. Depends on v0, Libbie, learning, Sprocket.

---

## Doc Authoring Rules (for LLMs and for Sean)

1. **Every doc starts with:**
   - Title
   - Status tag
   - One-sentence purpose
   - "Depends on" line listing other docs it assumes
   - The Locked Constraints block copied verbatim from this index
   - A "Scope / Out of Scope" block
2. **Keep each doc under ~600 lines.** If a topic grows past that, split it
   and add both pieces to this index.
3. **No doc contradicts another.** If you find a contradiction, stop and
   surface it to Sean; do not silently resolve it.
4. **Deprecated ideas stay in the doc they were proposed in**, under a
   "Deprecated Sections" heading, with a one-line reason. Do not delete
   history.
5. **Open questions are labeled as such** and never presented as answers.
6. **Planning only.** No code in these docs beyond illustrative snippets.
   Code lives in the eventual `caden/` package, not the planning docs.

---

## Reading Order (for a fresh LLM)

1. `CADEN.md` — know the spec
2. `CADEN_index.md` — know the map (this file)
3. `CADEN_v0.md` — know what's being built first
4. `CADEN_learning.md` — know how CADEN improves itself
5. Then the specific app doc relevant to the task
