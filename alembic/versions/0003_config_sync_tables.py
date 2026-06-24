"""config documents/code-refs/sync-runs tables (Y-01).

ADDITIVE migration mirroring ``custodex.server.db``'s ``ConfigDocumentRow`` /
``ConfigCodeRefRow`` / ``SyncRunRow`` 1:1 — the "indexed columns + full JSON" hybrid
(K6): a portable JSON column (``JSONB`` on Postgres, JSON on SQLite via the SAME
``_json_type`` the models use) holding the FULL shared pydantic model, plus indexed
scalar columns for the Y-02 relationship/sync-state queries. ``upgrade`` creates the
three tables; ``downgrade`` drops them (the up/down round-trip is gate-tested on temp
SQLite).

Revision ID: 0003_config_sync
Revises: 0002_token_hash
Create Date: 2026-06-07

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from custodex.server.db import _json_type

# revision identifiers, used by Alembic.
revision: str = "0003_config_sync"
down_revision: str | None = "0002_token_hash"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "config_documents",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("repo_id", sa.String(), nullable=False),
        sa.Column("doc_id", sa.String(), nullable=False),
        sa.Column("sync_kind", sa.String(), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("audience", sa.String(), nullable=False),
        sa.Column("unit", sa.String(), nullable=True),
        sa.Column("ref", sa.String(), nullable=True),
        sa.Column("synced_at", sa.String(), nullable=False),
        sa.Column("document", _json_type(), nullable=False),
    )
    op.create_index("ix_config_documents_repo_id", "config_documents", ["repo_id"])
    op.create_index("ix_config_documents_doc_id", "config_documents", ["doc_id"])
    op.create_index("ix_config_documents_sync_kind", "config_documents", ["sync_kind"])

    op.create_table(
        "config_code_refs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("repo_id", sa.String(), nullable=False),
        sa.Column("doc_id", sa.String(), nullable=False),
        sa.Column("sync_kind", sa.String(), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("unit", sa.String(), nullable=True),
        sa.Column("code_ref", _json_type(), nullable=False),
    )
    op.create_index("ix_config_code_refs_repo_id", "config_code_refs", ["repo_id"])
    op.create_index("ix_config_code_refs_doc_id", "config_code_refs", ["doc_id"])
    op.create_index("ix_config_code_refs_sync_kind", "config_code_refs", ["sync_kind"])

    op.create_table(
        "sync_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("repo_id", sa.String(), nullable=False),
        sa.Column("sync_kind", sa.String(), nullable=False),
        sa.Column("ref", sa.String(), nullable=True),
        sa.Column("branch", sa.String(), nullable=True),
        sa.Column("head_commit", sa.String(), nullable=True),
        sa.Column("main_commit", sa.String(), nullable=True),
        sa.Column("commits_ahead", sa.Integer(), nullable=False),
        sa.Column("fully_synced", sa.Boolean(), nullable=False),
        sa.Column("run", _json_type(), nullable=False),
    )
    op.create_index("ix_sync_runs_repo_id", "sync_runs", ["repo_id"])
    op.create_index("ix_sync_runs_sync_kind", "sync_runs", ["sync_kind"])


def downgrade() -> None:
    op.drop_table("sync_runs")
    op.drop_table("config_code_refs")
    op.drop_table("config_documents")
