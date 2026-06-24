"""config_edits pending-edit table (EDITOR E-03).

ADDITIVE migration mirroring ``custodex.server.db``'s ``ConfigEditRow`` 1:1 —
the "indexed columns + full JSON" hybrid (K6): a portable JSON column (``JSONB`` on
Postgres, JSON on SQLite via the SAME ``_json_type`` the model uses) holding the FULL
typed :class:`ConfigEdit` (the staged "mapping ticket"), plus indexed scalar columns
for the lifecycle queries (``repo_id``/``edit_id``/``status``). ``upgrade`` creates the
table; ``downgrade`` drops it (the up/down round-trip is gate-tested on temp SQLite).

Revision ID: 0004_config_edits
Revises: 0003_config_sync
Create Date: 2026-06-08

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from custodex.server.db import _json_type

# revision identifiers, used by Alembic.
revision: str = "0004_config_edits"
down_revision: str | None = "0003_config_sync"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "config_edits",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("repo_id", sa.String(), nullable=False),
        sa.Column("edit_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("applied_at", sa.String(), nullable=True),
        sa.Column("edit", _json_type(), nullable=False),
    )
    op.create_index("ix_config_edits_repo_id", "config_edits", ["repo_id"])
    op.create_index("ix_config_edits_edit_id", "config_edits", ["edit_id"])
    op.create_index("ix_config_edits_status", "config_edits", ["status"])


def downgrade() -> None:
    op.drop_table("config_edits")
