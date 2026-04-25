# Intake (First-Launch Self-Knowledge Capture)

**Status:** `draft`

**Purpose:** Plan a one-time intake flow that lets Sean seed CADEN's
memory with self-knowledge and code-pattern preferences before the
learning system has any data of its own. This is the only concession
to cold-start pain. Nothing further is added in this direction.

**Depends on:** `CADEN.md`, `CADEN_index.md`, `CADEN_v0.md`,
`CADEN_libbie.md`, `CADEN_learning.md`, `CADEN_sprocket.md`.

---

## Locked Constraints (from `CADEN.md`)

- No hand-written heuristics. Not one.
- No fallbacks. Loud failure only.
- Python only.
- Local-first. Private.
- Declared objective: track mood, energy, productivity; balance all three.
- One central mechanism: Predict, Observe, Correct.

Intake-specific implications:

- **Intake captures data, not rules.** Sean writes notes about Sean.
  Sean writes patterns Sean trusts. The notes and patterns are
  ordinary events in the unified DB. They are not consulted by
  hard-coded logic; they are retrieved like any other memory.
- **Intake is one-time.** There is no recurring "re-intake" mechanism.
  If Sean wants to add more self-knowledge later, he writes a thought
  dump or a chat message. Adding a permanent intake surface would
  pollute back into "the designer thinks Sean should periodically
  reflect."
- **Intake is skippable.** Sean can dismiss the intake surface at
  first launch. CADEN's no-heuristics behavior must work without
  intake data. Intake only shortens the cold-start tax; it does not
  enable any feature that wouldn't otherwise eventually unlock.

---

## Scope

In scope:

- The first-launch intake surface
- What Sean is invited to write (and what he is NOT invited to write)
- How intake content becomes memory (sources, metadata, embedding)
- Skip / partial / resume behavior
- The rule that intake never fires again

Out of scope:

- Any rubric or scoring of what Sean writes. The LLM doesn't grade
  the intake. It just captures.
- Any prompt that pushes Sean toward specific answers. Intake is
  open-ended.
- v0 inclusion. Intake is a v1 add-on. v0 ships without it.
- Recurring or scheduled reflection prompts. Forbidden by the
  one-time rule.

---

## What v0 Gives Intake

Nothing directly. Intake builds on:

- Libbie's `capture` API (per `CADEN_libbie.md`)
- The unified events table with embeddings
- Textual GUI framework
- The dashboard's chat surface (intake reuses chat-style input)

---

## When Intake Runs

- First time CADEN launches with an empty DB AND with intake not
  marked complete-or-skipped.
- Detected by: events table is empty AND no `intake_complete` event
  exists.
- A small modal/banner on the dashboard offers "Intake available."
  Clicking opens the intake surface in a new ephemeral tab. Closing
  the tab without finishing leaves intake resumable.
- After Sean clicks "I'm done" or "Skip," an `intake_complete` event
  is written. The intake surface never appears again on this
  installation.

### Hard rule

Intake never auto-launches as a blocking flow. Sean can ignore the
banner and use CADEN normally. The banner is dismissable; dismissing
writes an `intake_complete` event with `mode = skipped`.

---

## The Intake Surface

A single tab. Two sections, scrollable. Plain Textual layout.

### Section 1: Self-Knowledge

A large text area with a small header: **"Tell CADEN about yourself."**

Below the header, a deliberately short, neutral hint:

> "Anything you want CADEN to know about how you work, what you've
> noticed about yourself, what helps and what doesn't. Write whatever
> comes to mind in whatever order. There is no required structure.
> Submit in chunks (Ctrl+Enter) and keep going as long as you want."

That is the entire prompt. No checklist. No example list of topics.
No "consider writing about your sleep / mood / triggers." Any such
list is a heuristic about what matters.

Each Ctrl+Enter commits one event:

- `source = "intake_self_knowledge"`
- `trigger = "intake_commit"`
- `entry_type = "self_knowledge"` (a metadata field, not a schema
  category)
- standard `captured_at`, `timestamp`, `why` (LLM-generated rationale
  per Libbie rules)

The text area clears after each commit. Sean keeps writing until he's
done.

### Section 2: Code Patterns Sean Trusts

A second text area with header: **"Tell Sprocket about Python code
you trust."**

Hint:

> "Code patterns, libraries, idioms, or specific past code you've
> written and trust. Sprocket will treat these as memories he can
> retrieve and tweak. Paste freely. One commit per pattern."

