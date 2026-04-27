# Dashboard (Post-v0)

**Status:** `draft`

**Purpose:** Plan the Dashboard app beyond what v0 delivers. v0 gives
the primary Textual interface (today / chat / 7-day). When CADEN grows beyond
v0, that exact interface becomes the tab named `Dashboard` inside the root
multi-tab GUI. v0+ grows by adding sibling tabs around it, not by replacing it
with a different dashboard concept. This doc plans what that continuing
Dashboard tab becomes once the learning system is alive.

**Depends on:** `CADEN.md`, `CADEN_index.md`, `CADEN_v0.md`,
`CADEN_libbie.md`, `CADEN_learning.md`.

---

## Locked Constraints (from `CADEN.md`)

- No hand-written heuristics. Not one.
- No fallbacks. Loud failure only.
- Python only.
- Local-first. Private.
- Declared objective: track mood, energy, productivity; balance all three.
- One central mechanism: Predict, Observe, Correct.

Dashboard-specific implications:

- **The Dashboard is a Tab, not a brain.** It is just one app registered within the GUI's `TabbedContent` container. It surfaces what Libbie,
  the scheduler, the rater, and the learning system have produced.
- **The Dashboard is the continuation of v0, not a replacement for it.**
  The current v0 GUI becomes this tab when the rest of CADEN's apps are
  added.
- **Every displayed prediction shows its confidence and its residual
  history.** Sean is never shown a number without provenance.
- **Sean's interactions with the dashboard are memory.** Clicking
  accept / reject / override / veto writes an event.

---

## Scope

In scope:

- What the three panels become post-v0 (today, chat, 7-day)
- Prediction display (how mood/energy/productivity predictions surface)
- Schema-growth veto surface
- Phase-change notification surface
- Active optimization surface (ranked candidate schedules)
- Residual visibility (so Sean can audit CADEN's self-model)
- Input affordances beyond the add-task button

Out of scope:

- Any learning logic (lives in `CADEN_learning.md`)
- Any memory logic (lives in `CADEN_libbie.md`)
- The chat's conversational behavior (that's the LLM client + rater +
  retrieval, not the dashboard)
