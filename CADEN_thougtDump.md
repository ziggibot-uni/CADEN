# Thought Dump App (Post-v0)

**Status:** `draft`

**Purpose:** Plan the Thought Dump app. The spec calls it "an abyss for
Sean to type his thoughts into without shame." Small surface, simple
behavior, but memory-critical.

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

Thought-Dump-specific constraints from the spec:

- **An abyss without shame.** No judgement, no prompts, no structure
  imposed. Sean types; CADEN absorbs.
- **Everything embeds into the central DB.** Same DB as everything else.
  No thought-dump silo.
- **Hide button ciphers the visible text** (not the data, just what's
  on screen) so nobody reading over Sean's shoulder can see.

---

## Scope

In scope:

- Input surface (what the app looks and behaves like)
- Capture behavior (how thoughts become memories)
- The Hide button
- Interaction with the rater
- Interaction with Libbie's surfacing (does a thought dump influence
  other apps?)
- Privacy posture

Out of scope:

- Any content classification or auto-tagging. Thought Dump stays
  unstructured by design.
- Any "prompts for reflection" or guided journaling. That's shame. No.
- v0 material. v0 does not include Thought Dump at all.

---

## What v0 Gives Thought Dump

Nothing directly. Thought Dump is not in v0. It builds on:

- Libbie's `capture` API.
- The rater (events get rated; thought-dump events are no exception).
- The unified events table with embeddings.
- Textual GUI framework.

---

## Surface

One tab in the CADEN GUI. When selected, the screen becomes:

- A large text input area filling most of the screen.
- A small header strip with the app name and the Hide button.
- Nothing else. No sidebar, no history view, no counters, no tags,
  no prompts, no character count.

The emptiness is the feature. Any UI element is a judgement by
proximity. An empty field asks nothing.

### Why no history view in Thought Dump

- History would make Sean self-conscious about what past-Sean wrote.
  Defeats the "without shame" promise.
- Past thoughts still influence CADEN via retrieval. The influence is
  invisible from the Thought Dump surface but real in the dashboard
  and in ratings.
- If Sean wants to search past thoughts, that's a chat-in-the-dashboard
  task, not a Thought-Dump task.

---

## Capture Behavior

The question: when does typed text become a memory?

### Stance

- Capture on explicit commit. The default commit is pressing a key
  combination (e.g., Ctrl+Enter), not a timer and not on unfocus.
- Nothing saves automatically while typing. Draft state is in-memory
  only. If Sean closes the app without committing, the draft is lost.
  This is intentional: partial thoughts without commit are not
  memories; they're half-formed noise Sean chose not to keep.
- On commit, the full text becomes one event. One commit = one event.
  Sean decides the granularity by choosing when to commit.
- After commit, the text area clears. No "last commit" view. The
  abyss is empty again.

### Metadata on capture

Per `CADEN_libbie.md`:

- `source = "thought_dump"`
- `trigger = "thought_dump_commit"`
- `why` — LLM-generated rationale, as for all captures. The LLM may
  say something like "Sean dumped a thought about X while Y was on the
  schedule." The rationale is a guess; residuals correct it over time.
- `captured_at`, `timestamp` — both set to commit time.

### No editing

Thought-dump events are immutable like all events. If Sean wants to
revise a thought, he dumps a new one. History of thoughts is additive.
Same rule as ratings.

---

## The Hide Button

Per spec: cyphers all text on the app's screen (not the full CADEN GUI,
just the Thought Dump app), so onlookers can't read.

### Design

- Toggle. On = visible text is replaced with a cipher rendering in
  the text area and in any transient status messages this app shows.
  Off = normal.
- Cipher is a cosmetic substitution. It does not touch stored data.
  Data at rest is never ciphered by this button — it's always the
  real thought, stored per Libbie's rules. Hide is screen-only.
- The cipher does not have to be a real cryptographic construction.
  It's a readability defeater. A simple character-mapping shuffle
  (consistent per session so Sean can still see where his cursor is)
  is enough.
- Keyboard shortcut available. The button works too but the shortcut
  is the primary path, because Sean needs to hit it fast when someone
  walks up.

### Hard rules

- Hide never blocks capture. Sean can type with Hide on and commit
  with Hide on. The data stored is still the real text.
- Hide does not persist across app restarts. Default state on launch
  is visible. (Reason: if someone else launches CADEN on Sean's
  machine, Hide-on by default hides nothing useful; Hide-off by
  default means the dump area is empty anyway because nothing is shown
  until Sean types.)
