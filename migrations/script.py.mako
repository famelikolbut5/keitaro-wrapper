import sqlalchemy as sa
from alembic import op
${imports or ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade():
    ${upgrades or "pass"}


def downgrade():
    ${downgrades or "pass"}
