# CADEN Supplemental Documentation Claims Matrix

This file tracks feature claims found across all CADEN documentation files,
including planning and app-specific docs.

Purpose:
- capture claims that exist outside the authoritative pair (`CADEN.md` and
  `CADEN_v0.md`)
- preserve a backlog of potential future traceability rows
- separate planning/draft/open-question content from locked implementation
  contracts

Relation to `CADEN_testMatrix.md`:
- this file is supplemental and non-authoritative by default
- rows here can be promoted into the authoritative matrix when a claim is
  intentionally locked as a requirement

Strict implementation-proof companion:
- `CADEN_learning_libbie_scientific_audit.md` tracks claim-by-claim
  evidence grades (`Proven`, `Partial`, `Unproven`) specifically for
  Learning + Libbie, with direct code/test citations.

## Classification Legend

- `active`: described as currently intended behavior in the source
- `planned`: described as post-v0 or future behavior
- `open_question`: unresolved gap/issue statement
- `process_only`: documentation/process constraint, not runtime product behavior
- `historical`: history text retained for record, not active requirement

## Claims By Document

### CADEN_buildBrief.md

| ID | Source | Claim | Classification |
| --- | --- | --- | --- |
| DOC-001 | `CADEN_buildBrief.md` | v0 loads config from `~/.config/caden/settings.toml` | active |
| DOC-002 | `CADEN_buildBrief.md` | settings file is auto-created on first launch if missing | active |
| DOC-003 | `CADEN_buildBrief.md` | model choice comes from settings | active |
| DOC-004 | `CADEN_buildBrief.md` | root GUI is Textual app with `TabbedContent` and v0 Dashboard tab | active |
| DOC-005 | `CADEN_buildBrief.md` | dashboard uses 3-panel layout with left/middle/right roles | active |
| DOC-006 | `CADEN_buildBrief.md` | today panel window is 5 AM local to next 5 AM local | active |
| DOC-007 | `CADEN_buildBrief.md` | today panel mixes calendar, tasks, and CADEN blocks chronologically | active |
| DOC-008 | `CADEN_buildBrief.md` | 7-day panel is anchored from same circadian boundary | active |
| DOC-009 | `CADEN_buildBrief.md` | add-task modal requires description and deadline | active |
| DOC-010 | `CADEN_buildBrief.md` | milestone smoke-test approach: one E2E test per milestone | process_only |

### CADEN_dashboard.md

| ID | Source | Claim | Classification |
| --- | --- | --- | --- |
| DOC-011 | `CADEN_dashboard.md` | current v0 surface becomes Dashboard tab in multi-app CADEN | planned |
| DOC-012 | `CADEN_dashboard.md` | today panel will show prediction bundle per CADEN-scheduled item | planned |
| DOC-013 | `CADEN_dashboard.md` | today panel will show residuals after completion | planned |
| DOC-014 | `CADEN_dashboard.md` | chat panel may expose retrieved memories in collapsible strip | planned |
| DOC-015 | `CADEN_dashboard.md` | chat panel may show inline rating/correction affordance | planned |
| DOC-016 | `CADEN_dashboard.md` | 7-day panel may include axis trajectory sparklines | planned |
| DOC-017 | `CADEN_dashboard.md` | schedule what-if surface allows alternative schedule preview/selection | planned |
| DOC-018 | `CADEN_dashboard.md` | schema-growth proposals require explicit Sean accept/reject | planned |
| DOC-019 | `CADEN_dashboard.md` | phase-change alert surface with acknowledge/hold/tell-me-more controls | planned |
| DOC-020 | `CADEN_dashboard.md` | active optimization unlocks only after readiness conditions | planned |
| DOC-021 | `CADEN_dashboard.md` | add-task may show multiple candidate schedules with Pareto markers | planned |
| DOC-022 | `CADEN_dashboard.md` | residual audit overlay is transient and non-persistent | planned |
| DOC-023 | `CADEN_dashboard.md` | drag override on CADEN block is logged as preference-learning event | planned |
| DOC-024 | `CADEN_dashboard.md` | sacred 3-panel dashboard layout remains intact as features expand | planned |

### CADEN_gapList.md

| ID | Source | Claim | Classification |
| --- | --- | --- | --- |
| DOC-025 | `CADEN_gapList.md` | retrieval still has legacy/raw paths that should be converged | open_question |
| DOC-026 | `CADEN_gapList.md` | rater retrieval wiring and curated-memory usage have known alignment gaps | open_question |
| DOC-027 | `CADEN_gapList.md` | bootstrap constants remain in config and need reduction/audit | open_question |
| DOC-028 | `CADEN_gapList.md` | completion polling semantics needed reframing as implementation detail | open_question |
| DOC-029 | `CADEN_gapList.md` | memory-frame synthesis includes transitional scaffolding that may need tightening | open_question |