- Hide affects only the Thought Dump tab. Switching tabs while Hide
  is on shows the other tabs normally. The other tabs have their own
  content considerations (the dashboard is not shame-sensitive).

---

## Interaction With the Rater

Thought-dump events are rated like any other event on mood / energy /
productivity. This is not optional and not a special case.

- The rater gets the text + retrieved past events + Sean's self-
  knowledge memories. Output is three ratings with confidences. Rated
  event is stored alongside the thought, immutable.
- Thought-dump ratings feed into the same residual mechanism as
  everything else. If the rater is systematically wrong on thought-
  dump events specifically, that's a cluster the learning system can
  pick up (per `CADEN_learning.md`).
- Rating happens silently in the background. Sean is not shown the
  rating in the Thought Dump surface (that would undermine the "no
  judgement" promise). Ratings show up wherever ratings show up
  elsewhere in CADEN — primarily the dashboard's audit surface.

---

## Interaction With Libbie's Surfacing

Thought-dump events are first-class memories. They participate fully
in retrieval and surfacing.

- Other apps (the chat, the scheduler) retrieve thought-dump events
  when semantically relevant. A dumped thought about "I hate mornings"
  may surface weeks later when CADEN is proposing a morning schedule.
  This is the point.
- Thought Dump itself does NOT surface back into its own UI. Sean
  writes into the abyss and sees nothing. CADEN sees everything.
- Libbie may generate `libbie_observation` events triggered by patterns
  in thought-dump content (e.g., "Sean has mentioned X repeatedly in
  dumps"). These observations are not shown inside Thought Dump either.
  They surface through the dashboard's audit surface or via the chat
  naturally bringing them up.

---

## Privacy Posture

Thought Dump is the shame-free surface. Extra care:

- Data at rest is in the same local DB as everything else. Encryption
  at rest is not part of v0 or this doc. If it becomes a requirement,
  it applies to the whole DB, not just thought-dump rows. No
  special-casing.
- Hide button exists for onlooker defense, not cryptographic defense.
- No telemetry, no analytics, no backups to cloud. Already locked by
  spec but worth restating for this surface especially.
- LLM prompts that include thought-dump content stay on-device
  (ollama). Web search (SearXNG) is never invoked on thought-dump
  content automatically; if CADEN needs to search based on a thought,
  that happens through the chat loop, not Thought Dump.

### Hard rule

Thought-dump content never leaves the machine for any reason tied to
this app. If a future feature wants to use thought-dump content as
training signal for something external, the answer is no. The answer
will keep being no.

---

## Failure Modes (Thought-Dump-specific)

Must fail loudly:

- Libbie capture fails on commit (embedding unreachable, DB
  unreachable). The text area does NOT clear; an error banner appears
  in the app header; Sean sees that his thought was not saved. This is
  the only case where the text area preserves its content after a
  commit attempt.
- Rater fails on a thought-dump event. Event is still stored (capture
  succeeded); rating failure logs an error event; the rater will
  retry on its own schedule (per `CADEN_learning.md`'s retry
  discipline — which is itself punted, so for now: no retry, loud log
  only).
- Hide toggle fails to render (text stays visible). Loud status bar
  error. Sean must know hiding didn't work before he turns away from
  the screen.

### Hard rule on the commit failure case

Losing a thought is worse than almost any other failure mode in CADEN.
The text area preserving content on failed commit is the only
exception to the "append-only, text clears after commit" model, and
it's justified because the alternative (silently losing what Sean
just typed) violates shame-free in the cruelest way.

---

## Open Questions

- Is Ctrl+Enter the right commit gesture, or should commit be
  double-Escape / a dedicated key / configurable? Punt; make it
  configurable at build time, default Ctrl+Enter.
- Should there be a "discard" explicit action, or is closing the app
  / switching tabs with uncommitted text enough? Current stance:
  switching tabs discards silently. If Sean wanted to keep it, he
  would have committed. Revisit if this loses too much.
- Is it actually true that no history view belongs here, or does Sean
  want a minimal "last N commits" strip that he can toggle? Current
  stance: no. The temptation to self-edit past-Sean is real, and
  history in this surface feeds it. Revisit only if Sean asks.
- Does the rater ever call out thought-dump events as especially
  important signal (e.g., high-affect text)? Not by rule. If the
  learning system decides thought-dump residuals deserve more weight,
  that's fine; it emerges, it isn't written.
- Should Hide be available globally via a system keybind (works even
  when another tab is focused)? Tempting but out of scope — a global
  hotkey that ciphers one tab is surprising. Punt.

---

## Deprecated Sections

None yet.
