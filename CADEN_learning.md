# CADEN Learning System (Post-v0)

**Status:** `draft`

**Purpose:** Plan how CADEN gets better over time without hand-written
rules. This doc owns every mechanism that changes CADEN's own behavior:
schema growth, retrieval weight learning, decay, phase-change detection,
and active optimization of the mood/energy/productivity objective.

**Depends on:** `CADEN.md`, `CADEN_index.md`, `CADEN_v0.md`,
`CADEN_libbie.md`. Assumes the v0 substrate (events, ratings, predictions,
residuals, tasks, task_events) and Libbie's API exist.

---

## Locked Constraints (from `CADEN.md`)

- No hand-written heuristics. Not one.
- No fallbacks. Loud failure only.
- Python only.
- Local-first. Private.
- Declared objective: track mood, energy, productivity; balance all three.
- One central mechanism: Predict, Observe, Correct.

Learning-specific implications of these constraints:

- **A learning mechanism is not a heuristic** as long as it is generic
  and content-free about Sean. "Fit a regression on residuals" is not a
  heuristic. "Mondays are worse for Sean" is a heuristic. The first is
  math that operates on whatever data exists; the second is a claim
  about what matters. Only the first is allowed.
- **Every learning mechanism must itself emit predictions and accrue
  residuals.** The learner is not above the loop; it is inside it.
- **No mechanism tunes itself silently.** Weight updates, schema
  proposals, decay changes — all are logged as events with rationale.
  Past-CADEN's reasoning is preserved the same way past-Sean's is.

---

## Scope

In scope for this doc:

