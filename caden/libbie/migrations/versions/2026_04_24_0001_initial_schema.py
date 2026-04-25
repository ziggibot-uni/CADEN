"""Initial spec schema

Revision ID: 0001
Revises: 
Create Date: 2026-04-24 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # We execute raw SQL queries to ensure exact match with spec and sqlite-vec
    op.execute(
        """
        CREATE TABLE events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT NOT NULL,
            source      TEXT NOT NULL,
            raw_text    TEXT NOT NULL,
            meta_json   TEXT NOT NULL DEFAULT '{}'
        );
        """)
    
    op.execute("""
        CREATE TABLE event_embeddings (
            event_id INTEGER PRIMARY KEY REFERENCES events(id) ON DELETE CASCADE,
            embedding BLOB NOT NULL
        );
        """
    )
    op.execute("CREATE INDEX events_source_ts ON events(source, timestamp);")
    op.execute("CREATE INDEX events_ts ON events(timestamp);")

    op.execute(
        """
        CREATE TABLE event_metadata (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    op.execute("CREATE INDEX event_metadata_event ON event_metadata(event_id);")

    # Ratings
    op.execute(
        """
        CREATE TABLE ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
            mood REAL,
            energy REAL,
            productivity REAL,
            conf_mood REAL,
            conf_energy REAL,
            conf_productivity REAL,
            rationale TEXT,
            created_at TEXT NOT NULL
        );
        """
    )
    op.execute("CREATE INDEX ratings_event ON ratings(event_id);")

    # Tasks
    op.execute(
        """
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            google_task_id TEXT,
            description TEXT NOT NULL,
            deadline_utc TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            completed_at_utc TEXT
        );
        """
    )

    # Task Events
    op.execute(
        """
        CREATE TABLE task_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            google_event_id TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            chunk_count INTEGER NOT NULL
        );
        """
    )
    op.execute("CREATE INDEX task_events_task ON task_events(task_id);")

    # Predictions
    op.execute(
        """
        CREATE TABLE predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            google_event_id TEXT,
            pred_duration_min INTEGER NOT NULL,
            pred_pre_mood REAL, pred_pre_energy REAL, pred_pre_productivity REAL,
            pred_post_mood REAL, pred_post_energy REAL, pred_post_productivity REAL,
            conf_pre_mood REAL, conf_pre_energy REAL, conf_pre_productivity REAL,
            conf_post_mood REAL, conf_post_energy REAL, conf_post_productivity REAL,
            conf_duration REAL,
            created_at TEXT NOT NULL
        );
        """
    )
    op.execute("CREATE INDEX predictions_task ON predictions(task_id);")

    # Residuals
    op.execute(
        """
        CREATE TABLE residuals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prediction_id INTEGER NOT NULL REFERENCES predictions(id) ON DELETE CASCADE,
            duration_actual_min INTEGER,
            duration_residual_min INTEGER,
            pre_state_residual_mood REAL, pre_state_residual_energy REAL, pre_state_residual_productivity REAL,
            post_state_residual_mood REAL, post_state_residual_energy REAL, post_state_residual_productivity REAL,
            created_at TEXT NOT NULL
        );
        """
    )
    op.execute("CREATE INDEX residuals_prediction ON residuals(prediction_id);")


def downgrade() -> None:
    pass

