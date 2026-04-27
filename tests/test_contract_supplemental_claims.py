from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
from textual.widgets import Button, Input, Static, TabPane, TabbedContent

from caden.errors import CadenError, SprocketError, WebSearchError
from caden.libbie import capture, recall, search_web, surface_on_meaningful_change
from caden.learning.weights import fit_residual_ridge
from caden.learning.engine import (
    LearningSnapshot,
    SchemaProposal,
    apply_schema_proposal_if_approved,
    decay_weak_fields,
    detect_phase_shift,
    derive_retrieval_weights,
    evaluate_schema_proposal_on_history,
    log_schedule_selection,
    propose_schema_growth,
    propose_schema_growth_with_llm,
    record_schema_decision,
)
from caden.learning.optimize import (
    ScheduleCandidate,
    infer_preference_weights,
    pareto_frontier,
    rank_frontier_with_preferences,
)
from caden.google_sync.calendar import CalendarEvent
from caden.google_sync.tasks import GTask
from caden.libbie.store import link_task_event, write_prediction, write_residual, write_task
from caden.project_manager.service import ProjectManagerService
from caden.sprocket.service import SprocketService
from caden.ui.app import CadenApp
from caden.ui.chat import ChatWidget
from caden.ui.dashboard import Dashboard, SidePanel
from caden.ui.project_manager import ProjectManagerPane
from caden.ui.sprocket import SprocketPane
from caden.ui.thought_dump import ThoughtDumpPane
from textual.containers import VerticalScroll


class _Embedder:
    def embed(self, text: str):
        return [0.1] * 768


class _Tasks:
    def __init__(self) -> None:
        self.created: list[dict[str, str]] = []

    def create(self, title: str, due=None, notes: str = ""):
        self.created.append({"title": title, "notes": notes})
        return type("_Task", (), {"id": f"g_pm_{len(self.created)}"})()


class _SprocketLLM:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def chat(self, system: str, user: str, **kwargs) -> str:
        self.calls.append((system, user))
        return "1. Build\n2. Validate\n3. Report"


class _FailingSearxng:
    def search(self, query: str, *, limit: int = 5):
        raise WebSearchError("searxng request failed: timeout")


@pytest.mark.asyncio
async def test_sup_dash_001_dashboard_tab_remains_default_surface(mock_services):
    app = CadenApp(mock_services)

    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause(0.2)
        tabs = app.query_one(TabbedContent)
        pane_ids = {pane.id for pane in app.query(TabPane)}

    assert tabs.active == "dashboard"
    assert "dashboard" in pane_ids


@pytest.mark.asyncio
async def test_sup_dash_002_today_panel_shows_prediction_bundle_for_caden_scheduled_item(
    mock_services, monkeypatch
):
    monkeypatch.setattr(CadenApp, "_update_clock", lambda self: None)

    now = datetime.now(timezone.utc)
    start = now + timedelta(minutes=10)
    end = now + timedelta(minutes=50)

    task_id = write_task(
        mock_services.conn,
        description="Prepare architecture review",
        deadline_iso=(now + timedelta(days=1)).isoformat(),
        google_task_id="g_pred_bundle",
        embedding=[0.1] * 768,
    )
    link_task_event(
        mock_services.conn,
        task_id=task_id,
        google_event_id="evt_pred_bundle",
        planned_start_iso=start.isoformat(),
        planned_end_iso=end.isoformat(),
    )
    write_prediction(
        mock_services.conn,
        task_id=task_id,
        google_event_id="evt_pred_bundle",
        predicted_duration_min=45,
        pre=(0.10, 0.20, 0.30),
        post=(0.40, 0.50, 0.60),
        confidences={
            "duration": 0.80,
            "pre_mood": 0.70,
            "pre_energy": 0.71,
            "pre_productivity": 0.72,
            "post_mood": 0.73,
            "post_energy": 0.74,
            "post_productivity": 0.75,
        },
        rationale="contract test bundle",
        embedding=[0.1] * 768,
    )

    class _MockCalendar:
        def list_window(self, window_start, window_end):
            return [
                CalendarEvent(
                    id="evt_pred_bundle",
                    summary="Prepare architecture review",
                    start=start,
                    end=end,
                    raw={},
                )
            ]

    class _MockTasks:
        def list_open(self):
            return [
                GTask(
                    id="g_pred_bundle",
                    title="Prepare architecture review",
                    due=end,
                    status="needsAction",
                    completed_at=None,
                    raw={},
                )
            ]

    mock_services.calendar = _MockCalendar()
    mock_services.tasks = _MockTasks()

    app = CadenApp(mock_services)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.4)
        dashboard = app.query_one(Dashboard)
        today_panel = list(dashboard.query(SidePanel))[0]
        today_lines = [widget.render().plain for widget in today_panel.query("TaskItem Label")]

    assert any("pred dur=45m" in line for line in today_lines)
    assert any("pre=0.10/0.20/0.30" in line for line in today_lines)
    assert any("post=0.40/0.50/0.60" in line for line in today_lines)
    assert any("conf_dur=0.80" in line for line in today_lines)


@pytest.mark.asyncio
async def test_sup_dash_003_today_panel_shows_residual_bundle_after_completion(
    mock_services, monkeypatch
):
    monkeypatch.setattr(CadenApp, "_update_clock", lambda self: None)

    now = datetime.now(timezone.utc)
    start = now - timedelta(minutes=60)
    end = now - timedelta(minutes=10)

    task_id = write_task(
        mock_services.conn,
        description="Complete residual-visible task",
        deadline_iso=now.isoformat(),
        google_task_id="g_resid_bundle",
        embedding=[0.1] * 768,
    )
    link_task_event(
        mock_services.conn,
        task_id=task_id,
        google_event_id="evt_resid_bundle",
        planned_start_iso=start.isoformat(),
        planned_end_iso=end.isoformat(),
    )
    prediction_id = write_prediction(
        mock_services.conn,
        task_id=task_id,
        google_event_id="evt_resid_bundle",
        predicted_duration_min=35,
        pre=(0.10, 0.20, 0.30),
        post=(0.40, 0.50, 0.60),
        confidences={"duration": 0.80},
        rationale="contract residual bundle",
        embedding=[0.1] * 768,
    )
    write_residual(
        mock_services.conn,
        prediction_id=prediction_id,
        duration_actual_min=50,
        duration_residual_min=15,
        pre_residuals=(None, None, None),
        post_residuals=(0.10, -0.20, 0.00),
        embedding=[0.1] * 768,
    )
    mock_services.conn.execute(
        "UPDATE tasks SET status='complete', completed_at_utc=? WHERE id=?",
        (now.isoformat(), task_id),
    )
    mock_services.conn.execute(
        "UPDATE task_events SET actual_end=? WHERE task_id=?",
        (now.isoformat(), task_id),
    )
    mock_services.conn.commit()

    class _MockCalendar:
        def list_window(self, window_start, window_end):
            return [
                CalendarEvent(
                    id="evt_resid_bundle",
                    summary="Complete residual-visible task",
                    start=start,
                    end=end,
                    raw={},
                )
            ]

    class _MockTasks:
        def list_open(self):
            return []

    mock_services.calendar = _MockCalendar()
    mock_services.tasks = _MockTasks()

    app = CadenApp(mock_services)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.4)
        dashboard = app.query_one(Dashboard)
        today_panel = list(dashboard.query(SidePanel))[0]
        today_lines = [widget.render().plain for widget in today_panel.query("TaskItem Label")]

    assert any("resid dur=15m" in line for line in today_lines)
    assert any("post=0.10/-0.20/0.00" in line for line in today_lines)


