# Project Manager App (Post-v0)

**Status:** `draft`

**Purpose:** Plan the Project Manager app. Second tab in the CADEN GUI.
A place where Sean keeps track of everything he's working on — where
"project" means any task realm, including school classes, hobbies,
research threads, code projects, life projects, anything bounded.

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

Project-Manager-specific constraints from the spec:

- **Narrow project navigation panel on the left.** Rest of the screen
  shows the selected project.
- **Entry types via a row of buttons:** TODO, what-if, update, comment.
- **Enter submits; entries embed into the central DB** just like every
  other CADEN input. Entries are thought-chain material ready to be
  resurfaced.
- **Libbie works out of the Project Manager** — same DB discipline, no
  per-project silos.

---

## Scope

In scope:

- What a project is (identity and schema)
- Project creation (Sean-initiated and CADEN-proposed)
- Navigation panel ordering rule
- Entry types and their behaviors
- TODO lifecycle and Google Tasks integration
- Libbie's cross-project role
- Surface details (the project view itself)

Out of scope:

- Any learning mechanics (lives in `CADEN_learning.md`)
- General memory semantics (lives in `CADEN_libbie.md`)
- Sprocket's relationship to PM (that's a Sprocket concern, handled in
  `CADEN_sprocket.md`)
- v0 material. PM is not in v0.

---

## What "Project" Means

A **task realm**. Anything bounded Sean wants to group thoughts, work
items, and updates around. Examples Sean named: school classes,
personal projects, research threads. Not restricted to software.

### Identity

- First-class schema object: rows in a `projects` table.
- Starting fields: `id`, `name`, `created_at`, `last_touched_at`.
- No `status` field. No archive state. No completion state. Sean's
  attention is the only signal that matters for ordering, and that's
  captured by `last_touched_at`.
- Additional fields can arrive via schema growth (per
  `CADEN_learning.md`), not by pre-declaration.

### Why first-class (and not a tag on events)

- The left navigation panel requires a list of nameable, selectable
  entities. A cluster-learned identity can't be named in a sidebar
  without the sidebar becoming a heuristic about clustering.
- Sean explicitly said "task realm" — a container concept, not a
  search filter.
- Events still point at their project via a `project_id` field on the
  event row. Retrieval stays unified: Libbie can query events
  regardless of project, scoped by project, or across projects.

### Hard rule

A project's data is not a silo. All project entries are ordinary
events with a `project_id` pointer. Libbie's retrieval ignores
`project_id` unless a caller explicitly scopes by it. The one-DB,
no-fragmentation rule from `CADEN_libbie.md` holds.

---

## Project Creation

Two paths.

### Path 1: Sean creates explicitly

- A "New Project" button, somewhere unobtrusive in the nav panel
  (bottom of the list, or a small `+` icon at the top — defer to
  layout time).
- Modal asks for a name. That's it. No description field, no tags, no
  category. If Sean wants to describe the project, his first
  `comment` entry is the description.
- On creation, a `projects` row is written, and a project-creation
  event is captured (source = `pm_project_created`).

### Path 2: CADEN proposes a project from clustering

- The learning system may observe that recent events cluster around a
  topic not currently covered by any project. This is a form of
  schema-growth-adjacent pattern detection.
- When the clustering signal is strong enough (threshold is a learned
  parameter), CADEN proposes a new project. The proposal surfaces in
  the dashboard (schema-growth veto surface style: Accept / Reject /
  Ask more), not inside PM itself.
- On accept, the project is created and CADEN optionally offers to
  back-fill `project_id` on the clustered events. Sean confirms per
  event or in bulk. Rejected events stay with `project_id = null`.
- On reject, the proposal is archived as an event (training data for
  future proposals).

### Hard rules

- CADEN never creates a project silently.
- Sean can rename a project at any time. Name changes are events
  (append-only history). The project's `id` never changes.
- Projects are never deleted. If Sean is done with a project, it
  simply stops getting touched and drifts to the bottom of the nav
  list. Deletion would violate no-deletion-of-memory.

