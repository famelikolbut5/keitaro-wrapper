import sqlalchemy as sa
from alembic import op

revision = "20261119_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stream_states",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=False),
        sa.Column("campaign_id", sa.Integer, nullable=False),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("schema", sa.String, nullable=False),
        sa.Column("published", sa.JSON, nullable=False),
        sa.Column("draft", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("conflict", sa.Boolean, nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
    )
    op.create_index("ix_stream_states_campaign_id", "stream_states", ["campaign_id"])


def downgrade() -> None:
    op.drop_index("ix_stream_states_campaign_id", table_name="stream_states")
    op.drop_table("stream_states")