### CADEN_index.md

| ID | Source | Claim | Classification |
| --- | --- | --- | --- |
| DOC-030 | `CADEN_index.md` | docs are intentionally status-tagged (`locked`, `draft`, `deprecated`) | process_only |
| DOC-031 | `CADEN_index.md` | `CADEN.md` is immutable unless explicitly reopened | process_only |
| DOC-032 | `CADEN_index.md` | `CADEN_v0.md` is locked for v0 contracts | process_only |
| DOC-033 | `CADEN_index.md` | recommended reading order defines documentation precedence | process_only |

### CADEN_learning.md

| ID | Source | Claim | Classification |
| --- | --- | --- | --- |
| DOC-034 | `CADEN_learning.md` | schema growth is triggered by persistent residual failure plus weight plateau | planned |
| DOC-035 | `CADEN_learning.md` | LLM proposes schema fields and proposals are evaluated on historical data | planned |
| DOC-036 | `CADEN_learning.md` | accepted fields are back-filled and evaluated on held-out residual improvement | planned |
| DOC-037 | `CADEN_learning.md` | schema growth never deletes fields; weak fields decay toward zero weight | planned |
| DOC-038 | `CADEN_learning.md` | proposal decisions are logged with full provenance | planned |
| DOC-039 | `CADEN_learning.md` | Sean may veto schema growth before commitment | planned |
| DOC-040 | `CADEN_learning.md` | phase change is detected from residual statistics and bias shifts | planned |
| DOC-041 | `CADEN_learning.md` | phase correction uses recency-weighted refits, not history rewrites | planned |
| DOC-042 | `CADEN_learning.md` | old ratings remain immutable throughout adaptation | planned |
| DOC-043 | `CADEN_learning.md` | retrieval weights learned via Ridge-style residual fitting | planned |
| DOC-044 | `CADEN_learning.md` | active optimization ranks schedule options using Pareto logic | planned |
| DOC-045 | `CADEN_learning.md` | Sean selects among candidate schedules; picks are logged as learning events | planned |
| DOC-046 | `CADEN_learning.md` | no fixed weighted-sum objective is allowed for 3-axis tradeoff | planned |

### CADEN_libbie.md

| ID | Source | Claim | Classification |
| --- | --- | --- | --- |
| DOC-047 | `CADEN_libbie.md` | Libbie keeps one central DB for all memory, no storage fragmentation | active |
| DOC-048 | `CADEN_libbie.md` | raw events are immutable provenance and memories are CADEN-facing reasoning units | active |
| DOC-049 | `CADEN_libbie.md` | ligand is transient retrieval state and not persisted as memory | active |
| DOC-050 | `CADEN_libbie.md` | SearXNG integration supports public web lookup captured as memories | active |
| DOC-051 | `CADEN_libbie.md` | metadata supports captured_at/trigger/why/linked_to keys in baseline schema | active |
| DOC-052 | `CADEN_libbie.md` | Libbie may proactively surface memories on meaningful context changes | planned |
| DOC-053 | `CADEN_libbie.md` | self-knowledge memories are first-class and influence rating quality | active |
| DOC-054 | `CADEN_libbie.md` | Project Manager events remain inside Libbie and same central DB | active |
| DOC-055 | `CADEN_libbie.md` | SearXNG failures should be loud, without silent fallback | active |
| DOC-056 | `CADEN_libbie.md` | predict-observe-correct loop relies on Libbie retrieval and residual capture | active |
| DOC-056a | `CADEN_libbie.md` | ligand influences one retrieval pass only and then disappears | active |
| DOC-056b | `CADEN_libbie.md` | CADEN never sees the raw ligand object; only packaged ligand-derived context | active |

### CADEN_projectManager.md