- The general shape of "learning" in CADEN
- Retrieval weight learning (how Libbie's ranking improves)
- Decay (how older memories influence retrieval over time)
- Schema growth (when and how LLM-proposed fields get added)
- Phase-change detection (distinguishing "Sean changed" from "mechanism
  miscalibrated")
- Active optimization (what "balance all three" means mathematically
  once data exists)

Out of scope for this doc:

- Any per-app behavior. Apps consume these mechanisms; they don't
  redefine them.
- v0 content. If it's already decided in `CADEN_v0.md`, don't restate
  plans here — reference them.
- Code. Planning only.

---

## The General Shape of Learning in CADEN

CADEN learns by comparing predictions to observations and adjusting the
parameters that produced the prediction. That's the whole story. The
question this doc answers is: which parameters exist, and how do
residuals change them?

All learning in CADEN has the same five-step structure:

1. **A component emits a prediction** with a confidence. The prediction
   is stored as an event (schema from v0).
2. **Time passes. An observation arrives** (a rating, a completion, a
   downstream outcome). The observation is stored as an event.
3. **Residual is computed** as the difference between prediction and
   observation, with the component and the inputs that produced the
   prediction attached. Stored as an event.
4. **An aggregation over residuals** identifies which parameter, if
   nudged, would have reduced the residual. Aggregation is pandas +
   scikit-learn; no bespoke math.
5. **The parameter is nudged**, the nudge is logged as an event with
   rationale, and the next prediction uses the new parameter.

If a proposed mechanism does not fit this shape, it is a heuristic
wearing a disguise. Reject it.

---

## Retrieval Weight Learning

v0 retrieval already flows through Libbie's curated-memory layer: Libbie
packages recalled memories for CADEN rather than dumping raw events. Post-v0,
the ranking inside that retrieval path becomes a learned weighted combination
of signals. Which signals, which weights.

### Signals available to retrieval

- Semantic similarity between query and candidate (from embeddings).
- Recency (time between now and candidate's timestamp).
- Source match between query context and candidate.
- Trigger match (why the candidate was captured vs. why the query
  was issued).
- Past usefulness of this candidate (from its own residual history).
- Past usefulness of this candidate's source+trigger pair.

These signals are not a hand-written feature list about Sean. They are
generic attributes every event has. Picking *these specific signals*
is itself a minor design choice and it earns its residual: if one of
them is never pulling weight, it gets zeroed out and effectively
removed. New signals only enter via schema growth.

### Weight learning

- Weights start uniform. No guess about which signal matters.
- On every retrieval, the ranked list is a prediction. The caller's
  downstream outcome is the observation. The residual is attached to
  each item in the list weighted by its rank (top items bear more
  blame/credit).
- Periodically (frequency itself is learned — see below), a regression
  fits the weights that best explain residuals across recent retrievals.
  Scikit-learn, no bespoke math.
- The fit produces new weights. The old weights are archived as an
  event. New weights are logged with the residual-aggregate that
  justified them.

### When does "periodically" fire?

Not on a clock. A clock is a heuristic.

Candidate mechanism: refit when the residual stream itself indicates the
current weights have gone stale. That may look like a learned trigger on
residual magnitude, residual drift, or some other generic data-availability
condition, but this doc does not lock in a fixed bootstrap count or any
specific startup threshold. If a startup gate is required at all, it must be
treated as an explicitly unresolved design problem rather than silently
blessed as architecture.

---

## Decay

Old memories should influence less. That's a design intuition, not a
rule. The rule is: retrieval weights trained on residuals will naturally
downweight stale memories if stale memories produce bad retrievals.

### Stance

- No hard-coded decay function. No exponential half-life chosen by
  Sean or by the designer.
- Recency is a signal to the retrieval weight learner. If residuals
  show recency predicts usefulness, its weight rises; if not, it falls.
- Deletion never happens. "Decay" in CADEN means "retrieved less often."

### Consolidation

Open question: should Libbie periodically merge near-duplicate memories?
Current stance: no. Merging is a lossy operation, and the no-deletion
rule generalizes to no-merging. If duplicates inflate context, the
retrieval weight learner can downrank near-duplicates by learning that
a second retrieval of a near-duplicate adds no residual-reducing value.

Flag for later: if duplicates become a real context-bloat problem,
revisit. Do not pre-optimize.

---

## Schema Growth

v0 says: LLM proposes new fields when persistent high residuals suggest
the schema is insufficient. This section plans the actual mechanism.

### Trigger

Schema growth fires when residual magnitude for some component stays
high over a window, AND the retrieval weight learner has already
plateaued (so the problem is not "bad weights on existing signals" but
"missing signal"). Both conditions must hold. Both thresholds are
themselves learned parameters.

### Proposal

When triggered, CADEN asks the LLM: given these recent high-residual
events and their context, what piece of information would have let you
predict better? The LLM returns a proposed field: name, type, how to
compute or capture it.

### Evaluation

Before accepting, CADEN runs the proposal against historical data:

- Back-fill the proposed field for past events (the LLM is asked to
  infer the value from existing event text + metadata).
- Refit retrieval weights including the new signal.
- Measure residual reduction on held-out recent events.

If residual reduction passes a learned threshold, the field is accepted:
added to schema, logged as a schema-growth event with the full rationale,
and now participates in retrieval.

If not, proposal is archived as an event (rejected proposals are memory
too) and the trigger condition resets.

### Hard rules

- Schema growth never removes a field. Fields are additive. A field
  that stops earning its weight simply decays to zero weight.
- Every proposal, accepted or rejected, is logged with full provenance:
  which residuals triggered it, what the LLM proposed, what the
  back-fill looked like, what the held-out evaluation showed.
- Sean can veto. Schema growth events are surfaced in the dashboard
  (see `CADEN_dashboard.md`) before being committed. v0 does not have
  this surface; the first schema-growth event cannot happen until the
  dashboard supports it. This is a deliberate gate.
- This dashboard gate is global. Residuals originating in Project
  Manager, Thought Dump, scheduler behavior, chat, or later apps still
  funnel to the same Dashboard consent surface rather than creating
  separate per-app veto UIs.

---

## Phase-Change Detection

The hardest problem. Residuals rose. Is that because CADEN's model is
wrong, or because Sean entered a new phase and the data that trained
the model no longer describes him?

### Why it matters

- If the model is wrong: refit on all data, accept the update.
- If Sean changed: refit with heavier weight on recent data, because
  old data is now about past-Sean.
- Doing the wrong one is bad. Treating a bad model as a phase change
  throws away valid history. Treating a phase change as a bad model
  drags forward an outdated Sean.

### Stance

Phase-change detection is itself a Predict-Observe-Correct loop.

1. **Prediction:** CADEN continuously predicts residual magnitude
   distribution for the next window based on the current window.
2. **Observation:** actual residuals arrive.
3. **Signal:** if recent residuals are systematically biased in one
   direction (not just larger, but biased), that's a phase-change
   signal. "Systematically biased" is detected by a statistical test
   on the residual stream (scikit-learn / pandas, no bespoke math).
   Unbiased large residuals suggest a miscalibrated mechanism;
   biased residuals suggest a shifted target.

### What happens on detection

- A phase-change event is recorded, with the bias direction and the
  component it affects.
- The retrieval weight learner is instructed to refit with
  recency-heavy weighting for the affected signal set. "Recency-heavy"
  is itself a learned parameter (how heavy). This doc does not lock in a
  default bootstrap value for it.
- Sean is notified on the dashboard. Phase-change events are not
  silent.
- Old ratings are never deleted or re-rated. They remain data about
  past-Sean. The system reweights; it does not rewrite.

### Distinguishing from miscalibration

If the phase-change mechanism fires but no bias is found — residuals
are large but symmetric — the signal is miscalibration instead. The
retrieval weight learner refits without recency emphasis. If residuals
stay high after refit, schema growth is the next escalation.

The order is: weight refit → if still bad and residuals biased, phase
change → if still bad and residuals unbiased, schema growth. This order
is a learned parameter too (via how quickly each escalation's trigger
fires), not a hand-written sequence.

---

## Active Optimization ("Balance All Three")

The spec declares the objective: track mood, energy, productivity;
balance all three, maximize each without tanking the others. v0 punts
on this entirely. This section plans what turns it on.

### When does CADEN start optimizing?

Not by a date or a milestone. By readiness. Readiness means:

- Ratings exist on enough past events for the rater's residuals to be
  small and stable. "Enough" is a learned threshold: when refits of the
  rater stop changing its behavior meaningfully, it's stable.
- Predictions about duration and state have residuals small enough
  that CADEN can meaningfully compare two candidate schedules and
  trust the comparison.
- Retrieval weights have converged (refits aren't moving weights much).

All three conditions are themselves detected by the Predict-Observe-
Correct loop — is my prediction of "my system is stable" matching my
observation of it being stable? When yes, active optimization unlocks.

### What "balance all three" means operationally

CADEN does not pre-decide a scalar objective. Candidate stance:

- Every candidate schedule produces a predicted mood trajectory, energy
  trajectory, and productivity trajectory across the window. These are
  predictions; they earn residuals.
- "Balance" means: rank schedules by a Pareto criterion over the three
  axes. The Pareto frontier is generic math, not a rule about Sean.
- Among Pareto-equivalent schedules, pick by a learned preference. The
  preference is trained on Sean's revealed choices over time: when
  Sean changed CADEN's suggested schedule, which axis did he preserve?
- The preference is itself a prediction (of what Sean will accept) and
  earns residuals like everything else.

### Hard rule

No fixed weighted-sum like `0.4 * mood + 0.3 * energy + 0.3 * productivity`
is ever written down. That would be a heuristic about what matters to
Sean. The weights, if they exist at all, are learned from his revealed
choices.

### What active optimization produces

Not a plan Sean must follow. A ranked set of candidate schedules
surfaced on the dashboard. Sean picks. His pick is data.

### What's explicitly deferred

- Multi-day optimization. v1 of active optimization stays within a day,
  same as v0 scheduling. Longer horizons wait for longer residual data.
- Optimizing anything other than the three declared axes. The spec
  names three; CADEN optimizes three. Additional axes would need to
  be declared by Sean in the spec, not invented by the learning system.

---

## Cross-Cutting Rules

- **Every nudge is an event.** Weight updates, schema proposals, phase-
  change detections, optimization weight changes — all written to
  memory with rationale. This lets CADEN reason about its own history
  the same way it reasons about Sean's.
- **Sean is always informed.** Schema growth, phase-change, and
  optimization onset all notify on the dashboard. CADEN does not change
  itself in secret.
- **Fixed bootstrap thresholds are suspect and not assumed valid by
  default.** If a mechanism seems to require one, treat that as an open
  design problem to justify or remove, not as something automatically
  allowed.
- **Every mechanism can be disabled by its own residuals going flat.**
  If retrieval weight learning never produces weight changes that
  reduce residuals, the learner itself should be reconsidered. Same
  for schema growth, phase-change, optimization. CADEN's mechanisms
  are not sacred.

---

## Failure Modes (learning-specific)

Must fail loudly:

- Residual computation produces NaN or inf.
- Regression refit fails to converge (scikit-learn raises).
- LLM proposal for schema growth returns malformed output the repair
  layer cannot fix.
- Back-fill of a proposed field fails at a rate high enough that the
  proposal cannot be trusted.
- Phase-change detector signals contradictory conditions (both biased
  and flat).
- Active optimization asked to run before readiness conditions met.

No silent skip, no "try again next time" without logging. Failures
are events too.

---

## Open Questions

- If retrieval-weight learning needs a startup gate, what principled
  data-readiness condition should trigger the first refit without
  smuggling in a fixed policy?
- How does CADEN detect that one of its own learning mechanisms has
  stopped helping? Residual-on-residual is recursive; it terminates
  somewhere. Where?
- When schema growth proposes a field that seems to encode a heuristic
  ("is_it_monday"), does CADEN catch that? Candidate answer: no special
  filter — the field will fail to reduce residuals across phases of
  Sean and will decay to zero weight. If it doesn't decay, it's
  probably a real signal, not a heuristic in disguise. But this is
  worth watching.
- How is Sean's veto on schema growth recorded so that future
  proposals can learn from rejected ones? Candidate: veto events are
  part of the training data for the LLM's next proposal.
- Active optimization: is Pareto ranking actually the right framing,
  or does it collapse distinctions Sean cares about? The only honest
  way to find out is to ship it and track Sean's overrides.
- Do phase changes cluster (Sean has a type of phase he re-enters)?
  If so, phase-change detection itself could learn from past
  detections. Open.

---

## Deprecated Sections

None yet.
