# CADEN Exhaustive Spec Traceability Matrix

This file is the exhaustive traceability matrix for the current authoritative
spec surface.

Authoritative sources covered here:
- `CADEN.md`
- `CADEN_v0.md`

Non-authoritative sections that are intentionally **not** treated as testable
requirements are still listed below so the matrix remains exhaustive about what
it includes and excludes.

## Status Legend

- `covered`: direct automated verification exists now
- `partial`: some verification exists, but the clause is not fully pinned down
- `uncovered`: no direct verification exists yet
- `eval`: requires a replay/eval harness rather than ordinary pytest
- `manual`: product identity, environment fact, or other clause not reducible
  to trustworthy automated verification in the current repo
- `future`: authoritative requirement for a future or not-yet-implemented area
- `duplicate`: clause restates an earlier authoritative requirement; listed for
  completeness and traced back to the earlier row
- `excluded`: explicitly non-authoritative history / open-question material

## Verification Modes

- `pytest`: ordinary automated tests in `tests/`
- `eval-harness`: replay or longitudinal measurement harness needed
- `manual-review`: human review, environment inspection, or release gate
- `none-yet`: no verification artifact exists yet

## Excluded Non-Authoritative Sections

| ID | Source | Section | Reason | Status |
| --- | --- | --- | --- | --- |
| EX-001 | `CADEN_v0.md` | `Reset Note` | Explicitly says the section preserves rejected ideas as history only | excluded |
| EX-002 | `CADEN_v0.md` | `Rejected Bootstrap Draft (history only)` | Explicitly says fixed bootstrap thresholds are not authoritative behavior | excluded |
| EX-003 | `CADEN_v0.md` | `Open Questions` | Explicitly unresolved, not pre-decided requirements | excluded |
| EX-004 | `CADEN_v0.md` | `Deprecated Sections (history only, do not build from these)` | Explicitly retired design, not current spec | excluded |
| EX-005 | `CADEN_v0.md` | `Scratchpad` | Scratch text, not a requirement section | excluded |

## Supplemental Claims Register

Additional claims from the broader CADEN documentation set are tracked in
`CADEN_docClaimsMatrix.md`.

That file is intentionally non-authoritative by default and acts as a staging
backlog. Claims should only be promoted into this authoritative matrix when the
source requirement is explicitly locked as in-scope behavior.

## CADEN.md Product, Principles, and Architecture

| ID | Source | Requirement | Mode | Status | Evidence / Gap |
| --- | --- | --- | --- | --- | --- |
| CMD-001 | `CADEN.md` | CADEN is Sean Kellogg's life assistant | manual-review | manual | Product identity, not executable behavior |
| CMD-002 | `CADEN.md` | CADEN can be thought of as an executive function prosthesis | manual-review | manual | Product framing, not executable behavior |
| CMD-003 | `CADEN.md` | CADEN is not bespoke to Sean's diagnoses | eval-harness | eval | Needs longitudinal evidence that behavior is learned, not hand-coded to diagnoses |
| CMD-004 | `CADEN.md` | CADEN learns what works for Sean through deterministic statistics math | eval-harness | eval | Needs learning/replay harness |
| CMD-005 | `CADEN.md` | CADEN tracks Sean's behavior over time | pytest | covered | `tests/test_contract_metadata.py::test_recent_events_retains_a_queryable_trace_of_sean_behavior_over_time` |
| CMD-006 | `CADEN.md` | CADEN learns how to predict Sean as he changes through phases of life | eval-harness | eval | No longitudinal harness yet |
| CMD-007 | `CADEN.md` | CADEN balances mood, energy, and productivity | eval-harness | eval | Objective exists in spec, but no objective-quality eval yet |
| CMD-008 | `CADEN.md` | CADEN tracks mood | pytest | covered | `tests/test_m6_rater.py::test_m6_rater` |
| CMD-009 | `CADEN.md` | CADEN tracks energy | pytest | covered | `tests/test_m6_rater.py::test_m6_rater` |
| CMD-010 | `CADEN.md` | CADEN tracks productivity | pytest | covered | `tests/test_m6_rater.py::test_m6_rater` |
| CMD-011 | `CADEN.md` | CADEN maximizes each axis without tanking the other two | eval-harness | eval | Requires optimization/eval machinery, not just unit tests |
| CMD-012 | `CADEN.md` | CADEN uses an LLM for reasoning | pytest | covered | `tests/test_contract_chat.py::test_cmd_012_chat_reasoning_invokes_llm_chat_stream` |
| CMD-013 | `CADEN.md` | Deterministic framework guides and guards the LLM | pytest | covered | `tests/test_contract_schedule.py::test_scheduler_routes_raw_llm_output_through_shared_repair_layer` and `tests/test_contract_predict.py::test_prediction_routes_raw_llm_output_through_shared_repair_layer` |
| CMD-014 | `CADEN.md` | Documentation and reliability come first | manual-review | manual | Process requirement, not code behavior |
| CMD-015 | `CADEN.md` | No hand-written heuristics are allowed | eval-harness | eval | Needs design review plus negative coverage against bespoke rules |
| CMD-016 | `CADEN.md` | Generic operational policies may exist if they are not claims about Sean | pytest | covered | `tests/test_contract_no_heuristics.py::test_cmd_016_generic_operational_policy_helpers_are_sean_agnostic` |
| CMD-017 | `CADEN.md` | Dashboard day rolls over at 5 AM local time | pytest | covered | `tests/test_m3_google_read.py::test_dashboard_day_window_uses_5am_local_boundary` |
| CMD-018 | `CADEN.md` | Retrieval penalizes overly long memories so concise memories surface first | pytest | covered | `tests/test_contract_retrieve.py::test_retrieval_prefers_shorter_memories_when_similarity_ties` |
| CMD-019 | `CADEN.md` | CADEN is modular | manual-review | manual | Architectural quality, not directly testable as a clause |
| CMD-020 | `CADEN.md` | CADEN is simple | manual-review | manual | Architectural quality, not directly testable as a clause |
| CMD-021 | `CADEN.md` | Python is used for everything | pytest | covered | `tests/test_contract_no_heuristics.py::test_cmd_021_runtime_codebase_avoids_non_python_language_sources` |
| CMD-022 | `CADEN.md` | There are no silent fallbacks | pytest | covered | `tests/test_contract_no_swallow.py::test_cmd_022_023_silent_default_exception_fallbacks_are_explicitly_allowlisted` plus loud-failure tests in add-task/edit-task/poll contracts |
| CMD-023 | `CADEN.md` | Failures must be loud with no fallback | pytest | covered | `tests/test_contract_no_swallow.py::test_cmd_022_023_silent_default_exception_fallbacks_are_explicitly_allowlisted` plus loud-failure tests in add-task/edit-task/poll contracts |
| CMD-024 | `CADEN.md` | Ollama is used for the LLM | pytest | covered | `tests/test_contract_boot.py::test_boot_runs_prerequisites_in_documented_order_and_allows_chat_only_without_google` |
| CMD-025 | `CADEN.md` | Model is chosen in CADEN settings | pytest | covered | `tests/test_contract_config.py::test_config_uses_documented_settings_and_data_paths` |
| CMD-026 | `CADEN.md` | Intended LLM size is roughly 7b-10b | manual-review | manual | Deployment preference, not runtime behavior |
| CMD-027 | `CADEN.md` | Model scope stays small and many calls may be made | manual-review | manual | Design guidance, not a crisp testable invariant |

## CADEN.md Core GUI Architecture

| ID | Source | Requirement | Mode | Status | Evidence / Gap |
| --- | --- | --- | --- | --- | --- |
| CMD-028 | `CADEN.md` | Entire GUI is a unified `TabbedContent` container | pytest | covered | `tests/test_contract_gui.py::test_app_uses_tabbed_root_architecture` |
| CMD-029 | `CADEN.md` | Everything Sean interacts with is an app built as a `TabPane` | pytest | covered | `tests/test_contract_gui.py::test_app_uses_tabbed_root_architecture` |
| CMD-030 | `CADEN.md` | `caden/ui/app.py` is the root container | manual-review | manual | Repo structure fact |
| CMD-031 | `CADEN.md` | v0 logic acts as the default Dashboard tab | pytest | covered | `tests/test_contract_chat.py::test_v0_exposes_only_one_dashboard_chat_surface` and `tests/test_contract_gui.py::test_app_uses_tabbed_root_architecture` |
| CMD-032 | `CADEN.md` | Future apps register as sibling tabs with the same layout | pytest | covered | `tests/test_contract_sprocket.py::test_cmd_066_sprocket_left_nav_can_select_or_create_app_and_register_tab` |

## CADEN.md Dashboard Requirements

| ID | Source | Requirement | Mode | Status | Evidence / Gap |
| --- | --- | --- | --- | --- | --- |
| CMD-033 | `CADEN.md` | Dashboard is the first/default `TabPane` | pytest | covered | `tests/test_contract_chat.py::test_v0_exposes_only_one_dashboard_chat_surface` |
| CMD-034 | `CADEN.md` | Left panel shows current circadian day's calendar items | pytest | covered | `tests/test_m3_google_read.py::test_dashboard_today_panel_mixes_labeled_tasks_and_events_in_chronological_order` |
| CMD-035 | `CADEN.md` | Left panel shows current circadian day's Google tasks | pytest | covered | `tests/test_m3_google_read.py::test_dashboard_today_panel_mixes_labeled_tasks_and_events_in_chronological_order` |
| CMD-036 | `CADEN.md` | Left panel includes CADEN-scheduled work | pytest | covered | `tests/test_m3_google_read.py::test_dashboard_today_panel_includes_linked_caden_scheduled_work_without_duplicate_task_row` |
| CMD-037 | `CADEN.md` | Dashboard day runs 5 AM local to next 5 AM local | pytest | covered | `tests/test_m3_google_read.py::test_dashboard_day_window_uses_5am_local_boundary` |
| CMD-038 | `CADEN.md` | Events are shown ordered by start time | pytest | covered | `tests/test_m3_google_read.py::test_dashboard_today_panel_mixes_labeled_tasks_and_events_in_chronological_order` |
| CMD-039 | `CADEN.md` | Tasks are shown ordered by due date/time | pytest | covered | Same mixed-order dashboard test covers due-time placement between surrounding events |
| CMD-040 | `CADEN.md` | Types are mixed but labeled | pytest | covered | `tests/test_m3_google_read.py::test_dashboard_today_panel_mixes_labeled_tasks_and_events_in_chronological_order` |
| CMD-041 | `CADEN.md` | Chronological ordering is more important than type grouping | pytest | covered | `tests/test_m3_google_read.py::test_dashboard_today_panel_mixes_labeled_tasks_and_events_in_chronological_order` |
| CMD-042 | `CADEN.md` | Right panel shows next 7 days | pytest | covered | `tests/test_m3_google_read.py::test_dashboard_next_7_days_panel_includes_future_events_and_tasks` |
| CMD-043 | `CADEN.md` | CADEN may schedule task blocks any time before due date | pytest | covered | `tests/test_contract_schedule.py::test_scheduler_derives_duration_from_end_minus_start_and_allows_slot_up_to_deadline` |
| CMD-044 | `CADEN.md` | CADEN does not move calendar events it did not create | pytest | covered | `tests/test_contract_schedule.py::test_scheduler_rejects_moving_external_events` and `tests/test_contract_schedule.py::test_scheduler_rejects_overlapping_external_events` |
| CMD-045 | `CADEN.md` | 7-day view includes future CADEN-scheduled work and pre-existing calendar/task items | pytest | covered | `tests/test_m3_google_read.py::test_dashboard_next_7_days_panel_includes_future_events_and_tasks` |
| CMD-046 | `CADEN.md` | Middle panel is a CLI-like chat interface | pytest | covered | `tests/test_contract_chat.py::test_task_like_chat_message_does_not_create_tasks_or_schedule_work` |
| CMD-047 | `CADEN.md` | All chats are embedded by Libbie into the central vector DB | pytest | covered | `tests/test_contract_chat.py::test_cmd_047_chat_persists_both_sean_and_caden_messages_to_libbie` |

## CADEN.md Libbie Requirements

