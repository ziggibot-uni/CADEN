# CADEN Docs-to-Code Gap List

**Status:** `draft`

**Purpose:** Track verified mismatches between the current documentation
contract and the current implementation, so alignment work stays scoped and
documentation-first.

**Depends on:** `CADEN.md`, `CADEN_index.md`, `CADEN_v0.md`,
`CADEN_buildBrief.md`, `CADEN_libbie.md`, `CADEN_learning.md`.

---

## Scope

In scope:

- verified doc-to-code mismatches only
- gaps that matter to v0 behavior or to the adopted memory DSL contract
- concise statements of current code behavior versus current documented truth
- implementation plans for fixing verified gaps before code changes begin

Out of scope:

- speculative future improvements
- bugs not yet tied to a documentation contract
- broad refactors not anchored in one of the listed gaps

---

## Execution Order

The gaps should not be attacked in arbitrary order. The recommended sequence is:

1. Retrieval contract alignment
2. Rater retrieval alignment
3. Bootstrap-constant reduction / reclassification
4. Completion-poll semantic cleanup
5. Memory-frame canonicalization contract

Reason for this order:

- retrieval is the highest-leverage model-facing surface and defines what the
  9B model actually sees
- the rater should move only after the retrieval substrate it depends on is
  clarified
- bootstrap cleanup should follow once the new retrieval path is stable enough
  that old fixed limits can be reduced or reclassified safely
- completion polling is semantically important but mechanically smaller
- memory-frame canonicalization should be finalized after the retrieval and
  rater consumers make clear which frame fields are actually required

---

## Current Verified Gaps

### 1. Retrieval still has legacy raw-event paths and fixed scoring adapters

**Current status:** substantially resolved on this branch.

Documented truth:

- `CADEN_v0.md` says CADEN-facing retrieval is over curated `memories`, with
  Libbie returning compact recall packets rather than raw event dumps.
- `CADEN_libbie.md` says ligand construction and recall-packet packaging are
  the Libbie-owned path the model should see.

Current code:

- `caden/libbie/retrieve.py` still exposes `search(...)` over raw `events`.
- the same module still applies a fixed score adapter in
  `recall_packets_for_task(...)` and keeps a legacy length-bias heuristic in
  the raw-event search path.

Why this matters:

- the repo still has two retrieval philosophies at once: curated-memory
  retrieval for the new DSL, and legacy raw-event retrieval for older callers.
- that keeps the model-facing contract blurrier than the docs now allow.

Resolution note:

- chat, rater, scheduler, and prediction now consume Libbie's curated-memory
  recall path rather than `retrieve.search(...)`.
- the legacy raw-event search helper still exists, but no longer defines the
  primary model-facing retrieval contract.

Plan:

- **Target state:** `caden/libbie/retrieve.py` exposes one primary retrieval
  path centered on `MemoryFrame` -> `RecallPacket`, with raw-event lookup kept
  only as a provenance helper or removed entirely.
- **Implementation shape:** promote `recall_packets_for_task(...)` or an
  equivalent Libbie-owned API to the default retrieval surface; demote legacy
  `search(...)` so it no longer defines model-facing behavior.
- **Ranking stance:** keep any temporary fixed scoring adapter explicitly
  transitional and isolated to one function, with naming/comments that make it
  clear it is not the long-term learning mechanism.
- **Files likely affected:** `caden/libbie/retrieve.py`,
  `caden/libbie/curate.py`, callers that still consume raw-event retrieval,
  and tests that currently encode event-centric retrieval assumptions.
- **Validation required:** focused tests proving that chat and other callers
  consume curated-memory packets rather than raw event dumps; grep or direct
  call-site read showing that legacy raw-event retrieval is no longer the
  primary model-facing API.
- **Stop condition:** no model-facing path should depend on raw `events` as
  its retrieval payload shape.

### 2. The rater still reads legacy event retrieval instead of the curated-memory layer

**Current status:** resolved on this branch.

Documented truth:

- the memory DSL now treats `RecallPacket` as the CADEN-facing retrieval
  payload and the curated memory layer as the retrieval substrate.

Current code:

- `caden/rater/rate.py` calls `retrieve.search(...)`, not curated-memory
  recall packaging.
- the rater prompt is still built from raw event snippets plus fixed
  truncation constants.

Why this matters:

- one of the most important model calls in the system is still consuming the
  older retrieval form.
- that makes the memory DSL true for chat, but not yet true across the full
  v0 reasoning surface.

Resolution note:

- the rater now builds its supporting context from curated-memory recall
  packets instead of raw-event neighbours.

Plan:

- **Target state:** the rater consumes Libbie-packaged recalled memory in the
  same architectural form as chat, while preserving rater-specific context
  needs.
- **Implementation shape:** either teach the rater to call a Libbie retrieval
  function that returns `RecallPacket`-style context directly, or route the
  rater through a dedicated packaging helper in `caden/libbie/curate.py` that
  uses the same curated-memory substrate.
- **Prompt-shape rule:** the rater may still need a focused event-under-review
  block, but supporting memory should no longer be raw event snippets by
  default.
- **Files likely affected:** `caden/rater/rate.py`, `caden/libbie/retrieve.py`,
  possibly `caden/libbie/curate.py`, and rater tests.
- **Validation required:** a narrow rater test showing that retrieved support
  context is drawn from curated memory packets rather than direct raw-event
  search; regression check that the structural-source skip-list and
  NULL-on-unknown behavior stay intact.
- **Dependency:** do this only after gap 1 establishes the retrieval API the
  rater should consume.
- **Stop condition:** the rater should no longer call the legacy raw-event
  retrieval path for its main supporting context.

### 3. Config still encodes many fixed bootstrap thresholds the docs no longer bless

**Current status:** partially resolved on this branch.

Documented truth:

- `CADEN_v0.md` and `CADEN_learning.md` now reject fixed bootstrap thresholds
  as authoritative architecture except where a narrow implementation detail is
  explicitly tolerated.

Current code:

- `caden/config.py` still defines many `BOOTSTRAP_*` constants for prompt
  token budgets, retrieval counts, truncation sizes, scheduler caps, retry
  counts, and residual windows.
- those values are still imported and used by live code.

Why this matters:

- the docs have moved toward a stricter anti-threshold position, but the code
  still operationalizes many old limits as if they were part of the contract.

Resolution note:

- runtime `bootstrap_value_used` event logging has been removed.
- the remaining tolerated operational limits have been renamed away from
  bootstrap framing where they are still in use.
- some fixed operational caps still exist in code; those now read as
  implementation details rather than as pseudo-architectural learning truth.

Plan:

- **Target state:** fixed constants are split into two classes only:
  tolerated implementation details versus real architecture drift.
- **Implementation shape:** audit every live `BOOTSTRAP_*` constant and assign
  it one of three outcomes:
  1. remove it,
  2. rename/reclassify it as an implementation detail,
  3. keep it temporarily with explicit justification in docs and tests.
- **Priority inside this gap:** retrieval-count, truncation, prompt-budget,
  and scheduler-cap constants are the first candidates for removal or major
  downgrading because they most directly shape model attention.
- **Files likely affected:** `caden/config.py`, all import sites, tests that
  assert bootstrap semantics, and the docs if any remaining tolerated values
  need to be named explicitly.
- **Validation required:** focused search showing removed constants no longer
  drive model-facing behavior; targeted tests or checks proving that tolerated
  implementation-detail values are not logged or framed as learning truths.
- **Dependency:** do this after gaps 1 and 2, because retrieval/rater cleanup
  may remove some constants naturally.
- **Stop condition:** the remaining constants, if any, should read as narrow
  operational details rather than as pseudo-architectural policy.

### 4. Completion polling is still described in code as a bootstrap gate, not merely an implementation detail

**Current status:** resolved on this branch.

Documented truth:

- `CADEN_v0.md` now says the 60-second polling cadence is an implementation
  detail, not an authoritative learning rule about Sean.