---

## Navigation Panel Ordering

- Projects are listed **in order of `last_touched_at`**, most recent
  at the top.
- "Touched" = any entry captured against the project. Ordering
  updates on every commit.
- No folders, no grouping, no manual ordering. Recency is the only
  axis. This keeps the panel honest: Sean sees what he's actually
  working on at the top, and dormant projects fall away without
  needing an archive gesture.
- No filtering UI in v1 of PM. If Sean wants to find an old project,
  the search path is chat ("where was I working on X?") which Libbie
  retrieves.

### Why no archive button

Sean explicitly rejected status tracking. "Archived" is a heuristic
about when Sean is done. Recency ordering solves the same problem
without the claim.

---

## Entry Types

Four buttons in a row above the entry input, per spec: **TODO**,
**what-if**, **update**, **comment**.

The chosen button becomes the entry's `entry_type` metadata field on
capture. Behaviors differ only where noted.

### comment

- Default / neutral entry type. No special behavior.
- Stored as an event with `source = "pm_entry"`, `entry_type =
  "comment"`, `project_id = <current project>`.
- Embeds, rates, participates in retrieval normally.

### update

- Same behavior as comment at capture time. The label is semantic —
  it tells future retrieval "this was status, not idea." Libbie's
  retrieval weight learner may or may not find the distinction
  useful; that's its problem to decide via residuals.
- No hand-written rule says updates show up differently in the
  project view. They look like any other entry in chronological order.

### TODO

- **Creates a Google Task** on capture.
- Task title = the TODO text (first line if multiline).
- Task notes = structured metadata: the full entry text, the
  CADEN event id, the `project_id`, and the `pm_project_name`. The
  notes field is the integration point — CADEN reads its own metadata
  out of the notes field on the way back in.
- The created Google Task id is stored on the event and on a
  `pm_task_links` table row (linking project ↔ event ↔ google_task_id).
- Completion in Google Tasks flows back per v0's completion-detection
  mechanism. The PM surface reflects the completed state but does
  **not** hide completed TODOs (no-deletion-of-memory extends to
  display; a completed TODO is still part of the project's thought
  chain).
- **TODOs are done through Google Tasks.** That's the source of truth
  for completion. PM does not have its own "mark done" button for
  TODO entries; Sean marks done in Google Tasks (or wherever v0's
  completion surface lives).

#### Why notes-field metadata

- Google Tasks doesn't have custom fields. Notes is the only
  free-form attachment point.
- The framework repair layer (per `CADEN_v0.md`) handles parsing
  notes back into structured form loudly when it can't.
- Sean can still read the notes in Google Tasks; the metadata is
  appended below any human-readable text. Format is stable enough to
  be parsed back reliably, loud on failure.

### what-if

- **Just an idea Sean wants to save for later** so he can focus on a
  narrower scope right now.
- Same capture path as comment. No prediction is emitted. No watch
  list. No scheduled follow-up.
- The what-if is memory. Libbie will surface it naturally when
  related work comes up later, via the same retrieval that surfaces
  anything else. That's the entire behavior.
- The label exists so Sean (and retrieval) can distinguish
  "I decided this is what I'm doing" (update) from "I thought of
  this but I'm not doing it" (what-if).

---

## Project View (Right-Side Main Area)

When a project is selected:

- Entry input at the top or bottom (defer to layout time), with the
  four entry-type buttons in a row above the input box.
- Below that: a chronological list of all entries for this project,
  newest on top (or bottom — defer to layout time; probably newest
  on top to match the nav panel ordering convention).
- Entries show: timestamp, entry_type label, the text, and a small
  marker if the entry is a TODO that's now completed.

No counters, no burn-down, no progress bar, no metrics. PM is a
thought-chain surface, not a productivity dashboard. The dashboard
app is where productivity metrics live, if anywhere.

### What's not in the project view