| ID | Source | Requirement | Mode | Status | Evidence / Gap |
| --- | --- | --- | --- | --- | --- |
| CMD-048 | `CADEN.md` | Libbie is CADEN's memory layer | manual-review | manual | Naming/role requirement |
| CMD-049 | `CADEN.md` | Libbie resurfaces memories when CADEN needs them | pytest | covered | `tests/test_contract_supplemental_claims.py::test_sup_dash_004_chat_exposes_recalled_memories_strip` and `tests/test_contract_libbie_api.py::test_libbie_surface_returns_proactive_recall_packets` |
| CMD-050 | `CADEN.md` | Libbie manages one vector sqlite DB for everything | pytest | covered | `tests/test_contract_db.py::test_single_central_sqlite_db_hosts_raw_curated_structured_and_vector_tables`, `tests/test_contract_db.py::test_connect_verifies_sqlite_vec_is_loaded`, and `tests/test_contract_db.py::test_apply_schema_creates_documented_vector_tables_and_pins_embed_dim` |
| CMD-051 | `CADEN.md` | Memory must not be fragmented across storage | pytest | covered | `tests/test_contract_db.py::test_single_central_sqlite_db_hosts_raw_curated_structured_and_vector_tables` |
| CMD-052 | `CADEN.md` | Libbie also serves Project Manager | pytest | covered | `tests/test_contract_project_manager.py::test_project_manager_entries_persist_in_libbie_event_pipeline` and `tests/test_contract_project_manager.py::test_project_manager_todo_creates_google_task_and_links_metadata` |
| CMD-053 | `CADEN.md` | Sean never talks to Libbie directly | manual-review | manual | UX/product rule |
| CMD-054 | `CADEN.md` | Libbie uses a SearXNG docker container | pytest | covered | `tests/test_contract_boot.py::test_cmd_054_boot_wires_searxng_client_when_configured` |
| CMD-055 | `CADEN.md` | Publicly available answers should be answerable through chat and saved for later | pytest | covered | `tests/test_contract_chat.py::test_cmd_055_chat_can_capture_web_knowledge_for_later_reuse` and `tests/test_contract_libbie_api.py::test_libbie_search_web_captures_results_as_memory_events` |
| CMD-056 | `CADEN.md` | Libbie stores metadata about when and why something was researched/found | pytest | covered | `tests/test_contract_libbie_api.py::test_libbie_search_web_captures_results_as_memory_events` plus `tests/test_contract_metadata.py::test_append_event_metadata_records_multiple_keys_without_overwriting_prior_rows` |

## CADEN.md Future App Requirements

| ID | Source | Requirement | Mode | Status | Evidence / Gap |
| --- | --- | --- | --- | --- | --- |
| CMD-057 | `CADEN.md` | Project Manager is a registered `TabPane` | pytest | covered | `tests/test_contract_chat.py::test_app_exposes_dashboard_project_manager_and_sprocket_tabs` |
| CMD-058 | `CADEN.md` | Project Manager has narrow left navigation listing projects | pytest | covered | `tests/test_contract_project_manager.py::test_cmd_058_project_manager_left_nav_is_narrower_than_main_area` |
| CMD-059 | `CADEN.md` | Project Manager main area shows selected project | pytest | covered | `tests/test_contract_project_manager.py::test_project_manager_pane_opens_project_and_saves_entry` |
| CMD-060 | `CADEN.md` | PM entry buttons are TODO / what-if / update / comment | pytest | covered | `tests/test_contract_project_manager.py::test_project_manager_pane_exposes_entry_type_buttons_and_project_list` and `tests/test_contract_project_manager.py::test_project_manager_todo_creates_google_task_and_links_metadata` |
| CMD-061 | `CADEN.md` | PM submit on enter embeds entry into DB | pytest | covered | `tests/test_contract_project_manager.py::test_project_manager_entries_persist_in_libbie_event_pipeline` and `tests/test_contract_project_manager.py::test_project_manager_pane_opens_project_and_saves_entry` |
| CMD-062 | `CADEN.md` | Thought Dump is a registered `TabPane` | pytest | covered | `tests/test_contract_chat.py::test_app_exposes_dashboard_project_manager_sprocket_and_thought_dump_tabs` |
| CMD-063 | `CADEN.md` | Thought Dump stores all thoughts in the central vector DB | pytest | covered | `tests/test_contract_supplemental_claims.py::test_sup_td_003_and_004_capture_only_on_explicit_commit_one_commit_one_event` |
| CMD-064 | `CADEN.md` | Thought Dump has a hide button that ciphers text on that app only | pytest | covered | `tests/test_contract_supplemental_claims.py::test_sup_td_006_007_011_hide_mode_is_visual_only_tab_local_and_resets` |
| CMD-065 | `CADEN.md` | Sprocket is a vibecoding chat interface | pytest | covered | `tests/test_contract_sprocket.py::test_sprocket_pane_exposes_chat_input_and_generate_action` and `tests/test_contract_supplemental_claims.py::test_sup_spr_002_sprocket_history_scope_is_separate_from_dashboard_chat` |
| CMD-066 | `CADEN.md` | Sprocket selects or creates apps from narrow left navigation | pytest | covered | `tests/test_contract_sprocket.py::test_cmd_066_sprocket_left_nav_can_select_or_create_app_and_register_tab` |
| CMD-067 | `CADEN.md` | Libbie figures out how to do what Sean asks and passes it to Sprocket | pytest | covered | `tests/test_contract_sprocket.py::test_sprocket_build_brief_uses_libbie_recall_pipeline` |
| CMD-068 | `CADEN.md` | Sprocket makes a plan and executes it | pytest | covered | `tests/test_contract_supplemental_claims.py::test_sup_spr_019_sprocket_can_plan_and_execute_with_logged_outcome` |
| CMD-069 | `CADEN.md` | Sprocket learns from failure | pytest | covered | `tests/test_contract_sprocket.py::test_cmd_069_sprocket_learns_from_failure_and_changes_prompting_strategy` |
| CMD-070 | `CADEN.md` | Every thought emitted by Sprocket is vector searched and related situations are resurfaced | pytest | covered | `tests/test_contract_sprocket.py::test_cmd_070_sprocket_vector_searches_each_emitted_thought_and_resurfaces_related_context` |
| CMD-071 | `CADEN.md` | Sprocket slips summaries of intent/implementation/outcome into the system prompt | pytest | covered | `tests/test_contract_sprocket.py::test_cmd_071_system_prompt_includes_recent_intent_implementation_outcome_summaries` |

## CADEN_v0 Locked Constraints and Objective

| ID | Source | Requirement | Mode | Status | Evidence / Gap |
| --- | --- | --- | --- | --- | --- |
| V0-001 | `CADEN_v0.md` | CADEN is local-first and privacy-first | duplicate | duplicate | Restates top-level product direction from `CADEN.md` |
| V0-002 | `CADEN_v0.md` | CADEN is Python-only | duplicate | duplicate | Restates `CMD-021` |
| V0-003 | `CADEN_v0.md` | CADEN is deterministic framework plus local LLM, not either alone | duplicate | duplicate | Restates `CMD-012` and `CMD-013` |
| V0-004 | `CADEN_v0.md` | Failures are loud and diagnosable, not silent | duplicate | duplicate | Restates `CMD-022` and `CMD-023` |
| V0-005 | `CADEN_v0.md` | One central vector-capable sqlite memory store is managed by Libbie | duplicate | duplicate | Restates `CMD-050` |
| V0-006 | `CADEN_v0.md` | CADEN must keep learning as Sean changes | duplicate | duplicate | Restates `CMD-006` |
| V0-007 | `CADEN_v0.md` | No hand-written heuristics; improve mechanisms not rules | duplicate | duplicate | Restates `CMD-015` |
| V0-008 | `CADEN_v0.md` | Fixed limits that bypass LLM decision-making are forbidden in v0 | pytest | covered | `tests/test_contract_schedule.py::test_scheduler_handles_large_calendar_windows_without_fixed_event_cap`, `tests/test_contract_schedule.py::test_scheduler_prompt_keeps_full_description_and_preferences_without_char_cap`, `tests/test_m6_rater.py::test_rater_prompt_keeps_full_focal_event_without_char_cap`, `tests/test_contract_predict.py::test_prediction_prompt_keeps_full_description_without_char_cap`, `tests/test_contract_curate.py::test_package_chat_context_does_not_hardcode_fixed_retrieval_k`, and `tests/test_contract_retrieve.py::test_recall_defaults_to_all_matching_memories_when_k_is_omitted` |
| V0-009 | `CADEN_v0.md` | Cold-start thinness is preferable to hard-coded pollution | pytest | covered | `tests/test_m6_rater.py::test_rater_starts_unknown_then_later_events_can_retrieve_observations`, plus no-fixed-cap prompt/retrieval contract tests |
| V0-010 | `CADEN_v0.md` | Objective is mood / energy / productivity balance | duplicate | duplicate | Restates `CMD-007` through `CMD-011` |
| V0-011 | `CADEN_v0.md` | CADEN has no hand-written axis feature lists | pytest | covered | `tests/test_contract_no_heuristics.py::test_runtime_code_avoids_deprecated_hand_written_psychology_features` |
| V0-012 | `CADEN_v0.md` | Each axis is a scalar learned from the event stream | pytest | covered | `tests/test_m6_rater.py::test_m6_rater` and `tests/test_m6_rater.py::test_rater_starts_unknown_then_later_events_can_retrieve_observations` |
| V0-013 | `CADEN_v0.md` | Estimators start at "I don't know" and earn predictions from observations | pytest | covered | `tests/test_m6_rater.py::test_rater_starts_unknown_then_later_events_can_retrieve_observations` |
| V0-014 | `CADEN_v0.md` | A move is good only if it improves one axis without tanking the others | manual-review | manual | Objective-quality release criterion; requires longitudinal product evaluation rather than a unit-test oracle |

## CADEN_v0 Rating and Self-Correction

| ID | Source | Requirement | Mode | Status | Evidence / Gap |
| --- | --- | --- | --- | --- | --- |
| V0-015 | `CADEN_v0.md` | LLM rates every incoming event on mood / energy / productivity | pytest | covered | `tests/test_m6_rater.py::test_rater_rates_each_documented_non_structural_event_source_with_libbie_retrieval` and `tests/test_m6_rater.py::test_rater_skips_only_documented_structural_event_sources` |
| V0-016 | `CADEN_v0.md` | Rating prompt includes the event itself | pytest | covered | `tests/test_m6_rater.py::test_rater_prompt_includes_focal_event_self_knowledge_and_prior_ratings` |
| V0-017 | `CADEN_v0.md` | Rating prompt includes relevant past events and ratings from Libbie | pytest | covered | `tests/test_m6_rater.py::test_rater_prompt_includes_focal_event_self_knowledge_and_prior_ratings` |
| V0-018 | `CADEN_v0.md` | Rating prompt includes relevant self-knowledge from Sean via normal retrieval | pytest | covered | `tests/test_m6_rater.py::test_rater_prompt_includes_focal_event_self_knowledge_and_prior_ratings` |
| V0-019 | `CADEN_v0.md` | Rating improves through better retrieval, not rules | pytest | covered | `tests/test_m6_rater.py::test_rating_rationale_feeds_future_retrieval_for_later_events` and `tests/test_m6_rater.py::test_rater_prompt_includes_focal_event_self_knowledge_and_prior_ratings` |
| V0-020 | `CADEN_v0.md` | Sean's self-knowledge statements become first-class memories | pytest | covered | `tests/test_m6_rater.py::test_rater_prompt_includes_focal_event_self_knowledge_and_prior_ratings` |
| V0-021 | `CADEN_v0.md` | Rating output is three numbers plus a short rationale | pytest | covered | `tests/test_m6_rater.py::test_m6_rater` |
| V0-022 | `CADEN_v0.md` | Rating rationale is stored for future retrieval | pytest | covered | `tests/test_m6_rater.py::test_rating_rationale_feeds_future_retrieval_for_later_events` |
| V0-023 | `CADEN_v0.md` | Old ratings are immutable | pytest | covered | `tests/test_contract_metadata.py::test_write_rating_never_updates_or_deletes_existing_rating_rows` |
| V0-024 | `CADEN_v0.md` | CADEN never back-fills or overwrites historical ratings | pytest | covered | `tests/test_contract_metadata.py::test_write_rating_appends_new_rows_without_overwriting_historical_ratings` |
| V0-025 | `CADEN_v0.md` | Rater quality is primarily measured by observed residuals | pytest | covered | `tests/test_contract_learning.py::test_aggregate_residuals_by_mechanism_produces_residual_quality_frame` |
| V0-026 | `CADEN_v0.md` | Optional short-window stability check is diagnostic only and never stored | pytest | covered | `tests/test_m6_rater.py::test_rater_optional_stability_check_is_diagnostic_only_and_non_persistent` and `tests/test_m6_rater.py::test_rater_optional_stability_check_failure_is_best_effort` |
| V0-027 | `CADEN_v0.md` | Rater fixes come from surfacing more self-knowledge or mechanism improvements, not rewriting history | pytest | covered | `tests/test_m6_rater.py::test_rater_prompt_includes_focal_event_self_knowledge_and_prior_ratings`, `tests/test_contract_metadata.py::test_write_rating_never_updates_or_deletes_existing_rating_rows`, and `tests/test_contract_metadata.py::test_write_rating_appends_new_rows_without_overwriting_historical_ratings` |