@pytest.mark.asyncio
async def test_sup_dash_004_chat_exposes_recalled_memories_strip(mock_services, monkeypatch):
    monkeypatch.setattr(CadenApp, "_update_clock", lambda self: None)

    class _Ctx:
        recalled_memories = (
            type(
                "_Packet",
                (),
                {
                    "mem_id": "m1",
                    "summary": "Prior related memory surfaced",
                    "relevance": "high",
                    "reason": "semantic=0.90",
                },
            )(),
        )

    def _fake_recall(*args, **kwargs):
        return _Ctx(), _Ctx().recalled_memories

    monkeypatch.setattr("caden.ui.chat.recall", _fake_recall)

    app = CadenApp(mock_services)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        chat = app.query_one(ChatWidget)
        inp = chat.query_one("#chat-input", Input)
        inp.value = "show me memory context"
        await inp.action_submit()
        await pilot.pause(0.6)

        lines = [widget.render().plain for widget in app.query("#chat-log Static")]

    assert any("Prior related memory surfaced" in line for line in lines)


@pytest.mark.asyncio
async def test_sup_dash_006_week_panel_includes_trajectory_sparkline_for_predicted_items(
    mock_services, monkeypatch
):
    monkeypatch.setattr(CadenApp, "_update_clock", lambda self: None)
    now = datetime.now(timezone.utc)
    start = now + timedelta(days=1, minutes=10)
    end = start + timedelta(minutes=40)

    task_id = write_task(
        mock_services.conn,
        description="Sparkline candidate",
        deadline_iso=end.isoformat(),
        google_task_id="g_spark",
        embedding=[0.1] * 768,
    )
    link_task_event(
        mock_services.conn,
        task_id=task_id,
        google_event_id="evt_spark",
        planned_start_iso=start.isoformat(),
        planned_end_iso=end.isoformat(),
    )
    write_prediction(
        mock_services.conn,
        task_id=task_id,
        google_event_id="evt_spark",
        predicted_duration_min=40,
        pre=(0.0, 0.0, 0.0),
        post=(0.1, 0.5, -0.2),
        confidences={"duration": 0.8},
        rationale="sparkline",
        embedding=[0.1] * 768,
    )

    class _C:
        def list_window(self, ws, we):
            return [CalendarEvent(id="evt_spark", summary="Sparkline candidate", start=start, end=end, raw={})]

    class _T:
        def list_open(self):
            return [GTask(id="g_spark", title="Sparkline candidate", due=end, status="needsAction", completed_at=None, raw={})]

    mock_services.calendar = _C()
    mock_services.tasks = _T()
    app = CadenApp(mock_services)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.4)
        dashboard = app.query_one(Dashboard)
        week_panel = list(dashboard.query(SidePanel))[1]
        week_lines = [widget.render().plain for widget in week_panel.query("TaskItem Label")]

    assert any("trend:" in line for line in week_lines)


@pytest.mark.asyncio
async def test_sup_dash_012_residual_audit_overlay_is_transient_and_non_persistent(
    mock_services, monkeypatch
):
    monkeypatch.setattr(CadenApp, "_update_clock", lambda self: None)
    now = datetime.now(timezone.utc)
    start = now - timedelta(minutes=50)
    end = now - timedelta(minutes=10)
    task_id = write_task(
        mock_services.conn,
        description="Audit overlay task",
        deadline_iso=now.isoformat(),
        google_task_id="g_audit",
        embedding=[0.1] * 768,
    )
    link_task_event(
        mock_services.conn,
        task_id=task_id,
        google_event_id="evt_audit",
        planned_start_iso=start.isoformat(),
        planned_end_iso=end.isoformat(),
    )
    pred_id = write_prediction(
        mock_services.conn,
        task_id=task_id,
        google_event_id="evt_audit",
        predicted_duration_min=30,
        pre=(0.0, 0.0, 0.0),
        post=(0.0, 0.0, 0.0),
        confidences={"duration": 0.8},
        rationale="audit",
        embedding=[0.1] * 768,
    )
    write_residual(
        mock_services.conn,
        prediction_id=pred_id,
        duration_actual_min=40,
        duration_residual_min=10,
        pre_residuals=(None, None, None),
        post_residuals=(0.1, 0.0, -0.1),
        embedding=[0.1] * 768,
    )
    mock_services.conn.execute(
        "UPDATE tasks SET status='complete', completed_at_utc=? WHERE id=?",
        (now.isoformat(), task_id),
    )
    mock_services.conn.commit()

    class _C:
        def list_window(self, ws, we):
            return [CalendarEvent(id="evt_audit", summary="Audit overlay task", start=start, end=end, raw={})]

    class _T:
        def list_open(self):
            return []

    mock_services.calendar = _C()
    mock_services.tasks = _T()
    before_events = mock_services.conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]

    app = CadenApp(mock_services)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.4)
        audit_text = app.query_one("#residual-audit", Static).render().plain

    after_events = mock_services.conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]
    assert "audit:" in audit_text
    assert after_events == before_events


@pytest.mark.asyncio
async def test_sup_dash_013_drag_override_logs_preference_learning_event(mock_services, monkeypatch):
    monkeypatch.setattr(CadenApp, "_update_clock", lambda self: None)
    app = CadenApp(mock_services)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        dashboard = app.query_one(Dashboard)
        event_id = dashboard.record_drag_override(
            google_event_id="evt_drag",
            new_start_iso="2026-04-27T09:00:00+00:00",
            new_end_iso="2026-04-27T09:30:00+00:00",
        )
        await pilot.pause(0.1)

    row = mock_services.conn.execute(
        "SELECT source FROM events WHERE id=?",
        (event_id,),
    ).fetchone()
    assert row is not None
    assert row["source"] == "dashboard_drag_override"


@pytest.mark.asyncio
async def test_sup_dash_014_dashboard_keeps_three_panel_contract(mock_services):
    app = CadenApp(mock_services)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        dashboard = app.query_one(Dashboard)
        side_panels = list(dashboard.query(SidePanel))
        titles = [
            panel.query_one("#title", Static).render().plain
            for panel in side_panels
        ]
        chat_widgets = list(dashboard.query(ChatWidget))

    assert len(side_panels) == 2
    assert titles == ["Today", "Next 7 days"]
    assert len(chat_widgets) == 1


def test_sup_dash_005_inline_rating_correction_updates_prediction_and_logs_event(mock_services):
    now = datetime.now(timezone.utc)
    task_id = write_task(
        mock_services.conn,
        description="Inline correction task",
        deadline_iso=now.isoformat(),
        google_task_id="g_inline_corr",
        embedding=[0.1] * 768,
    )
    prediction_id = write_prediction(
        mock_services.conn,
        task_id=task_id,
        google_event_id="evt_inline_corr",
        predicted_duration_min=30,
        pre=(0.1, 0.2, 0.3),
        post=(0.4, 0.5, 0.6),
        confidences={"duration": 0.8},
        rationale="inline",
        embedding=[0.1] * 768,
    )
    dashboard = Dashboard(mock_services)
    event_id = dashboard.apply_inline_rating_correction(
        prediction_id=prediction_id,
        post=(0.8, 0.7, 0.6),
        reason="manual correction",
    )
    updated = mock_services.conn.execute(
        "SELECT pred_post_mood, pred_post_energy, pred_post_productivity FROM predictions WHERE id=?",
        (prediction_id,),
    ).fetchone()
    assert float(updated["pred_post_mood"]) == pytest.approx(0.8)
    assert float(updated["pred_post_energy"]) == pytest.approx(0.7)
    assert float(updated["pred_post_productivity"]) == pytest.approx(0.6)
    source = mock_services.conn.execute(
        "SELECT source FROM events WHERE id=?",
        (event_id,),
    ).fetchone()["source"]
    assert source == "dashboard_rating_correction"