- No filter-by-entry-type controls. Sean can see all entries in order;
  if he wants just TODOs, that's a Google Tasks view.
- No edit-in-place on entries. Events are immutable. If Sean wants to
  revise a thought, he adds a new entry.
- No delete button. Ever.
- No per-project settings panel in v1. If configuration becomes
  necessary later, it goes in a dedicated modal, not cluttering the
  main view.

---

## Libbie's Role in PM

Per the open question "what does Libbie concretely do here beyond
normal retrieval?":

- **Cross-project surfacing.** When Sean is viewing a project, Libbie
  proactively surfaces entries from OTHER projects that are
  semantically related to recent activity in this one. This is the
  PM-specific value-add.
- Surfaced cross-project entries appear in a small, collapsible side
  strip within the project view. Not mixed into the main entry list
  (that would confuse chronology and provenance).
- Each surfaced entry shows its origin project. Clicking it jumps to
  that project.
- Surfacing is the standard `libbie.surface(context)` call from
  `CADEN_libbie.md`, scoped by excluding the current project. Its
  predictions earn residuals as usual — if cross-project surfacing
  turns out to be noise, retrieval weights will learn to downrank it.

### Hard rule

The cross-project surfacing strip is collapsible and remembers its
collapsed state per project (persisted to the projects row, or as a
preference event — defer). If Sean doesn't want cross-pollination for
a given project, collapse stays collapsed. CADEN doesn't re-expand it.

---

## Schema Sketch (for reference, not commitment)

Conceptual, not final. Final schema grows via `CADEN_learning.md`'s
rules.

- `projects` table: `id`, `name`, `created_at`, `last_touched_at`.
- `events` table (already exists from v0): add nullable `project_id`
  column. Null for non-PM events.
- `pm_task_links` table: `event_id`, `project_id`, `google_task_id`,
  `created_at`. Lets CADEN look up tasks by project fast without
  pandas-grouping every time.

Nothing else gets pre-declared.

---

## Failure Modes (PM-specific)

Must fail loudly:

- Creating a Google Task from a TODO entry fails (network, auth,
  API). The event is still captured (it's a memory either way), but
  a loud error banner appears in the project view indicating the
  Google Task creation failed. Sean can retry via a small retry
  control on the entry. No silent skip.
- Parsing the notes-field metadata on a returning Google Task fails
  after the repair layer does its job. Loud error event logged. The
  Google Task is still recognized as a task (per v0), but its PM
  linkage is flagged missing. Sean sees this flag on the task.
- CADEN's project-proposal clustering produces contradictory signals
  (cluster fits multiple existing projects well). Proposal is
  suppressed; event logged; retry gated by additional data.
- A project's `last_touched_at` fails to update on a commit. Loud
  error. Commit still captures the event (no silent data loss), but
  nav-panel ordering will be wrong until the update succeeds.

---

## Open Questions

- Layout specifics: entry input at top or bottom of the main view?
  Entries newest-first or oldest-first? Defer to build time; not
  design-level decisions.
- When Sean renames a project, should old entries' retrieval context
  use the old name or the new one? Current stance: retrieval uses
  current name (the rename is a deliberate reframing by Sean);
  history preserves old names for provenance.
- When CADEN proposes a project, what's the minimum cluster size?
  Learned parameter per `CADEN_learning.md`, bootstrap at something
  small (e.g., 5 events) and let residuals tune.
- Does the cross-project surfacing strip show up in the chat tab too,
  when the chat is about a specific project? Probably yes but outside
  this doc's scope; revisit in the dashboard doc if it matters.
- Is the `pm_task_links` table necessary, or can a denormalized field
  on `events` do the same job? Current stance: separate table for
  query speed, but this is a mild pre-optimization. Revisit if
  residuals don't care.
- What if a TODO entry text is too long for a Google Task title?
  Current stance: first line = title, full text goes in notes above
  the metadata block. Loud failure only if even the first line is
  empty.

---

## Deprecated Sections

None yet.