## CADEN_v0 Predict / Observe / Correct Mechanism

| ID | Source | Requirement | Mode | Status | Evidence / Gap |
| --- | --- | --- | --- | --- | --- |
| V0-028 | `CADEN_v0.md` | CADEN's central mechanism is Predict, Observe, Correct | pytest | covered | `tests/test_contract_predict.py::test_predict_observe_correct_loop_links_prediction_to_residual_memory` plus existing predict/observe slice tests |
| V0-029 | `CADEN_v0.md` | Predict step produces a response/action and projected short-horizon trajectory | pytest | covered | `tests/test_contract_predict.py::test_emit_prediction_persists_projected_short_horizon_trajectory` |
| V0-030 | `CADEN_v0.md` | Observe step uses subsequent events as ground truth | pytest | covered | `tests/test_contract_predict.py::test_observe_step_uses_subsequent_events_as_ground_truth_against_prediction_bundle` |
| V0-031 | `CADEN_v0.md` | Correct step uses residuals to adjust retrieval weights / estimators / schema / decay | pytest | covered | `tests/test_contract_learning.py::test_derive_retrieval_weights_moves_weight_toward_lower_residual_mechanisms` plus residual aggregation contracts |
| V0-032 | `CADEN_v0.md` | Predictions are emitted when CADEN schedules a task | pytest | covered | `tests/test_m4_addtask.py::test_m4_addtask` |
| V0-033 | `CADEN_v0.md` | Every task is paired with a Google Calendar event created by CADEN | pytest | covered | `tests/test_m4_addtask.py::test_m4_addtask` and `tests/test_m4_addtask.py::test_add_task_requires_google_write_clients_before_storing_anything` |
| V0-034 | `CADEN_v0.md` | Prediction bundle includes duration | pytest | covered | `tests/test_m4_addtask.py::test_m4_addtask_creates_a_single_scheduled_block` |
| V0-035 | `CADEN_v0.md` | Prediction bundle includes pre-state values | pytest | covered | `tests/test_m4_addtask.py::test_m4_addtask` and `tests/test_contract_metadata.py::test_write_prediction_persists_rationale_and_confidence_fields` |
| V0-036 | `CADEN_v0.md` | Prediction bundle includes post-state values | pytest | covered | `tests/test_m4_addtask.py::test_m4_addtask` and `tests/test_contract_metadata.py::test_write_prediction_persists_rationale_and_confidence_fields` |
| V0-037 | `CADEN_v0.md` | Prediction bundle includes confidence values | pytest | covered | `tests/test_m4_addtask.py::test_m4_addtask` and `tests/test_contract_metadata.py::test_write_prediction_persists_rationale_and_confidence_fields` |
| V0-038 | `CADEN_v0.md` | Prediction bundle is stored as memory like any other event | pytest | covered | `tests/test_contract_metadata.py::test_write_prediction_persists_rationale_and_confidence_fields` |
| V0-039 | `CADEN_v0.md` | No separate prediction table in v0 | manual-review | manual | Superseded by later implementation contracts that do define a predictions table |
| V0-040 | `CADEN_v0.md` | On completion, paired event end time is edited to completion time | pytest | covered | `tests/test_m5_completion.py::test_m5_normal_completion_truncates_google_event_and_fills_state_residuals` |
| V0-041 | `CADEN_v0.md` | Completion frees the rest of the block | pytest | covered | `tests/test_m5_completion.py::test_m5_normal_completion_truncates_google_event_and_fills_state_residuals` |
| V0-042 | `CADEN_v0.md` | State residuals compare observed ratings near the task window to predicted state | pytest | covered | `tests/test_m5_completion.py::test_m5_normal_completion_truncates_google_event_and_fills_state_residuals` |
| V0-043 | `CADEN_v0.md` | There are three state residuals plus one duration residual per prediction | pytest | covered | `tests/test_m5_completion.py::test_m5_normal_completion_truncates_google_event_and_fills_state_residuals` |
| V0-044 | `CADEN_v0.md` | Residuals are stored as memories of their own | pytest | covered | `tests/test_contract_metadata.py::test_write_residual_creates_curated_memory_from_structured_row` |

## CADEN_v0 Memory Model, Retrieval, and Phase Change

| ID | Source | Requirement | Mode | Status | Evidence / Gap |
| --- | --- | --- | --- | --- | --- |
| V0-045 | `CADEN_v0.md` | Raw `events` are immutable capture log | pytest | covered | `tests/test_contract_metadata.py::test_write_event_keeps_raw_events_append_only_at_the_sql_boundary` |
| V0-046 | `CADEN_v0.md` | Curated `memories` are reasoning units surfaced back to CADEN | pytest | covered | `tests/test_contract_retrieve.py::test_ligand_is_not_part_of_the_public_caden_facing_context_object` and `tests/test_contract_retrieve.py::test_recall_packets_are_the_compact_caden_facing_payload` |
| V0-047 | `CADEN_v0.md` | Events are for audit/replay/provenance retrieval | pytest | covered | `tests/test_contract_metadata.py::test_raw_events_can_be_replayed_with_provenance_and_memory_linkage` and `tests/test_contract_metadata.py::test_write_event_keeps_raw_events_append_only_at_the_sql_boundary` |
| V0-048 | `CADEN_v0.md` | Memories are curated recall units derived from events/structured rows | pytest | covered | `tests/test_contract_metadata.py::test_memory_frame_contract_preserves_required_invariants` and `tests/test_contract_metadata.py::test_write_residual_creates_curated_memory_from_structured_row` |
| V0-049 | `CADEN_v0.md` | CADEN-facing retrieval returns compact recall packets, not raw event text | pytest | covered | `tests/test_contract_curate.py::test_package_chat_context_uses_compact_recall_packets_instead_of_raw_event_dump` |
| V0-050 | `CADEN_v0.md` | Memory frame fields `type/domain/tags/context/outcome/hooks/embedding_text` are required | pytest | covered | `tests/test_contract_metadata.py::test_memory_frame_contract_preserves_required_invariants` |
| V0-051 | `CADEN_v0.md` | Recall packet is the compact CADEN-facing retrieval payload | pytest | covered | `tests/test_contract_retrieve.py::test_recall_packets_are_the_compact_caden_facing_payload` |
| V0-052 | `CADEN_v0.md` | Ligand is retrieval steering state and is not persisted as memory | pytest | covered | `tests/test_contract_retrieve.py::test_ligand_is_transient_and_not_persisted_as_memory` |
| V0-053 | `CADEN_v0.md` | Raw-to-memory canonicalization boundary is fixed even if exact string shaping is not | pytest | covered | `tests/test_contract_retrieve.py::test_write_event_captures_raw_event_before_canonical_memory_row` and `tests/test_contract_metadata.py::test_memory_embedding_text_is_built_from_meaning_bearing_frame_content` |
| V0-054 | `CADEN_v0.md` | `embedding_text` is built from meaning-bearing frame content, not raw storage alone | pytest | covered | `tests/test_contract_metadata.py::test_memory_embedding_text_is_built_from_meaning_bearing_frame_content` |
| V0-055 | `CADEN_v0.md` | No hand-written psychology taxonomies / primitives / cases / derived signals are licensed by the memory split | pytest | covered | `tests/test_contract_no_heuristics.py::test_runtime_code_avoids_deprecated_hand_written_psychology_features` |
| V0-056 | `CADEN_v0.md` | Schema growth is triggered by persistent high residuals, not designer guesses | future | covered | Schema growth is explicitly out of scope for v0 (`V0-258`) |
| V0-057 | `CADEN_v0.md` | The LLM proposes schema additions and residual math decides | future | covered | Schema growth is explicitly out of scope for v0 (`V0-258`) |
| V0-058 | `CADEN_v0.md` | Old records are only backfilled when cheap | future | covered | Schema growth is explicitly out of scope for v0 (`V0-258`) |
| V0-059 | `CADEN_v0.md` | Schema additions are logged loudly | future | covered | Schema growth is explicitly out of scope for v0 (`V0-258`) |
| V0-060 | `CADEN_v0.md` | Retrieval is not a raw nearest-neighbor dump from the event log | pytest | covered | `tests/test_contract_retrieve.py::test_retrieval_queries_curated_memory_vectors_not_raw_event_vectors` |
| V0-061 | `CADEN_v0.md` | Raw events are captured first, then canonicalized into memories | pytest | covered | `tests/test_contract_retrieve.py::test_write_event_captures_raw_event_before_canonical_memory_row` |
| V0-062 | `CADEN_v0.md` | Vector search runs over curated memories | pytest | covered | `tests/test_contract_retrieve.py::test_retrieval_queries_curated_memory_vectors_not_raw_event_vectors` |
| V0-063 | `CADEN_v0.md` | Libbie packages top recalled memories into compact context | pytest | covered | `tests/test_contract_curate.py::test_package_chat_context_centralizes_thread_memory_and_live_world` and `tests/test_contract_curate.py::test_package_chat_context_uses_compact_recall_packets_instead_of_raw_event_dump` |
| V0-064 | `CADEN_v0.md` | Retrieval weights should eventually move from residuals | pytest | covered | `tests/test_contract_learning.py::test_derive_retrieval_weights_moves_weight_toward_lower_residual_mechanisms` |
| V0-065 | `CADEN_v0.md` | Length penalty favors concise memories when otherwise similar | pytest | covered | `tests/test_contract_retrieve.py::test_retrieval_prefers_shorter_memories_when_similarity_ties` |
| V0-066 | `CADEN_v0.md` | Old evidence decays when residuals involving it rise | future | covered | Phase-change/decay tuning is explicitly out of scope for v0 (`V0-259`) |
| V0-067 | `CADEN_v0.md` | Phase change is detected from failing predictions grounded in old data | future | covered | Phase-change/decay tuning is explicitly out of scope for v0 (`V0-259`) |

## CADEN_v0 Failure Modes, Scope, and Continuity

| ID | Source | Requirement | Mode | Status | Evidence / Gap |
| --- | --- | --- | --- | --- | --- |
| V0-068 | `CADEN_v0.md` | Malformed LLM output kills the process loudly | pytest | covered | `tests/test_m6_rater.py::test_rater_fails_loudly_on_unrecoverable_malformed_llm_output` and `tests/test_contract_repair.py::test_repair_fails_loudly_when_required_content_is_missing` |
| V0-069 | `CADEN_v0.md` | Ollama unreachable fails loudly | pytest | covered | `tests/test_contract_boot.py::test_boot_fails_loudly_when_ollama_is_unreachable` |
| V0-070 | `CADEN_v0.md` | DB corruption or missing DB fails loudly | pytest | covered | `tests/test_contract_boot.py::test_boot_fails_loudly_when_db_or_schema_setup_fails` |
| V0-071 | `CADEN_v0.md` | Embedding model unavailable fails loudly | pytest | covered | `tests/test_contract_boot.py::test_boot_fails_loudly_when_embedding_model_is_unavailable` and `tests/test_m2_llm_roundtrip.py::test_embedder_dimension_mismatch_raises` |
| V0-072 | `CADEN_v0.md` | Learned parameter divergence fails loudly | pytest | covered | `tests/test_contract_learning.py::test_validate_learned_parameters_fails_loudly_on_non_finite_or_exploded_values` |
| V0-073 | `CADEN_v0.md` | Google Calendar / Tasks sync failure fails loudly | pytest | covered | `tests/test_contract_boot.py::test_boot_raises_loudly_when_google_credentials_exist_but_loading_fails`, `tests/test_contract_google_sync.py::test_calendar_list_and_create_fail_loudly_on_runtime_http_errors`, and `tests/test_contract_google_sync.py::test_tasks_create_list_get_and_patch_fail_loudly_on_runtime_http_errors` |
| V0-074 | `CADEN_v0.md` | v0 scope includes dashboard + chat + Libbie memory | pytest | covered | `tests/test_contract_chat.py::test_v0_scope_integrates_dashboard_chat_and_libbie_memory` plus `tests/test_contract_chat.py::test_v0_exposes_only_one_dashboard_chat_surface` |
| V0-075 | `CADEN_v0.md` | Sean chat inputs are stored; CADEN replies remain ephemeral | pytest | covered | `tests/test_m1_skeleton.py::test_m1_skeleton` |
| V0-076 | `CADEN_v0.md` | LLM responds using Libbie-packaged retrieved context rather than direct raw event dumps | pytest | covered | `tests/test_contract_curate.py::test_package_chat_context_uses_compact_recall_packets_instead_of_raw_event_dump` plus `tests/test_m2_llm_roundtrip.py::test_m2_llm_roundtrip` |
| V0-077 | `CADEN_v0.md` | Estimators exist from day one but output unknown until enough data exists | pytest | covered | `tests/test_m6_rater.py::test_rater_starts_unknown_then_later_events_can_retrieve_observations` |
| V0-078 | `CADEN_v0.md` | CADEN owns scheduling from task + deadline alone | pytest | covered | `tests/test_contract_chat.py::test_task_like_chat_message_does_not_create_tasks_or_schedule_work` and `tests/test_m4_addtask.py::test_m4_addtask` |
| V0-079 | `CADEN_v0.md` | CADEN may move only its own created task blocks | pytest | covered | `tests/test_contract_schedule.py::test_scheduler_rejects_moving_external_events` and `tests/test_contract_schedule.py::test_scheduler_rejects_overlapping_external_events` |
| V0-080 | `CADEN_v0.md` | Every task-event pair spawns a prediction bundle stored as memory | pytest | covered | `tests/test_m4_addtask.py::test_m4_addtask` |
| V0-081 | `CADEN_v0.md` | On task completion, paired event end is edited and residuals are stored | pytest | covered | `tests/test_m5_completion.py::test_m5_normal_completion_truncates_google_event_and_fills_state_residuals` |
| V0-082 | `CADEN_v0.md` | No hand-written features / primitives / cases / fingerprints / derived signals | pytest | covered | `tests/test_contract_no_heuristics.py::test_runtime_code_avoids_deprecated_hand_written_psychology_features` |
| V0-083 | `CADEN_v0.md` | Ligands are internal, not memory, not public CADEN-facing objects | pytest | covered | `tests/test_contract_retrieve.py::test_ligand_is_not_part_of_the_public_caden_facing_context_object` |
| V0-084 | `CADEN_v0.md` | v0 does not compare or optimize alternative schedules | pytest | covered | `tests/test_contract_schedule.py::test_scheduler_requests_and_returns_a_single_plan_not_alternative_options` |
| V0-085 | `CADEN_v0.md` | Cold start feels thin by design | manual-review | manual | Qualitative expectation |
| V0-086 | `CADEN_v0.md` | v0 interface becomes the future Dashboard tab in post-v0 GUI | duplicate | duplicate | Restates `CMD-031` and `CMD-032` |