def test_sup_dash_007_alternative_schedule_preview_is_renderable(mock_services):
    dashboard = Dashboard(mock_services)
    lines = dashboard.format_alternative_schedule_preview(
        [
            {"id": "opt-a", "mood": 0.7, "energy": 0.3, "productivity": 0.5, "pareto": True},
            {"id": "opt-b", "mood": 0.6, "energy": 0.6, "productivity": 0.4, "pareto": False},
        ]
    )
    assert len(lines) == 2
    assert "opt-a" in lines[0]
    assert "opt-b" in lines[1]


def test_sup_dash_008_schema_growth_consent_action_logs_dashboard_decision(mock_services):
    dashboard = Dashboard(mock_services)
    event_id = dashboard.record_schema_growth_decision_from_dashboard(
        pending_event_id=17,
        decision="accept",
        reason="looks safe",
    )
    row = mock_services.conn.execute(
        "SELECT source FROM events WHERE id=?",
        (event_id,),
    ).fetchone()
    assert row["source"] == "dashboard_schema_decision"


def test_sup_dash_009_phase_change_alert_text_includes_signal_summary(mock_services):
    dashboard = Dashboard(mock_services)
    alert = dashboard.phase_change_alert_text(direction="positive", pvalue=0.01, sample_count=14)
    assert "phase shift detected" in alert
    assert "direction=positive" in alert


def test_sup_dash_010_readiness_gate_requires_minimum_residual_history(mock_services):
    dashboard = Dashboard(mock_services)
    ready, reason = dashboard.optimization_readiness(min_residual_rows=2)
    assert ready is False
    assert "need >= 2 residual rows" in reason


def test_sup_dash_011_preview_surfaces_pareto_marker(mock_services):
    dashboard = Dashboard(mock_services)
    lines = dashboard.format_alternative_schedule_preview(
        [{"label": "frontier-candidate", "mood": 0.4, "energy": 0.8, "productivity": 0.5, "pareto": True}]
    )
    assert lines[0].startswith("[pareto]")


def test_sup_dash_015_invalid_schema_decision_is_rejected_loudly(mock_services):
    dashboard = Dashboard(mock_services)
    with pytest.raises(ValueError, match="decision must be accept or reject"):
        dashboard.record_schema_growth_decision_from_dashboard(
            pending_event_id=17,
            decision="maybe",
            reason="invalid action",
        )


def test_sup_dash_016_inline_correction_unknown_prediction_fails_loudly(mock_services):
    dashboard = Dashboard(mock_services)
    with pytest.raises(ValueError, match="unknown prediction_id"):
        dashboard.apply_inline_rating_correction(
            prediction_id=999999,
            post=(0.2, 0.2, 0.2),
            reason="invalid target",
        )


def test_sup_learn_009_ratings_stay_immutable_through_adaptation(db_conn):
    event_id = db_conn.execute(
        "INSERT INTO events (source, raw_text, meta_json, timestamp) VALUES ('sean_chat', 'immutable rating source', '{}', datetime('now'))"
    ).lastrowid
    db_conn.execute(
        "INSERT INTO ratings (event_id, mood, energy, productivity, conf_mood, conf_energy, conf_productivity, rationale, created_at) VALUES (?, 0.1, 0.2, 0.3, 0.7, 0.7, 0.7, 'first', datetime('now'))",
        (event_id,),
    )
    db_conn.execute(
        "INSERT INTO ratings (event_id, mood, energy, productivity, conf_mood, conf_energy, conf_productivity, rationale, created_at) VALUES (?, 0.4, 0.5, 0.6, 0.8, 0.8, 0.8, 'second', datetime('now'))",
        (event_id,),
    )
    db_conn.commit()

    rows = db_conn.execute(
        "SELECT mood, rationale FROM ratings WHERE event_id=? ORDER BY id",
        (event_id,),
    ).fetchall()

    assert len(rows) == 2
    assert rows[0]["mood"] == 0.1
    assert rows[0]["rationale"] == "first"
    assert rows[1]["mood"] == 0.4
    assert rows[1]["rationale"] == "second"


def test_sup_learn_010_retrieval_weights_use_ridge_style_fit():
    frame = pd.DataFrame(
        [
            {"x1": 0.0, "x2": 1.0, "target": 1.0},
            {"x1": 1.0, "x2": 0.0, "target": 2.0},
            {"x1": 2.0, "x2": 1.0, "target": 4.0},
            {"x1": 3.0, "x2": 1.0, "target": 6.0},
        ]
    )

    weights = fit_residual_ridge(frame, target="target", alpha=1.0)

    assert weights.feature_names == ("x1", "x2")
    assert len(weights.coefficients) == 2


def test_sup_learn_001_schema_growth_triggered_by_residual_failure_plus_plateau():
    snapshot = LearningSnapshot(
        lookback_days=30,
        row_count=20,
        mean_abs_duration_residual=35.0,
        mean_abs_state_residual=0.4,
        duration_trend=type("_Trend", (), {"tau": 0.4, "pvalue": 0.01, "trend": "increasing"})(),
    )
    proposal = propose_schema_growth(snapshot, weight_plateau=True)
    assert proposal is not None


def test_sup_learn_002_llm_schema_proposal_and_history_eval_path(db_conn):
    snapshot = LearningSnapshot(
        lookback_days=30,
        row_count=20,
        mean_abs_duration_residual=28.0,
        mean_abs_state_residual=0.3,
        duration_trend=type("_Trend", (), {"tau": 0.2, "pvalue": 0.03, "trend": "increasing"})(),
    )

    class _LLMJson:
        def chat_stream(self, *args, **kwargs):
            return ('{"field_name":"context_switch_load","rationale":"residual drift","confidence":0.71}', "")

    proposal = propose_schema_growth_with_llm(snapshot, llm=_LLMJson(), require_plateau=True)
    assert proposal is not None
    evaluation = evaluate_schema_proposal_on_history(db_conn, proposal)
    assert 0.0 <= evaluation.backfill_success_rate <= 1.0


def test_sup_learn_003_backfill_and_heldout_validation_on_accept(db_conn):
    from caden.libbie.store import write_event

    emb = _Embedder()
    proposal = SchemaProposal(field_name="focus_window", rationale="test", confidence=0.8)
    pending_id = write_event(
        db_conn,
        source="schema_growth_pending",
        raw_text="pending proposal",
        embedding=emb.embed("pending proposal"),
        meta={"field_name": "focus_window"},
        timestamp=None,
    )
    evaluation = type(
        "_Eval",
        (),
        {
            "backfill_success_rate": 0.9,
            "heldout_residual_before": 1.0,
            "heldout_residual_after": 0.8,
            "heldout_improvement": 0.2,
            "accepted": True,
        },
    )()
    event_ids = apply_schema_proposal_if_approved(
        db_conn,
        proposal=proposal,
        evaluation=evaluation,
        approved=True,
        embedder=emb,
        reason="looks good",
        pending_event_id=pending_id,
        backfill_rows=100,
    )
    assert event_ids


