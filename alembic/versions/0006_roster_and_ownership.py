"""add the central roster table for ownership accountability (OWN-04).

ADDITIVE migration mirroring ``custodex.server.db.RosterRow`` 1:1 — the
central roster of identities (people / teams) the server cross-checks document
ownership against to flag departed-owner orphans. ``identity`` is the FULL
:class:`~custodex.ownership.Identity` JSON (the K6 source of truth, via the
SAME ``_json_type`` the model uses); ``name`` is the unique business key;
``kind``/``active`` are the indexed projection the orphan cascade reads.

The per-document ``owner``/``team``/``dri`` + the resolved ``accountable``/
``durable`` ride in the EXISTING ``config_documents`` JSON column (additive, K6 — NO
column migration; pre-OWN rows parse with ``None``), so this migration adds ONLY the
roster table. ``upgrade`` creates it; ``downgrade`` drops it (the up/down round-trip
is gate-tested on temp SQLite via the env's batch mode).

Revision ID: 0006_roster_and_ownership
Revises: 0005_provider_secret
Create Date: 2026-06-19

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from custodex.server.db import _json_type

# revision identifiers, used by Alembic.
revision: str = "0006_roster_and_ownership"
down_revision: str | None = "0005_provider_secret"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "roster",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("identity", _json_type(), nullable=False),
    )
    op.create_index("ix_roster_name", "roster", ["name"], unique=True)
    op.create_index("ix_roster_kind", "roster", ["kind"])
    op.create_index("ix_roster_active", "roster", ["active"])


def downgrade() -> None:
    op.drop_index("ix_roster_active", table_name="roster")
    op.drop_index("ix_roster_kind", table_name="roster")
    op.drop_index("ix_roster_name", table_name="roster")
    op.drop_table("roster")