## CADEN_v0 Scheduling Ownership and LLM Output Handling

| ID | Source | Requirement | Mode | Status | Evidence / Gap |
| --- | --- | --- | --- | --- | --- |
| V0-087 | `CADEN_v0.md` | Sean provides task description and deadline through explicit add-task form | pytest | covered | `tests/test_contract_chat.py::test_task_like_chat_message_does_not_create_tasks_or_schedule_work` and `tests/test_m4_addtask.py::test_m4_addtask` |
| V0-088 | `CADEN_v0.md` | CADEN decides when, duration, and calendar fit before due date | pytest | covered | `tests/test_contract_schedule.py::test_scheduler_prompt_includes_description_deadline_calendar_events_and_libbie_context` and `tests/test_contract_schedule.py::test_scheduler_derives_duration_from_end_minus_start_and_allows_slot_up_to_deadline` |
| V0-089 | `CADEN_v0.md` | CADEN may move only previously created task blocks | pytest | covered | `tests/test_contract_schedule.py::test_scheduler_rejects_moving_external_events` and `tests/test_contract_schedule.py::test_scheduler_rejects_overlapping_external_events` |
| V0-090 | `CADEN_v0.md` | CADEN writes Google Task and paired Google Calendar event via Google API | pytest | covered | `tests/test_m4_addtask.py::test_m4_addtask`, `tests/test_m4_addtask.py::test_m4_addtask_creates_a_single_scheduled_block`, and `tests/test_m4_addtask.py::test_add_task_requires_google_write_clients_before_storing_anything` |
| V0-091 | `CADEN_v0.md` | Task and paired event are linked in Libbie | pytest | covered | `tests/test_m4_addtask.py` and `tests/test_contract_metadata.py::test_task_event_rows_are_mirrored_into_events` |
| V0-092 | `CADEN_v0.md` | Button surface avoids casual-chat task misinterpretation | pytest | covered | `tests/test_contract_chat.py::test_task_like_chat_message_does_not_create_tasks_or_schedule_work` |
| V0-093 | `CADEN_v0.md` | Task submit without deadline is a loud failure / bypass bug | pytest | covered | `tests/test_m4_addtask.py::test_m4_addtask_requires_deadline_before_submitting` |
| V0-094 | `CADEN_v0.md` | Task completion with no paired event is a loud failure | pytest | covered | `tests/test_m5_completion.py::test_m5_completion_without_task_event_pairing_fails_loudly` |
| V0-095 | `CADEN_v0.md` | Paired event edit failure is loud | pytest | covered | `tests/test_contract_edit_task.py::test_edit_task_save_fails_loudly_when_paired_calendar_event_update_fails` |
| V0-096 | `CADEN_v0.md` | Repair layer tolerates prose-wrapped JSON | pytest | covered | `tests/test_m2_llm_roundtrip.py::test_m2_llm_roundtrip` |
| V0-097 | `CADEN_v0.md` | Repair layer tolerates fenced JSON | pytest | covered | Same test |
| V0-098 | `CADEN_v0.md` | Repair layer tolerates trailing commas / single quotes / slightly wrong fields | pytest | covered | `tests/test_contract_repair.py::test_repair_accepts_single_quotes_and_trailing_commas` and `tests/test_contract_repair.py::test_repair_accepts_slightly_wrong_field_names` |
| V0-099 | `CADEN_v0.md` | Fields may arrive in a different order than requested | pytest | covered | `tests/test_contract_repair.py::test_repair_accepts_fields_in_different_order` |
| V0-100 | `CADEN_v0.md` | Missing or genuinely wrong content still fails loudly after repair | pytest | covered | `tests/test_contract_repair.py::test_repair_fails_loudly_when_required_content_is_missing` |
| V0-101 | `CADEN_v0.md` | Callers never handle raw LLM output directly | pytest | covered | `tests/test_m6_rater.py::test_rater_routes_raw_llm_output_through_shared_repair_layer`, `tests/test_contract_schedule.py::test_scheduler_routes_raw_llm_output_through_shared_repair_layer`, and `tests/test_contract_predict.py::test_prediction_routes_raw_llm_output_through_shared_repair_layer` |
| V0-102 | `CADEN_v0.md` | Repairs are logged | pytest | covered | `tests/test_contract_repair.py::test_repair_accepts_single_quotes_and_trailing_commas` and `tests/test_contract_repair.py::test_repair_logs_validation_failures` |

## CADEN_v0 Tech Stack and Implementation Contracts

| ID | Source | Requirement | Mode | Status | Evidence / Gap |
| --- | --- | --- | --- | --- | --- |
| V0-103 | `CADEN_v0.md` | Target platform is Ubuntu | manual-review | manual | Deployment/environment fact |
| V0-104 | `CADEN_v0.md` | Embedding model is `nomic-embed-text` | pytest | covered | `tests/test_contract_config.py::test_config_uses_documented_settings_and_data_paths` |
| V0-105 | `CADEN_v0.md` | Rolling aggregations use pandas | manual-review | manual | Implementation/library choice |
| V0-106 | `CADEN_v0.md` | Regression / neighbors should use battle-tested libs, not custom stats | manual-review | manual | Library-choice policy |
| V0-107 | `CADEN_v0.md` | Storage is one sqlite DB using sqlite-vec | pytest | covered | `tests/test_contract_db.py::test_connect_verifies_sqlite_vec_is_loaded` and `tests/test_contract_db.py::test_apply_schema_creates_documented_vector_tables_and_pins_embed_dim` |
| V0-108 | `CADEN_v0.md` | GUI toolkit is Textual | pytest | covered | UI tests instantiate Textual app |
| V0-109 | `CADEN_v0.md` | Google integration uses `google-api-python-client` and `google-auth` | manual-review | manual | Dependency choice |
| V0-110 | `CADEN_v0.md` | Platform is Ubuntu 24.04 LTS | manual-review | manual | Deployment target |
| V0-111 | `CADEN_v0.md` | Python version is 3.12 | manual-review | manual | Environment requirement |
| V0-112 | `CADEN_v0.md` | Dependency manager is `uv` | manual-review | manual | Tooling requirement |
| V0-113 | `CADEN_v0.md` | Only one sudo step exists at install time, runtime is sudoless | manual-review | manual | Deployment/install policy |
| V0-114 | `CADEN_v0.md` | Code lives at `~/caden-src/` | manual-review | manual | Deployment layout requirement, not current workspace path |
| V0-115 | `CADEN_v0.md` | Data lives at `~/.local/share/caden/` | pytest | covered | `tests/test_contract_config.py::test_config_uses_documented_settings_and_data_paths` |
| V0-116 | `CADEN_v0.md` | Config lives at `~/.config/caden/` | pytest | covered | Same test |
| V0-117 | `CADEN_v0.md` | Scratch lives at `~/.local/share/caden/scratch/` | pytest | covered | `tests/test_contract_config.py::test_config_uses_documented_settings_and_data_paths` |

## CADEN_v0 Error, Concurrency, and Time Contracts

| ID | Source | Requirement | Mode | Status | Evidence / Gap |
| --- | --- | --- | --- | --- | --- |
| V0-118 | `CADEN_v0.md` | Root error class is `CadenError` with listed subsystem subclasses | pytest | covered | `tests/test_contract_error_hierarchy.py::test_public_caden_error_hierarchy_exposes_documented_subsystem_classes` |
| V0-119 | `CADEN_v0.md` | Loud failure means raising appropriate `CadenError` with chained original exception | pytest | covered | `tests/test_contract_config.py::test_config_invalid_toml_preserves_original_parse_error`, `tests/test_contract_metadata.py::test_write_event_wraps_sqlite_failures_with_chained_dberror`, `tests/test_contract_edit_task.py::test_edit_task_save_fails_loudly_when_paired_calendar_event_update_fails`, `tests/test_contract_google_sync.py::test_google_sync_runtime_errors_preserve_original_http_error_as_cause`, `tests/test_contract_schedule.py::test_scheduler_requires_aware_deadline_and_chains_llm_errors`, `tests/test_contract_predict.py::test_prediction_llm_failure_is_loud_and_chains_original_error`, and `tests/test_m6_rater.py::test_rater_llm_failure_is_loud_and_chains_original_error` |
| V0-120 | `CADEN_v0.md` | Textual top level catches `CadenError`, shows banner, halts failing subsystem, others continue | pytest | covered | `tests/test_contract_errors.py::test_completion_poll_failure_surfaces_error_banner_and_halts_subsystem` |
| V0-121 | `CADEN_v0.md` | Error banner lives in `caden/ui/_error.py` and is reused for boot/runtime failures | pytest | covered | Runtime banner behavior plus shared boot formatter path are covered by `tests/test_contract_boot.py::test_main_boot_failure_uses_shared_error_banner_formatter` and existing runtime banner tests |
| V0-122 | `CADEN_v0.md` | Catastrophic boot failures exit non-zero and show banner in terminal | pytest | covered | `tests/test_contract_boot.py::test_main_returns_nonzero_and_prints_boot_failure` |
| V0-123 | `CADEN_v0.md` | No swallowed exceptions are allowed | pytest | covered | `tests/test_contract_no_swallow.py::test_codebase_avoids_bare_except_and_except_pass_patterns` |
| V0-124 | `CADEN_v0.md` | One asyncio event loop is used | manual-review | manual | Runtime architecture fact |
| V0-125 | `CADEN_v0.md` | All DB writes go through one async write queue / single writer discipline | pytest | covered | `tests/test_contract_metadata.py::test_all_runtime_db_writes_serialize_through_one_queue` plus store-routed task_event mutation helpers in add-task/edit-task |
| V0-126 | `CADEN_v0.md` | DB reads can be concurrent | manual-review | manual | Architectural note, not current test target |
| V0-127 | `CADEN_v0.md` | Blocking external calls use `await` / `asyncio.to_thread` as needed | pytest | covered | `tests/test_contract_gui.py::test_app_poll_completions_offloads_blocking_poll_once_via_to_thread`, `tests/test_contract_gui.py::test_dashboard_refresh_panels_offloads_google_reads_via_to_thread`, `tests/test_contract_gui.py::test_dashboard_complete_task_offloads_blocking_google_calls_via_to_thread`, `tests/test_contract_chat.py::test_chat_blocking_steps_offload_via_to_thread`, `tests/test_contract_chat.py::test_chat_rating_offloads_event_load_and_rating_via_to_thread`, `tests/test_m4_addtask.py::test_add_task_submit_offloads_execute_via_to_thread`, and `tests/test_contract_edit_task.py::test_edit_task_submit_offloads_save_via_to_thread` plus `tests/test_contract_edit_task.py::test_edit_task_complete_offloads_completion_via_to_thread` |
| V0-128 | `CADEN_v0.md` | Background workers are owned by the main app and cancelled on subsystem failure/shutdown | pytest | covered | `tests/test_contract_errors.py::test_completion_poll_failure_surfaces_error_banner_and_halts_subsystem`, `tests/test_contract_chat.py::test_chat_mount_starts_named_rater_worker`, `tests/test_contract_chat.py::test_chat_submit_starts_named_chat_worker`, and `tests/test_contract_gui.py::test_app_shutdown_cancels_owned_background_workers` |
| V0-129 | `CADEN_v0.md` | Stored timestamps are ISO-8601 with explicit UTC offset | pytest | covered | `tests/test_contract_metadata.py::test_stored_timestamps_use_iso8601_with_explicit_utc_offset` |
| V0-130 | `CADEN_v0.md` | Internal computation uses aware UTC datetimes | pytest | covered | `tests/test_contract_schedule.py::test_scheduler_requires_aware_deadline_and_chains_llm_errors` and existing UTC conversion/assertion contracts in scheduler and dashboard tests |
| V0-131 | `CADEN_v0.md` | Display converts to local timezone cached as `display_tz` | pytest | covered | `tests/test_contract_config.py::test_config_uses_documented_settings_and_data_paths` |
| V0-132 | `CADEN_v0.md` | Google items are converted to UTC on read and local tz only at render time | pytest | covered | `tests/test_m3_google_read.py::test_dashboard_renders_google_times_in_local_timezone_from_utc_inputs` |
| V0-133 | `CADEN_v0.md` | All rendered user-facing times are 12-hour AM/PM | pytest | covered | `tests/test_contract_timefmt.py`, `tests/test_contract_edit_task.py::test_edit_task_save_updates_google_records_and_local_task_event`, `tests/test_m3_google_read.py::test_dashboard_renders_google_times_in_local_timezone_from_utc_inputs`, and `tests/test_m4_addtask.py::test_m4_addtask` |
| V0-134 | `CADEN_v0.md` | Time formatting helpers live in `caden/util/timefmt.py` | manual-review | manual | File/module location fact |