def test_sup_learn_004_field_decay_no_delete_behavior():
    decayed = decay_weak_fields({"a": 0.04, "b": 0.4}, weak_cutoff=0.08, decay_factor=0.5)
    assert "a" in decayed and "b" in decayed
    assert decayed["a"] == 0.02
    assert decayed["b"] == 0.4


def test_sup_learn_005_provenance_logged_for_schema_decisions(db_conn):
    emb = _Embedder()
    proposal = SchemaProposal(field_name="ctx", rationale="r", confidence=0.6)
    decision_id = record_schema_decision(
        db_conn,
        proposal=proposal,
        decision="reject",
        embedder=emb,
        reason="not now",
    )
    meta = {
        r["key"]: r["value"]
        for r in db_conn.execute(
            "SELECT key, value FROM event_metadata WHERE event_id=?",
            (decision_id,),
        ).fetchall()
    }
    assert meta["decision"] == "reject"
    assert meta["field_name"] == "ctx"


def test_sup_learn_006_veto_before_commit_prevents_activation(db_conn):
    from caden.libbie.store import write_event

    emb = _Embedder()
    proposal = SchemaProposal(field_name="veto_field", rationale="test", confidence=0.7)
    pending_id = write_event(
        db_conn,
        source="schema_growth_pending",
        raw_text="pending",
        embedding=emb.embed("pending"),
        meta={"field_name": "veto_field"},
        timestamp=None,
    )
    evaluation = type(
        "_Eval",
        (),
        {
            "backfill_success_rate": 0.95,
            "heldout_residual_before": 1.0,
            "heldout_residual_after": 0.7,
            "heldout_improvement": 0.3,
            "accepted": True,
        },
    )()
    ids = apply_schema_proposal_if_approved(
        db_conn,
        proposal=proposal,
        evaluation=evaluation,
        approved=False,
        embedder=emb,
        reason="veto",
        pending_event_id=pending_id,
        backfill_rows=50,
    )
    assert ids
    activated = db_conn.execute(
        "SELECT COUNT(*) AS n FROM events WHERE source='schema_growth_accept'"
    ).fetchone()["n"]
    assert activated == 0


def test_sup_learn_007_phase_change_detected_from_residual_stats(db_conn):
    task_id = write_task(
        db_conn,
        description="phase signal task",
        deadline_iso=datetime.now(timezone.utc).isoformat(),
        google_task_id="g_phase",
        embedding=[0.1] * 768,
    )
    prediction_id = write_prediction(
        db_conn,
        task_id=task_id,
        google_event_id="evt_phase",
        predicted_duration_min=30,
        pre=(0.0, 0.0, 0.0),
        post=(0.0, 0.0, 0.0),
        confidences={"duration": 0.8},
        rationale="phase",
        embedding=[0.1] * 768,
    )
    for delta in (20, 25, 30, 22, 24, 26, 28, 21, 23, 27, 29, 31, 19, 18, 17, 16, 15, 14, 13, 12):
        write_residual(
            db_conn,
            prediction_id=prediction_id,
            duration_actual_min=30 + delta,
            duration_residual_min=delta,
            pre_residuals=(None, None, None),
            post_residuals=(None, None, None),
            embedding=[0.1] * 768,
        )
    signal = detect_phase_shift(db_conn, lookback_days=30, min_samples=10)
    assert signal.sample_count >= 10


def test_sup_learn_008_recency_refit_adaptation_without_history_rewrite(db_conn):
    before = db_conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]
    _ = derive_retrieval_weights(db_conn, lookback_days=30, recency_bias=1.5)
    after = db_conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]
    assert after == before


def test_sup_learn_011_active_optimization_uses_pareto_ranking():
    candidates = [
        ScheduleCandidate(id="a", mood=0.6, energy=0.4, productivity=0.2),
        ScheduleCandidate(id="b", mood=0.5, energy=0.7, productivity=0.3),
        ScheduleCandidate(id="c", mood=0.2, energy=0.2, productivity=0.2),
    ]
    frontier = pareto_frontier(candidates)
    assert any(item.id == "a" for item in frontier)
    assert any(item.id == "b" for item in frontier)


def test_sup_learn_012_schedule_selection_logs_learning_event(db_conn):
    emb = _Embedder()
    selected = ScheduleCandidate(id="s1", mood=0.6, energy=0.7, productivity=0.8)
    rejected = [ScheduleCandidate(id="s2", mood=0.5, energy=0.6, productivity=0.7)]
    event_id = log_schedule_selection(
        db_conn,
        selected=selected,
        rejected=rejected,
        embedder=emb,
        rationale="best fit",
    )
    row = db_conn.execute("SELECT source FROM events WHERE id=?", (event_id,)).fetchone()
    assert row["source"] == "learning_preference"


def test_sup_learn_013_fixed_weighted_sum_not_used_as_sole_selector():
    options = [
        ScheduleCandidate(id="x", mood=0.9, energy=0.1, productivity=0.1),
        ScheduleCandidate(id="y", mood=0.1, energy=0.9, productivity=0.1),
    ]
    frontier = pareto_frontier(options)
    prefs = infer_preference_weights([(options[0], options[1])])
    ranked = rank_frontier_with_preferences(frontier, prefs)
    assert len(frontier) == 2
    assert ranked[0].id in {"x", "y"}


def test_sup_learn_014_schema_growth_requires_residual_failure_and_plateau():
    snapshot = LearningSnapshot(
        lookback_days=30,
        row_count=22,
        mean_abs_duration_residual=35.0,
        mean_abs_state_residual=0.35,
        duration_trend=type("_Trend", (), {"tau": 0.3, "pvalue": 0.02, "trend": "increasing"})(),
    )

    proposal = propose_schema_growth(snapshot, weight_plateau=False)
    assert proposal is None


def test_sup_learn_015_schema_growth_not_triggered_when_residual_health_is_good():
    snapshot = LearningSnapshot(
        lookback_days=30,
        row_count=22,
        mean_abs_duration_residual=8.0,
        mean_abs_state_residual=0.10,
        duration_trend=type("_Trend", (), {"tau": 0.0, "pvalue": 0.8, "trend": "no-trend"})(),
    )

    proposal = propose_schema_growth(snapshot, weight_plateau=True)
    assert proposal is None


def test_sup_libbie_001_proactive_surface_on_meaningful_context_change(db_conn):
    capture(
        db_conn,
        source="project_entry",
        raw_text="Project alpha: split scope into two milestones.",
        embedder=_Embedder(),
        meta={"trigger": "project_manager_submit"},
    )
    capture(
        db_conn,
        source="project_entry",
        raw_text="Project beta: gather stakeholder constraints first.",
        embedder=_Embedder(),
        meta={"trigger": "project_manager_submit"},
    )

    unchanged = surface_on_meaningful_change(
        db_conn,
        previous_context_text="currently planning project alpha",
        current_context_text="currently planning project alpha",
        embedder=_Embedder(),
        sources=("project_entry",),
        k=3,
        min_change_ratio=0.2,
    )
    changed = surface_on_meaningful_change(
        db_conn,
        previous_context_text="currently planning project alpha",
        current_context_text="currently planning project beta",
        embedder=_Embedder(),
        sources=("project_entry",),
        k=3,
        min_change_ratio=0.2,
    )

    assert unchanged == ()
    assert changed