| ID | Source | Claim | Classification |
| --- | --- | --- | --- |
| DOC-057 | `CADEN_projectManager.md` | Project Manager is a dedicated TabPane in CADEN GUI | planned |
| DOC-058 | `CADEN_projectManager.md` | project entity has id/name/created_at/last_touched_at core fields | planned |
| DOC-059 | `CADEN_projectManager.md` | projects are ordered by `last_touched_at` recency | planned |
| DOC-060 | `CADEN_projectManager.md` | projects are not deleted under no-deletion memory principle | planned |
| DOC-061 | `CADEN_projectManager.md` | entry types are TODO, what-if, update, comment | planned |
| DOC-062 | `CADEN_projectManager.md` | TODO entries create Google Tasks and preserve metadata linkage | planned |
| DOC-063 | `CADEN_projectManager.md` | completion state comes from shared Google/Task completion path | planned |
| DOC-064 | `CADEN_projectManager.md` | what-if entries are stored for retrieval but do not create immediate predictions | planned |
| DOC-065 | `CADEN_projectManager.md` | cross-project related-entry strip appears in project view | planned |
| DOC-066 | `CADEN_projectManager.md` | CADEN may propose projects from clustering, pending Sean decision | planned |
| DOC-066a | `CADEN_projectManager.md` | project entries are immutable; revisions are appended as new entries | planned |

### CADEN_sprocket.md

| ID | Source | Claim | Classification |
| --- | --- | --- | --- |
| DOC-067 | `CADEN_sprocket.md` | Sprocket is a separate TabPane with app list + chat workspace | planned |
| DOC-068 | `CADEN_sprocket.md` | Sprocket chat is separate from dashboard chat history scope | planned |
| DOC-069 | `CADEN_sprocket.md` | flow is Libbie brief first, then Sprocket implementation planning | planned |
| DOC-070 | `CADEN_sprocket.md` | Libbie brief may include past builds, context, and SearXNG if memory is thin | planned |
| DOC-071 | `CADEN_sprocket.md` | successful nearby examples prefer copy-and-tweak over from-scratch generation | planned |
| DOC-072 | `CADEN_sprocket.md` | code memories include AST representation plus textual form | planned |
| DOC-073 | `CADEN_sprocket.md` | non-parsing code is rejected loudly and not stored | planned |
| DOC-074 | `CADEN_sprocket.md` | retrieval uses semantic and structural (AST) pathways | planned |
| DOC-075 | `CADEN_sprocket.md` | execution occurs in restricted sandbox with no network by default | planned |
| DOC-076 | `CADEN_sprocket.md` | timeout/attempt budget are learned controls, not fixed constants | planned |
| DOC-077 | `CADEN_sprocket.md` | source quality is learned from outcomes without manual allowlist | planned |
| DOC-078 | `CADEN_sprocket.md` | abstraction templates emerge from successful-cluster analysis | planned |
| DOC-079 | `CADEN_sprocket.md` | successful builds can be integrated into new CADEN TabPane after review | planned |
| DOC-080 | `CADEN_sprocket.md` | accepted integration modifies app registration and runs smoke-test gate | planned |
| DOC-081 | `CADEN_sprocket.md` | v1 guardrail: no modifications to existing CADEN code, only new app/files | planned |
| DOC-081a | `CADEN_sprocket.md` | copy-and-tweak path performs AST rewrite rather than string substitution | planned |

### CADEN_thougtDump.md

| ID | Source | Claim | Classification |
| --- | --- | --- | --- |
| DOC-082 | `CADEN_thougtDump.md` | Thought Dump is a dedicated TabPane in CADEN GUI | planned |
| DOC-083 | `CADEN_thougtDump.md` | UI is a minimal large text input with no history/counters/tags/prompts | planned |
| DOC-084 | `CADEN_thougtDump.md` | capture occurs only on explicit commit action | planned |
| DOC-085 | `CADEN_thougtDump.md` | one commit creates one event; draft loss on close is accepted behavior | planned |
| DOC-086 | `CADEN_thougtDump.md` | metadata includes source/trigger and asynchronous why generation | planned |
| DOC-087 | `CADEN_thougtDump.md` | hide mode is visual cipher only, default-visible, and tab-local | planned |
| DOC-088 | `CADEN_thougtDump.md` | hide mode never alters stored text and never blocks capture | planned |
| DOC-089 | `CADEN_thougtDump.md` | thought-dump events are rated silently in background | planned |
| DOC-090 | `CADEN_thougtDump.md` | thought-dump events are first-class in retrieval, but not resurfaced inside Thought Dump UI | planned |
| DOC-091 | `CADEN_thougtDump.md` | thought-dump content does not auto-trigger SearXNG and stays local-only | planned |
| DOC-091a | `CADEN_thougtDump.md` | hide mode does not persist across restarts; launch defaults to visible | planned |
| DOC-091b | `CADEN_thougtDump.md` | hide render failure is surfaced loudly before Sean can assume concealment | planned |
| DOC-091c | `CADEN_thougtDump.md` | failed commit preserves typed text as the only clear-after-commit exception | planned |

### CADEN.md