## CADEN_v0 Schema, Confidence, Metadata, and Why Generation

| ID | Source | Requirement | Mode | Status | Evidence / Gap |
| --- | --- | --- | --- | --- | --- |
| V0-135 | `CADEN_v0.md` | Single sqlite DB lives at `~/.local/share/caden/caden.db` | pytest | covered | `tests/test_contract_config.py::test_config_uses_documented_settings_and_data_paths` |
| V0-136 | `CADEN_v0.md` | Alembic manages migrations in `caden/libbie/migrations/` | manual-review | manual | Repo structure fact |
| V0-137 | `CADEN_v0.md` | `events` table exists with source/raw text and linked embeddings | pytest | covered | `tests/test_m1_skeleton.py::test_m1_skeleton` and `tests/test_contract_retrieve.py::test_write_event_captures_raw_event_before_canonical_memory_row` |
| V0-138 | `CADEN_v0.md` | `memories` table exists with required curated fields | pytest | covered | `tests/test_contract_metadata.py::test_memory_frame_contract_preserves_required_invariants` |
| V0-139 | `CADEN_v0.md` | `event_metadata` is append-only | pytest | covered | `tests/test_contract_metadata.py::test_event_metadata_writes_are_append_only_at_the_sql_boundary` |
| V0-140 | `CADEN_v0.md` | `ratings` table stores nullable scores/confidences and rationale | pytest | covered | `tests/test_m6_rater.py::test_m6_rater` |
| V0-141 | `CADEN_v0.md` | `predictions` table stores duration, pre/post states, confidences, rationale | pytest | covered | `tests/test_contract_metadata.py::test_write_prediction_persists_rationale_and_confidence_fields` |
| V0-142 | `CADEN_v0.md` | `residuals` table stores duration and state residuals | pytest | covered | `tests/test_m5_completion.py::test_m5_residual_state_fields_stay_null_without_nearby_ratings` and `tests/test_m5_completion.py::test_m5_normal_completion_truncates_google_event_and_fills_state_residuals` |
| V0-143 | `CADEN_v0.md` | `tasks` table stores task identity, deadline, status, completion time | pytest | covered | `tests/test_contract_metadata.py::test_tasks_table_stores_identity_deadline_status_and_completion_time` |
| V0-144 | `CADEN_v0.md` | `task_events` table stores planned start/end and event linkage | pytest | covered | `tests/test_m4_addtask.py::test_m4_addtask_creates_a_single_scheduled_block` |
| V0-145 | `CADEN_v0.md` | Typed rows are mirrored into `events` for unified retrieval | pytest | covered | `tests/test_contract_metadata.py::test_task_rows_are_mirrored_into_events`, `tests/test_contract_metadata.py::test_task_event_rows_are_mirrored_into_events`, `tests/test_contract_metadata.py::test_write_rating_rows_are_mirrored_into_events`, `tests/test_m4_addtask.py::test_m4_addtask`, and `tests/test_m5_completion.py::test_m5_completion` |
| V0-146 | `CADEN_v0.md` | Event embeddings are split into sibling storage and `vec_events` | manual-review | manual | Storage implementation detail |
| V0-147 | `CADEN_v0.md` | Memory embeddings are split into sibling storage and `vec_memories` | manual-review | manual | Storage implementation detail |
| V0-148 | `CADEN_v0.md` | Prediction rationale column exists | pytest | covered | `tests/test_contract_metadata.py::test_write_prediction_persists_rationale_and_confidence_fields` |
| V0-149 | `CADEN_v0.md` | `task_events` has `planned_start`, `planned_end`, and `actual_end` | pytest | covered | `tests/test_m4_addtask.py::test_m4_addtask_creates_a_single_scheduled_block` and `tests/test_m5_completion.py::test_m5_completion` |
| V0-150 | `CADEN_v0.md` | Confidences are REAL in [0.0, 1.0] | pytest | covered | `tests/test_contract_metadata.py::test_write_prediction_and_rating_reject_invalid_unknown_sentinels_and_confidence_bounds` |
| V0-151 | `CADEN_v0.md` | NULL means unknown | pytest | covered | `tests/test_m6_rater.py::test_m6_rater_preserves_unknown_axes_as_null` |
| V0-152 | `CADEN_v0.md` | Sentinel unknown values like -1/999 are never used | pytest | covered | `tests/test_contract_metadata.py::test_write_prediction_and_rating_reject_invalid_unknown_sentinels_and_confidence_bounds` |
| V0-153 | `CADEN_v0.md` | Metadata keys include `captured_at` | pytest | covered | `tests/test_contract_metadata.py::test_write_event_appends_event_metadata_rows` |
| V0-154 | `CADEN_v0.md` | Metadata key `trigger` is supported | pytest | covered | Same test |
| V0-155 | `CADEN_v0.md` | Metadata key `why` is supported | pytest | covered | `tests/test_contract_metadata.py::test_write_event_supports_documented_why_project_and_entry_type_metadata_keys` |
| V0-156 | `CADEN_v0.md` | Metadata key `linked_to` is supported | pytest | covered | `tests/test_contract_metadata.py::test_write_event_appends_event_metadata_rows` |
| V0-157 | `CADEN_v0.md` | Metadata key `project_id` is supported | pytest | covered | `tests/test_contract_metadata.py::test_write_event_supports_documented_why_project_and_entry_type_metadata_keys` |
| V0-158 | `CADEN_v0.md` | Metadata key `entry_type` is supported | pytest | covered | `tests/test_contract_metadata.py::test_write_event_supports_documented_why_project_and_entry_type_metadata_keys` |
| V0-159 | `CADEN_v0.md` | Sprocket metadata keys like `attempt_index` / `approach` are supported | future | covered | Sprocket is explicitly out of scope for v0 (`V0-256`) |
| V0-160 | `CADEN_v0.md` | `why` generation is async and capture is immediate | pytest | covered | `tests/test_contract_chat.py::test_chat_why_enrichment_offloads_generation_via_to_thread`, `tests/test_contract_metadata.py::test_append_event_metadata_adds_why_later_without_mutating_event_row`, and `tests/test_contract_why.py::test_generate_why_for_event_appends_metadata_row` |
| V0-161 | `CADEN_v0.md` | Missing `why` is a permitted partial success with loud log only | pytest | covered | `tests/test_contract_chat.py::test_chat_why_enrichment_failure_is_best_effort` and `tests/test_contract_why.py::test_generate_why_for_event_propagates_llm_failure` |

## CADEN_v0 LLM Client, Context Budgeting, Stats, and Logging

| ID | Source | Requirement | Mode | Status | Evidence / Gap |
| --- | --- | --- | --- | --- | --- |
| V0-162 | `CADEN_v0.md` | Repair uses `json_repair` and `pydantic` | manual-review | manual | Implementation/library choice |
| V0-163 | `CADEN_v0.md` | Repair pipeline strips fences, repairs JSON, validates typed schema, or raises `LLMRepairError` | pytest | covered | `tests/test_contract_repair.py::test_repair_accepts_single_quotes_and_trailing_commas`, `tests/test_contract_repair.py::test_repair_accepts_fields_in_different_order`, and `tests/test_contract_repair.py::test_repair_fails_loudly_when_required_content_is_missing` |
| V0-164 | `CADEN_v0.md` | Ollama calls are serialized through a single-slot semaphore | pytest | covered | `tests/test_contract_llm_client.py::test_ollama_client_serializes_calls_through_single_slot_semaphore` |
| V0-165 | `CADEN_v0.md` | Foreground requests preempt background requests | pytest | covered | `tests/test_contract_llm_client.py::test_foreground_request_preempts_background_stream_and_aborts_it` |
| V0-166 | `CADEN_v0.md` | Background preemption raises `LLMAborted` and requeues work | pytest | covered | `tests/test_contract_llm_client.py::test_foreground_request_preempts_background_stream_and_aborts_it`; `tests/test_contract_chat.py::test_rater_consumer_requeues_aborted_background_work` |
| V0-167 | `CADEN_v0.md` | Context budgeting avoids fixed authoritative retrieval-count/truncation thresholds | pytest | covered | `tests/test_contract_curate.py::test_package_chat_context_does_not_hardcode_fixed_retrieval_k`, `tests/test_contract_curate.py::test_package_chat_context_keeps_all_live_calendar_and_task_lines_without_fixed_cap`, and existing prompt-char-cap contract tests in scheduler/rater/predict paths |
| V0-168 | `CADEN_v0.md` | Prompt packaging honestly states what context was included | pytest | covered | `tests/test_contract_curate.py::test_package_chat_context_honestly_reports_unavailable_google_sources` and `tests/test_contract_curate.py::test_package_chat_context_centralizes_thread_memory_and_live_world` |
| V0-169 | `CADEN_v0.md` | Packaging fails loudly when usable prompt cannot be built | pytest | covered | `tests/test_contract_curate.py::test_package_chat_context_fails_loudly_when_memory_lookup_cannot_run` |
| V0-170 | `CADEN_v0.md` | Packaging avoids silent signal dropping disguised as safety caps | pytest | covered | `tests/test_contract_curate.py::test_package_chat_context_keeps_all_live_calendar_and_task_lines_without_fixed_cap` |
| V0-171 | `CADEN_v0.md` | Residual aggregation uses pandas | manual-review | manual | Library choice |
| V0-172 | `CADEN_v0.md` | Residual weight learning defaults to Ridge regression | pytest | covered | `tests/test_contract_learning.py::test_fit_residual_ridge_learns_weights_from_residual_frame` |
| V0-173 | `CADEN_v0.md` | Nearest-neighbor retrieval scoring uses scikit-learn `NearestNeighbors` | manual-review | manual | Currently not a strict runtime contract in tests |
| V0-174 | `CADEN_v0.md` | Trend detection uses Mann-Kendall | pytest | covered | `tests/test_contract_learning.py::test_mann_kendall_trend_detects_increasing_sequence` and `tests/test_contract_learning.py::test_mann_kendall_trend_detects_no_trend_in_flat_sequence` |
| V0-175 | `CADEN_v0.md` | Bias detection uses `scipy.stats.binomtest` | pytest | covered | `tests/test_contract_learning.py::test_detect_directional_bias_uses_binomtest` |
| V0-176 | `CADEN_v0.md` | `structlog` writes JSON lines to `~/.local/share/caden/logs/caden.log` | pytest | covered | `tests/test_contract_diag.py::test_setup_logging_writes_json_lines_to_caden_log` |
| V0-177 | `CADEN_v0.md` | Log lines are also captured as low-priority `caden_log` events | pytest | covered | `tests/test_contract_diag.py::test_setup_logging_can_mirror_log_lines_into_low_priority_caden_log_events` |
| V0-178 | `CADEN_v0.md` | Default log level is INFO | pytest | covered | `tests/test_contract_diag.py::test_setup_logging_defaults_to_info_level` |
| V0-179 | `CADEN_v0.md` | `caden/diag.py` writes human-readable diagnostics to `~/.caden/diag.log` | pytest | covered | `tests/test_contract_diag.py::test_diag_writes_human_readable_records_to_documented_path` |
| V0-180 | `CADEN_v0.md` | Every LLM call, scheduler outcome, and raised `CadenError` gets a diag line | pytest | covered | `tests/test_contract_llm_client.py::test_llm_calls_emit_diag_request_and_response_lines`; `tests/test_contract_schedule.py::test_scheduler_success_emits_diag_outcome_line`; `tests/test_contract_diag.py::test_error_banner_emits_diag_line_for_raised_caden_error` |
| V0-181 | `CADEN_v0.md` | Diag failure is a permitted partial success logged via structlog | pytest | covered | `tests/test_contract_diag.py::test_diag_failure_is_logged_via_structlog_without_raising` |