def test_sup_libbie_002_searxng_failures_are_loud(db_conn):
    with pytest.raises(WebSearchError, match="timeout"):
        search_web(
            db_conn,
            "python dataclass defaults",
            searxng=_FailingSearxng(),
            embedder=_Embedder(),
            limit=2,
        )


@pytest.mark.asyncio
async def test_sup_libbie_003_libbie_is_internal_no_dedicated_ui_tab(mock_services):
    app = CadenApp(mock_services)

    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause(0.2)
        pane_ids = {pane.id for pane in app.query(TabPane)}

    assert "libbie" not in pane_ids


@pytest.mark.asyncio
async def test_sup_pm_001_project_manager_is_dedicated_tab(mock_services):
    app = CadenApp(mock_services)

    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause(0.2)
        pane_ids = {pane.id for pane in app.query(TabPane)}

    assert "project-manager" in pane_ids


@pytest.mark.asyncio
async def test_sup_pm_013_no_project_is_created_silently_on_mount(mock_services):
    before = mock_services.conn.execute(
        "SELECT COUNT(*) AS n FROM events WHERE source='project_entry'"
    ).fetchone()["n"]

    app = CadenApp(mock_services)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause(0.2)
        app.action_focus_project_manager()
        await pilot.pause(0.2)

    after = mock_services.conn.execute(
        "SELECT COUNT(*) AS n FROM events WHERE source='project_entry'"
    ).fetchone()["n"]
    assert after == before


def test_sup_pm_002_project_schema_includes_id_name_created_and_last_touched(db_conn):
    service = ProjectManagerService(db_conn, _Embedder())
    service.add_entry(project_name="Compiler Class", entry_type="comment", text="first")

    projects = service.list_projects()
    assert len(projects) == 1
    project = projects[0]

    assert project.project_id
    assert project.project_name == "Compiler Class"
    assert project.created_at
    assert project.last_touched_at


def test_sup_pm_003_projects_order_by_last_touched_recency(db_conn):
    service = ProjectManagerService(db_conn, _Embedder())
    alpha_first = service.add_entry(project_name="Alpha", entry_type="comment", text="a1")
    beta_first = service.add_entry(project_name="Beta", entry_type="comment", text="b1")
    alpha_second = service.add_entry(project_name="Alpha", entry_type="update", text="a2")

    db_conn.execute(
        "UPDATE events SET timestamp=? WHERE id=?",
        ("2025-01-01T12:00:00+00:00", alpha_first.event_id),
    )
    db_conn.execute(
        "UPDATE events SET timestamp=? WHERE id=?",
        ("2025-01-01T12:01:00+00:00", beta_first.event_id),
    )
    db_conn.execute(
        "UPDATE events SET timestamp=? WHERE id=?",
        ("2025-01-01T12:02:00+00:00", alpha_second.event_id),
    )
    db_conn.commit()

    projects = service.list_projects()

    assert [p.project_name for p in projects][:2] == ["Alpha", "Beta"]


def test_sup_pm_004_projects_not_deleted_under_no_deletion_principle(db_conn):
    service = ProjectManagerService(db_conn, _Embedder())
    service.add_entry(project_name="Dormant", entry_type="comment", text="old note")
    service.add_entry(project_name="Active", entry_type="comment", text="new note")

    projects = service.list_projects()
    names = {p.project_name for p in projects}

    assert "Dormant" in names
    assert "Active" in names
    assert not hasattr(service, "delete_project")


def test_sup_pm_005_entry_types_match_contract():
    assert ProjectManagerService.entry_types() == ("todo", "what_if", "update", "comment")


def test_sup_pm_006_todo_creates_google_task_with_linked_metadata(db_conn):
    tasks = _Tasks()
    service = ProjectManagerService(db_conn, _Embedder(), tasks_client=tasks)

    result = service.add_entry(
        project_name="Errands",
        entry_type="todo",
        text="Call the clinic\nAsk for earliest follow-up slot",
    )

    assert result.google_task_id == "g_pm_1"
    assert len(tasks.created) == 1
    assert tasks.created[0]["title"] == "Call the clinic"


@pytest.mark.asyncio
async def test_sup_pm_007_pm_todo_uses_shared_google_completion_route(mock_services, monkeypatch):
    class _TasksWithCompletion(_Tasks):
        def __init__(self) -> None:
            super().__init__()
            self.completed: list[str] = []

        def mark_completed(self, task_id: str):
            self.completed.append(task_id)

    tasks = _TasksWithCompletion()
    mock_services.tasks = tasks
    pm = ProjectManagerService(mock_services.conn, _Embedder(), tasks_client=tasks)
    todo = pm.add_entry(
        project_name="Shared Path",
        entry_type="todo",
        text="Finish shared completion flow",
    )

    called: list[str] = []

    async def _fake_to_thread(func, *args):
        called.append(getattr(func, "__name__", ""))
        if getattr(func, "__name__", "") == "poll_once":
            return []
        return func(*args)

    monkeypatch.setattr("caden.ui.dashboard.asyncio.to_thread", _fake_to_thread)

    app = CadenApp(mock_services)
    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause(0.2)
        dashboard = app.query_one(Dashboard)
        await dashboard._complete_task(todo.google_task_id or "")
        await pilot.pause(0.1)

    assert todo.google_task_id is not None
    assert tasks.completed == [todo.google_task_id]
    assert "poll_once" in called


def test_sup_pm_008_what_if_is_retrievable_without_predictions(db_conn):
    service = ProjectManagerService(db_conn, _Embedder())
    created = service.add_entry(
        project_name="Strategy",
        entry_type="what_if",
        text="What if we delay beta launch by one week?",
    )

    prediction_count = db_conn.execute(
        "SELECT COUNT(*) AS n FROM predictions"
    ).fetchone()["n"]
    assert prediction_count == 0

    _context, packets = recall(
        db_conn,
        "delay beta launch one week",
        embedder=_Embedder(),
        sources=("project_entry",),
        k=5,
    )

    assert packets
    assert any("what_if" in packet.summary.lower() for packet in packets)

    entry_type = db_conn.execute(
        "SELECT value FROM event_metadata WHERE event_id=? AND key='entry_type'",
        (created.event_id,),
    ).fetchone()["value"]
    assert entry_type == "what_if"


@pytest.mark.asyncio
async def test_sup_pm_009_cross_project_related_entry_strip_appears(mock_services, monkeypatch):
    monkeypatch.setattr(CadenApp, "_update_clock", lambda self: None)
    app = CadenApp(mock_services)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        app.action_focus_project_manager()
        await pilot.pause(0.2)

        pane = app.query_one(ProjectManagerPane)
        await pane._open_project("Alpha")
        await pane._refresh_projects()

        await asyncio.to_thread(
            pane._pm.add_entry,
            project_name="Alpha",
            entry_type="comment",
            text="Primary alpha thread",
        )
        await asyncio.to_thread(
            pane._pm.add_entry,
            project_name="Beta",
            entry_type="update",
            text="Cross-project related context",
        )

        await pane._refresh_projects()
        await pane._refresh_entries()
        await pane._refresh_related_entries()

        related = pane.query_one("#pm-related", VerticalScroll)
        related_lines = [widget.render().plain for widget in related.query(Static)]

    assert related is not None
    assert any("Beta:" in line for line in related_lines)