| ID | Source | Claim | Classification |
| --- | --- | --- | --- |
| DOC-092 | `CADEN.md` | CADEN learns Sean behavior over time using deterministic methods around LLM reasoning | active |
| DOC-093 | `CADEN.md` | objective balances mood, energy, productivity without tanking other axes | active |
| DOC-094 | `CADEN.md` | no hand-written heuristics about Sean are allowed | active |
| DOC-095 | `CADEN.md` | loud-failure/no-fallback behavior is required | active |
| DOC-096 | `CADEN.md` | architecture is local-first with Ollama and central Libbie memory DB | active |
| DOC-097 | `CADEN.md` | dashboard uses 3-panel layout with 5 AM circadian boundary | active |
| DOC-098 | `CADEN.md` | chats are embedded into Libbie and retrieval penalizes overlong memories | active |
| DOC-099 | `CADEN.md` | Project Manager/Thought Dump/Sprocket are planned sibling apps | planned |

### CADEN_v0.md

| ID | Source | Claim | Classification |
| --- | --- | --- | --- |
| DOC-100 | `CADEN_v0.md` | v0 core loop is Predict, Observe, Correct with residual-driven updates | active |
| DOC-101 | `CADEN_v0.md` | each incoming event is rated on 3 axes with rationale and confidence | active |
| DOC-102 | `CADEN_v0.md` | old ratings are immutable and never overwritten/back-filled | active |
| DOC-103 | `CADEN_v0.md` | add-task emits prediction bundle and creates task-event pairing | active |
| DOC-104 | `CADEN_v0.md` | completion edits paired event timing and writes residual memories | active |
| DOC-105 | `CADEN_v0.md` | chat stores Sean inputs with embeddings; CADEN replies remain ephemeral | active |
| DOC-106 | `CADEN_v0.md` | repair layer cleans malformed JSON but still fails loudly on real omissions | active |
| DOC-107 | `CADEN_v0.md` | one sqlite+sqlite-vec DB stores events, memories, ratings, predictions, residuals, tasks | active |
| DOC-108 | `CADEN_v0.md` | scheduling owned by CADEN, but only CADEN-created blocks are movable | active |
| DOC-109 | `CADEN_v0.md` | post-v0 scope includes deferred schema growth, phase change, and active optimization | planned |

## Behavioral Traceability Crosswalk

Behavioral claims in this supplemental register are required to have a test
path in `CADEN_testMatrix.md`:

- `active` rows must map to existing automated test evidence now
- `planned` rows must map to a future test/eval placeholder row
- non-behavioral rows (`process_only`, `open_question`, `historical`) are
  explicitly excluded from proof requirements

| DOC ID | Test Path |
| --- | --- |
| DOC-001 | `V0-116` |
| DOC-002 | `V0-234` |
| DOC-003 | `CMD-025` |
| DOC-004 | `CMD-028`, `CMD-031` |
| DOC-005 | `CMD-033` to `CMD-046` |
| DOC-006 | `CMD-017`, `CMD-037`, `V0-190` |
| DOC-007 | `CMD-034` to `CMD-041` |
| DOC-008 | `CMD-042`, `V0-191` |
| DOC-009 | `V0-087`, `V0-246` |
| DOC-011 to DOC-024 | `SUP-DASH-001` to `SUP-DASH-014` |
| DOC-034 to DOC-046 | `SUP-LEARN-001` to `SUP-LEARN-013` |
| DOC-047 | `CMD-050` |
| DOC-048 | `V0-045`, `V0-046` |
| DOC-049 | `V0-052` |
| DOC-050 | `CMD-055` |
| DOC-051 | `V0-153` to `V0-156` |
| DOC-052 | `SUP-LIBBIE-001` |
| DOC-053 | `V0-018`, `V0-020` |
| DOC-054 | `CMD-052` |
| DOC-055 | `SUP-LIBBIE-002` |
| DOC-056 | `V0-028`, `V0-031` |
| DOC-056a | `V0-052` |
| DOC-056b | `V0-083` |
| DOC-057 to DOC-066a | `SUP-PM-001` to `SUP-PM-011` |
| DOC-067 to DOC-081a | `SUP-SPR-001` to `SUP-SPR-016` |
| DOC-082 to DOC-091c | `SUP-TD-001` to `SUP-TD-013` |
| DOC-092 to DOC-099 | `CMD-003` to `CMD-071` |
| DOC-100 to DOC-109 | `V0-028` to `V0-260` |

## Suggested Promotion Workflow

1. pick a row in this file
2. decide whether it is now authoritative
3. if yes, add authoritative row(s) into `CADEN_testMatrix.md` with status and
   evidence/gap
4. optionally mark the originating `DOC-*` row as promoted in a future revision