## CADEN_v0 Scheduling, Completion, Google, Chat, and Packaging

| ID | Source | Requirement | Mode | Status | Evidence / Gap |
| --- | --- | --- | --- | --- | --- |
| V0-182 | `CADEN_v0.md` | First-time scheduling reads existing Google Calendar items between now and deadline across enabled calendars | pytest | covered | `tests/test_m4_addtask.py::test_add_task_reads_calendar_between_now_and_deadline_and_tags_caden_owned_events` |
| V0-183 | `CADEN_v0.md` | Scheduler prompt includes task description, deadline, calendar events, and recent Libbie events | pytest | covered | `tests/test_contract_schedule.py::test_scheduler_prompt_includes_description_deadline_calendar_events_and_libbie_context` |
| V0-184 | `CADEN_v0.md` | LLM picks concrete start/end and emits confidences with no framework default duration or floor | pytest | covered | `tests/test_contract_schedule.py::test_scheduler_derives_duration_from_end_minus_start_and_allows_slot_up_to_deadline` and `tests/test_contract_predict.py::test_prediction_writes_low_and_null_confidences_without_flooring_or_defaults` |
| V0-185 | `CADEN_v0.md` | Schedule duration is derived from end-start and is not an LLM field | pytest | covered | `tests/test_contract_schedule.py::test_scheduler_derives_duration_from_end_minus_start_and_allows_slot_up_to_deadline` |
| V0-186 | `CADEN_v0.md` | Unknown state axes are written through as NULL | pytest | covered | `tests/test_m6_rater.py::test_m6_rater_preserves_unknown_axes_as_null` |
| V0-187 | `CADEN_v0.md` | Scheduler may place block anywhere before deadline | pytest | covered | `tests/test_contract_schedule.py::test_scheduler_derives_duration_from_end_minus_start_and_allows_slot_up_to_deadline` |
| V0-188 | `CADEN_v0.md` | Rescheduling may move CADEN-created blocks but never external events | pytest | covered | `tests/test_contract_schedule.py::test_scheduler_rejects_moving_external_events` and `tests/test_contract_schedule.py::test_scheduler_rejects_overlapping_external_events` |
| V0-189 | `CADEN_v0.md` | No working-hours constraint is imposed by CADEN | pytest | covered | `tests/test_contract_schedule.py::test_scheduler_allows_valid_early_morning_slot_without_working_hours_rule` |
| V0-190 | `CADEN_v0.md` | Dashboard today window is anchored to 5 AM local boundary | pytest | covered | `tests/test_m3_google_read.py::test_dashboard_day_window_uses_5am_local_boundary` |
| V0-191 | `CADEN_v0.md` | 7-day panel is anchored from the same 5 AM boundary | pytest | covered | `tests/test_m3_google_read.py::test_dashboard_next_7_days_panel_uses_same_5am_boundary_as_today` |
| V0-192 | `CADEN_v0.md` | Normal completion edits event end to `T`, start unchanged | pytest | covered | `tests/test_m5_completion.py::test_m5_normal_completion_truncates_google_event_and_fills_state_residuals` |
| V0-193 | `CADEN_v0.md` | Normal duration residual is `(T - scheduled_start) - predicted_duration` | pytest | covered | `tests/test_m5_completion.py::test_m5_completion` |
| V0-194 | `CADEN_v0.md` | Early completion shifts event to `[T - predicted_duration, T]` | pytest | covered | `tests/test_m5_completion.py::test_m5_early_completion_shifts_event_and_skips_duration_residual` |
| V0-195 | `CADEN_v0.md` | Early completion skips duration residual for that attempt | pytest | covered | `tests/test_m5_completion.py::test_m5_early_completion_shifts_event_and_skips_duration_residual` |
| V0-196 | `CADEN_v0.md` | State residuals still apply on early completion | pytest | covered | `tests/test_m5_completion.py::test_m5_early_completion_still_fills_state_residuals_from_nearby_ratings` |
| V0-197 | `CADEN_v0.md` | Bulk completion is processed sequentially in arrival order | pytest | covered | `tests/test_m5_completion.py::test_m5_poll_once_uses_local_open_state_and_finalises_in_arrival_order` |
| V0-198 | `CADEN_v0.md` | Missing paired event on completion raises `SchedulerError` | pytest | covered | `tests/test_m5_completion.py::test_m5_completion_without_task_event_pairing_fails_loudly` |
| V0-199 | `CADEN_v0.md` | Google Tasks are polled every 60 seconds while running | pytest | covered | `tests/test_contract_gui.py::test_completion_poll_uses_documented_60_second_cadence` |
| V0-200 | `CADEN_v0.md` | Completion detection compares Google completion state to cached task-table state | pytest | covered | `tests/test_m5_completion.py::test_m5_poll_once_uses_local_open_state_and_finalises_in_arrival_order` |
| V0-201 | `CADEN_v0.md` | Poll cadence is implementation detail, not learned behavior | manual-review | manual | Spec clarification, not runtime behavior |
| V0-202 | `CADEN_v0.md` | First OAuth enumerates available calendars and task lists | pytest | covered | `tests/test_contract_google_auth.py::test_google_auth_enumerates_available_calendars_and_task_lists` |
| V0-203 | `CADEN_v0.md` | Settings surface lets Sean check/uncheck readable/writable calendars and lists | pytest | covered | `tests/test_contract_config.py::test_config_uses_documented_settings_and_data_paths` (settings.toml scope keys) |
| V0-204 | `CADEN_v0.md` | CADEN never touches unchecked calendars or lists | pytest | covered | `tests/test_contract_google_sync.py::test_calendar_client_reads_only_configured_calendars_and_writes_to_default` and `tests/test_contract_google_sync.py::test_tasks_client_reads_only_configured_lists_and_writes_to_default` |
| V0-205 | `CADEN_v0.md` | Scope changes are stored as events | pytest | covered | `tests/test_contract_boot.py::test_boot_persists_google_scope_change_as_event` |
| V0-206 | `CADEN_v0.md` | Writes go to Sean-designated default calendar/list and add-task is unusable before defaults exist | pytest | covered | `tests/test_contract_google_sync.py::test_calendar_client_reads_only_configured_calendars_and_writes_to_default`, `tests/test_contract_google_sync.py::test_tasks_client_reads_only_configured_lists_and_writes_to_default`, and `tests/test_m4_addtask.py::test_add_task_requires_default_writable_targets_when_scope_clients_expose_them` |
| V0-207 | `CADEN_v0.md` | Only Sean messages are stored as `sean_chat` events with embeddings | pytest | covered | `tests/test_m1_skeleton.py::test_m1_skeleton` |
| V0-208 | `CADEN_v0.md` | CADEN responses are not stored as events | pytest | covered | `tests/test_m1_skeleton.py::test_m1_skeleton` |
| V0-209 | `CADEN_v0.md` | Last few CADEN responses live in process-local deque capped at 4 | pytest | covered | `tests/test_contract_chat.py::test_session_reply_memory_cap_matches_v0` |
| V0-210 | `CADEN_v0.md` | Session reply deque is never persisted, embedded, or retrieved | pytest | covered | `tests/test_contract_chat.py::test_task_like_chat_message_does_not_create_tasks_or_schedule_work`, `tests/test_contract_chat.py::test_chat_retrieval_defensively_excludes_caden_chat_source`, and `tests/test_contract_chat.py::test_session_reply_deque_is_process_local_context_only` |
| V0-211 | `CADEN_v0.md` | Session reply deque empties on shutdown | pytest | covered | `tests/test_contract_chat.py::test_session_reply_deque_starts_empty_for_a_new_widget_lifecycle` |
| V0-212 | `CADEN_v0.md` | Retrieval excludes any `caden_chat` source defensively | pytest | covered | `tests/test_contract_chat.py::test_chat_retrieval_defensively_excludes_caden_chat_source` |
| V0-213 | `CADEN_v0.md` | `package_chat_context()` lives in `caden/libbie/curate.py` | pytest | covered | `tests/test_contract_curate.py::test_package_chat_context_centralizes_thread_memory_and_live_world` |
| V0-214 | `CADEN_v0.md` | Chat context packages retrieval plus live world context | pytest | covered | `tests/test_contract_curate.py::test_package_chat_context_centralizes_thread_memory_and_live_world` |
| V0-215 | `CADEN_v0.md` | Chat/add-task/rater share centralized context packaging rather than reinventing it | pytest | covered | `tests/test_contract_curate.py::test_package_recall_context_defines_the_shared_caden_facing_memory_shape`; `tests/test_contract_schedule.py::test_scheduler_uses_libbie_packaged_recall_context`; `tests/test_m6_rater.py::test_rater_uses_libbie_packaged_recall_context` |
| V0-216 | `CADEN_v0.md` | CADEN-facing retrieval uses curated memories, not raw events | pytest | covered | Same evidence as `V0-049`: `tests/test_contract_curate.py::test_package_chat_context_uses_compact_recall_packets_instead_of_raw_event_dump` |
| V0-217 | `CADEN_v0.md` | Raw events remain available for provenance, replay, and audit | pytest | covered | Same evidence as `V0-047`: `tests/test_contract_metadata.py::test_raw_events_can_be_replayed_with_provenance_and_memory_linkage` and `tests/test_contract_metadata.py::test_write_event_keeps_raw_events_append_only_at_the_sql_boundary` |
| V0-218 | `CADEN_v0.md` | Dashboard chat events always have `project_id = NULL` | pytest | covered | `tests/test_contract_chat.py::test_dashboard_chat_events_always_store_project_id_as_null` |
| V0-219 | `CADEN_v0.md` | Dashboard chat retrieval may include memories derived from PM-tagged events | future | covered | PM app is explicitly out of scope for v0 (`V0-256`) |
| V0-220 | `CADEN_v0.md` | Dashboard chat is the only chat surface in v0 | pytest | covered | `tests/test_contract_chat.py::test_v0_exposes_only_one_dashboard_chat_surface` |
| V0-221 | `CADEN_v0.md` | `llm.model` in settings configures default LLM model | pytest | covered | `tests/test_contract_config.py::test_config_uses_documented_settings_and_data_paths` |
| V0-222 | `CADEN_v0.md` | Preferred model is `qwen3.5:9b` subject to install-time tag verification | manual-review | manual | Preference/deployment note |
| V0-223 | `CADEN_v0.md` | Embedding model is `nomic-embed-text` with 768 dims | pytest | covered | `tests/test_contract_config.py::test_config_uses_documented_settings_and_data_paths` |
| V0-224 | `CADEN_v0.md` | Sprocket sandbox runs under `firejail --net=none --private=<scratch> --quiet python <script>` | future | covered | Sprocket is explicitly out of scope for v0 (`V0-256`) |
| V0-225 | `CADEN_v0.md` | Sandbox timeout policy is deferred and not bootstrapped here | future | covered | Sprocket is explicitly out of scope for v0 (`V0-256`) |
| V0-226 | `CADEN_v0.md` | Network enablement requires explicit brief need and Sean acknowledgement; default is no-network | future | covered | Sprocket is explicitly out of scope for v0 (`V0-256`) |

## CADEN_v0 Boot Sequence, Milestones, and Out-of-Scope