def test_sup_pm_011_project_entries_are_immutable_append_only(db_conn):
    service = ProjectManagerService(db_conn, _Embedder())
    first = service.add_entry(project_name="Immutable", entry_type="comment", text="v1")
    second = service.add_entry(project_name="Immutable", entry_type="comment", text="v2")

    rows = db_conn.execute(
        "SELECT id, raw_text FROM events WHERE source='project_entry' ORDER BY id"
    ).fetchall()

    ids = [row["id"] for row in rows if row["id"] in {first.event_id, second.event_id}]
    assert ids == [first.event_id, second.event_id]


def test_sup_pm_012_project_id_is_stable_across_revisions(db_conn):
    service = ProjectManagerService(db_conn, _Embedder())
    first = service.add_entry(project_name="Stable Project", entry_type="comment", text="v1")
    second = service.add_entry(project_name="Stable Project", entry_type="update", text="v2")

    assert first.project_id == second.project_id


@pytest.mark.asyncio
async def test_sup_spr_001_sprocket_is_dedicated_tab(mock_services):
    app = CadenApp(mock_services)

    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause(0.2)
        pane_ids = {pane.id for pane in app.query(TabPane)}

    assert "sprocket" in pane_ids


@pytest.mark.asyncio
async def test_sup_spr_002_sprocket_history_scope_is_separate_from_dashboard_chat(
    mock_services, monkeypatch
):
    monkeypatch.setattr(CadenApp, "_update_clock", lambda self: None)
    app = CadenApp(mock_services)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        app.action_focus_sprocket()
        await pilot.pause(0.1)
        sprocket = app.query_one(SprocketPane)

        async def _fake_run_plan(query: str) -> None:
            await sprocket._append_log(f"sean> {query}")
            await sprocket._append_log("plan> isolated")

        monkeypatch.setattr(sprocket, "_run_plan", _fake_run_plan)

        s_input = sprocket.query_one("#s-input", Input)
        s_input.value = "sprocket-only prompt"
        await s_input.action_submit()
        await pilot.pause(0.2)

        sprocket_logs = [widget.render().plain for widget in app.query("#s-log Static")]
        dashboard_chat_logs = [widget.render().plain for widget in app.query("#chat-log Static")]

    assert any("sean> sprocket-only prompt" in line for line in sprocket_logs)
    assert all("sprocket-only prompt" not in line for line in dashboard_chat_logs)


def test_sup_spr_003_sprocket_flow_brief_then_plan(db_conn, monkeypatch):
    llm = _SprocketLLM()
    service = SprocketService(db_conn, llm, _Embedder())

    call_order: list[str] = []

    def _fake_build_brief(self, query: str):
        call_order.append("build_brief")
        return type("_Brief", (), {"query": query, "memory_excerpt": "brief context"})()

    monkeypatch.setattr(SprocketService, "build_brief", _fake_build_brief)
    plan = service.propose_plan("Build a small PM analytics tab")

    assert "Build" in plan.plan_text
    assert call_order == ["build_brief"]
    assert len(llm.calls) == 1


def test_sup_spr_004_thin_memory_brief_includes_searxng_context(db_conn, monkeypatch):
    class _EmptyContext:
        recalled_memories = ()

    monkeypatch.setattr(
        "caden.sprocket.service.recall_packets_for_task",
        lambda conn, q, embedder, **kwargs: (None, _EmptyContext(), []),
    )

    class _Hit:
        def __init__(self, text: str) -> None:
            self._text = text

        def summary_text(self) -> str:
            return self._text

    class _Searxng:
        def search(self, query: str, limit: int = 3):
            return [
                _Hit("Relevant API guidance from docs"),
                _Hit("Similar implementation discussion"),
            ]

    service = SprocketService(db_conn, _SprocketLLM(), _Embedder(), searxng=_Searxng())
    brief = service.build_brief("Build a tiny parser helper")

    assert "web>" in brief.memory_excerpt
    assert "Relevant API guidance from docs" in brief.memory_excerpt