Each commit captures the text plus an AST parse (per Sprocket's
storage rules in `CADEN_sprocket.md`):

- `source = "intake_code_pattern"`
- `trigger = "intake_commit"`
- `ast_serialized` populated; if the snippet doesn't parse, **loud
  failure** — the snippet is rejected and Sean is told to fix or skip
  it. (No silent storage of unparseable code. Same rule as Sprocket
  generation.)
- standard metadata otherwise

If Sean wants to attach a comment about why he trusts the pattern, he
includes it as a Python comment in the snippet itself or commits a
self-knowledge entry alongside. The intake surface does NOT have a
separate "annotation" field, because that would invite structured
metadata that becomes a schema heuristic.

### Section 3: Done

A "Mark intake complete" button at the bottom. Clicking it:

- Writes an `intake_complete` event with `mode = completed` and the
  count of entries captured in each section.
- Closes the intake tab.
- Removes the intake banner permanently.

### What's NOT in the surface

- No questionnaire.
- No rating sliders.
- No demographic fields.
- No "save and continue later" feature beyond closing the tab (which
  works automatically — events captured persist; a returning Sean
  picks up where he left off).
- No undo. Captured events are immutable per the CADEN-wide rule.
  Sean can write a contradicting entry; both stay.

---

## How Intake Content Is Used

Intake events are ordinary memories. No component reads them via
intake-specific code paths. They participate in retrieval like any
other event.

Concrete consequences:

- The rater's first ratings get richer retrieved context because
  self-knowledge events surface for relevant queries (intake events
  themselves are NOT rated — see Implementation Contracts in
  `CADEN_v0.md`. They feed retrieval but are skipped by the rater).
  This shortens the rater's cold start.
- Sprocket's first builds get richer retrieved context because
  code-pattern events surface for relevant briefs. Source-quality
  starts at zero for everything; intake-provided patterns earn their
  scores through the same residual mechanism as web sources.
- Libbie's surfacing has more material to surface from on day one.

### Hard rules

- Intake events are NOT given a permanent retrieval boost. They earn
  their weights through the standard residual loop. If an intake
  self-knowledge note turns out to be wrong, retrieval will downrank
  it like any stale memory. Sean's day-one belief about himself does
  not get protected status.
- Intake events are NOT marked as ground truth. They are predictions
  about Sean (made by Sean), and they accrue residuals like
  everything else.
- Intake events are NEVER deleted, even if they become outdated.
  Same rule as ratings, thoughts, projects.

---

## Skip and Partial States

- **Skip:** banner dismissed before opening the surface. Writes
  `intake_complete` with `mode = skipped`, `entries_count = 0`. Banner
  never returns.
- **Opened, never committed anything:** closing the tab leaves intake
  resumable. Banner returns next launch.
- **Opened, committed some, didn't click Done:** events captured;
  intake resumable. Banner returns next launch with note "Resume
  intake (X entries already captured)."
- **Opened and clicked Done:** complete. Banner gone forever.

---

## Failure Modes (Intake-specific)

Must fail loudly:

- Libbie capture fails on commit (embedding unreachable, DB
  unreachable). Same rule as Thought Dump: text area preserves its
  content, error banner appears. Losing intake work to a silent
  failure violates the spirit of the surface.
- AST parse fails on a code-pattern entry. Snippet rejected, Sean
  shown the parse error, can fix and resubmit.
- The `intake_complete` event fails to write. Loud error; intake stays
  in its current state until the write succeeds. (Otherwise the
  banner could resurrect after Sean thought he was done, which is
  worse than a one-time error visible to Sean.)

---

## Open Questions

- Should intake surface a small "what would help CADEN learn faster"
  hint anywhere? Current stance: no. Any such hint is a designer's
  claim about what's useful. The neutral prompts already given are
  the firm boundary.
- If Sean reinstalls CADEN with a fresh DB but has old intake data
  he wants to preserve, is there an import path? Current stance: out
  of scope. Backup/restore of the whole DB is the answer to that
  question, not intake-specific import.
- Could intake be re-offered after a phase-change detection ("you've
  changed; want to re-intake?")? **Tempting and rejected.** That's
  exactly the recurring-reflection pollution the one-time rule
  forbids. Sean can write new self-knowledge any time via thought
  dump or chat. The system doesn't ask.

---

## Deprecated Sections

None yet.