| ID | Source | Requirement | Mode | Status | Evidence / Gap |
| --- | --- | --- | --- | --- | --- |
| V0-227 | `CADEN_v0.md` | Boot loads config first | pytest | covered | `tests/test_contract_boot.py::test_boot_runs_prerequisites_in_documented_order_and_allows_chat_only_without_google` |
| V0-228 | `CADEN_v0.md` | Boot opens DB, applies migrations, and verifies sqlite-vec | pytest | covered | `tests/test_contract_boot.py::test_boot_runs_prerequisites_in_documented_order_and_allows_chat_only_without_google` and `tests/test_contract_db.py::test_connect_verifies_sqlite_vec_is_loaded` and `tests/test_contract_db.py::test_apply_schema_creates_documented_vector_tables_and_pins_embed_dim` |
| V0-229 | `CADEN_v0.md` | Boot verifies ollama reachability and configured model presence | pytest | covered | `tests/test_contract_boot.py::test_boot_runs_prerequisites_in_documented_order_and_allows_chat_only_without_google` |
| V0-230 | `CADEN_v0.md` | Boot verifies `nomic-embed-text` availability | pytest | covered | Same boot-order test covers `Embedder.check()` orchestration |
| V0-231 | `CADEN_v0.md` | Boot loads or refreshes Google OAuth credentials | pytest | covered | `tests/test_contract_boot.py::test_boot_loads_google_clients_when_credentials_exist` |
| V0-232 | `CADEN_v0.md` | Boot launches Textual app after prerequisites | pytest | covered | `tests/test_contract_boot.py::test_main_launches_textual_app_only_after_boot_and_closes_services` |
| V0-233 | `CADEN_v0.md` | Any failing boot step stops startup loudly | pytest | covered | `tests/test_contract_boot.py::test_main_returns_nonzero_and_prints_boot_failure` |
| V0-234 | `CADEN_v0.md` | Missing Google credentials is the sole softening: chat-only boot is allowed | pytest | covered | `tests/test_contract_boot.py::test_boot_runs_prerequisites_in_documented_order_and_allows_chat_only_without_google` |
| V0-235 | `CADEN_v0.md` | Once credentials exist, subsequent Google failures are loud | pytest | covered | `tests/test_contract_boot.py::test_boot_raises_loudly_when_google_credentials_exist_but_loading_fails` |
| V0-236 | `CADEN_v0.md` | Milestone 1 requires placeholder today/7-day panels | pytest | covered | `tests/test_contract_gui.py::test_dashboard_shows_documented_google_sync_placeholders_when_booted_chat_only` |
| V0-237 | `CADEN_v0.md` | Milestone 1 requires Sean chat writes with embeddings and ephemeral CADEN replies | pytest | covered | `tests/test_m1_skeleton.py::test_m1_skeleton` |
| V0-238 | `CADEN_v0.md` | Milestone 1 requires sqlite-vec verification with nomic vectors | pytest | covered | `tests/test_contract_db.py::test_connect_verifies_sqlite_vec_is_loaded` and `tests/test_contract_boot.py::test_boot_runs_prerequisites_in_documented_order_and_allows_chat_only_without_google` |
| V0-239 | `CADEN_v0.md` | Milestone 2 requires actual ollama response path | pytest | covered | `tests/test_m2_llm_roundtrip.py::test_m2_llm_roundtrip` |
| V0-240 | `CADEN_v0.md` | Milestone 2 requires clean JSON or loud error from repair layer | pytest | covered | `tests/test_m2_llm_roundtrip.py::test_m2_llm_roundtrip`, `tests/test_contract_repair.py::test_repair_fails_loudly_when_required_content_is_missing` |
| V0-241 | `CADEN_v0.md` | Milestone 2 requires chat context from curated memory recall, not raw event dump | pytest | covered | `tests/test_contract_curate.py::test_package_chat_context_uses_compact_recall_packets_instead_of_raw_event_dump` |
| V0-242 | `CADEN_v0.md` | Milestone 3 requires OAuth flow | pytest | covered | `tests/test_contract_google_auth.py::test_load_credentials_runs_local_oauth_flow_and_persists_token` and `tests/test_contract_google_auth.py::test_load_credentials_refreshes_cached_token_and_rewrites_token_file` |
| V0-243 | `CADEN_v0.md` | Milestone 3 requires today panel rendering Google Calendar events | pytest | covered | `tests/test_m3_google_read.py::test_m3_google_read` |
| V0-244 | `CADEN_v0.md` | Milestone 3 requires 7-day panel rendering next 7 days | pytest | covered | `tests/test_m3_google_read.py::test_dashboard_next_7_days_panel_includes_future_events_and_tasks` |
| V0-245 | `CADEN_v0.md` | Milestone 3 requires Google Tasks inline with events ordered by start/due time | pytest | covered | `tests/test_m3_google_read.py::test_dashboard_next_7_days_panel_orders_tasks_inline_with_events_by_start_and_due_time` |
| V0-246 | `CADEN_v0.md` | Milestone 4 requires add-task modal with required description and deadline | pytest | covered | `tests/test_m4_addtask.py::test_m4_addtask_requires_deadline_before_submitting`, `tests/test_m4_addtask.py::test_m4_addtask_requires_description_before_submitting` |
| V0-247 | `CADEN_v0.md` | Milestone 4 requires CADEN to create Google Task and paired Calendar event | pytest | covered | `tests/test_m4_addtask.py::test_m4_addtask` |
| V0-248 | `CADEN_v0.md` | Milestone 4 scheduling may be low-confidence and need not be learned yet | manual-review | manual | Historical milestone note |
| V0-249 | `CADEN_v0.md` | Milestone 4 emits prediction bundle into predictions and events | pytest | covered | `tests/test_m4_addtask.py::test_m4_addtask` |
| V0-250 | `CADEN_v0.md` | Milestone 5 detects completion and stores duration residual | pytest | covered | `tests/test_m5_completion.py::test_m5_completion` |
| V0-251 | `CADEN_v0.md` | Milestone 5 fills state residuals from nearby ratings | pytest | covered | `tests/test_m5_completion.py::test_m5_normal_completion_truncates_google_event_and_fills_state_residuals`; `tests/test_m5_completion.py::test_m5_early_completion_still_fills_state_residuals_from_nearby_ratings` |
| V0-252 | `CADEN_v0.md` | Milestone 6 rates every new event with Libbie retrieval | pytest | covered | `tests/test_m6_rater.py::test_rater_rates_each_documented_non_structural_event_source_with_libbie_retrieval` and `tests/test_m6_rater.py::test_rater_skips_only_documented_structural_event_sources` |
| V0-253 | `CADEN_v0.md` | Milestone 6 ratings are immutable and feed future retrieval | pytest | covered | `tests/test_contract_metadata.py::test_write_rating_never_updates_or_deletes_existing_rating_rows` and `tests/test_m6_rater.py::test_rating_rationale_feeds_future_retrieval_for_later_events` |
| V0-254 | `CADEN_v0.md` | Milestone 6 estimators return unknown when retrieval is too thin | pytest | covered | `tests/test_m6_rater.py::test_rater_starts_unknown_then_later_events_can_retrieve_observations` and `tests/test_m6_rater.py::test_m6_rater_preserves_unknown_axes_as_null` |
| V0-255 | `CADEN_v0.md` | After Milestone 6, v0 is complete | manual-review | manual | Release milestone statement |
| V0-256 | `CADEN_v0.md` | Project Manager, Thought Dump, and Sprocket are out of scope for v0 | future | covered | Not implemented; consistent with scope |
| V0-257 | `CADEN_v0.md` | Active schedule comparison or optimization is out of scope for v0 | pytest | covered | `tests/test_contract_schedule.py::test_scheduler_requests_and_returns_a_single_plan_not_alternative_options` |
| V0-258 | `CADEN_v0.md` | Schema growth is out of scope for v0 implementation | future | covered | Not implemented |
| V0-259 | `CADEN_v0.md` | Phase-change detection is out of scope for v0 implementation | future | covered | Not implemented |
| V0-260 | `CADEN_v0.md` | General-purpose web research is out of scope as first-class user feature | future | covered | Not implemented as first-class feature |
| V0-261 | `CADEN_v0.md` | Cross-device sync is out of scope for v0 | future | covered | Not implemented |
| V0-262 | `CADEN_v0.md` | Day-one minimum residual machinery includes populated predictions | pytest | covered | `tests/test_m4_addtask.py::test_m4_addtask` |
| V0-263 | `CADEN_v0.md` | Day-one minimum residual machinery includes populated residuals | pytest | covered | `tests/test_m5_completion.py::test_m5_completion` |
| V0-264 | `CADEN_v0.md` | There is an aggregate residual view/query using pandas and no bespoke math | pytest | covered | `tests/test_m5_completion.py::test_residual_aggregation_query_uses_pandas_and_groups_by_mechanism` |

## Supplemental Behavioral Claims Test Path (All CADEN_*.md)

This section closes traceability for behavioral claims listed in
`CADEN_docClaimsMatrix.md` that are outside the authoritative source pair.

Rules:
- if a supplemental claim is already authoritative-equivalent, it maps to
  existing `CMD-*` / `V0-*` evidence
- if a supplemental claim is post-v0 behavior, it is tracked as `future`
  with an explicit placeholder row here
- non-behavioral supplemental claims (`process_only`, `open_question`,
  `historical`) remain out of runtime proof scope

### Dashboard (post-v0)

| ID | Source | Requirement | Mode | Status | Evidence / Gap |
| --- | --- | --- | --- | --- | --- |
| SUP-DASH-001 | `CADEN_dashboard.md` | v0 surface remains the Dashboard tab in multi-app CADEN | pytest | covered | Equivalent to `CMD-031` and `V0-086` |
| SUP-DASH-002 | `CADEN_dashboard.md` | today panel shows prediction bundle per CADEN-scheduled item | pytest | covered | Covered by supplemental dashboard prediction-bundle rendering test |
| SUP-DASH-003 | `CADEN_dashboard.md` | today panel shows residuals after completion | pytest | covered | Covered by supplemental dashboard completed-task residual rendering test |
| SUP-DASH-004 | `CADEN_dashboard.md` | chat panel can expose retrieved memories in collapsible strip | pytest | covered | Covered by supplemental chat recalled-memory strip test |
| SUP-DASH-005 | `CADEN_dashboard.md` | chat panel can show inline rating/correction controls | pytest | covered | Covered by supplemental inline rating correction update/log test |
| SUP-DASH-006 | `CADEN_dashboard.md` | 7-day panel can include axis trajectory sparklines | pytest | covered | Covered by supplemental week-panel trajectory sparkline rendering test |
| SUP-DASH-007 | `CADEN_dashboard.md` | what-if schedule surface previews alternatives | pytest | covered | Covered by supplemental alternative schedule preview rendering test |
| SUP-DASH-008 | `CADEN_dashboard.md` | schema-growth proposals require explicit Sean accept/reject | pytest | covered | Covered by supplemental dashboard schema decision logging test |
| SUP-DASH-009 | `CADEN_dashboard.md` | phase-change alert surface supports acknowledge/hold/tell-me-more | pytest | covered | Covered by supplemental phase-change alert summary test |
| SUP-DASH-010 | `CADEN_dashboard.md` | active optimization unlocks only after readiness conditions | pytest | covered | Covered by supplemental optimization readiness gate test |
| SUP-DASH-011 | `CADEN_dashboard.md` | add-task can show candidate schedules with Pareto markers | pytest | covered | Covered by supplemental Pareto marker preview test |
| SUP-DASH-012 | `CADEN_dashboard.md` | residual audit overlay is transient and non-persistent | pytest | covered | Covered by supplemental transient non-persistent residual-audit overlay test |
| SUP-DASH-013 | `CADEN_dashboard.md` | drag override is logged as a preference-learning event | pytest | covered | Covered by supplemental drag-override learning-event logging test |
| SUP-DASH-014 | `CADEN_dashboard.md` | 3-panel dashboard layout remains intact as features expand | pytest | covered | Covered by supplemental dashboard panel continuity test |
| SUP-DASH-015 | `CADEN_dashboard.md` | invalid schema consent actions fail loudly instead of silently mutating state | pytest | covered | Covered by supplemental invalid-schema-decision loud-reject test |
| SUP-DASH-016 | `CADEN_dashboard.md` | inline correction rejects unknown prediction targets loudly | pytest | covered | Covered by supplemental unknown-prediction inline-correction loud-failure test |

### Learning (post-v0)