- v0 material (don't restate)

---

## What v0 Already Gives the Dashboard

Restated for self-containment:

- Three-panel Textual layout: left = today, middle = chat, right = 7-day.
- This exact v0 layout is the thing that later becomes the `Dashboard` tab;
  post-v0 does not invent a separate dashboard from scratch.
- The dashboard's day boundary is 5 AM local time, not midnight. The left
  panel's "today" view runs 5 AM -> next 5 AM, and the right panel's 7-day
  horizon is anchored from that same circadian boundary.
- Google Calendar + Google Tasks rendered, mixed chronologically,
  labeled by type.
- Add-task button that creates a Google Task + paired Calendar event
  plus a prediction bundle.
- Completion marks flow back as observations.
- Completion updates the rendered item rather than making it vanish from the
  active day/week view; the dashboard preserves continuity with the event it
  originally showed.
- Sean's chat inputs become events with embeddings; CADEN replies are
  ephemeral in-session context only.

Everything below assumes these exist.

---

## Post-v0: The Three Panels, Enriched

### Today panel (left)

v0 renders items in chronological order, mixed and labeled. Post-v0
adds, per item:

- **CADEN's prediction bundle** for items CADEN scheduled: predicted
  duration, predicted pre-state, predicted post-state, confidence for
  each. Shown compactly (e.g., as small icons or inline annotations)
  so the chronological list stays readable.
- **Post-hoc residual** once the item completes: predicted vs. actual
  duration, predicted vs. rated post-state. This replaces the
  prediction display after completion.
- **Source tag** (Google Task / Google Calendar / CADEN-scheduled).
  v0 already labels by type; post-v0 adds subtler provenance for
  CADEN-scheduled items (which prediction mechanism produced the slot).

Items NOT added to the today panel:

- Ambient events (ratings, residuals, Libbie observations). Those are
  memory, not calendar. They do not clutter the today view.

### Chat panel (middle)

v0 is bidirectional chat. Post-v0 additions:

- **Retrieved memories shown with each response** in a collapsible
  strip. Sean can see which memories shaped the answer. Click to
  inspect or annotate. Not a debug feature; a trust feature.
- **Rating of each exchange** happens automatically (via the rater)
  and is displayed as a small mood/energy/productivity triple. Sean
  can correct it inline; a correction is a new rating event, old
  rating stays immutable.
- **LLM confidence** surfaced when low. If the LLM flags itself as
  unsure or the repair layer had to work hard, that's visible.

### 7-day panel (right)

v0 shows the next seven days of Calendar + Tasks. Post-v0 additions:

- **Predicted trajectories** when active optimization is live: a
  compact view of the predicted mood / energy / productivity arc over
  the week given the current schedule. Three small sparklines.
- **"What if?" affordance**: Sean can ask the dashboard to preview
  alternative schedules (generated by active optimization). The 7-day
  panel swaps to show the alternative's predicted trajectories. Sean
  picks one or returns to current. His pick is an event.
- **CADEN may schedule anywhere before the task's due date, but only by
  moving CADEN-created task blocks.** Non-CADEN calendar events remain
  fixed constraints. The 7-day panel therefore shows both committed
  future task blocks and previewed alternatives.

---

## Prediction Display (The Trust Surface)

CADEN's credibility depends on Sean seeing where its numbers come from.
The dashboard is where this happens.

### Rules

- Every prediction is shown with its confidence.
- Every prediction has an on-demand "why" that lists the retrieved
  memories, the active retrieval weights, and the residual history of
  the mechanism that produced it. Clicking expands this.
- Residuals for recent predictions are shown as a small rolling chart
  on the mechanism's label. Sean can tell at a glance whether
  "duration prediction" has been reliable this week.

### What is NOT shown

- The underlying math. No weights-as-numbers surfaced by default, no
  regression coefficients. If Sean wants them, they're in a dev-mode
  inspector (future); the default dashboard stays readable.
- Predictions the rater labels "unknown." These show as "no prediction
  yet" — honest, not a fake number.

---

## Schema-Growth Veto Surface

`CADEN_learning.md` gates the first schema-growth event behind this
surface. Spec here.

### The veto panel

When the learning system produces a schema-growth proposal:

- The proposal always surfaces here, regardless of whether the triggering
  residuals came from dashboard chat, scheduler output, Project Manager,
  Thought Dump, or a later app. CADEN has one consent surface for schema
  growth.
- A non-blocking notification appears in the chat panel and a
  dedicated "CADEN is proposing something" strip above the today
  panel. Persistent until Sean acts.
- Clicking opens a modal (or inline card) with:
  - The proposed field name and type
  - The rationale (residual cluster that triggered it, LLM's
    reasoning for the field)
  - The back-fill sample (a few past events with the proposed value
    filled in by the LLM, so Sean can sanity-check)
  - The held-out evaluation result (residual reduction number)
  - Three buttons: **Accept**, **Reject**, **Ask more**
- "Ask more" opens a chat branch scoped to the proposal. Whatever
  Sean asks, and the LLM's answers, are attached to the proposal
  event.
- Accept commits the field. Reject archives the proposal (rejected
  proposals stay as training data for future ones per
  `CADEN_learning.md`). Neither action is silent.

### Hard rule

No schema growth commits without Sean's explicit Accept. No auto-accept
on timeout, no auto-reject on timeout. The proposal waits.

---

## Phase-Change Notification Surface

When the phase-change detector fires:

- A persistent banner appears at the top of the dashboard: "CADEN
  noticed your patterns have shifted." Color/icon distinct from
  schema-growth proposals so Sean learns the difference.
- Click to expand: the affected component, the bias direction, the
  residual history that produced the detection, the planned response
  (e.g., "refitting retrieval weights with heavier recency emphasis").
- Three buttons: **Acknowledge**, **Hold off**, **Tell me more**.
  - Acknowledge = proceed with the refit. Event logged.
  - Hold off = pause the refit. Event logged with rationale
    (optional freeform note). Phase-change detection keeps
    monitoring; if the signal strengthens, another banner appears.
  - Tell me more = open chat branch scoped to the detection.

### Hard rule

Phase changes never commit silently. CADEN changing its own model is
a consent event.

---

## Active Optimization Surface

Unlocked only when readiness conditions in `CADEN_learning.md` are met.
Until then, this surface is dormant and the panel shows a simple note
explaining why (residuals still too large; data still too thin).

### When live

- A new strip appears between the today panel and the chat: "Today
  at a glance" showing the predicted mood / energy / productivity
  trajectory for the scheduled day, as three compact sparklines.
- When Sean adds a task, the add-task modal gains a second step:
  **"CADEN has three ways to schedule this."** Three candidate
  schedules shown, each with its predicted three-axis trajectory and
  a Pareto marker. Sean picks. His pick is memory (per the learning
  doc, this trains the preference among Pareto-equivalents).
- If Sean manually edits a CADEN-generated slot, the edit is captured
  as a preference-training event. Axis preserved by the edit is
  inferred by the rater and logged.

### Hard rule

CADEN never picks for Sean silently. If only one schedule is Pareto-
dominant, it's still shown with its trajectory; Sean confirms. If
CADEN cannot produce candidates (upstream failure), it says so loudly
and does not schedule.

---

## Residual Visibility (Audit Surface)

A dedicated tab-within-tab or a keyboard-toggled overlay showing
CADEN's current self-assessment:

- Per-mechanism residual magnitude over time (rater, duration
  predictor, pre-state predictor, post-state predictor, retrieval).
- Which mechanism is weakest right now.
- Recent weight updates and what they were in response to.
- Recent schema-growth proposals (committed and rejected).
- Recent phase-change detections.

This is not a production feature for daily use. It's for Sean when he
wants to audit CADEN, and for future Sprocket to draw on when editing
CADEN itself.

Not shown by default. Keyboard-triggered or a small button, not a
persistent panel.

---

## Input Affordances Beyond Add-Task

v0 has add-task. Post-v0 dashboard also exposes:

- **Quick capture button** — one keystroke captures a thought directly
  into events (distinct from Thought Dump, which is its own app with
  its own surface). This is for "I just remembered something; don't
  interrupt what I'm doing." Captured events get a trigger of
  "dashboard_quick_capture."
- **Inline rating correction** (covered above in the chat panel).
- **Schedule override gesture** — Sean can drag a CADEN-scheduled
  slot to a new time. The drag is a preference-training event. CADEN
  emits a new prediction bundle for the new slot.

No other input surfaces. Chat remains the primary interaction.

---

## Display Discipline

CADEN has a lot of internal machinery. The dashboard must stay
readable. Rules:

- The three-panel layout from v0 is sacred. Post-v0 additions fit
  inside those panels or appear as transient overlays (banners,
  modals). No fourth persistent panel.
- Any new persistent element requires a matching removal or collapse.
  If adding the trajectory strip would crowd the today panel, the
  trajectory strip is collapsible by default and expands on hover or
  keystroke.
- Color is used sparingly and consistently. Proposals, phase changes,
  and residuals each get a distinct subtle color that Sean learns.
  Given Sean's synesthesia, color choices should not be locked here;
  they are a config setting.

---

## Failure Modes (Dashboard-specific)

Must fail loudly:

- Textual fails to render a panel (exception surfaced in status bar,
  not a blank panel).
- A prediction lacks confidence metadata (display refuses to show
  the number; shows "malformed prediction" with a link to the event).
- A proposal modal cannot fetch its back-fill sample (modal refuses
  to open; error logged).
- The readiness check for active optimization returns contradictory
  signals (optimization stays dormant, error logged).
- A sparkline receives NaN (display refuses; shows "data corrupted").

No silent blanks, no "best effort" renders, no partial displays that
hide missing data.

---

## Open Questions

- How much provenance does Sean actually want inline vs. on-demand?
  Current stance: minimal inline, rich on-demand. Revisit once the
  dashboard is live.
- Should the residual audit surface be gated behind a keystroke or
  always available as a tab? Current stance: keystroke, to keep the
  default view clean. Revisit.
- When three candidate schedules are shown, is three always the right
  number? Or should the count be learned from how many Sean actually
  considers before picking? Punt; start with three.
- How does the dashboard render on a bad day (low energy, high mood-
  cost of looking at complex UI)? Possible answer: a "quiet mode"
  that collapses all prediction overlays. But choosing when to offer
  quiet mode is dangerously close to a heuristic; probably Sean
  toggles it manually.
- If Sean's synesthesia makes certain colors actively distracting,
  does the dashboard learn that from override events? Probably yes,
  via the standard residual mechanism — if Sean keeps toggling
  colors, the learner picks defaults that stick. Flag for later.

---

## Deprecated Sections

None yet.