def test_sup_spr_005_prefers_copy_and_tweak_when_relevant_memory_exists(db_conn, monkeypatch):
    monkeypatch.setattr(
        SprocketService,
        "build_brief",
        lambda self, q: type(
            "_Brief",
            (),
            {
                "query": q,
                "memory_excerpt": "1. (high) Similar prior implementation exists",
            },
        )(),
    )

    llm = _SprocketLLM()
    service = SprocketService(db_conn, llm, _Embedder())
    _plan = service.propose_plan("Add a compact audit overlay")

    assert "copy_and_tweak" in llm.calls[0][1]

    row = db_conn.execute(
        "SELECT id FROM events WHERE source='sprocket_attempt' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row is not None
    metadata = {
        (r["key"], r["value"])
        for r in db_conn.execute(
            "SELECT key, value FROM event_metadata WHERE event_id=?",
            (row["id"],),
        ).fetchall()
    }
    assert ("approach", "copy_and_tweak") in metadata


def test_sup_spr_006_code_memory_stores_ast_and_text(db_conn):
    service = SprocketService(db_conn, _SprocketLLM(), _Embedder())
    code = "def add(a, b):\n    return a + b\n"

    event_id = service.store_code_memory(code_text=code, context="utility helper")

    row = db_conn.execute(
        "SELECT source, raw_text FROM events WHERE id=?",
        (event_id,),
    ).fetchone()
    assert row is not None
    assert row["source"] == "sprocket_code_memory"
    assert "def add(a, b)" in row["raw_text"]

    metadata = {
        r["key"]: r["value"]
        for r in db_conn.execute(
            "SELECT key, value FROM event_metadata WHERE event_id=?",
            (event_id,),
        ).fetchall()
    }
    assert metadata["format"] == "python_ast_plus_text"
    assert "FunctionDef" in metadata["ast"]


def test_sup_spr_007_non_parsing_code_is_rejected_loudly_and_not_stored(db_conn):
    service = SprocketService(db_conn, _SprocketLLM(), _Embedder())
    before = db_conn.execute(
        "SELECT COUNT(*) AS n FROM events WHERE source='sprocket_code_memory'"
    ).fetchone()["n"]

    with pytest.raises(SprocketError, match="sprocket code memory parse failed"):
        service.store_code_memory(code_text="def bad(:\n    pass")

    after = db_conn.execute(
        "SELECT COUNT(*) AS n FROM events WHERE source='sprocket_code_memory'"
    ).fetchone()["n"]
    assert after == before


def test_sup_spr_009_sandbox_execution_is_restricted_and_no_network(db_conn, monkeypatch):
    captured: dict[str, object] = {}

    class _Completed:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return _Completed()

    monkeypatch.setattr("caden.sprocket.service.subprocess.run", _fake_run)
    service = SprocketService(db_conn, _SprocketLLM(), _Embedder())
    code, out, err = service.run_in_sandbox(
        script_path="/tmp/sprocket_attempt.py",
        scratch_dir="/tmp/sprocket_scratch",
        timeout_seconds=12,
    )

    cmd = captured["cmd"]
    assert cmd[0] == "firejail"
    assert "--net=none" in cmd
    assert "--private=/tmp/sprocket_scratch" in cmd
    assert code == 0
    assert out == "ok"
    assert err == ""


def test_sup_spr_008_retrieval_combines_semantic_and_structural_ast(db_conn):
    service = SprocketService(db_conn, _SprocketLLM(), _Embedder())
    service.store_code_memory(
        code_text="def parse_item(x):\n    return x.strip()\n",
        context="parser",
    )
    service.store_code_memory(
        code_text="def sum_item(a, b):\n    return a + b\n",
        context="math",
    )

    ranked = service.retrieve_code_memories(
        query="parser helper",
        query_code="def parse_item(x):\n    return x.strip()\n",
        k=2,
    )

    assert ranked
    assert "structural_score" in ranked[0]
    assert ranked[0]["structural_score"] >= ranked[1]["structural_score"]


def test_sup_spr_010_and_011_learned_attempt_budget_and_source_quality(db_conn):
    service = SprocketService(db_conn, _SprocketLLM(), _Embedder())
    assert service.learned_attempt_budget() == 3

    service.record_attempt_outcome(
        source="docs.python.org",
        attempt_count=2,
        success=True,
        quality_score=0.9,
    )
    service.record_attempt_outcome(
        source="example.com",
        attempt_count=6,
        success=False,
        quality_score=0.2,
    )
    service.record_attempt_outcome(
        source="docs.python.org",
        attempt_count=4,
        success=True,
        quality_score=0.8,
    )

    budget = service.learned_attempt_budget()
    scores = service.source_quality_scores()

    assert budget == 4
    assert scores["docs.python.org"] > scores["example.com"]


def test_sup_spr_013_and_014_integration_after_review_and_smoke_gate(db_conn):
    service = SprocketService(db_conn, _SprocketLLM(), _Embedder())
    proposal_id = service.propose_integration(
        app_name="Focus Board",
        module_path="caden/ui/focus_board.py",
    )

    accepted_id = service.accept_integration(
        proposal_event_id=proposal_id,
        smoke_gate=lambda: True,
    )

    accepted = db_conn.execute(
        "SELECT source FROM events WHERE id=?",
        (accepted_id,),
    ).fetchone()
    assert accepted is not None
    assert accepted["source"] == "sprocket_integration_accepted"

    metadata = {
        (r["key"], r["value"])
        for r in db_conn.execute(
            "SELECT key, value FROM event_metadata WHERE event_id=?",
            (accepted_id,),
        ).fetchall()
    }
    assert ("smoke_gate", "passed") in metadata


def test_sup_spr_015_guardrail_forbids_modifying_existing_code(db_conn):
    service = SprocketService(db_conn, _SprocketLLM(), _Embedder())
    with pytest.raises(SprocketError, match="forbidden"):
        service.guardrail_validate_target(target_path="caden/ui/app.py")


def test_sup_spr_016_copy_and_tweak_uses_ast_rewrite(db_conn):
    service = SprocketService(db_conn, _SprocketLLM(), _Embedder())
    base = "def calc(x):\n    return x + 1\n"
    tweaked = service.ast_copy_and_tweak(
        base_code=base,
        function_name="calc",
        new_return_expr="x * 2",
    )

    assert "return x * 2" in tweaked
    tree = __import__("ast").parse(tweaked)
    fn = next(node for node in tree.body if isinstance(node, __import__("ast").FunctionDef))
    assert isinstance(fn.body[0], __import__("ast").Return)


def test_sup_spr_017_python_only_guardrail_rejects_non_python_language_requests(db_conn):
    service = SprocketService(db_conn, _SprocketLLM(), _Embedder())

    with pytest.raises(SprocketError, match="Python-only"):
        service.propose_plan("Build this in TypeScript with React")


def test_sup_spr_018_python_request_still_generates_plan(db_conn, monkeypatch):
    monkeypatch.setattr(
        SprocketService,
        "build_brief",
        lambda self, q: type(
            "_Brief",
            (),
            {
                "query": q,
                "memory_excerpt": "(no recalled memories)",
            },
        )(),
    )
    llm = _SprocketLLM()
    service = SprocketService(db_conn, llm, _Embedder())

    plan = service.propose_plan("Build a Python utility for parsing logs")

    assert "Build" in plan.plan_text


def test_sup_spr_019_sprocket_can_plan_and_execute_with_logged_outcome(db_conn, monkeypatch):
    service = SprocketService(db_conn, _SprocketLLM(), _Embedder())

    monkeypatch.setattr(
        service,
        "run_in_sandbox",
        lambda **kwargs: (0, "ok", ""),
    )

    plan, code, out, err = service.propose_and_execute(
        "Build a Python helper",
        script_path="/tmp/sprocket_attempt.py",
        scratch_dir="/tmp/sprocket_scratch",
        timeout_seconds=10,
    )

    assert "Build" in plan.plan_text
    assert code == 0
    assert out == "ok"
    assert err == ""

    row = db_conn.execute(
        "SELECT source FROM events WHERE source='sprocket_execution' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row is not None
    assert row["source"] == "sprocket_execution"


def test_sup_pm_010_can_propose_projects_from_clusters(db_conn):
    from caden.libbie.store import write_event

    emb = _Embedder()
    write_event(
        db_conn,
        "sean_chat",
        "compiler parser design keeps breaking at parser stage",
        emb.embed("compiler parser design keeps breaking at parser stage"),
        {},
        None,
    )
    write_event(
        db_conn,
        "sean_chat",
        "need compiler parser cleanup before lexer polish",
        emb.embed("need compiler parser cleanup before lexer polish"),
        {},
        None,
    )

    service = ProjectManagerService(db_conn, emb)
    proposals = service.propose_projects_from_clusters(limit=3)

    assert proposals
    assert any("compiler_parser" in proposal for proposal in proposals)


def test_sup_spr_012_abstraction_templates_emerge_from_successful_clusters(db_conn):
    service = SprocketService(db_conn, _SprocketLLM(), _Embedder())
    service.record_attempt_outcome(
        source="docs.python.org",
        attempt_count=2,
        success=True,
        quality_score=0.85,
    )
    service.record_attempt_outcome(
        source="docs.python.org",
        attempt_count=3,
        success=True,
        quality_score=0.91,
    )

    templates = service.derive_abstraction_templates(min_support=2)

    assert templates
    assert any("docs.python.org" in template for template in templates)


@pytest.mark.asyncio
async def test_sup_td_001_thought_dump_is_dedicated_tab(mock_services):
    app = CadenApp(mock_services)

    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause(0.2)
        pane_ids = {pane.id for pane in app.query(TabPane)}

    assert "thought-dump" in pane_ids


@pytest.mark.asyncio
async def test_sup_td_002_thought_dump_ui_is_minimal(mock_services):
    app = CadenApp(mock_services)

    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause(0.2)
        app.action_focus_thought_dump()
        await pilot.pause(0.2)
        pane = app.query_one(ThoughtDumpPane)

        assert pane.query_one("#td-input", Input) is not None
        assert pane.query_one("#td-commit", Button) is not None
        assert pane.query_one("#td-hide", Button) is not None
        assert pane.query_one("#td-preview", Static) is not None


@pytest.mark.asyncio
async def test_sup_td_003_and_004_capture_only_on_explicit_commit_one_commit_one_event(mock_services):
    app = CadenApp(mock_services)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        app.action_focus_thought_dump()
        await pilot.pause(0.2)
        pane = app.query_one(ThoughtDumpPane)
        inp = pane.query_one("#td-input", Input)
        inp.value = "first thought"
        await inp.action_submit()
        await pilot.pause(0.2)

        before = mock_services.conn.execute(
            "SELECT COUNT(*) AS n FROM events WHERE source='thought_dump'"
        ).fetchone()["n"]

        pane.query_one("#td-commit", Button).press()
        await pilot.pause(0.3)

        after = mock_services.conn.execute(
            "SELECT COUNT(*) AS n FROM events WHERE source='thought_dump'"
        ).fetchone()["n"]

    assert before == 0
    assert after == 1


@pytest.mark.asyncio
async def test_sup_td_005_metadata_and_async_why_path(mock_services, monkeypatch):
    called = {"why": 0}

    def _fake_why(conn, event_id, llm):
        called["why"] += 1
        return True

    monkeypatch.setattr("caden.ui.thought_dump.generate_why_for_event", _fake_why)
    app = CadenApp(mock_services)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        app.action_focus_thought_dump()
        await pilot.pause(0.2)
        pane = app.query_one(ThoughtDumpPane)
        inp = pane.query_one("#td-input", Input)
        inp.value = "metadata check thought"
        pane.query_one("#td-commit", Button).press()
        await pilot.pause(0.4)

    row = mock_services.conn.execute(
        "SELECT id, source, raw_text FROM events WHERE source='thought_dump' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row is not None
    assert row["source"] == "thought_dump"
    trigger = mock_services.conn.execute(
        "SELECT value FROM event_metadata WHERE event_id=? AND key='trigger' ORDER BY id DESC LIMIT 1",
        (row["id"],),
    ).fetchone()
    assert trigger is not None
    assert trigger["value"] == "thought_dump_commit"
    assert called["why"] >= 1


@pytest.mark.asyncio
async def test_sup_td_006_007_011_hide_mode_is_visual_only_tab_local_and_resets(mock_services):
    app = CadenApp(mock_services)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        app.action_focus_thought_dump()
        await pilot.pause(0.2)
        pane = app.query_one(ThoughtDumpPane)
        inp = pane.query_one("#td-input", Input)
        inp.value = "private text"
        pane.query_one("#td-hide", Button).press()
        await pilot.pause(0.2)

        preview_hidden = pane.query_one("#td-preview", Static).render().plain
        pane.query_one("#td-commit", Button).press()
        await pilot.pause(0.3)

        stored = mock_services.conn.execute(
            "SELECT raw_text FROM events WHERE source='thought_dump' ORDER BY id DESC LIMIT 1"
        ).fetchone()["raw_text"]

        app.action_focus_sprocket()
        await pilot.pause(0.1)
        assert app.query_one(SprocketPane) is not None

    assert "private text" not in preview_hidden
    assert stored == "private text"

    app2 = CadenApp(mock_services)
    async with app2.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        app2.action_focus_thought_dump()
        await pilot.pause(0.2)
        pane2 = app2.query_one(ThoughtDumpPane)
        assert pane2.query_one("#td-hide", Button).label.plain == "Hide: OFF"


@pytest.mark.asyncio
async def test_sup_td_008_background_rating_path_and_td_010_no_auto_searxng(mock_services, monkeypatch):
    called = {"rate": 0, "search": 0}

    def _fake_rate(*args, **kwargs):
        called["rate"] += 1
        return 1

    monkeypatch.setattr("caden.ui.thought_dump.rate_event", _fake_rate)

    class _S:
        def search(self, q, limit=5):
            called["search"] += 1
            return []

        def close(self):
            return None

    mock_services.searxng = _S()
    app = CadenApp(mock_services)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        app.action_focus_thought_dump()
        await pilot.pause(0.2)
        pane = app.query_one(ThoughtDumpPane)
        pane.query_one("#td-input", Input).value = "rate me but do not web-search"
        pane.query_one("#td-commit", Button).press()
        await pilot.pause(0.5)

    assert called["rate"] >= 1
    assert called["search"] == 0


def test_sup_td_009_retrieval_first_class_not_self_resurfaced(db_conn):
    emb = _Embedder()
    from caden.libbie.store import write_event

    write_event(
        db_conn,
        "thought_dump",
        "retrieval candidate thought",
        emb.embed("retrieval candidate thought"),
        {"trigger": "thought_dump_commit"},
        None,
    )
    _context, packets = recall(
        db_conn,
        "retrieval candidate",
        embedder=emb,
        sources=("thought_dump",),
        k=3,
    )
    assert packets


@pytest.mark.asyncio
async def test_sup_td_013_failed_commit_preserves_text(mock_services, monkeypatch):
    def _boom(*args, **kwargs):
        raise CadenError("simulated write failure")

    monkeypatch.setattr("caden.ui.thought_dump.write_event", _boom)
    app = CadenApp(mock_services)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        app.action_focus_thought_dump()
        await pilot.pause(0.2)
        pane = app.query_one(ThoughtDumpPane)
        inp = pane.query_one("#td-input", Input)
        inp.value = "must remain after failed commit"
        pane.query_one("#td-commit", Button).press()
        await pilot.pause(0.2)

        assert inp.value == "must remain after failed commit"


@pytest.mark.asyncio
async def test_sup_td_012_hide_render_failure_is_loud(mock_services, monkeypatch):
    notifications: list[tuple[str, str]] = []

    def _fake_notify(self, message, *, severity="information", **kwargs):
        notifications.append((message, severity))

    monkeypatch.setattr(CadenApp, "notify", _fake_notify)

    app = CadenApp(mock_services)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        app.action_focus_thought_dump()
        await pilot.pause(0.2)
        pane = app.query_one(ThoughtDumpPane)

        def _boom():
            raise RuntimeError("render boom")

        monkeypatch.setattr(pane, "_render_preview", _boom)
        pane.query_one("#td-hide", Button).press()
        await pilot.pause(0.2)

    assert any("thought-dump hide render failed" in msg for msg, _sev in notifications)


@pytest.mark.asyncio
async def test_sup_td_014_commit_never_calls_cloud_api_clients(mock_services, monkeypatch):
    called = {"calendar": 0, "tasks": 0, "search": 0}

    class _Calendar:
        def list_window(self, *args, **kwargs):
            called["calendar"] += 1
            return []

    class _TasksClient:
        def list_open(self):
            called["tasks"] += 1
            return []

    class _Searxng:
        def search(self, query: str, *, limit: int = 5):
            called["search"] += 1
            return []

        def close(self):
            return None

    mock_services.calendar = _Calendar()
    mock_services.tasks = _TasksClient()
    mock_services.searxng = _Searxng()

    async def _noop_refresh(self):
        return None

    monkeypatch.setattr(Dashboard, "refresh_panels", _noop_refresh)

    app = CadenApp(mock_services)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        app.action_focus_thought_dump()
        await pilot.pause(0.2)
        pane = app.query_one(ThoughtDumpPane)
        pane.query_one("#td-input", Input).value = "local only thought"
        pane.query_one("#td-commit", Button).press()
        await pilot.pause(0.4)

    assert called == {"calendar": 0, "tasks": 0, "search": 0}


def _pending_claim(claim_id: str, reason: str):
    return pytest.param(
        claim_id,
        reason,
        marks=pytest.mark.xfail(reason=reason, strict=False),
        id=claim_id,
    )


_PENDING_SUP_CLAIMS = [
]


@pytest.mark.parametrize(("claim_id", "reason"), _PENDING_SUP_CLAIMS)
def test_pending_supplemental_claims(claim_id: str, reason: str):
    pytest.xfail(reason)