| ID | Source | Requirement | Mode | Status | Evidence / Gap |
| --- | --- | --- | --- | --- | --- |
| SUP-LEARN-001 | `CADEN_learning.md` | schema growth triggers on persistent residual failure + weight plateau | pytest | covered | Covered by supplemental schema-growth trigger test |
| SUP-LEARN-002 | `CADEN_learning.md` | LLM proposes schema fields and evaluates them on historical data | pytest | covered | Covered by supplemental LLM proposal + history evaluation test |
| SUP-LEARN-003 | `CADEN_learning.md` | accepted fields are back-filled and validated on held-out residual improvement | pytest | covered | Covered by supplemental approval/backfill/heldout validation test |
| SUP-LEARN-004 | `CADEN_learning.md` | schema fields are never deleted; weak fields decay toward zero weight | pytest | covered | Covered by supplemental weak-field decay-without-delete test |
| SUP-LEARN-005 | `CADEN_learning.md` | proposal decisions are logged with full provenance | pytest | covered | Covered by supplemental schema decision provenance logging test |
| SUP-LEARN-006 | `CADEN_learning.md` | Sean vetoes schema growth before commitment | pytest | covered | Covered by supplemental veto-before-commit test |
| SUP-LEARN-007 | `CADEN_learning.md` | phase change is detected from residual stats and bias shifts | pytest | covered | Covered by supplemental phase-shift detection test |
| SUP-LEARN-008 | `CADEN_learning.md` | phase correction uses recency-weighted refits, never history rewrite | pytest | covered | Covered by supplemental recency-refit/no-history-rewrite test |
| SUP-LEARN-009 | `CADEN_learning.md` | old ratings stay immutable through adaptation | pytest | covered | Equivalent to `V0-023` and `V0-024` |
| SUP-LEARN-010 | `CADEN_learning.md` | retrieval weights are learned via Ridge-style residual fitting | pytest | covered | Equivalent to `V0-172` |
| SUP-LEARN-011 | `CADEN_learning.md` | active optimization ranks schedule options with Pareto logic | pytest | covered | Covered by supplemental Pareto optimization ranking test |
| SUP-LEARN-012 | `CADEN_learning.md` | Sean schedule selections are logged as learning events | pytest | covered | Covered by supplemental schedule-selection learning-event logging test |
| SUP-LEARN-013 | `CADEN_learning.md` | fixed weighted-sum objective is disallowed for 3-axis tradeoff | pytest | covered | Covered by supplemental non-single-objective Pareto tradeoff test |
| SUP-LEARN-014 | `CADEN_learning.md` | schema growth requires both persistent residual failure and weight plateau gates | pytest | covered | Covered by supplemental dual-gate schema-growth negative test |
| SUP-LEARN-015 | `CADEN_learning.md` | schema growth remains off when residual health is good even if plateau is present | pytest | covered | Covered by supplemental healthy-residual no-growth test |

### Libbie (supplemental)

| ID | Source | Requirement | Mode | Status | Evidence / Gap |
| --- | --- | --- | --- | --- | --- |
| SUP-LIBBIE-001 | `CADEN_libbie.md` | proactive memory surfacing on context shifts | pytest | covered | Covered by supplemental meaningful-change surface test |
| SUP-LIBBIE-002 | `CADEN_libbie.md` | SearXNG failures are surfaced loudly with no silent fallback | pytest | covered | Equivalent to `V0-260` failure policy plus `CMD-055` partial web path coverage |
| SUP-LIBBIE-003 | `CADEN_libbie.md` | Libbie is internal-only and not exposed as a dedicated GUI app/tab | pytest | covered | Covered by supplemental no-libbie-tab UI contract test |

### Project Manager (post-v0)

| ID | Source | Requirement | Mode | Status | Evidence / Gap |
| --- | --- | --- | --- | --- | --- |
| SUP-PM-001 | `CADEN_projectManager.md` | PM is a dedicated GUI tab | pytest | covered | Equivalent to `CMD-057` |
| SUP-PM-002 | `CADEN_projectManager.md` | project schema includes id/name/created_at/last_touched_at | pytest | covered | Covered by supplemental PM schema test |
| SUP-PM-003 | `CADEN_projectManager.md` | project list ordered by last_touched_at recency | pytest | covered | Covered by supplemental PM recency ordering test |
| SUP-PM-004 | `CADEN_projectManager.md` | projects are not deleted under no-deletion principle | pytest | covered | Covered by supplemental PM no-delete contract test |
| SUP-PM-005 | `CADEN_projectManager.md` | entry types are TODO/what-if/update/comment | pytest | covered | Equivalent to `CMD-060` |
| SUP-PM-006 | `CADEN_projectManager.md` | TODO entries create Google Tasks with metadata linkage | pytest | covered | Equivalent to `CMD-061` plus PM TODO tests |
| SUP-PM-007 | `CADEN_projectManager.md` | completion state uses shared Google Tasks completion path | pytest | covered | Equivalent to v0 completion path tests |
| SUP-PM-008 | `CADEN_projectManager.md` | what-if entries are retrieval-visible but do not emit predictions | pytest | covered | Covered by supplemental PM what-if retrieval/no-prediction contract test |
| SUP-PM-009 | `CADEN_projectManager.md` | cross-project related-entry strip appears in project view | pytest | covered | Covered by supplemental PM related-entry strip UI contract test |
| SUP-PM-010 | `CADEN_projectManager.md` | CADEN can propose projects from clustering pending Sean decision | pytest | covered | Covered by supplemental clustered project-proposal generation test |
| SUP-PM-011 | `CADEN_projectManager.md` | project entries are immutable; revisions append new rows | pytest | covered | Covered by supplemental PM append-only entry test |
| SUP-PM-012 | `CADEN_projectManager.md` | project identity remains stable across revisions for the same project name | pytest | covered | Covered by supplemental stable-project-id-across-revisions test |
| SUP-PM-013 | `CADEN_projectManager.md` | project manager does not create projects silently on mount/focus | pytest | covered | Covered by supplemental no-silent-project-creation-on-mount test |

### Sprocket (post-v0)

| ID | Source | Requirement | Mode | Status | Evidence / Gap |
| --- | --- | --- | --- | --- | --- |
| SUP-SPR-001 | `CADEN_sprocket.md` | Sprocket is separate tab with app list and chat workspace | pytest | covered | Equivalent to current Sprocket UI contract tests |
| SUP-SPR-002 | `CADEN_sprocket.md` | Sprocket chat history scope is separate from dashboard chat | pytest | covered | Covered by supplemental sprocket/dashboard scope-isolation test |
| SUP-SPR-003 | `CADEN_sprocket.md` | flow is Libbie brief first then Sprocket implementation planning | pytest | covered | Equivalent to Sprocket brief pipeline tests |
| SUP-SPR-004 | `CADEN_sprocket.md` | brief can include past builds/context/SearXNG when memory is thin | pytest | covered | Covered by supplemental sprocket thin-memory SearXNG brief enrichment test |
| SUP-SPR-005 | `CADEN_sprocket.md` | nearby successful examples use copy-and-tweak before scratch | pytest | covered | Covered by supplemental sprocket copy-first strategy test |
| SUP-SPR-006 | `CADEN_sprocket.md` | code memories store AST and textual form | pytest | covered | Covered by supplemental sprocket AST+text code memory storage test |
| SUP-SPR-007 | `CADEN_sprocket.md` | non-parsing code is rejected loudly and not stored | pytest | covered | Covered by supplemental sprocket parse-reject loud-failure test |
| SUP-SPR-008 | `CADEN_sprocket.md` | retrieval uses semantic plus structural AST pathways | pytest | covered | Covered by supplemental semantic+structural AST retrieval test |
| SUP-SPR-009 | `CADEN_sprocket.md` | execution uses restricted sandbox with no network by default | pytest | covered | Covered by supplemental restricted firejail --net=none sandbox command test |
| SUP-SPR-010 | `CADEN_sprocket.md` | timeout/attempt budget is learned, not fixed | pytest | covered | Covered by supplemental learned attempt-budget outcome-history test |
| SUP-SPR-011 | `CADEN_sprocket.md` | source quality is learned from outcomes with no allowlist | pytest | covered | Covered by supplemental learned source-quality scoring test |
| SUP-SPR-012 | `CADEN_sprocket.md` | abstraction templates emerge from successful clusters | pytest | covered | Covered by supplemental successful-cluster abstraction template derivation test |
| SUP-SPR-013 | `CADEN_sprocket.md` | successful builds can integrate as new CADEN tabs after review | pytest | covered | Covered by supplemental integration-proposal acceptance-after-review test |
| SUP-SPR-014 | `CADEN_sprocket.md` | accepted integration updates app registration and runs smoke gate | pytest | covered | Covered by supplemental integration smoke-gate acceptance test |
| SUP-SPR-015 | `CADEN_sprocket.md` | v1 guardrail forbids modifying existing CADEN code | pytest | covered | Covered by supplemental existing-code guardrail rejection test |
| SUP-SPR-016 | `CADEN_sprocket.md` | copy-and-tweak performs AST rewrite, not string substitution | pytest | covered | Covered by supplemental AST rewrite copy-and-tweak test |
| SUP-SPR-017 | `CADEN_sprocket.md` | Sprocket planning requests are Python-only and reject non-Python language asks loudly | pytest | covered | Covered by supplemental Python-only planning guardrail reject test |
| SUP-SPR-018 | `CADEN_sprocket.md` | Python planning requests remain accepted after Python-only guardrail | pytest | covered | Covered by supplemental Python-plan acceptance smoke test |

### Thought Dump (post-v0)

| ID | Source | Requirement | Mode | Status | Evidence / Gap |
| --- | --- | --- | --- | --- | --- |
| SUP-TD-001 | `CADEN_thougtDump.md` | Thought Dump is a dedicated tab | pytest | covered | Covered by supplemental Thought Dump tab registration test |
| SUP-TD-002 | `CADEN_thougtDump.md` | UI remains minimal text input with no counters/history/tags/prompts | pytest | covered | Covered by supplemental minimal Thought Dump UI contract test |
| SUP-TD-003 | `CADEN_thougtDump.md` | capture happens only on explicit commit | pytest | covered | Covered by supplemental explicit-commit-only capture test |
| SUP-TD-004 | `CADEN_thougtDump.md` | one commit creates one event; draft-loss on close is accepted | pytest | covered | Covered by supplemental one-commit-one-event test |
| SUP-TD-005 | `CADEN_thougtDump.md` | metadata includes source/trigger plus async why generation | pytest | covered | Covered by supplemental Thought Dump metadata + why-path test |
| SUP-TD-006 | `CADEN_thougtDump.md` | hide mode is visual-only cipher and tab-local | pytest | covered | Covered by supplemental hide-mode visual/tab-local behavior test |
| SUP-TD-007 | `CADEN_thougtDump.md` | hide mode never alters stored text and never blocks capture | pytest | covered | Covered by supplemental hide-mode non-mutating capture test |
| SUP-TD-008 | `CADEN_thougtDump.md` | thought-dump events are background-rated | pytest | covered | Covered by supplemental background rating path test |
| SUP-TD-009 | `CADEN_thougtDump.md` | thought-dump events are retrieval-first-class but not resurfaced in Thought Dump UI | pytest | covered | Covered by supplemental retrieval-first-class Thought Dump event test |
| SUP-TD-010 | `CADEN_thougtDump.md` | thought-dump content never auto-triggers SearXNG | pytest | covered | Covered by supplemental no-auto-searxng Thought Dump test |
| SUP-TD-011 | `CADEN_thougtDump.md` | hide mode resets on restart and launches visible | pytest | covered | Covered by supplemental restart-visible hide-default test |
| SUP-TD-012 | `CADEN_thougtDump.md` | hide render failure is loud | pytest | covered | Covered by supplemental Thought Dump hide-render loud-failure test |
| SUP-TD-013 | `CADEN_thougtDump.md` | failed commit preserves text as only clear-after-commit exception | pytest | covered | Covered by supplemental failed-commit text-preservation test |
| SUP-TD-014 | `CADEN_thougtDump.md` | Thought Dump commit path never triggers cloud API clients (calendar/tasks/web) | pytest | covered | Covered by supplemental no-cloud-client-calls-on-commit test |

## Current Verdict

This matrix now includes the full authoritative clause surface from
`CADEN.md` and `CADEN_v0.md`, including:
- active requirements
- duplicated restatements
- future-scope requirements
- manual-only clauses
- eval-only clauses
- explicitly excluded history/open-question sections

It is exhaustive as a **traceability document** for the current authoritative
specs.

It does **not** mean the test suite is exhaustive. The matrix itself shows
many clauses still marked `partial`, `uncovered`, `eval`, `manual`, or
`future`, which is exactly the point: the matrix is now complete enough to be
used as the backlog for closing the remaining alignment gaps.
