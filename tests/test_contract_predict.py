from datetime import datetime, timedelta, timezone

import pytest

from caden.errors import LLMError, SchedulerError
from caden.libbie.store import write_event, write_rating, write_task
from caden.scheduler.residual import compute_and_store
from caden.scheduler.predict import PredictionBundle, emit_prediction


class _LLM:
    def chat_stream(self, system, user, **kwargs):
        return "MESSY RAW PREDICTION OUTPUT", ""


class _Embedder:
    def embed(self, text: str):
        return [0.1] * 768


def test_prediction_routes_raw_llm_output_through_shared_repair_layer(db_conn, monkeypatch):
    captured: dict[str, object] = {}

    def _fake_parse(raw, model):
        captured["raw"] = raw
        captured["model"] = model
        return PredictionBundle.model_validate(
            {
                "predicted_duration_min": 60,
                "pre": {"mood": 0.1, "energy": 0.2, "productivity": 0.3},
                "post": {"mood": 0.2, "energy": 0.1, "productivity": 0.4},
                "confidence": {
                    "duration": 0.8,
                    "pre_mood": 0.5,
                    "pre_energy": 0.5,
                    "pre_productivity": 0.5,
                    "post_mood": 0.6,
                    "post_energy": 0.6,
                    "post_productivity": 0.6,
                },
                "rationale": "repair path used",
            }
        )

    monkeypatch.setattr(
        "caden.scheduler.predict.retrieve.recall_packets_for_query",
        lambda *args, **kwargs: (None, type("Ctx", (), {"recalled_memories": []})(), []),
    )
    monkeypatch.setattr(
        "caden.scheduler.predict.curate.package_recall_context",
        lambda task_text, recalled_memories: "(none)",
    )
    monkeypatch.setattr("caden.scheduler.predict.parse_and_validate", _fake_parse)

    task_id = write_task(
        db_conn,
        description="Predict this task",
        deadline_iso=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        google_task_id="g_pred_1",
        embedding=[0.1] * 768,
    )

    prediction_id = emit_prediction(
        db_conn,
        task_id=task_id,
        description="Predict this task",
        description_embedding=[0.1] * 768,
        planned_start_iso="2026-05-01T15:00:00+00:00",
        planned_end_iso="2026-05-01T16:00:00+00:00",
        google_event_id="evt_pred_1",
        llm=_LLM(),
        embedder=_Embedder(),
    )

    assert prediction_id is not None
    assert captured == {"raw": "MESSY RAW PREDICTION OUTPUT", "model": PredictionBundle}


