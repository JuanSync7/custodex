"""initial schema: repos, records, resolutions, coverage_snapshots (E-04).

Mirrors ``custodex.server.db`` 1:1 — the "indexed columns + full JSON"
hybrid (K6): a portable JSON column (``JSONB`` on Postgres, JSON on SQLite via the
SAME ``_json_type`` the models use) holding the FULL shared pydantic model, plus
indexed scalar columns for E-05 queries. ``upgrade`` creates the four tables;
``downgrade`` drops them (the up/down round-trip is gate-tested on temp SQLite).

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-05

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from custodex.server.db import _json_type

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "repos",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("repo_id", sa.String(), nullable=False),
        sa.Column("payload", _json_type(), nullable=False),
    )
    op.create_index("ix_repos_repo_id", "repos", ["repo_id"], unique=True)

    op.create_table(
        "records",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("repo_id", sa.String(), nullable=False),
        sa.Column("record_id", sa.String(), nullable=False),
        sa.Column("doc_id", sa.String(), nullable=False),
        sa.Column("verdict", sa.String(), nullable=False),
        sa.Column("drift_kind", sa.String(), nullable=False),
        sa.Column("audience", sa.String(), nullable=False),
        sa.Column("detected_at", sa.String(), nullable=False),
        sa.Column("source_sha", sa.String(), nullable=True),
        sa.Column("record", _json_type(), nullable=False),
    )
    op.create_index("ix_records_repo_id", "records", ["repo_id"])
    op.create_index("ix_records_record_id", "records", ["record_id"])
    op.create_index("ix_records_doc_id", "records", ["doc_id"])
    op.create_index("ix_records_verdict", "records", ["verdict"])
    op.create_index("ix_records_drift_kind", "records", ["drift_kind"])
    op.create_index("ix_records_audience", "records", ["audience"])
    op.create_index("ix_records_detected_at", "records", ["detected_at"])
    op.create_index("ix_records_source_sha", "records", ["source_sha"])

    op.create_table(
        "resolutions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("record_id", sa.String(), nullable=False),
        sa.Column("resolution", sa.String(), nullable=False),
        sa.Column("resolved_at", sa.String(), nullable=False),
        sa.Column("resolution_json", _json_type(), nullable=False),
    )
    op.create_index("ix_resolutions_record_id", "resolutions", ["record_id"])
    op.create_index("ix_resolutions_resolution", "resolutions", ["resolution"])
    op.create_index("ix_resolutions_resolved_at", "resolutions", ["resolved_at"])

    op.create_table(
        "coverage_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("repo_id", sa.String(), nullable=False),
        sa.Column("captured_at", sa.String(), nullable=False),
        sa.Column("snapshot", _json_type(), nullable=False),
    )
    op.create_index("ix_coverage_snapshots_repo_id", "coverage_snapshots", ["repo_id"])
    op.create_index(
        "ix_coverage_snapshots_captured_at", "coverage_snapshots", ["captured_at"]
    )


def downgrade() -> None:
    op.drop_table("coverage_snapshots")
    op.drop_table("resolutions")
    op.drop_table("records")
    op.drop_table("repos")
