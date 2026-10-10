"""One library-wide embedding model: drop the per-paper override (ARA-091).

Papers that had an override now follow the library setting in `model_configurations`. Their
other-model indexes stay readable until startup reconciliation embeds the library model and
prunes them, so questions keep working through the change.

Revision ID: 0008_library_embeddings
"""

import sqlalchemy as sa

from alembic import op

revision = "0008_library_embeddings"
down_revision = "0007_feature_merge"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column("papers", "retrieval_profile")


def downgrade():
    op.add_column("papers", sa.Column("retrieval_profile", sa.String(40)))