def test_emit_prediction_persists_projected_short_horizon_trajectory(db_conn, monkeypatch):
    def _fake_parse(raw, model):
        return PredictionBundle.model_validate(
            {
                "predicted_duration_min": 75,
                "pre": {"mood": -0.1, "energy": 0.2, "productivity": 0.0},
                "post": {"mood": 0.3, "energy": -0.2, "productivity": 0.4},
                "confidence": {
                    "duration": 0.7,
                    "pre_mood": 0.5,
                    "pre_energy": 0.6,
                    "pre_productivity": 0.4,
                    "post_mood": 0.8,
                    "post_energy": 0.5,
                    "post_productivity": 0.7,
                },
                "rationale": "Sean usually needs a slow start but finishes with momentum.",
            }
        )

    monkeypatch.setattr(
        "caden.scheduler.predict.retrieve.recall_packets_for_query",
        lambda *args, **kwargs: (None, type("Ctx", (), {"recalled_memories": []})(), []),
    )
    monkeypatch.setattr(
        "caden.scheduler.predict.curate.package_recall_context",
        lambda task_text, recalled_memories: "(none)",
    )
    monkeypatch.setattr("caden.scheduler.predict.parse_and_validate", _fake_parse)

    task_id = write_task(
        db_conn,
        description="Ship the projected trajectory test",
        deadline_iso=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        google_task_id="g_pred_contract_1",
        embedding=[0.1] * 768,
    )

    prediction_id = emit_prediction(
        db_conn,
        task_id=task_id,
        description="Ship the projected trajectory test",
        description_embedding=[0.1] * 768,
        planned_start_iso="2026-05-01T15:00:00+00:00",
        planned_end_iso="2026-05-01T16:15:00+00:00",
        google_event_id="evt_pred_contract_1",
        llm=_LLM(),
        embedder=_Embedder(),
    )

    row = db_conn.execute(
        """
        SELECT google_event_id, pred_duration_min,
               pred_pre_mood, pred_pre_energy, pred_pre_productivity,
               pred_post_mood, pred_post_energy, pred_post_productivity,
               conf_duration,
               conf_pre_mood, conf_pre_energy, conf_pre_productivity,
               conf_post_mood, conf_post_energy, conf_post_productivity,
               rationale
        FROM predictions
        WHERE id=?
        """,
        (prediction_id,),
    ).fetchone()

    assert row is not None
    assert row["google_event_id"] == "evt_pred_contract_1"
    assert row["pred_duration_min"] == 75
    assert row["pred_pre_mood"] == pytest.approx(-0.1)
    assert row["pred_pre_energy"] == pytest.approx(0.2)
    assert row["pred_post_mood"] == pytest.approx(0.3)
    assert row["pred_post_productivity"] == pytest.approx(0.4)
    assert row["conf_duration"] == pytest.approx(0.7)
    assert row["conf_post_productivity"] == pytest.approx(0.7)
    assert "slow start" in row["rationale"]

    event_row = db_conn.execute(
        "SELECT raw_text, meta_json FROM events WHERE source='prediction' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert event_row is not None
    assert "duration=75min" in event_row["raw_text"]
    assert '"prediction_id":' in event_row["meta_json"]


def test_observe_step_uses_subsequent_events_as_ground_truth_against_prediction_bundle(db_conn, monkeypatch):
    def _fake_parse(raw, model):
        return PredictionBundle.model_validate(
            {
                "predicted_duration_min": 60,
                "pre": {"mood": 0.1, "energy": 0.0, "productivity": -0.2},
                "post": {"mood": 0.0, "energy": 0.1, "productivity": 0.2},
                "confidence": {
                    "duration": 0.8,
                    "pre_mood": 0.5,
                    "pre_energy": 0.5,
                    "pre_productivity": 0.5,
                    "post_mood": 0.6,
                    "post_energy": 0.6,
                    "post_productivity": 0.6,
                },
                "rationale": "Baseline prediction bundle.",
            }
        )

    monkeypatch.setattr(
        "caden.scheduler.predict.retrieve.recall_packets_for_query",
        lambda *args, **kwargs: (None, type("Ctx", (), {"recalled_memories": []})(), []),
    )
    monkeypatch.setattr(
        "caden.scheduler.predict.curate.package_recall_context",
        lambda task_text, recalled_memories: "(none)",
    )
    monkeypatch.setattr("caden.scheduler.predict.parse_and_validate", _fake_parse)

    task_id = write_task(
        db_conn,
        description="Observe against later events",
        deadline_iso=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        google_task_id="g_pred_contract_2",
        embedding=[0.1] * 768,
    )
    planned_start = datetime(2026, 5, 1, 15, 0, tzinfo=timezone.utc)
    actual_end = planned_start + timedelta(minutes=45)

    prediction_id = emit_prediction(
        db_conn,
        task_id=task_id,
        description="Observe against later events",
        description_embedding=[0.1] * 768,
        planned_start_iso=planned_start.isoformat(),
        planned_end_iso=(planned_start + timedelta(minutes=60)).isoformat(),
        google_event_id="evt_pred_contract_2",
        llm=_LLM(),
        embedder=_Embedder(),
    )

    pre_event_id = write_event(
        db_conn,
        "sean_chat",
        "pre boundary observation",
        [0.1] * 768,
        timestamp=(planned_start + timedelta(minutes=2)).isoformat(),
    )
    write_rating(
        db_conn,
        event_id=pre_event_id,
        mood=0.4,
        energy=0.3,
        productivity=0.0,
        c_mood=0.9,
        c_energy=0.9,
        c_productivity=0.9,
        rationale="observed just after the planned start",
        embedding=[0.1] * 768,
    )

    post_event_id = write_event(
        db_conn,
        "sean_chat",
        "post boundary observation",
        [0.1] * 768,
        timestamp=(actual_end - timedelta(minutes=1)).isoformat(),
    )
    write_rating(
        db_conn,
        event_id=post_event_id,
        mood=0.2,
        energy=-0.1,
        productivity=0.5,
        c_mood=0.9,
        c_energy=0.9,
        c_productivity=0.9,
        rationale="observed at the actual end",
        embedding=[0.1] * 768,
    )

    residual_id = compute_and_store(
        db_conn,
        prediction_id=prediction_id,
        planned_start_iso=planned_start.isoformat(),
        actual_end_iso=actual_end.isoformat(),
    )

    residual = db_conn.execute(
        """
        SELECT duration_actual_min, duration_residual_min,
               pre_state_residual_mood, pre_state_residual_energy, pre_state_residual_productivity,
               post_state_residual_mood, post_state_residual_energy, post_state_residual_productivity
        FROM residuals WHERE id=?
        """,
        (residual_id,),
    ).fetchone()

    assert residual is not None
    assert residual["duration_actual_min"] == 45
    assert residual["duration_residual_min"] == -15
    assert residual["pre_state_residual_mood"] == pytest.approx(0.3)
    assert residual["pre_state_residual_energy"] == pytest.approx(0.3)
    assert residual["pre_state_residual_productivity"] == pytest.approx(0.2)
    assert residual["post_state_residual_mood"] == pytest.approx(0.2)
    assert residual["post_state_residual_energy"] == pytest.approx(-0.2)
    assert residual["post_state_residual_productivity"] == pytest.approx(0.3)


def test_prediction_writes_low_and_null_confidences_without_flooring_or_defaults(db_conn, monkeypatch):
    def _fake_parse(raw, model):
        return PredictionBundle.model_validate(
            {
                "predicted_duration_min": 35,
                "pre": {"mood": None, "energy": 0.1, "productivity": None},
                "post": {"mood": 0.2, "energy": None, "productivity": 0.0},
                "confidence": {
                    "duration": 0.02,
                    "pre_mood": None,
                    "pre_energy": 0.01,
                    "pre_productivity": None,
                    "post_mood": 0.03,
                    "post_energy": None,
                    "post_productivity": 0.0,
                },
                "rationale": "Thin evidence, low confidence is still the honest answer.",
            }
        )

    monkeypatch.setattr(
        "caden.scheduler.predict.retrieve.recall_packets_for_query",
        lambda *args, **kwargs: (None, type("Ctx", (), {"recalled_memories": []})(), []),
    )
    monkeypatch.setattr(
        "caden.scheduler.predict.curate.package_recall_context",
        lambda task_text, recalled_memories: "(none)",
    )
    monkeypatch.setattr("caden.scheduler.predict.parse_and_validate", _fake_parse)

    task_id = write_task(
        db_conn,
        description="Preserve low confidences",
        deadline_iso=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        google_task_id="g_pred_contract_3",
        embedding=[0.1] * 768,
    )

    prediction_id = emit_prediction(
        db_conn,
        task_id=task_id,
        description="Preserve low confidences",
        description_embedding=[0.1] * 768,
        planned_start_iso="2026-05-01T09:00:00+00:00",
        planned_end_iso="2026-05-01T09:35:00+00:00",
        google_event_id="evt_pred_contract_3",
        llm=_LLM(),
        embedder=_Embedder(),
    )

    row = db_conn.execute(
        """
        SELECT conf_duration,
               conf_pre_mood, conf_pre_energy, conf_pre_productivity,
               conf_post_mood, conf_post_energy, conf_post_productivity
        FROM predictions
        WHERE id=?
        """,
        (prediction_id,),
    ).fetchone()

    assert row is not None
    assert row["conf_duration"] == pytest.approx(0.02)
    assert row["conf_pre_mood"] is None
    assert row["conf_pre_energy"] == pytest.approx(0.01)
    assert row["conf_pre_productivity"] is None
    assert row["conf_post_mood"] == pytest.approx(0.03)
    assert row["conf_post_energy"] is None
    assert row["conf_post_productivity"] == pytest.approx(0.0)


def test_prediction_prompt_keeps_full_description_without_char_cap(db_conn, monkeypatch):
    marker = "PREDICT-TAIL-DO-NOT-TRUNCATE"
    long_description = "p" * 5000 + marker
    captured: dict[str, str] = {}

    class _CapturingLLM:
        def chat_stream(self, system, user, **kwargs):
            captured["user"] = user
            return (
                '{"predicted_duration_min": 30, '
                '"pre": {"mood": null, "energy": null, "productivity": null}, '
                '"post": {"mood": null, "energy": null, "productivity": null}, '
                '"confidence": {"duration": null, "pre_mood": null, "pre_energy": null, "pre_productivity": null, "post_mood": null, "post_energy": null, "post_productivity": null}, '
                '"rationale": "thin evidence"}',
                "",
            )

    monkeypatch.setattr(
        "caden.scheduler.predict.retrieve.recall_packets_for_query",
        lambda *args, **kwargs: (None, type("Ctx", (), {"recalled_memories": []})(), []),
    )
    monkeypatch.setattr(
        "caden.scheduler.predict.curate.package_recall_context",
        lambda task_text, recalled_memories: "(none)",
    )

    task_id = write_task(
        db_conn,
        description=long_description,
        deadline_iso=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        google_task_id="g_pred_long_1",
        embedding=[0.1] * 768,
    )

    emit_prediction(
        db_conn,
        task_id=task_id,
        description=long_description,
        description_embedding=[0.1] * 768,
        planned_start_iso="2026-05-01T15:00:00+00:00",
        planned_end_iso="2026-05-01T16:00:00+00:00",
        google_event_id="evt_pred_long_1",
        llm=_CapturingLLM(),
        embedder=_Embedder(),
    )

    assert marker in captured["user"]


def test_prediction_llm_failure_is_loud_and_chains_original_error(db_conn, monkeypatch):
    monkeypatch.setattr(
        "caden.scheduler.predict.retrieve.recall_packets_for_query",
        lambda *args, **kwargs: (None, type("Ctx", (), {"recalled_memories": []})(), []),
    )
    monkeypatch.setattr(
        "caden.scheduler.predict.curate.package_recall_context",
        lambda task_text, recalled_memories: "(none)",
    )

    task_id = write_task(
        db_conn,
        description="failure chain check",
        deadline_iso=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        google_task_id="g_pred_chain_1",
        embedding=[0.1] * 768,
    )

    class _BoomLLM:
        def chat_stream(self, *args, **kwargs):
            raise LLMError("ollama down")

    with pytest.raises(SchedulerError, match="prediction LLM call failed: ollama down") as exc_info:
        emit_prediction(
            db_conn,
            task_id=task_id,
            description="failure chain check",
            description_embedding=[0.1] * 768,
            planned_start_iso="2026-05-01T15:00:00+00:00",
            planned_end_iso="2026-05-01T16:00:00+00:00",
            google_event_id="evt_pred_chain_1",
            llm=_BoomLLM(),
            embedder=_Embedder(),
        )
    assert isinstance(exc_info.value.__cause__, LLMError)


def test_predict_observe_correct_loop_links_prediction_to_residual_memory(db_conn, monkeypatch):
    def _fake_parse(raw, model):
        return PredictionBundle.model_validate(
            {
                "predicted_duration_min": 60,
                "pre": {"mood": 0.1, "energy": 0.2, "productivity": 0.3},
                "post": {"mood": 0.2, "energy": 0.3, "productivity": 0.4},
                "confidence": {
                    "duration": 0.6,
                    "pre_mood": 0.6,
                    "pre_energy": 0.6,
                    "pre_productivity": 0.6,
                    "post_mood": 0.6,
                    "post_energy": 0.6,
                    "post_productivity": 0.6,
                },
                "rationale": "predict-observe-correct loop contract",
            }
        )

    monkeypatch.setattr(
        "caden.scheduler.predict.retrieve.recall_packets_for_query",
        lambda *args, **kwargs: (None, type("Ctx", (), {"recalled_memories": []})(), []),
    )
    monkeypatch.setattr(
        "caden.scheduler.predict.curate.package_recall_context",
        lambda task_text, recalled_memories: "(none)",
    )
    monkeypatch.setattr("caden.scheduler.predict.parse_and_validate", _fake_parse)

    task_id = write_task(
        db_conn,
        description="loop contract task",
        deadline_iso=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        google_task_id="g_pred_loop_1",
        embedding=[0.1] * 768,
    )

    planned_start = datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc)
    actual_end = planned_start + timedelta(minutes=50)
    prediction_id = emit_prediction(
        db_conn,
        task_id=task_id,
        description="loop contract task",
        description_embedding=[0.1] * 768,
        planned_start_iso=planned_start.isoformat(),
        planned_end_iso=(planned_start + timedelta(minutes=60)).isoformat(),
        google_event_id="evt_pred_loop_1",
        llm=_LLM(),
        embedder=_Embedder(),
    )

    pre_event = write_event(
        db_conn,
        "sean_chat",
        "pre boundary",
        [0.1] * 768,
        timestamp=(planned_start + timedelta(minutes=1)).isoformat(),
    )
    write_rating(
        db_conn,
        event_id=pre_event,
        mood=0.3,
        energy=0.2,
        productivity=0.4,
        c_mood=0.9,
        c_energy=0.9,
        c_productivity=0.9,
        rationale="pre",
        embedding=[0.1] * 768,
    )

    post_event = write_event(
        db_conn,
        "sean_chat",
        "post boundary",
        [0.1] * 768,
        timestamp=(actual_end - timedelta(minutes=1)).isoformat(),
    )
    write_rating(
        db_conn,
        event_id=post_event,
        mood=0.1,
        energy=0.1,
        productivity=0.2,
        c_mood=0.9,
        c_energy=0.9,
        c_productivity=0.9,
        rationale="post",
        embedding=[0.1] * 768,
    )

    residual_id = compute_and_store(
        db_conn,
        prediction_id=prediction_id,
        planned_start_iso=planned_start.isoformat(),
        actual_end_iso=actual_end.isoformat(),
    )

    residual_row = db_conn.execute(
        "SELECT prediction_id FROM residuals WHERE id=?",
        (residual_id,),
    ).fetchone()
    mirrored = db_conn.execute(
        "SELECT meta_json FROM events WHERE source='residual' ORDER BY id DESC LIMIT 1",
    ).fetchone()

    assert residual_row is not None
    assert residual_row["prediction_id"] == prediction_id
    assert mirrored is not None
    assert f'"prediction_id": {prediction_id}' in mirrored["meta_json"]