Current code:

- `caden/ui/app.py` still imports `BOOTSTRAP_COMPLETION_POLL_SECONDS`, logs it
  through `log_bootstrap_use(...)`, and comments on it as a bootstrap gate.

Why this matters:

- this is a smaller gap than the retrieval ones, but it shows the old
  bootstrap framing is still live in the runtime semantics.

Resolution note:

- completion polling keeps its 60-second behavior but is now named and tested
  as an operational cadence rather than a bootstrap gate.

Plan:

- **Target state:** completion polling remains at 60 seconds if needed, but is
  named, commented, and tested as an operational cadence only.
- **Implementation shape:** remove bootstrap-specific naming and event logging
  around the poll cadence; keep the runtime interval if it is still the chosen
  implementation detail.
- **Files likely affected:** `caden/ui/app.py`, `caden/config.py` if the name
  lives there, and GUI/contract tests that currently assert bootstrap framing.
- **Validation required:** focused test that the app still polls at the chosen
  interval, plus a source check confirming there is no `bootstrap_value_used`
  semantics tied to completion polling.
- **Dependency:** can happen after gap 3 or alongside it, since it is a narrow
  case of bootstrap cleanup.
- **Stop condition:** the code should preserve behavior without implying that
  the cadence is part of CADEN's learned architecture.

### 5. Memory-frame synthesis is currently a heuristic string-shaping pass, not a clearly spec-locked canonicalization contract

**Current status:** resolved as a documentation ambiguity; implementation now
has an explicit transitional status.

Documented truth:

- the docs now define `MemoryFrame` as Libbie's canonical structured memory
  unit and position it as the stable packaging layer for a 9B model.

Current code:

- `caden/libbie/store.py` generates memory frames through deterministic token
  extraction, source-to-type mapping, synthetic hook phrases, and summary
  truncation.

Why this matters:

- this may be acceptable as a transitional implementation, but the current doc
  set does not yet say whether these shaping rules are temporary scaffolding,
  part of the v0 contract, or drift to be removed.

Resolution note:

- the docs now explicitly treat the current shaping rules as deterministic
  transitional scaffolding, while committing only the invariants that must
  hold for `MemoryFrame` generation.
- contract coverage now checks those invariants without freezing arbitrary
  wording.

Plan:

- **Target state:** the repo has an explicit answer to what is canonical about
  `MemoryFrame` generation and what is temporary scaffolding.
- **Decision now adopted:** token extraction, source-to-type mapping,
  synthetic hooks, and summary shaping are treated as tolerated transitional
  scaffolding rather than as frozen architecture.
- **Implementation shape:** once the docs decide that status, either
  formalize the current canonicalization contract or replace the most
  arbitrary shaping rules with a narrower deterministic transformation that
  better matches the docs.
- **Files likely affected:** `caden/libbie/store.py`, `caden/learning/schema.py`,
  possibly `CADEN_v0.md` / `CADEN_libbie.md` if the accepted contract needs to
  be made more explicit.
- **Validation required:** tests that assert stable `MemoryFrame` structure for
  representative sources without overfitting to arbitrary wording; direct read
  confirming that `embedding_text` is built from the documented frame contract.
- **Dependency:** this should be finalized after gaps 1 and 2 make clear what
  retrieval consumers actually need from a frame.
- **Stop condition:** `MemoryFrame` generation should no longer sit in an
  ambiguous state between “official contract” and “temporary heuristic.”

---

## Implementation Rules For The Gap Work

When code work starts, each gap should follow this pattern:

1. change the smallest controlling abstraction first
2. validate the changed path immediately with the narrowest executable check
3. only then move to the next dependent gap

Specific rule for this repo:

- do not start bootstrap cleanup before the retrieval and rater paths are
  clarified, or the cleanup will remove names without reducing the deeper
  architectural drift.

---

## Working Rule For This File

Only add a new gap when both sides are explicit:

- the relevant documentation statement is identifiable
- the current code path showing the mismatch has been read directly

If either side is fuzzy, do not add the gap yet.